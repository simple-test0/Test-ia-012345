package com.orienteering.gpxoverlay

import java.io.InputStream

/** Ouvre une trace GPX, TCX ou FIT en reconnaissant le format au contenu. */
object TrackParser {
    fun parse(input: InputStream): Track {
        val data = input.readBytes()
        if (FitParser.isFit(data)) return FitParser.parse(data)
        return GpxParser.parse(data.inputStream())
    }
}
