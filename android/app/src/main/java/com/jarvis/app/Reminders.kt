package com.jarvis.app

import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** Reminders and the morning briefing, scheduled as alarms on the phone itself: they fire on
 *  time with the laptop off, the app closed, even without internet, and survive a restart. */
object Reminders {
    private const val PREFS = "reminders"
    private const val BRIEFING_CODE = 900_000
    private val FORMAT: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")

    const val BRIEFING_PROMPT = "Give me my morning briefing: today's date, the weather where I live, my reminders " +
        "for today, my phone and laptop battery, and the top 3 new job posts that match my resume. " +
        "Under 120 words, friendly, spoken style."

    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    // ---------------- reminders ----------------

    fun all(context: Context): MutableList<JSONObject> {
        val raw = JSONArray(prefs(context).getString("items", "[]"))
        return (0 until raw.length()).map { raw.getJSONObject(it) }.toMutableList()
    }

    private fun save(context: Context, items: List<JSONObject>) =
        prefs(context).edit().putString("items", JSONArray(items).toString()).apply()

    /** due = "YYYY-MM-DD HH:MM" in the phone's local time. */
    fun add(context: Context, message: String, due: String): String {
        val whenLocal = try {
            LocalDateTime.parse(due.trim(), FORMAT)
        } catch (e: Exception) {
            return "The time must look like 2026-10-20 18:30."
        }
        val at = whenLocal.atZone(ZoneId.systemDefault()).toInstant().toEpochMilli()
        if (at <= System.currentTimeMillis()) return "$due is in the past."
        val items = all(context)
        val id = (items.maxOfOrNull { it.getInt("id") } ?: 0) + 1
        items += JSONObject().put("id", id).put("message", message).put("due", at).put("done", false)
        save(context, items)
        schedule(context, id, at)
        val exact = canBeExact(context)
        return "Reminder $id set for ${whenLocal.format(DateTimeFormatter.ofPattern("EEE d MMM, h:mm a"))}: $message" +
            if (exact) "" else " (it may arrive a few minutes late until exact alarms are allowed in JARVIS settings)"
    }

    fun upcoming(context: Context): List<JSONObject> = all(context).filter { !it.getBoolean("done") }

    fun cancel(context: Context, id: Int): String {
        val items = all(context)
        if (items.none { it.getInt("id") == id }) return "No reminder with id $id."
        save(context, items.filter { it.getInt("id") != id })
        alarms(context).cancel(pending(context, id, "reminder"))
        return "Reminder $id cancelled."
    }

    fun markDone(context: Context, id: Int) =
        save(context, all(context).map { if (it.getInt("id") == id) it.put("done", true) else it })

    fun snooze(context: Context, id: Int, minutes: Int = 10) {
        val at = System.currentTimeMillis() + minutes * 60_000L
        save(context, all(context).map { if (it.getInt("id") == id) it.put("due", at).put("done", false) else it })
        schedule(context, id, at)
    }

    // ---------------- morning briefing ----------------

    fun briefingTime(context: Context): String? = prefs(context).getString("briefing", null) // "07:30" or null = off

    fun setBriefing(context: Context, time: String?) {
        prefs(context).edit().putString("briefing", time).apply()
        if (time == null) alarms(context).cancel(pending(context, BRIEFING_CODE, "briefing"))
        else scheduleBriefing(context)
    }

    fun scheduleBriefing(context: Context) {
        val time = briefingTime(context) ?: return
        val zone = ZoneId.systemDefault()
        var next = LocalDateTime.now(zone).with(LocalTime.parse(time))
        if (!next.isAfter(LocalDateTime.now(zone))) next = next.plusDays(1)
        setAlarm(context, next.atZone(zone).toInstant().toEpochMilli(), pending(context, BRIEFING_CODE, "briefing"))
    }

    /** Ask cloud JARVIS for the briefing now; the reply arrives as a notification (and spoken). */
    fun briefNow(context: Context) {
        try {
            LinkService.start(context)
            CloudLink.chat(BRIEFING_PROMPT)
        } catch (e: Exception) { // Android may refuse to start JARVIS from the background
            val tap = PendingIntent.getActivity(context, BRIEFING_CODE,
                Intent(context, MainActivity::class.java).setAction(ACTION_BRIEFING), PendingIntent.FLAG_IMMUTABLE)
            val manager = context.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel("alerts", "JARVIS reminders and alerts", NotificationManager.IMPORTANCE_HIGH))
            manager.notify(BRIEFING_CODE, Notification.Builder(context, "alerts")
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setContentTitle("Good morning, sir")
                .setContentText("Tap to hear your briefing.")
                .setContentIntent(tap)
                .setAutoCancel(true)
                .build())
        }
    }

    const val ACTION_BRIEFING = "com.jarvis.app.BRIEFING"

    // ---------------- alarm plumbing ----------------

    private fun alarms(context: Context) = context.getSystemService(AlarmManager::class.java)

    fun canBeExact(context: Context) = Build.VERSION.SDK_INT < 31 || alarms(context).canScheduleExactAlarms()

    private fun pending(context: Context, id: Int, kind: String): PendingIntent =
        PendingIntent.getBroadcast(
            context, if (kind == "briefing") BRIEFING_CODE else id,
            Intent(context, AlarmReceiver::class.java).putExtra("kind", kind).putExtra("id", id),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

    private fun schedule(context: Context, id: Int, at: Long) = setAlarm(context, at, pending(context, id, "reminder"))

    private fun setAlarm(context: Context, at: Long, intent: PendingIntent) {
        if (canBeExact(context)) alarms(context).setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, intent)
        else alarms(context).setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, intent)
    }

    /** After a phone restart, alarms are gone: set them again. */
    fun rescheduleAll(context: Context) {
        upcoming(context).forEach { if (it.getLong("due") > System.currentTimeMillis()) schedule(context, it.getInt("id"), it.getLong("due")) }
        scheduleBriefing(context)
    }

    fun notify(context: Context, id: Int, title: String, text: String, actions: List<Notification.Action> = emptyList()) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("alerts", "JARVIS reminders and alerts", NotificationManager.IMPORTANCE_HIGH))
        val open = PendingIntent.getActivity(context, id, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val builder = Notification.Builder(context, "alerts")
            .setSmallIcon(android.R.drawable.ic_popup_reminder)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setContentIntent(open)
            .setAutoCancel(true)
            .setCategory(Notification.CATEGORY_REMINDER)
        actions.forEach { builder.addAction(it) }
        manager.notify(id, builder.build())
    }
}

/** Fires reminders and the daily briefing. */
class AlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val id = intent.getIntExtra("id", 0)
        when (intent.getStringExtra("kind")) {
            "briefing" -> {
                Reminders.scheduleBriefing(context) // tomorrow's
                Reminders.briefNow(context)
            }
            "reminder" -> {
                val item = Reminders.all(context).firstOrNull { it.getInt("id") == id } ?: return
                Reminders.markDone(context, id)
                fun action(label: String, kind: String) = Notification.Action.Builder(
                    null, label,
                    PendingIntent.getBroadcast(context, id * 10 + label.length,
                        Intent(context, AlarmReceiver::class.java).putExtra("kind", kind).putExtra("id", id),
                        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT),
                ).build()
                Reminders.notify(context, 5000 + id, "Reminder, sir", item.getString("message"),
                    listOf(action("Snooze 10 min", "snooze"), action("Done", "done")))
                if (Prefs.speakReplies) {
                    Speaker.init(context)
                    Speaker.say("Reminder: ${item.getString("message")}")
                }
            }
            "snooze" -> {
                Reminders.snooze(context, id)
                context.getSystemService(NotificationManager::class.java).cancel(5000 + id)
            }
            "done" -> context.getSystemService(NotificationManager::class.java).cancel(5000 + id)
        }
    }
}

/** Puts reminders and the briefing back after the phone restarts. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) Reminders.rescheduleAll(context)
    }
}
