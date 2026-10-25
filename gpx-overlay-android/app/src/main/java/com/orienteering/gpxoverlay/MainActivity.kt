package com.orienteering.gpxoverlay

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.graphics.Bitmap
import android.content.res.ColorStateList
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.net.Uri
import android.os.Bundle
import android.text.InputType
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import java.util.Locale
import java.util.concurrent.Executors

class MainActivity : Activity(), OverlayView.Listener {

    private lateinit var overlay: OverlayView
    private lateinit var stats: TextView
    private lateinit var hint: TextView
    private lateinit var progress: ProgressBar
    private lateinit var btnMap: Button
    private lateinit var btnTrace: Button
    private lateinit var btnCalib: Button
    private lateinit var btnUndo: Button
    private lateinit var btnDone: Button

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

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        overlay = findViewById(R.id.overlay)
        stats = findViewById(R.id.stats)
        hint = findViewById(R.id.hint)
        progress = findViewById(R.id.progress)
        btnMap = findViewById(R.id.btnMap)
        btnTrace = findViewById(R.id.btnTrace)
        btnCalib = findViewById(R.id.btnCalib)
        btnUndo = findViewById(R.id.btnUndo)
        btnDone = findViewById(R.id.btnDone)

        overlay.listener = this
        btnMap.setOnClickListener { overlay.mode = OverlayView.Mode.MAP }
        btnTrace.setOnClickListener {
            if (overlay.track == null) toast("Ouvrez d'abord une trace GPX.")
            else overlay.mode = OverlayView.Mode.TRACE
        }
        btnCalib.setOnClickListener {
            if (overlay.track == null || overlay.mapBitmap == null) toast("Ouvrez une carte et une trace GPX.")
            else overlay.mode = OverlayView.Mode.CALIBRATE
        }
        btnUndo.setOnClickListener { overlay.undoCalibration() }
        btnDone.setOnClickListener { overlay.mode = OverlayView.Mode.MAP }

        overlay.speedColors = prefs.getBoolean("speedColors", true)
        overlay.lockTraceScale = prefs.getBoolean("lockScale", false)
        overlay.traceWidthDp = prefs.getFloat("traceWidth", 4f)
        scaleDenominator = prefs.getInt("scaleDen", 10000)
        imageDpi = prefs.getInt("dpi", 300)

        restoreSession()
        refreshUi()
    }

    override fun onPause() {
        super.onPause()
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
            R.id.open_map -> pick(REQ_MAP, "*/*", arrayOf("image/*", "application/pdf"))
            R.id.open_gpx -> pick(REQ_GPX, "*/*", null)
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

    private fun pick(req: Int, type: String, mimes: Array<String>?) {
        val i = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            this.type = type
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
                    mapUri = uri; mapIsPdf = m.isPdf; mapPage = m.page; mapPageCount = m.pageCount
                    mapPxPerMm = m.pxPerMm
                    overlay.setMap(m.bitmap, refitTrace && savedMatrix == null)
                    if (savedMatrix != null) overlay.traceMatrix.setValues(savedMatrix)
                    else if (refitTrace && m.isPdf) applyKnownScale(quiet = true)
                    if (old != null && old !== m.bitmap) old.recycle()
                    invalidateOptionsMenu()
                    refreshUi()
                    saveSession()
                    if (refitTrace && overlay.track != null && savedMatrix == null) {
                        toast("Trace placée au centre. Calez-la avec « Ajuster trace » ou « Calage ».")
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
                val t = contentResolver.openInputStream(uri)!!.use { GpxParser.parse(it) }
                runOnUiThread {
                    busy(false)
                    gpxUri = uri
                    overlay.setTrack(t, refit = savedMatrix == null)
                    if (savedMatrix != null) overlay.traceMatrix.setValues(savedMatrix)
                    else if (overlay.mapBitmap != null && mapIsPdf) applyKnownScale(quiet = true)
                    if (overlay.mode == OverlayView.Mode.CALIBRATE) overlay.mode = OverlayView.Mode.MAP
                    refreshUi()
                    saveSession()
                }
            } catch (e: Throwable) {
                runOnUiThread { busy(false); toast(e.message ?: "GPX illisible") }
            }
        }
    }

    // ---------- Échelle ----------

    /** Si on connaît la résolution de la carte, met la trace à la bonne échelle. */
    private fun applyKnownScale(quiet: Boolean) {
        val pxPerMm = mapPxPerMm ?: return
        if (overlay.track == null) return
        // 1 m au sol = 1000 / dénominateur mm sur le papier.
        overlay.setTraceScale(pxPerMm * 1000.0 / scaleDenominator)
        if (!quiet) toast("Trace mise à l'échelle 1:$scaleDenominator")
    }

    private fun showScaleDialog() {
        val pad = (16 * resources.displayMetrics.density).toInt()
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(pad, pad / 2, pad, 0) }
        val scaleLabel = TextView(this).apply { text = "Échelle 1 :" }
        val scaleEdit = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_NUMBER
            setText(scaleDenominator.toString())
        }
        box.addView(scaleLabel); box.addView(scaleEdit)
        var dpiEdit: EditText? = null
        if (!mapIsPdf) {
            box.addView(TextView(this).apply { text = "Résolution de l'image (dpi) :" })
            dpiEdit = EditText(this).apply {
                inputType = InputType.TYPE_CLASS_NUMBER
                setText(imageDpi.toString())
            }
            box.addView(dpiEdit)
            box.addView(TextView(this).apply {
                text = "Pour une image, l'échelle n'est juste que si le dpi est connu (scan ou export). Sinon, utilisez le calage par points."
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
                    // Recalcule les px/mm de l'image avec le nouveau dpi.
                    mapPxPerMm?.let { old -> mapPxPerMm = old / imageDpi * dpi }
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
            .putBoolean("speedColors", overlay.speedColors)
            .putBoolean("lockScale", overlay.lockTraceScale)
            .putFloat("traceWidth", overlay.traceWidthDp)
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
        // Les deux chargements passent par le même fil, dans l'ordre : GPX puis carte.
        if (gpx != null) openGpx(gpx, matrix)
        if (map != null) openMap(map, page, refitTrace = false, savedMatrix = matrix)
    }

    // ---------- Interface ----------

    override fun onCalibrationStateChanged() = refreshUi()

    override fun onMessage(msg: String) = toast(msg)

    private fun refreshUi() {
        val mode = overlay.mode
        val calib = mode == OverlayView.Mode.CALIBRATE
        btnMap.visibility = if (calib) View.GONE else View.VISIBLE
        btnTrace.visibility = if (calib) View.GONE else View.VISIBLE
        btnCalib.visibility = if (calib) View.GONE else View.VISIBLE
        btnUndo.visibility = if (calib) View.VISIBLE else View.GONE
        btnDone.visibility = if (calib) View.VISIBLE else View.GONE
        styleButton(btnMap, mode == OverlayView.Mode.MAP)
        styleButton(btnTrace, mode == OverlayView.Mode.TRACE)
        styleButton(btnCalib, false)
        styleButton(btnUndo, false)
        styleButton(btnDone, true)

        val t = overlay.track
        stats.text = if (t == null) "Aucune trace" else buildString {
            append(String.format(Locale.FRANCE, "%.2f km", t.distanceM / 1000))
            t.durationMs?.let { append(" · ").append(formatDuration(it)) }
            t.paceSecPerKm?.let {
                val s = it.toInt()
                append(String.format(Locale.FRANCE, " · %d'%02d\"/km", s / 60, s % 60))
            }
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
        }
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

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_LONG).show()

    companion object {
        private const val REQ_MAP = 1
        private const val REQ_GPX = 2
        private const val REQ_EXPORT = 3
    }
}
