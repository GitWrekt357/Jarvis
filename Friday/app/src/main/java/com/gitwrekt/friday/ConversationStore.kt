package com.gitwrekt.friday

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/** Chat history + voice setting, persisted across app restarts. */
class ConversationStore(context: Context) {
    private val prefs = context.getSharedPreferences("friday", Context.MODE_PRIVATE)

    fun load(): List<ChatMessage> {
        val raw = prefs.getString("history", null) ?: return emptyList()
        return runCatching {
            val arr = JSONArray(raw)
            List(arr.length()) { i ->
                val o = arr.getJSONObject(i)
                ChatMessage(o.getString("role"), o.getString("text"))
            }
        }.getOrDefault(emptyList())
    }

    fun save(list: List<ChatMessage>) {
        val arr = JSONArray()
        list.takeLast(MAX_STORED).forEach {
            arr.put(JSONObject().put("role", it.role).put("text", it.text))
        }
        prefs.edit().putString("history", arr.toString()).apply()
    }

    fun clear() = prefs.edit().remove("history").apply()

    var voiceName: String?
        get() = prefs.getString("voice", null)
        set(v) = prefs.edit().putString("voice", v).apply()

    companion object { const val MAX_STORED = 60 }
}
