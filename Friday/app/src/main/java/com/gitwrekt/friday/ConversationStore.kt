package com.gitwrekt.friday

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/**
 * Chat history + voice setting, persisted across app restarts.
 * Guest history lives in normal app prefs. Household history lives in the encrypted
 * store, so a guest using the app never sees it.
 */
class ConversationStore(context: Context) {
    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences("friday", Context.MODE_PRIVATE)

    init {
        // Pre-tier versions kept one shared history in plain text. Drop it rather than show
        // old household chats to a guest.
        if (prefs.contains(LEGACY_KEY)) prefs.edit().remove(LEGACY_KEY).apply()
    }

    private fun prefsFor(tier: Tier) =
        if (tier == Tier.HOUSEHOLD) SecureStore.prefs(appContext) else prefs

    private fun keyFor(tier: Tier) = if (tier == Tier.HOUSEHOLD) "history_household" else "history_guest"

    fun load(tier: Tier): List<ChatMessage> {
        val raw = prefsFor(tier)?.getString(keyFor(tier), null) ?: return emptyList()
        return runCatching {
            val arr = JSONArray(raw)
            List(arr.length()) { i ->
                val o = arr.getJSONObject(i)
                ChatMessage(o.getString("role"), o.getString("text"))
            }
        }.getOrDefault(emptyList())
    }

    fun save(tier: Tier, list: List<ChatMessage>) {
        val arr = JSONArray()
        list.takeLast(MAX_STORED).forEach {
            arr.put(JSONObject().put("role", it.role).put("text", it.text))
        }
        prefsFor(tier)?.edit()?.putString(keyFor(tier), arr.toString())?.apply()
    }

    fun clear(tier: Tier) {
        prefsFor(tier)?.edit()?.remove(keyFor(tier))?.apply()
    }

    var voiceName: String?
        get() = prefs.getString("voice", null)
        set(v) = prefs.edit().putString("voice", v).apply()

    companion object {
        const val MAX_STORED = 60
        private const val LEGACY_KEY = "history"
    }
}
