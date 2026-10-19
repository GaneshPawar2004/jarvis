package com.jarvis.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** The phone's link to cloud JARVIS: one websocket that carries chat both ways and the
 *  cloud's requests to act on this phone (tool calls), plus Allow/Deny questions. */
object CloudLink {
    interface Listener {
        fun onStatus(connected: Boolean, message: String) {}
        fun onSent(text: String) {}
        fun onTool(name: String) {}
        fun onReply(text: String, isError: Boolean) {}
    }

    private val main = Handler(Looper.getMainLooper())
    private val work = Executors.newCachedThreadPool()
    private val listeners = mutableSetOf<Listener>()
    private val http = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .connectTimeout(90, TimeUnit.SECONDS) // a sleeping free server takes ~1 minute to wake
        .build()

    private lateinit var app: Context
    private var socket: WebSocket? = null
    private var wanted = false
    private var retryDelayMs = 5_000L
    private val outbox = mutableListOf<String>() // said while reconnecting; sent once connected

    @Volatile var connected = false
        private set
    var statusMessage = "Not connected"
        private set

    fun addListener(listener: Listener) {
        listeners += listener
        listener.onStatus(connected, statusMessage)
    }

    fun removeListener(listener: Listener) {
        listeners -= listener
    }

    private fun emit(block: (Listener) -> Unit) = main.post { listeners.toList().forEach(block) }

    private fun setStatus(isConnected: Boolean, message: String) {
        connected = isConnected
        statusMessage = message
        emit { it.onStatus(isConnected, message) }
    }

    /** Trade the password for this phone's own device key (the password isn't stored). */
    fun pair(context: Context, url: String, password: String, name: String): String {
        val body = JSONObject().put("password", password).put("name", name).toString()
            .toRequestBody("application/json".toMediaType())
        http.newCall(Request.Builder().url(url.trimEnd('/') + "/api/pair").post(body).build()).execute().use { response ->
            val json = JSONObject(response.body?.string().orEmpty().ifBlank { "{}" })
            if (!response.isSuccessful) throw IllegalStateException(json.optString("error", "Pairing failed (${response.code})"))
            Prefs.savePairing(context, url, json.getString("token"))
            return json.getString("token")
        }
    }

    fun start(context: Context) {
        app = context.applicationContext
        wanted = true
        if (socket == null) connect()
    }

    fun stop() {
        wanted = false
        socket?.close(1000, "bye")
        socket = null
        setStatus(false, "Disconnected")
    }

    private fun connect() {
        val token = Prefs.token(app) ?: return setStatus(false, "Not paired")
        val url = Prefs.url(app).replace("https://", "wss://").replace("http://", "ws://") + "/agent"
        setStatus(false, "Connecting… (a sleeping server can take a minute)")
        val request = Request.Builder().url(url).header("Authorization", "Bearer $token").build()
        socket = http.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                retryDelayMs = 5_000L
                val hello = JSONObject().put("type", "hello").put("kind", "phone").put("tools", PhoneTools.declarations())
                webSocket.send(hello.toString())
                setStatus(true, "Connected")
                synchronized(outbox) {
                    outbox.forEach { send(webSocket, it) }
                    outbox.clear()
                }
            }

            override fun onMessage(webSocket: WebSocket, text: String) = handle(webSocket, JSONObject(text))

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = dropped(webSocket, "Disconnected")

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                if (response?.code == 401 || response?.code == 403) {
                    wanted = false
                    Prefs.forget(app)
                    dropped(webSocket, "This phone's key was rejected. Pair again.")
                } else {
                    dropped(webSocket, "Offline (${t.javaClass.simpleName}), retrying…")
                }
            }
        })
    }

    private fun dropped(webSocket: WebSocket, message: String) {
        if (socket !== webSocket) return
        socket = null
        setStatus(false, message)
        if (wanted) {
            main.postDelayed({ if (wanted && socket == null) connect() }, retryDelayMs)
            retryDelayMs = (retryDelayMs * 2).coerceAtMost(60_000L)
        }
    }

    private fun handle(webSocket: WebSocket, message: JSONObject) {
        when (message.optString("type")) {
            "call" -> work.execute {
                val reply = JSONObject().put("type", "result").put("id", message.getString("id"))
                try {
                    reply.put("result", PhoneTools.run(app, message.getString("tool"), message.optJSONObject("args") ?: JSONObject()))
                } catch (e: Exception) {
                    reply.put("error", e.message ?: e.javaClass.simpleName)
                }
                webSocket.send(reply.toString())
            }
            "confirm" -> work.execute {
                val approved = ConfirmCenter.ask(app, message.optString("text"))
                webSocket.send(JSONObject().put("type", "confirm_reply").put("id", message.getString("id")).put("approved", approved).toString())
            }
            "tool" -> emit { it.onTool(message.optString("name")) }
            "chat_reply" -> reply(message.optString("text"), false)
            "chat_error" -> reply(message.optString("text"), true)
        }
    }

    private fun reply(text: String, isError: Boolean) {
        emit { it.onReply(text, isError) }
        if (!isError && Prefs.speakReplies) Speaker.say(text)
        if (!appVisible) notifyReply(text)
    }

    /** The user is in another app: show JARVIS's answer as a notification too. */
    private fun notifyReply(text: String) {
        val manager = app.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("replies", "JARVIS replies", NotificationManager.IMPORTANCE_HIGH))
        val open = PendingIntent.getActivity(app, 0, Intent(app, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        manager.notify(
            REPLY_NOTIFICATION,
            Notification.Builder(app, "replies")
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setContentTitle("JARVIS")
                .setContentText(text)
                .setStyle(Notification.BigTextStyle().bigText(text))
                .setContentIntent(open)
                .setAutoCancel(true)
                .setTimeoutAfter(60_000)
                .build(),
        )
    }

    @Volatile var appVisible = false

    private const val REPLY_NOTIFICATION = 2

    private fun send(ws: WebSocket, text: String) =
        ws.send(JSONObject().put("type", "chat").put("id", UUID.randomUUID().toString()).put("text", text).toString())

    /** Send something the user typed or said. If JARVIS is reconnecting, it's sent as soon as
     *  the link is back. */
    fun chat(text: String) {
        emit { it.onSent(text) }
        val ws = socket
        if (ws != null && connected && send(ws, text)) return
        synchronized(outbox) { outbox += text }
    }
}
