package com.jarvis.app

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.view.Gravity
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView

/** A small "Listening…" panel that opens on top of whatever app is on screen (from the
 *  floating mic, the Quick Settings tile, long-press power, or the app's 🎤), sends what
 *  the user says to JARVIS, then gets out of the way so they stay in their app. */
class ListenActivity : Activity() {
    private val cyan = Ui.primary
    private val amber = Ui.warn
    private lateinit var heading: TextView
    private lateinit var heard: TextView
    private var recognizer: SpeechRecognizer? = null
    private var usedFallback = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.setLayout(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        window.setGravity(Gravity.BOTTOM)
        window.addFlags(WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL)
        setFinishOnTouchOutside(true)

        val density = resources.displayMetrics.density
        val panel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding((20 * density).toInt(), (18 * density).toInt(), (20 * density).toInt(), (22 * density).toInt())
            elevation = 12 * density
            background = GradientDrawable().apply {
                setColor(Color.WHITE)
                setStroke((1 * density).toInt(), Ui.border)
                cornerRadius = 22 * density
            }
        }
        heading = TextView(this).apply { text = "🎤  Listening…"; textSize = 18f; setTextColor(cyan) }
        heard = TextView(this).apply { textSize = 16f; setTextColor(Ui.text); setPadding(0, (8 * density).toInt(), 0, 0) }
        panel.addView(heading)
        panel.addView(heard)
        setContentView(android.widget.FrameLayout(this).apply {
            val margin = (12 * density).toInt()
            setPadding(margin, margin, margin, margin + (24 * density).toInt()) // clear of the gesture bar
            addView(panel)
        })

        LinkService.start(this) // make sure the link to JARVIS is up
        Speaker.stop()
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), MIC_PERMISSION)
        } else {
            listen()
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) listen()
        else fail("JARVIS needs microphone permission. Allow it in App info → Permissions → Microphone.")
    }

    private fun listen() {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) return fallback()
        val engine = SpeechRecognizer.createSpeechRecognizer(this).also { recognizer = it }
        engine.setRecognitionListener(object : RecognitionListener {
            override fun onResults(results: Bundle?) {
                val text = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()
                if (text.isNullOrBlank()) fail("I didn't catch that. Tap the mic to try again.") else send(text)
            }
            override fun onPartialResults(partial: Bundle?) {
                partial?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.let { heard.text = it }
            }
            override fun onError(error: Int) {
                when (error) {
                    SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT ->
                        fail("I didn't hear anything. Tap the mic to try again.")
                    SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS ->
                        fail("JARVIS needs microphone permission. Allow it in App info → Permissions → Microphone.")
                    else -> fallback() // the phone's built-in listener isn't working; use Google's voice pop-up
                }
            }
            override fun onReadyForSpeech(params: Bundle?) {}
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(rmsdB: Float) {}
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() { heading.text = "…" }
            override fun onEvent(eventType: Int, params: Bundle?) {}
        })
        engine.startListening(speechIntent().putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true))
    }

    private fun speechIntent() = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
        putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-IN")
        putExtra(RecognizerIntent.EXTRA_PROMPT, "Talk to JARVIS")
    }

    private fun fallback() {
        if (usedFallback) return fail("Voice input isn't available. Install or enable the Google app, or use your keyboard's mic.")
        usedFallback = true
        recognizer?.destroy()
        recognizer = null
        try {
            @Suppress("DEPRECATION")
            startActivityForResult(speechIntent(), GOOGLE_VOICE)
        } catch (e: Exception) {
            fail("Voice input isn't available. Install or enable the Google app, or use your keyboard's mic.")
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != GOOGLE_VOICE) return
        val text = data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
        if (resultCode == RESULT_OK && !text.isNullOrBlank()) send(text) else finish()
    }

    private fun send(text: String) {
        CloudLink.chat(text) // queued if JARVIS is still reconnecting
        heading.text = "Sent to JARVIS"
        heard.text = text
        heading.postDelayed({ finish() }, 900)
    }

    private fun fail(message: String) {
        heading.text = "JARVIS"
        heading.setTextColor(amber)
        heard.text = message
        heading.postDelayed({ finish() }, 3500)
    }

    override fun onDestroy() {
        recognizer?.destroy()
        super.onDestroy()
    }

    companion object {
        private const val MIC_PERMISSION = 1
        private const val GOOGLE_VOICE = 2

        fun open(context: android.content.Context) {
            context.startActivity(Intent(context, ListenActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
    }
}
