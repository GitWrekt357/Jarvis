package com.gitwrekt.friday

import android.app.Application
import android.os.SystemClock
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import java.io.IOException

enum class Status { IDLE, LISTENING, THINKING, SPEAKING }

class AssistantViewModel(app: Application) : AndroidViewModel(app), SpeechInput.Listener {

    private val store = ConversationStore(app)
    private val client = ClaudeClient(BuildConfig.CLAUDE_API_KEY, BuildConfig.CLAUDE_MODEL)
    private val hub = HubClient(BuildConfig.JARVIS_HUB_URL)
    private val vault = TokenVault(app)
    private var newSession = true

    // The household token exists in memory only while unlocked. It is never in the APK.
    private var householdToken: String? = null
    private var backgroundedAt = 0L

    val messages = mutableStateListOf<ChatMessage>()
    var status by mutableStateOf(Status.IDLE); private set
    var partial by mutableStateOf(""); private set
    var error by mutableStateOf<String?>(null); private set
    var voiceLabel by mutableStateOf("loading…"); private set
    /** True when the last reply came from the direct-Claude fallback (no files/memory). */
    var offline by mutableStateOf(false); private set
    /** Guest by default. Household only after the biometric/PIN prompt succeeds. */
    var tier by mutableStateOf(Tier.GUEST); private set

    val hasHouseholdToken: Boolean get() = vault.has()

    private var currentVoice: String? = null
    private var requestJob: Job? = null

    private val speech = SpeechInput(app, this)
    private val speaker = Speaker(app) { refreshVoice() }

    init {
        messages.addAll(store.load(Tier.GUEST))
    }

    // ---- UI actions ----

    fun onMicTapped() {
        error = null
        when (status) {
            Status.IDLE -> { newSession = true; startListening() }
            Status.LISTENING -> { speech.cancel(); partial = ""; status = Status.IDLE }
            Status.THINKING -> {
                requestJob?.cancel()
                dropPendingUserMessage()
                status = Status.IDLE
            }
            Status.SPEAKING -> { speaker.stop(); startListening() } // tap to barge in
        }
    }

    /**
     * Called with the digits the barcode scanner read. Sends them to the brain as a
     * normal message, so the pantry tool on the hub does the lookup and the adding.
     * After the spoken reply Friday listens again, so you can say a quantity or expiry date.
     */
    fun onBarcodeScanned(code: String?) {
        if (tier != Tier.HOUSEHOLD) {
            error = "Unlock household mode to add things to the pantry."
            return
        }
        val digits = code?.filter { it.isDigit() }.orEmpty()
        if (digits.isEmpty()) {
            error = "That code does not look like a product barcode."
            return
        }
        stopEverything()
        error = null
        newSession = true
        sendToBrain("I scanned barcode $digits. Add it to the pantry.")
    }

    fun onScanError(message: String?) {
        error = message ?: "Barcode scanning failed."
    }

    fun clearHistory() {
        stopEverything()
        store.clear(tier)
        messages.clear()
    }

    // ---- Household unlock ----

    /** Saves the household token (encrypted). Returns false if it couldn't be stored. */
    fun saveHouseholdToken(token: String): Boolean {
        if (token.isBlank()) {
            error = "Scan or paste the household token first."
            return false
        }
        // The real token is ~22-43 characters. A short entry is almost certainly a PIN or a typo.
        if (token.trim().length < MIN_TOKEN_LENGTH) {
            error = "That is too short to be the hub token. Use the long FRIDAY_TOKEN, not your phone PIN."
            return false
        }
        val ok = vault.save(token)
        if (!ok) error = "Secure storage isn't available on this phone, so household mode can't be used."
        return ok
    }

    /** Call only after BiometricGate succeeds. */
    fun unlockHousehold() {
        val token = vault.read()
        if (token == null) {
            error = "No household token is saved on this phone."
            return
        }
        stopEverything()
        store.save(Tier.GUEST, messages)
        householdToken = token
        switchTier(Tier.HOUSEHOLD)
    }

    fun lockHousehold() {
        if (tier != Tier.HOUSEHOLD) return
        stopEverything()
        store.save(Tier.HOUSEHOLD, messages)
        householdToken = null
        switchTier(Tier.GUEST)
    }

    fun onUnlockError(message: String) { error = message }

    /** Household mode locks itself after the app has been in the background a while. */
    fun onBackgrounded() { backgroundedAt = SystemClock.elapsedRealtime() }

    fun onForegrounded() {
        if (tier == Tier.HOUSEHOLD && backgroundedAt != 0L &&
            SystemClock.elapsedRealtime() - backgroundedAt > RELOCK_AFTER_MS
        ) lockHousehold()
    }

    private fun switchTier(next: Tier) {
        tier = next
        newSession = true   // fresh conversation; the hub also keeps one session per tier
        offline = false
        error = null
        messages.clear()
        messages.addAll(store.load(next))
    }

    private fun currentToken(): String? =
        if (tier == Tier.HOUSEHOLD) householdToken
        else BuildConfig.JARVIS_GUEST_TOKEN.takeIf { it.isNotBlank() }

    private fun hubReady(): Boolean = hub.hasUrl && currentToken() != null

    private fun onHubRejectedToken() {
        if (tier == Tier.HOUSEHOLD) {
            vault.clear()
            lockHousehold()
            error = "The hub rejected the household token. Unlock again and paste the current one."
        } else {
            error = "The hub rejected the guest token. Check JARVIS_GUEST_TOKEN against FRIDAY_GUEST_TOKEN."
        }
    }

    fun cycleVoice() {
        val voices = speaker.englishVoices()
        if (voices.isEmpty()) return
        val idx = voices.indexOfFirst { it.name == currentVoice }
        val next = voices[(idx + 1) % voices.size]
        currentVoice = next.name
        store.voiceName = next.name
        voiceLabel = describe(next)
        stopEverything()
        status = Status.SPEAKING
        speaker.speak("This is how I sound now.", currentVoice) {
            status = Status.IDLE
        }
    }

    // ---- Speech callbacks ----

    override fun onPartial(text: String) { partial = text }

    override fun onFinal(text: String) {
        partial = ""
        val said = text.trim()
        if (isEndPhrase(said)) {
            status = Status.SPEAKING
            speaker.speak(Persona.signOff, currentVoice) { status = Status.IDLE }
            return
        }
        sendToBrain(said)
    }

    override fun onNothingHeard() {
        partial = ""
        if (status == Status.LISTENING) status = Status.IDLE
    }

    override fun onSpeechError(message: String) {
        partial = ""
        error = message
        status = Status.IDLE
    }

    // ---- internals ----

    /** Shared by voice and barcode input: show the message, ask the brain, speak the reply. */
    private fun sendToBrain(said: String) {
        messages.add(ChatMessage("user", said))
        status = Status.THINKING
        requestJob = viewModelScope.launch {
            try {
                val wasOffline = offline
                val reply = askBrain(said)
                messages.add(ChatMessage("assistant", reply))
                store.save(tier, messages)
                status = Status.SPEAKING
                val spoken = if (offline && !wasOffline) {
                    "I can't reach home, so I'm working without your files for now. $reply"
                } else reply
                // Open conversation: after speaking, listen again until silence or sign-off.
                speaker.speak(spoken, currentVoice) {
                    if (status == Status.SPEAKING) startListening()
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: HubAuthException) {
                dropPendingUserMessage()
                status = Status.IDLE
                onHubRejectedToken()
            } catch (e: Exception) {
                dropPendingUserMessage()
                error = e.message ?: "Request failed"
                status = Status.IDLE
            }
        }
    }

    /** Home hub first (full memory + files); direct Claude if home can't be reached. */
    private suspend fun askBrain(text: String): String {
        val token = currentToken()
        if (hub.hasUrl && token != null) {
            try {
                val result = hub.chat(token, text, newSession)
                newSession = false
                offline = false
                if (result.actions.isNotEmpty()) {
                    PhoneActions.run(getApplication(), result.actions)
                }
                return result.reply
            } catch (e: HubUnreachableException) {
                if (!client.hasKey) throw IOException("Can't reach home, and no fallback key is set.")
                offline = true
            }
        } else {
            offline = true
        }
        return client.send(Persona.systemPrompt, historyForApi())
    }

    private fun startListening() {
        if (!hubReady() && !client.hasKey) {
            error = "Nothing to talk to. Set JARVIS_HUB_URL and JARVIS_GUEST_TOKEN (or CLAUDE_API_KEY) in local.properties and rebuild."
            return
        }
        if (!speech.available) {
            error = "No speech recognizer on this phone (install/enable Google's speech services)."
            return
        }
        partial = ""
        status = Status.LISTENING
        speech.start()
    }

    private fun stopEverything() {
        requestJob?.cancel()
        dropPendingUserMessage()
        speech.cancel()
        speaker.stop()
        partial = ""
        status = Status.IDLE
    }

    private fun dropPendingUserMessage() {
        if (messages.lastOrNull()?.role == "user") messages.removeAt(messages.lastIndex)
    }

    /** API wants user/assistant alternation starting with user. */
    private fun historyForApi(): List<ChatMessage> =
        messages.takeLast(MAX_CONTEXT).dropWhile { it.role != "user" }

    private fun refreshVoice() {
        val voices = speaker.englishVoices()
        val saved = store.voiceName?.takeIf { n -> voices.any { it.name == n } }
        val chosen = saved
            ?: voices.firstOrNull()?.name
        currentVoice = chosen
        voiceLabel = voices.firstOrNull { it.name == chosen }?.let(::describe) ?: "system default"
    }

    private fun describe(v: android.speech.tts.Voice): String =
        "${v.locale.displayCountry} · ${v.name}" + if (v.isNetworkConnectionRequired) " (online)" else ""

    private fun isEndPhrase(said: String): Boolean {
        val n = said.lowercase().replace(Regex("[^a-z' ]"), "").trim()
        return END_PHRASES.any { n == it || n.endsWith(" $it") }
    }

    override fun onCleared() {
        requestJob?.cancel()
        speech.destroy()
        speaker.shutdown()
    }

    companion object {
        private const val MAX_CONTEXT = 30
        private const val RELOCK_AFTER_MS = 5 * 60 * 1000L
        private const val MIN_TOKEN_LENGTH = 20
        private val END_PHRASES = listOf(
            "goodbye", "that's all", "that is all", "that'll be all", "stop listening",
            "never mind", "nevermind", "we're done", "thanks that's all",
        )
    }
}
