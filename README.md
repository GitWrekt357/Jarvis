# Jarvis — A Local-First Voice Assistant

A fully hands-free voice assistant built on Linux, combining local speech
recognition and synthesis with Claude's tool-use API. Built as a personal
project to explore voice-interface design, tiered security for a
multi-user household, and how far a single-developer system can go before
it needs more architecture than a single script can hold.

## What it does

- **Wake-word activated** ("hey Jarvis") using [openWakeWord](https://github.com/dscripka/openWakeWord)
- **Local speech-to-text** via [faster-whisper](https://github.com/SYSTRAN/faster-whisper), tuned with
  voice-activity detection and a user-editable hotword list to improve
  recognition of proper nouns and niche vocabulary
- **Local text-to-speech** via [Piper](https://github.com/rhasspy/piper), with support for multiple
  voices and mid-conversation persona switching
- **Speaker recognition and trust tiers** using [Resemblyzer](https://github.com/resemble-ai/Resemblyzer) voice
  embeddings — household members get a properly averaged, multi-sample
  voiceprint and elevated privileges; unrecognized voices are enrolled as
  guests with a separate, lower-trust profile and no access to household
  data
- **Tool use via the Claude API**, including:
  - Google Calendar lookups
  - A sandboxed workspace for hands-free code drafting and testing,
    fully isolated from the live running program
  - Read-only access to the project's own live source for
    self-discussion, plus a one-way (never reverse) copy tool into the
    sandbox
  - A two-tier memory system: a compact, periodically-regenerated
    summary for ongoing context, plus an on-demand search tool over the
    full raw conversation history when more detail is needed
- **Confirmation gates on anything consequential** — shutting down
  requires an explicit spoken confirmation; a name that collides with an
  existing household member never silently overwrites anyone; an
  uncertain match (e.g. an ambiguous artist name) is confirmed before
  acting on it, not guessed at

## Architecture notes

The system deliberately separates a few things that are easy to
conflate:

- **Trust tier vs. identity.** Whether someone is "household" or "guest"
  is determined entirely by voice embedding match against a stored
  reference — never by a name someone claims out loud. A guest saying
  "call me Josh" does not grant Josh's privileges.
- **Live source vs. sandbox.** Jarvis can read its own source code for
  self-discussion and copy files into an isolated workspace to draft or
  test changes, but it can never write back to the files that are
  actually running. Promoting a tested change into production is a
  manual, human-driven step.
- **Raw log vs. summary.** Conversation history is never silently
  truncated and discarded. A raw, append-only log per person remains the
  source of truth; a separate, periodically-regenerated summary provides
  compact ongoing context without needing to reload everything on every
  turn.

## Before you run this

The source files were written for one specific machine and currently
hardcode a few values you'll need to change for your own setup:

- **Project path.** Every module (`jarvis.py`, `workspace_tool.py`,
  `music_tool.py`, `project_tool.py`, `memory_tool.py`) independently
  hardcodes `~/desktopjarvis` as an absolute path. If you clone this
  anywhere else, or under a different folder name, search each file for
  `desktopjarvis` and replace it with your actual project path. Nothing
  will throw an import error if you skip this — it'll just silently look
  for files in a directory that doesn't exist.
- **Microphone index.** `INPUT_DEVICE_INDEX` is set to a specific number
  in both `jarvis.py` and `enroll_household.py`, matching one developer's
  hardware. Set it to `None` and run either script once to print a list
  of your own available input devices, then hard-code the correct index
  for your machine.
- **Music library path**, if you use the music indexer:
  `MUSIC_LIBRARY_ROOT` in `music_indexer.py` points at a specific
  folder and will need to match wherever your own music actually lives.

## Setup

1. Clone the repo and create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. Create a `.env` file in the project root (never commit this):
   ```
   ANTHROPIC_API_KEY=your_key_here
   ```

3. Download Piper voice models into `voices/` (see [Piper's voice
   catalog](https://huggingface.co/rhasspy/piper-voices) — this project
   was built against `en_GB-alan-medium` and `en_GB-alba-medium`).

4. If using the Calendar tool, this requires a one-time Google OAuth setup:
   1. In the [Google Cloud Console](https://console.cloud.google.com/), create
      a project, enable the Calendar API, and create an OAuth client ID of
      type **Desktop app**. Download it as `credentials.json` and place it
      in the project root (never commit this file).
   2. Run the setup script once:
      ```bash
      python auth_setup.py
      ```
      This opens a browser for you to sign in and grant read-only calendar
      access, then saves a `token.json` in the project root (also never
      committed). `calendar_tool.py` will load and automatically refresh
      this token on future runs — you only need to run `auth_setup.py`
      again if the token is ever revoked or deleted.

5. Set `INPUT_DEVICE_INDEX` in `jarvis.py` (see "Before you run this"
   above for the full list of machine-specific values to update first).

6. Run it:
   ```bash
   python jarvis.py
   ```

## What's not included

This repo intentionally excludes anything that shouldn't be public or
shouldn't be shared between installs:

- `.env` (API keys)
- `credentials.json` / `token.json` (Google OAuth)
- `*_voiceprints.json` (biometric voice data)
- Personal conversation logs and memory summaries
- Downloaded voice/wake-word model binaries (fetched separately, see
  Setup)

## Known limitations

- **Music playback is a known, unresolved rough edge.** The current
  implementation shuffle-plays a local music library via VLC, but
  playback reliability under repeated launches has been inconsistent —
  likely a combination of PulseAudio/PipeWire device-routing quirks and
  a race condition between killing and relaunching VLC. Rather than keep
  patching around it, the plan is to rebuild music as its own isolated
  sub-agent rather than a tool call on the main orchestrator, once time
  allows.
- This is a personal, single-household project, not a polished consumer
  product. Expect rough edges consistent with that.

## Why this exists

Built to actually learn voice-interface design and multi-agent tool
architecture by shipping something real, not a tutorial project — and
because a genuinely personalized household assistant, built by the one
person who knows exactly what it should do, is a different thing than
what any off-the-shelf product offers.
