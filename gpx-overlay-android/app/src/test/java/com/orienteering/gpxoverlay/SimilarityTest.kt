package com.orienteering.gpxoverlay

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SimilarityTest {

    @Test
    fun recoversKnownTransform() {
        val truth = Similarity(a = 2.0 * Math.cos(0.3), b = 2.0 * Math.sin(0.3), tx = 100.0, ty = -50.0)
        val src = doubleArrayOf(0.0, 0.0, 10.0, 0.0, 0.0, 20.0, -5.0, 7.0)
        val dst = DoubleArray(src.size)
        for (i in 0 until src.size / 2) {
            dst[2 * i] = truth.applyX(src[2 * i], src[2 * i + 1])
            dst[2 * i + 1] = truth.applyY(src[2 * i], src[2 * i + 1])
        }
        val fit = Similarity.fit(src, dst)!!
        assertEquals(2.0, fit.scale, 1e-9)
        assertEquals(Math.toDegrees(0.3), fit.rotationDeg, 1e-9)
        assertEquals(100.0, fit.tx, 1e-9)
        assertEquals(-50.0, fit.ty, 1e-9)
    }

    @Test
    fun twoPointsAreMatchedExactly() {
        val fit = Similarity.fit(doubleArrayOf(0.0, 0.0, 1.0, 0.0), doubleArrayOf(5.0, 5.0, 5.0, 8.0))!!
        assertEquals(5.0, fit.applyX(0.0, 0.0), 1e-9)
        assertEquals(5.0, fit.applyY(0.0, 0.0), 1e-9)
        assertEquals(5.0, fit.applyX(1.0, 0.0), 1e-9)
        assertEquals(8.0, fit.applyY(1.0, 0.0), 1e-9)
        assertEquals(90.0, fit.rotationDeg, 1e-9)
    }

    @Test
    fun needsTwoDistinctPoints() {
        assertNull(Similarity.fit(doubleArrayOf(1.0, 1.0), doubleArrayOf(2.0, 2.0)))
        assertNull(Similarity.fit(doubleArrayOf(1.0, 1.0, 1.0, 1.0), doubleArrayOf(2.0, 2.0, 3.0, 3.0)))
    }
}
