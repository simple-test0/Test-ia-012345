package com.orienteering.gpxoverlay

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.DashPathEffect
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Path
import android.os.SystemClock
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin

/**
 * Affiche la carte, la trace GPX, les postes et le replay.
 *
 * Repères :
 *  - « local » : mètres autour du centre de la trace (x est, y sud) ;
 *  - « carte » : pixels du bitmap de la carte ;
 *  - « écran » : pixels de la vue.
 * [traceMatrix] : local → carte, [viewMatrix] : carte → écran.
 */
class OverlayView(context: Context, attrs: AttributeSet? = null) : View(context, attrs) {

    enum class Mode { MAP, TRACE, CALIBRATE, CONTROLS, REPLAY }

    interface Listener {
        fun onStateChanged()
        fun onMessage(msg: String)
        fun onReplayTick(timeMs: Long, playing: Boolean) {}
    }

    var listener: Listener? = null

    var mode = Mode.MAP
        set(value) {
            if (field == Mode.REPLAY && value != Mode.REPLAY) replayPlaying = false
            field = value
            pendingTraceIdx = -1
            draggedControl = -1
            invalidate()
            listener?.onStateChanged()
        }

    var speedColors = true
        set(value) { field = value; rebuildBins(); invalidate() }

    /** Épaisseur de la trace en dp. */
    var traceWidthDp = 4f
        set(value) { field = value; invalidate() }

    /** Si vrai, les gestes à deux doigts sur la trace ne changent pas son échelle. */
    var lockTraceScale = false

    /** Pixels de carte par mm de papier, si connu (sert à la taille des cercles de postes). */
    var mapPxPerMm: Double? = null

    var mapBitmap: Bitmap? = null
        private set
    var track: Track? = null
        private set

    val traceMatrix = Matrix()
    private val viewMatrix = Matrix()
    private val tmpMatrix = Matrix()
    private val invMatrix = Matrix()

    private val density = resources.displayMetrics.density
    private val touchSlop = ViewConfiguration.get(context).scaledTouchSlop

    // ---------- Calage par points ----------
    private val calibLocal = ArrayList<FloatArray>()
    private val calibMap = ArrayList<FloatArray>()
    private var pendingTraceIdx = -1

    val calibrationCount: Int get() = calibLocal.size
    val waitingForMapPoint: Boolean get() = pendingTraceIdx >= 0

    // ---------- Postes (en pixels de carte) ----------
    val controls = ArrayList<FloatArray>()
    private var draggedControl = -1

    // ---------- Section mise en évidence ----------
    private var highlightFrom = -1
    private var highlightTo = -1

    // ---------- Replay ----------
    var replayTimeMs = 0L
        private set
    var replaySpeed = 10f
    var replayFollow = true
    var replayPlaying = false
        set(value) {
            val t = track
            field = value && t != null && t.timedIdx.size >= 2
            if (field) {
                if (replayTimeMs >= (t!!.endTimeMs ?: 0)) replayTimeMs = t.startTimeMs ?: 0
                lastFrame = SystemClock.uptimeMillis()
                postInvalidateOnAnimation()
            }
            listener?.onReplayTick(replayTimeMs, field)
        }
    private var lastFrame = 0L
    /** Durée de la « traîne » derrière le coureur, en temps de course. */
    private val tailMs = 60_000L

    // ---------- Pinceaux ----------
    private val bitmapPaint = Paint(Paint.FILTER_BITMAP_FLAG or Paint.ANTI_ALIAS_FLAG)
    private val linePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeCap = Paint.Cap.ROUND; strokeJoin = Paint.Join.ROUND
    }
    private val haloPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeCap = Paint.Cap.ROUND; color = Color.argb(150, 255, 255, 255)
    }
    private val markerPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; color = Color.rgb(200, 0, 160)
    }
    private val coursePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; color = COURSE_COLOR
    }
    private val courseText = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = COURSE_COLOR; textAlign = Paint.Align.LEFT; isFakeBoldText = true
    }
    private val dashPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; color = Color.rgb(0, 90, 255)
        pathEffect = DashPathEffect(floatArrayOf(10f, 8f), 0f)
    }
    private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.DKGRAY; textAlign = Paint.Align.CENTER
    }

    private var screenPts = FloatArray(0)
    private var bins: Array<IntArray> = emptyArray()
    private var binColors = IntArray(0)
    private var binBuffers: Array<FloatArray> = emptyArray()
    /** Couleur de chaque tronçon i → i+1 (0 si pas de tronçon). */
    private var segColor = IntArray(0)

    // ---------- Chargement ----------

    fun setMap(bmp: Bitmap?, refitTrace: Boolean) {
        mapBitmap = bmp
        fitView()
        if (refitTrace) fitTraceToMap()
        invalidate()
    }

    fun setTrack(t: Track?, refit: Boolean) {
        track = t
        screenPts = FloatArray(t?.local?.size ?: 0)
        calibLocal.clear(); calibMap.clear(); pendingTraceIdx = -1
        clearHighlight()
        replayPlaying = false
        replayTimeMs = t?.startTimeMs ?: 0
        rebuildBins()
        if (refit) fitTraceToMap()
        if (mapBitmap == null) fitView()
        invalidate()
        listener?.onStateChanged()
    }

    private fun contentSize(): Pair<Float, Float> {
        val b = mapBitmap
        if (b != null) return b.width.toFloat() to b.height.toFloat()
        return max(width, 1).toFloat() to max(height, 1).toFloat()
    }

    /** Recadre la vue pour voir toute la carte. */
    fun fitView() {
        if (width == 0 || height == 0) return
        val (cw, ch) = contentSize()
        val s = min(width / cw, height / ch)
        viewMatrix.setScale(s, s)
        viewMatrix.postTranslate((width - cw * s) / 2, (height - ch * s) / 2)
        invalidate()
    }

    /** Recadre la vue sur un rectangle en pixels de carte. */
    private fun fitViewTo(x0: Float, y0: Float, x1: Float, y1: Float) {
        if (width == 0 || height == 0) return
        val w = max(x1 - x0, 1f) * 1.3f
        val h = max(y1 - y0, 1f) * 1.3f
        val (cw, ch) = contentSize()
        val s = min(min(width / w, height / h), 12f * density).coerceAtLeast(0.3f * min(width / cw, height / ch))
        viewMatrix.setScale(s, s)
        viewMatrix.postTranslate(width / 2f - (x0 + x1) / 2 * s, height / 2f - (y0 + y1) / 2 * s)
        invalidate()
    }

    /** Place la trace au centre de la carte, nord en haut, à 80 % de sa taille. */
    fun fitTraceToMap() {
        val t = track ?: return
        if (t.isEmpty) return
        val (cw, ch) = contentSize()
        val tw = max(t.maxX - t.minX, 1f)
        val th = max(t.maxY - t.minY, 1f)
        val s = 0.8f * min(cw / tw, ch / th)
        traceMatrix.setTranslate(-(t.minX + t.maxX) / 2, -(t.minY + t.maxY) / 2)
        traceMatrix.postScale(s, s)
        traceMatrix.postTranslate(cw / 2, ch / 2)
        calibLocal.clear(); calibMap.clear(); pendingTraceIdx = -1
        listener?.onStateChanged()
        invalidate()
    }

    /** Met la trace à [pxPerMeter] pixels de carte par mètre, en gardant rotation et centre. */
    fun setTraceScale(pxPerMeter: Double) {
        val t = track ?: return
        val v = FloatArray(9).also { traceMatrix.getValues(it) }
        val rot = atan2(v[Matrix.MSKEW_Y].toDouble(), v[Matrix.MSCALE_X].toDouble())
        val cx = (t.minX + t.maxX) / 2
        val cy = (t.minY + t.maxY) / 2
        val c = floatArrayOf(cx, cy).also { traceMatrix.mapPoints(it) }
        val a = pxPerMeter * cos(rot)
        val b = pxPerMeter * sin(rot)
        val sim = Similarity(a, b, c[0] - (a * cx - b * cy), c[1] - (b * cx + a * cy))
        traceMatrix.setValues(sim.toMatrixValues())
        invalidate()
    }

    fun traceScale(): Double {
        val v = FloatArray(9).also { traceMatrix.getValues(it) }
        return hypot(v[Matrix.MSCALE_X].toDouble(), v[Matrix.MSKEW_Y].toDouble())
    }

    fun traceRotationDeg(): Double {
        val v = FloatArray(9).also { traceMatrix.getValues(it) }
        return Math.toDegrees(atan2(v[Matrix.MSKEW_Y].toDouble(), v[Matrix.MSCALE_X].toDouble()))
    }

    // ---------- Postes ----------

    /** Positions des postes dans le repère local de la trace (mètres), ou null. */
    fun controlsLocal(): DoubleArray? {
        if (controls.isEmpty() || !traceMatrix.invert(invMatrix)) return null
        val out = DoubleArray(controls.size * 2)
        val p = FloatArray(2)
        controls.forEachIndexed { i, c ->
            invMatrix.mapPoints(p, c)
            out[2 * i] = p[0].toDouble(); out[2 * i + 1] = p[1].toDouble()
        }
        return out
    }

    fun setControls(list: List<FloatArray>) {
        controls.clear(); controls.addAll(list)
        invalidate()
        listener?.onStateChanged()
    }

    fun undoControl() {
        if (controls.isNotEmpty()) controls.removeAt(controls.size - 1)
        clearHighlight()
        invalidate()
        listener?.onStateChanged()
    }

    fun clearControls() {
        controls.clear()
        clearHighlight()
        invalidate()
        listener?.onStateChanged()
    }

    /** Rayon d'un cercle de poste en pixels de carte (6 mm de diamètre sur le papier). */
    private fun controlRadiusMap(): Float {
        mapPxPerMm?.let { return (3.0 * it).toFloat() }
        val (cw, ch) = contentSize()
        return max(cw, ch) * 0.012f
    }

    /** Met en évidence la section de la trace entre deux indices, et zoome dessus. */
    fun highlight(fromIdx: Int, toIdx: Int) {
        val t = track ?: return
        highlightFrom = min(fromIdx, toIdx); highlightTo = max(fromIdx, toIdx)
        var x0 = Float.MAX_VALUE; var y0 = Float.MAX_VALUE; var x1 = -Float.MAX_VALUE; var y1 = -Float.MAX_VALUE
        val p = FloatArray(2)
        for (i in highlightFrom..highlightTo) {
            p[0] = t.local[2 * i]; p[1] = t.local[2 * i + 1]
            traceMatrix.mapPoints(p)
            x0 = min(x0, p[0]); y0 = min(y0, p[1]); x1 = max(x1, p[0]); y1 = max(y1, p[1])
        }
        fitViewTo(x0, y0, x1, y1)
    }

    fun clearHighlight() { highlightFrom = -1; highlightTo = -1; invalidate() }

    // ---------- Replay ----------

    fun setReplayTime(t: Long) {
        val tr = track ?: return
        replayTimeMs = t.coerceIn(tr.startTimeMs ?: 0, tr.endTimeMs ?: 0)
        invalidate()
        listener?.onReplayTick(replayTimeMs, replayPlaying)
    }

    // ---------- Couleurs selon la vitesse ----------

    private fun rebuildBins() {
        val t = track
        if (t == null || t.points.size < 2) {
            bins = emptyArray(); binBuffers = emptyArray(); binColors = IntArray(0); segColor = IntArray(0); return
        }
        val useSpeed = speedColors && t.hasTimes
        val nBins = if (useSpeed) 12 else 1
        var lo = 0f; var hi = 1f
        if (useSpeed) {
            val sorted = t.speeds.filter { !it.isNaN() }.sorted()
            lo = sorted[(sorted.size * 0.05).toInt().coerceIn(0, sorted.size - 1)]
            hi = sorted[(sorted.size * 0.95).toInt().coerceIn(0, sorted.size - 1)]
            if (hi - lo < 0.05f) hi = lo + 0.05f
        }
        binColors = IntArray(nBins) { i ->
            if (!useSpeed) Color.rgb(230, 20, 30) else speedColor(i / (nBins - 1f))
        }
        val lists = Array(nBins) { ArrayList<Int>() }
        segColor = IntArray(t.points.size)
        t.forEachSegment { a, b ->
            for (i in a until b - 1) {
                val bin = if (!useSpeed) 0 else {
                    val s = t.speeds[i]
                    if (s.isNaN()) 0 else (((s - lo) / (hi - lo)) * nBins).toInt().coerceIn(0, nBins - 1)
                }
                lists[bin].add(i)
                segColor[i] = binColors[bin]
            }
        }
        bins = Array(nBins) { lists[it].toIntArray() }
        binBuffers = Array(nBins) { FloatArray(bins[it].size * 4) }
    }

    /** 0 = lent (rouge) → 0,5 = jaune → 1 = rapide (vert). */
    private fun speedColor(f: Float): Int {
        val r: Int; val g: Int
        if (f < 0.5f) { r = 230; g = (40 + 400 * f).toInt() } else { r = (230 - 420 * (f - 0.5f)).toInt(); g = 240 - (60 * (f - 0.5f)).toInt() }
        return Color.rgb(r.coerceIn(0, 255), g.coerceIn(0, 255), 30)
    }

    // ---------- Dessin ----------

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        if (oldw == 0 || oldh == 0) {
            fitView()
            if (mapBitmap == null && track != null && traceMatrix.isIdentity) fitTraceToMap()
        } else {
            viewMatrix.postTranslate((w - oldw) / 2f, (h - oldh) / 2f)
        }
    }

    override fun onDraw(canvas: Canvas) {
        canvas.drawColor(Color.rgb(235, 235, 230))
        mapBitmap?.let { canvas.drawBitmap(it, viewMatrix, bitmapPaint) }
        val t = track
        if (t == null && mapBitmap == null) {
            textPaint.textSize = 16 * density
            canvas.drawText("Ouvrez une carte (image ou PDF)", width / 2f, height / 2f - 12 * density, textPaint)
            canvas.drawText("et une trace (GPX, FIT, TCX) avec les boutons du haut.", width / 2f, height / 2f + 12 * density, textPaint)
            return
        }
        val vs = viewScale()
        drawCourse(canvas, viewMatrix, controlRadiusMap() * vs, max(1.5f * density, controlRadiusMap() * vs * 0.1f))
        if (t == null || t.isEmpty) return
        tmpMatrix.set(traceMatrix)
        tmpMatrix.postConcat(viewMatrix)
        val w = traceWidthDp * density
        val dim = mode == Mode.REPLAY || highlightFrom >= 0
        drawTrack(canvas, t, tmpMatrix, w, screenPts, if (dim) 70 else 255)
        if (highlightFrom >= 0) drawRange(canvas, t, screenPts, highlightFrom, highlightTo, w * 1.4f, Color.rgb(0, 90, 255))
        if (mode == Mode.REPLAY) drawReplay(canvas, t, w)
        else drawStartFinish(canvas, screenPts, t, 9 * density)
        if (mode == Mode.CALIBRATE) drawCalibration(canvas)
    }

    private fun viewScale(): Float {
        val v = FloatArray(9).also { viewMatrix.getValues(it) }
        return v[Matrix.MSCALE_X]
    }

    /** Dessine la trace (local → canvas via [toTarget]). Remplit [pts] avec les positions. */
    fun drawTrack(canvas: Canvas, t: Track, toTarget: Matrix, widthPx: Float, pts: FloatArray, alpha: Int = 255) {
        toTarget.mapPoints(pts, t.local)
        haloPaint.strokeWidth = widthPx * 1.8f
        haloPaint.alpha = 150 * alpha / 255
        linePaint.strokeWidth = widthPx
        for (k in bins.indices) {
            val idx = bins[k]
            val buf = binBuffers[k]
            for (j in idx.indices) {
                val i = idx[j]
                buf[4 * j] = pts[2 * i]; buf[4 * j + 1] = pts[2 * i + 1]
                buf[4 * j + 2] = pts[2 * i + 2]; buf[4 * j + 3] = pts[2 * i + 3]
            }
        }
        // Halo blanc seulement pour la trace pleine (en transparence il fait des pointillés).
        if (alpha == 255) for (k in bins.indices) canvas.drawLines(binBuffers[k], haloPaint)
        linePaint.strokeCap = if (alpha == 255) Paint.Cap.ROUND else Paint.Cap.BUTT
        for (k in bins.indices) {
            linePaint.color = binColors[k]
            linePaint.alpha = alpha
            canvas.drawLines(binBuffers[k], linePaint)
        }
        haloPaint.alpha = 150
        linePaint.alpha = 255
        linePaint.strokeCap = Paint.Cap.ROUND
    }

    /** Dessine les tronçons [from, to) déjà projetés dans [pts]. color = 0 → couleur de vitesse. */
    private fun drawRange(canvas: Canvas, t: Track, pts: FloatArray, from: Int, to: Int, widthPx: Float, color: Int) {
        haloPaint.strokeWidth = widthPx * 1.8f
        linePaint.strokeWidth = widthPx
        val ends = t.segmentStarts
        for (pass in 0..1) {
            for (i in max(0, from) until min(to, t.points.size - 1)) {
                if (ends.contains(i + 1) && i + 1 != t.points.size) continue
                if (pass == 0) canvas.drawLine(pts[2 * i], pts[2 * i + 1], pts[2 * i + 2], pts[2 * i + 3], haloPaint)
                else {
                    linePaint.color = if (color != 0) color else segColor[i]
                    canvas.drawLine(pts[2 * i], pts[2 * i + 1], pts[2 * i + 2], pts[2 * i + 3], linePaint)
                }
            }
        }
    }

    private fun drawReplay(canvas: Canvas, t: Track, w: Float) {
        val now = SystemClock.uptimeMillis()
        if (replayPlaying) {
            val dt = (now - lastFrame).coerceIn(0, 200)
            replayTimeMs += (dt * replaySpeed).toLong()
            val end = t.endTimeMs ?: replayTimeMs
            if (replayTimeMs >= end) { replayTimeMs = end; replayPlaying = false }
            listener?.onReplayTick(replayTimeMs, replayPlaying)
        }
        lastFrame = now
        val pos = FloatArray(2)
        val idx = t.positionAt(replayTimeMs, pos)
        if (idx < 0) return
        val tailStart = FloatArray(2)
        val idx0 = t.positionAt(replayTimeMs - tailMs, tailStart)
        drawRange(canvas, t, screenPts, idx0, idx, w * 1.3f, 0)
        tmpMatrix.mapPoints(pos)
        // Dernier bout : du point précédent jusqu'à la position exacte du coureur.
        linePaint.color = if (idx < segColor.size) segColor[idx] else Color.RED
        canvas.drawLine(screenPts[2 * idx], screenPts[2 * idx + 1], pos[0], pos[1], linePaint)
        if (replayFollow) {
            val mx = width * 0.2f; val my = height * 0.2f
            if (pos[0] < mx || pos[0] > width - mx || pos[1] < my || pos[1] > height - my) {
                val dx = width / 2f - pos[0]; val dy = height / 2f - pos[1]
                viewMatrix.postTranslate(dx, dy)
                pos[0] += dx; pos[1] += dy
                postInvalidateOnAnimation()
            }
        }
        fillPaint.color = Color.WHITE
        canvas.drawCircle(pos[0], pos[1], 9 * density, fillPaint)
        fillPaint.color = Color.rgb(0, 90, 255)
        canvas.drawCircle(pos[0], pos[1], 6.5f * density, fillPaint)
        if (replayPlaying) postInvalidateOnAnimation()
    }

    /** Départ = triangle, arrivée = double cercle (symboles de course d'orientation). */
    fun drawStartFinish(canvas: Canvas, pts: FloatArray, t: Track, r: Float) {
        if (t.points.size < 2 || controls.size >= 2) return
        markerPaint.strokeWidth = r / 4
        canvas.drawPath(trianglePath(pts[0], pts[1], 1.4f * r, null), markerPaint)
        val n = t.points.size - 1
        canvas.drawCircle(pts[2 * n], pts[2 * n + 1], r, markerPaint)
        canvas.drawCircle(pts[2 * n], pts[2 * n + 1], r * 0.6f, markerPaint)
    }

    /** Triangle équilatéral centré, pointe vers [toward] (ou vers le haut). */
    private fun trianglePath(x: Float, y: Float, r: Float, toward: FloatArray?): Path {
        val base = if (toward != null) atan2((toward[1] - y).toDouble(), (toward[0] - x).toDouble()) else -Math.PI / 2
        val path = Path()
        for (k in 0..2) {
            val ang = base + k * 2 * Math.PI / 3
            val px = x + r * cos(ang).toFloat()
            val py = y + r * sin(ang).toFloat()
            if (k == 0) path.moveTo(px, py) else path.lineTo(px, py)
        }
        path.close()
        return path
    }

    /** Dessine le circuit (postes en pixels de carte, projetés par [toTarget]). */
    fun drawCourse(canvas: Canvas, toTarget: Matrix, r: Float, stroke: Float) {
        if (controls.isEmpty()) return
        val n = controls.size
        val pts = FloatArray(n * 2)
        for (i in 0 until n) { pts[2 * i] = controls[i][0]; pts[2 * i + 1] = controls[i][1] }
        toTarget.mapPoints(pts)
        coursePaint.strokeWidth = stroke
        courseText.textSize = max(12 * density, r * 1.3f)
        fun radiusOf(i: Int) = when {
            i == 0 -> r * 1.2f
            i == n - 1 && n >= 2 -> r * 1.2f
            else -> r
        }
        // Traits entre postes, arrêtés au bord des symboles.
        for (i in 1 until n) {
            val x0 = pts[2 * i - 2]; val y0 = pts[2 * i - 1]; val x1 = pts[2 * i]; val y1 = pts[2 * i + 1]
            val d = hypot(x1 - x0, y1 - y0)
            val r0 = radiusOf(i - 1) + stroke; val r1 = radiusOf(i) + stroke
            if (d > r0 + r1) {
                val ux = (x1 - x0) / d; val uy = (y1 - y0) / d
                canvas.drawLine(x0 + ux * r0, y0 + uy * r0, x1 - ux * r1, y1 - uy * r1, coursePaint)
            }
        }
        for (i in 0 until n) {
            val x = pts[2 * i]; val y = pts[2 * i + 1]
            when {
                i == 0 -> canvas.drawPath(
                    trianglePath(x, y, r * 1.2f, if (n > 1) floatArrayOf(pts[2], pts[3]) else null), coursePaint
                )
                i == n - 1 && n >= 2 -> {
                    canvas.drawCircle(x, y, r * 0.8f, coursePaint)
                    canvas.drawCircle(x, y, r * 1.2f, coursePaint)
                }
                else -> {
                    canvas.drawCircle(x, y, r, coursePaint)
                    canvas.drawText(i.toString(), x + r * 0.9f, y - r * 0.9f, courseText)
                }
            }
        }
        if (mode == Mode.CONTROLS && draggedControl >= 0 && draggedControl < n) {
            fillPaint.color = Color.argb(60, 166, 38, 255)
            canvas.drawCircle(pts[2 * draggedControl], pts[2 * draggedControl + 1], r * 1.5f, fillPaint)
        }
    }

    private fun drawCalibration(canvas: Canvas) {
        val r = 8 * density
        dashPaint.strokeWidth = 2 * density
        textPaint.textSize = 13 * density
        val a = FloatArray(2); val b = FloatArray(2)
        for (i in calibLocal.indices) {
            tmpMatrix.mapPoints(a, calibLocal[i])
            viewMatrix.mapPoints(b, calibMap[i])
            canvas.drawLine(a[0], a[1], b[0], b[1], dashPaint)
            fillPaint.color = Color.rgb(0, 90, 255)
            canvas.drawCircle(a[0], a[1], r * 0.6f, fillPaint)
            markerPaint.strokeWidth = 2.5f * density
            canvas.drawLine(b[0] - r, b[1], b[0] + r, b[1], markerPaint)
            canvas.drawLine(b[0], b[1] - r, b[0], b[1] + r, markerPaint)
            canvas.drawCircle(b[0], b[1], r, markerPaint)
            canvas.drawText("${i + 1}", b[0] + 1.6f * r, b[1] - 1.2f * r, textPaint)
        }
        if (pendingTraceIdx >= 0) {
            val p = track ?: return
            a[0] = p.local[2 * pendingTraceIdx]; a[1] = p.local[2 * pendingTraceIdx + 1]
            tmpMatrix.mapPoints(a)
            fillPaint.color = Color.argb(120, 0, 90, 255)
            canvas.drawCircle(a[0], a[1], 2.2f * r, fillPaint)
            fillPaint.color = Color.rgb(0, 90, 255)
            canvas.drawCircle(a[0], a[1], r * 0.7f, fillPaint)
        }
    }

    // ---------- Export ----------

    /** Image de la carte avec le circuit et la trace, à la résolution de la carte. */
    fun renderComposite(): Bitmap? {
        val map = mapBitmap ?: return null
        val t = track
        val out = map.copy(Bitmap.Config.ARGB_8888, true) ?: return null
        val c = Canvas(out)
        val r = controlRadiusMap()
        drawCourse(c, Matrix(), r, r * 0.1f)
        if (t != null && !t.isEmpty) {
            val w = max(3f, max(map.width, map.height) / 900f) * traceWidthDp / 4f
            val pts = FloatArray(t.local.size)
            drawTrack(c, t, traceMatrix, w, pts)
            drawStartFinish(c, pts, t, w * 2.5f)
        }
        return out
    }

    // ---------- Calage par points ----------

    fun undoCalibration() {
        if (pendingTraceIdx >= 0) pendingTraceIdx = -1
        else if (calibLocal.isNotEmpty()) {
            calibLocal.removeAt(calibLocal.size - 1)
            calibMap.removeAt(calibMap.size - 1)
            applyCalibration()
        }
        invalidate()
        listener?.onStateChanged()
    }

    fun clearCalibration() {
        calibLocal.clear(); calibMap.clear(); pendingTraceIdx = -1
        invalidate()
        listener?.onStateChanged()
    }

    private fun applyCalibration() {
        val n = calibLocal.size
        if (n == 0) return
        if (n == 1) {
            val p = FloatArray(2).also { traceMatrix.mapPoints(it, calibLocal[0]) }
            traceMatrix.postTranslate(calibMap[0][0] - p[0], calibMap[0][1] - p[1])
            return
        }
        val src = DoubleArray(2 * n); val dst = DoubleArray(2 * n)
        for (i in 0 until n) {
            src[2 * i] = calibLocal[i][0].toDouble(); src[2 * i + 1] = calibLocal[i][1].toDouble()
            dst[2 * i] = calibMap[i][0].toDouble(); dst[2 * i + 1] = calibMap[i][1].toDouble()
        }
        Similarity.fit(src, dst)?.let { traceMatrix.setValues(it.toMatrixValues()) }
    }

    private fun handleCalibrationTap(x: Float, y: Float) {
        val t = track ?: run { listener?.onMessage("Ouvrez d'abord une trace."); return }
        if (pendingTraceIdx < 0) {
            tmpMatrix.set(traceMatrix); tmpMatrix.postConcat(viewMatrix)
            tmpMatrix.mapPoints(screenPts, t.local)
            var best = -1; var bestD = Float.MAX_VALUE
            for (i in 0 until t.points.size) {
                val d = hypot(screenPts[2 * i] - x, screenPts[2 * i + 1] - y)
                if (d < bestD) { bestD = d; best = i }
            }
            if (best < 0 || bestD > 40 * density) {
                listener?.onMessage("Touchez un point situé sur la trace.")
                return
            }
            pendingTraceIdx = best
        } else {
            viewMatrix.invert(invMatrix)
            val m = floatArrayOf(x, y).also { invMatrix.mapPoints(it) }
            calibLocal.add(floatArrayOf(t.local[2 * pendingTraceIdx], t.local[2 * pendingTraceIdx + 1]))
            calibMap.add(m)
            pendingTraceIdx = -1
            applyCalibration()
        }
        invalidate()
        listener?.onStateChanged()
    }

    // ---------- Gestes ----------

    private val prevX = FloatArray(2)
    private val prevY = FloatArray(2)
    private val prevId = IntArray(2) { -1 }
    private var downX = 0f
    private var downY = 0f
    private var tapCandidate = false

    private fun rememberPointers(e: MotionEvent, skipIndex: Int = -1) {
        var k = 0
        prevId[0] = -1; prevId[1] = -1
        for (i in 0 until e.pointerCount) {
            if (i == skipIndex) continue
            if (k >= 2) break
            prevId[k] = e.getPointerId(i); prevX[k] = e.getX(i); prevY[k] = e.getY(i); k++
        }
    }

    /** Indice du poste sous le doigt, ou -1. */
    private fun controlAt(x: Float, y: Float): Int {
        val touch = max(24 * density, controlRadiusMap() * viewScale() * 1.2f)
        val p = FloatArray(2)
        var best = -1; var bestD = Float.MAX_VALUE
        controls.forEachIndexed { i, c ->
            viewMatrix.mapPoints(p, c)
            val d = hypot(p[0] - x, p[1] - y)
            if (d < touch && d < bestD) { bestD = d; best = i }
        }
        return best
    }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                downX = e.x; downY = e.y; tapCandidate = true
                draggedControl = if (mode == Mode.CONTROLS) controlAt(e.x, e.y) else -1
                rememberPointers(e)
            }
            MotionEvent.ACTION_POINTER_DOWN -> { tapCandidate = false; draggedControl = -1; rememberPointers(e) }
            MotionEvent.ACTION_POINTER_UP -> rememberPointers(e, e.actionIndex)
            MotionEvent.ACTION_MOVE -> {
                if (tapCandidate && hypot(e.x - downX, e.y - downY) > touchSlop) tapCandidate = false
                if (!tapCandidate) {
                    if (draggedControl >= 0 && e.pointerCount == 1) moveControl(e)
                    else handleMove(e)
                }
            }
            MotionEvent.ACTION_UP -> {
                if (tapCandidate) {
                    when (mode) {
                        Mode.CALIBRATE -> handleCalibrationTap(e.x, e.y)
                        Mode.CONTROLS -> if (draggedControl < 0) addControlAt(e.x, e.y)
                        else -> {}
                    }
                }
                if (draggedControl >= 0) { draggedControl = -1; invalidate(); listener?.onStateChanged() }
                tapCandidate = false
            }
            MotionEvent.ACTION_CANCEL -> { tapCandidate = false; draggedControl = -1 }
        }
        return true
    }

    private fun addControlAt(x: Float, y: Float) {
        viewMatrix.invert(invMatrix)
        controls.add(floatArrayOf(x, y).also { invMatrix.mapPoints(it) })
        clearHighlight()
        invalidate()
        listener?.onStateChanged()
    }

    private fun moveControl(e: MotionEvent) {
        viewMatrix.invert(invMatrix)
        val dx = e.x - prevX[0]; val dy = e.y - prevY[0]
        val c = controls[draggedControl]
        val p = FloatArray(2)
        viewMatrix.mapPoints(p, c)
        p[0] += dx; p[1] += dy
        invMatrix.mapPoints(p)
        c[0] = p[0]; c[1] = p[1]
        rememberPointers(e)
        invalidate()
    }

    private fun handleMove(e: MotionEvent) {
        val i0 = e.findPointerIndex(prevId[0])
        val i1 = if (prevId[1] >= 0) e.findPointerIndex(prevId[1]) else -1
        if (i0 < 0) { rememberPointers(e); return }
        val d = Matrix()
        val editTrace = mode == Mode.TRACE
        if (i1 >= 0) {
            val ax = prevX[0]; val ay = prevY[0]; val bx = prevX[1]; val by = prevY[1]
            val cx = e.getX(i0); val cy = e.getY(i0); val dx = e.getX(i1); val dy = e.getY(i1)
            val d0 = hypot(bx - ax, by - ay); val d1 = hypot(dx - cx, dy - cy)
            if (d0 < 1f || d1 < 1f) { rememberPointers(e); return }
            var s = d1 / d0
            if (editTrace && lockTraceScale) s = 1f
            val mx0 = (ax + bx) / 2; val my0 = (ay + by) / 2
            val mx1 = (cx + dx) / 2; val my1 = (cy + dy) / 2
            if (!editTrace) s = clampZoom(s)
            d.setScale(s, s, mx0, my0)
            if (editTrace) {
                val rot = Math.toDegrees(
                    (atan2(dy - cy, dx - cx) - atan2(by - ay, bx - ax)).toDouble()
                ).toFloat()
                d.postRotate(rot, mx0, my0)
            }
            d.postTranslate(mx1 - mx0, my1 - my0)
        } else {
            d.setTranslate(e.getX(i0) - prevX[0], e.getY(i0) - prevY[0])
        }
        if (editTrace) {
            viewMatrix.invert(invMatrix)
            traceMatrix.postConcat(viewMatrix)
            traceMatrix.postConcat(d)
            traceMatrix.postConcat(invMatrix)
        } else {
            viewMatrix.postConcat(d)
        }
        rememberPointers(e)
        invalidate()
    }

    private fun clampZoom(s: Float): Float {
        val cur = viewScale()
        val (cw, ch) = contentSize()
        val minScale = 0.3f * min(width / cw, height / ch)
        val maxScale = 12f * density
        return (cur * s).coerceIn(minScale, maxScale) / cur
    }

    companion object {
        /** Violet des circuits de course d'orientation (norme IOF). */
        val COURSE_COLOR = Color.argb(230, 166, 38, 255)
    }
}
