# Copyright (c) 2026 GitWrekt357
# Licensed under the GNU Affero General Public License v3.0
import os
from datetime import datetime

WORKSPACE_DIR = os.path.realpath(os.path.expanduser("~/desktopjarvis/workspace"))

MAX_READ_CHARS = 8000


def resolve_workspace_path(relative_path: str) -> str:
    candidate = os.path.realpath(os.path.join(WORKSPACE_DIR, relative_path))
    if os.path.commonpath([WORKSPACE_DIR, candidate]) != WORKSPACE_DIR:
        raise ValueError(f"Path '{relative_path}' escapes the workspace directory.")
    return candidate


def list_workspace(relative_path: str = "") -> str:
    try:
        safe_path = resolve_workspace_path(relative_path)
    except ValueError as e:
        return f"Error: {e}"

    if not os.path.exists(safe_path):
        return f"'{relative_path or '.'}' does not exist in the workspace yet."
    if not os.path.isdir(safe_path):
        return f"Error: '{relative_path}' is not a directory."

    entries = []
    for name in sorted(os.listdir(safe_path)):
        full = os.path.join(safe_path, name)
        kind = "dir" if os.path.isdir(full) else "file"
        entries.append(f"{kind}: {name}")
    return "\n".join(entries) if entries else "(empty)"


def read_workspace_file(relative_path: str) -> str:
    try:
        safe_path = resolve_workspace_path(relative_path)
    except ValueError as e:
        return f"Error: {e}"

    if not os.path.isfile(safe_path):
        return f"Error: '{relative_path}' is not a file, or doesn't exist yet."

    with open(safe_path, "r", errors="replace") as f:
        content = f.read()

    if len(content) > MAX_READ_CHARS:
        content = content[:MAX_READ_CHARS] + "\n... (truncated)"
    return content


def write_workspace_file(relative_path: str, content: str, mode: str = "overwrite", backup_choice: str = None) -> str:
    try:
        safe_path = resolve_workspace_path(relative_path)
    except ValueError as e:
        return f"Error: {e}"

    os.makedirs(os.path.dirname(safe_path), exist_ok=True)

    file_exists_with_content = os.path.exists(safe_path) and os.path.getsize(safe_path) > 0
    backup_note = ""

    if file_exists_with_content:
        backup_path = safe_path + ".bak"

        if os.path.exists(backup_path) and backup_choice is None:
            backup_time = datetime.fromtimestamp(os.path.getmtime(backup_path)).strftime("%B %d, %Y at %I:%M %p")
            return (
                f"CONFIRMATION NEEDED: An existing backup of '{relative_path}' already exists, "
                f"created {backup_time}. Ask the user whether to overwrite this existing backup, "
                f"or keep it and create a separate, additionally timestamped backup instead. "
                f"Do not write the file yet. Once they answer, call write_workspace_file again "
                f"with the same relative_path and content, setting backup_choice to 'overwrite' "
                f"or 'secondary' based on their answer."
            )

        with open(safe_path, "r", errors="replace") as f:
            existing_content = f.read()

        if backup_choice == "secondary":
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            secondary_backup_path = f"{safe_path}.{timestamp}.bak"
            with open(secondary_backup_path, "w") as f:
                f.write(existing_content)
            backup_note = f" (existing backup kept; previous version also saved to '{os.path.basename(secondary_backup_path)}')"
        else:
            with open(backup_path, "w") as f:
                f.write(existing_content)
            backup_note = f" (previous version saved to '{os.path.basename(backup_path)}')"

    file_mode = "a" if mode == "append" else "w"
    with open(safe_path, file_mode) as f:
        if mode == "append" and file_exists_with_content:
            f.write("\n" + content)
        else:
            f.write(content)

    return f"Successfully {'appended to' if mode == 'append' else 'wrote'} '{relative_path}' in the workspace{backup_note}."


workspace_tool_schemas = [
    {
        "name": "list_workspace",
        "description": "List files and folders in Jarvis's coding workspace, a dedicated scratch directory for drafting and discussing scripts. Use an empty path for the top level.",
        "input_schema": {
            "type": "object",
            "properties": {
                "relative_path": {
                    "type": "string",
                    "description": "Subpath within the workspace to list. Empty string for the top level.",
                }
            },
        },
    },
    {
        "name": "read_workspace_file",
        "description": "Read a file from Jarvis's coding workspace, such as a reference copy of jarvis.py or a script being drafted.",
        "input_schema": {
            "type": "object",
            "properties": {
                "relative_path": {
                    "type": "string",
                    "description": "Path to the file within the workspace, e.g. 'jarvis_reference.py'.",
                }
            },
            "required": ["relative_path"],
        },
    },
    {
        "name": "write_workspace_file",
        "description": "Write or append content to a file in Jarvis's coding workspace -- for drafting Python scripts or notes for later manual review and testing. This never touches the live running program.",
        "input_schema": {
            "type": "object",
            "properties": {
                "relative_path": {
                    "type": "string",
                    "description": "Path to the file within the workspace to create or edit.",
                },
                "content": {
                    "type": "string",
                    "description": "The text or code to write.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["overwrite", "append"],
                    "description": "Overwrite the whole file or append to it. Default overwrite.",
                },
            },
            "required": ["relative_path", "content"],
        },
    },
]
