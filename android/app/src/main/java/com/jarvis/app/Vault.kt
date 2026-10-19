package com.jarvis.app

import android.content.Context
import org.json.JSONObject

/** The user's personal details for form filling, encrypted on the phone (see Crypto).
 *  Cloud JARVIS only ever sees field names; values are typed locally by the app. */
object Vault {
    data class Entry(val key: String, val label: String, val category: String, val sensitive: Boolean, val value: String)

    /** Suggested fields: key to (label, category, sensitive). Same keys as the laptop vault. */
    val TEMPLATE = linkedMapOf(
        "full_name" to Triple("Full name", "Basic", false),
        "first_name" to Triple("First name", "Basic", false),
        "last_name" to Triple("Last name", "Basic", false),
        "email" to Triple("Email", "Basic", false),
        "phone" to Triple("Mobile number", "Basic", false),
        "date_of_birth" to Triple("Date of birth (DD/MM/YYYY)", "Basic", false),
        "gender" to Triple("Gender", "Basic", false),
        "father_name" to Triple("Father's name", "Basic", false),
        "address_line1" to Triple("Address line 1", "Address", false),
        "address_line2" to Triple("Address line 2", "Address", false),
        "city" to Triple("City", "Address", false),
        "state" to Triple("State", "Address", false),
        "pincode" to Triple("PIN code", "Address", false),
        "country" to Triple("Country", "Address", false),
        "job_title" to Triple("Current job title", "Work", false),
        "company" to Triple("Current company", "Work", false),
        "experience_years" to Triple("Years of experience", "Work", false),
        "skills" to Triple("Skills", "Work", false),
        "linkedin_url" to Triple("LinkedIn profile URL", "Work", false),
        "portfolio_url" to Triple("Portfolio / GitHub URL", "Work", false),
        "college" to Triple("College / university", "Education", false),
        "degree" to Triple("Degree", "Education", false),
        "branch" to Triple("Branch / specialisation", "Education", false),
        "graduation_year" to Triple("Graduation year", "Education", false),
        "cgpa" to Triple("CGPA / percentage", "Education", false),
        "pan_number" to Triple("PAN number", "IDs", true),
        "aadhaar_number" to Triple("Aadhaar number", "IDs", true),
        "passport_number" to Triple("Passport number", "IDs", true),
        "driving_licence" to Triple("Driving licence number", "IDs", true),
        "voter_id" to Triple("Voter ID", "IDs", true),
    )

    private fun prefs(context: Context) = context.getSharedPreferences("vault", Context.MODE_PRIVATE)

    fun load(context: Context): Map<String, Entry> {
        val sealed = prefs(context).getString("data", null) ?: return emptyMap()
        val json = JSONObject(Crypto.unseal(sealed))
        return json.keys().asSequence().associateWith { key ->
            val e = json.getJSONObject(key)
            Entry(key, e.getString("label"), e.getString("category"), e.getBoolean("sensitive"), e.getString("value"))
        }
    }

    private fun save(context: Context, entries: Map<String, Entry>) {
        val json = JSONObject()
        entries.values.forEach {
            json.put(it.key, JSONObject().put("label", it.label).put("category", it.category)
                .put("sensitive", it.sensitive).put("value", it.value))
        }
        prefs(context).edit().putString("data", Crypto.seal(json.toString())).apply()
    }

    fun set(context: Context, key: String, value: String, label: String? = null, sensitive: Boolean = false) {
        val template = TEMPLATE[key]
        val entry = Entry(
            key,
            label ?: template?.first ?: key.replace('_', ' ').replaceFirstChar { it.uppercase() },
            template?.second ?: "Custom",
            template?.third ?: sensitive,
            value,
        )
        save(context, load(context) + (key to entry))
    }

    fun delete(context: Context, key: String) = save(context, load(context) - key)

    /** For showing on screen: "ABCDE1234F" -> "AB******4F". */
    fun mask(value: String): String =
        if (value.length <= 4) "*".repeat(value.length) else value.take(2) + "*".repeat(value.length - 4) + value.takeLast(2)

    /** Replaces any saved value inside text with "[your <label>]" before the AI sees it. */
    fun redact(text: String, entries: Collection<Entry>): String {
        var result = text
        entries.filter { it.value.length >= 3 }.sortedByDescending { it.value.length }.forEach {
            result = result.replace(it.value, "[your ${it.label}]", ignoreCase = true)
        }
        return result
    }
}
