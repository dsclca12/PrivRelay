package dev.privrelay.privrelay

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import dev.privrelay.privrelay.sms.NativeBridge

class MainActivity : FlutterActivity() {
    private var bridge:NativeBridge?=null
    override fun configureFlutterEngine(engine:FlutterEngine){super.configureFlutterEngine(engine);bridge=NativeBridge(this,engine.dartExecutor.binaryMessenger,this)}
    override fun onRequestPermissionsResult(request:Int,permissions:Array<out String>,grants:IntArray){super.onRequestPermissionsResult(request,permissions,grants);if(request==721)bridge?.permissionResult(grants)}
    override fun onDestroy(){bridge?.close();bridge=null;super.onDestroy()}
}
