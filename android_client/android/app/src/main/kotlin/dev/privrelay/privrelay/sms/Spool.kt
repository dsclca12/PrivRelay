package dev.privrelay.privrelay.sms

import android.content.Context
import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.security.KeyStore
import java.security.MessageDigest
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

object Crypto {
    @Synchronized private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey("privrelay_spool", null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder("privrelay_spool", KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    fun encrypt(raw: String): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        return cipher.iv + cipher.doFinal(raw.toByteArray(Charsets.UTF_8))
    }
    fun decrypt(raw: ByteArray): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, raw.copyOfRange(0,12)))
        return String(cipher.doFinal(raw.copyOfRange(12,raw.size)), Charsets.UTF_8)
    }
}

class Spool(context: Context, private val encode:(String)->ByteArray=Crypto::encrypt, private val decode:(ByteArray)->String=Crypto::decrypt): SQLiteOpenHelper(context, "sms_spool.db", null, 1) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE spool (id TEXT PRIMARY KEY, dedup TEXT UNIQUE NOT NULL, payload BLOB NOT NULL)")
        // Tombstones keep retransmitted broadcasts idempotent after Dart ACK.
        db.execSQL("CREATE TABLE seen (dedup TEXT PRIMARY KEY, id TEXT NOT NULL)")
    }
    override fun onUpgrade(db: SQLiteDatabase, old: Int, new: Int) { error("Migration required") }
    @Synchronized fun insert(sender:String, body:String, received:Long, sub:Int, slot:Int, operator:String = ""):String {
        val dedup = fingerprint(sender,body,received,sub)
        val db = writableDatabase
        db.beginTransaction()
        try {
            db.rawQuery("SELECT id FROM seen WHERE dedup=?",arrayOf(dedup)).use { if(it.moveToFirst()) { db.setTransactionSuccessful(); return it.getString(0) } }
            val id = uuidV7()
            val data = JSONObject().put("message_id",id).put("sender",sender).put("body",body)
                .put("received_at",received).put("subscription_id",sub).put("slot",slot)
                .put("operator",operator).put("collected_at",System.currentTimeMillis())
            db.insertOrThrow("spool",null,ContentValues().apply {put("id",id);put("dedup",dedup);put("payload",encode(data.toString()))})
            db.insertOrThrow("seen",null,ContentValues().apply {put("dedup",dedup);put("id",id)})
            db.setTransactionSuccessful()
            return id
        } finally { db.endTransaction() }
    }
    fun peek():List<Map<String,Any?>> {
        val result = mutableListOf<Map<String,Any?>>()
        readableDatabase.rawQuery("SELECT payload FROM spool ORDER BY rowid LIMIT 50",null).use {
            while(it.moveToNext()) {
                val json = JSONObject(decode(it.getBlob(0)))
                result.add(json.keys().asSequence().associateWith { k -> json.get(k) })
            }
        }
        return result
    }
    fun ack(ids:List<String>) { val db=writableDatabase; db.beginTransaction(); try {for(id in ids) db.delete("spool","id=?",arrayOf(id)); db.setTransactionSuccessful()} finally{db.endTransaction()} }
    fun count():Int = readableDatabase.rawQuery("SELECT count(*) FROM spool",null).use {it.moveToFirst();it.getInt(0)}
    companion object {
        fun fingerprint(sender:String,body:String,received:Long,sub:Int):String = Base64.encodeToString(
            MessageDigest.getInstance("SHA-256").digest(JSONObject().put("sender",sender).put("body",body).put("at",received).put("sub",sub).toString().toByteArray()),Base64.NO_WRAP)
        fun uuidV7():String {
            val r=UUID.randomUUID(); val ms=System.currentTimeMillis()
            return UUID((ms shl 16) or 0x7000L or (r.mostSignificantBits and 0xfffL), (r.leastSignificantBits and 0x3fffffffffffffffL) or Long.MIN_VALUE).toString()
        }
    }
}
