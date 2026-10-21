package dev.privrelay.privrelay.sms

import android.content.Context
import androidx.work.*
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.embedding.engine.dart.DartExecutor
import io.flutter.FlutterInjector
import io.flutter.plugin.common.MethodChannel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.util.concurrent.TimeUnit

class SyncWorker(context:Context,params:WorkerParameters):CoroutineWorker(context,params) {
    override suspend fun doWork():Result {
        if(!enabled(applicationContext))return Result.success()
        if(!inputData.getBoolean("force_sync",false) && Spool(applicationContext).use{it.count()}==0) return Result.success()
        return withContext(Dispatchers.Main) {
            val loader=FlutterInjector.instance().flutterLoader()
            loader.startInitialization(applicationContext);loader.ensureInitializationComplete(applicationContext,null)
            val engine=FlutterEngine(applicationContext)
            val bridge=NativeBridge(applicationContext,engine.dartExecutor.binaryMessenger)
            val done=CompletableDeferred<Boolean>()
            MethodChannel(engine.dartExecutor.binaryMessenger,"dev.privrelay/worker").setMethodCallHandler { call,result ->
                if(call.method=="done"){result.success(null);done.complete(true)}else result.notImplemented()
            }
            try {
                engine.dartExecutor.executeDartEntrypoint(DartExecutor.DartEntrypoint(loader.findAppBundlePath(),"backgroundMain"))
                if(withTimeoutOrNull(90000){done.await()}==true) Result.success() else Result.retry()
            } finally {bridge.close();engine.destroy()}
        }
    }
    companion object {
        fun enabled(context:Context)=context.getSharedPreferences("runtime",0).getBoolean("background",true)
        fun enqueue(context:Context,delay:Long=0,forceSync:Boolean=false) {
            if(!enabled(context))return
            val builder=OneTimeWorkRequestBuilder<SyncWorker>().setInitialDelay(delay,TimeUnit.SECONDS)
                .setInputData(workDataOf("force_sync" to forceSync))
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL,30,TimeUnit.SECONDS)
            if(delay>0) builder.setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            val request=builder.build()
            WorkManager.getInstance(context).enqueueUniqueWork("sms-consume",ExistingWorkPolicy.APPEND_OR_REPLACE,request)
        }
        fun periodic(context:Context) {
            if(!enabled(context))return
            WorkManager.getInstance(context).enqueueUniquePeriodicWork("sms-periodic",ExistingPeriodicWorkPolicy.KEEP,
                PeriodicWorkRequestBuilder<SyncWorker>(15,TimeUnit.MINUTES)
                    .setInputData(workDataOf("force_sync" to true))
                    .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build())
        }
        fun cancel(context:Context){WorkManager.getInstance(context).cancelUniqueWork("sms-periodic");WorkManager.getInstance(context).cancelUniqueWork("sms-consume")}
    }
}
