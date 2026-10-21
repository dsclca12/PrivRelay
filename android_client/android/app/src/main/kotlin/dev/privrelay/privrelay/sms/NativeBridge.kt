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
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import android.util.Base64

class NativeBridge(private val context:Context, messenger:BinaryMessenger, private val activity:Activity? = null) {
    private val channel = MethodChannel(messenger,"dev.privrelay/sms")
    private var ownsLock=false
    private var pendingPermission:MethodChannel.Result?=null
    init {
        if(activity!=null) foreground=this
        channel.setMethodCallHandler { call,result ->
            try {
                when(call.method) {
                    "status" -> result.success(mapOf("sms" to granted(Manifest.permission.RECEIVE_SMS),"notifications" to (Build.VERSION.SDK_INT<33 || granted(Manifest.permission.POST_NOTIFICATIONS)),"spool_count" to Spool(context).use{it.count()}))
                    "requestSms" -> request(Manifest.permission.RECEIVE_SMS,result)
                    "requestNotifications" -> if(Build.VERSION.SDK_INT>=33) request(Manifest.permission.POST_NOTIFICATIONS,result) else result.success(true)
                    "peek" -> result.success(Spool(context).use{it.peek()})
                    "ack" -> { Spool(context).use{it.ack((call.arguments as List<*>).map{v->v as String})}; result.success(null) }
                    "lock" -> { if(!ownsLock) ownsLock=consumer.compareAndSet(false,true); result.success(ownsLock) }
                    "unlock" -> {releaseLock();result.success(null)}
                    "identity" -> result.success(identity())
                    "sign" -> {val store=keyStore(); val sig=Signature.getInstance("SHA256withECDSA");sig.initSign(store.getKey("privrelay_identity",null) as java.security.PrivateKey);sig.update((call.arguments as String).toByteArray());result.success(Base64.encodeToString(sig.sign(),Base64.NO_WRAP))}
                    "initialize" -> {SyncWorker.periodic(context);result.success(null)}
                    "schedule" -> {SyncWorker.enqueue(context,(call.arguments as? Number)?.toLong() ?: 30,true);result.success(null)}
                    "background" -> {context.getSharedPreferences("runtime",0).edit().putBoolean("background",call.arguments as Boolean).apply(); if(call.arguments==true) {SyncWorker.periodic(context);SyncWorker.enqueue(context)} else SyncWorker.cancel(context);result.success(null)}
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
    fun permissionResult(grants:IntArray) {pendingPermission?.success(grants.isNotEmpty() && grants.all{it==PackageManager.PERMISSION_GRANTED});pendingPermission=null}
    private fun granted(permission:String)=context.checkSelfPermission(permission)==PackageManager.PERMISSION_GRANTED
    private fun request(permission:String,result:MethodChannel.Result) {
        if(granted(permission)) {result.success(true);return}
        if(activity==null || pendingPermission!=null){result.success(false);return}
        pendingPermission=result;activity.requestPermissions(arrayOf(permission),721)
    }
    private fun releaseLock(){if(ownsLock){ownsLock=false;consumer.set(false)}}
    fun close(){releaseLock();if(foreground===this)foreground=null;channel.setMethodCallHandler(null);pendingPermission?.success(false);pendingPermission=null}
    private fun keyStore()=KeyStore.getInstance("AndroidKeyStore").apply{load(null)}
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
