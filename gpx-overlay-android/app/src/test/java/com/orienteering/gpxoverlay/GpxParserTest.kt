package com.orienteering.gpxoverlay

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class GpxParserTest {

    private fun parse(xml: String) = GpxParser.parse(xml.byteInputStream())

    @Test
    fun readsTrackPointsWithTimesAndSegments() {
        val t = parse(
            """<?xml version="1.0"?>
            <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
              <metadata><name>Course</name></metadata>
              <trk><name>Ma trace</name>
                <trkseg>
                  <trkpt lat="45.0000" lon="5.0000"><ele>200</ele><time>2024-05-01T10:00:00Z</time></trkpt>
                  <trkpt lat="45.0009" lon="5.0000"><time>2024-05-01T10:00:30Z</time></trkpt>
                </trkseg>
                <trkseg>
                  <trkpt lon="5.001" lat="45.001"><time>2024-05-01T10:01:00+00:00</time></trkpt>
                </trkseg>
              </trk>
            </gpx>"""
        )
        assertEquals("Course", t.name)
        assertEquals(3, t.points.size)
        assertEquals(3, t.segmentStarts.size)
        assertEquals(200.0, t.points[0].ele!!, 1e-9)
        assertEquals(60_000L, t.durationMs)
        // 0,0009° de latitude ≈ 100 m
        assertEquals(100.0, t.distanceM, 1.0)
        assertTrue(t.hasTimes)
        // Le nord est vers le haut : le 2e point a un y plus petit.
        assertTrue(t.local[3] < t.local[1])
    }

    @Test
    fun fallsBackToRoutePointsAndHandlesPrefixes() {
        val t = parse(
            """<g:gpx xmlns:g="http://www.topografix.com/GPX/1/0">
                 <g:rte><g:rtept lat="1" lon="2"/><g:rtept lat="1.001" lon="2.001"/></g:rte>
               </g:gpx>"""
        )
        assertEquals(2, t.points.size)
        assertNull(t.durationMs)
    }

    @Test(expected = GpxParser.GpxException::class)
    fun rejectsFileWithoutPoints() {
        parse("<gpx><wpt lat=\"1\" lon=\"2\"/></gpx>")
    }

    @Test
    fun parsesTimeFormats() {
        assertNotNull(GpxParser.parseTime("2024-05-01T10:00:00.123Z"))
        assertNotNull(GpxParser.parseTime("2024-05-01T12:00:00+02:00"))
        assertEquals(GpxParser.parseTime("2024-05-01T10:00:00Z"), GpxParser.parseTime("2024-05-01T12:00:00+02:00"))
        assertNotNull(GpxParser.parseTime("2024-05-01T10:00:00"))
        assertNull(GpxParser.parseTime("n'importe quoi"))
    }

    @Test
    fun readsTcx() {
        val t = TrackParser.parse(
            """<?xml version="1.0"?>
            <TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
              <Activities><Activity Sport="Running"><Id>2024-05-01T10:00:00Z</Id>
                <Lap StartTime="2024-05-01T10:00:00Z"><Track>
                  <Trackpoint><Time>2024-05-01T10:00:00Z</Time>
                    <Position><LatitudeDegrees>45.0</LatitudeDegrees><LongitudeDegrees>5.0</LongitudeDegrees></Position>
                    <AltitudeMeters>300</AltitudeMeters><HeartRateBpm><Value>150</Value></HeartRateBpm></Trackpoint>
                  <Trackpoint><Time>2024-05-01T10:00:05Z</Time><HeartRateBpm><Value>151</Value></HeartRateBpm></Trackpoint>
                  <Trackpoint><Time>2024-05-01T10:00:10Z</Time>
                    <Position><LatitudeDegrees>45.0009</LatitudeDegrees><LongitudeDegrees>5.0</LongitudeDegrees></Position></Trackpoint>
                </Track></Lap>
              </Activity></Activities>
            </TrainingCenterDatabase>""".byteInputStream()
        )
        assertEquals(2, t.points.size)
        assertEquals(300.0, t.points[0].ele!!, 1e-9)
        assertEquals(150, t.points[0].hr)
        assertEquals(10_000L, t.durationMs)
        assertEquals(100.0, t.distanceM, 1.0)
    }

    @Test
    fun positionAtInterpolates() {
        val t = parse(
            """<gpx><trk><trkseg>
              <trkpt lat="45.0" lon="5.0"><time>2024-05-01T10:00:00Z</time></trkpt>
              <trkpt lat="45.0009" lon="5.0"><time>2024-05-01T10:00:10Z</time></trkpt>
            </trkseg></trk></gpx>"""
        )
        val out = FloatArray(2)
        val i = t.positionAt(t.startTimeMs!! + 5_000, out)
        assertEquals(0, i)
        assertEquals((t.local[1] + t.local[3]) / 2, out[1], 0.01f)
        // Avant le début / après la fin : on reste aux extrémités.
        t.positionAt(0, out); assertEquals(t.local[1], out[1], 0.01f)
        t.positionAt(Long.MAX_VALUE, out); assertEquals(t.local[3], out[1], 0.01f)
    }

    @Test
    fun readsGarminGpxExtensions() {
        val t = parse(
            """<gpx xmlns="http://www.topografix.com/GPX/1/1"
                   xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">
              <trk><trkseg>
                <trkpt lat="45.0" lon="5.0"><ele>200</ele><time>2024-05-01T10:00:00Z</time>
                  <extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>140</gpxtpx:hr><gpxtpx:cad>85</gpxtpx:cad></gpxtpx:TrackPointExtension></extensions></trkpt>
                <trkpt lat="45.0005" lon="5.0"><ele>210</ele><time>2024-05-01T10:00:20Z</time>
                  <extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>160</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions></trkpt>
                <trkpt lat="45.001" lon="5.0"><ele>205</ele><time>2024-05-01T10:00:40Z</time></trkpt>
                <trkpt lat="45.0015" lon="5.0"><ele>230</ele><time>2024-05-01T10:01:00Z</time></trkpt>
              </trkseg></trk></gpx>"""
        )
        assertEquals(140, t.points[0].hr)
        assertEquals(160, t.points[1].hr)
        assertNull(t.points[2].hr)
        assertTrue(t.hasHr)
        assertEquals(150.0, t.avgHr!!, 1e-9)
        assertEquals(160, t.maxHr)
        // 200 → 210 (+10), 210 → 205 (-5), 205 → 230 (+25)
        assertEquals(35.0, t.gainM, 1e-6)
        assertEquals(5.0, t.lossM, 1e-6)
        assertEquals(150.0, t.avgHrBetween(0, 3)!!, 1e-9)
        assertEquals(10.0, t.gainBetween(0, 1), 1e-6)
    }

    @Test
    fun smallElevationNoiseIsIgnored() {
        val pts = (0 until 50).map { TrackPoint(45.0 + it * 0.0001, 5.0, 100.0 + (it % 2) * 2.0, null) }
        val t = Track(null, listOf(pts))
        assertEquals(0.0, t.gainM, 1e-6)
    }

    @Test
    fun readsTrackInsideGarminZip() {
        val gpx = """<gpx><trk><trkseg>
              <trkpt lat="45.0" lon="5.0"><time>2024-05-01T10:00:00Z</time></trkpt>
              <trkpt lat="45.001" lon="5.0"><time>2024-05-01T10:01:00Z</time></trkpt>
            </trkseg></trk></gpx>""".toByteArray()
        val bos = java.io.ByteArrayOutputStream()
        java.util.zip.ZipOutputStream(bos).use { z ->
            z.putNextEntry(java.util.zip.ZipEntry("lisez-moi.txt")); z.write("x".toByteArray()); z.closeEntry()
            z.putNextEntry(java.util.zip.ZipEntry("12345_ACTIVITY.gpx")); z.write(gpx); z.closeEntry()
        }
        val t = TrackParser.parse(bos.toByteArray().inputStream())
        assertEquals(2, t.points.size)
    }

    @Test
    fun xxeIsRefused() {
        val xml = """<?xml version="1.0"?>
            <!DOCTYPE gpx [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]>
            <gpx><trk><name>&xxe;</name><trkseg>
              <trkpt lat="45.0" lon="5.0"/><trkpt lat="45.001" lon="5.0"/>
            </trkseg></trk></gpx>"""
        val e = runCatching { parse(xml) }.exceptionOrNull()
        assertTrue(e is GpxParser.GpxException)
        assertTrue(e!!.message!!.contains("DOCTYPE"))
    }

    @Test
    fun entityExpansionIsRefused() {
        val xml = """<?xml version="1.0"?>
            <!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>
            <gpx><trk><name>&lol2;</name></trk></gpx>"""
        assertTrue(runCatching { parse(xml) }.exceptionOrNull() is GpxParser.GpxException)
        // Même en UTF-16 (octets nuls entre les caractères).
        assertTrue(GpxParser.hasDoctype(xml.toByteArray(Charsets.UTF_16LE)))
    }

    @Test
    fun oversizedInputIsRefused() {
        val big = java.io.ByteArrayInputStream(ByteArray(2 * 1024 * 1024))
        val e = runCatching { TrackParser.readLimited(big, 1024 * 1024) }.exceptionOrNull()
        assertTrue(e is GpxParser.GpxException)
    }
}
