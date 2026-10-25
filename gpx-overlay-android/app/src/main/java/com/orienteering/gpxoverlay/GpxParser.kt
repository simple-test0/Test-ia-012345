package com.orienteering.gpxoverlay

import org.xml.sax.Attributes
import org.xml.sax.helpers.DefaultHandler
import java.io.InputStream
import java.time.Instant
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneOffset
import javax.xml.parsers.SAXParserFactory

/**
 * Lecture d'un fichier XML de trace :
 *  - GPX : points de trace (trkpt), ou à défaut points de route (rtept) ;
 *  - TCX (Garmin Training Center) : Trackpoint.
 */
object GpxParser {

    class GpxException(msg: String) : Exception(msg)

    fun parse(input: InputStream): Track {
        val factory = SAXParserFactory.newInstance()
        factory.isNamespaceAware = true
        for (f in listOf(
            "http://xml.org/sax/features/external-general-entities",
            "http://xml.org/sax/features/external-parameter-entities",
        )) {
            try { factory.setFeature(f, false) } catch (_: Exception) { }
        }
        val handler = Handler()
        try {
            factory.newSAXParser().parse(input, handler)
        } catch (e: Exception) {
            throw GpxException("Fichier de trace illisible : ${e.message}")
        }
        val segments = handler.trackSegments.filter { it.isNotEmpty() }
            .ifEmpty { handler.routes.filter { it.isNotEmpty() } }
        if (segments.isEmpty()) throw GpxException("Aucun point de trace avec position GPS dans ce fichier.")
        return Track(handler.name, segments)
    }

    fun parseTime(s: String): Long? {
        val t = s.trim()
        if (t.isEmpty()) return null
        return try { Instant.parse(t).toEpochMilli() } catch (_: Exception) {
            try { OffsetDateTime.parse(t).toInstant().toEpochMilli() } catch (_: Exception) {
                try { LocalDateTime.parse(t).toInstant(ZoneOffset.UTC).toEpochMilli() } catch (_: Exception) { null }
            }
        }
    }

    private class Handler : DefaultHandler() {
        val trackSegments = mutableListOf<MutableList<TrackPoint>>()
        val routes = mutableListOf<MutableList<TrackPoint>>()
        var name: String? = null

        private var current: MutableList<TrackPoint>? = null
        private var lat = 0.0
        private var lon = 0.0
        private var ele: Double? = null
        private var time: Long? = null
        private var hr: Int? = null
        private var inPoint = false
        private var tcxPoint = false
        private var inHeartRate = false
        private var depth = 0
        private var pointDepth = 0
        private val text = StringBuilder()

        private fun local(localName: String?, qName: String?): String =
            (localName?.takeIf { it.isNotEmpty() } ?: qName?.substringAfter(':') ?: "").lowercase()

        override fun startElement(uri: String?, localName: String?, qName: String?, attrs: Attributes) {
            depth++
            text.setLength(0)
            when (local(localName, qName)) {
                "trkseg", "track" -> { current = mutableListOf<TrackPoint>().also { trackSegments.add(it) } }
                "heartratebpm" -> inHeartRate = true
                "trackpoint" -> {
                    lat = Double.NaN; lon = Double.NaN; ele = null; time = null; hr = null
                    inPoint = true; tcxPoint = true; pointDepth = depth
                }
                "rte" -> { current = mutableListOf<TrackPoint>().also { routes.add(it) } }
                "trkpt", "rtept" -> {
                    val la = attrs.getValue("lat")?.toDoubleOrNull()
                    val lo = attrs.getValue("lon")?.toDoubleOrNull()
                    if (la != null && lo != null && la in -90.0..90.0 && lo in -180.0..180.0) {
                        lat = la; lon = lo; ele = null; time = null; hr = null
                        inPoint = true; pointDepth = depth
                    }
                }
            }
        }

        override fun characters(ch: CharArray, start: Int, length: Int) {
            text.appendRange(ch, start, start + length)
        }

        override fun endElement(uri: String?, localName: String?, qName: String?) {
            val n = local(localName, qName)
            if (inPoint) {
                when (n) {
                    "ele", "altitudemeters" -> ele = text.toString().trim().toDoubleOrNull()
                    // Garmin : <gpxtpx:hr> (GPX) ou <HeartRateBpm><Value> (TCX).
                    "hr", "heartrate", "heart_rate" -> hr = text.toString().trim().toDoubleOrNull()?.toInt()
                    "value" -> if (inHeartRate) hr = text.toString().trim().toDoubleOrNull()?.toInt()
                    "heartratebpm" -> inHeartRate = false
                    "time" -> time = parseTime(text.toString())
                    "latitudedegrees" -> lat = text.toString().trim().toDoubleOrNull() ?: Double.NaN
                    "longitudedegrees" -> lon = text.toString().trim().toDoubleOrNull() ?: Double.NaN
                    "trackpoint" -> if (depth == pointDepth) {
                        // Les Trackpoint sans position (pause, capteur seul) sont ignorés.
                        if (lat in -90.0..90.0 && lon in -180.0..180.0) {
                            val seg = current ?: mutableListOf<TrackPoint>().also { current = it; trackSegments.add(it) }
                            seg.add(TrackPoint(lat, lon, ele, time, hr))
                        }
                        inPoint = false; tcxPoint = false
                    }
                    "trkpt", "rtept" -> if (depth == pointDepth) {
                        val seg = current ?: mutableListOf<TrackPoint>().also {
                            current = it
                            if (n == "trkpt") trackSegments.add(it) else routes.add(it)
                        }
                        seg.add(TrackPoint(lat, lon, ele, time, hr))
                        inPoint = false
                    }
                }
            } else if (n == "name" && name == null && depth <= 3) {
                name = text.toString().trim().ifEmpty { null }
            }
            if (n == "trkseg" || n == "rte" || n == "track") current = null
            text.setLength(0)
            depth--
        }
    }
}
