package com.orienteering.gpxoverlay

import java.io.ByteArrayInputStream
import java.io.InputStream
import java.util.zip.ZipInputStream

/**
 * Ouvre une trace GPX, TCX ou FIT en reconnaissant le format au contenu.
 * Accepte aussi un ZIP (export « fichier d'origine » de Garmin Connect) : la première trace trouvée dedans.
 */
object TrackParser {
    private const val MAX_ENTRY = 64L * 1024 * 1024

    fun parse(input: InputStream): Track = parseBytes(input.readBytes(), depth = 0)

    private fun parseBytes(data: ByteArray, depth: Int): Track {
        if (isZip(data) && depth == 0) return parseZip(data)
        if (FitParser.isFit(data)) return FitParser.parse(data)
        return GpxParser.parse(data.inputStream())
    }

    private fun isZip(d: ByteArray) = d.size >= 4 && d[0] == 'P'.code.toByte() && d[1] == 'K'.code.toByte() &&
        d[2].toInt() == 3 && d[3].toInt() == 4

    private fun parseZip(data: ByteArray): Track {
        ZipInputStream(ByteArrayInputStream(data)).use { zip ->
            while (true) {
                val e = zip.nextEntry ?: break
                val name = e.name.lowercase()
                if (e.isDirectory || !(name.endsWith(".fit") || name.endsWith(".gpx") || name.endsWith(".tcx"))) continue
                val bytes = readLimited(zip)
                return parseBytes(bytes, depth = 1)
            }
        }
        throw GpxParser.GpxException("Aucune trace (FIT, GPX ou TCX) dans ce fichier ZIP.")
    }

    private fun readLimited(input: InputStream): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        val buf = ByteArray(64 * 1024)
        var total = 0L
        while (true) {
            val n = input.read(buf)
            if (n < 0) break
            total += n
            if (total > MAX_ENTRY) throw GpxParser.GpxException("Fichier trop gros dans le ZIP.")
            out.write(buf, 0, n)
        }
        return out.toByteArray()
    }
}
