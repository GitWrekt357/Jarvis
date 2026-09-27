package com.gitwrekt.friday

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer

/** Wraps Android's SpeechRecognizer (the phone's STT; on-device when available). */
class SpeechInput(private val context: Context, private val listener: Listener) {

    interface Listener {
        fun onPartial(text: String)
        fun onFinal(text: String)
        fun onNothingHeard()
        fun onSpeechError(message: String)
    }

    val available: Boolean get() = SpeechRecognizer.isRecognitionAvailable(context)

    private val recognizer: SpeechRecognizer =
        SpeechRecognizer.createSpeechRecognizer(context).apply {
            setRecognitionListener(object : RecognitionListener {
                override fun onResults(results: Bundle?) {
                    val text = results
                        ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        ?.firstOrNull().orEmpty()
                    if (text.isBlank()) listener.onNothingHeard() else listener.onFinal(text)
                }
                override fun onPartialResults(partial: Bundle?) {
                    partial?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        ?.firstOrNull()?.let { listener.onPartial(it) }
                }
                override fun onError(error: Int) {
                    when (error) {
                        SpeechRecognizer.ERROR_NO_MATCH,
                        SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> listener.onNothingHeard()
                        SpeechRecognizer.ERROR_CLIENT -> Unit // usually our own cancel()
                        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS ->
                            listener.onSpeechError("Microphone permission is off.")
                        SpeechRecognizer.ERROR_NETWORK,
                        SpeechRecognizer.ERROR_NETWORK_TIMEOUT ->
                            listener.onSpeechError("Speech recognition needs a connection (no offline model).")
                        else -> listener.onSpeechError("Speech recognizer error $error")
                    }
                }
                override fun onReadyForSpeech(params: Bundle?) {}
                override fun onBeginningOfSpeech() {}
                override fun onRmsChanged(rmsdB: Float) {}
                override fun onBufferReceived(buffer: ByteArray?) {}
                override fun onEndOfSpeech() {}
                override fun onEvent(eventType: Int, params: Bundle?) {}
            })
        }

    fun start() {
        recognizer.cancel()
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
            // Pause tolerance hints — some recognizers ignore these.
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 2000L)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 2000L)
        }
        recognizer.startListening(intent)
    }

    fun cancel() = recognizer.cancel()
    fun destroy() = recognizer.destroy()
}
