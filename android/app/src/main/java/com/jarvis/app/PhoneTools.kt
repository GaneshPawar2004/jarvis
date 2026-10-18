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
        tool("phone_read_screen", "Read what is on the phone's screen as a numbered list of elements (buttons, text, input fields). " +
            "Use the numbers with phone_tap and phone_type. Read again after each action to see the result."),
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
    ))

    // ---- running a tool ----

    fun run(context: Context, tool: String, args: JSONObject): Any = when (tool) {
        "phone_open_app" -> openApp(context, args.getString("name"))
        "phone_list_apps" -> JSONArray(launchable(context).keys.sorted())
        "phone_read_screen" -> JSONObject().put("app", service().currentApp()).put("elements", JSONArray(service().readScreen()))
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

    private fun status(context: Context): JSONObject {
        val battery = context.getSystemService(BatteryManager::class.java)
        return JSONObject()
            .put("battery_percent", battery.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY))
            .put("charging", battery.isCharging)
            .put("app_on_screen", JarvisAccessibilityService.instance?.currentApp() ?: "unknown (phone control is off)")
            .put("phone_control_enabled", JarvisAccessibilityService.instance != null)
    }
}
