package dev.privrelay.privrelay.sms

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import io.flutter.FlutterInjector
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.embedding.engine.dart.DartExecutor
import dev.privrelay.privrelay.R

/** Optional, explicitly user-started runtime for more responsive background draining. */
class ForegroundSyncService : Service() {
    private var engine: FlutterEngine? = null
    private var bridge: NativeBridge? = null

    override fun onCreate() {
        super.onCreate()
        val manager = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL, getString(R.string.sync_notification_channel), NotificationManager.IMPORTANCE_LOW)
            )
        }
        startForeground(NOTIFICATION_ID, buildNotification())
        if (!SyncWorker.enabled(this) || !enabled(this)) {
            stopSelf()
            return
        }
        SyncWorker.periodic(this)
        SyncWorker.enqueue(this)
        startPersistentSocket()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!SyncWorker.enabled(this) || !enabled(this)) {
            stopSelf(startId)
            return START_NOT_STICKY
        }
        SyncWorker.enqueue(this)
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun startPersistentSocket() {
        try {
            val loader = FlutterInjector.instance().flutterLoader()
            loader.startInitialization(applicationContext)
            loader.ensureInitializationComplete(applicationContext, null)
            val runtime = FlutterEngine(applicationContext)
            engine = runtime
            bridge = NativeBridge(applicationContext, runtime.dartExecutor.binaryMessenger, persistentOwner = true)
            runtime.dartExecutor.executeDartEntrypoint(
                DartExecutor.DartEntrypoint(loader.findAppBundlePath(), "foregroundListenMain")
            )
        } catch (error: Exception) {
            Log.e("PrivRelaySync", "Could not start persistent socket runtime", error)
        }
    }

    override fun onDestroy() {
        bridge?.close()
        bridge = null
        engine?.destroy()
        engine = null
        super.onDestroy()
    }

    @Suppress("OVERRIDE_DEPRECATION")
    override fun onTimeout(startId: Int) {
        stopForSystemLimit(startId)
    }

    override fun onTimeout(startId: Int, foregroundServiceType: Int) {
        stopForSystemLimit(startId)
    }

    private fun stopForSystemLimit(startId: Int) {
        getSharedPreferences("runtime", 0).edit().putBoolean("foreground_sync", false).apply()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf(startId)
    }

    private fun buildNotification(): Notification {
        val launch = packageManager.getLaunchIntentForPackage(packageName)
        val pending = launch?.let {
            PendingIntent.getActivity(this, 0, it, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        }
        return NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setContentTitle(getString(R.string.sync_notification_title))
            .setContentText(getString(R.string.sync_notification_body))
            .setContentIntent(pending)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .build()
    }

    companion object {
        private const val CHANNEL = "background_sync"
        private const val NOTIFICATION_ID = 8788

        fun enabled(context: Context) = context.getSharedPreferences("runtime", 0).getBoolean("foreground_sync", false)

        fun setEnabled(context: Context, enabled: Boolean) {
            context.getSharedPreferences("runtime", 0).edit().putBoolean("foreground_sync", enabled).apply()
            val intent = Intent(context, ForegroundSyncService::class.java)
            if (enabled) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(intent)
                else context.startService(intent)
            } else {
                context.stopService(intent)
            }
        }
    }
}
