# Friday (v0.1) — mobile companion to Jarvis

Kotlin + Jetpack Compose voice assistant for Android. Jarvis is the desktop agent; Friday is the mobile one.

Pipeline: phone speech-to-text (Android SpeechRecognizer, on-device when available)
→ Claude Messages API → phone text-to-speech (Android TextToSpeech).

## Features
- Tap to talk, then open conversation: after each reply it listens again until you
  go quiet or say a sign-off ("that's all", "goodbye", "never mind"…).
- Tap while it's speaking to interrupt and talk.
- Persistent chat history (survives restarts).
- Voice picker (tap the Voice line to cycle and hear a sample).

## Setup
1. Open this folder in Android Studio (it will generate the Gradle wrapper and `local.properties`).
2. Add to `local.properties` (see `local.properties.example`):
   ```
   CLAUDE_API_KEY=sk-ant-...
   CLAUDE_MODEL=claude-sonnet-5
   ```
3. Phone: Settings → About phone → tap Build number 7× → Developer options → USB debugging on.
4. Plug in, pick the phone in Android Studio's device menu, press Run.
   Or: Build → Build App Bundle(s)/APK(s) → Build APK(s), then sideload the APK.

## Security note
In this version the API key is compiled into the APK, which anyone holding the APK
can extract. Fine for your own phone; don't share the APK. The planned fix is a
home server that holds the key — change `ClaudeClient`'s `endpoint` to point at it.

## License
AGPL-3.0, same as Jarvis. Copy the LICENSE file from the Jarvis repo into this folder.

## Home hub (shared brain)
When JARVIS_HUB_URL and JARVIS_HUB_TOKEN are set, Friday sends what you say to
server.py on the laptop, which runs the same brain as desktop Jarvis (memory,
household.md, calendar, project/workspace files). If the laptop can't be reached,
she falls back to calling Claude directly and shows "offline mode".
