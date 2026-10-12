package com.osos.hmi.ui

import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
import android.webkit.JavascriptInterface
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import com.osos.hmi.AppContainer
import org.json.JSONObject

/**
 * The meter-map window: the very same web page the browser HMI serves
 * (source/browser-hmi/meter-map, bundled into the app's assets by the
 * syncMeterMapAssets Gradle task), so the two cannot drift apart.
 *
 * The page does not open its own broker connection. This app already has one, so
 * commands go out through [MapBridge] and every fleet message the page needs is
 * pushed in through OsosBridge.onMessage (see AppContainer.mapSink).
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun MeterMapScreen(c: AppContainer, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val connected by c.client.connected.collectAsState()
    val holder = remember { arrayOfNulls<WebView>(1) }
    val chooser = remember { arrayOfNulls<ValueCallback<Array<Uri>>>(1) }

    // <input type=file> inside a WebView does nothing unless the host answers it.
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        chooser[0]?.onReceiveValue(uri?.let { arrayOf(it) })
        chooser[0] = null
    }

    BackHandler(onBack = onClose)

    // Keep the page told whether the broker is up.
    LaunchedEffect(connected) {
        holder[0]?.post {
            holder[0]?.evaluateJavascript("window.OsosBridge&&OsosBridge.onState($connected)", null)
        }
    }

    DisposableEffect(Unit) {
        c.mapSink = { topic, text ->
            val wv = holder[0]
            wv?.post {
                wv.evaluateJavascript(
                    "window.OsosBridge&&OsosBridge.onMessage(${JSONObject.quote(topic)},${JSONObject.quote(text)})",
                    null,
                )
            }
        }
        onDispose {
            c.mapSink = null
            holder[0]?.destroy()
            holder[0] = null
        }
    }

    AndroidView(
        modifier = Modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.statusBars),
        factory = { context ->
            WebView(context).apply {
                holder[0] = this
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true            // the profile library lives in localStorage
                settings.allowFileAccess = false             // assets are exempt; nothing else is readable
                settings.allowContentAccess = false
                settings.setSupportZoom(false)
                webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                        // The page's "back to the HMI" link, or anything else that is not the page itself.
                        if (!request.url.toString().contains("/android_asset/meter-map/")) {
                            onClose()
                            return true
                        }
                        return false
                    }
                }
                webChromeClient = object : WebChromeClient() {
                    override fun onShowFileChooser(
                        view: WebView,
                        callback: ValueCallback<Array<Uri>>,
                        params: FileChooserParams,
                    ): Boolean {
                        chooser[0]?.onReceiveValue(null)
                        chooser[0] = callback
                        picker.launch(arrayOf("*/*"))
                        return true
                    }
                }
                addJavascriptInterface(
                    MapBridge(c) { name, text ->
                        post {
                            val send = Intent(Intent.ACTION_SEND).apply {
                                type = "text/plain"
                                putExtra(Intent.EXTRA_SUBJECT, name)
                                putExtra(Intent.EXTRA_TEXT, text)
                            }
                            ctx.startActivity(Intent.createChooser(send, name))
                        }
                    },
                    "OsosAndroid",
                )
                val sel = c.selected.value
                val query = buildString {
                    if (sel != null) append("?modem=").append(Uri.encode(sel.mid)).append("&analyzer=").append(Uri.encode(sel.aid))
                }
                loadUrl("file:///android_asset/meter-map/index.html$query")
            }
        },
    )
}

/** What the page may ask of the app. Everything else it learns from pushed messages. */
class MapBridge(
    private val c: AppContainer,
    private val share: (name: String, text: String) -> Unit,
) {
    /** Publishes a command to a modem; returns its id, which the ack carries back. */
    @JavascriptInterface
    fun send(mid: String, action: String, argsJson: String): String =
        c.client.publishCmd(mid, action, JSONObject(argsJson))

    /** Retained topics already received (registry, status, profiles), as {topic: payload}. */
    @JavascriptInterface
    fun snapshot(): String = JSONObject(c.retained.toMap()).toString()

    @JavascriptInterface
    fun connected(): Boolean = c.client.connected.value

    @JavascriptInterface
    fun shareText(name: String, text: String) = share(name, text)
}
