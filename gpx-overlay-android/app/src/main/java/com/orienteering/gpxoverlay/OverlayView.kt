package com.orienteering.gpxoverlay

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.DashPathEffect
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Path
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
 * Affiche la carte et la trace GPX superposée.
 *
 * Repères :
 *  - « local » : mètres autour du centre de la trace (x est, y sud) ;
 *  - « carte » : pixels du bitmap de la carte ;
 *  - « écran » : pixels de la vue.
 * [traceMatrix] : local → carte, [viewMatrix] : carte → écran.
 */
class OverlayView(context: Context, attrs: AttributeSet? = null) : View(context, attrs) {

    enum class Mode { MAP, TRACE, CALIBRATE }

    interface Listener {
        fun onCalibrationStateChanged()
        fun onMessage(msg: String)
    }

    var listener: Listener? = null

    var mode = Mode.MAP
        set(value) {
            field = value
            pendingTraceIdx = -1
            invalidate()
            listener?.onCalibrationStateChanged()
        }

    var speedColors = true
        set(value) { field = value; rebuildBins(); invalidate() }

    /** Épaisseur de la trace en dp. */
    var traceWidthDp = 4f
        set(value) { field = value; invalidate() }

    /** Si vrai, les gestes à deux doigts sur la trace ne changent pas son échelle. */
    var lockTraceScale = false

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
    /** Paires (point local de la trace, point sur la carte). */
    private val calibLocal = ArrayList<FloatArray>()
    private val calibMap = ArrayList<FloatArray>()
    private var pendingTraceIdx = -1

    val calibrationCount: Int get() = calibLocal.size
    val waitingForMapPoint: Boolean get() = pendingTraceIdx >= 0

    // ---------- Dessin ----------
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
        rebuildBins()
        if (refit) fitTraceToMap()
        if (mapBitmap == null) fitView()
        invalidate()
        listener?.onCalibrationStateChanged()
    }

    /** Taille (en pixels « carte ») de l'espace de travail. */
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
        listener?.onCalibrationStateChanged()
        invalidate()
    }

    /**
     * Applique une échelle réelle à la trace : [pxPerMeter] pixels de carte par mètre au sol.
     * On garde la rotation et la position du centre de la trace.
     */
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

    /** Échelle actuelle de la trace en pixels de carte par mètre. */
    fun traceScale(): Double {
        val v = FloatArray(9).also { traceMatrix.getValues(it) }
        return hypot(v[Matrix.MSCALE_X].toDouble(), v[Matrix.MSKEW_Y].toDouble())
    }

    fun traceRotationDeg(): Double {
        val v = FloatArray(9).also { traceMatrix.getValues(it) }
        return Math.toDegrees(atan2(v[Matrix.MSKEW_Y].toDouble(), v[Matrix.MSCALE_X].toDouble()))
    }

    // ---------- Couleurs selon la vitesse ----------

    private fun rebuildBins() {
        val t = track
        if (t == null || t.points.size < 2) {
            bins = emptyArray(); binBuffers = emptyArray(); binColors = IntArray(0); return
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
        val lists = Array(nBins) { ArrayList<Int>() }
        t.forEachSegment { a, b ->
            for (i in a until b - 1) {
                val bin = if (!useSpeed) 0 else {
                    val s = t.speeds[i]
                    if (s.isNaN()) 0 else (((s - lo) / (hi - lo)) * nBins).toInt().coerceIn(0, nBins - 1)
                }
                lists[bin].add(i)
            }
        }
        bins = Array(nBins) { lists[it].toIntArray() }
        binBuffers = Array(nBins) { FloatArray(bins[it].size * 4) }
        binColors = IntArray(nBins) { i ->
            if (!useSpeed) Color.rgb(230, 20, 30) else speedColor(i / (nBins - 1f))
        }
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
            // Rotation de l'écran : on garde le même centre.
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
            canvas.drawText("et une trace GPX avec les boutons du haut.", width / 2f, height / 2f + 12 * density, textPaint)
            return
        }
        if (t == null || t.isEmpty) return
        tmpMatrix.set(traceMatrix)
        tmpMatrix.postConcat(viewMatrix)
        drawTrack(canvas, t, tmpMatrix, traceWidthDp * density, screenPts)
        drawStartFinish(canvas, screenPts, t, 9 * density)
        if (mode == Mode.CALIBRATE) drawCalibration(canvas)
    }

    /** Dessine la trace avec la transformation [toTarget] (local → pixels du canvas). */
    fun drawTrack(canvas: Canvas, t: Track, toTarget: Matrix, widthPx: Float, pts: FloatArray) {
        toTarget.mapPoints(pts, t.local)
        haloPaint.strokeWidth = widthPx * 1.8f
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
        for (k in bins.indices) canvas.drawLines(binBuffers[k], haloPaint)
        for (k in bins.indices) {
            linePaint.color = binColors[k]
            canvas.drawLines(binBuffers[k], linePaint)
        }
    }

    /** Départ = triangle, arrivée = double cercle (symboles de course d'orientation). */
    fun drawStartFinish(canvas: Canvas, pts: FloatArray, t: Track, r: Float) {
        if (t.points.size < 2) return
        markerPaint.strokeWidth = r / 4
        val sx = pts[0]; val sy = pts[1]
        val path = Path()
        for (k in 0..2) {
            val ang = -Math.PI / 2 + k * 2 * Math.PI / 3
            val x = sx + 1.4f * r * cos(ang).toFloat()
            val y = sy + 1.4f * r * sin(ang).toFloat()
            if (k == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }
        path.close()
        canvas.drawPath(path, markerPaint)
        val n = t.points.size - 1
        canvas.drawCircle(pts[2 * n], pts[2 * n + 1], r, markerPaint)
        canvas.drawCircle(pts[2 * n], pts[2 * n + 1], r * 0.6f, markerPaint)
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

    /** Image de la carte avec la trace, à la résolution de la carte. */
    fun renderComposite(): Bitmap? {
        val map = mapBitmap ?: return null
        val t = track
        val out = map.copy(Bitmap.Config.ARGB_8888, true) ?: return null
        if (t != null && !t.isEmpty) {
            val c = Canvas(out)
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
        listener?.onCalibrationStateChanged()
    }

    fun clearCalibration() {
        calibLocal.clear(); calibMap.clear(); pendingTraceIdx = -1
        invalidate()
        listener?.onCalibrationStateChanged()
    }

    private fun applyCalibration() {
        val n = calibLocal.size
        if (n == 0) return
        if (n == 1) {
            // Un seul point : on déplace seulement la trace.
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
        val t = track ?: run { listener?.onMessage("Ouvrez d'abord une trace GPX."); return }
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
        listener?.onCalibrationStateChanged()
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

    override fun onTouchEvent(e: MotionEvent): Boolean {
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                downX = e.x; downY = e.y; tapCandidate = true
                rememberPointers(e)
            }
            MotionEvent.ACTION_POINTER_DOWN -> { tapCandidate = false; rememberPointers(e) }
            MotionEvent.ACTION_POINTER_UP -> rememberPointers(e, e.actionIndex)
            MotionEvent.ACTION_MOVE -> {
                if (tapCandidate && hypot(e.x - downX, e.y - downY) > touchSlop) tapCandidate = false
                if (!tapCandidate) handleMove(e)
            }
            MotionEvent.ACTION_UP -> {
                if (tapCandidate && mode == Mode.CALIBRATE) handleCalibrationTap(e.x, e.y)
                tapCandidate = false
            }
            MotionEvent.ACTION_CANCEL -> tapCandidate = false
        }
        return true
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
            if (!editTrace) {
                s = clampZoom(s)
            }
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
            // trace' = V⁻¹ · D · V · trace
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
        val v = FloatArray(9).also { viewMatrix.getValues(it) }
        val cur = v[Matrix.MSCALE_X]
        val (cw, ch) = contentSize()
        val minScale = 0.3f * min(width / cw, height / ch)
        val maxScale = 12f * density
        return (cur * s).coerceIn(minScale, maxScale) / cur
    }
}
