# Friday (v0.3) — mobile companion to Jarvis

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
- **Barcode scanning (household mode only):** tap **Scan** at the top, point the camera at a product's UPC/EAN
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
- **Guest and household modes:** Friday starts as a guest. Tap **Unlock** and pass the
  fingerprint (or PIN) prompt to switch to household mode. See "Trust model" below.
- **Persistent chat history** (survives restarts; kept separately for each mode) and a **voice picker** (tap the Voice line
  to cycle and hear a sample).

## Setup
1. Open this folder in Android Studio (it generates the Gradle wrapper and `local.properties`),
   then **Sync Project**.
2. Copy the entries from `local.properties.example` into `local.properties`:
   ```
   JARVIS_HUB_URL=https://your-laptop.your-tailnet.ts.net
   JARVIS_GUEST_TOKEN=same-value-as-FRIDAY_GUEST_TOKEN-in-the-hub-.env
   CLAUDE_API_KEY=sk-ant-...        # fallback only, used when home is unreachable
   CLAUDE_MODEL=claude-sonnet-5
   ```
   Do **not** put the household token (`FRIDAY_TOKEN`) here: anything in `local.properties`
   is compiled into the APK. Upgrading from an older build? Delete the old
   `JARVIS_HUB_TOKEN` line.
3. Phone: Settings → About phone → tap Build number 7× → Developer options → USB debugging on.
4. Plug in, pick the phone in Android Studio's device menu, press Run.
   Or: Build → Build APK(s), then sideload the APK.
5. First household unlock: tap **Unlock**, paste `FRIDAY_TOKEN` once, then confirm with your
   fingerprint or PIN. After that, Unlock only asks for the fingerprint/PIN. The phone needs a
   screen lock set up.

## Hub setup
The hub (`server.py`) runs on the home machine, binds to `127.0.0.1`, and is exposed to
your own devices with `tailscale serve`. Its `.env` needs:

```
FRIDAY_TOKEN=long-random-string          # household
FRIDAY_SPEAKER=Josh                      # your name in household_voiceprints.json
FRIDAY_GUEST_TOKEN=a-different-random-string   # guest (optional; unset = no guest access)
FRIDAY_GUEST_SPEAKER=Phone Guest         # optional, this is the default
```
The two tokens must differ. Generate each with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
Restart the hub after changing `.env`.

## Home hub (shared brain)
Friday sends what you say to the hub, which runs the same brain as desktop Jarvis (memory,
household notes, calendar, workspace files, pantry). The hub replies with `{reply, actions}`.
Actions are phone-side jobs (currently `set_alarm` and `set_timer`) that `PhoneActions.kt`
runs with Android intents. If the hub can't be reached within a few seconds, Friday calls
Claude directly and shows "offline mode" (no files, memory or pantry).

## Trust model
Friday does no voice recognition. Android speech-to-text runs on the phone and the hub only
receives text, so the hub can't tell who is speaking. The **token** is the only thing that
decides the tier, never anything else the app sends:

| | Guest | Household |
|---|---|---|
| Token | `FRIDAY_GUEST_TOKEN`, built into the APK | `FRIDAY_TOKEN`, pasted on the phone, never in the APK |
| How you get it | Always active at launch | Fingerprint, or PIN as fallback |
| Hub speaker | `Phone Guest` | your `FRIDAY_SPEAKER` |
| Hub tools | Only the brain's guest allowlist (`GUEST_ALLOWED_TOOLS`): on the phone that is alarms and timers; music is desktop-only | Everything, including household notes, files, calendar and pantry |
| Chat history on the phone | Plain app storage | Encrypted (Android Keystore) |

- The hub keeps a **separate session per tier**, so switching tiers never reuses the other
  tier's conversation.
- The household token is stored with `EncryptedSharedPreferences` (Android Keystore). It is
  held in memory only while unlocked.
- Household mode relocks when you tap **Lock** or after about 5 minutes in the background.
  Killing the app also relocks it.
- If the hub rejects the household token (for example after you rotate it), Friday forgets it
  and asks for the new one at the next unlock.
- What the guest tier can do is enforced by `brain.py` on the hub: guests are only offered the
  tools in `GUEST_ALLOWED_TOOLS`, and `run_tool` refuses anything else even if it is requested.
  A new tool is household-only until you add it to that set on purpose.

## Security notes
- **`server.py` prints every conversation, in both tiers, to stdout.** Run as a service, that
  goes to journald (`journalctl --user -u jarvis-hub`), so full chat text sits in the
  hub machine's logs.
- `local.properties` is gitignored; never commit it. Everything in it is compiled into the APK,
  which currently means the guest token and the `CLAUDE_API_KEY` fallback. Anyone holding the
  APK can extract both. Fine for your own phone; don't share the APK.
- The app-level lock is a software gate: a rooted or compromised phone could still get at
  the unlocked token in memory. It is meant to stop casual use by someone holding your phone.
- The hub is reachable only over your tailnet and still requires a token.

## License
GPL-3.0. See [LICENSE](LICENSE).
