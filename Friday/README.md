# Friday (v0.2) — mobile companion to Jarvis

Kotlin + Jetpack Compose voice assistant for Android. Jarvis is the desktop agent; Friday is the mobile one.
Both share one brain (`brain.py`) running on your home machine.

```
phone speech-to-text → home hub (server.py over Tailscale) → brain.py → Claude API
                     ↘ (hub unreachable) direct Claude call, "offline mode"
phone text-to-speech ← reply + optional phone actions (alarms, timers)
```

## Features
- **Tap to talk, then open conversation:** after each reply Friday listens again until you
  go quiet or say a sign-off ("that's all", "goodbye", "never mind"…).
- **Barge-in:** tap while she is speaking to interrupt and talk.
- **Barcode scanning:** tap **Scan** at the top, point the camera at a product's UPC/EAN
  barcode, and Friday sends the code to the hub as "I scanned barcode … Add it to the
  pantry." The pantry tool on the hub looks the product up and adds it. Afterwards she
  listens, so you can say a quantity or expiry date.
  - Uses Google's code scanner (ML Kit, via Play Services), which runs in its own screen,
    so **Friday needs no camera permission**.
  - Reads EAN-13, EAN-8, UPC-A and UPC-E only (product barcodes; QR codes are ignored).
  - Needs a pantry tool registered in the hub's `brain.py`. Without one, Friday will
    receive the scan but have nothing to do with it.
- **Alarms and timers:** "wake me at 6:30", "timer for ten minutes". The hub queues the
  action and the phone sets it through the system Clock app.
- **Persistent chat history** (survives restarts) and a **voice picker** (tap the Voice line
  to cycle and hear a sample).

## Setup
1. Open this folder in Android Studio (it generates the Gradle wrapper and `local.properties`),
   then **Sync Project**.
2. Copy the entries from `local.properties.example` into `local.properties`:
   ```
   JARVIS_HUB_URL=https://your-laptop.your-tailnet.ts.net
   JARVIS_HUB_TOKEN=same-value-as-FRIDAY_TOKEN-in-the-hub-.env
   CLAUDE_API_KEY=sk-ant-...        # fallback only, used when home is unreachable
   CLAUDE_MODEL=claude-sonnet-5
   ```
3. Phone: Settings → About phone → tap Build number 7× → Developer options → USB debugging on.
4. Plug in, pick the phone in Android Studio's device menu, press Run.
   Or: Build → Build APK(s), then sideload the APK.

The hub (`server.py`) runs on the home machine, binds to `127.0.0.1`, and is exposed to
your own devices with `tailscale serve`. Every request needs the bearer token.

## Home hub (shared brain)
When `JARVIS_HUB_URL` and `JARVIS_HUB_TOKEN` are set, Friday sends what you say to the hub,
which runs the same brain as desktop Jarvis (memory, household notes, calendar, workspace
files, pantry). The hub replies with `{reply, actions}`. Actions are phone-side jobs
(currently `set_alarm` and `set_timer`) that `PhoneActions.kt` runs with Android intents.
If the hub can't be reached within a few seconds, Friday calls Claude directly and shows
"offline mode" (no files, memory or pantry).

## Security notes
- `local.properties` holds your hub token and API key. It is gitignored; never commit it.
- The API key and hub token are compiled into the APK, so anyone holding the APK can
  extract them. Fine for your own phone; don't share the APK.
- The hub is reachable only over your tailnet and still requires the token.

## License
GPL-3.0. See [LICENSE](LICENSE).
