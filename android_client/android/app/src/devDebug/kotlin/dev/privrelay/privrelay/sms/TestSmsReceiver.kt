package dev.privrelay.privrelay.sms
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Shell-only synthetic input. Absent from every release and prod build. */
class TestSmsReceiver:BroadcastReceiver(){
    override fun onReceive(context:Context,intent:Intent){
        if(intent.getBooleanExtra("status",false)) {resultData="spool_count="+Spool(context).use{it.count()};return}
        val stamp=intent.getLongExtra("timestamp",System.currentTimeMillis())
        Spool(context).use{it.insert("PR-BACKGROUND","PrivRelay synthetic background recovery fixture",stamp,999,0)}
        SyncWorker.enqueue(context)
    }
}
