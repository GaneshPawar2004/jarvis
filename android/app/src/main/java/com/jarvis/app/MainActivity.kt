package com.jarvis.app

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import kotlin.concurrent.thread

/** The JARVIS app screen: pair once with the password, then chat by typing or with the mic.
 *  Also opens when JARVIS is chosen as the phone's assistant (long-press power / home). */
class MainActivity : Activity(), CloudLink.Listener {
    private val cyan = Color.parseColor("#3FD9FF")
    private val muted = Color.parseColor("#6C93A8")
    private val amber = Color.parseColor("#FFB84D")
    private val textColor = Color.parseColor("#CFEFFF")

    private lateinit var status: TextView
    private lateinit var controlRow: LinearLayout
    private lateinit var log: LinearLayout
    private lateinit var scroll: ScrollView
    private lateinit var input: EditText
    private lateinit var mic: Button
    private var recognizer: SpeechRecognizer? = null
    private var listenWhenReady = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2)
        }
        Speaker.init(this)
        if (Prefs.token(this) == null) showPairing() else showChat()
        listenWhenReady = intent?.action == Intent.ACTION_ASSIST
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.action == Intent.ACTION_ASSIST && ::mic.isInitialized) startListening()
    }

    override fun onResume() {
        super.onResume()
        if (::controlRow.isInitialized) {
            controlRow.visibility = if (JarvisAccessibilityService.instance == null) View.VISIBLE else View.GONE
        }
        if (listenWhenReady && ::mic.isInitialized) {
            listenWhenReady = false
            startListening()
        }
    }

    override fun onDestroy() {
        CloudLink.removeListener(this)
        recognizer?.destroy()
        super.onDestroy()
    }

    // ---------------- pairing ----------------

    private fun showPairing() {
        val root = column().apply { setPadding(dp(24), dp(48), dp(24), dp(24)) }
        root.addView(title())
        root.addView(label("Connect this phone to your cloud JARVIS. You only do this once.", muted))
        val url = field("Cloud JARVIS address", Prefs.DEFAULT_URL).apply { setText(Prefs.url(this@MainActivity)) }
        val password = field("JARVIS password", "").apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        val message = label("", amber)
        val pair = button("CONNECT") {
            message.setTextColor(muted)
            message.text = "Connecting… (a sleeping server can take up to a minute)"
            val address = url.text.toString().trim()
            val secret = password.text.toString()
            thread {
                try {
                    CloudLink.pair(this, address, secret, "Phone (${Build.MANUFACTURER} ${Build.MODEL})")
                    runOnUiThread { showChat() }
                } catch (e: Exception) {
                    runOnUiThread {
                        message.setTextColor(amber)
                        message.text = e.message ?: "Couldn't connect."
                    }
                }
            }
        }
        listOf(url, password, pair, message).forEach { root.addView(it, spaced()) }
        setContentView(root)
    }

    // ---------------- chat ----------------

    private fun showChat() {
        LinkService.start(this)
        val root = column().apply { setPadding(dp(16), dp(28), dp(16), dp(12)) }
        root.addView(title())
        status = label("", muted).also { root.addView(it) }

        controlRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            addView(label("Phone control is off — JARVIS can chat but not tap or type.", amber),
                LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            addView(button("TURN ON") { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) })
            visibility = if (JarvisAccessibilityService.instance == null) View.VISIBLE else View.GONE
        }
        root.addView(controlRow, spaced())

        log = column()
        scroll = ScrollView(this).apply { addView(log) }
        root.addView(scroll, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))

        val speak = CheckBox(this).apply {
            text = "Speak replies"
            setTextColor(muted)
            isChecked = Prefs.speakReplies
            setOnCheckedChangeListener { _, checked -> Prefs.speakReplies = checked; if (!checked) Speaker.stop() }
        }
        root.addView(speak)

        val bar = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        mic = button("🎤") { startListening() }
        input = EditText(this).apply {
            hint = "Talk to JARVIS…"
            setHintTextColor(muted)
            setTextColor(textColor)
            imeOptions = EditorInfo.IME_ACTION_SEND
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
            setOnEditorActionListener { _, _, _ -> send(); true }
        }
        bar.addView(mic)
        bar.addView(input, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        bar.addView(button("SEND") { send() })
        root.addView(bar)
        setContentView(root)
        CloudLink.addListener(this)
    }

    private fun send(text: String = input.text.toString().trim()) {
        if (text.isEmpty()) return
        input.setText("")
        if (!CloudLink.chat(text)) {
            addLine("Not connected to cloud JARVIS yet — try again in a moment.", amber)
            return
        }
        addLine(text, textColor, alignEnd = true)
        status.text = "Thinking…"
    }

    override fun onStatus(connected: Boolean, message: String) {
        if (::status.isInitialized) {
            status.text = if (connected) "● Online" else "○ $message"
            status.setTextColor(if (connected) cyan else muted)
        }
        if (!connected && message.startsWith("This phone's key was rejected")) showPairing()
    }

    override fun onTool(name: String) = addLine("⚙ $name", muted)

    override fun onReply(text: String, isError: Boolean) {
        addLine(if (isError) "⚠ $text" else text, if (isError) amber else cyan)
        status.text = "● Online"
    }

    // ---------------- voice ----------------

    private fun startListening() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1)
            return
        }
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            addLine("Speech recognition isn't available on this phone (install/enable the Google app).", amber)
            return
        }
        Speaker.stop()
        val engine = recognizer ?: SpeechRecognizer.createSpeechRecognizer(this).also { recognizer = it }
        engine.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) { mic.setTextColor(amber); status.text = "Listening…" }
            override fun onResults(results: Bundle?) {
                mic.setTextColor(cyan)
                results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.let { send(it) }
            }
            override fun onPartialResults(partial: Bundle?) {
                partial?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.let { input.setText(it) }
            }
            override fun onError(error: Int) { mic.setTextColor(cyan); status.text = "Didn't catch that — tap 🎤 to try again." }
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(rmsdB: Float) {}
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() {}
            override fun onEvent(eventType: Int, params: Bundle?) {}
        })
        engine.startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-IN")
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
        })
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        if (requestCode == 1 && grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) startListening()
    }

    // ---------------- small view helpers ----------------

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    private fun column() = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }

    private fun spaced() = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)
        .apply { topMargin = dp(12) }

    private fun title() = TextView(this).apply {
        text = "J.A.R.V.I.S."
        textSize = 26f
        letterSpacing = 0.3f
        typeface = Typeface.DEFAULT_BOLD
        setTextColor(cyan)
        setShadowLayer(18f, 0f, 0f, cyan)
    }

    private fun label(value: String, color: Int) = TextView(this).apply {
        text = value
        textSize = 14f
        setTextColor(color)
    }

    private fun field(hintText: String, value: String) = EditText(this).apply {
        hint = hintText
        setText(value)
        setTextColor(textColor)
        setHintTextColor(muted)
        isSingleLine = true
    }

    private fun button(text: String, onClick: () -> Unit) = Button(this).apply {
        this.text = text
        setTextColor(cyan)
        background = GradientDrawable().apply { setStroke(dp(1), cyan); cornerRadius = dp(6).toFloat() }
        setOnClickListener { onClick() }
    }

    private fun addLine(text: String, color: Int, alignEnd: Boolean = false) {
        if (!::log.isInitialized) return
        val line = TextView(this).apply {
            this.text = text
            textSize = 16f
            setTextColor(color)
            gravity = if (alignEnd) Gravity.END else Gravity.START
            setPadding(dp(4), dp(6), dp(4), dp(6))
        }
        log.addView(line, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))
        scroll.post { scroll.fullScroll(View.FOCUS_DOWN) }
    }
}
