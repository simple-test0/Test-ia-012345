package com.orienteering.gpxoverlay

import kotlin.math.PI
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

data class TrackPoint(
    val lat: Double,
    val lon: Double,
    val ele: Double? = null,
    val timeMs: Long? = null,
    /** Fréquence cardiaque (battements/min). */
    val hr: Int? = null,
)

/**
 * Une trace GPX projetée dans un repère local en mètres :
 * x vers l'est, y vers le SUD (même sens que les pixels d'une image).
 */
class Track(val name: String?, segments: List<List<TrackPoint>>) {

    val points: List<TrackPoint>
    /** Indice du premier point de chaque segment (+ taille totale à la fin). */
    val segmentStarts: IntArray
    /** Coordonnées locales x0,y0,x1,y1… en mètres. */
    val local: FloatArray
    /** Vitesse (m/s) du tronçon i → i+1, NaN si inconnue. */
    val speeds: FloatArray

    val minX: Float; val maxX: Float; val minY: Float; val maxY: Float
    val distanceM: Double
    val durationMs: Long?
    /** Distance parcourue depuis le premier point (m). */
    val cumDist: DoubleArray
    /** Indices des points horodatés, dans l'ordre. */
    val timedIdx: IntArray
    /** Altitude de chaque point (m), NaN si inconnue. */
    val eles: FloatArray
    /** Fréquence cardiaque de chaque point, NaN si inconnue. */
    val hrs: FloatArray
    /** Dénivelé positif cumulé depuis le début (m). */
    val cumGain: FloatArray
    val gainM: Double
    val lossM: Double
    val avgHr: Double?
    val maxHr: Int?

    init {
        val segs = segments.filter { it.isNotEmpty() }
        points = segs.flatten()
        segmentStarts = IntArray(segs.size + 1)
        var acc = 0
        segs.forEachIndexed { i, s -> segmentStarts[i] = acc; acc += s.size }
        segmentStarts[segs.size] = acc

        val lat0 = if (points.isEmpty()) 0.0 else (points.minOf { it.lat } + points.maxOf { it.lat }) / 2
        val lon0 = if (points.isEmpty()) 0.0 else (points.minOf { it.lon } + points.maxOf { it.lon }) / 2
        val kx = EARTH_R * PI / 180 * cos(lat0 * PI / 180)
        val ky = EARTH_R * PI / 180
        local = FloatArray(points.size * 2)
        var x0 = Float.MAX_VALUE; var x1 = -Float.MAX_VALUE
        var y0 = Float.MAX_VALUE; var y1 = -Float.MAX_VALUE
        points.forEachIndexed { i, p ->
            val x = ((p.lon - lon0) * kx).toFloat()
            val y = (-(p.lat - lat0) * ky).toFloat()
            local[2 * i] = x; local[2 * i + 1] = y
            x0 = min(x0, x); x1 = max(x1, x); y0 = min(y0, y); y1 = max(y1, y)
        }
        if (points.isEmpty()) { x0 = 0f; x1 = 0f; y0 = 0f; y1 = 0f }
        minX = x0; maxX = x1; minY = y0; maxY = y1

        cumDist = DoubleArray(points.size)
        var d = 0.0
        forEachSegment { a, b ->
            if (a < points.size) cumDist[a] = d
            for (i in a until b - 1) {
                d += haversine(points[i], points[i + 1])
                cumDist[i + 1] = d
            }
        }
        distanceM = d

        val timed = ArrayList<Int>()
        var lastT = Long.MIN_VALUE
        points.forEachIndexed { i, p ->
            val t = p.timeMs
            if (t != null && t >= lastT) { timed.add(i); lastT = t }
        }
        timedIdx = timed.toIntArray()

        eles = FloatArray(points.size) { points[it].ele?.toFloat() ?: Float.NaN }
        hrs = FloatArray(points.size) { i -> points[i].hr?.takeIf { it in 25..250 }?.toFloat() ?: Float.NaN }

        // Dénivelé avec hystérésis de 3 m : on ignore les petites oscillations de l'altitude GPS.
        cumGain = FloatArray(points.size)
        var gain = 0.0
        var loss = 0.0
        var ref = Float.NaN
        for (i in points.indices) {
            val e = eles[i]
            if (!e.isNaN()) {
                if (ref.isNaN()) ref = e
                else if (e - ref >= 3f) { gain += e - ref; ref = e }
                else if (ref - e >= 3f) { loss += ref - e; ref = e }
            }
            cumGain[i] = gain.toFloat()
        }
        gainM = gain
        lossM = loss

        val validHr = hrs.filter { !it.isNaN() }
        avgHr = if (validHr.isEmpty()) null else validHr.average()
        maxHr = validHr.maxOrNull()?.toInt()

        val t0 = points.firstOrNull { it.timeMs != null }?.timeMs
        val t1 = points.lastOrNull { it.timeMs != null }?.timeMs
        durationMs = if (t0 != null && t1 != null && t1 > t0) t1 - t0 else null

        speeds = FloatArray(points.size) { Float.NaN }
        // Vitesse lissée sur une fenêtre de quelques points pour limiter le bruit GPS.
        val k = 3
        forEachSegment { a, b ->
            for (i in a until b - 1) {
                val lo = max(a, i - k)
                val hi = min(b - 1, i + 1 + k)
                val ta = points[lo].timeMs
                val tb = points[hi].timeMs
                if (ta == null || tb == null || tb <= ta) continue
                var dist = 0.0
                for (j in lo until hi) dist += haversine(points[j], points[j + 1])
                speeds[i] = (dist / ((tb - ta) / 1000.0)).toFloat()
            }
        }
    }

    val startTimeMs: Long? get() = timedIdx.firstOrNull()?.let { points[it].timeMs }
    val endTimeMs: Long? get() = timedIdx.lastOrNull()?.let { points[it].timeMs }

    /**
     * Position à l'instant [t] (interpolée entre deux points horodatés).
     * Écrit x,y locaux dans [out] et renvoie l'indice du point juste avant, ou -1.
     */
    fun positionAt(t: Long, out: FloatArray): Int {
        if (timedIdx.isEmpty()) return -1
        var lo = 0
        var hi = timedIdx.size - 1
        if (t <= points[timedIdx[0]].timeMs!!) hi = 0
        else if (t >= points[timedIdx[hi]].timeMs!!) lo = hi
        else {
            while (hi - lo > 1) {
                val mid = (lo + hi) / 2
                if (points[timedIdx[mid]].timeMs!! <= t) lo = mid else hi = mid
            }
        }
        val ia = timedIdx[lo]
        val ib = timedIdx[hi]
        val ta = points[ia].timeMs!!
        val tb = points[ib].timeMs!!
        val f = if (tb > ta) ((t - ta).toDouble() / (tb - ta)).toFloat().coerceIn(0f, 1f) else 0f
        out[0] = local[2 * ia] + (local[2 * ib] - local[2 * ia]) * f
        out[1] = local[2 * ia + 1] + (local[2 * ib + 1] - local[2 * ia + 1]) * f
        return ia
    }

    val isEmpty: Boolean get() = points.isEmpty()
    val hasHr: Boolean get() = avgHr != null
    val hasEle: Boolean get() = eles.count { !it.isNaN() } >= 2

    /** Fréquence cardiaque moyenne entre deux points, ou null. */
    fun avgHrBetween(from: Int, to: Int): Double? {
        var sum = 0.0
        var n = 0
        for (i in from..to.coerceAtMost(points.size - 1)) {
            val h = hrs[i]
            if (!h.isNaN()) { sum += h; n++ }
        }
        return if (n == 0) null else sum / n
    }

    /** Dénivelé positif entre deux points (m). */
    fun gainBetween(from: Int, to: Int): Double = (cumGain[to] - cumGain[from]).toDouble()
    val hasTimes: Boolean get() = speeds.any { !it.isNaN() }

    inline fun forEachSegment(block: (start: Int, end: Int) -> Unit) {
        for (s in 0 until segmentStarts.size - 1) block(segmentStarts[s], segmentStarts[s + 1])
    }

    /** Allure moyenne en secondes par km, ou null. */
    val paceSecPerKm: Double?
        get() = durationMs?.let { if (distanceM > 10) it / 1000.0 / (distanceM / 1000.0) else null }

    companion object {
        const val EARTH_R = 6_371_000.0

        fun haversine(p: TrackPoint, q: TrackPoint): Double {
            val dLat = (q.lat - p.lat) * PI / 180
            val dLon = (q.lon - p.lon) * PI / 180
            val h = sin(dLat / 2).let { it * it } +
                cos(p.lat * PI / 180) * cos(q.lat * PI / 180) * sin(dLon / 2).let { it * it }
            return 2 * EARTH_R * asin(sqrt(min(1.0, h)))
        }
    }
}
