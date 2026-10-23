package dev.privrelay.privrelay.sms

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class MmsNotificationTest {
    @Test fun parsesTransactionIdAndHttpContentLocation() {
        val fields = byteArrayOf(0xBE.toByte(), 0x8C.toByte(), 0x82.toByte(), 0x98.toByte()) +
            "tx-1\u0000".toByteArray() + byteArrayOf(0x83.toByte()) +
            "http://mmsc.carrier.example/123\u0000".toByteArray()
        val pdu = byteArrayOf(1, 6, fields.size.toByte()) + fields
        assertEquals("tx-1", MmsNotification.transactionId(pdu))
        assertEquals("http://mmsc.carrier.example/123", MmsNotification.contentLocation(pdu))
    }

    @Test fun rejectsTruncatedOrNonUrlNotifications() {
        assertNull(MmsNotification.contentLocation(byteArrayOf(1, 6, 8, 0xBE.toByte())))
        val value = byteArrayOf(0xBE.toByte(), 0x83.toByte()) + "javascript:alert(1)\u0000".toByteArray()
        val pdu = byteArrayOf(1, 6, value.size.toByte()) + value
        assertNull(MmsNotification.contentLocation(pdu))
    }
}
