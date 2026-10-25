package com.orienteering.gpxoverlay

import kotlin.math.hypot

/** Passage détecté à un poste : point de la trace le plus proche lors du passage. */
data class Punch(val pointIndex: Int, val timeMs: Long?, val distanceM: Double, val sure: Boolean)

/** Une section entre deux postes consécutifs. */
data class Leg(
    val from: Int,
    val to: Int,
    val fromIdx: Int,
    val toIdx: Int,
    val timeMs: Long?,
    /** Distance réellement parcourue (m). */
    val runM: Double,
    /** Distance à vol d'oiseau entre les postes (m). */
    val straightM: Double,
    val sure: Boolean,
) {
    /** Allure en secondes par km, ou null. */
    val paceSecPerKm: Double? get() = timeMs?.let { if (runM > 1) it / 1000.0 / (runM / 1000.0) else null }
    /** Distance en plus par rapport à la ligne droite, en %. */
    val extraPercent: Double get() = if (straightM > 1) (runM / straightM - 1) * 100 else 0.0
}

object Splits {

    /** Rayon autour d'un poste dans lequel on considère qu'on y est passé (erreur GPS comprise). */
    const val DEFAULT_RADIUS_M = 30.0

    /**
     * Détecte le passage à chaque poste, dans l'ordre.
     * [controls] = positions des postes dans le repère local de la trace (x0,y0,x1,y1… en mètres).
     */
    fun punches(track: Track, controls: DoubleArray, radiusM: Double = DEFAULT_RADIUS_M): List<Punch> {
        val n = track.points.size
        val count = controls.size / 2
        if (n == 0 || count == 0) return emptyList()
        val result = ArrayList<Punch>(count)
        var from = 0
        for (k in 0 until count) {
            val p = findPassage(track, controls[2 * k], controls[2 * k + 1], from, radiusM)
            result.add(p)
            from = p.pointIndex
        }
        // Départ : on garde le DERNIER passage dans le cercle du triangle avant le poste suivant
        // (on tourne souvent autour du départ avant de partir), et le point le plus proche de ce passage.
        if (count >= 2 && result[0].sure) {
            val cx = controls[0]; val cy = controls[1]
            var best = result[0].pointIndex
            var bestD = Double.MAX_VALUE
            var inside = false
            for (i in result[0].pointIndex..result[1].pointIndex) {
                val d = dist(track, i, cx, cy)
                if (d <= radiusM) {
                    if (!inside) { inside = true; bestD = Double.MAX_VALUE }
                    if (d < bestD) { bestD = d; best = i }
                } else inside = false
            }
            result[0] = punchAt(track, best, cx, cy, true)
        }
        return result
    }

    private fun dist(t: Track, i: Int, x: Double, y: Double) =
        hypot(t.local[2 * i] - x, t.local[2 * i + 1] - y)

    private fun punchAt(t: Track, i: Int, x: Double, y: Double, sure: Boolean) =
        Punch(i, t.points[i].timeMs, dist(t, i, x, y), sure)

    private fun findPassage(t: Track, x: Double, y: Double, from: Int, radiusM: Double): Punch {
        val n = t.points.size
        var i = from
        while (i < n && dist(t, i, x, y) > radiusM) i++
        if (i < n) {
            // Point le plus proche pendant ce passage dans le cercle.
            var best = i
            var bestD = dist(t, i, x, y)
            var j = i + 1
            while (j < n) {
                val d = dist(t, j, x, y)
                if (d > radiusM) break
                if (d < bestD) { bestD = d; best = j }
                j++
            }
            return punchAt(t, best, x, y, true)
        }
        // Jamais passé dans le cercle : point le plus proche, signalé comme incertain.
        var best = from
        var bestD = Double.MAX_VALUE
        for (k in from until n) {
            val d = dist(t, k, x, y)
            if (d < bestD) { bestD = d; best = k }
        }
        return punchAt(t, best, x, y, false)
    }

    fun legs(track: Track, controls: DoubleArray, punches: List<Punch>): List<Leg> {
        val legs = ArrayList<Leg>()
        for (k in 1 until punches.size) {
            val a = punches[k - 1]
            val b = punches[k]
            val time = if (a.timeMs != null && b.timeMs != null && b.timeMs >= a.timeMs) b.timeMs - a.timeMs else null
            legs.add(
                Leg(
                    from = k - 1, to = k,
                    fromIdx = a.pointIndex, toIdx = b.pointIndex,
                    timeMs = time,
                    runM = track.cumDist[b.pointIndex] - track.cumDist[a.pointIndex],
                    straightM = hypot(controls[2 * k] - controls[2 * k - 2], controls[2 * k + 1] - controls[2 * k - 1]),
                    sure = a.sure && b.sure,
                )
            )
        }
        return legs
    }

    /** Nom d'un poste : « Départ », « 1 », « 2 »… « Arrivée ». */
    fun label(index: Int, count: Int): String = when {
        index == 0 -> "Départ"
        index == count - 1 && count >= 2 -> "Arrivée"
        else -> index.toString()
    }
}
