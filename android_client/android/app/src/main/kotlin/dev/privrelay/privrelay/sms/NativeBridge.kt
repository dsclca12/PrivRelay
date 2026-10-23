package dev.privrelay.privrelay.sms

import android.Manifest
import android.app.Activity
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.role.RoleManager
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
import dev.privrelay.privrelay.R

class NativeBridge(private val context:Context, messenger:BinaryMessenger, private val activity:Activity? = null, private val persistentOwner:Boolean = activity != null) {
    private val channel = MethodChannel(messenger,"dev.privrelay/sms")
    private var vaultCachePassphrase:String?=null
    private var vaultCacheSalt:String?=null
    private var vaultCacheKey:SecretKeySpec?=null
    private var ownsLock=false
    private var pendingPermission:MethodChannel.Result?=null
    private var pendingAuthentication:MethodChannel.Result?=null
    private var pendingSmsRole:MethodChannel.Result?=null
    init {
        if(persistentOwner) synchronized(NativeBridge::class.java) {
            if(activity==null) serviceBridge=this else activityBridge=this
        }
        channel.setMethodCallHandler { call,result ->
            try {
                when(call.method) {
                    "status" -> result.success(mapOf("sms" to granted(Manifest.permission.RECEIVE_SMS),"read_sms" to granted(Manifest.permission.READ_SMS),"send_sms" to granted(Manifest.permission.SEND_SMS),"default_sms" to isDefaultSmsApp(),"notifications" to (Build.VERSION.SDK_INT<33 || granted(Manifest.permission.POST_NOTIFICATIONS)),"foreground_sync" to ForegroundSyncService.enabled(context),"spool_count" to Spool(context).use{it.count()}))
                    "takeLiveRelays" -> result.success(takeLiveRelays())
                    "publishLiveRelay" -> {
                        val values=call.arguments as? Map<*,*> ?: error("Invalid live relay envelope")
                        val message=values.entries.associate { (key,value) ->
                            (key as? String ?: error("Invalid live relay field")) to (value ?: error("Null live relay field"))
                        }
                        publishLiveRelay(message)
                        result.success(null)
                    }
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
                    "requestSmsRole" -> requestSmsRole(result)
                    "requestReadSms" -> request(Manifest.permission.READ_SMS,result)
                    "requestSendSms" -> request(Manifest.permission.SEND_SMS,result)
                    "sendSms" -> {
                        if (!granted(Manifest.permission.SEND_SMS)) throw SecurityException("SEND_SMS permission required")
                        val args=call.arguments as Map<*,*>
                        val address=(args["address"] as? String)?.trim().orEmpty()
                        val body=args["body"] as? String ?: ""
                        require(address.isNotEmpty() && address.length<=40 && body.isNotBlank() && body.length<=5000) { "Invalid SMS address or body" }
                        val manager=context.getSystemService(android.telephony.SmsManager::class.java)
                        val parts=manager.divideMessage(body)
                        if(parts.size<=1) manager.sendTextMessage(address,null,body,null,null)
                        else manager.sendMultipartTextMessage(address,null,parts,null,null)
                        result.success(mapOf("parts" to parts.size))
                    }
                    "importHistory" -> {
                        if (!granted(Manifest.permission.READ_SMS)) throw SecurityException("READ_SMS permission required")
                        val limit = ((call.arguments as? Number)?.toInt() ?: 500).coerceIn(1, 5000)
                        val rows = mutableListOf<Map<String, Any>>()
                        val projection = arrayOf(android.provider.Telephony.Sms.ADDRESS,
                            android.provider.Telephony.Sms.BODY, android.provider.Telephony.Sms.DATE, android.provider.Telephony.Sms.SUBSCRIPTION_ID)
                        context.contentResolver.query(android.provider.Telephony.Sms.Inbox.CONTENT_URI, projection, null, null, "date ASC")?.use { cursor ->
                            val addressCol=cursor.getColumnIndexOrThrow(android.provider.Telephony.Sms.ADDRESS)
                            val bodyCol=cursor.getColumnIndexOrThrow(android.provider.Telephony.Sms.BODY)
                            val dateCol=cursor.getColumnIndexOrThrow(android.provider.Telephony.Sms.DATE)
                            val subCol=cursor.getColumnIndex(android.provider.Telephony.Sms.SUBSCRIPTION_ID)
                            val start=maxOf(0, cursor.count-limit)
                            if (start > 0) cursor.moveToPosition(start-1)
                            while (rows.size < limit && cursor.moveToNext()) {
                                val sub=if(subCol>=0 && !cursor.isNull(subCol)) cursor.getInt(subCol) else -1
                                val slot=if(Build.VERSION.SDK_INT>=22 && sub>=0) android.telephony.SubscriptionManager.from(context).activeSubscriptionInfoList?.firstOrNull{it.subscriptionId==sub}?.simSlotIndex ?: -1 else -1
                                val sender=cursor.getString(addressCol) ?: ""
                                val body=cursor.getString(bodyCol) ?: ""
                                val received=cursor.getLong(dateCol)
                                val stableId=Spool.stableId(sender,body,received,sub)
                                rows.add(mapOf("message_id" to stableId, "sender" to sender,
                                    "body" to body, "received_at" to received, "subscription_id" to sub, "slot" to slot))
                            }
                        } ?: throw IllegalStateException("SMS provider unavailable")
                        result.success(rows)
                    }
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
                    "background" -> {context.getSharedPreferences("runtime",0).edit().putBoolean("background",call.arguments as Boolean).apply(); if(call.arguments==true) {SyncWorker.periodic(context);SyncWorker.enqueue(context)} else {SyncWorker.cancel(context);ForegroundSyncService.setEnabled(context,false)};result.success(null)}
                    "foregroundSync" -> {val enabled=call.arguments as Boolean;if(enabled&&!SyncWorker.enabled(context)) throw IllegalStateException("请先开启后台补发");ForegroundSyncService.setEnabled(context,enabled);result.success(null)}
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
    fun smsRoleResult(result:Int) { pendingSmsRole?.success(isDefaultSmsApp()); pendingSmsRole=null }
    fun refreshStatus(attempt:Int=0) {
        channel.invokeMethod("statusChanged", null, object:MethodChannel.Result {
            override fun success(value:Any?) {}
            override fun error(code:String,message:String?,details:Any?) { if(attempt<10) Handler(Looper.getMainLooper()).postDelayed({refreshStatus(attempt+1)},500) }
            override fun notImplemented() { if(attempt<10) Handler(Looper.getMainLooper()).postDelayed({refreshStatus(attempt+1)},500) }
        })
    }
    fun handleIntent(intent:Intent?) {
        if (intent?.action != Intent.ACTION_SENDTO) return
        val uri=intent.data ?: return
        val address=uri.schemeSpecificPart?.substringBefore('?')?.trim().orEmpty()
        if (address.isEmpty()) return
        val body=intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString()
            ?: intent.getStringExtra("sms_body").orEmpty()
        fun dispatch(attempt:Int) {
            if (attempt>=10) return
            Handler(Looper.getMainLooper()).postDelayed({
                channel.invokeMethod("composeIntent", mapOf("address" to address,"body" to body), object:MethodChannel.Result {
                    override fun success(value:Any?) {}
                    override fun error(code:String,message:String?,details:Any?) { if(code=="channel-error") dispatch(attempt+1) }
                    override fun notImplemented() { dispatch(attempt+1) }
                })
            },if(attempt==0) 700 else 500)
        }
        dispatch(0)
    }
    private fun isDefaultSmsApp():Boolean = if(Build.VERSION.SDK_INT>=Build.VERSION_CODES.KITKAT) context.packageName==android.provider.Telephony.Sms.getDefaultSmsPackage(context) else false
    private fun requestSmsRole(result:MethodChannel.Result) {
        if(isDefaultSmsApp()) { result.success(true); return }
        val owner=activity
        if(owner==null || pendingSmsRole!=null) { result.success(false); return }
        val requestIntent = if(Build.VERSION.SDK_INT>=Build.VERSION_CODES.Q) {
            val manager=context.getSystemService(RoleManager::class.java)
            if(!manager.isRoleAvailable(RoleManager.ROLE_SMS)) { result.success(false); return }
            manager.createRequestRoleIntent(RoleManager.ROLE_SMS)
        } else {
            Intent(android.provider.Telephony.Sms.Intents.ACTION_CHANGE_DEFAULT)
                .putExtra(android.provider.Telephony.Sms.Intents.EXTRA_PACKAGE_NAME,context.packageName)
        }
        pendingSmsRole=result
        owner.startActivityForResult(requestIntent,723)
    }
    fun permissionResult(grants:IntArray) {pendingPermission?.success(grants.isNotEmpty() && grants.all{it==PackageManager.PERMISSION_GRANTED});pendingPermission=null}
    private fun granted(permission:String)=context.checkSelfPermission(permission)==PackageManager.PERMISSION_GRANTED
    private fun request(permission:String,result:MethodChannel.Result) {
        if(granted(permission)) {result.success(true);return}
        if(activity==null || pendingPermission!=null){result.success(false);return}
        pendingPermission=result;activity.requestPermissions(arrayOf(permission),721)
    }
    private fun releaseLock(){if(ownsLock){ownsLock=false;consumer.set(false)}}
    fun close(){pendingAuthentication?.success(false);pendingAuthentication=null;pendingSmsRole?.success(false);pendingSmsRole=null;releaseLock();vaultCachePassphrase=null;vaultCacheSalt=null;vaultCacheKey=null;synchronized(NativeBridge::class.java){if(activityBridge===this)activityBridge=null;if(serviceBridge===this)serviceBridge=null};channel.setMethodCallHandler(null);pendingPermission?.success(false);pendingPermission=null}
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
        nm.createNotificationChannel(NotificationChannel("messages",context.getString(R.string.sms_notification_channel),NotificationManager.IMPORTANCE_DEFAULT))
        val launch=context.packageManager.getLaunchIntentForPackage(context.packageName) ?: return
        val pi=PendingIntent.getActivity(context,0,launch,PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        nm.notify(id.hashCode(),NotificationCompat.Builder(context,"messages").setSmallIcon(android.R.drawable.ic_dialog_email)
            .setContentTitle(context.getString(R.string.sms_notification_title)).setContentText(context.getString(R.string.sms_notification_body)).setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setContentIntent(pi).setOnlyAlertOnce(true).setAutoCancel(true).build())
    }
    companion object {
        private val consumer=AtomicBoolean(false)
        private var activityBridge:NativeBridge?=null
        private var serviceBridge:NativeBridge?=null
        private val relayLock=Any()
        private val liveRelays=ArrayDeque<Map<String,Any>>()
        private fun takeLiveRelays():List<Map<String,Any>> = synchronized(relayLock) {
            liveRelays.toList().also { liveRelays.clear() }
        }
        private fun publishLiveRelay(message:Map<String,Any>) { synchronized(relayLock) {
            liveRelays.removeAll { it["message_id"] == message["message_id"] }
            liveRelays.addFirst(HashMap(message))
            while(liveRelays.size>30) liveRelays.removeLast()
        };Handler(Looper.getMainLooper()).post { activityBridge?.channel?.invokeMethod("liveRelay",message) } }
        fun changed(message:Map<String,Any>? = null){Handler(Looper.getMainLooper()).post{
            val bridge=serviceBridge ?: activityBridge
            if(message!=null) bridge?.channel?.invokeMethod("smsReceived",message)
            bridge?.channel?.invokeMethod("changed",null)
        }}
    }
}
