package com.gitwrekt.friday

import android.app.Application
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
    private val hub = HubClient(BuildConfig.JARVIS_HUB_URL, BuildConfig.JARVIS_HUB_TOKEN)
    private var newSession = true

    val messages = mutableStateListOf<ChatMessage>()
    var status by mutableStateOf(Status.IDLE); private set
    var partial by mutableStateOf(""); private set
    var error by mutableStateOf<String?>(null); private set
    var voiceLabel by mutableStateOf("loading…"); private set
    /** True when the last reply came from the direct-Claude fallback (no files/memory). */
    var offline by mutableStateOf(false); private set

    private var currentVoice: String? = null
    private var requestJob: Job? = null

    private val speech = SpeechInput(app, this)
    private val speaker = Speaker(app) { refreshVoice() }

    init {
        messages.addAll(store.load())
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

    fun clearHistory() {
        stopEverything()
        store.clear()
        messages.clear()
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
        messages.add(ChatMessage("user", said))
        status = Status.THINKING
        requestJob = viewModelScope.launch {
            try {
                val wasOffline = offline
                val reply = askBrain(said)
                messages.add(ChatMessage("assistant", reply))
                store.save(messages)
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
            } catch (e: Exception) {
                dropPendingUserMessage()
                error = e.message ?: "Request failed"
                status = Status.IDLE
            }
        }
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

    /** Home hub first (full memory + files); direct Claude if home can't be reached. */
    private suspend fun askBrain(text: String): String {
        if (hub.configured) {
            try {
                val result = hub.chat(text, newSession)
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
        if (!hub.configured && !client.hasKey) {
            error = "Nothing to talk to. Set JARVIS_HUB_URL/TOKEN or CLAUDE_API_KEY in local.properties and rebuild."
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
        private val END_PHRASES = listOf(
            "goodbye", "that's all", "that is all", "that'll be all", "stop listening",
            "never mind", "nevermind", "we're done", "thanks that's all",
        )
    }
}
