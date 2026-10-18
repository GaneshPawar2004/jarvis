package com.jarvis.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder

/** Keeps the link to cloud JARVIS alive while other apps are on screen, so JARVIS can keep
 *  working (and speaking) after it opens LinkedIn, Chrome, etc. Shows a quiet notification. */
class LinkService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, "JARVIS connection", NotificationManager.IMPORTANCE_MIN)
        )
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE
        )
        val notification = Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("JARVIS is standing by")
            .setContentText("Tap to talk to JARVIS")
            .setContentIntent(open)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(ID, notification)
        }
        Speaker.init(this)
        CloudLink.start(this)
        return START_STICKY
    }

    override fun onDestroy() {
        CloudLink.stop()
        super.onDestroy()
    }

    companion object {
        private const val CHANNEL = "link"
        private const val ID = 1

        fun start(context: Context) {
            context.startForegroundService(Intent(context, LinkService::class.java))
        }
    }
}
