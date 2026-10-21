package dev.privrelay.privrelay.sms

import android.content.Context
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk=[35])
class SpoolTest {
    @Test fun fingerprintIncludesSimAndContents(){
        val a=Spool.fingerprint("sender","body",123,1)
        assertEquals(a,Spool.fingerprint("sender","body",123,1))
        assertNotEquals(a,Spool.fingerprint("sender","body",123,2))
        assertNotEquals(a,Spool.fingerprint("sender","other",123,1))
    }
    @Test fun idIsUuidV7(){val id=UUID.fromString(Spool.uuidV7());assertEquals(7,id.version());assertEquals(2,id.variant())}
    @Test fun spoolDurableAndDeduplicatedAfterAck(){
        val ctx=RuntimeEnvironment.getApplication() as Context;ctx.deleteDatabase("sms_spool.db")
        fun open()=Spool(ctx,{it.toByteArray()},{String(it)})
        val id=open().use{it.insert("test","synthetic only",123,1,0)}
        open().use{assertEquals(1,it.count());assertEquals(id,it.peek().first()["message_id"]);assertEquals(id,it.insert("test","synthetic only",123,1,0));it.ack(listOf(id));assertEquals(0,it.count())}
        open().use{assertEquals(id,it.insert("test","synthetic only",123,1,0));assertEquals(0,it.count());assertNotEquals(id,it.insert("test","synthetic only",123,2,1));assertEquals(1,it.count())}
    }
}
