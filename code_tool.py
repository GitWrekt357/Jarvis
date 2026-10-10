"""
Code-writing tool for Jarvis and Friday.

Haiku handles the conversation. When the speaker asks for real code, Haiku calls
write_code with a description of the job, and this module hands that job to a
stronger model (Sonnet by default) with a coding-focused prompt. The files it
returns are saved into the workspace folder only, never the live app, so the
manual copy-to-live step stays the safety gate.

Rules this module follows:
- It never executes generated code.
- It never overwrites a workspace file. If the target already exists, the new
  version is saved beside it as name.proposed.ext (then .proposed2, and so on).
- Paths go through workspace_tool's own path check, so nothing can escape the
  workspace folder.

Swap the model without editing code:  JARVIS_CODE_MODEL=claude-opus-5-5
"""
import os
import re

import workspace_tool as ws

CODE_MODEL = os.environ.get("JARVIS_CODE_MODEL", "claude-sonnet-5-5")
CODE_MAX_TOKENS = 16000
CODE_TIMEOUT = 300  # seconds

MAX_FILES = 8
MAX_CONTEXT_FILE_CHARS = 60000
MAX_CONTEXT_TOTAL_CHARS = 120000

_client = None


def _log(message):
    """Log to stdout. flush=True so the line reaches the journal right away,
    not whenever Python's output buffer fills."""
    print(f"[code_tool] {message}", flush=True)


def set_client(client):
    """Reuse the already-authenticated Anthropic client from the rest of Jarvis."""
    global _client
    _client = client


def _get_client():
    global _client
    if _client is None:
        import anthropic  # falls back to ANTHROPIC_API_KEY in the environment
        _client = anthropic.Anthropic()
    return _client


CODE_SYSTEM_PROMPT = (
    "You are a careful senior Python developer writing code for a personal home "
    "assistant project called Jarvis, which runs on Arch Linux. "
    "Always deliver complete, working files, never fragments or diffs. When you are "
    "given an existing file to change, return the entire updated file. "
    "Prefer the standard library. Never hard code API keys, passwords or tokens; "
    "read secrets from environment variables. Do not write code that deletes files, "
    "runs shell commands, or contacts the network unless the task explicitly needs it. "
    "Add short comments for anything that is not obvious. "
    "Your only way to answer is the save_files tool. Always finish by calling it exactly "
    "once, with every file, and never put code in a plain text reply. The summary field is read "
    "aloud by a voice assistant, so write one or two plain sentences with no code, "
    "no file contents, and no dashes."
)

_SAVE_FILES_TOOL = {
    "name": "save_files",
    "description": "Save the finished files and give a short spoken summary.",
    "input_schema": {
        "type": "object",
        "properties": {
            "files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path inside the workspace, e.g. 'rename_photos.py'.",
                        },
                        "content": {
                            "type": "string",
                            "description": "The complete contents of the file.",
                        },
                    },
                    "required": ["path", "content"],
                },
            },
            "summary": {
                "type": "string",
                "description": "One or two plain sentences saying what was written.",
            },
        },
        "required": ["files", "summary"],
    },
}


def _spoken(text):
    """Dashes make awkward pauses in text to speech, so swap them for commas."""
    text = re.sub(r"\s*[—–]\s*", ", ", text or "")
    return re.sub(r"\s+-\s+", ", ", text).strip()


def _read_context(paths):
    """Read workspace files in full (the normal read tool truncates at 8000 chars)."""
    chunks, total = [], 0
    for rel in paths:
        try:
            safe = ws.resolve_workspace_path(rel)
        except ValueError as e:
            return None, f"I could not read {rel}: {e}"
        if not os.path.isfile(safe):
            return None, f"I could not find {rel} in the workspace."
        with open(safe, "r", errors="replace") as f:
            text = f.read()
        if len(text) > MAX_CONTEXT_FILE_CHARS:
            return None, f"{rel} is too large to send along as context."
        total += len(text)
        if total > MAX_CONTEXT_TOTAL_CHARS:
            return None, "The context files together are too large to send."
        chunks.append(f'<file path="{rel}">\n{text}\n</file>')
    return "\n\n".join(chunks), None


def _free_path(rel):
    """Return (path, renamed). Never returns a path that already exists."""
    safe = ws.resolve_workspace_path(rel)  # raises ValueError if it escapes
    if not os.path.exists(safe):
        return rel, False
    stem, ext = os.path.splitext(rel)
    n = 1
    while True:
        tag = ".proposed" if n == 1 else f".proposed{n}"
        candidate = f"{stem}{tag}{ext}"
        if not os.path.exists(ws.resolve_workspace_path(candidate)):
            return candidate, True
        n += 1


def _call_model(messages):
    return _get_client().messages.create(
        model=CODE_MODEL,
        max_tokens=CODE_MAX_TOKENS,
        system=CODE_SYSTEM_PROMPT,
        tools=[_SAVE_FILES_TOOL],
        # "auto" on purpose: this model rejects tool_choice type "tool" or "any".
        tool_choice={"type": "auto"},
        messages=messages,
        timeout=CODE_TIMEOUT,
    )


def write_code(task, files=None, filename=None):
    if not task or not str(task).strip():
        return "Tell me what the code should do."

    context, err = _read_context(files or [])
    if err:
        return err

    parts = []
    if context:
        parts.append("Existing files for reference:\n\n" + context)
    parts.append("Task:\n" + str(task).strip())
    if filename:
        parts.append(f"Preferred name for the main file: {filename}")

    messages = [{"role": "user", "content": "\n\n".join(parts)}]
    block = None
    # The model rejects a forced tool_choice, so we ask for save_files in the prompt.
    # If it answers in plain text instead of calling the tool, nudge it once.
    for attempt in range(2):
        try:
            response = _call_model(messages)
        except Exception as e:
            _log(f"API call failed: model={CODE_MODEL} error={e!r}")
            reason = str(e)[:300]
            # The wording tells the chat model to report the failure, not quietly
            # write the code itself.
            return (f"I could not reach the coding model: {reason}. "
                    "Tell the speaker the code tool failed. Do not write the code yourself.")

        usage = getattr(response, "usage", None)
        _log(
            f"model={CODE_MODEL} stop_reason={response.stop_reason} "
            f"input_tokens={getattr(usage, 'input_tokens', '?')} "
            f"output_tokens={getattr(usage, 'output_tokens', '?')}"
        )

        if response.stop_reason == "max_tokens":
            return ("That job was too big to finish in one go, so nothing was saved. "
                    "Ask for one piece at a time.")

        block = next((b for b in response.content if b.type == "tool_use"), None)
        if block is not None or not response.content:
            break
        if attempt == 0:
            _log("no tool_use block, asking once more for save_files")
            messages = messages + [
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": "Call the save_files tool now with the finished files."},
            ]

    if block is None:
        _log("no tool_use block in the response")
        return ("The coding model did not return any files, so nothing was saved. "
                "Tell the speaker. Do not write the code yourself.")

    data = block.input or {}
    items = data.get("files") or []
    if not items:
        _log("tool_use block had no files")
        return ("The coding model did not return any files, so nothing was saved. "
                "Tell the speaker. Do not write the code yourself.")
    if len(items) > MAX_FILES:
        return (f"That would be {len(items)} files, which is more than I save at once. "
                "Ask for fewer pieces.")

    # Validate and plan every file before writing any, so a bad path saves nothing.
    plan = []
    for item in items:
        rel = re.sub(r"^(\./)+", "", (item.get("path") or "").strip())
        content = item.get("content")
        if not rel or rel.endswith("/") or not isinstance(content, str):
            return "The coding model returned a file I could not use, so nothing was saved."
        try:
            final, renamed = _free_path(rel)
        except ValueError:
            return f"The coding model tried to write outside the workspace ({rel}), so nothing was saved."
        plan.append((rel, final, renamed, content))

    saved, renamed_notes, failures = [], [], []
    for original, final, renamed, content in plan:
        result = ws.write_workspace_file(final, content)
        if str(result).startswith("Successfully"):
            saved.append(final)
            if renamed:
                renamed_notes.append(f"{original} already existed, so the new version is {final}")
        else:
            failures.append(f"{final}: {result}")

    if not saved:
        return "Nothing was saved. " + "; ".join(failures)

    message = "Saved " + ", ".join(saved) + " to the workspace."
    if renamed_notes:
        message += " " + "; ".join(renamed_notes) + "."
    if failures:
        message += " These failed: " + "; ".join(failures) + "."
    summary = _spoken(data.get("summary"))
    if summary:
        message += " " + summary
    return message


code_tool_schemas = [
    {
        "name": "write_code",
        "description": (
            "Use this for ANY request to write, build, fix or change code or scripts. "
            "It hands the job to a stronger coding model and saves the finished files in "
            "the workspace folder. Never read code aloud. Describe the task completely in "
            "the task field, including every requirement the speaker mentioned. To change "
            "an existing workspace file, list it in files so it is sent as context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "A complete description of what the code should do.",
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Workspace file paths to send as context or to modify.",
                },
                "filename": {
                    "type": "string",
                    "description": "Preferred name for the main file, e.g. 'rename_photos.py'.",
                },
            },
            "required": ["task"],
        },
    }
]

CODE_TOOL_NAMES = {s["name"] for s in code_tool_schemas}


def run_code_tool(name, args):
    if name == "write_code":
        return write_code(
            task=args.get("task"),
            files=args.get("files"),
            filename=args.get("filename"),
        )
    return f"Unknown code tool: {name}"
