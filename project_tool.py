# Copyright (c) 2026 GitWrekt357
# Licensed under the GNU Affero General Public License v3.0
import os
import shutil

BASE_DIR = os.path.realpath(os.path.expanduser("~/desktopjarvis"))

BLOCKED_FILENAMES = {
    ".env",
    "household_voiceprints.json",
    "guest_voiceprints.json",
    "credentials.json",
    "token.json",
}

SKIP_DIR_NAMES = {"venv", "__pycache__", ".git"}

WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")

MAX_READ_CHARS = 8000


def resolve_project_path(relative_path: str) -> str:
    candidate = os.path.realpath(os.path.join(BASE_DIR, relative_path))
    if os.path.commonpath([BASE_DIR, candidate]) != BASE_DIR:
        raise ValueError(f"Path '{relative_path}' escapes the project directory.")

    parts = os.path.relpath(candidate, BASE_DIR).split(os.sep)
    if any(part in SKIP_DIR_NAMES for part in parts):
        raise ValueError(f"'{relative_path}' is inside an excluded directory.")
    if os.path.basename(candidate) in BLOCKED_FILENAMES:
        raise ValueError(f"'{os.path.basename(candidate)}' is not accessible through this tool.")

    return candidate


def list_project_directory(relative_path: str = "") -> str:
    try:
        safe_path = resolve_project_path(relative_path)
    except ValueError as e:
        return f"Error: {e}"

    if not os.path.isdir(safe_path):
        return f"Error: '{relative_path}' is not a directory."

    entries = []
    for name in sorted(os.listdir(safe_path)):
        if name in SKIP_DIR_NAMES or name in BLOCKED_FILENAMES:
            continue
        full = os.path.join(safe_path, name)
        kind = "dir" if os.path.isdir(full) else "file"
        entries.append(f"{kind}: {name}")
    return "\n".join(entries) if entries else "(empty directory)"


def read_project_file(relative_path: str) -> str:
    try:
        safe_path = resolve_project_path(relative_path)
    except ValueError as e:
        return f"Error: {e}"

    if not os.path.isfile(safe_path):
        return f"Error: '{relative_path}' is not a file, or doesn't exist."

    with open(safe_path, "r", errors="replace") as f:
        content = f.read()

    if len(content) > MAX_READ_CHARS:
        content = content[:MAX_READ_CHARS] + "\n... (truncated)"
    return content


def copy_to_workspace(relative_path: str) -> str:
    try:
        source_path = resolve_project_path(relative_path)
    except ValueError as e:
        return f"Error: {e}"

    if not os.path.isfile(source_path):
        return f"Error: '{relative_path}' is not a file, or doesn't exist."

    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    dest_name = os.path.basename(source_path)
    dest_path = os.path.join(WORKSPACE_DIR, dest_name)

    shutil.copy(source_path, dest_path)
    return f"Copied '{relative_path}' into the workspace as '{dest_name}'. The live original was not touched."


project_tool_schemas = [
    {
        "name": "list_project_directory",
        "description": (
            "List files and folders in Jarvis's actual live project directory (not the "
            "workspace sandbox). Use an empty path for the top level, or a subpath. "
            "Secrets and voice trust data are hidden from listings entirely."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "relative_path": {
                    "type": "string",
                    "description": "Subpath within the project directory to list. Empty string for the top level.",
                }
            },
        },
    },
    {
        "name": "read_project_file",
        "description": (
            "Read a file from Jarvis's actual live, current source code or project files "
            "(e.g. 'jarvis.py', 'music_tool.py', 'users/household.md'). Read-only -- cannot "
            "modify anything here, and cannot read secrets or voice trust data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "relative_path": {
                    "type": "string",
                    "description": "Path to the file, relative to the project root.",
                }
            },
            "required": ["relative_path"],
        },
    },
    {
        "name": "copy_to_workspace",
        "description": (
            "Copy a real, live project file into the workspace sandbox for hands-free "
            "testing or editing, without ever touching or affecting the live running "
            "program. One-way only: core to workspace, never the reverse. Cannot copy "
            "secrets or voice trust data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "relative_path": {
                    "type": "string",
                    "description": "Path to the file to copy, relative to the project root, e.g. 'jarvis.py'.",
                }
            },
            "required": ["relative_path"],
        },
    },
]
