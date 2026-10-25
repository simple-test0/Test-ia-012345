package com.orienteering.gpxoverlay

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Bitmap
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import android.text.InputType
import android.view.Gravity
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.TableLayout
import android.widget.TableRow
import android.widget.TextView
import android.widget.Toast
import java.io.File
import java.util.Locale
import java.util.concurrent.Executors

class MainActivity : Activity(), OverlayView.Listener {

    private lateinit var overlay: OverlayView
    private lateinit var stats: TextView
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
    private lateinit var btnPlay: Button
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
        stats = findViewById(R.id.stats)
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
            AlertDialog.Builder(this)
                .setMessage("Effacer tous les postes ?")
                .setPositiveButton("Effacer") { _, _ -> overlay.clearControls() }
                .setNegativeButton("Annuler", null)
                .show()
        }
        findViewById<Button>(R.id.btnSplits).setOnClickListener { showSplits() }
        findViewById<Button>(R.id.btnCtrlDone).setOnClickListener { overlay.mode = OverlayView.Mode.MAP }
        findViewById<Button>(R.id.btnReplayDone).setOnClickListener { overlay.mode = OverlayView.Mode.MAP }
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

        overlay.speedColors = prefs.getBoolean("speedColors", true)
        overlay.lockTraceScale = prefs.getBoolean("lockScale", false)
        overlay.traceWidthDp = prefs.getFloat("traceWidth", 4f)
        overlay.replaySpeed = prefs.getFloat("replaySpeed", 10f).takeIf { v -> speeds.any { it == v } } ?: 10f
        scaleDenominator = prefs.getInt("scaleDen", 10000)
        imageDpi = prefs.getInt("dpi", 300)

        restoreSession()
        handleIncoming(intent)
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

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.main, menu)
        return true
    }

    override fun onPrepareOptionsMenu(menu: Menu): Boolean {
        menu.findItem(R.id.speed_colors).isChecked = overlay.speedColors
        menu.findItem(R.id.lock_scale).isChecked = overlay.lockTraceScale
        menu.findItem(R.id.pdf_page).isVisible = mapIsPdf && mapPageCount > 1
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        when (item.itemId) {
            R.id.open_map -> pick(REQ_MAP, arrayOf("image/*", "application/pdf"))
            R.id.open_track -> pick(REQ_GPX, null)
            R.id.splits -> showSplits()
            R.id.map_scale -> showScaleDialog()
            R.id.pdf_page -> mapUri?.let { choosePdfPage(it, mapPageCount) }
            R.id.speed_colors -> {
                overlay.speedColors = !overlay.speedColors
                if (overlay.speedColors && overlay.track?.hasTimes == false) toast("Cette trace n'a pas d'horaires.")
                refreshUi()
            }
            R.id.lock_scale -> overlay.lockTraceScale = !overlay.lockTraceScale
            R.id.trace_width -> showWidthDialog()
            R.id.reset_trace -> overlay.fitTraceToMap()
            R.id.fit_view -> overlay.fitView()
            R.id.export -> {
                if (overlay.mapBitmap == null) toast("Ouvrez d'abord une carte.")
                else startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    type = "image/jpeg"
                    putExtra(Intent.EXTRA_TITLE, "carte_trace.jpg")
                }, REQ_EXPORT)
            }
            else -> return super.onOptionsItemSelected(item)
        }
        return true
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
            REQ_MAP -> { keepPermission(uri); openMap(uri, page = -1, refitTrace = true) }
            REQ_GPX -> { keepPermission(uri); openGpx(uri, savedMatrix = null) }
            REQ_EXPORT -> exportTo(uri)
        }
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
        val keep = setOfNotNull(mapUri?.path, gpxUri?.path)
        dir.listFiles()?.sortedByDescending { it.lastModified() }?.drop(6)?.forEach {
            if (it.path !in keep) it.delete()
        }
        var name = "fichier"
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst() && !c.isNull(0)) name = c.getString(0)
        }
        name = name.replace(Regex("[^A-Za-z0-9._-]"), "_").takeLast(80)
        val out = File(dir, "${System.currentTimeMillis()}_$name")
        contentResolver.openInputStream(uri)!!.use { input -> out.outputStream().use { input.copyTo(it) } }
        val head = ByteArray(16)
        val n = out.inputStream().use { it.read(head) }
        val type = contentResolver.getType(uri) ?: ""
        val isMap = type.startsWith("image/") || type == "application/pdf" || (n >= 4 && looksLikeMap(head))
        return out to isMap
    }

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
                    invalidateOptionsMenu()
                    refreshUi()
                    saveSession()
                    if (refitTrace && overlay.track != null && savedMatrix == null) {
                        toast("Trace placée au centre. Calez-la avec « Ajuster » ou « Caler ».")
                    }
                }
            } catch (e: Throwable) {
                runOnUiThread { busy(false); toast("Carte illisible : ${e.message ?: e.javaClass.simpleName}") }
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
                    if (overlay.mode == OverlayView.Mode.CALIBRATE || overlay.mode == OverlayView.Mode.REPLAY) {
                        overlay.mode = OverlayView.Mode.MAP
                    }
                    overlay.setTrack(t, refit = savedMatrix == null)
                    if (savedMatrix != null) overlay.traceMatrix.setValues(savedMatrix)
                    else if (overlay.mapBitmap != null && mapIsPdf) applyKnownScale(quiet = true)
                    refreshUi()
                    saveSession()
                }
            } catch (e: Throwable) {
                runOnUiThread { busy(false); toast(e.message ?: "Trace illisible") }
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
        val pad = (6 * resources.displayMetrics.density).toInt()
        val table = TableLayout(this).apply {
            setPadding(pad * 2, pad, pad * 2, pad)
            isStretchAllColumns = true
        }
        fun cell(text: String, bold: Boolean = false, align: Int = Gravity.END) = TextView(this).apply {
            this.text = text
            textSize = 14f
            gravity = align
            setPadding(pad / 2, pad, pad / 2, pad)
            setTextColor(0xFF222222.toInt())
            if (bold) setTypeface(typeface, Typeface.BOLD)
        }
        table.addView(TableRow(this).apply {
            addView(cell("Section", true, Gravity.START))
            addView(cell("Temps", true)); addView(cell("Cumul", true))
            addView(cell("Allure", true)); addView(cell("Dist.", true))
        })
        val paces = legs.mapNotNull { it.paceSecPerKm }
        val slow = if (paces.size >= 3) paces.max() else null
        val fast = if (paces.size >= 3) paces.min() else null
        val t0 = punches.first().timeMs
        var dialog: AlertDialog? = null
        for (leg in legs) {
            val pace = leg.paceSecPerKm
            val name = "${Splits.label(leg.from, n).take(3)}→${Splits.label(leg.to, n).take(3)}" + if (leg.sure) "" else " ?"
            val cum = punches[leg.to].timeMs?.let { b -> t0?.let { formatDuration(b - it) } } ?: "—"
            val row = TableRow(this).apply {
                addView(cell(name, align = Gravity.START))
                addView(cell(leg.timeMs?.let { formatDuration(it) } ?: "—", bold = true))
                addView(cell(cum))
                addView(cell(pace?.let { formatPace(it) } ?: "—"))
                addView(cell(String.format(Locale.FRANCE, "%d m\n+%d %%", leg.runM.toInt(), leg.extraPercent.toInt())))
                when (pace) {
                    null -> {}
                    slow -> setBackgroundColor(0xFFFFDCDC.toInt())
                    fast -> setBackgroundColor(0xFFDDF3DD.toInt())
                }
                isClickable = true
                setOnClickListener {
                    this@MainActivity.overlay.highlight(leg.fromIdx, leg.toIdx)
                    hint.text = "Section ${Splits.label(leg.from, n)} → ${Splits.label(leg.to, n)} en bleu"
                    dialog?.dismiss()
                }
            }
            table.addView(row)
        }
        val total = legs.mapNotNull { it.timeMs }.takeIf { it.size == legs.size }?.sum()
        val totalRun = legs.sumOf { it.runM }
        table.addView(TableRow(this).apply {
            addView(cell("Total", true, Gravity.START))
            addView(cell(total?.let { formatDuration(it) } ?: "—", true))
            addView(cell(""))
            addView(cell(if (total != null && totalRun > 10) formatPace(total / 1000.0 / (totalRun / 1000.0)) else "—"))
            addView(cell(String.format(Locale.FRANCE, "%.2f km", totalRun / 1000)))
        })
        val note = TextView(this).apply {
            textSize = 12f
            setPadding(pad * 2, pad, pad * 2, pad * 2)
            text = buildString {
                append("Touchez une section pour la voir sur la carte. Rouge = section la plus lente, vert = la plus rapide (allure). ")
                append("« +% » = distance en plus par rapport à la ligne droite.")
                if (legs.any { !it.sure }) {
                    append("\n? = passage à moins de ${Splits.DEFAULT_RADIUS_M.toInt()} m non trouvé : vérifiez le calage ou la position du poste.")
                }
                if (this@MainActivity.overlay.track?.hasTimes == false) append("\nCette trace n'a pas d'horaires : seules les distances sont connues.")
            }
        }
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(table); addView(note)
        }
        dialog = AlertDialog.Builder(this)
            .setTitle("Temps intermédiaires")
            .setView(ScrollView(this).apply { addView(box) })
            .setPositiveButton("Fermer", null)
            .show()
    }

    // ---------- Replay ----------

    private fun startReplay() {
        val t = overlay.track
        if (t == null) { toast("Ouvrez d'abord une trace."); return }
        if (t.timedIdx.size < 2) { toast("Cette trace n'a pas d'horaires : impossible de la rejouer."); return }
        replayPunches = computePunches()?.first ?: emptyList()
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
        btnPlay.text = if (playing) "⏸" else "▶"
        btnSpeed.text = "×" + overlay.replaySpeed.toInt()
        if (overlay.mode != OverlayView.Mode.REPLAY) return
        // Temps de course : depuis le départ s'il est placé, sinon depuis le début de la trace.
        val start = replayPunches.firstOrNull()?.timeMs?.takeIf { replayPunches.first().sure } ?: a
        val sb = StringBuilder()
        sb.append(if (timeMs >= start) formatDuration(timeMs - start) else "-" + formatDuration(start - timeMs))
        sb.append(" / ").append(formatDuration((replayPunches.lastOrNull()?.timeMs ?: b) - start))
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
        hint.text = sb.toString()
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
        val v = FloatArray(9).also { overlay.traceMatrix.getValues(it) }
        prefs.edit()
            .putString("mapUri", mapUri?.toString())
            .putInt("mapPage", mapPage)
            .putString("gpxUri", gpxUri?.toString())
            .putString("traceMatrix", v.joinToString(","))
            .putString("controls", overlay.controls.joinToString(";") { "${it[0]},${it[1]}" })
            .putString("controlsMap", mapUri?.toString())
            .putBoolean("speedColors", overlay.speedColors)
            .putBoolean("lockScale", overlay.lockTraceScale)
            .putFloat("traceWidth", overlay.traceWidthDp)
            .putFloat("replaySpeed", overlay.replaySpeed)
            .putInt("scaleDen", scaleDenominator)
            .putInt("dpi", imageDpi)
            .apply()
    }

    private fun restoreSession() {
        val matrix = prefs.getString("traceMatrix", null)?.split(",")?.mapNotNull { it.toFloatOrNull() }
            ?.takeIf { it.size == 9 }?.toFloatArray()
        val gpx = prefs.getString("gpxUri", null)?.let(Uri::parse)
        val map = prefs.getString("mapUri", null)?.let(Uri::parse)
        val page = prefs.getInt("mapPage", 0)
        pendingControls = prefs.getString("controls", null)?.split(";")?.mapNotNull { s ->
            val xy = s.split(",").mapNotNull { it.toFloatOrNull() }
            if (xy.size == 2) floatArrayOf(xy[0], xy[1]) else null
        }
        pendingControlsMap = prefs.getString("controlsMap", null)
        // Les chargements passent par le même fil, dans l'ordre : trace puis carte.
        if (gpx != null) openGpx(gpx, matrix)
        if (map != null) openMap(map, page, refitTrace = false, savedMatrix = matrix)
    }

    // ---------- Interface ----------

    override fun onStateChanged() = refreshUi()

    override fun onMessage(msg: String) = toast(msg)

    private fun refreshUi() {
        val mode = overlay.mode
        modeBar.visibility = if (mode == OverlayView.Mode.MAP || mode == OverlayView.Mode.TRACE) View.VISIBLE else View.GONE
        calibBar.visibility = if (mode == OverlayView.Mode.CALIBRATE) View.VISIBLE else View.GONE
        controlsBar.visibility = if (mode == OverlayView.Mode.CONTROLS) View.VISIBLE else View.GONE
        replayBar.visibility = if (mode == OverlayView.Mode.REPLAY) View.VISIBLE else View.GONE
        styleButton(btnMap, mode == OverlayView.Mode.MAP)
        styleButton(btnTrace, mode == OverlayView.Mode.TRACE)
        styleButton(btnCalib, false)
        styleButton(btnControls, false)
        styleButton(btnReplay, false)

        val t = overlay.track
        stats.text = if (t == null) "Aucune trace" else buildString {
            append(String.format(Locale.FRANCE, "%.2f km", t.distanceM / 1000))
            t.durationMs?.let { append(" · ").append(formatDuration(it)) }
            t.paceSecPerKm?.let { append(" · ").append(formatPace(it)) }
            if (overlay.speedColors && t.hasTimes) append("  (rouge = lent, vert = rapide)")
        }
        hint.text = when (mode) {
            OverlayView.Mode.MAP -> "Glisser : déplacer · Pincer : zoomer"
            OverlayView.Mode.TRACE -> "Glisser : déplacer la trace · Deux doigts : tourner" +
                if (overlay.lockTraceScale) " (échelle verrouillée)" else " / agrandir"
            OverlayView.Mode.CALIBRATE -> {
                val n = overlay.calibrationCount
                val step = if (overlay.waitingForMapPoint) "2) Touchez l'endroit correspondant sur la carte"
                else "1) Touchez un point reconnaissable de la trace"
                "$step · $n point(s)" + if (n < 2) " — 2 minimum pour caler" else ""
            }
            OverlayView.Mode.CONTROLS -> {
                val n = overlay.controls.size
                val next = when (n) { 0 -> "le départ"; else -> "le poste $n (ou l'arrivée)" }
                "Touchez la carte pour placer $next · Glisser un poste pour le déplacer · Le dernier = arrivée"
            }
            OverlayView.Mode.REPLAY -> hint.text
        }
        if (mode == OverlayView.Mode.REPLAY) onReplayTick(overlay.replayTimeMs, overlay.replayPlaying)
    }

    /** Bouton sélectionné : fond plein magenta et texte blanc ; sinon fond transparent. */
    private fun styleButton(b: Button, selected: Boolean) {
        val radius = 8 * resources.displayMetrics.density
        val content = GradientDrawable().apply {
            setColor(if (selected) getColor(R.color.mode_selected) else 0x00000000)
            cornerRadius = radius
        }
        val mask = GradientDrawable().apply { setColor(0xFFFFFFFF.toInt()); cornerRadius = radius }
        b.background = RippleDrawable(ColorStateList.valueOf(0x33000000), content, mask)
        b.setTextColor(if (selected) 0xFFFFFFFF.toInt() else 0xFF333333.toInt())
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

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_LONG).show()

    companion object {
        private const val REQ_MAP = 1
        private const val REQ_GPX = 2
        private const val REQ_EXPORT = 3
    }
}
