package com.orienteering.gpxoverlay

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

class FitParserTest {

    /** Petit encodeur FIT pour fabriquer des fichiers de test. */
    private class FitWriter {
        private val body = ByteArrayOutputStream()
        private fun le(n: Int, v: Long) { for (i in 0 until n) body.write(((v shr (8 * i)) and 0xFF).toInt()) }

        fun define(local: Int, global: Int, fields: List<Pair<Int, Int>>) {
            body.write(0x40 or local); body.write(0); body.write(0); le(2, global.toLong())
            body.write(fields.size)
            for ((num, size) in fields) { body.write(num); body.write(size); body.write(if (size == 4) 0x86 else 0x84) }
        }
        fun data(local: Int, values: List<Pair<Int, Long>>) { body.write(local); for ((size, v) in values) le(size, v) }
        fun compressed(local: Int, offset: Int, values: List<Pair<Int, Long>>) {
            body.write(0x80 or (local shl 5) or (offset and 0x1F)); for ((size, v) in values) le(size, v)
        }
        fun bytes(): ByteArray {
            val b = body.toByteArray()
            val h = ByteBuffer.allocate(14).order(ByteOrder.LITTLE_ENDIAN)
            h.put(14); h.put(0x20); h.putShort(2100); h.putInt(b.size); h.put(".FIT".toByteArray()); h.putShort(0)
            return h.array() + b + byteArrayOf(0, 0)
        }
    }

    private fun semi(deg: Double) = (deg / 180.0 * 2147483648.0).toLong() and 0xFFFFFFFFL

    @Test
    fun readsRecordsWithPositionTimeAndAltitude() {
        val fitTs = 1_000_000_000L // secondes depuis 1989-12-31
        val w = FitWriter()
        // Message file_id (n° 0) qui doit être ignoré.
        w.define(0, 0, listOf(0 to 1))
        w.data(0, listOf(1 to 4L))
        w.define(1, 20, listOf(253 to 4, 0 to 4, 1 to 4, 2 to 2, 3 to 1))
        w.data(1, listOf(4 to fitTs, 4 to semi(45.0), 4 to semi(5.0), 2 to ((250 + 500) * 5L), 1 to 152L))
        w.data(1, listOf(4 to fitTs + 10, 4 to semi(45.001), 4 to semi(5.0), 2 to 0xFFFFL, 1 to 0xFFL))
        // Record sans position (capteur seul) : ignoré.
        w.data(1, listOf(4 to fitTs + 20, 4 to 0x7FFFFFFFL, 4 to 0x7FFFFFFFL, 2 to 0xFFFFL, 1 to 150L))
        // Timestamp compressé : (fitTs+20) & ~31 + 30.
        w.define(2, 20, listOf(0 to 4, 1 to 4))
        val base = fitTs + 20
        val off = ((base and 0x1F) + 5).toInt() and 0x1F
        w.compressed(2, off, listOf(4 to semi(45.002), 4 to semi(5.0)))

        val t = FitParser.parse(w.bytes())
        assertEquals(3, t.points.size)
        assertEquals(45.0, t.points[0].lat, 1e-6)
        assertEquals(5.0, t.points[0].lon, 1e-6)
        assertEquals(250.0, t.points[0].ele!!, 1e-6)
        assertNull(t.points[1].ele)
        assertEquals(152, t.points[0].hr)
        assertNull(t.points[1].hr)
        assertEquals((fitTs + 631_065_600L) * 1000, t.points[0].timeMs)
        assertEquals(10_000L, t.points[1].timeMs!! - t.points[0].timeMs!!)
        assertEquals(25_000L, t.points[2].timeMs!! - t.points[0].timeMs!!)
        assertEquals(222.0, t.distanceM, 2.0)
    }

    @Test
    fun trackParserDetectsFit() {
        val w = FitWriter()
        w.define(0, 20, listOf(253 to 4, 0 to 4, 1 to 4))
        w.data(0, listOf(4 to 100L, 4 to semi(1.0), 4 to semi(2.0)))
        w.data(0, listOf(4 to 101L, 4 to semi(1.0001), 4 to semi(2.0)))
        val t = TrackParser.parse(w.bytes().inputStream())
        assertEquals(2, t.points.size)
        assertTrue(t.hasTimes)
    }

    @Test(expected = GpxParser.GpxException::class)
    fun fitWithoutPositionsIsRejected() {
        val w = FitWriter()
        w.define(0, 20, listOf(253 to 4))
        w.data(0, listOf(4 to 100L))
        FitParser.parse(w.bytes())
    }
}
