package com.jarvis.app

import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioManager
import android.os.BatteryManager
import android.provider.Settings
import org.json.JSONArray
import org.json.JSONObject

/** The phone_* tools cloud JARVIS can call on this phone. Same names and meaning as the
 *  laptop's ADB versions, so JARVIS uses them the same way — but no laptop is needed. */
object PhoneTools {
    private val RISKY = Regex(
        "\\b(submit|send|pay|payment|post|apply|place order|buy|purchase|confirm|book|delete|remove|" +
            "transfer|checkout|proceed to pay|share|publish|sign up|register)\\b",
        RegexOption.IGNORE_CASE
    )
    private val ALIASES = mapOf("insta" to "instagram", "yt" to "youtube", "fb" to "facebook", "gpay" to "google pay", "x" to "twitter")
    private val INTENT_APPS = mapOf(
        "settings" to Intent(Settings.ACTION_SETTINGS),
        "wifi settings" to Intent(Settings.ACTION_WIFI_SETTINGS),
        "bluetooth settings" to Intent(Settings.ACTION_BLUETOOTH_SETTINGS),
        "camera" to Intent("android.media.action.STILL_IMAGE_CAMERA"),
        "phone" to Intent(Intent.ACTION_DIAL),
        "dialer" to Intent(Intent.ACTION_DIAL),
    )

    // ---- declarations sent to the cloud (Gemini function-declaration format) ----

    private fun tool(name: String, description: String, vararg params: Triple<String, String, String>, required: List<String> = params.map { it.first }): JSONObject {
        val json = JSONObject().put("name", name).put("description", description)
        if (params.isNotEmpty()) {
            val props = JSONObject()
            params.forEach { (p, type, desc) -> props.put(p, JSONObject().put("type", type).put("description", desc)) }
            json.put("parameters", JSONObject().put("type", "OBJECT").put("properties", props).put("required", JSONArray(required)))
        }
        return json
    }

    fun declarations(): JSONArray = JSONArray(listOf(
        tool("phone_open_app", "Open an app on the user's Android phone, by its name (e.g. \"LinkedIn\", \"WhatsApp\", \"camera\", \"settings\").",
            Triple("name", "STRING", "The app's name.")),
        tool("phone_list_apps", "List the names of the apps installed on the user's phone."),
        tool("phone_open_url", "Open a web link on the phone, e.g. a job post. LinkedIn and Naukri links open in their apps when installed.",
            Triple("url", "STRING", "The full https:// link.")),
        tool("phone_read_screen", "Read what is on the phone's screen as a numbered list of elements (buttons, text, input fields). " +
            "Every phone action already returns the screen afterwards (screen_after), so you only need this at the start."),
        tool("phone_tap", "Tap an element on the phone screen. Buttons like Submit, Send, Pay, Apply or Delete ask the user's permission first.",
            Triple("element_number", "INTEGER", "The element's number from the latest phone_read_screen.")),
        tool("phone_type", "Type text into an input field on the phone (any language).",
            Triple("text", "STRING", "The text to type."),
            Triple("element_number", "INTEGER", "Input field number from phone_read_screen; 0 types into the field that is already selected."),
            required = listOf("text")),
        tool("phone_press", "Press a phone button: \"back\", \"home\", \"recent apps\", \"notifications\", \"enter\", \"volume up\", \"volume down\".",
            Triple("key", "STRING", "Which button.")),
        tool("phone_scroll", "Scroll the phone screen: \"down\" (see content further down), \"up\", \"left\" or \"right\".",
            Triple("direction", "STRING", "Which way.")),
        tool("phone_status", "Get the phone's battery level, charging state and the app currently on screen."),
        JSONObject()
            .put("name", "phone_actions")
            .put("description", "Do several phone steps in ONE call, e.g. tap the search box, type a query, press enter. " +
                "Much faster than separate calls. Element numbers refer to the latest screen you saw. Stops at the first step " +
                "that fails or that the user doesn't allow. Returns each step's result and the screen afterwards.")
            .put("parameters", JSONObject().put("type", "OBJECT").put("required", JSONArray(listOf("steps"))).put("properties",
                JSONObject().put("steps", JSONObject().put("type", "ARRAY").put("description", "The steps, in order.").put("items",
                    JSONObject().put("type", "OBJECT").put("required", JSONArray(listOf("action"))).put("properties", JSONObject()
                        .put("action", JSONObject().put("type", "STRING").put("description", "tap, type, fill, press or scroll"))
                        .put("element_number", JSONObject().put("type", "INTEGER").put("description", "For tap, type (0 = selected field) and fill"))
                        .put("text", JSONObject().put("type", "STRING").put("description", "For type"))
                        .put("field_key", JSONObject().put("type", "STRING").put("description", "For fill: a vault key such as email"))
                        .put("key", JSONObject().put("type", "STRING").put("description", "For press: back, home, enter..."))
                        .put("direction", JSONObject().put("type", "STRING").put("description", "For scroll: up, down, left, right"))))))),
        tool("vault_list_fields", "List the user's saved personal details (name, email, address, education, work, " +
            "ID numbers...) by key and label. Values are hidden; fill them into forms with phone_fill_field."),
        tool("phone_fill_field", "Fill an input field on the phone with one of the user's saved details. The real value " +
            "is typed by the phone itself and never shown to you. ID numbers ask the user's permission first.",
            Triple("element_number", "INTEGER", "The input field's number from the latest phone_read_screen."),
            Triple("field_key", "STRING", "The vault key to fill in, e.g. \"email\", \"full_name\", \"pincode\".")),
        tool("vault_save_field", "Save a non-sensitive detail the user told you (e.g. a new email or city) into the " +
            "phone's vault for future forms. ID numbers must be added by the user in the app's My details screen.",
            Triple("key", "STRING", "Short snake_case key, e.g. \"email\", \"city\"."),
            Triple("value", "STRING", "The value the user gave."),
            Triple("label", "STRING", "Human-readable name; optional for standard keys."),
            required = listOf("key", "value")),
    ))

    // ---- running a tool ----

    fun run(context: Context, tool: String, args: JSONObject): Any {
        val service = JarvisAccessibilityService.instance
        service?.working(true)
        try {
            return runTool(context, tool, args)
        } finally {
            service?.working(false)
        }
    }

    /** Actions that change the screen: their result includes the screen afterwards, so the
     *  AI doesn't need a separate read (that halves the steps of a phone task). */
    private val ACTIONS = setOf("phone_open_app", "phone_open_url", "phone_tap", "phone_type", "phone_press",
        "phone_scroll", "phone_fill_field", "phone_actions")

    private fun runTool(context: Context, tool: String, args: JSONObject): Any {
        val result = runOne(context, tool, args)
        if (tool !in ACTIONS || JarvisAccessibilityService.instance == null) return result
        val out = if (result is JSONObject) result else JSONObject().put("result", result)
        return try {
            out.put("screen_after", screen(context))
        } catch (e: Exception) {
            out.put("screen_after", "Couldn't read the screen (it may be protected).")
        }
    }

    private fun screen(context: Context): JSONObject {
        val saved = Vault.load(context).values  // the AI never sees the user's saved details
        return JSONObject().put("app", service().currentApp())
            .put("elements", JSONArray(service().readScreen().map { Vault.redact(it, saved) }))
    }

    /** phone_actions: several steps without re-reading the screen in between. */
    private fun actions(context: Context, steps: JSONArray): JSONObject {
        val results = JSONArray()
        for (i in 0 until steps.length()) {
            val step = steps.getJSONObject(i)
            val message = try {
                when (step.optString("action").trim().lowercase()) {
                    "tap" -> tap(context, step.getInt("element_number"))
                    "type" -> { service().type(step.getString("text"), step.optInt("element_number", 0)); "Typed." }
                    "fill" -> fillField(context, step.getInt("element_number"), step.getString("field_key"))
                    "press" -> press(context, step.getString("key").trim().lowercase())
                    "scroll" -> { service().scroll(step.getString("direction").trim().lowercase()); "Scrolled." }
                    else -> "Unknown action '${step.optString("action")}'."
                }
            } catch (e: Exception) {
                "Failed: ${e.message}"
            }
            results.put("${i + 1}. $message")
            if (message.startsWith("Failed") || message.startsWith("Unknown") || message.contains("did NOT allow")) {
                results.put("Stopped here.")
                break
            }
        }
        return JSONObject().put("steps", results)
    }

    private fun runOne(context: Context, tool: String, args: JSONObject): Any = when (tool) {
        "phone_open_app" -> openApp(context, args.getString("name"))
        "phone_list_apps" -> JSONArray(launchable(context).keys.sorted())
        "phone_open_url" -> openUrl(context, args.getString("url"))
        "phone_read_screen" -> screen(context)
        "phone_actions" -> actions(context, args.getJSONArray("steps"))
        "phone_tap" -> tap(context, args.getInt("element_number"))
        "phone_type" -> {
            service().type(args.getString("text"), args.optInt("element_number", 0))
            "Typed the text on the phone."
        }
        "phone_press" -> press(context, args.getString("key").trim().lowercase())
        "phone_scroll" -> {
            service().scroll(args.getString("direction").trim().lowercase())
            "Scrolled."
        }
        "phone_status" -> status(context)
        "vault_list_fields" -> listFields(context)
        "phone_fill_field" -> fillField(context, args.getInt("element_number"), args.getString("field_key"))
        "vault_save_field" -> saveField(context, args.getString("key"), args.getString("value"), args.optString("label").ifBlank { null })
        else -> throw IllegalArgumentException("Unknown phone tool $tool")
    }

    private fun service(): JarvisAccessibilityService = JarvisAccessibilityService.instance
        ?: throw IllegalStateException("JARVIS phone control is off. On the phone: Settings → Accessibility → JARVIS phone control → On.")

    private fun launchable(context: Context): Map<String, Intent> {
        val pm = context.packageManager
        val query = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        return pm.queryIntentActivities(query, PackageManager.MATCH_ALL).associate { info ->
            info.loadLabel(pm).toString() to Intent(Intent.ACTION_MAIN)
                .addCategory(Intent.CATEGORY_LAUNCHER)
                .setClassName(info.activityInfo.packageName, info.activityInfo.name)
        }
    }

    private fun openApp(context: Context, name: String): String {
        val key = name.trim().lowercase().let { ALIASES[it] ?: it }
        val intent = INTENT_APPS[key] ?: run {
            val apps = launchable(context)
            val exact = apps.entries.firstOrNull { it.key.lowercase() == key }
            val partial = apps.entries.filter { it.key.lowercase().contains(key) || key.contains(it.key.lowercase()) }
            when {
                exact != null -> exact.value
                partial.size == 1 -> partial.first().value
                partial.size > 1 -> return "Several apps match '$name': ${partial.joinToString { it.key }}. Say which one."
                else -> return "No app called '$name' is installed. Use phone_list_apps to see what is installed."
            }
        }
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        // Starting from the accessibility service is allowed even while JARVIS is in the background.
        (JarvisAccessibilityService.instance ?: context).startActivity(intent)
        Thread.sleep(1500)
        return "Opened $name on the phone."
    }

    private fun openUrl(context: Context, url: String): String {
        if (!url.startsWith("https://") && !url.startsWith("http://")) return "Only web links (https://…) can be opened."
        val intent = Intent(Intent.ACTION_VIEW, android.net.Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        (JarvisAccessibilityService.instance ?: context).startActivity(intent)
        Thread.sleep(2500)
        return "Opened the link on the phone."
    }

    private fun tap(context: Context, number: Int): String {
        val label = service().element(number).label
        if (RISKY.containsMatchIn(label) && !ConfirmCenter.ask(context, "JARVIS wants to tap '$label' on your phone. Allow?")) {
            return "The user did NOT allow tapping '$label'. Do not retry unless they ask again."
        }
        service().tap(number)
        return "Tapped '$label'."
    }

    private fun press(context: Context, key: String): String {
        val audio = context.getSystemService(AudioManager::class.java)
        when (key) {
            "back" -> service().performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
            "home" -> service().performGlobalAction(AccessibilityService.GLOBAL_ACTION_HOME)
            "recent apps", "recents" -> service().performGlobalAction(AccessibilityService.GLOBAL_ACTION_RECENTS)
            "notifications" -> service().performGlobalAction(AccessibilityService.GLOBAL_ACTION_NOTIFICATIONS)
            "enter", "search" -> if (!service().pressEnter()) return "No text field is selected to press enter in."
            "volume up" -> audio.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_RAISE, AudioManager.FLAG_SHOW_UI)
            "volume down" -> audio.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_LOWER, AudioManager.FLAG_SHOW_UI)
            else -> return "Unknown key '$key'."
        }
        Thread.sleep(500)
        return "Pressed $key."
    }

    private fun listFields(context: Context): Any {
        val entries = Vault.load(context).values
        if (entries.isEmpty()) return "The vault is empty. The user can add details in the JARVIS app: MY DETAILS."
        return JSONArray(entries.map {
            JSONObject().put("key", it.key).put("label", it.label).put("category", it.category).put("sensitive", it.sensitive)
        })
    }

    private fun fillField(context: Context, number: Int, key: String): String {
        val entry = Vault.load(context)[key]
            ?: return "'$key' is not saved. Ask the user for it, or check vault_list_fields."
        if (entry.sensitive && !ConfirmCenter.ask(context, "Fill your ${entry.label} into the form on your phone?")) {
            return "The user did NOT allow filling their ${entry.label}."
        }
        service().type(entry.value, number)
        return "Filled the field with the user's ${entry.label}."
    }

    private fun saveField(context: Context, key: String, value: String, label: String?): String {
        val clean = key.trim().lowercase().replace(' ', '_')
        if (Vault.TEMPLATE[clean]?.third == true) {
            return "ID numbers must be added by the user in the JARVIS app (MY DETAILS), not through chat."
        }
        Vault.set(context, clean, value, label)
        return "Saved ${label ?: clean} to the phone's vault."
    }

    private fun status(context: Context): JSONObject {
        val battery = context.getSystemService(BatteryManager::class.java)
        return JSONObject()
            .put("battery_percent", battery.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY))
            .put("charging", battery.isCharging)
            .put("app_on_screen", JarvisAccessibilityService.instance?.currentApp() ?: "unknown (phone control is off)")
            .put("phone_control_enabled", JarvisAccessibilityService.instance != null)
    }
}
