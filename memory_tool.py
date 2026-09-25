# Copyright (c) 2026 GitWrekt357
# Licensed under the GNU Affero General Public License v3.0
import os
import os
import re
from datetime import datetime, timedelta

USERS_DIR = os.path.expanduser("~/desktopjarvis/users")

SUMMARY_REGEN_INTERVAL_HOURS = 24
MAX_SOURCE_CHARS_FOR_SUMMARY = 15000
MAX_SEARCH_RESULT_CHARS = 4000

TIMESTAMP_PATTERN = re.compile(r"^\s*-\s*\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]")


def user_file_path(name: str) -> str:
    return os.path.join(USERS_DIR, f"{name.lower()}.md")


def summary_file_path(name: str) -> str:
    return os.path.join(USERS_DIR, f"{name.lower()}_summary.md")


def _read_summary_raw(name: str):
    path = summary_file_path(name)
    if not os.path.exists(path):
        return None, ""
    with open(path, "r") as f:
        content = f.read()

    match = re.match(r"^---\nlast_updated:\s*(.+?)\n---\n\n(.*)", content, re.DOTALL)
    if not match:
        return None, content.strip()

    timestamp_str, body = match.groups()
    try:
        last_updated = datetime.fromisoformat(timestamp_str.strip())
    except ValueError:
        last_updated = None
    return last_updated, body.strip()


def should_regenerate_summary(name: str) -> bool:
    last_updated, _ = _read_summary_raw(name)
    if last_updated is None:
        return os.path.exists(user_file_path(name))
    return datetime.now() - last_updated > timedelta(hours=SUMMARY_REGEN_INTERVAL_HOURS)


def load_summary_context(name: str) -> str:
    _, body = _read_summary_raw(name)
    return body


def _entries_since(name: str, since):
    path = user_file_path(name)
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        lines = f.readlines()

    matched = []
    for line in lines:
        m = TIMESTAMP_PATTERN.match(line)
        if not m:
            continue
        try:
            entry_time = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if since is None or entry_time > since:
            matched.append(line.rstrip())
    return matched


def load_recent_raw_context(name: str) -> str:
    last_updated, _ = _read_summary_raw(name)
    entries = _entries_since(name, last_updated)
    return "\n".join(entries)


def regenerate_summary(client, name: str) -> None:
    last_updated, existing_summary = _read_summary_raw(name)
    new_entries = _entries_since(name, last_updated)
    new_content = "\n".join(new_entries)

    if not existing_summary and not new_content:
        return

    if len(new_content) > MAX_SOURCE_CHARS_FOR_SUMMARY:
        new_content = new_content[-MAX_SOURCE_CHARS_FOR_SUMMARY:]

    prompt = (
        f"You maintain a compact, evolving summary of what's worth remembering about "
        f"{name} across past conversations, for a voice assistant to use as ongoing context.\n\n"
        f"Current summary (may be empty if this is the first time):\n{existing_summary or '(none yet)'}\n\n"
        f"New conversation notes since the summary was last updated:\n{new_content or '(none)'}\n\n"
        f"Produce an updated summary that integrates anything new and still relevant, drops "
        f"anything stale, and stays concise, a few short paragraphs, not an exhaustive log. "
        f"Focus on recurring themes, ongoing projects, communication style, and specific facts "
        f"worth retaining. Do not invent anything not actually present in the notes above."
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    new_summary = response.content[0].text.strip()

    with open(summary_file_path(name), "w") as f:
        f.write(f"---\nlast_updated: {datetime.now().isoformat()}\n---\n\n{new_summary}\n")


def search_conversation_history(name: str, query: str) -> str:
    path = user_file_path(name)
    if not os.path.exists(path):
        return "No conversation history exists for this user yet."

    with open(path, "r") as f:
        lines = f.readlines()

    ql = query.lower()
    matches = [line.rstrip() for line in lines if ql in line.lower()]

    if not matches:
        return f"Nothing found in the full conversation history matching '{query}'."

    result = "\n".join(matches)
    if len(result) > MAX_SEARCH_RESULT_CHARS:
        result = result[-MAX_SEARCH_RESULT_CHARS:]
    return result


search_conversation_history_schema = {
    "name": "search_conversation_history",
    "description": (
        "Search the user's full, original conversation history for a specific topic, when "
        "the standing summary doesn't have enough detail. Returns the actual matching "
        "conversation notes verbatim, not a paraphrase. Use this when the summary alludes "
        "to something but you need the real specifics to answer well."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keyword or phrase to search for in the user's past conversation notes.",
            }
        },
        "required": ["query"],
    },
}
