package dev.privrelay.privrelay.sms

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * Shell-only synthetic SMS input for devDebug builds.
 *
 * Only the shell UID holds android.permission.DUMP, so ordinary apps cannot
 * send this broadcast. See docs/ANDROID_MVP.md for the adb command.
 */
class TestSmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (!dev.privrelay.privrelay.BuildConfig.DEBUG || dev.privrelay.privrelay.BuildConfig.FLAVOR != "dev") return
        if (intent.getBooleanExtra("status", false) || intent.getStringExtra("action") == "status") {
            resultData = "spool_count=" + Spool(context).use { it.count() }
            return
        }
        val sender = intent.getStringExtra("sender") ?: DEFAULT_SENDER
        val body = intent.getStringExtra("body") ?: DEFAULT_BODY
        val stamp = longExtra(intent, "timestamp", "received_at") ?: System.currentTimeMillis()
        val sub = intExtra(intent, "subscription_id", "subscription", "sub") ?: DEFAULT_SUBSCRIPTION
        val slot = intExtra(intent, "slot") ?: DEFAULT_SLOT
        val id = Spool(context).use { it.insert(sender, body, stamp, sub, slot) }
        NativeBridge.changed()
        SyncWorker.enqueue(context)
        resultData = "message_id=$id spool_count=" + Spool(context).use { it.count() } +
            " received_at=$stamp subscription_id=$sub slot=$slot"
    }

    private fun longExtra(intent: Intent, vararg keys: String): Long? =
        keys.firstNotNullOfOrNull { key ->
            (intent.getStringExtra(key)?.toLongOrNull()
                ?: if (intent.hasExtra(key)) intent.getLongExtra(key, 0L) else null)
                ?.takeIf { it > 0 }
        }

    private fun intExtra(intent: Intent, vararg keys: String): Int? =
        keys.firstNotNullOfOrNull { key ->
            intent.getStringExtra(key)?.toIntOrNull()
                ?: if (intent.hasExtra(key)) intent.getIntExtra(key, 0) else null
        }

    private companion object {
        const val DEFAULT_SENDER = "PR-BACKGROUND"
        const val DEFAULT_BODY = "PrivRelay synthetic background recovery fixture"
        const val DEFAULT_SUBSCRIPTION = 999
        const val DEFAULT_SLOT = 0
    }
}
