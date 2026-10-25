package com.orienteering.gpxoverlay

import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Lecture minimale d'un fichier FIT (montres Garmin, Coros, Suunto…) :
 * seuls les messages « record » (n° 20) avec position sont gardés.
 */
object FitParser {

    private const val MSG_RECORD = 20
    private const val FIELD_TIMESTAMP = 253
    private const val FIELD_LAT = 0
    private const val FIELD_LON = 1
    private const val FIELD_ALT = 2
    private const val FIELD_ENH_ALT = 78
    private const val FIELD_HR = 3
    /** Écart entre l'époque FIT (31/12/1989) et l'époque Unix, en secondes. */
    private const val FIT_EPOCH_S = 631_065_600L
    private const val SEMICIRCLE_TO_DEG = 180.0 / 2147483648.0

    fun isFit(head: ByteArray): Boolean =
        head.size >= 12 && head[8] == '.'.code.toByte() && head[9] == 'F'.code.toByte() &&
            head[10] == 'I'.code.toByte() && head[11] == 'T'.code.toByte()

    private class FieldDef(val num: Int, val size: Int)
    private class MsgDef(val global: Int, val bigEndian: Boolean, val fields: List<FieldDef>, val devSize: Int)

    fun parse(data: ByteArray): Track {
        if (!isFit(data)) throw GpxParser.GpxException("Ce n'est pas un fichier FIT.")
        val headerSize = data[0].toInt() and 0xFF
        val dataSize = ByteBuffer.wrap(data, 4, 4).order(ByteOrder.LITTLE_ENDIAN).int.toLong() and 0xFFFFFFFFL
        val end = minOf(data.size.toLong(), headerSize + dataSize).toInt()
        var pos = headerSize
        val defs = arrayOfNulls<MsgDef>(16)
        val points = ArrayList<TrackPoint>()
        var lastTimestamp = -1L

        try {
            while (pos < end) {
                val header = data[pos++].toInt() and 0xFF
                if (header and 0x80 != 0) {
                    // En-tête « timestamp compressé » : message de données.
                    val local = (header shr 5) and 0x3
                    val offset = header and 0x1F
                    val def = defs[local] ?: throw GpxParser.GpxException("FIT : définition manquante")
                    var ts = -1L
                    if (lastTimestamp >= 0) {
                        ts = (lastTimestamp and 0x1F.inv().toLong()) + offset
                        if (offset < (lastTimestamp and 0x1F)) ts += 0x20
                        lastTimestamp = ts
                    }
                    pos = readData(data, pos, def, ts, points) { lastTimestamp = it }
                } else if (header and 0x40 != 0) {
                    // Message de définition.
                    val local = header and 0x0F
                    val hasDev = header and 0x20 != 0
                    pos++ // réservé
                    val big = data[pos++].toInt() == 1
                    val g0 = data[pos].toInt() and 0xFF
                    val g1 = data[pos + 1].toInt() and 0xFF
                    val global = if (big) (g0 shl 8) or g1 else (g1 shl 8) or g0
                    pos += 2
                    val n = data[pos++].toInt() and 0xFF
                    val fields = ArrayList<FieldDef>(n)
                    repeat(n) {
                        fields.add(FieldDef(data[pos].toInt() and 0xFF, data[pos + 1].toInt() and 0xFF))
                        pos += 3
                    }
                    var devSize = 0
                    if (hasDev) {
                        val nd = data[pos++].toInt() and 0xFF
                        repeat(nd) { devSize += data[pos + 1].toInt() and 0xFF; pos += 3 }
                    }
                    defs[local] = MsgDef(global, big, fields, devSize)
                } else {
                    val def = defs[header and 0x0F] ?: throw GpxParser.GpxException("FIT : définition manquante")
                    pos = readData(data, pos, def, -1L, points) { lastTimestamp = it }
                }
            }
        } catch (e: IndexOutOfBoundsException) {
            // Fichier tronqué : on garde ce qui a été lu.
        }
        if (points.isEmpty()) throw GpxParser.GpxException("Aucun point avec position GPS dans ce fichier FIT.")
        return Track(null, listOf(points))
    }

    private inline fun readData(
        data: ByteArray, start: Int, def: MsgDef, compressedTs: Long,
        out: MutableList<TrackPoint>, onTimestamp: (Long) -> Unit,
    ): Int {
        var pos = start
        val bb = ByteBuffer.wrap(data).order(if (def.bigEndian) ByteOrder.BIG_ENDIAN else ByteOrder.LITTLE_ENDIAN)
        var ts = compressedTs
        var lat = Int.MAX_VALUE
        var lon = Int.MAX_VALUE
        var alt: Double? = null
        var hr: Int? = null
        for (f in def.fields) {
            if (def.global == MSG_RECORD || f.num == FIELD_TIMESTAMP) {
                when {
                    f.num == FIELD_TIMESTAMP && f.size == 4 -> {
                        val v = bb.getInt(pos).toLong() and 0xFFFFFFFFL
                        if (v != 0xFFFFFFFFL) { ts = v; onTimestamp(v) }
                    }
                    def.global != MSG_RECORD -> {}
                    f.num == FIELD_LAT && f.size == 4 -> lat = bb.getInt(pos)
                    f.num == FIELD_LON && f.size == 4 -> lon = bb.getInt(pos)
                    f.num == FIELD_ENH_ALT && f.size == 4 -> {
                        val v = bb.getInt(pos).toLong() and 0xFFFFFFFFL
                        if (v != 0xFFFFFFFFL) alt = v / 5.0 - 500
                    }
                    f.num == FIELD_HR && f.size == 1 -> {
                        val v = data[pos].toInt() and 0xFF
                        if (v != 0xFF) hr = v
                    }
                    f.num == FIELD_ALT && f.size == 2 && alt == null -> {
                        val v = bb.getShort(pos).toInt() and 0xFFFF
                        if (v != 0xFFFF) alt = v / 5.0 - 500
                    }
                }
            }
            pos += f.size
        }
        pos += def.devSize
        if (def.global == MSG_RECORD && lat != Int.MAX_VALUE && lon != Int.MAX_VALUE) {
            val la = lat * SEMICIRCLE_TO_DEG
            val lo = lon * SEMICIRCLE_TO_DEG
            if (la in -90.0..90.0 && lo in -180.0..180.0) {
                if (out.size >= Track.MAX_POINTS) throw GpxParser.GpxException("Trace trop longue (plus de ${Track.MAX_POINTS} points).")
                out.add(TrackPoint(la, lo, alt, if (ts >= 0) (ts + FIT_EPOCH_S) * 1000 else null, hr))
            }
        }
        return pos
    }
}
