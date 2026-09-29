# Jarvis: A Local-First Voice Assistant

A fully hands-free voice assistant built on Linux. Speech recognition,
speech synthesis, wake-word detection, and speaker recognition all run
locally; reasoning and tool use go through Claude's API (see
[Privacy and data flow](#privacy-and-data-flow)). Built as a personal
project to explore voice-interface design, tiered security for a
multi-user household, and how far a single-developer system can go before
it needs more architecture than a single script can hold.

Jarvis has a mobile companion, [Friday](#friday-mobile-companion), for Android.

## What it does

- **Wake-word activated** ("hey Jarvis") using [openWakeWord](https://github.com/dscripka/openWakeWord)
- **Local speech-to-text** via [faster-whisper](https://github.com/SYSTRAN/faster-whisper), tuned with
  voice-activity detection and a user-editable hotword list to improve
  recognition of proper nouns and niche vocabulary
- **Local text-to-speech** via [Piper](https://github.com/rhasspy/piper), with support for multiple
  voices and mid-conversation persona switching (Jarvis and Friday)
- **Speaker recognition and trust tiers** using [Resemblyzer](https://github.com/resemble-ai/Resemblyzer) voice
  embeddings: household members get a properly averaged, multi-sample
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
- **Confirmation gates on anything consequential**: shutting down
  requires an explicit spoken confirmation; a name that collides with an
  existing household member never silently overwrites anyone; an
  uncertain match (e.g. an ambiguous artist name) is confirmed before
  acting on it, not guessed at
- **A home hub** (`server.py`) that lets the Friday phone app use the same
  brain, memory, and files as the desktop assistant

By default, Jarvis and Friday run on Claude Haiku, chosen for low latency
on short spoken replies. <!-- VERIFY: confirm the model constant now lives in brain.py and that jarvis.py / memory_tool.py import it rather than hardcoding their own copies. -->
The model is set in `brain.py`.

## Privacy and data flow

"Local-first" describes the audio pipeline, not the whole system.

**Stays on your machine:**
- Raw microphone audio
- Voice embeddings and voiceprints (`*_voiceprints.json`)
- Wake-word detection, transcription, and speech synthesis
- The raw, append-only conversation log for each person

**Sent to the Claude API on each turn:**
- The transcribed text of what was said, and the running conversation
- The system prompt, including loaded context: the household and general
  notes, the person's regenerated summary, and recent raw log entries
- Results returned by tools (calendar events, workspace files, project
  source that Claude asked to read)

Guests are sent only their own notes and the general notes, never
household data. If you need nothing to leave the machine, this design
does not provide that; a fully local LLM backend would be required.

## Architecture notes

The system deliberately separates a few things that are easy to
conflate:

- **Trust tier vs. identity.** Whether someone is "household" or "guest"
  is determined entirely by voice embedding match against a stored
  reference, never by a name someone claims out loud. A guest saying
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
- **Context window vs. notes files.** The notes files (`household.md`,
  `general_knowledge.md`, and guest files) are loaded into context as
  their last `MAX_CONTEXT_CHARS` characters (3000 by default). Nothing is
  deleted on disk, but once a notes file outgrows that limit, its oldest
  entries stop being visible to Claude. Keep the notes files short and
  current, or raise the limit in `jarvis.py`.
- **One brain, two front ends.** The desktop assistant (`jarvis.py`) and
  the home hub (`server.py`, used by Friday) share the same brain
  (`brain.py`), so both personas have the same memory, notes, and tools.
  <!-- VERIFY: describe brain.py's actual responsibilities (model calls, tool dispatch, both?) and whether jarvis.py and server.py both import it. -->

## Requirements

- Linux with a working audio stack (developed on Arch-based Garuda Linux
  with PipeWire/PulseAudio)
- Python 3.<!-- VERIFY: your Python version --> with `venv`
- System packages (not installable through pip):
  - **PortAudio**, required by PyAudio
    (`sudo pacman -S portaudio` on Arch, `sudo apt install portaudio19-dev` on Debian/Ubuntu)
  - **VLC**, required only for the music tool
    (`sudo pacman -S vlc` or `sudo apt install vlc`)
- An Anthropic API key
- Internet access on first run: faster-whisper downloads the
  `small.en` model automatically the first time it loads
- Speech recognition runs on CPU (int8), so expect noticeable latency on
  older machines

## Before you run this

The source files were written for one specific machine and currently
hardcode a few values you'll need to change for your own setup:

- **Project path.** Every module (`jarvis.py`, `workspace_tool.py`,
  `music_tool.py`, `project_tool.py`, `memory_tool.py`, and any others
  that reference it) independently hardcodes `~/desktopjarvis` as an
  absolute path, including the wake-word model, the Piper voices, and the
  notes, guest, and workspace folders. If you clone this anywhere else,
  search each file for `desktopjarvis` and replace it with your actual
  project path. If you skip this, the directories may be created at the
  default location and startup will then fail when the wake-word model and
  voices can't be found where the code expects them.
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
   If you plan to use the Friday phone app through the home hub, also add
   a `FRIDAY_TOKEN` (see [Home hub](#home-hub)).

3. Download Piper voice models into `voices/` inside your project path (see
   [Piper's voice catalog](https://huggingface.co/rhasspy/piper-voices);
   this project was built against `en_GB-alan-medium` and
   `en_GB-alba-medium`). Each voice needs both its `.onnx` file and its
   matching `.onnx.json` config.

4. Download the wake-word model. openWakeWord ships a helper for its
   pretrained models:
   ```bash
   python -c "import openwakeword; openwakeword.utils.download_models()"
   ```
   Copy `hey_jarvis_v0.1.onnx` from the download location into
   `wakeword_models/` inside your project path (this is where
   `WAKE_WORD_MODEL_PATH` in `jarvis.py` points).
   <!-- VERIFY: confirm download_models() puts hey_jarvis_v0.1.onnx somewhere copyable, and note the location. -->

5. If using the Calendar tool, this requires a one-time Google OAuth setup:
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
      this token on future runs. You only need to run `auth_setup.py`
      again if the token is ever revoked or deleted.

6. Set `INPUT_DEVICE_INDEX` in `jarvis.py` (see "Before you run this"
   above for the full list of machine-specific values to update first).

7. **Enroll yourself as a household member.** Voice identity is the only
   thing that grants household privileges, so until you enroll, every
   speaker, including you, is treated as a guest with no access to
   household data:
   ```bash
   python enroll_household.py
   ```
   Follow the prompts to record several voice samples; they are averaged
   into a single voiceprint. Repeat for each household member.
   <!-- VERIFY: confirm enroll_household.py's prompts and behavior match this description. -->

8. Run it:
   ```bash
   python jarvis.py
   ```

## Home hub

`server.py` lets the Friday phone app use the same brain as the desktop
assistant. Friday sends what you say to the hub's `/chat` endpoint with a
bearer token; the hub replies with the spoken text and any phone actions
(such as alarms and timers) for the app to run.

- The hub token is set with `FRIDAY_TOKEN` in the desktop `.env`, and must
  match `JARVIS_HUB_TOKEN` in Friday's `local.properties`.
- The intended setup is to reach the hub over [Tailscale](https://tailscale.com/)
  (`tailscale serve`) rather than exposing it to the open internet. A
  bearer token alone is thin protection for anything reachable publicly.
- See [`HUB_SETUP.md`](HUB_SETUP.md) for full setup, including running the
  hub as a service (`jarvis-hub.service`).
  <!-- VERIFY: HUB_SETUP.md and jarvis-hub.service contain no real tokens, IPs, or usernames before publishing. -->

## What's not included

This repo intentionally excludes anything that shouldn't be public or
shouldn't be shared between installs:

- `.env` (API keys and the hub token)
- `credentials.json` / `token.json` (Google OAuth)
- `*_voiceprints.json` (biometric voice data)
- Personal conversation logs and memory summaries
- Your music index database and runtime logs
- Downloaded voice/wake-word model binaries (fetched separately, see
  Setup)

## Known limitations

- **Music playback is a known, unresolved rough edge.** The current
  implementation shuffle-plays a local music library via VLC, but
  playback reliability under repeated launches has been inconsistent,
  likely a combination of PulseAudio/PipeWire device-routing quirks and
  a race condition between killing and relaunching VLC. Rather than keep
  patching around it, the plan is to rebuild music as its own isolated
  sub-agent rather than a tool call on the main orchestrator, once time
  allows.
- **Voice is the only identity check.** Household privileges depend on a
  voice-embedding match, so a close enough recording played near the
  microphone could match. This assumes physical access to the room is
  already trusted.
- This is a personal, single-household project, not a polished consumer
  product. Expect rough edges consistent with that.

## Friday: mobile companion

The `Friday/` folder contains an Android app (Kotlin, Jetpack Compose)
that acts as Jarvis's mobile counterpart. It listens with Android's
on-device speech recognition, sends the text to the home hub (or directly
to Claude if the hub is unreachable), and speaks the reply with Android
text-to-speech. See [`Friday/README.md`](Friday/README.md) for build and
setup steps.

## Why this exists

Built to actually learn voice-interface design and multi-agent tool
architecture by shipping something real, not a tutorial project, and
because a genuinely personalized household assistant, built by the one
person who knows exactly what it should do, is a different thing than
what any off-the-shelf product offers.

## License

Jarvis and Friday are released under the
[GNU AGPL-3.0](LICENSE).
<!-- VERIFY: a LICENSE file with the AGPL-3.0 text exists in the repo root. -->
