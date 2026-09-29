# Friday (v0.1): mobile companion to Jarvis

Kotlin + Jetpack Compose voice assistant for Android. Jarvis is the desktop agent; Friday is the mobile one.

Pipeline: phone speech-to-text (Android SpeechRecognizer, on-device when available)
→ home hub (`server.py` on your laptop, the same brain as desktop Jarvis)
→ phone text-to-speech (Android TextToSpeech).

If the hub can't be reached, Friday falls back to calling the Claude Messages
API directly (see [Offline mode](#offline-mode)).

## Features
- Tap to talk, then open conversation: after each reply it listens again until you
  go quiet or say a sign-off ("that's all", "goodbye", "never mind"…).
- Tap while it's speaking to interrupt and talk.
- Persistent chat history (survives restarts).
- Voice picker (tap the Voice line to cycle and hear a sample).
- Phone actions from the hub, such as setting alarms and timers.

## Setup
1. Open this folder in Android Studio (it will generate the Gradle wrapper and `local.properties`).
2. Add to `local.properties` (see `local.properties.example`). Android Studio
   already puts `sdk.dir` there; leave it alone.
   ```
   # Home hub (your laptop, via Tailscale). Get the URL from `tailscale serve status`.
   JARVIS_HUB_URL=https://your-laptop.your-tailnet.ts.net
   JARVIS_HUB_TOKEN=same-value-as-FRIDAY_TOKEN-in-the-desktop-.env

   # Optional fallback when home is unreachable (calls Claude directly, no files or memory).
   CLAUDE_API_KEY=sk-ant-...
   CLAUDE_MODEL=claude-haiku-4-5-20251001
   ```
   You need at least one of the two: the hub settings or a Claude API key.
3. Phone: Settings → About phone → tap Build number 7× → Developer options → USB debugging on.
4. Plug in, pick the phone in Android Studio's device menu, press Run.
   Or: Build → Build App Bundle(s)/APK(s) → Build APK(s), then sideload the APK.

These values are read from `local.properties` at build time, so change them
and rebuild the app to apply a new hub URL, token, key, or model.

## Home hub (shared brain)
When `JARVIS_HUB_URL` and `JARVIS_HUB_TOKEN` are set, Friday sends what you say to
`server.py` on the laptop, which runs the same brain as desktop Jarvis (memory,
`household.md`, calendar, project/workspace files). The hub URL is normally a
Tailscale address, so it is only reachable from devices on your tailnet. See
`HUB_SETUP.md` in the Jarvis repo root for setting up the hub itself.

## Offline mode
If the laptop can't be reached and `CLAUDE_API_KEY` is set, Friday falls back
to calling Claude directly and shows "offline mode". In this mode she has
no access to your files, notes, or memory. If you leave `CLAUDE_API_KEY`
blank, there is no fallback and Friday will report that she can't reach home.

## Security note
Anything in `local.properties` is compiled into the APK, and anyone holding
the APK can extract it, so don't share your build.

- **`JARVIS_HUB_TOKEN`** is only useful to someone who can also reach your
  hub, which over Tailscale means a device on your tailnet.
- **`CLAUDE_API_KEY`** is the riskier one: it is a real API key. To keep it
  off the phone entirely, leave it blank and accept that there is no
  offline fallback.

## License
AGPL-3.0, same as Jarvis. Copy the LICENSE file from the Jarvis repo into this folder.
