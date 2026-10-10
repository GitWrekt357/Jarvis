package com.gitwrekt.friday

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** Which token the phone is using. The hub decides the tier from the token alone. */
enum class Tier { GUEST, HOUSEHOLD }

/**
 * Encrypted preferences backed by the Android Keystore. Holds the household token
 * and the household chat history, so neither sits in plain text on the phone and
 * neither ships inside the APK.
 */
object SecureStore {
    private var cached: SharedPreferences? = null

    /** Null if the Keystore is unusable on this device; callers must cope. */
    @Synchronized
    fun prefs(context: Context): SharedPreferences? {
        cached?.let { return it }
        val app = context.applicationContext
        val created = runCatching { open(app) }.getOrElse {
            // Keys can become unreadable (restore, lock-screen reset). Start clean once.
            runCatching { app.deleteSharedPreferences(FILE) }
            runCatching { open(app) }.getOrNull()
        }
        cached = created
        return created
    }

    private fun open(app: Context): SharedPreferences {
        val key = MasterKey.Builder(app)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        return EncryptedSharedPreferences.create(
            app,
            FILE,
            key,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    private const val FILE = "friday_secure"
}

/** The household token, stored encrypted. Read only after the user passes the biometric/PIN prompt. */
class TokenVault(private val context: Context) {
    fun has(): Boolean = read() != null

    fun read(): String? =
        SecureStore.prefs(context)?.getString(KEY, null)?.takeIf { it.isNotBlank() }

    /** Returns false if secure storage isn't available. */
    fun save(token: String): Boolean {
        val prefs = SecureStore.prefs(context) ?: return false
        prefs.edit().putString(KEY, token.trim()).apply()
        return true
    }

    fun clear() {
        SecureStore.prefs(context)?.edit()?.remove(KEY)?.apply()
    }

    private companion object { const val KEY = "household_token" }
}
