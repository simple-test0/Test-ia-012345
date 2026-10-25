package com.orienteering.gpxoverlay

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.util.Base64
import android.view.View
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.URLUtil
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebStorage
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.PopupMenu
import android.widget.ProgressBar
import android.widget.TextView
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

/**
 * Garmin Connect dans l'app : l'utilisateur se connecte sur la vraie page de Garmin
 * (ses identifiants ne passent pas par Trace O), choisit une activité et l'exporte.
 * Le fichier exporté est récupéré et renvoyé à l'écran principal.
 */
class GarminActivity : Activity() {

    private lateinit var web: WebView
    private lateinit var progress: ProgressBar
    private lateinit var banner: View
    private val io = Executors.newSingleThreadExecutor()
    private val prefs by lazy { getSharedPreferences("state", MODE_PRIVATE) }

    /** Adresse de la page affichée (le pont JavaScript n'accepte que les pages Garmin). */
    @Volatile
    internal var pageUrl: String? = null

    internal val bridge = Bridge()

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_garmin)
        web = findViewById(R.id.web)
        progress = findViewById(R.id.webProgress)
        banner = findViewById(R.id.garminBanner)

        findViewById<View>(R.id.btnGarminClose).setOnClickListener { finish() }
        findViewById<View>(R.id.btnGarminMore).setOnClickListener { showMenu(it) }
        findViewById<View>(R.id.btnBannerOk).setOnClickListener {
            banner.visibility = View.GONE
            prefs.edit().putBoolean("garminBannerSeen", true).apply()
        }
        if (prefs.getBoolean("garminBannerSeen", false)) banner.visibility = View.GONE

        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            loadWithOverviewMode = true
            useWideViewPort = true
            builtInZoomControls = true
            displayZoomControls = false
            allowFileAccess = false
            allowContentAccess = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            setSupportMultipleWindows(false)
        }
        applyUserAgent()
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true)
        web.addJavascriptInterface(bridge, "TraceOBridge")
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url
                if (isGarmin(url)) return false
                // Hors de Garmin : ouverture dans le navigateur du téléphone.
                try { startActivity(Intent(Intent.ACTION_VIEW, url)) } catch (_: Exception) { }
                return true
            }

            override fun onPageStarted(view: WebView, url: String, favicon: android.graphics.Bitmap?) {
                pageUrl = url
                progress.visibility = View.VISIBLE
            }

            override fun onPageFinished(view: WebView, url: String) {
                pageUrl = url
                progress.visibility = View.GONE
                findViewById<TextView>(R.id.garminSubtitle).text = Uri.parse(url).host ?: ""
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView, newProgress: Int) { progress.progress = newProgress }
        }
        web.setDownloadListener { url, userAgent, contentDisposition, mimeType, _ ->
            val name = URLUtil.guessFileName(url, contentDisposition, mimeType)
            if (url.startsWith("blob:")) fetchBlob(url, name)
            else download(url, userAgent, name)
        }
        if (savedInstanceState != null) web.restoreState(savedInstanceState)
        else load(START_URL)
    }

    private fun load(url: String) {
        pageUrl = url
        web.loadUrl(url)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    @Deprecated("Gestion simple du retour")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else @Suppress("DEPRECATION") super.onBackPressed()
    }

    override fun onDestroy() {
        super.onDestroy()
        io.shutdown()
        web.destroy()
    }

    private fun showMenu(anchor: View) {
        val popup = PopupMenu(this, anchor)
        popup.menu.add(0, 1, 0, "Mes activités")
        popup.menu.add(0, 2, 1, "Recharger")
        popup.menu.add(0, 3, 2, "Version ordinateur").apply {
            isCheckable = true; isChecked = prefs.getBoolean("garminDesktop", false)
        }
        popup.menu.add(0, 4, 3, "Aide")
        popup.menu.add(0, 5, 4, "Se déconnecter de Garmin")
        popup.setOnMenuItemClickListener {
            when (it.itemId) {
                1 -> load(START_URL)
                2 -> web.reload()
                3 -> {
                    prefs.edit().putBoolean("garminDesktop", !prefs.getBoolean("garminDesktop", false)).apply()
                    applyUserAgent(); web.reload()
                }
                4 -> banner.visibility = View.VISIBLE
                5 -> {
                    CookieManager.getInstance().removeAllCookies(null)
                    WebStorage.getInstance().deleteAllData()
                    web.clearCache(true)
                    load(START_URL)
                }
            }
            true
        }
        popup.show()
    }

    /** Version ordinateur : utile si la page mobile de Garmin cache le bouton d'export. */
    private fun applyUserAgent() {
        val desktop = prefs.getBoolean("garminDesktop", false)
        web.settings.userAgentString = if (desktop) DESKTOP_UA else null
    }

    private fun isGarmin(u: Uri?): Boolean {
        val host = u?.host?.lowercase() ?: return false
        return u.scheme == "https" && (host == "garmin.com" || host.endsWith(".garmin.com"))
    }

    private fun download(url: String, userAgent: String?, name: String) {
        val uri = Uri.parse(url)
        if (!isGarmin(uri)) { info("Téléchargement refusé : ce fichier ne vient pas de Garmin."); return }
        progress.visibility = View.VISIBLE
        info("Récupération de l'activité…")
        val cookies = CookieManager.getInstance().getCookie(url)
        io.execute {
            try {
                val conn = URL(url).openConnection() as HttpURLConnection
                conn.connectTimeout = 20_000
                conn.readTimeout = 60_000
                cookies?.let { conn.setRequestProperty("Cookie", it) }
                conn.setRequestProperty("User-Agent", userAgent ?: web.settings.userAgentString)
                if (conn.responseCode !in 200..299) throw IllegalStateException("réponse ${conn.responseCode} de Garmin")
                val bytes = conn.inputStream.use { readLimited(it) }
                deliver(bytes, name)
            } catch (e: Exception) {
                runOnUiThread { progress.visibility = View.GONE; info("Échec du téléchargement : ${e.message}") }
            }
        }
    }

    /** Certains exports Garmin passent par un « blob » : on le lit depuis la page. */
    private fun fetchBlob(url: String, name: String) {
        bridge.pendingName = name
        val safe = url.replace("'", "")
        web.evaluateJavascript(
            "(function(){fetch('$safe').then(function(r){return r.blob();}).then(function(b){" +
                "var fr=new FileReader();fr.onload=function(){TraceOBridge.onData(fr.result.split(',')[1], b.type||'');};" +
                "fr.readAsDataURL(b);}).catch(function(e){TraceOBridge.onError(String(e));});})()",
            null
        )
    }

    inner class Bridge {
        @Volatile var pendingName: String = "garmin"

        @JavascriptInterface
        fun onData(base64: String, type: String) {
            if (!isGarmin(pageUrl?.let(Uri::parse))) return
            try {
                val bytes = Base64.decode(base64, Base64.DEFAULT)
                if (bytes.size > MAX_BYTES) throw IllegalStateException("fichier trop gros")
                var name = pendingName
                if (!name.contains('.')) name += when {
                    type.contains("zip") -> ".zip"
                    type.contains("gpx") -> ".gpx"
                    type.contains("tcx") -> ".tcx"
                    else -> ".fit"
                }
                deliver(bytes, name)
            } catch (e: Exception) {
                runOnUiThread { info("Échec de la récupération : ${e.message}") }
            }
        }

        @JavascriptInterface
        fun onError(msg: String) {
            runOnUiThread { info("Échec de la récupération : $msg") }
        }
    }

    private fun readLimited(input: java.io.InputStream): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        val buf = ByteArray(64 * 1024)
        var total = 0
        while (true) {
            val n = input.read(buf)
            if (n < 0) break
            total += n
            if (total > MAX_BYTES) throw IllegalStateException("fichier trop gros")
            out.write(buf, 0, n)
        }
        return out.toByteArray()
    }

    /** Enregistre le fichier dans l'app et le renvoie à l'écran principal. */
    private fun deliver(bytes: ByteArray, name: String) {
        val safe = name.replace(Regex("[^A-Za-z0-9._-]"), "_").takeLast(80)
        val dir = File(filesDir, "imports").apply { mkdirs() }
        val file = File(dir, "${System.currentTimeMillis()}_$safe")
        file.writeBytes(bytes)
        runOnUiThread {
            setResult(RESULT_OK, Intent().setData(Uri.fromFile(file)).putExtra(EXTRA_NAME, safe))
            finish()
        }
    }

    private fun info(msg: String) {
        findViewById<TextView>(R.id.garminSubtitle).text = msg
    }

    companion object {
        const val START_URL = "https://connect.garmin.com/app/activities"
        const val EXTRA_NAME = "name"
        private const val MAX_BYTES = 64 * 1024 * 1024
        private const val DESKTOP_UA =
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    }
}
