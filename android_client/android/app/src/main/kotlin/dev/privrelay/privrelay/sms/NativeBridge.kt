package dev.privrelay.privrelay.sms

import android.Manifest
import android.app.Activity
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import androidx.core.app.NotificationCompat
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import javax.crypto.Cipher
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.SecretKeySpec
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import android.util.Base64

class NativeBridge(private val context:Context, messenger:BinaryMessenger, private val activity:Activity? = null) {
    private val channel = MethodChannel(messenger,"dev.privrelay/sms")
    private var vaultCachePassphrase:String?=null
    private var vaultCacheSalt:String?=null
    private var vaultCacheKey:SecretKeySpec?=null
    private var ownsLock=false
    private var pendingPermission:MethodChannel.Result?=null
    private var pendingAuthentication:MethodChannel.Result?=null
    init {
        if(activity!=null) foreground=this
        channel.setMethodCallHandler { call,result ->
            try {
                when(call.method) {
                    "status" -> result.success(mapOf("sms" to granted(Manifest.permission.RECEIVE_SMS),"notifications" to (Build.VERSION.SDK_INT<33 || granted(Manifest.permission.POST_NOTIFICATIONS)),"spool_count" to Spool(context).use{it.count()}))
                    "authenticate" -> {
                        val owner=activity
                        val keyguard=context.getSystemService(Context.KEYGUARD_SERVICE) as android.app.KeyguardManager
                        if(owner==null || pendingAuthentication!=null || !keyguard.isDeviceSecure) result.success(false)
                        else {
                            val intent=keyguard.createConfirmDeviceCredentialIntent("解锁 PrivRelay","请验证设备锁屏密码以查看短信")
                            if(intent==null) result.success(false)
                            else {pendingAuthentication=result;owner.startActivityForResult(intent,722)}
                        }
                    }
                    "requestSms" -> request(Manifest.permission.RECEIVE_SMS,result)
                    "requestNotifications" -> if(Build.VERSION.SDK_INT>=33) request(Manifest.permission.POST_NOTIFICATIONS,result) else result.success(true)
                    "peek" -> result.success(Spool(context).use{it.peek()})
                    "ack" -> { Spool(context).use{it.ack((call.arguments as List<*>).map{v->v as String})}; result.success(null) }
                    "lock" -> { if(!ownsLock) ownsLock=consumer.compareAndSet(false,true); result.success(ownsLock) }
                    "unlock" -> {releaseLock();result.success(null)}
                    "identity" -> result.success(identity())
                    "sign" -> {val store=keyStore(); val sig=Signature.getInstance("SHA256withECDSA");sig.initSign(store.getKey("privrelay_identity",null) as java.security.PrivateKey);sig.update((call.arguments as String).toByteArray());result.success(Base64.encodeToString(sig.sign(),Base64.NO_WRAP))}
                    "encryptVault" -> { val a=call.arguments as Map<*,*>; result.success(encryptVault(a["plaintext"] as String,a["passphrase"] as String,a["salt"] as String)) }
                    "decryptVault" -> { val a=call.arguments as Map<*,*>; result.success(decryptVault(a["ciphertext"] as String,a["passphrase"] as String,a["salt"] as String)) }
                    "initialize" -> {SyncWorker.periodic(context);result.success(null)}
                    "schedule" -> {SyncWorker.enqueue(context,(call.arguments as? Number)?.toLong() ?: 30,true);result.success(null)}
                    "background" -> {context.getSharedPreferences("runtime",0).edit().putBoolean("background",call.arguments as Boolean).apply(); if(call.arguments==true) {SyncWorker.periodic(context);SyncWorker.enqueue(context)} else SyncWorker.cancel(context);result.success(null)}
                    "protectScreen" -> {
                        val enabled=call.arguments as Boolean
                        val owner=activity ?: throw IllegalStateException("Foreground activity required")
                        if(enabled) owner.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)
                        else owner.window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)
                        context.getSharedPreferences("runtime",0).edit().putBoolean("screen_protection",enabled).commit()
                        result.success(null)
                    }
                    "notify" -> {notifyGeneric(call.arguments as String);result.success(null)}
                    "testInject" -> {
                        if(!dev.privrelay.privrelay.BuildConfig.DEBUG || dev.privrelay.privrelay.BuildConfig.FLAVOR!="dev") {result.notImplemented()}
                        else {val a=call.arguments as Map<*,*>;val id=Spool(context).use{it.insert(a["sender"] as String,a["body"] as String,(a["received_at"] as Number).toLong(),(a["subscription_id"] as Number).toInt(),(a["slot"] as Number).toInt())};result.success(id)}
                    }
                    else -> result.notImplemented()
                }
            } catch(_:Exception) { result.error("PLATFORM_ERROR","平台操作未完成，数据已保留",null) }
        }
    }
    fun authenticationResult(result:Int) {pendingAuthentication?.success(result==Activity.RESULT_OK);pendingAuthentication=null}
    fun permissionResult(grants:IntArray) {pendingPermission?.success(grants.isNotEmpty() && grants.all{it==PackageManager.PERMISSION_GRANTED});pendingPermission=null}
    private fun granted(permission:String)=context.checkSelfPermission(permission)==PackageManager.PERMISSION_GRANTED
    private fun request(permission:String,result:MethodChannel.Result) {
        if(granted(permission)) {result.success(true);return}
        if(activity==null || pendingPermission!=null){result.success(false);return}
        pendingPermission=result;activity.requestPermissions(arrayOf(permission),721)
    }
    private fun releaseLock(){if(ownsLock){ownsLock=false;consumer.set(false)}}
    fun close(){pendingAuthentication?.success(false);pendingAuthentication=null;releaseLock();vaultCachePassphrase=null;vaultCacheSalt=null;vaultCacheKey=null;if(foreground===this)foreground=null;channel.setMethodCallHandler(null);pendingPermission?.success(false);pendingPermission=null}
    private fun keyStore()=KeyStore.getInstance("AndroidKeyStore").apply{load(null)}
    @Synchronized private fun vaultKey(passphrase:String,salt:String):SecretKeySpec {
        require(passphrase.length >= 12 && passphrase.all { it.code in 33..126 }) { "Vault passphrase must contain at least 12 visible ASCII characters" }
        if(vaultCachePassphrase==passphrase && vaultCacheSalt==salt) return vaultCacheKey!!
        val saltBytes=Base64.decode(salt,Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
        require(saltBytes.size == 16) { "Invalid vault salt" }
        val spec=PBEKeySpec(passphrase.toCharArray(),saltBytes,600000,256)
        return try {
            SecretKeySpec(SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded,"AES").also {
                vaultCachePassphrase=passphrase; vaultCacheSalt=salt; vaultCacheKey=it
            }
        }
        finally { spec.clearPassword() }
    }
    private fun encryptVault(plain:String,passphrase:String,salt:String):String {
        val cipher=Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE,vaultKey(passphrase,salt))
        cipher.updateAAD("PrivRelay-E2EE-v1".toByteArray(Charsets.UTF_8))
        val nonce=cipher.iv
        val sealed=cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
        val envelope=byteArrayOf(1)+nonce+sealed
        return Base64.encodeToString(envelope,Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
    }
    private fun decryptVault(encoded:String,passphrase:String,salt:String):String {
        val envelope=Base64.decode(encoded,Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
        require(envelope.size >= 29 && envelope[0].toInt()==1) { "Invalid encrypted envelope" }
        val cipher=Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE,vaultKey(passphrase,salt),GCMParameterSpec(128,envelope.copyOfRange(1,13)))
        cipher.updateAAD("PrivRelay-E2EE-v1".toByteArray(Charsets.UTF_8))
        return String(cipher.doFinal(envelope.copyOfRange(13,envelope.size)),Charsets.UTF_8)
    }
    @Synchronized private fun identity():Map<String,String> {
        var store=keyStore()
        if(!store.containsAlias("privrelay_identity")) {
            KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC,"AndroidKeyStore").apply {
                initialize(KeyGenParameterSpec.Builder("privrelay_identity",KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY)
                    .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1")).setDigests(KeyProperties.DIGEST_SHA256).build())
            }.generateKeyPair();store=keyStore()
        }
        val prefs=context.getSharedPreferences("identity",0)
        val id=prefs.getString("device_id",null) ?: UUID.randomUUID().toString().also{prefs.edit().putString("device_id",it).commit()}
        return mapOf("device_id" to id,"public_key" to Base64.encodeToString(store.getCertificate("privrelay_identity").publicKey.encoded,Base64.NO_WRAP))
    }
    private fun notifyGeneric(id:String) {
        if(Build.VERSION.SDK_INT>=33 && !granted(Manifest.permission.POST_NOTIFICATIONS))return
        val nm=context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(NotificationChannel("messages","新短信",NotificationManager.IMPORTANCE_DEFAULT))
        val launch=context.packageManager.getLaunchIntentForPackage(context.packageName) ?: return
        val pi=PendingIntent.getActivity(context,0,launch,PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        nm.notify(id.hashCode(),NotificationCompat.Builder(context,"messages").setSmallIcon(android.R.drawable.ic_dialog_email)
            .setContentTitle("PrivRelay").setContentText("收到新短信，点击在应用中查看").setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setContentIntent(pi).setOnlyAlertOnce(true).setAutoCancel(true).build())
    }
    companion object {
        private val consumer=AtomicBoolean(false)
        private var foreground:NativeBridge?=null
        fun changed(){Handler(Looper.getMainLooper()).post{foreground?.channel?.invokeMethod("changed",null)}}
    }
}
