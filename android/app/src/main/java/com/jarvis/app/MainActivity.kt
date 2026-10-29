package com.jarvis.app

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.app.KeyguardManager
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import kotlin.concurrent.thread

/** The JARVIS app: pair once with the password, then chat by typing or with the mic.
 *  Light theme; every screen keeps clear of the status bar, gesture bar and keyboard. */
class MainActivity : Activity(), CloudLink.Listener {
    private lateinit var status: TextView
    private lateinit var controlBanner: View
    private lateinit var log: LinearLayout
    private lateinit var scroll: ScrollView
    private lateinit var input: EditText
    private var emptyState: View? = null
    private var lastTool: TextView? = null
    private var lastToolName = ""
    private var lastToolCount = 0
    private var settingsDialog: AlertDialog? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2)
        }
        Speaker.init(this)
        if (Prefs.token(this) == null) showPairing() else showChat()
        if (intent?.action == Reminders.ACTION_BRIEFING) Reminders.briefNow(this)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.action == Reminders.ACTION_BRIEFING) Reminders.briefNow(this)
    }

    override fun onPause() {
        CloudLink.appVisible = false
        JarvisAccessibilityService.instance?.appInFront(false)
        super.onPause()
    }

    override fun onResume() {
        super.onResume()
        CloudLink.appVisible = true
        JarvisAccessibilityService.instance?.appInFront(true) // no floating mic on top of JARVIS itself
        getSystemService(android.app.NotificationManager::class.java).cancel(2) // the reply notification
        refreshControlBanner()
        JarvisAccessibilityService.onConnected = { refreshControlBanner() }
    }

    private fun refreshControlBanner() {
        if (::controlBanner.isInitialized) {
            controlBanner.visibility = if (JarvisAccessibilityService.instance == null) View.VISIBLE else View.GONE
        }
    }

    override fun onDestroy() {
        JarvisAccessibilityService.onConnected = null
        CloudLink.removeListener(this)
        super.onDestroy()
    }

    private fun dp(value: Int) = Ui.dp(this, value)

    // ---------------- pairing ----------------

    private fun showPairing() {
        val root = Ui.column(this).apply { gravity = Gravity.CENTER_VERTICAL }
        root.addView(Ui.text(this, "JARVIS", 34f, Ui.primary, bold = true).apply { gravity = Gravity.CENTER; letterSpacing = 0.25f })
        root.addView(Ui.text(this, "Your personal assistant", 15f, Ui.muted).apply { gravity = Gravity.CENTER }, Ui.matchWrap(4, this))

        val card = Ui.card(this).apply { setPadding(dp(18), dp(18), dp(18), dp(18)) }
        card.addView(Ui.text(this, "Connect this phone", 18f, bold = true))
        card.addView(Ui.text(this, "Enter your JARVIS password once. It isn't saved on the phone.", 14f, Ui.muted), Ui.matchWrap(4, this))
        val url = Ui.field(this, "Cloud JARVIS address", Prefs.url(this))
        val password = Ui.field(this, "JARVIS password").apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        val message = Ui.text(this, "", 14f, Ui.muted)
        val connect = Ui.primaryButton(this, "Connect") {
            message.setTextColor(Ui.muted)
            message.text = "Connecting… (a sleeping server can take up to a minute)"
            val address = url.text.toString().trim()
            val secret = password.text.toString()
            thread {
                try {
                    CloudLink.pair(this, address, secret, "Phone (${Build.MANUFACTURER} ${Build.MODEL})")
                    runOnUiThread { showChat() }
                } catch (e: Exception) {
                    runOnUiThread { message.setTextColor(Ui.warn); message.text = e.message ?: "Couldn't connect." }
                }
            }
        }
        card.addView(url, Ui.matchWrap(16, this))
        card.addView(password, Ui.matchWrap(10, this))
        card.addView(connect, Ui.matchWrap(16, this))
        card.addView(message, Ui.matchWrap(10, this))
        root.addView(card, Ui.matchWrap(28, this))
        Ui.show(this, root, padH = 20)
    }

    // ---------------- chat ----------------

    private fun showChat() {
        LinkService.start(this)
        val root = Ui.column(this)

        // Header: name + live status, then details and settings buttons.
        val header = Ui.row(this)
        val titles = Ui.column(this)
        titles.addView(Ui.text(this, "JARVIS", 24f, Ui.text, bold = true).apply { letterSpacing = 0.12f })
        status = Ui.text(this, "Connecting…", 13f, Ui.muted).also { titles.addView(it) }
        header.addView(titles, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        header.addView(Ui.iconButton(this, "🔒", 44, filled = false) { unlockVault() })
        header.addView(Ui.iconButton(this, "⚙", 44, filled = false) { showSettings() }.apply {
            (layoutParams as LinearLayout.LayoutParams).marginStart = dp(8)
        })
        root.addView(header, Ui.matchWrap(4, this))

        // Shown only while phone control (Accessibility) is off.
        controlBanner = Ui.row(this).apply {
            background = Ui.rounded(Ui.warnSoft, 12, this@MainActivity)
            setPadding(dp(14), dp(10), dp(10), dp(10))
            addView(Ui.text(this@MainActivity, "Phone control is off. JARVIS can chat but can't tap or type.", 14f, Ui.warn),
                LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            addView(Ui.softButton(this@MainActivity, "Turn on") { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) })
            visibility = if (JarvisAccessibilityService.instance == null) View.VISIBLE else View.GONE
        }
        root.addView(controlBanner, Ui.matchWrap(12, this))

        log = Ui.column(this).apply { setPadding(0, dp(8), 0, dp(8)) }
        scroll = ScrollView(this).apply { isFillViewport = true; addView(log) }
        root.addView(scroll, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f).apply { topMargin = dp(8) })
        showEmptyState()

        // Composer: rounded text box with send, and a round mic button.
        val composer = Ui.row(this)
        val pill = Ui.row(this).apply {
            background = Ui.rounded(Ui.surface, 26, this@MainActivity, Ui.border)
            setPadding(dp(16), dp(2), dp(4), dp(2))
        }
        input = EditText(this).apply {
            hint = "Message JARVIS…"
            textSize = 16f
            setTextColor(Ui.text)
            setHintTextColor(Ui.muted)
            background = null
            maxLines = 4
            imeOptions = EditorInfo.IME_ACTION_SEND
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_SENTENCES or InputType.TYPE_TEXT_FLAG_MULTI_LINE
            setOnEditorActionListener { _, _, _ -> send(); true }
        }
        pill.addView(input, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        pill.addView(Ui.iconButton(this, "➤", 42, filled = false) { send() }.apply {
            background = null
            setTextColor(Ui.primary)
        })
        composer.addView(pill, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        composer.addView(Ui.iconButton(this, "🎤", 52, filled = true) { ListenActivity.open(this) }.apply {
            (layoutParams as LinearLayout.LayoutParams).marginStart = dp(10)
        })
        root.addView(composer, Ui.matchWrap(8, this))

        Ui.show(this, root)
        CloudLink.addListener(this)
    }

    private fun showEmptyState() {
        val hint = Ui.column(this).apply { gravity = Gravity.CENTER; setPadding(dp(24), dp(48), dp(24), dp(24)) }
        hint.addView(Ui.text(this, "How can I help?", 20f, bold = true).apply { gravity = Gravity.CENTER })
        hint.addView(Ui.text(this,
            "Tap 🎤 or type. Try:\n“Find jobs that match my resume”\n“Open LinkedIn”\n“What's my laptop battery?”",
            15f, Ui.muted).apply { gravity = Gravity.CENTER }, Ui.matchWrap(8, this))
        emptyState = hint
        log.addView(hint, Ui.matchWrap(0, this))
    }

    private fun send(text: String = input.text.toString().trim()) {
        if (text.isEmpty()) return
        input.setText("")
        CloudLink.chat(text) // shown via onSent; queued if JARVIS is reconnecting
    }

    override fun onSent(text: String) {
        addBubble(text, fromUser = true)
        setStatus(if (CloudLink.connected) "Thinking…" else "Will send when connected…", Ui.primary)
    }

    override fun onStatus(connected: Boolean, message: String) {
        if (connected) setStatus("● Online", Ui.green) else setStatus(message, Ui.muted)
        if (!connected && message.startsWith("This phone's key was rejected")) showPairing()
    }

    override fun onTool(name: String) {
        if (!::log.isInitialized) return
        val label = TOOL_LABELS[name] ?: name.replace('_', ' ')
        val current = lastTool
        if (current != null && lastToolName == label) { // collapse repeats: "Searching jobs ×3"
            lastToolCount++
            current.text = "⚙  $label  ×$lastToolCount"
        } else {
            lastToolName = label
            lastToolCount = 1
            lastTool = Ui.text(this, "⚙  $label", 13f, Ui.muted).apply {
                background = Ui.rounded(Ui.primarySoft, 10, this@MainActivity)
                setPadding(dp(10), dp(4), dp(10), dp(4))
            }
            addRow(lastTool!!, alignEnd = false, topMargin = 4)
        }
        setStatus("Working: $label…", Ui.primary)
    }

    override fun onReply(text: String, isError: Boolean) {
        lastTool = null
        if (isError) {
            addRow(Ui.text(this, "⚠  $text", 15f, Ui.warn).apply {
                background = Ui.rounded(Ui.warnSoft, 14, this@MainActivity)
                setPadding(dp(14), dp(10), dp(14), dp(10))
            }, alignEnd = false, topMargin = 8)
        } else {
            addBubble(text, fromUser = false)
        }
        setStatus("● Online", Ui.green)
    }

    override fun onImages(ids: List<Int>) {
        ids.forEach { id ->
            thread {
                try {
                    val bytes = CloudLink.fetchImage(this, id)
                    val bitmap = android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return@thread
                    runOnUiThread { addImage(bitmap, bytes) }
                } catch (e: Exception) {
                    runOnUiThread { addBubble("(Couldn't load the picture: ${e.message})", fromUser = false) }
                }
            }
        }
    }

    private fun addImage(bitmap: android.graphics.Bitmap, bytes: ByteArray) {
        val width = (resources.displayMetrics.widthPixels * 0.7).toInt()
        val view = android.widget.ImageView(this).apply {
            setImageBitmap(bitmap)
            adjustViewBounds = true
            maxWidth = width
            clipToOutline = true
            background = Ui.rounded(Ui.surface, 18, this@MainActivity, Ui.border)
            layoutParams = LinearLayout.LayoutParams(width, LinearLayout.LayoutParams.WRAP_CONTENT)
            setOnClickListener {
                AlertDialog.Builder(this@MainActivity)
                    .setMessage("Save this picture to your gallery?")
                    .setPositiveButton("Save") { _, _ -> saveImage(bytes) }
                    .setNegativeButton("Cancel", null)
                    .show()
            }
        }
        addRow(view, alignEnd = false, topMargin = 8)
    }

    private fun saveImage(bytes: ByteArray) {
        val values = android.content.ContentValues().apply {
            put(android.provider.MediaStore.Images.Media.DISPLAY_NAME, "jarvis_${System.currentTimeMillis()}.jpg")
            put(android.provider.MediaStore.Images.Media.MIME_TYPE, "image/jpeg")
            put(android.provider.MediaStore.Images.Media.RELATIVE_PATH, "Pictures/JARVIS")
        }
        val uri = contentResolver.insert(android.provider.MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
        if (uri == null) {
            android.widget.Toast.makeText(this, "Couldn't save.", android.widget.Toast.LENGTH_SHORT).show()
            return
        }
        contentResolver.openOutputStream(uri)?.use { it.write(bytes) }
        android.widget.Toast.makeText(this, "Saved to Pictures/JARVIS", android.widget.Toast.LENGTH_SHORT).show()
    }

    private fun setStatus(text: String, color: Int) {
        if (!::status.isInitialized) return
        status.text = text
        status.setTextColor(color)
    }

    private fun addBubble(text: String, fromUser: Boolean) {
        lastTool = null
        val bubble = Ui.text(this, text, 16f, if (fromUser) Color.WHITE else Ui.text).apply {
            setTextIsSelectable(true)
            setPadding(dp(14), dp(10), dp(14), dp(10))
            background = android.graphics.drawable.GradientDrawable().apply {
                val r = dp(18).toFloat()
                val small = dp(4).toFloat()
                cornerRadii = if (fromUser) floatArrayOf(r, r, r, r, small, small, r, r) else floatArrayOf(r, r, r, r, r, r, small, small)
                setColor(if (fromUser) Ui.primary else Ui.surface)
                if (!fromUser) setStroke(dp(1), Ui.border)
            }
            maxWidth = (resources.displayMetrics.widthPixels * 0.8).toInt()
        }
        addRow(bubble, alignEnd = fromUser, topMargin = 10)
    }

    private fun addRow(view: View, alignEnd: Boolean, topMargin: Int) {
        if (!::log.isInitialized) return
        emptyState?.let { log.removeView(it); emptyState = null }
        val wrapper = LinearLayout(this).apply { gravity = if (alignEnd) Gravity.END else Gravity.START }
        wrapper.addView(view, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT))
        log.addView(wrapper, Ui.matchWrap(topMargin, this))
        scroll.post { scroll.fullScroll(View.FOCUS_DOWN) }
    }

    // ---------------- settings ----------------

    private fun showSettings() {
        val form = Ui.column(this).apply { setPadding(dp(22), dp(8), dp(22), dp(4)) }
        fun toggle(label: String, on: Boolean, change: (Boolean) -> Unit) = Switch(this).apply {
            text = label
            textSize = 16f
            setTextColor(Ui.text)
            isChecked = on
            setPadding(0, dp(10), 0, dp(10))
            setOnCheckedChangeListener { _, checked -> change(checked) }
        }
        form.addView(Ui.primaryButton(this, "🧠  What JARVIS remembers") { settingsDialog?.dismiss(); unlockVault(MEMORY_UNLOCK) },
            Ui.matchWrap(4, this))
        form.addView(Ui.primaryButton(this, "🔑  AI providers and keys") { settingsDialog?.dismiss(); unlockVault(PROVIDERS_UNLOCK) },
            Ui.matchWrap(8, this))
        form.addView(toggle("Speak replies", Prefs.speakReplies) { Prefs.speakReplies = it; if (!it) Speaker.stop() })
        form.addView(toggle("Floating 🎤 on all apps", Prefs.floatingMic(this)) { on ->
            Prefs.setFloatingMic(this, on)
            JarvisAccessibilityService.instance?.let { if (on) it.showBubble() else it.removeBubble() }
        })
        // Morning briefing: a daily time, or off.
        val briefingAt = Reminders.briefingTime(this)
        val briefingButton = Ui.softButton(this, if (briefingAt == null) "Morning briefing: off" else "Morning briefing: $briefingAt") {}
        briefingButton.setOnClickListener {
            val (h, m) = (briefingAt ?: "07:30").split(":").map { it.toInt() }
            android.app.TimePickerDialog(this, { _, hour, minute ->
                val time = "%02d:%02d".format(hour, minute)
                Reminders.setBriefing(this, time)
                briefingButton.text = "Morning briefing: $time"
            }, h, m, false).apply {
                setButton(android.content.DialogInterface.BUTTON_NEUTRAL, "Turn off") { _, _ ->
                    Reminders.setBriefing(this@MainActivity, null)
                    briefingButton.text = "Morning briefing: off"
                }
            }.show()
        }
        form.addView(briefingButton, Ui.matchWrap(10, this))
        form.addView(Ui.softButton(this, "Brief me now") { settingsDialog?.dismiss(); Reminders.briefNow(this) }, Ui.matchWrap(8, this))
        if (!Reminders.canBeExact(this) && Build.VERSION.SDK_INT >= 31) {
            form.addView(Ui.softButton(this, "Allow on-time reminders") {
                startActivity(Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, android.net.Uri.parse("package:$packageName")))
            }, Ui.matchWrap(8, this))
        }
        val controlOn = JarvisAccessibilityService.instance != null
        form.addView(Ui.text(this, if (controlOn) "Phone control: on" else "Phone control: off", 15f,
            if (controlOn) Ui.green else Ui.warn), Ui.matchWrap(10, this))
        form.addView(Ui.softButton(this, "Accessibility settings") { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) },
            Ui.matchWrap(8, this))
        form.addView(Ui.text(this, "Tip: add the JARVIS tile to Quick Settings, or set JARVIS as your digital assistant to open it with the power button.",
            13f, Ui.muted), Ui.matchWrap(14, this))
        settingsDialog = AlertDialog.Builder(this)
            .setTitle("Settings")
            .setView(form)
            .setPositiveButton("Done", null)
            .setNeutralButton("Disconnect phone") { _, _ ->
                AlertDialog.Builder(this)
                    .setMessage("Disconnect this phone from JARVIS? You'll need the password to connect again.")
                    .setPositiveButton("Disconnect") { _, _ ->
                        CloudLink.stop()
                        Prefs.forget(this)
                        stopService(Intent(this, LinkService::class.java))
                        showPairing()
                    }
                    .setNegativeButton("Cancel", null)
                    .show()
            }
            .show()
    }

    // ---------------- my details (vault) ----------------

    /** The vault screen is behind the phone's own screen lock (fingerprint / PIN). */
    private fun unlockVault(requestCode: Int = VAULT_UNLOCK) {
        val keyguard = getSystemService(KeyguardManager::class.java)
        if (!keyguard.isDeviceSecure) {
            AlertDialog.Builder(this)
                .setMessage("Your phone has no screen lock, so anyone holding it could open your details. Set a PIN or fingerprint in Settings for better protection.")
                .setPositiveButton("Open anyway") { _, _ ->
                    when (requestCode) { MEMORY_UNLOCK -> showMemory(); PROVIDERS_UNLOCK -> showProviders(); else -> showVault() }
                }
                .setNegativeButton("Cancel", null)
                .show()
            return
        }
        @Suppress("DEPRECATION")
        val intent = when (requestCode) {
            MEMORY_UNLOCK -> keyguard.createConfirmDeviceCredentialIntent("What JARVIS remembers", "Unlock to view or edit JARVIS's memory")
            PROVIDERS_UNLOCK -> keyguard.createConfirmDeviceCredentialIntent("AI providers", "Unlock to manage your API keys")
            else -> keyguard.createConfirmDeviceCredentialIntent("My details", "Unlock to view or edit your saved details")
        }
        startActivityForResult(intent, requestCode)
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == VAULT_UNLOCK && resultCode == RESULT_OK) showVault()
        if (requestCode == MEMORY_UNLOCK && resultCode == RESULT_OK) showMemory()
        if (requestCode == PROVIDERS_UNLOCK && resultCode == RESULT_OK) showProviders()
        if (requestCode == PICK_RESUME && resultCode == RESULT_OK) data?.data?.let { uploadResume(it) }
    }

    private fun showVault() {
        CloudLink.removeListener(this)
        val root = Ui.column(this)
        val header = Ui.row(this)
        header.addView(Ui.softButton(this, "‹ Back") { showChat() })
        header.addView(Ui.text(this, "My details", 22f, bold = true).apply { setPadding(dp(12), 0, 0, 0) },
            LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        root.addView(header, Ui.matchWrap(4, this))

        val list = Ui.column(this).apply { setPadding(0, 0, 0, dp(16)) }
        list.addView(Ui.text(this, "🔒 Encrypted on this phone. JARVIS's AI never sees these values, only which ones exist. Tap a detail to edit it.",
            14f, Ui.muted), Ui.matchWrap(10, this))
        list.addView(Ui.primaryButton(this, "📄  Upload resume (PDF)") { pickResume() }, Ui.matchWrap(14, this))

        val saved = Vault.load(this)
        val rows = Vault.TEMPLATE.map { (key, t) -> Triple(key, t, saved[key]) } +
            saved.values.filter { it.key !in Vault.TEMPLATE }.map { Triple(it.key, Triple(it.label, it.category, it.sensitive), it) }
        rows.groupBy { it.second.second }.forEach { (category, items) ->
            list.addView(Ui.text(this, category.uppercase(), 12f, Ui.muted, bold = true).apply { letterSpacing = 0.1f },
                Ui.matchWrap(20, this))
            val card = Ui.card(this).apply { setPadding(dp(16), dp(4), dp(16), dp(4)) }
            items.forEachIndexed { index, (key, template, entry) ->
                val (labelText, _, sensitive) = template
                if (index > 0) card.addView(View(this).apply { setBackgroundColor(Ui.border) },
                    LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 1))
                val item = Ui.column(this).apply {
                    setPadding(0, dp(10), 0, dp(10))
                    isClickable = true
                    setOnClickListener { editField(key, labelText, sensitive, entry?.value) }
                }
                item.addView(Ui.text(this, labelText + if (sensitive) "  🔒" else "", 13f, Ui.muted))
                item.addView(Ui.text(this, when {
                    entry == null -> "Not set"
                    sensitive -> Vault.mask(entry.value)
                    else -> entry.value
                }, 16f, if (entry == null) Ui.muted else Ui.text))
                card.addView(item)
            }
            list.addView(card, Ui.matchWrap(8, this))
        }
        list.addView(Ui.softButton(this, "+  Add a custom detail") { addCustomField() }, Ui.matchWrap(16, this))
        root.addView(ScrollView(this).apply { addView(list) },
            LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        Ui.show(this, root)
    }

    private fun editField(key: String, labelText: String, sensitive: Boolean, current: String?) {
        val box = Ui.field(this, labelText, current.orEmpty()).apply {
            if (sensitive) inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD
        }
        val frame = Ui.column(this).apply { setPadding(dp(22), dp(8), dp(22), 0); addView(box) }
        AlertDialog.Builder(this)
            .setTitle(labelText)
            .setView(frame)
            .setPositiveButton("Save") { _, _ ->
                val value = box.text.toString().trim()
                if (value.isEmpty()) Vault.delete(this, key) else Vault.set(this, key, value)
                showVault()
            }
            .setNeutralButton("Clear") { _, _ -> Vault.delete(this, key); showVault() }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun addCustomField() {
        val name = Ui.field(this, "Detail name, e.g. Employee ID")
        val value = Ui.field(this, "Value")
        val secret = CheckBox(this).apply { text = "Sensitive (an ID or account number)"; setTextColor(Ui.text) }
        val form = Ui.column(this).apply {
            setPadding(dp(22), dp(8), dp(22), 0)
            addView(name)
            addView(value, Ui.matchWrap(10, this@MainActivity))
            addView(secret, Ui.matchWrap(8, this@MainActivity))
        }
        AlertDialog.Builder(this)
            .setTitle("Add a detail")
            .setView(form)
            .setPositiveButton("Save") { _, _ ->
                val label = name.text.toString().trim()
                if (label.isNotEmpty() && value.text.isNotBlank()) {
                    val key = label.lowercase().replace(Regex("[^a-z0-9]+"), "_").trim('_')
                    Vault.set(this, key, value.text.toString().trim(), label, secret.isChecked)
                }
                showVault()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    // ---------------- AI providers (your own API keys) ----------------

    private fun showProviders() {
        CloudLink.removeListener(this)
        val root = Ui.column(this)
        val header = Ui.row(this)
        header.addView(Ui.softButton(this, "‹ Back") { showChat() })
        header.addView(Ui.text(this, "AI providers", 22f, bold = true).apply { setPadding(dp(12), 0, 0, 0) },
            LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        root.addView(header, Ui.matchWrap(4, this))
        val body = Ui.column(this).apply { setPadding(0, 0, 0, dp(16)) }
        body.addView(Ui.text(this, "Loading…", 15f, Ui.muted), Ui.matchWrap(16, this))
        root.addView(ScrollView(this).apply { addView(body) }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        Ui.show(this, root)
        settingsCall(org.json.JSONObject().put("action", "list")) { renderProviders(body, it) }
    }

    private fun settingsCall(request: org.json.JSONObject, done: (org.json.JSONObject) -> Unit) {
        thread {
            try {
                val result = CloudLink.request(request.put("type", "settings"), 90)
                runOnUiThread {
                    if (result.has("error")) AlertDialog.Builder(this).setMessage(result.getString("error")).setPositiveButton("OK", null).show()
                    else {
                        result.optString("message").takeIf { it.isNotEmpty() }?.let {
                            android.widget.Toast.makeText(this, it, android.widget.Toast.LENGTH_SHORT).show()
                        }
                        done(result)
                    }
                }
            } catch (e: Exception) {
                runOnUiThread { AlertDialog.Builder(this).setMessage(e.message ?: "Couldn't reach JARVIS.").setPositiveButton("OK", null).show() }
            }
        }
    }

    private fun renderProviders(body: LinearLayout, result: org.json.JSONObject) {
        body.removeAllViews()
        val all = result.getJSONArray("providers").let { a -> (0 until a.length()).map { a.getJSONObject(it) } }
        fun kinds(p: org.json.JSONObject) = p.getJSONArray("kinds").let { k -> (0 until k.length()).map { k.getString(it) } }
        body.addView(Ui.text(this, "Keys are stored encrypted in your cloud JARVIS and never shown to the AI. If a provider fails, JARVIS falls back to Gemini.",
            14f, Ui.muted), Ui.matchWrap(10, this))

        // Which AI runs the chat
        body.addView(Ui.text(this, "CHAT BRAIN", 12f, Ui.muted, bold = true), Ui.matchWrap(20, this))
        val chat = android.widget.RadioGroup(this)
        all.filter { "chat" in kinds(it) && it.getBoolean("connected") }.forEach { p ->
            chat.addView(android.widget.RadioButton(this).apply {
                text = p.getString("name") + (p.optString("model").takeIf { m -> m.isNotEmpty() && m != "gemini" }?.let { m -> " · $m" } ?: "")
                setTextColor(Ui.text)
                isChecked = result.optString("chat_provider") == p.getString("id")
                setOnClickListener { settingsCall(org.json.JSONObject().put("action", "route").put("kind", "chat").put("choice", p.getString("id"))) { renderProviders(body, it) } }
            })
        }
        body.addView(Ui.card(this).apply { addView(chat) }, Ui.matchWrap(8, this))

        // Which service makes pictures
        body.addView(Ui.text(this, "PICTURES", 12f, Ui.muted, bold = true), Ui.matchWrap(20, this))
        val pictures = android.widget.RadioGroup(this)
        val imageChoices = listOf("auto" to "Automatic (free first)") +
            all.filter { "images" in kinds(it) && it.getBoolean("connected") }.map { it.getString("id") to it.getString("name") }
        imageChoices.forEach { (id, name) ->
            pictures.addView(android.widget.RadioButton(this).apply {
                text = name
                setTextColor(Ui.text)
                isChecked = result.optString("image_provider") == id
                setOnClickListener { settingsCall(org.json.JSONObject().put("action", "route").put("kind", "images").put("choice", id)) { renderProviders(body, it) } }
            })
        }
        body.addView(Ui.card(this).apply { addView(pictures) }, Ui.matchWrap(8, this))

        // Every provider, with its key
        body.addView(Ui.text(this, "PROVIDERS", 12f, Ui.muted, bold = true), Ui.matchWrap(20, this))
        all.forEach { p ->
            val card = Ui.card(this)
            card.addView(Ui.text(this, p.getString("name"), 16f, bold = true))
            card.addView(Ui.text(this, p.optString("note"), 13f, Ui.muted), Ui.matchWrap(2, this))
            val status = when {
                p.optBoolean("no_key") -> "Free, no key needed"
                p.optBoolean("own_key") -> "Connected · ••••" + p.optString("last4")
                p.getBoolean("connected") -> "Connected (JARVIS's own key)"
                else -> "Not set"
            }
            card.addView(Ui.text(this, status, 14f, if (p.getBoolean("connected")) Ui.green else Ui.muted), Ui.matchWrap(6, this))
            if (!p.optBoolean("no_key")) {
                val buttons = Ui.row(this)
                buttons.addView(Ui.softButton(this, if (p.optBoolean("own_key")) "Change key" else "Add key") { addKey(body, p) })
                if (p.optBoolean("own_key")) buttons.addView(Ui.softButton(this, "Remove") {
                    settingsCall(org.json.JSONObject().put("action", "remove_key").put("provider", p.getString("id"))) { renderProviders(body, it) }
                }.apply { (layoutParams as? LinearLayout.LayoutParams)?.marginStart = dp(8) })
                buttons.addView(Ui.softButton(this, "Get a key") {
                    startActivity(Intent(Intent.ACTION_VIEW, android.net.Uri.parse(p.getString("signup"))))
                })
                card.addView(buttons, Ui.matchWrap(8, this))
            }
            body.addView(card, Ui.matchWrap(8, this))
        }
    }

    private fun addKey(body: LinearLayout, provider: org.json.JSONObject) {
        val key = Ui.field(this, "Paste the API key").apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD
        }
        val extra = provider.optString("needs_extra").takeIf { it.isNotEmpty() }?.let { Ui.field(this, it) }
        val form = Ui.column(this).apply {
            setPadding(dp(22), dp(8), dp(22), 0)
            addView(key)
            extra?.let { addView(it, Ui.matchWrap(10, this@MainActivity)) }
            addView(Ui.text(this@MainActivity, "JARVIS tests the key before saving it.", 13f, Ui.muted), Ui.matchWrap(8, this@MainActivity))
        }
        AlertDialog.Builder(this)
            .setTitle(provider.getString("name"))
            .setView(form)
            .setPositiveButton("Test and save") { _, _ ->
                val request = org.json.JSONObject().put("action", "save_key").put("provider", provider.getString("id"))
                    .put("key", key.text.toString().trim()).put("extra", extra?.text?.toString()?.trim().orEmpty())
                settingsCall(request) { renderProviders(body, it) }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    // ---------------- what JARVIS remembers (Memory 2.0) ----------------

    private fun showMemory() {
        CloudLink.removeListener(this)
        val root = Ui.column(this)
        val header = Ui.row(this)
        header.addView(Ui.softButton(this, "‹ Back") { showChat() })
        header.addView(Ui.text(this, "Memory", 22f, bold = true).apply { setPadding(dp(12), 0, 0, 0) },
            LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        root.addView(header, Ui.matchWrap(4, this))
        val list = Ui.column(this).apply { setPadding(0, 0, 0, dp(16)) }
        list.addView(Ui.text(this, "What JARVIS has learned about you. It updates these by itself as you talk; tap one to fix or delete it.",
            14f, Ui.muted), Ui.matchWrap(10, this))
        list.addView(Ui.primaryButton(this, "+  Add a memory") { editMemory(null) }, Ui.matchWrap(14, this))
        val body = Ui.column(this)
        body.addView(Ui.text(this, "Loading…", 15f, Ui.muted), Ui.matchWrap(16, this))
        list.addView(body)
        root.addView(ScrollView(this).apply { addView(list) }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        Ui.show(this, root)
        memoryCall(org.json.JSONObject().put("action", "list")) { renderMemories(body, it) }
    }

    /** Runs a memory request on a background thread, then updates the screen. */
    private fun memoryCall(request: org.json.JSONObject, done: (org.json.JSONObject) -> Unit) {
        thread {
            try {
                val result = CloudLink.request(request.put("type", "memory"))
                runOnUiThread {
                    if (result.has("error")) AlertDialog.Builder(this).setMessage(result.getString("error")).setPositiveButton("OK", null).show()
                    else done(result)
                }
            } catch (e: Exception) {
                runOnUiThread { AlertDialog.Builder(this).setMessage(e.message ?: "Couldn't reach JARVIS.").setPositiveButton("OK", null).show() }
            }
        }
    }

    private fun renderMemories(body: LinearLayout, result: org.json.JSONObject) {
        body.removeAllViews()
        val items = result.optJSONArray("items") ?: org.json.JSONArray()
        if (items.length() == 0) {
            body.addView(Ui.text(this, "Nothing yet. JARVIS will learn as you talk.", 15f, Ui.muted), Ui.matchWrap(16, this))
            return
        }
        val byKind = (0 until items.length()).map { items.getJSONObject(it) }.groupBy { it.optString("kind", "fact") }
        listOf("person", "place", "project", "goal", "preference", "routine", "fact").filter { it in byKind }.forEach { kind ->
            body.addView(Ui.text(this, KIND_LABELS[kind] ?: kind.uppercase(), 12f, Ui.muted, bold = true).apply { letterSpacing = 0.1f },
                Ui.matchWrap(20, this))
            val card = Ui.card(this).apply { setPadding(dp(16), dp(4), dp(16), dp(4)) }
            byKind.getValue(kind).forEachIndexed { index, item ->
                if (index > 0) card.addView(View(this).apply { setBackgroundColor(Ui.border) },
                    LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 1))
                val star = if (item.optInt("importance") >= 4) "  ★" else ""
                card.addView(Ui.text(this, item.optString("text") + star, 15f).apply {
                    setPadding(0, dp(12), 0, dp(12))
                    setOnClickListener { editMemory(item) }
                })
            }
            body.addView(card, Ui.matchWrap(8, this))
        }
    }

    private fun editMemory(item: org.json.JSONObject?) {
        val box = Ui.field(this, "e.g. I prefer remote jobs", item?.optString("text").orEmpty()).apply { isSingleLine = false }
        val important = CheckBox(this).apply {
            text = "Important (always remembered)"
            setTextColor(Ui.text)
            isChecked = (item?.optInt("importance") ?: 3) >= 4
        }
        val form = Ui.column(this).apply {
            setPadding(dp(22), dp(8), dp(22), 0)
            addView(box)
            addView(important, Ui.matchWrap(8, this@MainActivity))
        }
        val dialog = AlertDialog.Builder(this)
            .setTitle(if (item == null) "Add a memory" else "Edit memory")
            .setView(form)
            .setPositiveButton("Save") { _, _ ->
                val text = box.text.toString().trim()
                if (text.isNotEmpty()) {
                    val request = org.json.JSONObject().put("text", text).put("importance", if (important.isChecked) 5 else 3)
                    if (item == null) request.put("action", "add") else request.put("action", "update").put("memory_id", item.getInt("id"))
                    memoryCall(request) { showMemory() }
                }
            }
            .setNegativeButton("Cancel", null)
        if (item != null) dialog.setNeutralButton("Delete") { _, _ ->
            memoryCall(org.json.JSONObject().put("action", "delete").put("memory_id", item.getInt("id"))) { showMemory() }
        }
        dialog.show()
    }

    // ---------------- resume ----------------

    private fun pickResume() {
        @Suppress("DEPRECATION")
        startActivityForResult(
            Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/pdf"),
            PICK_RESUME,
        )
    }

    private fun uploadResume(uri: android.net.Uri) {
        val waiting = AlertDialog.Builder(this)
            .setMessage("JARVIS is reading your resume… (up to a minute)")
            .setCancelable(false)
            .show()
        thread {
            try {
                var name = "resume.pdf"
                contentResolver.query(uri, null, null, null, null)?.use { cursor ->
                    val column = cursor.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
                    if (column >= 0 && cursor.moveToFirst()) name = cursor.getString(column)
                }
                val bytes = contentResolver.openInputStream(uri)!!.use { it.readBytes() }
                val result = CloudLink.uploadResume(this, bytes, name)
                runOnUiThread { waiting.dismiss(); offerVaultDetails(result) }
            } catch (e: Exception) {
                runOnUiThread {
                    waiting.dismiss()
                    AlertDialog.Builder(this).setMessage(e.message ?: "Upload failed.").setPositiveButton("OK", null).show()
                }
            }
        }
    }

    /** Show what JARVIS learned, and let the user pick which details to save on the phone. */
    private fun offerVaultDetails(result: org.json.JSONObject) {
        val saved = Vault.load(this)
        val suggestions = result.optJSONObject("vault_suggestions") ?: org.json.JSONObject()
        val form = Ui.column(this).apply { setPadding(dp(22), dp(8), dp(22), 0) }
        form.addView(Ui.text(this, result.optString("summary"), 15f))
        val roles = result.optJSONArray("suggested_roles")
        if (roles != null && roles.length() > 0) {
            form.addView(Ui.text(this, "Roles that suit you: " + (0 until roles.length()).joinToString { roles.getString(it) },
                15f, Ui.primary), Ui.matchWrap(12, this))
        }
        val boxes = mutableListOf<Pair<CheckBox, Pair<String, String>>>()
        if (suggestions.length() > 0) {
            form.addView(Ui.text(this, "Add these to My details?", 15f, bold = true), Ui.matchWrap(16, this))
            suggestions.keys().forEach { key ->
                val value = suggestions.getString(key)
                val box = CheckBox(this).apply {
                    text = "${Vault.TEMPLATE[key]?.first ?: key}: $value"
                    setTextColor(Ui.text)
                    isChecked = saved[key]?.value.isNullOrBlank() // new details ticked; existing ones left as they are
                }
                form.addView(box)
                boxes += box to (key to value)
            }
        }
        AlertDialog.Builder(this)
            .setTitle("JARVIS read your resume")
            .setView(ScrollView(this).apply { addView(form) })
            .setPositiveButton("Save ticked") { _, _ ->
                boxes.filter { it.first.isChecked }.forEach { (_, kv) -> Vault.set(this, kv.first, kv.second) }
                showVault()
            }
            .setNegativeButton("Skip", null)
            .show()
    }

    companion object {
        private const val VAULT_UNLOCK = 3
        private const val PICK_RESUME = 4
        private const val MEMORY_UNLOCK = 5
        private const val PROVIDERS_UNLOCK = 6

        private val KIND_LABELS = mapOf(
            "person" to "PEOPLE", "place" to "PLACES", "project" to "PROJECTS", "goal" to "GOALS",
            "preference" to "PREFERENCES", "routine" to "ROUTINES", "fact" to "OTHER FACTS",
        )

        /** Friendly names for what JARVIS is doing. */
        private val TOOL_LABELS = mapOf(
            "find_jobs" to "Searching jobs", "get_resume_profile" to "Reading your resume",
            "shortlist_job" to "Saving to shortlist", "list_jobs" to "Checking your jobs",
            "update_job_status" to "Updating job status", "web_search" to "Searching the web",
            "get_datetime" to "Checking the time", "remember" to "Remembering", "forget" to "Forgetting",
            "recall_conversations" to "Recalling past chats", "phone_open_app" to "Opening app",
            "phone_open_url" to "Opening link", "phone_read_screen" to "Reading the screen",
            "phone_tap" to "Tapping", "phone_type" to "Typing", "phone_press" to "Pressing a button",
            "phone_scroll" to "Scrolling", "phone_status" to "Checking the phone",
            "phone_fill_field" to "Filling in your details", "vault_list_fields" to "Checking your saved details",
            "vault_save_field" to "Saving a detail", "system_status" to "Checking the laptop",
            "generate_image" to "Creating a picture", "get_weather" to "Checking the weather",
            "phone_actions" to "Working on the phone", "phone_set_reminder" to "Setting a reminder",
        )
    }
}
