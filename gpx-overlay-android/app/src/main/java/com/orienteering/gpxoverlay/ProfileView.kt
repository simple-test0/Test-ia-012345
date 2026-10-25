package com.orienteering.gpxoverlay

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.Path
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View
import java.util.Locale
import kotlin.math.max

/**
 * Profil de la course en fonction de la distance : allure, altitude ou fréquence cardiaque.
 * Un curseur suit le replay ; toucher ou glisser sur le graphique choisit un point.
 */
class ProfileView(context: Context, attrs: AttributeSet? = null) : View(context, attrs) {

    enum class Metric { PACE, ELEVATION, HEART_RATE }

    var track: Track? = null
        set(value) { field = value; rebuild() }
    var metric = Metric.PACE
        set(value) { field = value; rebuild() }
    /** Point de la trace sous le curseur, ou -1. */
    var cursorIndex = -1
        set(value) { if (field != value) { field = value; invalidate() } }
    /** Indices des passages aux postes (traits verticaux). */
    var punchIndices = IntArray(0)
        set(value) { field = value; invalidate() }

    /** Appelé quand l'utilisateur touche le graphique (indice du point de la trace). */
    var onPick: ((Int) -> Unit)? = null

    private val density = resources.displayMetrics.density
    private val padL = 40 * density
    private val padR = 8 * density
    private val padT = 8 * density
    private val padB = 16 * density

    private val linePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 2 * density; strokeJoin = Paint.Join.ROUND
    }
    private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val gridPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.rgb(227, 229, 234); strokeWidth = density
    }
    private val punchPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.argb(140, 166, 38, 255); strokeWidth = density
        pathEffect = DashPathEffect(floatArrayOf(4 * density, 3 * density), 0f)
    }
    private val cursorPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = OverlayView.HIGHLIGHT; strokeWidth = 2 * density
    }
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.rgb(107, 114, 128); textSize = 10.5f * density
    }

    /** Valeur affichée pour chaque point (NaN = pas de donnée). */
    private var values = FloatArray(0)
    private var vMin = 0f
    private var vMax = 1f
    private var maxDist = 1.0
    private val line = Path()
    private val area = Path()

    val hasData: Boolean get() = values.any { !it.isNaN() }

    private fun valueOf(t: Track, i: Int): Float = when (metric) {
        // Allure en s/km (vitesse lissée), bornée pour ignorer les arrêts.
        Metric.PACE -> t.speeds.getOrElse(i) { Float.NaN }.let { s ->
            if (s.isNaN() || s < 0.3f) Float.NaN else (1000f / s).coerceIn(120f, 1500f)
        }
        Metric.ELEVATION -> t.eles[i]
        Metric.HEART_RATE -> t.hrs[i]
    }

    private fun rebuild() {
        val t = track
        if (t == null || t.points.size < 2) { values = FloatArray(0); invalidate(); return }
        val n = t.points.size
        values = FloatArray(n) { valueOf(t, it) }
        // L'allure du dernier point n'existe pas : on reprend celle du précédent.
        if (metric == Metric.PACE && n >= 2 && values[n - 1].isNaN()) values[n - 1] = values[n - 2]
        val sorted = values.filter { !it.isNaN() }.sorted()
        if (sorted.isEmpty()) { invalidate(); return }
        val q = if (metric == Metric.ELEVATION) 0.0 else 0.02
        vMin = sorted[(sorted.size * q).toInt().coerceIn(0, sorted.size - 1)]
        vMax = sorted[(sorted.size * (1 - q)).toInt().coerceIn(0, sorted.size - 1)]
        val span = max(vMax - vMin, if (metric == Metric.PACE) 30f else 5f)
        vMin -= span * 0.08f; vMax = vMin + span * 1.16f
        if (metric == Metric.PACE) { vMin = vMin.coerceAtLeast(110f); vMax = vMax.coerceAtMost(1520f) }
        if (metric == Metric.HEART_RATE) vMin = vMin.coerceAtLeast(30f)
        maxDist = max(t.distanceM, 1.0)
        buildPaths()
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        buildPaths()
    }

    private fun xOf(i: Int): Float {
        val t = track ?: return padL
        return padL + ((t.cumDist[i] / maxDist) * (width - padL - padR)).toFloat()
    }

    /** Allure : plus rapide en haut. Autres : plus haut = valeur plus grande. */
    private fun yOf(v: Float): Float {
        val f = ((v - vMin) / (vMax - vMin)).coerceIn(0f, 1f)
        val h = height - padT - padB
        return if (metric == Metric.PACE) padT + f * h else padT + (1 - f) * h
    }

    private fun buildPaths() {
        line.reset(); area.reset()
        val t = track ?: return
        if (width == 0 || values.isEmpty()) { invalidate(); return }
        // Un point moyen par pixel : le tracé reste léger même pour de longues traces.
        val cols = max(1, (width - padL - padR).toInt())
        val sum = DoubleArray(cols); val cnt = IntArray(cols)
        for (i in values.indices) {
            val v = values[i]
            if (v.isNaN()) continue
            val c = (((t.cumDist[i] / maxDist) * (cols - 1)).toInt()).coerceIn(0, cols - 1)
            sum[c] += v; cnt[c]++
        }
        val base = height - padB
        var started = false
        var firstX = 0f; var lastX = 0f
        for (c in 0 until cols) {
            if (cnt[c] == 0) continue
            val x = padL + c.toFloat()
            val y = yOf((sum[c] / cnt[c]).toFloat())
            if (!started) { line.moveTo(x, y); area.moveTo(x, base); area.lineTo(x, y); firstX = x; started = true }
            else { line.lineTo(x, y); area.lineTo(x, y) }
            lastX = x
        }
        if (started) { area.lineTo(lastX, base); area.lineTo(firstX, base); area.close() }
        invalidate()
    }

    private fun color(): Int = when (metric) {
        Metric.PACE -> Color.rgb(242, 101, 34)
        Metric.ELEVATION -> Color.rgb(120, 85, 50)
        Metric.HEART_RATE -> Color.rgb(220, 38, 38)
    }

    fun format(v: Float): String = when (metric) {
        Metric.PACE -> String.format(Locale.FRANCE, "%d'%02d", v.toInt() / 60, v.toInt() % 60)
        Metric.ELEVATION -> String.format(Locale.FRANCE, "%d m", v.toInt())
        Metric.HEART_RATE -> String.format(Locale.FRANCE, "%d", v.toInt())
    }

    override fun onDraw(canvas: Canvas) {
        val t = track
        if (t == null || !hasData) {
            textPaint.textAlign = Paint.Align.CENTER
            canvas.drawText(
                when (metric) {
                    Metric.PACE -> "Pas d'horaires dans cette trace"
                    Metric.ELEVATION -> "Pas d'altitude dans cette trace"
                    Metric.HEART_RATE -> "Pas de fréquence cardiaque dans cette trace"
                },
                width / 2f, height / 2f, textPaint
            )
            return
        }
        val top = padT; val bottom = height - padB
        canvas.drawLine(padL, top, width - padR, top, gridPaint)
        canvas.drawLine(padL, (top + bottom) / 2, width - padR, (top + bottom) / 2, gridPaint)
        canvas.drawLine(padL, bottom, width - padR, bottom, gridPaint)
        // Étiquettes de l'axe vertical (haut / bas).
        textPaint.textAlign = Paint.Align.RIGHT
        val vTop = if (metric == Metric.PACE) vMin else vMax
        val vBot = if (metric == Metric.PACE) vMax else vMin
        canvas.drawText(format(vTop), padL - 4 * density, top + textPaint.textSize * 0.8f, textPaint)
        canvas.drawText(format(vBot), padL - 4 * density, bottom, textPaint)
        // Distance totale en bas à droite.
        textPaint.textAlign = Paint.Align.RIGHT
        canvas.drawText(String.format(Locale.FRANCE, "%.1f km", maxDist / 1000), width - padR, height - 2 * density, textPaint)
        textPaint.textAlign = Paint.Align.LEFT
        canvas.drawText("0", padL, height - 2 * density, textPaint)

        for (p in punchIndices) if (p in values.indices) {
            val x = xOf(p)
            canvas.drawLine(x, top, x, bottom, punchPaint)
        }
        val c = color()
        fillPaint.color = Color.argb(45, Color.red(c), Color.green(c), Color.blue(c))
        canvas.drawPath(area, fillPaint)
        linePaint.color = c
        canvas.drawPath(line, linePaint)

        val ci = cursorIndex
        if (ci in values.indices) {
            val x = xOf(ci)
            canvas.drawLine(x, top, x, bottom, cursorPaint)
            val v = values[ci]
            if (!v.isNaN()) {
                fillPaint.color = Color.WHITE
                canvas.drawCircle(x, yOf(v), 5 * density, fillPaint)
                fillPaint.color = OverlayView.HIGHLIGHT
                canvas.drawCircle(x, yOf(v), 3.5f * density, fillPaint)
            }
        }
    }

    /** Valeur au point [i], ou NaN. */
    fun valueAt(i: Int): Float = values.getOrElse(i) { Float.NaN }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        val t = track ?: return false
        if (values.isEmpty()) return false
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN, MotionEvent.ACTION_MOVE -> {
                parent?.requestDisallowInterceptTouchEvent(true)
                val f = ((e.x - padL) / (width - padL - padR)).coerceIn(0f, 1f)
                val target = f * maxDist
                // Recherche du point le plus proche en distance (cumDist est croissante).
                var lo = 0; var hi = t.points.size - 1
                while (hi - lo > 1) {
                    val mid = (lo + hi) / 2
                    if (t.cumDist[mid] < target) lo = mid else hi = mid
                }
                val i = if (target - t.cumDist[lo] < t.cumDist[hi] - target) lo else hi
                cursorIndex = i
                onPick?.invoke(i)
                return true
            }
        }
        return true
    }

}
