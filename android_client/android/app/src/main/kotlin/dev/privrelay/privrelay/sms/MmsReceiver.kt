package dev.privrelay.privrelay.sms

import android.app.Activity
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.Telephony
import android.telephony.SmsManager
import android.util.Log
import android.database.Cursor
import android.net.Uri
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream

/** Downloads a carrier-delivered MMS notification into Android's shared MMS provider. */
class MmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.WAP_PUSH_DELIVER_ACTION) return
        val pdu = intent.getByteArrayExtra("data") ?: run {
            Log.w(TAG, "MMS WAP push had no data")
            return
        }
        val location = MmsNotification.contentLocation(pdu) ?: run {
            Log.w(TAG, "MMS notification had no valid content location")
            return
        }
        val uri = try {
            context.contentResolver.insert(Telephony.Mms.Inbox.CONTENT_URI, ContentValues().apply {
                put("msg_box", Telephony.Mms.MESSAGE_BOX_INBOX)
                put("m_type", 130) // WSP PDU message type: m-notification-ind.
                put("ct_l", location)
                put("tr_id", MmsNotification.transactionId(pdu).orEmpty())
                put("date", System.currentTimeMillis() / 1000)
                put("read", 0)
                put("seen", 0)
            })
        } catch (error: Exception) {
            Log.e(TAG, "Could not create MMS provider row", error)
            null
        } ?: return

        try {
            val subscription = intent.getIntExtra("subscription", -1)
            val baseManager = context.getSystemService(SmsManager::class.java)
            val manager = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP_MR1 && subscription >= 0)
                baseManager.createForSubscriptionId(subscription) else baseManager
            val result = PendingIntent.getBroadcast(
                context, uri.toString().hashCode(),
                Intent(context, MmsDownloadReceiver::class.java).setData(uri),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
            manager.downloadMultimediaMessage(context, location, uri, null, result)
        } catch (error: Exception) {
            Log.e(TAG, "Could not start carrier MMS download", error)
            // Keep the provider notification row so a later system retry does not lose the MMS.
        }
    }

    companion object { private const val TAG = "PrivRelayMms" }
}

/** Completion callback is intentionally generic; media content never enters logs. */
class MmsDownloadReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (resultCode == Activity.RESULT_OK) {
            val row = intent.data
            if (row != null) try {
                val imported = importDownloadedMms(context, row)
                if (!imported) Log.w(TAG, "Downloaded MMS had no importable sender or parts")
            } catch (error: Exception) {
                Log.e(TAG, "Could not import downloaded MMS", error)
            }
            NativeBridge.changed()
        } else {
            Log.w(TAG, "Carrier MMS download failed with result $resultCode")
        }
    }

    private fun importDownloadedMms(context: Context, row: Uri): Boolean {
        val resolver = context.contentResolver
        val messageId = row.lastPathSegment ?: return false
        var sender = ""
        var dateMillis = System.currentTimeMillis()
        var subscription = -1
        resolver.query(row, arrayOf(Telephony.Mms.DATE, Telephony.Mms.SUBSCRIPTION_ID), null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                dateMillis = c.longOr(Telephony.Mms.DATE)?.let { if (it < 100000000000L) it * 1000 else it } ?: dateMillis
                subscription = c.longOr(Telephony.Mms.SUBSCRIPTION_ID)?.toInt() ?: -1
            }
        }
        val addressUri = Uri.parse("content://mms/$messageId/addr")
        resolver.query(addressUri, arrayOf("address", "type"), null, null, null)?.use { c ->
            while (c.moveToNext()) {
                val type = c.longOr("type")?.toInt()
                val candidate = c.stringOr("address").orEmpty()
                if (type == 137 && candidate.isNotBlank() && candidate != "insert-address-token") { sender = candidate; break }
            }
        }
        if (sender.isBlank()) return false
        val parts = JSONArray()
        var total = 0
        var body = ""
        var truncated = false
        val partsUri = Uri.parse("content://mms/$messageId/part")
        resolver.query(partsUri, arrayOf("_id", "ct", "name", "fn", "text"), null, null, null)?.use { c ->
            while (c.moveToNext()) {
                val id = c.stringOr("_id") ?: continue
                val mime = c.stringOr("ct") ?: "application/octet-stream"
                if (mime == "application/smil") continue
                if (mime.startsWith("text/")) {
                    val text = c.stringOr("text").orEmpty()
                    if (mime == "text/plain") body += text
                    continue
                }
                val bytes = resolver.openInputStream(Uri.parse("content://mms/part/$id"))?.use { input ->
                    val out = ByteArrayOutputStream()
                    val buf = ByteArray(8192)
                    while (true) {
                        val n = input.read(buf); if (n < 0) break
                        if (out.size() + n > MAX_ATTACHMENT_BYTES || total + out.size() + n > MAX_ATTACHMENT_BYTES) { truncated = true; return@use null }
                        out.write(buf, 0, n)
                    }
                    out.toByteArray()
                } ?: continue
                total += bytes.size
                val filename = c.stringOr("fn") ?: c.stringOr("name") ?: "attachment-${parts.length()+1}"
                parts.put(JSONObject().put("filename", filename.take(160)).put("mime_type", mime.take(100))
                    .put("data_base64", Base64.encodeToString(bytes, Base64.NO_WRAP)).put("size", bytes.size))
            }
        }
        if (truncated) Log.w(TAG, "MMS attachment payload exceeds local sync limit")
        val slot = try {
            if (Build.VERSION.SDK_INT >= 22 && subscription >= 0)
                android.telephony.SubscriptionManager.from(context).activeSubscriptionInfoList?.firstOrNull { it.subscriptionId == subscription }?.simSlotIndex ?: -1 else -1
        } catch (_: SecurityException) { -1 }
        Spool(context).use { it.insert(sender, body, dateMillis, subscription, slot, contentKind = "mms", attachments = parts, attachmentsTruncated = truncated, identityKey = "mms:$messageId") }
        return true
    }

    private fun Cursor.stringOr(name: String): String? = getColumnIndex(name).takeIf { it >= 0 && !isNull(it) }?.let(::getString)
    private fun Cursor.longOr(name: String): Long? = getColumnIndex(name).takeIf { it >= 0 && !isNull(it) }?.let(::getLong)

    companion object { private const val TAG = "PrivRelayMms"; private const val MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024 }
}

/** Minimal WSP parser for MMS notification-ind Content-Location and Transaction-Id. */
internal object MmsNotification {
    fun transactionId(pdu: ByteArray): String? = headerValue(pdu, 0x98)

    fun contentLocation(pdu: ByteArray): String? = headerValue(pdu, 0x83)?.let { raw ->
        raw.trim().takeIf { it.startsWith("http://") || it.startsWith("https://") }
    }

    private fun headerValue(pdu: ByteArray, wanted: Int): String? {
        if (pdu.size < 4) return null
        var i = 2 // Transaction-ID, PDU type
        val headerLength = readUintvar(pdu, i) ?: return null
        i = headerLength.second
        val headerEnd = (i + headerLength.first).coerceAtMost(pdu.size)
        // Skip the WSP Content-Type value (short integer or NUL-terminated text).
        if (i >= headerEnd) return null
        if ((pdu[i].toInt() and 0x80) != 0) i++ else i = skipText(pdu, i, headerEnd)
        while (i < headerEnd) {
            val field = pdu[i++].toInt() and 0xff
            if (field < 0x80) {
                i = skipText(pdu, i, headerEnd)
                continue
            }
            val start = i
            if (field == wanted) {
                // Both fields are encoded as text-string. Strip the optional quote/charset marker.
                if (i < headerEnd && (pdu[i].toInt() and 0xff) == 0x7f) i++
                if (i < headerEnd && (pdu[i].toInt() and 0x80) != 0) i++
                val end = (i until headerEnd).firstOrNull { pdu[it].toInt() == 0 } ?: headerEnd
                return pdu.copyOfRange(i, end).toString(Charsets.UTF_8)
            }
            // Values in notification-ind headers may be text, short integers, or value-length forms.
            i = when {
                i >= headerEnd -> headerEnd
                (pdu[i].toInt() and 0x80) != 0 -> i + 1
                (pdu[i].toInt() and 0xff) <= 30 -> {
                    val length = pdu[i].toInt() and 0xff
                    (i + 1 + length).coerceAtMost(headerEnd)
                }
                else -> skipText(pdu, i, headerEnd)
            }
            if (i <= start) return null
        }
        return null
    }

    private fun skipText(bytes: ByteArray, start: Int, end: Int): Int {
        val zero = (start until end).firstOrNull { bytes[it].toInt() == 0 }
        return if (zero == null) end else zero + 1
    }

    private fun readUintvar(bytes: ByteArray, start: Int): Pair<Int, Int>? {
        var value = 0
        var i = start
        while (i < bytes.size && i - start < 5) {
            val b = bytes[i++].toInt() and 0xff
            value = (value shl 7) or (b and 0x7f)
            if (b and 0x80 == 0) return value to i
        }
        return null
    }
}
