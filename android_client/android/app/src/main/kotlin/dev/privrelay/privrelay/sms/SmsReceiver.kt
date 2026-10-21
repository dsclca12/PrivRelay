package dev.privrelay.privrelay.sms

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony

class SmsReceiver: BroadcastReceiver() {
    override fun onReceive(context:Context,intent:Intent) {
        if(intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
        val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent)
        if(parts.isEmpty()) return
        // Persist synchronously before returning; no Flutter engine or network required.
        val sender = parts.first().originatingAddress ?: "未知发件人"
        val body = parts.joinToString("") { it.messageBody ?: "" }
        val sub = intent.getIntExtra("subscription",intent.getIntExtra("android.telephony.extra.SUBSCRIPTION_INDEX",-1))
        val slot = intent.getIntExtra("slot",intent.getIntExtra("android.telephony.extra.SLOT_INDEX",-1))
        Spool(context).use { it.insert(sender,body,parts.first().timestampMillis,sub,slot) }
        NativeBridge.changed()
        SyncWorker.enqueue(context)
    }
}
class RecoveryReceiver: BroadcastReceiver() {
    override fun onReceive(context:Context,intent:Intent) {
        if(intent.action in listOf(Intent.ACTION_BOOT_COMPLETED,Intent.ACTION_MY_PACKAGE_REPLACED)) SyncWorker.enqueue(context,forceSync=true)
    }
}
