package com.orienteering.gpxoverlay

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.OpenableColumns
import android.text.InputType
import android.view.Gravity
import android.view.MenuItem
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.ImageButton
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.PopupMenu
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.TextView
import java.io.File
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import java.util.concurrent.Executors

class MainActivity : Activity(), OverlayView.Listener {

    private lateinit var overlay: OverlayView
    private lateinit var root: View
    private lateinit var topBar: View
    private lateinit var subtitle: TextView
    private lateinit var emptyState: View
    private lateinit var home: View
    private val sessions by lazy { SessionStore(File(filesDir, "sessions")) }
    /** Session en cours (mise à jour automatiquement), ou null sur l'accueil. */
    private var currentSessionId: String? = null
    /** Fichiers encore en cours de chargement pendant une reprise de session (pas d'enregistrement avant). */
    private var restoringLoads = 0

    private var restoreFailed = false

    /** [ok] = faux si le fichier n'a pas pu être lu : la session enregistrée n'est alors pas écrasée. */
    private fun loadDone(ok: Boolean = true) {
        if (!ok && restoringLoads > 0) restoreFailed = true
        if (restoringLoads > 0 && --restoringLoads == 0) {
            if (restoreFailed) {
                // On se détache de la session pour ne pas perdre le fichier manquant.
                currentSessionId = null
                showSnack("Un fichier de la session est introuvable (déplacé ou supprimé ?)", null, null)
            } else saveCurrentSession()
            restoreFailed = false
        }
    }
    private lateinit var bottomPanel: View
    private lateinit var statsRow: View
    private lateinit var statDist: TextView
    private lateinit var statTime: TextView
    private lateinit var statPace: TextView
    private lateinit var legend: View
    private lateinit var legendBar: View
    private lateinit var legendLabel: TextView
    private lateinit var statGain: TextView
    private lateinit var statHr: TextView
    private lateinit var statGainBox: View
    private lateinit var statHrBox: View
    private lateinit var btnProfile: Button
    private lateinit var profileBox: View
    private lateinit var profile: ProfileView
    private lateinit var chipPace: TextView
    private lateinit var chipEle: TextView
    private lateinit var chipHr: TextView
    private var showProfile = false
    private lateinit var btnFit: View
    private lateinit var splitsSheet: View
    private lateinit var splitsList: LinearLayout
    private lateinit var splitsScroll: ScrollView
    private lateinit var splitsSummary: TextView
    private lateinit var snackbar: View
    private lateinit var snackText: TextView
    private lateinit var snackAction: Button
    private lateinit var hint: TextView
    private lateinit var progress: ProgressBar
    private lateinit var modeBar: View
    private lateinit var calibBar: View
    private lateinit var controlsBar: View
    private lateinit var replayBar: View
    private lateinit var btnMap: Button
    private lateinit var btnTrace: Button
    private lateinit var btnCalib: Button
    private lateinit var btnControls: Button
    private lateinit var btnReplay: Button
    private lateinit var btnPlay: ImageButton
    private lateinit var btnSpeed: Button
    private lateinit var replaySeek: SeekBar

    private val io = Executors.newSingleThreadExecutor()
    private val prefs by lazy { getSharedPreferences("state", MODE_PRIVATE) }

    private var mapUri: Uri? = null
    private var mapIsPdf = false
    private var mapPage = 0
    private var mapPageCount = 1
    private var mapPxPerMm: Double? = null
    private var gpxUri: Uri? = null
    private var mapName: String? = null
    private var trackName: String? = null
    private var selectedLeg = -1
    private val handler = Handler(Looper.getMainLooper())
    private val hideSnack = Runnable { snackbar.visibility = View.GONE }
    private var scaleDenominator = 10000
    private var imageDpi = 300

    /** Postes à remettre quand la carte restaurée sera chargée. */
    private var pendingControls: List<FloatArray>? = null
    private var pendingControlsMap: String? = null

    /** Passages aux postes calculés pour le replay. */
    private var replayPunches: List<Punch> = emptyList()
    private var userSeeking = false
    private val speeds = floatArrayOf(1f, 5f, 10f, 20f, 50f)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        overlay = findViewById(R.id.overlay)
        root = findViewById(R.id.root)
        topBar = findViewById(R.id.topBar)
        subtitle = findViewById(R.id.subtitle)
        emptyState = findViewById(R.id.emptyState)
        home = findViewById(R.id.home)
        bottomPanel = findViewById(R.id.bottomPanel)
        statsRow = findViewById(R.id.statsRow)
        statDist = findViewById(R.id.statDist)
        statTime = findViewById(R.id.statTime)
        statPace = findViewById(R.id.statPace)
        legend = findViewById(R.id.legend)
        legendBar = findViewById(R.id.legendBar)
        legendLabel = findViewById(R.id.legendLabel)
        statGain = findViewById(R.id.statGain)
        statHr = findViewById(R.id.statHr)
        statGainBox = findViewById(R.id.statGainBox)
        statHrBox = findViewById(R.id.statHrBox)
        btnProfile = findViewById(R.id.btnProfile)
        profileBox = findViewById(R.id.profileBox)
        profile = findViewById(R.id.profile)
        chipPace = findViewById(R.id.chipPace)
        chipEle = findViewById(R.id.chipEle)
        chipHr = findViewById(R.id.chipHr)
        btnFit = findViewById(R.id.btnFit)
        splitsSheet = findViewById(R.id.splitsSheet)
        splitsList = findViewById(R.id.splitsList)
        splitsScroll = findViewById(R.id.splitsScroll)
        splitsSummary = findViewById(R.id.splitsSummary)
        snackbar = findViewById(R.id.snackbar)
        snackText = findViewById(R.id.snackText)
        snackAction = findViewById(R.id.snackAction)
        hint = findViewById(R.id.hint)
        progress = findViewById(R.id.progress)
        modeBar = findViewById(R.id.modeBar)
        calibBar = findViewById(R.id.calibBar)
        controlsBar = findViewById(R.id.controlsBar)
        replayBar = findViewById(R.id.replayBar)
        btnMap = findViewById(R.id.btnMap)
        btnTrace = findViewById(R.id.btnTrace)
        btnCalib = findViewById(R.id.btnCalib)
        btnControls = findViewById(R.id.btnControls)
        btnReplay = findViewById(R.id.btnReplay)
        btnPlay = findViewById(R.id.btnPlay)
        btnSpeed = findViewById(R.id.btnSpeed)
        replaySeek = findViewById(R.id.replaySeek)

        val openMap = View.OnClickListener { pick(REQ_MAP, arrayOf("image/*", "application/pdf")) }
        val openTrack = View.OnClickListener { pick(REQ_GPX, null) }
        findViewById<View>(R.id.btnOpenMap).setOnClickListener(openMap)
        findViewById<View>(R.id.btnOpenTrack).setOnClickListener(openTrack)
        findViewById<View>(R.id.btnEmptyMap).setOnClickListener(openMap)
        findViewById<View>(R.id.btnEmptyTrack).setOnClickListener(openTrack)
        findViewById<View>(R.id.btnEmptyGarmin).setOnClickListener { openGarmin() }
        findViewById<View>(R.id.btnMore).setOnClickListener { showMoreMenu(it) }
        btnFit.setOnClickListener { overlay.fitView(animate = true) }
        findViewById<View>(R.id.btnSplitsClose).setOnClickListener { hideSplits() }
        legend.setOnClickListener { showColorDialog() }
        btnProfile.setOnClickListener {
            showProfile = !showProfile
            if (!showProfile) overlay.probeIndex = -1
            refreshUi()
        }
        chipPace.setOnClickListener { setMetric(ProfileView.Metric.PACE) }
        chipEle.setOnClickListener { setMetric(ProfileView.Metric.ELEVATION) }
        chipHr.setOnClickListener { setMetric(ProfileView.Metric.HEART_RATE) }
        profile.onPick = { i -> onProfilePick(i) }
        // Les panneaux flottants cachent une partie de la carte : on le signale à la vue.
        root.viewTreeObserver.addOnGlobalLayoutListener { updateInsets() }

        overlay.listener = this
        btnMap.setOnClickListener { overlay.mode = OverlayView.Mode.MAP }
        btnTrace.setOnClickListener {
            if (overlay.track == null) toast("Ouvrez d'abord une trace.")
            else overlay.mode = OverlayView.Mode.TRACE
        }
        btnCalib.setOnClickListener {
            if (overlay.track == null || overlay.mapBitmap == null) toast("Ouvrez une carte et une trace.")
            else overlay.mode = OverlayView.Mode.CALIBRATE
        }
        btnControls.setOnClickListener {
            if (overlay.mapBitmap == null) toast("Ouvrez d'abord une carte.")
            else { overlay.clearHighlight(); overlay.mode = OverlayView.Mode.CONTROLS }
        }
        btnReplay.setOnClickListener { startReplay() }
        findViewById<Button>(R.id.btnUndo).setOnClickListener { overlay.undoCalibration() }
        findViewById<Button>(R.id.btnDone).setOnClickListener { overlay.mode = OverlayView.Mode.MAP }
        findViewById<Button>(R.id.btnCtrlUndo).setOnClickListener { overlay.undoControl() }
        findViewById<Button>(R.id.btnCtrlClear).setOnClickListener {
            if (overlay.controls.isEmpty()) return@setOnClickListener
            val saved = overlay.controls.map { it.copyOf() }
            overlay.clearControls()
            showSnack("Postes effacés", "Annuler") { overlay.setControls(saved) }
        }
        findViewById<Button>(R.id.btnSplits).setOnClickListener { showSplits() }
        findViewById<Button>(R.id.btnCtrlDone).setOnClickListener { overlay.mode = OverlayView.Mode.MAP }
        findViewById<View>(R.id.btnReplayDone).setOnClickListener { overlay.mode = OverlayView.Mode.MAP }
        btnPlay.setOnClickListener { overlay.replayPlaying = !overlay.replayPlaying }
        btnSpeed.setOnClickListener {
            val i = speeds.indexOfFirst { it == overlay.replaySpeed }
            overlay.replaySpeed = speeds[(i + 1) % speeds.size]
            onReplayTick(overlay.replayTimeMs, overlay.replayPlaying)
        }
        replaySeek.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar, p: Int, fromUser: Boolean) {
                if (!fromUser) return
                val t = overlay.track ?: return
                val a = t.startTimeMs ?: return
                val b = t.endTimeMs ?: return
                overlay.setReplayTime(a + (b - a) * p / sb.max)
            }
            override fun onStartTrackingTouch(sb: SeekBar) { userSeeking = true }
            override fun onStopTrackingTouch(sb: SeekBar) { userSeeking = false }
        })

        overlay.colorMode = runCatching {
            OverlayView.ColorMode.valueOf(prefs.getString("colorMode", null) ?: "SPEED")
        }.getOrDefault(OverlayView.ColorMode.SPEED)
        profile.metric = runCatching {
            ProfileView.Metric.valueOf(prefs.getString("chartMetric", null) ?: "PACE")
        }.getOrDefault(ProfileView.Metric.PACE)
        showProfile = prefs.getBoolean("showProfile", false)
        overlay.lockTraceScale = prefs.getBoolean("lockScale", false)
        overlay.traceWidthDp = prefs.getFloat("traceWidth", 4f)
        overlay.replaySpeed = prefs.getFloat("replaySpeed", 10f).takeIf { v -> speeds.any { it == v } } ?: 10f
        scaleDenominator = prefs.getInt("scaleDen", 10000)
        imageDpi = prefs.getInt("dpi", 300)

        migrateLegacySession()
        handleIncoming(intent)
        buildHome()
        refreshUi()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIncoming(intent)
    }

    override fun onPause() {
        super.onPause()
        overlay.replayPlaying = false
        saveSession()
    }

    override fun onDestroy() {
        super.onDestroy()
        io.shutdown()
    }

    // ---------- Menu ----------

    private fun showMoreMenu(anchor: View) {
        val popup = PopupMenu(this, anchor)
        popup.menuInflater.inflate(R.menu.main, popup.menu)
        popup.menu.findItem(R.id.lock_scale).isChecked = overlay.lockTraceScale
        popup.menu.findItem(R.id.pdf_page).isVisible = mapIsPdf && mapPageCount > 1
        popup.setOnMenuItemClickListener { onMenuItem(it) }
        popup.show()
    }

    /** Action d'un élément du menu « ⋮ ». */
    fun onMenuItem(item: MenuItem): Boolean {
        when (item.itemId) {
            R.id.home -> goHome()
            R.id.garmin -> openGarmin()
            R.id.splits -> showSplits()
            R.id.map_scale -> showScaleDialog()
            R.id.pdf_page -> mapUri?.let { choosePdfPage(it, mapPageCount) }
            R.id.color_mode -> showColorDialog()
            R.id.lock_scale -> {
                overlay.lockTraceScale = !overlay.lockTraceScale
                toast(if (overlay.lockTraceScale) "Échelle de la trace verrouillée" else "Échelle de la trace libre")
                refreshUi()
            }
            R.id.trace_width -> showWidthDialog()
            R.id.reset_trace -> overlay.fitTraceToMap()
            R.id.export -> {
                if (overlay.mapBitmap == null) toast("Ouvrez d'abord une carte.")
                else startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    type = "image/jpeg"
                    putExtra(Intent.EXTRA_TITLE, "carte_trace.jpg")
                }, REQ_EXPORT)
            }
            R.id.help -> showHelp()
            else -> return false
        }
        return true
    }

    private fun showHelp() {
        AlertDialog.Builder(this)
            .setTitle("Comment ça marche")
            .setMessage(
                "1. Ouvrez la carte (image ou PDF) puis votre trace (GPX, FIT ou TCX).\n\n" +
                    "2. Calez la trace sur la carte :\n" +
                    "   • Ajuster : glissez la trace, tournez-la à deux doigts ;\n" +
                    "   • Caler : touchez un point de la trace puis le même endroit sur la carte (2 fois ou plus) ;\n" +
                    "   • ⋮ → Échelle : pour un PDF, la trace se met à la bonne taille.\n\n" +
                    "3. Postes : touchez la carte pour placer le départ, les postes, puis l'arrivée. " +
                    "Glissez un poste pour le déplacer, appui long pour le supprimer.\n\n" +
                    "4. Temps : vos temps intermédiaires. Touchez une section pour la voir sur la carte.\n\n" +
                    "5. Rejouer : revivez la course, à la vitesse de votre choix.\n\n" +
                    "6. Profil : graphique de l'allure, de l'altitude ou de la fréquence cardiaque. " +
                    "Touchez-le pour voir le point sur la carte. La couleur de la trace suit le graphique.\n\n" +
                    "Depuis Garmin : sur connect.garmin.com (navigateur), ouvrez l'activité, roue dentée → " +
                    "« Exporter le fichier d'origine » (ZIP avec le FIT : FC, altitude, allure) ou « Exporter au format GPX », " +
                    "puis ouvrez le fichier avec « Trace ». Depuis la montre branchée en USB : dossier GARMIN/Activity, fichiers .fit.\n\n" +
                    "Astuces : double-tap pour zoomer, bouton ⤢ pour revoir toute la carte, " +
                    "« Partager » un fichier vers Trace O depuis une autre app."
            )
            .setPositiveButton("OK", null)
            .show()
    }

    private fun pick(req: Int, mimes: Array<String>?) {
        val i = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "*/*"
            if (mimes != null) putExtra(Intent.EXTRA_MIME_TYPES, mimes)
        }
        startActivityForResult(i, req)
    }

    @Deprecated("API Activity simple, suffisante ici")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        val uri = data?.data
        if (resultCode != RESULT_OK || uri == null) return
        when (requestCode) {
            REQ_MAP -> { keepPermission(uri); pendingMapName = displayName(uri); openMap(uri, page = -1, refitTrace = true) }
            REQ_GPX -> { keepPermission(uri); pendingTrackName = displayName(uri); openGpx(uri, savedMatrix = null) }
            REQ_EXPORT -> exportTo(uri)
            REQ_GARMIN -> openImported(uri, data.getStringExtra(GarminActivity.EXTRA_NAME))
        }
    }

    private fun openGarmin() {
        startActivityForResult(Intent(this, GarminActivity::class.java), REQ_GARMIN)
    }

    /** Fichier déjà copié dans l'app (Garmin) : carte ou trace selon son contenu. */
    private fun openImported(uri: Uri, name: String?) {
        val file = File(uri.path ?: return)
        val head = ByteArray(16)
        val n = try { file.inputStream().use { it.read(head) } } catch (_: Exception) { -1 }
        if (n >= 4 && looksLikeMap(head)) {
            pendingMapName = name; openMap(uri, page = -1, refitTrace = true)
        } else {
            pendingTrackName = name; openGpx(uri, savedMatrix = null)
        }
    }

    private var pendingMapName: String? = null
    private var pendingTrackName: String? = null

    private fun displayName(uri: Uri): String? {
        if (uri.scheme == "file") return uri.lastPathSegment?.let { n ->
            // Fichiers importés : « horodatage-n_nom » → « nom ».
            if (Regex("^\\d+(-\\d+)?_.+").matches(n)) n.substringAfter('_') else n
        }
        return try {
            contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst() && !c.isNull(0)) c.getString(0) else null
            }
        } catch (_: Exception) { null }
    }

    private fun keepPermission(uri: Uri) {
        try {
            contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
        } catch (_: Exception) { }
    }

    // ---------- Fichiers reçus d'autres apps ----------

    @Suppress("DEPRECATION")
    private fun handleIncoming(intent: Intent?) {
        intent ?: return
        val uris = ArrayList<Uri>()
        when (intent.action) {
            Intent.ACTION_SEND -> (intent.getParcelableExtra(Intent.EXTRA_STREAM) as? Uri)?.let(uris::add)
            Intent.ACTION_SEND_MULTIPLE ->
                intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)?.let(uris::addAll)
            Intent.ACTION_VIEW -> intent.data?.let(uris::add)
            else -> return
        }
        if (uris.isEmpty()) {
            val text = intent.getStringExtra(Intent.EXTRA_TEXT)
            if (text != null && text.contains("strava", ignoreCase = true)) {
                AlertDialog.Builder(this)
                    .setTitle("Lien Strava")
                    .setMessage(
                        "Strava partage un lien, pas le fichier de la trace.\n\n" +
                            "Sur strava.com, ouvrez l'activité, menu « … » → « Exporter au format GPX », " +
                            "puis ouvrez le fichier téléchargé avec Trace O (ou bouton Trace)."
                    )
                    .setPositiveButton("OK", null)
                    .show()
            } else {
                toast("Aucun fichier reçu.")
            }
            return
        }
        // Évite de retraiter le même partage si l'activité est recréée.
        setIntent(Intent(this, MainActivity::class.java))
        busy(true)
        io.execute {
            val maps = ArrayList<Uri>()
            val tracks = ArrayList<Uri>()
            var error: String? = null
            for (u in uris) {
                try {
                    val (file, isMap) = importFile(u)
                    if (isMap) maps.add(Uri.fromFile(file)) else tracks.add(Uri.fromFile(file))
                } catch (e: Exception) {
                    error = e.message ?: e.javaClass.simpleName
                }
            }
            runOnUiThread {
                busy(false)
                error?.let { toast("Fichier illisible : $it") }
                maps.firstOrNull()?.let { openMap(it, page = -1, refitTrace = true) }
                tracks.firstOrNull()?.let { openGpx(it, savedMatrix = null) }
            }
        }
    }

    /** Copie le fichier reçu dans le stockage de l'app (l'accès accordé par l'autre app est temporaire). */
    private fun importFile(uri: Uri): Pair<File, Boolean> {
        val dir = File(filesDir, "imports").apply { mkdirs() }
        // On garde seulement les fichiers récents ou utilisés par la session.
        val keep = (setOfNotNull(mapUri?.toString(), gpxUri?.toString()) + sessions.referencedUris())
            .mapNotNull { Uri.parse(it).path }.toSet()
        dir.listFiles()?.sortedByDescending { it.lastModified() }?.drop(10)?.forEach {
            if (it.path !in keep) it.delete()
        }
        var name = displayName(uri) ?: uri.lastPathSegment ?: "fichier"
        name = name.replace(Regex("[^A-Za-z0-9._-]"), "_").takeLast(80)
        // Nom unique : plusieurs fichiers peuvent arriver dans la même milliseconde.
        val out = File(dir, "${System.currentTimeMillis()}-${importCounter.incrementAndGet()}_$name")
        contentResolver.openInputStream(uri)!!.use { input -> out.outputStream().use { input.copyTo(it) } }
        val head = ByteArray(16)
        val n = out.inputStream().use { it.read(head) }
        val type = contentResolver.getType(uri) ?: ""
        val isMap = type.startsWith("image/") || type == "application/pdf" || (n >= 4 && looksLikeMap(head))
        return out to isMap
    }

    private val importCounter = java.util.concurrent.atomic.AtomicInteger()

    private fun looksLikeMap(h: ByteArray): Boolean {
        fun b(i: Int) = h[i].toInt() and 0xFF
        return (b(0) == '%'.code && b(1) == 'P'.code && b(2) == 'D'.code && b(3) == 'F'.code) || // PDF
            (b(0) == 0xFF && b(1) == 0xD8) || // JPEG
            (b(0) == 0x89 && b(1) == 'P'.code && b(2) == 'N'.code && b(3) == 'G'.code) || // PNG
            (b(0) == 'G'.code && b(1) == 'I'.code && b(2) == 'F'.code) || // GIF
            (b(0) == 'R'.code && b(1) == 'I'.code && b(8) == 'W'.code && b(9) == 'E'.code) // WebP
    }

    // ---------- Chargement ----------

    private fun busy(b: Boolean) { progress.visibility = if (b) View.VISIBLE else View.GONE }

    /** [page] = -1 : demander la page si le PDF en a plusieurs. */
    private fun openMap(uri: Uri, page: Int, refitTrace: Boolean, savedMatrix: FloatArray? = null) {
        busy(true)
        io.execute {
            try {
                val pdf = MapLoader.isPdf(this, uri)
                if (pdf && page < 0) {
                    val count = MapLoader.pdfPageCount(this, uri)
                    if (count > 1) {
                        runOnUiThread { busy(false); choosePdfPage(uri, count) }
                        return@execute
                    }
                }
                val m = if (pdf) MapLoader.loadPdf(this, uri, page.coerceAtLeast(0))
                else MapLoader.loadImage(this, uri, imageDpi.toDouble())
                runOnUiThread {
                    busy(false)
                    val old = overlay.mapBitmap
                    val sameMap = uri == mapUri
                    mapUri = uri; mapIsPdf = m.isPdf; mapPage = m.page; mapPageCount = m.pageCount
                    mapName = pendingMapName ?: (if (sameMap) mapName else null) ?: displayName(uri)
                    pendingMapName = null
                    mapPxPerMm = m.pxPerMm
                    overlay.mapPxPerMm = m.pxPerMm
                    overlay.setMap(m.bitmap, refitTrace && savedMatrix == null)
                    if (savedMatrix != null) overlay.traceMatrix.setValues(savedMatrix)
                    else if (refitTrace && m.isPdf) applyKnownScale(quiet = true)
                    val pc = pendingControls
                    if (pc != null && pendingControlsMap == uri.toString()) overlay.setControls(pc)
                    else if (!sameMap) overlay.setControls(emptyList())
                    pendingControls = null
                    if (old != null && old !== m.bitmap) old.recycle()
                    refreshUi()
                    saveSession()
                    if (refitTrace && overlay.track != null && savedMatrix == null) {
                        toast("Trace placée au centre. Calez-la avec « Ajuster » ou « Caler ».")
                    }
                    loadDone()
                }
            } catch (e: Throwable) {
                runOnUiThread {
                    busy(false)
                    toast("Carte illisible : ${e.message ?: e.javaClass.simpleName}")
                    loadDone(ok = false)
                }
            }
        }
    }

    private fun choosePdfPage(uri: Uri, count: Int) {
        val items = Array(count) { "Page ${it + 1}" }
        AlertDialog.Builder(this)
            .setTitle("Quelle page du PDF ?")
            .setItems(items) { _, which -> openMap(uri, which, refitTrace = overlay.mapBitmap == null || uri != mapUri) }
            .show()
    }

    private fun openGpx(uri: Uri, savedMatrix: FloatArray?) {
        busy(true)
        io.execute {
            try {
                val t = contentResolver.openInputStream(uri)!!.use { TrackParser.parse(it) }
                runOnUiThread {
                    busy(false)
                    gpxUri = uri
                    trackName = pendingTrackName ?: displayName(uri)
                    pendingTrackName = null
                    hideSplits()
                    if (overlay.mode == OverlayView.Mode.CALIBRATE || overlay.mode == OverlayView.Mode.REPLAY) {
                        overlay.mode = OverlayView.Mode.MAP
                    }
                    overlay.setTrack(t, refit = savedMatrix == null)
                    profile.track = t
                    profile.cursorIndex = -1
                    // On choisit d'office ce que la trace contient (FC si disponible, sinon allure…).
                    if (savedMatrix == null) pickDefaultMetric(t)
                    if (savedMatrix != null) overlay.traceMatrix.setValues(savedMatrix)
                    else if (overlay.mapBitmap != null && mapIsPdf) applyKnownScale(quiet = true)
                    refreshUi()
                    saveSession()
                    loadDone()
                }
            } catch (e: Throwable) {
                runOnUiThread { busy(false); toast(e.message ?: "Trace illisible"); loadDone(ok = false) }
            }
        }
    }

    // ---------- Temps intermédiaires ----------

    private fun computePunches(): Pair<List<Punch>, List<Leg>>? {
        val t = overlay.track ?: return null
        val loc = overlay.controlsLocal() ?: return null
        if (overlay.controls.size < 2) return null
        val punches = Splits.punches(t, loc)
        return punches to Splits.legs(t, loc, punches)
    }

    private fun showSplits() {
        if (overlay.track == null) { toast("Ouvrez d'abord une trace."); return }
        val res = computePunches()
        if (res == null) {
            toast("Placez au moins le départ et l'arrivée avec le mode « Postes ».")
            return
        }
        val (punches, legs) = res
        val n = overlay.controls.size
        val dp = resources.displayMetrics.density
        splitsList.removeAllViews()
        val paces = legs.mapNotNull { it.paceSecPerKm }
        val slow = if (paces.size >= 3) paces.max() else null
        val fast = if (paces.size >= 3) paces.min() else null
        val t0 = punches.first().timeMs
        val rows = ArrayList<View>()
        fun rowBackground(leg: Leg, selected: Boolean) = GradientDrawable().apply {
            cornerRadius = 12 * dp
            setColor(
                when (leg.paceSecPerKm) {
                    null -> getColor(R.color.surface)
                    slow -> getColor(R.color.slow_bg)
                    fast -> getColor(R.color.fast_bg)
                    else -> getColor(R.color.surface)
                }
            )
            if (selected) setStroke((2 * dp).toInt(), getColor(R.color.highlight))
        }
        legs.forEachIndexed { li, leg ->
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                setPadding((10 * dp).toInt(), (10 * dp).toInt(), (12 * dp).toInt(), (10 * dp).toInt())
                background = rowBackground(leg, li == selectedLeg)
                layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                    .apply { topMargin = (4 * dp).toInt() }
            }
            val badge = TextView(this).apply {
                text = "${Splits.label(leg.from, n).take(3)}\n→ ${Splits.label(leg.to, n).take(3)}"
                textSize = 12f
                gravity = Gravity.CENTER
                setTextColor(getColor(R.color.course))
                setTypeface(typeface, Typeface.BOLD)
                background = GradientDrawable().apply { cornerRadius = 10 * dp; setColor(0x14A626FF) }
                layoutParams = LinearLayout.LayoutParams((58 * dp).toInt(), ViewGroup.LayoutParams.WRAP_CONTENT)
                setPadding(0, (6 * dp).toInt(), 0, (6 * dp).toInt())
            }
            val mid = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                    .apply { marginStart = (12 * dp).toInt() }
                addView(TextView(this@MainActivity).apply {
                    text = (leg.timeMs?.let { formatDuration(it) } ?: "—") + if (leg.sure) "" else "  ?"
                    textSize = 19f
                    fontFeatureSettings = "tnum"
                    setTextColor(getColor(R.color.ink))
                    setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL))
                })
                val cum = punches[leg.to].timeMs?.let { b -> t0?.let { formatDuration(b - it) } }
                addView(TextView(this@MainActivity).apply {
                    text = if (cum != null) "cumul $cum" else ""
                    textSize = 12f
                    fontFeatureSettings = "tnum"
                    setTextColor(getColor(R.color.muted))
                })
            }
            val right = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                gravity = Gravity.END
                addView(TextView(this@MainActivity).apply {
                    text = leg.paceSecPerKm?.let { formatPace(it) } ?: "—"
                    textSize = 15f
                    fontFeatureSettings = "tnum"
                    setTextColor(getColor(R.color.ink))
                })
                addView(TextView(this@MainActivity).apply {
                    text = String.format(Locale.FRANCE, "%d m · +%d %%", leg.runM.toInt(), leg.extraPercent.toInt())
                    textSize = 12f
                    fontFeatureSettings = "tnum"
                    setTextColor(getColor(R.color.muted))
                })
                val extra = listOfNotNull(
                    leg.avgHr?.let { "♥ ${it.toInt()}" },
                    if (this@MainActivity.overlay.track?.hasEle == true) "↗ ${leg.gainM.toInt()} m" else null,
                ).joinToString(" · ")
                if (extra.isNotEmpty()) addView(TextView(this@MainActivity).apply {
                    text = extra
                    textSize = 12f
                    fontFeatureSettings = "tnum"
                    setTextColor(getColor(R.color.muted))
                })
            }
            row.addView(badge); row.addView(mid); row.addView(right)
            row.isClickable = true
            row.setOnClickListener {
                selectedLeg = li
                rows.forEachIndexed { k, r -> r.background = rowBackground(legs[k], k == li) }
                overlay.highlight(leg.fromIdx, leg.toIdx)
            }
            rows.add(row)
            splitsList.addView(row)
        }
        val total = legs.mapNotNull { it.timeMs }.takeIf { it.size == legs.size }?.sum()
        val totalRun = legs.sumOf { it.runM }
        splitsSummary.text = buildString {
            append("Total ").append(total?.let { formatDuration(it) } ?: "—")
            append(String.format(Locale.FRANCE, " · %.2f km", totalRun / 1000))
            if (total != null && totalRun > 10) append(" · ").append(formatPace(total / 1000.0 / (totalRun / 1000.0)))
        }
        splitsList.addView(TextView(this).apply {
            textSize = 12f
            setTextColor(getColor(R.color.muted))
            setPadding((6 * dp).toInt(), (10 * dp).toInt(), (6 * dp).toInt(), 0)
            text = buildString {
                append("Touchez une section pour la voir en bleu sur la carte. ")
                append("Rouge = section la plus lente, vert = la plus rapide (allure). ")
                append("« +% » = distance en plus par rapport à la ligne droite.")
                if (legs.any { !it.sure }) {
                    append("\n? = passage à moins de ${Splits.DEFAULT_RADIUS_M.toInt()} m non trouvé : vérifiez le calage ou la position du poste.")
                }
                if (this@MainActivity.overlay.track?.hasTimes == false) append("\nCette trace n'a pas d'horaires : seules les distances sont connues.")
            }
        })
        // Le panneau prend au plus la moitié de l'écran : la carte reste visible au-dessus.
        val maxH = (root.height * 0.45f).toInt().coerceAtLeast((200 * dp).toInt())
        splitsList.measure(
            View.MeasureSpec.makeMeasureSpec(root.width.coerceAtLeast(1), View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED),
        )
        splitsScroll.layoutParams = splitsScroll.layoutParams.apply {
            height = if (splitsList.measuredHeight > maxH) maxH else ViewGroup.LayoutParams.WRAP_CONTENT
        }
        splitsSheet.visibility = View.VISIBLE
        splitsSheet.translationY = (60 * dp)
        splitsSheet.alpha = 0f
        splitsSheet.animate().translationY(0f).alpha(1f).setDuration(220).start()
        bottomPanel.visibility = View.GONE
    }

    private fun hideSplits() {
        if (splitsSheet.visibility != View.VISIBLE) return
        splitsSheet.visibility = View.GONE
        selectedLeg = -1
        overlay.clearHighlight()
        refreshUi()
    }

    val splitsVisible: Boolean get() = splitsSheet.visibility == View.VISIBLE

    // ---------- Replay ----------

    private fun startReplay() {
        val t = overlay.track
        if (t == null) { toast("Ouvrez d'abord une trace."); return }
        if (t.timedIdx.size < 2) { toast("Cette trace n'a pas d'horaires : impossible de la rejouer."); return }
        replayPunches = computePunches()?.first ?: emptyList()
        hideSplits()
        overlay.clearHighlight()
        overlay.mode = OverlayView.Mode.REPLAY
        if (overlay.replayTimeMs >= (t.endTimeMs ?: 0) || overlay.replayTimeMs < (t.startTimeMs ?: 0)) {
            overlay.setReplayTime(t.startTimeMs ?: 0)
        }
        onReplayTick(overlay.replayTimeMs, false)
    }

    override fun onReplayTick(timeMs: Long, playing: Boolean) {
        val t = overlay.track ?: return
        val a = t.startTimeMs ?: return
        val b = t.endTimeMs ?: return
        if (!userSeeking && b > a) replaySeek.progress = ((timeMs - a) * replaySeek.max / (b - a)).toInt()
        btnPlay.setImageResource(if (playing) R.drawable.ic_pause else R.drawable.ic_play)
        if (playing) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        btnSpeed.text = "×" + overlay.replaySpeed.toInt()
        if (overlay.mode != OverlayView.Mode.REPLAY) return
        // Temps de course : depuis le départ s'il est placé, sinon depuis le début de la trace.
        val start = replayPunches.firstOrNull()?.timeMs?.takeIf { replayPunches.first().sure } ?: a
        val sb = StringBuilder()
        sb.append(if (timeMs >= start) formatDuration(timeMs - start) else "-" + formatDuration(start - timeMs))
        sb.append(" / ").append(formatDuration((replayPunches.lastOrNull()?.timeMs ?: b) - start))
        val tmp = FloatArray(2)
        val idx = t.positionAt(timeMs, tmp)
        if (idx >= 0) profile.cursorIndex = idx
        val n = replayPunches.size
        for (k in 0 until n - 1) {
            val ta = replayPunches[k].timeMs ?: continue
            val tb = replayPunches[k + 1].timeMs ?: continue
            if (timeMs in ta until tb) {
                sb.append(" · ").append(Splits.label(k, n)).append(" → ").append(Splits.label(k + 1, n))
                sb.append(" (").append(formatDuration(timeMs - ta)).append(")")
                break
            }
        }
        if (idx >= 0) sb.append("\n").append(readout(t, idx, withDistance = false))
        hint.text = sb.toString()
    }

    /** Valeurs au point [i] : distance, allure, FC, altitude (selon ce que contient la trace). */
    private fun readout(t: Track, i: Int, withDistance: Boolean): String {
        val parts = ArrayList<String>()
        if (withDistance) parts.add(String.format(Locale.FRANCE, "%.2f km", t.cumDist[i] / 1000))
        if (withDistance) t.points[i].timeMs?.let { tm -> t.startTimeMs?.let { parts.add(formatDuration(tm - it)) } }
        val sp = t.speeds.getOrElse(i) { Float.NaN }
        if (!sp.isNaN() && sp > 0.3f) parts.add(formatPace(1000.0 / sp))
        val hr = t.hrs[i]
        if (!hr.isNaN()) parts.add("♥ ${hr.toInt()}")
        val e = t.eles[i]
        if (!e.isNaN()) parts.add("${e.toInt()} m")
        return parts.joinToString("  ·  ")
    }

    private fun onProfilePick(i: Int) {
        val t = overlay.track ?: return
        if (overlay.mode == OverlayView.Mode.REPLAY) {
            t.points[i].timeMs?.let { overlay.setReplayTime(it) }
        } else {
            overlay.probeIndex = i
            hint.text = readout(t, i, withDistance = true)
        }
    }

    private fun setMetric(m: ProfileView.Metric) {
        profile.metric = m
        // La couleur de la trace suit le graphique (sauf si l'utilisateur a choisi une couleur unie).
        if (overlay.colorMode != OverlayView.ColorMode.SOLID) {
            overlay.colorMode = when (m) {
                ProfileView.Metric.PACE -> OverlayView.ColorMode.SPEED
                ProfileView.Metric.ELEVATION -> OverlayView.ColorMode.ELEVATION
                ProfileView.Metric.HEART_RATE -> OverlayView.ColorMode.HEART_RATE
            }
        }
        refreshUi()
    }

    private fun pickDefaultMetric(t: Track) {
        val current = profile.metric
        val ok = when (current) {
            ProfileView.Metric.PACE -> t.hasTimes
            ProfileView.Metric.ELEVATION -> t.hasEle
            ProfileView.Metric.HEART_RATE -> t.hasHr
        }
        if (!ok) profile.metric = when {
            t.hasTimes -> ProfileView.Metric.PACE
            t.hasHr -> ProfileView.Metric.HEART_RATE
            else -> ProfileView.Metric.ELEVATION
        }
    }

    private fun styleChip(c: TextView, selected: Boolean, enabled: Boolean) {
        c.isEnabled = enabled
        c.alpha = if (enabled) 1f else 0.4f
        c.setTextColor(getColor(if (selected) R.color.accent else R.color.ink))
        c.background = if (selected) GradientDrawable().apply {
            cornerRadius = 12 * resources.displayMetrics.density; setColor(getColor(R.color.accent_soft))
        } else getDrawable(R.drawable.bg_chip)
    }

    private fun updateLegend() {
        val t = overlay.track ?: return
        val cm = overlay.effectiveColorMode
        val dp = resources.displayMetrics.density
        legendBar.background = GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT, OverlayView.rampStops(cm)).apply {
            cornerRadius = 4 * dp
        }
        val lo = overlay.colorLo; val hi = overlay.colorHi
        legendLabel.text = when (cm) {
            OverlayView.ColorMode.SPEED ->
                "Allure : " + formatPace(1000.0 / lo.coerceAtLeast(0.3f)).removeSuffix("/km") + " → " + formatPace(1000.0 / hi.coerceAtLeast(0.3f))
            OverlayView.ColorMode.ELEVATION -> String.format(Locale.FRANCE, "Altitude : %d → %d m", lo.toInt(), hi.toInt())
            OverlayView.ColorMode.HEART_RATE -> String.format(Locale.FRANCE, "FC : %d → %d bpm", lo.toInt(), hi.toInt())
            OverlayView.ColorMode.SOLID -> "Couleur unie · toucher pour changer"
        }
        if (overlay.colorMode != OverlayView.ColorMode.SOLID && cm == OverlayView.ColorMode.SOLID) {
            legendLabel.text = "Donnée absente de la trace · couleur unie"
        }
        if (!t.hasTimes && !t.hasEle && !t.hasHr) legendLabel.text = "Couleur unie"
    }

    private fun showColorDialog() {
        val t = overlay.track ?: return
        val modes = listOf(
            OverlayView.ColorMode.SPEED to ("Allure (vitesse)" to t.hasTimes),
            OverlayView.ColorMode.HEART_RATE to ("Fréquence cardiaque" to t.hasHr),
            OverlayView.ColorMode.ELEVATION to ("Altitude" to t.hasEle),
            OverlayView.ColorMode.SOLID to ("Couleur unie" to true),
        )
        val labels = modes.map { (_, v) -> if (v.second) v.first else v.first + " (absente de la trace)" }.toTypedArray()
        val cur = modes.indexOfFirst { it.first == overlay.colorMode }
        AlertDialog.Builder(this)
            .setTitle("Couleur de la trace")
            .setSingleChoiceItems(labels, cur) { d, which ->
                val (m, info) = modes[which]
                if (!info.second) { toast("Cette trace ne contient pas cette donnée."); return@setSingleChoiceItems }
                overlay.colorMode = m
                when (m) {
                    OverlayView.ColorMode.SPEED -> profile.metric = ProfileView.Metric.PACE
                    OverlayView.ColorMode.HEART_RATE -> profile.metric = ProfileView.Metric.HEART_RATE
                    OverlayView.ColorMode.ELEVATION -> profile.metric = ProfileView.Metric.ELEVATION
                    OverlayView.ColorMode.SOLID -> {}
                }
                refreshUi()
                d.dismiss()
            }
            .show()
    }

    // ---------- Échelle ----------

    private fun applyKnownScale(quiet: Boolean) {
        val pxPerMm = mapPxPerMm ?: return
        if (overlay.track == null) return
        overlay.setTraceScale(pxPerMm * 1000.0 / scaleDenominator)
        if (!quiet) toast("Trace mise à l'échelle 1:$scaleDenominator")
    }

    private fun showScaleDialog() {
        val pad = (16 * resources.displayMetrics.density).toInt()
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(pad, pad / 2, pad, 0) }
        val scaleEdit = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_NUMBER
            setText(scaleDenominator.toString())
        }
        box.addView(TextView(this).apply { text = "Échelle 1 :" }); box.addView(scaleEdit)
        var dpiEdit: EditText? = null
        if (!mapIsPdf) {
            box.addView(TextView(this).apply { text = "Résolution de l'image (dpi) :" })
            dpiEdit = EditText(this).apply {
                inputType = InputType.TYPE_CLASS_NUMBER
                setText(imageDpi.toString())
            }
            box.addView(dpiEdit)
            box.addView(TextView(this).apply {
                text = "Pour une image, l'échelle n'est juste que si le dpi est connu (scan ou export). Sinon, utilisez « Caler »."
                textSize = 12f
            })
        }
        AlertDialog.Builder(this)
            .setTitle("Échelle de la carte")
            .setView(box)
            .setPositiveButton("Appliquer") { _, _ ->
                val den = scaleEdit.text.toString().toIntOrNull()
                val dpi = dpiEdit?.text?.toString()?.toIntOrNull()
                if (den == null || den < 500 || den > 200_000) { toast("Échelle invalide"); return@setPositiveButton }
                scaleDenominator = den
                if (dpi != null && dpi in 30..4800 && !mapIsPdf) {
                    mapPxPerMm?.let { old -> mapPxPerMm = old / imageDpi * dpi }
                    overlay.mapPxPerMm = mapPxPerMm
                    imageDpi = dpi
                }
                if (overlay.mapBitmap == null || overlay.track == null) toast("Ouvrez une carte et une trace.")
                else applyKnownScale(quiet = false)
                refreshUi()
            }
            .setNegativeButton("Annuler", null)
            .show()
    }

    private fun showWidthDialog() {
        val values = floatArrayOf(2f, 3f, 4f, 6f, 8f)
        val labels = arrayOf("Fine", "Moyenne", "Normale", "Épaisse", "Très épaisse")
        val cur = values.indexOfFirst { it == overlay.traceWidthDp }
        AlertDialog.Builder(this)
            .setTitle("Épaisseur de la trace")
            .setSingleChoiceItems(labels, cur) { d, which ->
                overlay.traceWidthDp = values[which]; d.dismiss()
            }
            .show()
    }

    // ---------- Export ----------

    private fun exportTo(uri: Uri) {
        val bmp = overlay.renderComposite() ?: return
        busy(true)
        io.execute {
            try {
                contentResolver.openOutputStream(uri)!!.use { bmp.compress(Bitmap.CompressFormat.JPEG, 92, it) }
                runOnUiThread { busy(false); toast("Image enregistrée") }
            } catch (e: Throwable) {
                runOnUiThread { busy(false); toast("Échec de l'export : ${e.message}") }
            } finally {
                bmp.recycle()
            }
        }
    }

    // ---------- Sauvegarde de la session ----------

    private fun saveSession() {
        saveCurrentSession()
        val v = FloatArray(9).also { overlay.traceMatrix.getValues(it) }
        prefs.edit()
            .putString("mapUri", mapUri?.toString())
            .putInt("mapPage", mapPage)
            .putString("gpxUri", gpxUri?.toString())
            .putString("mapName", mapName)
            .putString("trackName", trackName)
            .putString("traceMatrix", v.joinToString(","))
            .putString("controls", overlay.controls.joinToString(";") { "${it[0]},${it[1]}" })
            .putString("controlsMap", mapUri?.toString())
            .putString("colorMode", overlay.colorMode.name)
            .putString("chartMetric", profile.metric.name)
            .putBoolean("showProfile", showProfile)
            .putBoolean("lockScale", overlay.lockTraceScale)
            .putFloat("traceWidth", overlay.traceWidthDp)
            .putFloat("replaySpeed", overlay.replaySpeed)
            .putInt("scaleDen", scaleDenominator)
            .putInt("dpi", imageDpi)
            .apply()
    }

    // ---------- Sessions ----------

    /** Enregistre la session en cours (carte, trace, calage, postes) avec une miniature. */
    private fun saveCurrentSession() {
        if (restoringLoads > 0) return
        val map = mapUri?.toString()
        val track = gpxUri?.toString()
        if (map == null && track == null) return
        val cur = currentSessionId?.let { sessions.get(it) }
        // Même session tant qu'on complète ou ajuste ; nouvelle si on change de carte ou de trace.
        val same = cur != null && (cur.mapUri == null || cur.mapUri == map) && (cur.trackUri == null || cur.trackUri == track)
        val id = if (same) cur!!.id else sessions.findByFiles(map, track)?.id ?: SessionStore.newId()
        val name = if (same) cur!!.name else sessions.get(id)?.name
        val t = overlay.track
        val m = FloatArray(9).also { overlay.traceMatrix.getValues(it) }
        sessions.upsert(
            Session(
                id = id, name = name, savedAt = System.currentTimeMillis(),
                mapUri = map, mapPage = mapPage, mapName = mapName,
                trackUri = track, trackName = trackName,
                matrix = if (t != null) m else null,
                controls = overlay.controls.map { it.copyOf() },
                scaleDen = scaleDenominator, dpi = imageDpi,
                distanceM = t?.distanceM, durationMs = t?.durationMs,
            )
        )
        currentSessionId = id
        overlay.renderThumbnail(480)?.let { thumb ->
            val f = sessions.thumbFile(id)
            io.execute {
                // Écriture dans un fichier temporaire puis renommage : jamais de miniature à moitié écrite.
                try {
                    val tmp = File(f.path + ".tmp")
                    tmp.outputStream().use { thumb.compress(Bitmap.CompressFormat.PNG, 90, it) }
                    tmp.renameTo(f)
                } catch (_: Exception) { }
                thumb.recycle()
                runOnUiThread { if (home.visibility == View.VISIBLE) buildHome() }
            }
        }
    }

    /** Rouvre une session enregistrée. */
    private fun restore(s: Session) {
        overlay.mode = OverlayView.Mode.MAP
        hideSplits()
        currentSessionId = s.id
        scaleDenominator = s.scaleDen
        imageDpi = s.dpi
        pendingControls = s.controls
        pendingControlsMap = s.mapUri
        pendingMapName = s.mapName
        pendingTrackName = s.trackName
        restoringLoads = listOfNotNull(s.trackUri, s.mapUri).size
        // Les chargements passent par le même fil, dans l'ordre : trace puis carte.
        s.trackUri?.let { openGpx(Uri.parse(it), s.matrix) }
        s.mapUri?.let { openMap(Uri.parse(it), s.mapPage, refitTrace = false, savedMatrix = s.matrix) }
    }

    /** Retour à l'accueil : la session est enregistrée puis fermée. */
    private fun goHome() {
        saveCurrentSession()
        overlay.mode = OverlayView.Mode.MAP
        hideSplits()
        overlay.setControls(emptyList())
        overlay.setTrack(null, refit = false)
        overlay.setMap(null, refitTrace = false)
        profile.track = null
        mapUri = null; gpxUri = null; mapName = null; trackName = null
        mapIsPdf = false; mapPxPerMm = null; overlay.mapPxPerMm = null
        currentSessionId = null
        buildHome()
        refreshUi()
    }

    /** Reprend la session de la version précédente (avant l'arrivée des sessions). */
    private fun migrateLegacySession() {
        if (sessions.list().isNotEmpty()) return
        val map = prefs.getString("mapUri", null)
        val track = prefs.getString("gpxUri", null)
        if (map == null && track == null) return
        val matrix = prefs.getString("traceMatrix", null)?.split(",")?.mapNotNull { it.toFloatOrNull() }
            ?.takeIf { it.size == 9 }?.toFloatArray()
        val controls = prefs.getString("controls", null)?.split(";")?.mapNotNull { str ->
            val xy = str.split(",").mapNotNull { it.toFloatOrNull() }
            if (xy.size == 2) floatArrayOf(xy[0], xy[1]) else null
        } ?: emptyList()
        sessions.upsert(
            Session(
                SessionStore.newId(), null, System.currentTimeMillis(), map, prefs.getInt("mapPage", 0),
                prefs.getString("mapName", null), track, prefs.getString("trackName", null), matrix,
                if (prefs.getString("controlsMap", null) == map) controls else emptyList(),
                scaleDenominator, imageDpi, null, null,
            )
        )
        prefs.edit().remove("mapUri").remove("gpxUri").apply()
    }

    private fun buildHome() {
        val list = sessions.list()
        val last = list.firstOrNull()
        val dp = resources.displayMetrics.density
        // Avec des sessions, l'accueil se resserre pour que « Reprendre » soit visible sans défiler.
        val compact = last != null
        findViewById<View>(R.id.welcomeText).visibility = if (compact) View.GONE else View.VISIBLE
        findViewById<View>(R.id.welcomeTip).visibility = if (compact) View.GONE else View.VISIBLE
        findViewById<View>(R.id.welcomeLogo).visibility = if (compact) View.GONE else View.VISIBLE
        (home as ScrollView).scrollTo(0, 0)
        findViewById<View>(R.id.resumeHeader).visibility = if (last != null) View.VISIBLE else View.GONE
        val lastCard = findViewById<View>(R.id.lastSession)
        lastCard.visibility = if (last != null) View.VISIBLE else View.GONE
        if (last != null) {
            val thumb = findViewById<ImageView>(R.id.lastThumb)
            val bmp = sessions.thumbFile(last.id).takeIf { it.exists() }?.let { BitmapFactory.decodeFile(it.path) }
            thumb.visibility = if (bmp != null) View.VISIBLE else View.GONE
            thumb.setImageBitmap(bmp)
            thumb.clipToOutline = true
            thumb.outlineProvider = object : android.view.ViewOutlineProvider() {
                override fun getOutline(v: View, o: android.graphics.Outline) {
                    o.setRoundRect(0, 0, v.width, v.height + (18 * dp).toInt(), 18 * dp)
                }
            }
            findViewById<TextView>(R.id.lastTitle).text = last.title
            findViewById<TextView>(R.id.lastSubtitle).text = sessionDetails(last)
            lastCard.setOnClickListener { restore(last) }
            findViewById<View>(R.id.btnResume).setOnClickListener { restore(last) }
            findViewById<View>(R.id.btnLastMore).setOnClickListener { showSessionMenu(it, last) }
        }
        val others = list.drop(1).take(15)
        findViewById<View>(R.id.previousHeader).visibility = if (others.isNotEmpty()) View.VISIBLE else View.GONE
        val box = findViewById<LinearLayout>(R.id.sessionList)
        box.visibility = if (others.isNotEmpty()) View.VISIBLE else View.GONE
        box.removeAllViews()
        others.forEachIndexed { i, s ->
            if (i > 0) box.addView(View(this).apply {
                setBackgroundColor(getColor(R.color.line))
                layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 1).apply {
                    marginStart = (84 * dp).toInt()
                }
            })
            box.addView(sessionRow(s))
        }
    }

    private fun sessionRow(s: Session): View {
        val dp = resources.displayMetrics.density
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding((12 * dp).toInt(), (8 * dp).toInt(), (4 * dp).toInt(), (8 * dp).toInt())
            background = getDrawable(android.R.drawable.list_selector_background)
            isClickable = true
            setOnClickListener { restore(s) }
            setOnLongClickListener { showSessionMenu(it, s); true }
        }
        val thumb = ImageView(this).apply {
            layoutParams = LinearLayout.LayoutParams((60 * dp).toInt(), (60 * dp).toInt())
            scaleType = ImageView.ScaleType.CENTER_CROP
            background = GradientDrawable().apply { cornerRadius = 10 * dp; setColor(getColor(R.color.surface2)) }
            clipToOutline = true
            sessions.thumbFile(s.id).takeIf { it.exists() }?.let { f ->
                BitmapFactory.decodeFile(f.path, BitmapFactory.Options().apply { inSampleSize = 4 })?.let { setImageBitmap(it) }
            }
        }
        val texts = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
                marginStart = (12 * dp).toInt()
            }
            addView(TextView(this@MainActivity).apply {
                text = s.title
                textSize = 15f
                isSingleLine = true
                ellipsize = android.text.TextUtils.TruncateAt.MIDDLE
                setTextColor(getColor(R.color.ink))
                setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL))
            })
            addView(TextView(this@MainActivity).apply {
                text = sessionDetails(s)
                textSize = 12.5f
                fontFeatureSettings = "tnum"
                setTextColor(getColor(R.color.muted))
            })
        }
        val more = ImageButton(this).apply {
            layoutParams = LinearLayout.LayoutParams((44 * dp).toInt(), (44 * dp).toInt())
            setImageResource(R.drawable.ic_more)
            imageTintList = ColorStateList.valueOf(getColor(R.color.muted))
            background = getDrawable(android.R.drawable.list_selector_background)
            contentDescription = getString(R.string.more)
            setOnClickListener { showSessionMenu(it, s) }
        }
        row.addView(thumb); row.addView(texts); row.addView(more)
        return row
    }

    /** « Aujourd'hui 14:02 · 4,62 km · 22:00 » */
    private fun sessionDetails(s: Session): String {
        val zone = ZoneId.systemDefault()
        val dt = Instant.ofEpochMilli(s.savedAt).atZone(zone)
        val today = LocalDate.now(zone)
        val day = when (dt.toLocalDate()) {
            today -> "Aujourd'hui"
            today.minusDays(1) -> "Hier"
            else -> dt.format(DateTimeFormatter.ofPattern("d MMM yyyy", Locale.FRANCE))
        }
        val parts = mutableListOf(day + " " + dt.format(DateTimeFormatter.ofPattern("HH:mm")))
        s.distanceM?.let { parts.add(String.format(Locale.FRANCE, "%.2f km", it / 1000)) }
        s.durationMs?.let { parts.add(formatDuration(it)) }
        if (s.controls.size >= 2) parts.add("${s.controls.size - 2} postes")
        return parts.joinToString(" · ")
    }

    private fun showSessionMenu(anchor: View, s: Session) {
        val popup = PopupMenu(this, anchor)
        popup.menu.add(0, 1, 0, "Ouvrir")
        popup.menu.add(0, 2, 1, "Renommer…")
        popup.menu.add(0, 3, 2, "Supprimer")
        popup.setOnMenuItemClickListener {
            when (it.itemId) {
                1 -> restore(s)
                2 -> {
                    val pad = (20 * resources.displayMetrics.density).toInt()
                    val edit = EditText(this).apply { setText(s.title); setSelection(text.length) }
                    AlertDialog.Builder(this)
                        .setTitle("Nom de la session")
                        .setView(LinearLayout(this).apply { setPadding(pad, pad / 2, pad, 0); addView(edit, LinearLayout.LayoutParams(-1, -2)) })
                        .setPositiveButton("OK") { _, _ -> sessions.rename(s.id, edit.text.toString()); buildHome() }
                        .setNegativeButton("Annuler", null)
                        .show()
                }
                3 -> AlertDialog.Builder(this)
                    .setMessage("Supprimer la session « ${s.title} » ?\nLes fichiers de carte et de trace ne sont pas effacés.")
                    .setPositiveButton("Supprimer") { _, _ -> sessions.delete(s.id); buildHome() }
                    .setNegativeButton("Annuler", null)
                    .show()
            }
            true
        }
        popup.show()
    }

    // ---------- Interface ----------

    override fun onStateChanged() = refreshUi()

    override fun onMessage(msg: String) = toast(msg)

    private fun refreshUi() {
        val mode = overlay.mode
        val t = overlay.track
        val nothing = t == null && overlay.mapBitmap == null
        home.visibility = if (nothing) View.VISIBLE else View.GONE
        val sheet = splitsVisible
        bottomPanel.visibility = if (nothing || sheet) View.GONE else View.VISIBLE
        btnFit.visibility = if (nothing) View.GONE else View.VISIBLE
        // Sur l'accueil, les gros boutons suffisent : on allège la barre du haut.
        findViewById<View>(R.id.btnOpenMap).visibility = if (nothing) View.GONE else View.VISIBLE
        findViewById<View>(R.id.btnOpenTrack).visibility = if (nothing) View.GONE else View.VISIBLE
        subtitle.text = listOfNotNull(mapName, trackName).joinToString("  ·  ").ifEmpty { "Trace GPS sur carte de CO" }

        modeBar.visibility = if (mode == OverlayView.Mode.MAP || mode == OverlayView.Mode.TRACE) View.VISIBLE else View.GONE
        calibBar.visibility = if (mode == OverlayView.Mode.CALIBRATE) View.VISIBLE else View.GONE
        controlsBar.visibility = if (mode == OverlayView.Mode.CONTROLS) View.VISIBLE else View.GONE
        replayBar.visibility = if (mode == OverlayView.Mode.REPLAY) View.VISIBLE else View.GONE
        styleButton(btnMap, mode == OverlayView.Mode.MAP)
        styleButton(btnTrace, mode == OverlayView.Mode.TRACE)
        styleButton(btnCalib, false)
        styleButton(btnControls, false)
        styleButton(btnReplay, false)

        statsRow.visibility = if (t == null) View.GONE else View.VISIBLE
        if (t != null) {
            statDist.text = String.format(Locale.FRANCE, "%.2f km", t.distanceM / 1000)
            statTime.text = t.durationMs?.let { formatDuration(it) } ?: "—"
            statPace.text = t.paceSecPerKm?.let { formatPace(it) } ?: "—"
        }
        if (t != null) {
            statGainBox.visibility = if (t.hasEle) View.VISIBLE else View.GONE
            statGain.text = String.format(Locale.FRANCE, "%d m", t.gainM.toInt())
            statHrBox.visibility = if (t.hasHr) View.VISIBLE else View.GONE
            statHr.text = t.avgHr?.let { String.format(Locale.FRANCE, "%d", it.toInt()) } ?: "—"
            findViewById<TextView>(R.id.statHrLabel).text = "FC moy." + (t.maxHr?.let { " · max $it" } ?: "")
        }
        // En replay, les valeurs en direct remplacent les statistiques : plus de place pour la carte.
        val replayMode = mode == OverlayView.Mode.REPLAY
        findViewById<View>(R.id.statsScroll).visibility = if (t == null || replayMode) View.GONE else View.VISIBLE
        findViewById<View>(R.id.legendRow).visibility = if (t == null || replayMode) View.GONE else View.VISIBLE
        updateLegend()
        val profileShown = t != null && (showProfile || mode == OverlayView.Mode.REPLAY)
        profileBox.visibility = if (profileShown) View.VISIBLE else View.GONE
        btnProfile.visibility = if (mode == OverlayView.Mode.REPLAY) View.GONE else View.VISIBLE
        btnProfile.background = if (showProfile) GradientDrawable().apply {
            cornerRadius = 12 * resources.displayMetrics.density; setColor(getColor(R.color.accent_soft))
        } else getDrawable(R.drawable.bg_chip)
        if (!profileShown) overlay.probeIndex = -1
        if (profileShown) {
            styleChip(chipPace, profile.metric == ProfileView.Metric.PACE, t?.hasTimes == true)
            styleChip(chipEle, profile.metric == ProfileView.Metric.ELEVATION, t?.hasEle == true)
            styleChip(chipHr, profile.metric == ProfileView.Metric.HEART_RATE, t?.hasHr == true)
            profile.punchIndices = computePunches()?.first?.map { it.pointIndex }?.toIntArray() ?: IntArray(0)
        }

        val replay = mode == OverlayView.Mode.REPLAY
        hint.textSize = if (replay) 15f else 13f
        hint.setTextColor(getColor(if (replay) R.color.ink else R.color.muted))
        hint.fontFeatureSettings = if (replay) "tnum" else null
        hint.text = when (mode) {
            OverlayView.Mode.MAP -> when {
                overlay.mapBitmap == null -> "Ouvrez la carte de la course avec « Carte »."
                t == null -> "Ouvrez votre trace avec « Trace »."
                else -> "Glisser pour déplacer · pincer ou double-tap pour zoomer"
            }
            OverlayView.Mode.TRACE -> "Glissez la trace · deux doigts pour la tourner" +
                if (overlay.lockTraceScale) " (échelle verrouillée)" else " ou l'agrandir"
            OverlayView.Mode.CALIBRATE -> {
                val n = overlay.calibrationCount
                val step = if (overlay.waitingForMapPoint) "② Touchez le même endroit sur la carte"
                else "① Touchez un point reconnaissable de la trace"
                "$step\n$n point(s) calé(s)" + if (n < 2) " — 2 minimum" else " — la trace est calée"
            }
            OverlayView.Mode.CONTROLS -> {
                val n = overlay.controls.size
                val next = if (n == 0) "le départ ▲" else "le poste $n (ou l'arrivée ◎)"
                "Touchez la carte pour placer $next\nGlisser : déplacer · appui long : supprimer"
            }
            OverlayView.Mode.REPLAY -> hint.text
        }
        if (replay) onReplayTick(overlay.replayTimeMs, overlay.replayPlaying)
        root.post { updateInsets() }
    }

    /** Signale à la carte la place prise par les panneaux, et place le bouton ⤢ au-dessus du panneau du bas. */
    private fun updateInsets() {
        if (root.height == 0) return
        val dp = resources.displayMetrics.density
        val bottomView = when {
            splitsVisible -> splitsSheet
            bottomPanel.visibility == View.VISIBLE -> bottomPanel
            else -> null
        }
        val bottomTop = bottomView?.let { it.top + it.translationY } ?: root.height.toFloat()
        overlay.setInsets(topBar.bottom.toFloat(), root.height - bottomTop)
        btnFit.translationY = -(root.height - bottomTop) - 4 * dp
    }

    private fun showSnack(msg: String, action: String?, onAction: (() -> Unit)?) {
        handler.removeCallbacks(hideSnack)
        snackText.text = msg
        snackAction.visibility = if (action != null) View.VISIBLE else View.GONE
        snackAction.text = action
        snackAction.setOnClickListener { onAction?.invoke(); snackbar.visibility = View.GONE }
        snackbar.visibility = View.VISIBLE
        snackbar.alpha = 0f
        snackbar.animate().alpha(1f).setDuration(150).start()
        handler.postDelayed(hideSnack, 4500)
    }

    override fun onControlRemoved(index: Int, position: FloatArray) {
        showSnack("Poste supprimé", "Annuler") { overlay.restoreControl(index, position) }
    }

    @Deprecated("Gestion simple du retour")
    override fun onBackPressed() {
        when {
            splitsVisible -> hideSplits()
            snackbar.visibility == View.VISIBLE -> snackbar.visibility = View.GONE
            overlay.mode != OverlayView.Mode.MAP -> overlay.mode = OverlayView.Mode.MAP
            overlay.mapBitmap != null || overlay.track != null -> goHome()
            else -> @Suppress("DEPRECATION") super.onBackPressed()
        }
    }

    /** Mode sélectionné : pastille orange pâle, icône et texte orange. */
    private fun styleButton(b: Button, selected: Boolean) {
        val radius = 14 * resources.displayMetrics.density
        val content = GradientDrawable().apply {
            setColor(if (selected) getColor(R.color.accent_soft) else 0x00000000)
            cornerRadius = radius
        }
        val mask = GradientDrawable().apply { setColor(0xFFFFFFFF.toInt()); cornerRadius = radius }
        b.background = RippleDrawable(ColorStateList.valueOf(0x22000000), content, mask)
        val c = getColor(if (selected) R.color.accent else R.color.ink)
        b.setTextColor(c)
        b.compoundDrawableTintList = ColorStateList.valueOf(c)
    }

    private fun formatDuration(ms: Long): String {
        val s = ms / 1000
        return if (s >= 3600) String.format(Locale.FRANCE, "%d:%02d:%02d", s / 3600, s / 60 % 60, s % 60)
        else String.format(Locale.FRANCE, "%d:%02d", s / 60, s % 60)
    }

    private fun formatPace(secPerKm: Double): String {
        val s = secPerKm.toInt()
        return String.format(Locale.FRANCE, "%d'%02d\"/km", s / 60, s % 60)
    }

    private fun toast(msg: String) = showSnack(msg, null, null)

    companion object {
        private const val REQ_MAP = 1
        private const val REQ_GPX = 2
        private const val REQ_EXPORT = 3
        private const val REQ_GARMIN = 4
    }
}
