"""
Shared brain for Jarvis (desktop) and Friday (phone).

Everything that isn't audio lives here: prompts, memory files, knowledge
triggers, tools, and the Claude call. jarvis.py (microphone + speakers) and
server.py (the phone bridge) both import this, so there is exactly one brain.
"""
import os
import re
import json
import time
from datetime import datetime

from workspace_tool import list_workspace, read_workspace_file, write_workspace_file, workspace_tool_schemas
from music_tool import shuffle_music, stop_music, music_tool_schema, stop_music_schema
from project_tool import list_project_directory, read_project_file, copy_to_workspace, project_tool_schemas
from memory_tool import (
    should_regenerate_summary, regenerate_summary, load_summary_context,
    load_recent_raw_context, search_conversation_history, search_conversation_history_schema,
)
from calendar_tool import get_upcoming_events, calendar_tool_schema

MODEL = "claude-haiku-4-5-20251001"
# Spoken replies stay short because the system prompt asks for that, not because
# of this cap. The cap has to be big enough for a whole file inside a tool call.
MAX_TOKENS = 8192
MAX_TOOL_ROUNDS = 4

# Spoken when a turn fails. These get read aloud, so no dashes.
TRUNCATED_REPLY = (
    "That was too big for me to write in one go, so nothing was saved. "
    "Try asking for one piece at a time, like just the database part first."
)
ROUND_CAP_REPLY = (
    "I ran out of steps before I finished that. "
    "Anything I already saved is still in the workspace. Try asking for a smaller piece."
)
EMPTY_REPLY = "Sorry, I lost my train of thought there. Could you ask again?"

HOUSE_KNOWLEDGE_TRIGGER = "house knowledge"
GENERAL_KNOWLEDGE_TRIGGER = "general knowledge"

USERS_DIR = os.path.expanduser("~/desktopjarvis/users")
HOUSEHOLD_FILE = os.path.join(USERS_DIR, "household.md")
GENERAL_KNOWLEDGE_FILE = os.path.join(USERS_DIR, "general_knowledge.md")
GUESTS_DIR = os.path.expanduser("~/desktopjarvis/guests")

MAX_CONTEXT_CHARS = 3000

SET_ALARM_TOOL = {
    "name": "set_alarm",
    "description": "Set an alarm on Josh's phone. Only works from the phone.",
    "input_schema": {
        "type": "object",
        "properties": {
            "hour": {"type": "integer", "description": "24-hour format, 0-23"},
            "minute": {"type": "integer"},
            "label": {"type": "string"},
        },
        "required": ["hour", "minute"],
    },
}

SET_TIMER_TOOL = {
    "name": "set_timer",
    "description": "Set a countdown timer on Josh's phone. Only works from the phone.",
    "input_schema": {
        "type": "object",
        "properties": {
            "seconds": {"type": "integer"},
            "label": {"type": "string"},
        },
        "required": ["seconds"],
    },
}

PHONE_ONLY_TOOLS = {"set_alarm", "set_timer"}

AVAILABLE_TOOLS = (
    [calendar_tool_schema]
    + workspace_tool_schemas
    + [music_tool_schema, stop_music_schema]
    + project_tool_schemas
    + [search_conversation_history_schema]
    + [SET_ALARM_TOOL, SET_TIMER_TOOL]
)

# Music plays on the laptop's speakers, so it makes no sense from the phone.
DESKTOP_ONLY_TOOLS = {"shuffle_music", "stop_music"}

BASE_SYSTEM_PROMPT = (
    "You are Jarvis, a refined British butler and desktop voice assistant. "
    "Speak concisely, clearly, and naturally. Keep responses short and conversational "
    "since they will be read aloud, not read as text. "
    "Do not use em dashes, en dashes, or hyphens as punctuation for pauses or asides, "
    "use commas or periods instead, since dashes do not produce a natural spoken pause "
    "when converted to speech."
)

FRIDAY_SYSTEM_PROMPT = (
    "You are Friday, a warmer and quicker-witted voice than Jarvis. You are the mobile "
    "side of the same assistant system, sharing his memory, tools, and workspace folder. "
    "Speak concisely and naturally for text-to-speech. Do not use em dashes or en dashes "
    "for pauses; use commas or periods instead. "
    "When asked to build or write code, never speak the code aloud. Save it to the "
    "workspace with write_workspace_file, one file at a time, starting with the most "
    "important file. Then reply with one or two short sentences saying what you wrote "
    "and where. For a large project, write one piece per request and tell the speaker "
    "what the next piece would be."
)

PERSONAS = {
    "jarvis": {"voice": "jarvis", "system_prompt": BASE_SYSTEM_PROMPT},
    "friday": {"voice": "friday", "system_prompt": FRIDAY_SYSTEM_PROMPT},
}

DEVICE_NOTES = {
    "desktop": "",
    "phone": (
        "\n\nThe speaker is talking to you through the Friday app on their phone, "
        "probably away from the home computer. Music playback isn't available from "
        "the phone, since it would play on the home computer's speakers."
    ),
}


# ---------- files ----------

def ensure_dirs():
    os.makedirs(USERS_DIR, exist_ok=True)
    os.makedirs(GUESTS_DIR, exist_ok=True)
    if not os.path.exists(HOUSEHOLD_FILE):
        with open(HOUSEHOLD_FILE, "w") as f:
            f.write("# Household Knowledge\n\n")
    if not os.path.exists(GENERAL_KNOWLEDGE_FILE):
        with open(GENERAL_KNOWLEDGE_FILE, "w") as f:
            f.write("# General Knowledge (shared with guests)\n\n")


def load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def save_json(path: str, data: dict):
    with open(path, "w") as f:
        json.dump(data, f)


def trusted_file_path(name: str) -> str:
    return os.path.join(USERS_DIR, f"{name.lower()}.md")


def guest_file_path(name: str) -> str:
    return os.path.join(GUESTS_DIR, f"guest_{name.lower()}.md")


def append_to_file(path: str, text: str):
    if not text.strip():
        return
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(f"# Notes for {os.path.basename(path).replace('.md', '').title()}\n\n")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(path, "a") as f:
        f.write(f"- [{timestamp}] {text.strip()}\n")


def _read_capped(path: str) -> str:
    with open(path, "r") as f:
        content = f.read()
    return content[-MAX_CONTEXT_CHARS:] if len(content) > MAX_CONTEXT_CHARS else content


def load_context_for(name: str, tier: str) -> str:
    parts = []
    if tier == "household":
        summary_text = load_summary_context(name)
        if summary_text:
            parts.append(f"Summary of prior conversations with {name}:\n{summary_text}")
        recent_raw = load_recent_raw_context(name)
        if recent_raw:
            parts.append(f"Notes from very recent conversations (since the last summary):\n{recent_raw}")
        paths = (HOUSEHOLD_FILE, GENERAL_KNOWLEDGE_FILE)
    else:
        paths = (guest_file_path(name), GENERAL_KNOWLEDGE_FILE)
    for path in paths:
        if os.path.exists(path):
            parts.append(_read_capped(path))
    return "\n\n".join(parts)


def build_persona_system_prompt(persona_key: str, speaker_name: str, tier: str, context_text: str) -> str:
    prompt = PERSONAS[persona_key]["system_prompt"] + (
        f"\n\nA voice-recognition pipeline has already identified the current speaker as "
        f"'{speaker_name}' ({tier} tier), before this conversation reached you. "
        f"Do not guess, question, or substitute a different name for them."
    )
    if context_text.strip():
        prompt += (
            f"\n\nHere is background you remember about {speaker_name}:\n"
            f"{context_text}\n\n"
            "Use this naturally if it's relevant, but don't recite it verbatim unless asked."
        )
    return prompt


# ---------- tools ----------

def tools_for(device: str) -> list:
    if device == "desktop":
        return [t for t in AVAILABLE_TOOLS if t.get("name") not in PHONE_ONLY_TOOLS]
    return [t for t in AVAILABLE_TOOLS if t.get("name") not in DESKTOP_ONLY_TOOLS]


def run_tool(name: str, args: dict, speaker_name: str, tier: str, device: str, pending_actions: list):
    if name in DESKTOP_ONLY_TOOLS and device != "desktop":
        return "That tool only works from the desktop."
    if name in PHONE_ONLY_TOOLS:
        if device != "phone":
            return "That tool only works from the phone."
        pending_actions.append({"type": name, **args})
        return "Queued on the phone."
    if name == "get_upcoming_events":
        return get_upcoming_events(
            time_range=args.get("time_range", "today"),
            max_results=args.get("max_results", 10),
        )
    if name == "list_workspace":
        return list_workspace(relative_path=args.get("relative_path", ""))
    if name == "read_workspace_file":
        return read_workspace_file(relative_path=args["relative_path"])
    if name == "write_workspace_file":
        return write_workspace_file(
            relative_path=args["relative_path"],
            content=args["content"],
            mode=args.get("mode", "overwrite"),
        )
    if name == "shuffle_music":
        return shuffle_music(
            query=args["query"],
            confirmed_name=args.get("confirmed_name"),
            confirmed_type=args.get("confirmed_type"),
        )
    if name == "stop_music":
        return stop_music()
    if name == "list_project_directory":
        return list_project_directory(relative_path=args.get("relative_path", ""))
    if name == "read_project_file":
        return read_project_file(relative_path=args["relative_path"])
    if name == "copy_to_workspace":
        return copy_to_workspace(relative_path=args["relative_path"])
    if name == "search_conversation_history":
        if tier == "household":
            return search_conversation_history(speaker_name, args["query"])
        return "I can only search full conversation history for household members."
    return f"Unknown tool: {name}"


def ask_claude(client, history: list, user_text: str, system_prompt: str,
               speaker_name: str, tier: str, device: str = "desktop",
               pending_actions: list = None) -> str:
    if pending_actions is None:
        pending_actions = []

    # If this turn fails, everything added since here is discarded, so a failed
    # attempt can never be saved into history and repeated on the next request.
    start_len = len(history)
    history.append({"role": "user", "content": user_text})
    tools = tools_for(device)
    response = None

    for round_num in range(MAX_TOOL_ROUNDS + 1):
        response = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=system_prompt,
            tools=tools, messages=history,
        )
        out_tokens = getattr(getattr(response, "usage", None), "output_tokens", "?")
        print(f"[brain] {device} round {round_num}: "
              f"stop_reason={response.stop_reason}, output_tokens={out_tokens}")

        if response.stop_reason == "max_tokens":
            has_tool_call = any(b.type == "tool_use" for b in response.content)
            has_text = any(b.type == "text" and b.text.strip() for b in response.content)
            if has_tool_call or not has_text:
                # A tool call cut off mid-argument is unusable, so don't run it.
                del history[start_len:]
                print("[brain] cut off at MAX_TOKENS, turn discarded")
                return TRUNCATED_REPLY
            break  # plain text that got cut off: still better than nothing

        if response.stop_reason != "tool_use":
            break

        if round_num == MAX_TOOL_ROUNDS:
            del history[start_len:]
            print("[brain] hit MAX_TOOL_ROUNDS, turn discarded")
            return ROUND_CAP_REPLY

        history.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"[brain] tool call: {block.name}")
            try:
                result = run_tool(block.name, block.input, speaker_name, tier, device, pending_actions)
            except Exception as e:
                result = f"Tool error: {e}"
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(result)})
        history.append({"role": "user", "content": tool_results})

    reply_text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not reply_text:
        del history[start_len:]
        print("[brain] empty reply, turn discarded")
        return EMPTY_REPLY
    history.append({"role": "assistant", "content": reply_text})
    return reply_text


# ---------- sessions ----------

class Session:
    """One conversation with one identified speaker, on one device."""

    def __init__(self, client, speaker_name: str, tier: str,
                 persona: str = "jarvis", device: str = "desktop"):
        self.client = client
        self.speaker_name = speaker_name
        self.tier = tier
        self.device = device
        self.history = []
        self.last_active = time.time()
        self.pending_actions = []

        if tier == "household" and should_regenerate_summary(speaker_name):
            print(f"Updating memory summary for {speaker_name}...")
            regenerate_summary(client, speaker_name)

        self.context_text = load_context_for(speaker_name, tier)
        self.set_persona(persona)

    def set_persona(self, persona: str):
        self.persona = persona
        self.system_prompt = build_persona_system_prompt(
            persona, self.speaker_name, self.tier, self.context_text
        ) + DEVICE_NOTES.get(self.device, "")
        if self.device == "phone":
            self.system_prompt += (
                f"\n\nThe current date and time is "
                f"{datetime.now().strftime('%A, %B %d, %Y, %I:%M %p')}."
            )

    def route(self, user_text: str):
        """Apply knowledge triggers and logging.
        Returns (text_for_claude, notice) where notice is an optional line to speak first."""
        notice = None
        lower_text = user_text.lower()

        if HOUSE_KNOWLEDGE_TRIGGER in lower_text:
            cleaned = re.sub(HOUSE_KNOWLEDGE_TRIGGER, "", user_text, flags=re.IGNORECASE).strip(" ,.")
            if self.tier == "household":
                append_to_file(HOUSEHOLD_FILE, cleaned)
                print(f"Logged to household.md: {cleaned}")
            else:
                notice = "I'm not able to add that to the household notes."
                append_to_file(guest_file_path(self.speaker_name), cleaned)
                print(f"Guest attempted household knowledge, logged to guest file instead: {cleaned}")
            return cleaned, notice

        if GENERAL_KNOWLEDGE_TRIGGER in lower_text:
            cleaned = re.sub(GENERAL_KNOWLEDGE_TRIGGER, "", user_text, flags=re.IGNORECASE).strip(" ,.")
            append_to_file(GENERAL_KNOWLEDGE_FILE, cleaned)
            print(f"Logged to general_knowledge.md: {cleaned}")
            return cleaned, notice

        target_path = (trusted_file_path(self.speaker_name) if self.tier == "household"
                       else guest_file_path(self.speaker_name))
        append_to_file(target_path, user_text)
        return user_text, notice

    def ask(self, text_for_claude: str) -> str:
        self.last_active = time.time()
        self.pending_actions = []
        reply = ask_claude(self.client, self.history, text_for_claude, self.system_prompt,
                           self.speaker_name, self.tier, self.device,
                           pending_actions=self.pending_actions)
        self.last_active = time.time()
        return reply

    def handle(self, user_text: str):
        """route + ask in one call. Returns (notice, reply)."""
        text_for_claude, notice = self.route(user_text)
        return notice, self.ask(text_for_claude)
