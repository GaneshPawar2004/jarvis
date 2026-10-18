package com.jarvis.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Asks the user Allow/Deny for risky actions with a pop-up notification, which shows on
 *  top of whatever app JARVIS is working in. No answer within 2 minutes counts as Deny. */
object ConfirmCenter {
    private const val CHANNEL = "confirm"
    private const val TIMEOUT_SECONDS = 120L
    private val waiting = ConcurrentHashMap<Int, Pair<CountDownLatch, BooleanArray>>()
    private var nextId = 100

    /** Blocks the calling (background) thread until the user answers. */
    fun ask(context: Context, question: String): Boolean {
        val id = synchronized(this) { nextId++ }
        val latch = CountDownLatch(1)
        val answer = BooleanArray(1)
        waiting[id] = latch to answer

        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, "JARVIS permission requests", NotificationManager.IMPORTANCE_HIGH)
        )
        fun action(label: String, approved: Boolean): Notification.Action {
            val intent = Intent(context, ConfirmReceiver::class.java).putExtra("id", id).putExtra("approved", approved)
            val pending = PendingIntent.getBroadcast(
                context, id * 2 + if (approved) 1 else 0, intent,
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
            )
            return Notification.Action.Builder(null, label, pending).build()
        }
        val notification = Notification.Builder(context, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle("JARVIS needs your permission")
            .setContentText(question)
            .setStyle(Notification.BigTextStyle().bigText(question))
            .setCategory(Notification.CATEGORY_CALL) // shown as a heads-up pop-up
            .addAction(action("Deny", false))
            .addAction(action("Allow", true))
            .setAutoCancel(true)
            .setTimeoutAfter(TIMEOUT_SECONDS * 1000)
            .build()
        manager.notify(id, notification)

        val answered = latch.await(TIMEOUT_SECONDS, TimeUnit.SECONDS)
        waiting.remove(id)
        manager.cancel(id)
        return answered && answer[0]
    }

    fun answer(id: Int, approved: Boolean) {
        waiting[id]?.let { (latch, answer) ->
            answer[0] = approved
            latch.countDown()
        }
    }
}

class ConfirmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        ConfirmCenter.answer(intent.getIntExtra("id", -1), intent.getBooleanExtra("approved", false))
    }
}
