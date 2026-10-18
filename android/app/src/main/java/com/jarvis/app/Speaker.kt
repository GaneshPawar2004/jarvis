package com.jarvis.app

import android.content.Context
import android.speech.tts.TextToSpeech
import java.util.Locale

/** Speaks JARVIS's replies in a British English voice, even while another app is on screen. */
object Speaker {
    private var tts: TextToSpeech? = null
    private var ready = false
    private val queued = mutableListOf<String>()

    fun init(context: Context) {
        if (tts != null) return
        tts = TextToSpeech(context.applicationContext) { status ->
            ready = status == TextToSpeech.SUCCESS
            if (ready) {
                tts?.language = Locale.UK
                tts?.setSpeechRate(1.02f)
                queued.forEach { say(it) }
            }
            queued.clear()
        }
    }

    fun say(text: String) {
        val engine = tts ?: return
        if (!ready) {
            queued += text
            return
        }
        engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, "jarvis-${System.nanoTime()}")
    }

    fun stop() {
        tts?.stop()
    }
}
