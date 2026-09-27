package com.gitwrekt.friday

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.speech.tts.Voice

/** Wraps Android TextToSpeech. Piper-on-Android (sherpa-onnx) can replace this later. */
class Speaker(context: Context, private val onReady: () -> Unit) : TextToSpeech.OnInitListener {

    private val main = Handler(Looper.getMainLooper())
    private val tts = TextToSpeech(context.applicationContext, this)
    private var onFinished: (() -> Unit)? = null
    private var lastUtteranceId: String? = null

    var ready = false
        private set

    override fun onInit(status: Int) {
        if (status != TextToSpeech.SUCCESS) return
        tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {}
            override fun onDone(utteranceId: String?) = finish(utteranceId)
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) = finish(utteranceId)
            override fun onError(utteranceId: String?, errorCode: Int) = finish(utteranceId)
        })
        main.post { ready = true; onReady() }
    }

    private fun finish(id: String?) {
        if (id != lastUtteranceId) return
        main.post {
            val cb = onFinished
            onFinished = null
            cb?.invoke()
        }
    }

    /** English voices, British ones first. */
    fun englishVoices(): List<Voice> =
        runCatching { tts.voices.orEmpty() }.getOrDefault(emptySet())
            .filter { it.locale.language == "en" }
            .sortedWith(compareBy({ it.locale.country != "GB" }, { it.isNetworkConnectionRequired }, { it.name }))

    fun speak(text: String, voiceName: String?, done: () -> Unit) {
        val clean = text.replace(Regex("[*#_`]"), "").trim()
        if (!ready || clean.isEmpty()) { done(); return }
        voiceName?.let { n -> englishVoices().firstOrNull { it.name == n }?.let { tts.voice = it } }

        val id = "u${System.nanoTime()}"
        lastUtteranceId = id
        onFinished = done
        val chunks = chunk(clean)
        chunks.forEachIndexed { i, c ->
            val uid = if (i == chunks.lastIndex) id else "$id-$i"
            tts.speak(c, if (i == 0) TextToSpeech.QUEUE_FLUSH else TextToSpeech.QUEUE_ADD, null, uid)
        }
    }

    fun stop() {
        onFinished = null
        lastUtteranceId = null
        tts.stop()
    }

    fun shutdown() = tts.shutdown()

    private fun chunk(text: String): List<String> {
        val max = TextToSpeech.getMaxSpeechInputLength() - 100
        if (text.length <= max) return listOf(text)
        val out = mutableListOf<String>()
        val sb = StringBuilder()
        text.split(Regex("(?<=[.!?])\\s+")).forEach { s ->
            if (sb.isNotEmpty() && sb.length + s.length + 1 > max) {
                out += sb.toString().trim(); sb.clear()
            }
            sb.append(s.take(max)).append(' ')
        }
        if (sb.isNotBlank()) out += sb.toString().trim()
        return out
    }
}
