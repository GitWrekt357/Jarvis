package com.gitwrekt.friday

import android.content.Context
import android.content.Intent
import android.provider.AlarmClock
import org.json.JSONObject

/** Executes actions the hub brain hands back (alarms, timers, ...). */
object PhoneActions {

    fun run(ctx: Context, actions: List<JSONObject>): Boolean {
        var allOk = true
        for (a in actions) {
            val ok = when (a.optString("type")) {
                "set_alarm" -> setAlarm(
                    ctx,
                    a.getInt("hour"),
                    a.getInt("minute"),
                    a.optString("label").takeIf { it.isNotBlank() },
                )
                "set_timer" -> setTimer(
                    ctx,
                    a.getInt("seconds"),
                    a.optString("label").takeIf { it.isNotBlank() },
                )
                else -> false
            }
            if (!ok) allOk = false
        }
        return allOk
    }

    private fun setAlarm(ctx: Context, hour: Int, minute: Int, label: String?): Boolean = runCatching {
        val intent = Intent(AlarmClock.ACTION_SET_ALARM).apply {
            putExtra(AlarmClock.EXTRA_HOUR, hour)
            putExtra(AlarmClock.EXTRA_MINUTES, minute)
            label?.let { putExtra(AlarmClock.EXTRA_MESSAGE, it) }
            putExtra(AlarmClock.EXTRA_SKIP_UI, true)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        ctx.startActivity(intent)
    }.isSuccess

    private fun setTimer(ctx: Context, seconds: Int, label: String?): Boolean = runCatching {
        val intent = Intent(AlarmClock.ACTION_SET_TIMER).apply {
            putExtra(AlarmClock.EXTRA_LENGTH, seconds)
            label?.let { putExtra(AlarmClock.EXTRA_MESSAGE, it) }
            putExtra(AlarmClock.EXTRA_SKIP_UI, true)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        ctx.startActivity(intent)
    }.isSuccess
}
