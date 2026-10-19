package com.jarvis.app

import android.content.Context

/** Settings. The device key is encrypted with the phone's Keystore (see Crypto); the
 *  password itself is never saved. */
object Prefs {
    const val DEFAULT_URL = "https://jarvis-cloud-5azx.onrender.com"
    private const val FILE = "jarvis"

    private fun prefs(context: Context) = context.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun url(context: Context): String = prefs(context).getString("url", DEFAULT_URL) ?: DEFAULT_URL

    fun token(context: Context): String? {
        val stored = prefs(context).getString("token", null) ?: return null
        return try {
            Crypto.unseal(stored)
        } catch (e: Exception) {
            null
        }
    }

    fun savePairing(context: Context, url: String, token: String) {
        prefs(context).edit()
            .putString("url", url.trimEnd('/'))
            .putString("token", Crypto.seal(token))
            .apply()
    }

    fun forget(context: Context) = prefs(context).edit().remove("token").apply()

    var speakReplies: Boolean = true
}
