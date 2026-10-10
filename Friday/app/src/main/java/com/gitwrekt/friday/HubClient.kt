package com.gitwrekt.friday

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Thrown when the laptop can't be reached at all (so falling back is safe). */
class HubUnreachableException(cause: Throwable) : IOException("Home hub unreachable", cause)

/** The hub rejected the token (rotated, wrong, or guest access switched off). */
class HubAuthException(message: String) : IOException(message)

/** What the hub sent back: what to say, plus any phone actions (alarms, timers) to run. */
data class HubReply(val reply: String, val actions: List<JSONObject>)

/**
 * Talks to server.py on the laptop: the shared Jarvis/Friday brain.
 * The token is passed per call, because it decides the tier: the guest token is built in,
 * the household token only exists in memory after the user unlocks with biometrics.
 */
class HubClient(private val baseUrl: String) {

    val hasUrl: Boolean get() = baseUrl.isNotBlank()

    private val http = OkHttpClient.Builder()
        .connectTimeout(4, TimeUnit.SECONDS)   // fail fast so fallback kicks in quickly
        .readTimeout(90, TimeUnit.SECONDS)     // tool use can take a while
        .build()

    suspend fun chat(token: String, text: String, newSession: Boolean): HubReply = withContext(Dispatchers.IO) {
        val body = JSONObject().put("text", text).put("new_session", newSession)
        val request = Request.Builder()
            .url(baseUrl.trimEnd('/') + "/chat")
            .header("Authorization", "Bearer $token")
            .post(body.toString().toRequestBody("application/json".toMediaType()))
            .build()

        val response = try {
            http.newCall(request).execute()
        } catch (e: IOException) {
            throw HubUnreachableException(e)
        }

        response.use {
            val raw = it.body?.string().orEmpty()
            if (it.code == 401) throw HubAuthException("Home hub rejected the token")
            if (!it.isSuccessful) {
                val detail = runCatching { JSONObject(raw).getString("detail") }
                    .getOrDefault(raw.take(200))
                throw IOException("Home hub ${it.code}: $detail")
            }
            val obj = JSONObject(raw)
            val actionsArr = obj.optJSONArray("actions")
            val actions = buildList {
                actionsArr?.let { arr -> for (i in 0 until arr.length()) add(arr.getJSONObject(i)) }
            }
            HubReply(obj.getString("reply"), actions)
        }
    }
}
