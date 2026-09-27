package com.gitwrekt.friday

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

data class ChatMessage(val role: String, val text: String)

/** Minimal Messages API client. Swap the URL for your own server later. */
class ClaudeClient(
    private val apiKey: String,
    private val model: String,
    private val endpoint: String = "https://api.anthropic.com/v1/messages",
) {
    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(90, TimeUnit.SECONDS)
        .build()

    val hasKey: Boolean get() = apiKey.isNotBlank()

    suspend fun send(system: String, history: List<ChatMessage>): String =
        withContext(Dispatchers.IO) {
            val messages = JSONArray()
            history.forEach {
                messages.put(JSONObject().put("role", it.role).put("content", it.text))
            }
            val body = JSONObject()
                .put("model", model)
                .put("max_tokens", 1024)
                .put("system", system)
                .put("messages", messages)

            val request = Request.Builder()
                .url(endpoint)
                .header("x-api-key", apiKey)
                .header("anthropic-version", "2023-06-01")
                .post(body.toString().toRequestBody("application/json".toMediaType()))
                .build()

            http.newCall(request).execute().use { resp ->
                val raw = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) {
                    val msg = runCatching {
                        JSONObject(raw).getJSONObject("error").getString("message")
                    }.getOrDefault(raw.take(200))
                    throw IOException("Claude API ${resp.code}: $msg")
                }
                val content = JSONObject(raw).getJSONArray("content")
                buildString {
                    for (i in 0 until content.length()) {
                        val block = content.getJSONObject(i)
                        if (block.optString("type") == "text") append(block.getString("text"))
                    }
                }.trim()
            }
        }
}
