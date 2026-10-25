package com.orienteering.gpxoverlay

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SplitsTest {

    /** Trace vers l'est le long de l'équateur : 1 point toutes les 10 s, ~11 m entre points. */
    private fun eastTrack(n: Int, extraBefore: List<Pair<Double, Double>> = emptyList()): Track {
        val pts = ArrayList<TrackPoint>()
        var t = 0L
        for ((lat, lon) in extraBefore) { pts.add(TrackPoint(lat, lon, null, t)); t += 10_000 }
        for (i in 0 until n) { pts.add(TrackPoint(0.0, i * 0.0001, null, t)); t += 10_000 }
        return Track(null, listOf(pts))
    }

    private fun localOf(t: Track, i: Int) = doubleArrayOf(t.local[2 * i].toDouble(), t.local[2 * i + 1].toDouble())

    @Test
    fun detectsPassagesInOrder() {
        val t = eastTrack(100)
        val controls = localOf(t, 0) + localOf(t, 40) + localOf(t, 99)
        val p = Splits.punches(t, controls)
        assertEquals(listOf(0, 40, 99), p.map { it.pointIndex })
        assertTrue(p.all { it.sure })
        val legs = Splits.legs(t, controls, p)
        assertEquals(2, legs.size)
        assertEquals(400_000L, legs[0].timeMs)
        assertEquals(legs[0].straightM, legs[0].runM, 1.0)
        assertEquals(0.0, legs[0].extraPercent, 0.5)
        // ~11,1 m par 10 s → ~15 min/km
        assertEquals(900.0, legs[0].paceSecPerKm!!, 10.0)
    }

    @Test
    fun startUsesLastPassageNearTriangle() {
        // Passage au départ, petit tour à 100 m à l'ouest, retour au départ puis course vers l'est.
        val before = listOf(0.0 to 0.0, 0.0 to -0.0005, 0.0 to -0.001, 0.0 to -0.0005)
        val t = eastTrack(50, extraBefore = before)
        val controls = localOf(t, 4) + localOf(t, 40)
        val p = Splits.punches(t, controls)
        assertEquals(4, p[0].pointIndex)
        assertEquals(40, p[1].pointIndex)
    }

    @Test
    fun missedControlIsFlagged() {
        val t = eastTrack(60)
        val far = localOf(t, 30).also { it[1] += 200.0 } // 200 m au sud de la trace
        val controls = localOf(t, 0) + far + localOf(t, 59)
        val p = Splits.punches(t, controls)
        assertFalse(p[1].sure)
        assertEquals(30, p[1].pointIndex)
        assertTrue(p[2].sure)
        assertFalse(Splits.legs(t, controls, p)[0].sure)
    }

    @Test
    fun labels() {
        assertEquals("Départ", Splits.label(0, 4))
        assertEquals("2", Splits.label(2, 4))
        assertEquals("Arrivée", Splits.label(3, 4))
    }
}
