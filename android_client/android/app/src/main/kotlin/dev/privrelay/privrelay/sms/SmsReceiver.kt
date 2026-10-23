package dev.privrelay.privrelay.sms

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony

class SmsReceiver: BroadcastReceiver() {
    override fun onReceive(context:Context,intent:Intent) {
        if(intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION && intent.action != Telephony.Sms.Intents.SMS_DELIVER_ACTION) return
        val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent)
        if(parts.isEmpty()) return
        // Persist synchronously before returning; no Flutter engine or network required.
        val sender = parts.first().originatingAddress ?: "未知发件人"
        val body = parts.joinToString("") { it.messageBody ?: "" }
        val sub = intent.getIntExtra("subscription",intent.getIntExtra("android.telephony.extra.SUBSCRIPTION_INDEX",-1))
        val slot = intent.getIntExtra("slot",intent.getIntExtra("android.telephony.extra.SLOT_INDEX",-1))
        if(intent.action == Telephony.Sms.Intents.SMS_DELIVER_ACTION) {
            // The default SMS handler owns writing delivered messages to the shared telephony inbox.
            // Keep this best-effort so the encrypted local queue remains available if OEM provider
            // implementations reject a field or temporarily fail.
            try {
                val values=android.content.ContentValues().apply {
                    put(Telephony.Sms.ADDRESS,sender); put(Telephony.Sms.BODY,body)
                    put(Telephony.Sms.DATE,parts.first().timestampMillis); put(Telephony.Sms.DATE_SENT,0L)
                    put(Telephony.Sms.READ,0); put(Telephony.Sms.SEEN,0)
                    put(Telephony.Sms.TYPE,Telephony.Sms.MESSAGE_TYPE_INBOX)
                    put(Telephony.Sms.SUBSCRIPTION_ID,sub)
                }
                context.contentResolver.insert(Telephony.Sms.Inbox.CONTENT_URI,values)
            } catch(error:Exception) {
                // Provider failures must never prevent the independent encrypted queue from saving SMS.
                android.util.Log.w("PrivRelaySms", "System SMS provider insert failed", error)
            }
        }
        Spool(context).use { it.insert(sender,body,parts.first().timestampMillis,sub,slot) }
        NativeBridge.changed()
        SyncWorker.enqueue(context)
    }
}
class RecoveryReceiver: BroadcastReceiver() {
    override fun onReceive(context:Context,intent:Intent) {
        if(intent.action in listOf(Intent.ACTION_BOOT_COMPLETED,Intent.ACTION_MY_PACKAGE_REPLACED)) {
            // Android restricts starting dataSync foreground services from boot.
            // Revert the opt-in after reboot so the UI does not imply it is active.
            context.getSharedPreferences("runtime",0).edit().putBoolean("foreground_sync",false).apply()
            SyncWorker.enqueue(context,forceSync=true)
        }
    }
}
