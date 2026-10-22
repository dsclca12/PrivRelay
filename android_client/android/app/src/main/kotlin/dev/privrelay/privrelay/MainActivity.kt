package dev.privrelay.privrelay

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import dev.privrelay.privrelay.sms.NativeBridge

class MainActivity : FlutterActivity() {
    override fun onCreate(savedInstanceState:android.os.Bundle?) {
        // Protect the first frame and recent-app thumbnail before Flutter starts.
        if(getSharedPreferences("runtime",0).getBoolean("screen_protection",true)) {
            window.addFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)
        }
        super.onCreate(savedInstanceState)
    }
    private var bridge:NativeBridge?=null
    override fun configureFlutterEngine(engine:FlutterEngine){super.configureFlutterEngine(engine);bridge=NativeBridge(this,engine.dartExecutor.binaryMessenger,this)}
    override fun onRequestPermissionsResult(request:Int,permissions:Array<out String>,grants:IntArray){super.onRequestPermissionsResult(request,permissions,grants);if(request==721)bridge?.permissionResult(grants)}
    override fun onActivityResult(request:Int,result:Int,data:android.content.Intent?){super.onActivityResult(request,result,data);if(request==722)bridge?.authenticationResult(result)}
    override fun onDestroy(){bridge?.close();bridge=null;super.onDestroy()}
}
