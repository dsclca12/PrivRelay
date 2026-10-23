package dev.privrelay.privrelay.sms

import android.app.IntentService
import android.content.Intent
import android.provider.Telephony
import android.telephony.SmsManager
import android.telephony.TelephonyManager
import android.util.Log

/** Handles an explicit “reply with message” action initiated by Android's call UI. */
class RespondViaMessageService : IntentService("PrivRelayRespondViaMessage") {
    override fun onHandleIntent(intent: Intent?) {
        if (intent?.action != TelephonyManager.ACTION_RESPOND_VIA_MESSAGE) return
        val address = intent.data?.schemeSpecificPart?.substringBefore('?')
        val body = intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString()?.trim()
        if (address.isNullOrBlank() || body.isNullOrBlank() || body.length > 5000) {
            Log.w(TAG, "Ignoring malformed respond-via-message request")
            return
        }
        try {
            val manager = getSystemService(SmsManager::class.java)
            val parts = manager.divideMessage(body)
            if (parts.size == 1) manager.sendTextMessage(address, null, body, null, null)
            else manager.sendMultipartTextMessage(address, null, parts, null, null)
            val values = android.content.ContentValues().apply {
                put(Telephony.Sms.ADDRESS, address)
                put(Telephony.Sms.BODY, body)
                put(Telephony.Sms.DATE, System.currentTimeMillis())
                put(Telephony.Sms.READ, 1)
                put(Telephony.Sms.SEEN, 1)
                put(Telephony.Sms.TYPE, Telephony.Sms.MESSAGE_TYPE_SENT)
            }
            contentResolver.insert(Telephony.Sms.Sent.CONTENT_URI, values)
        } catch (error: Exception) {
            Log.e(TAG, "System quick reply failed", error)
        }
    }

    companion object { private const val TAG = "PrivRelayQuickReply" }
}
