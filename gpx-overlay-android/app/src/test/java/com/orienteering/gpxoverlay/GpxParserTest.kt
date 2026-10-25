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
}
