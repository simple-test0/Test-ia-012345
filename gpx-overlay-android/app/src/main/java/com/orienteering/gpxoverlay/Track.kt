package com.orienteering.gpxoverlay

import kotlin.math.PI
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

data class TrackPoint(val lat: Double, val lon: Double, val ele: Double? = null, val timeMs: Long? = null)

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

        var d = 0.0
        forEachSegment { a, b -> for (i in a until b - 1) d += haversine(points[i], points[i + 1]) }
        distanceM = d

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

    val isEmpty: Boolean get() = points.isEmpty()
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
