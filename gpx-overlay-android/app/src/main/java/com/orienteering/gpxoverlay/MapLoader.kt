package com.orienteering.gpxoverlay

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.pdf.PdfRenderer
import android.net.Uri
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/** Carte chargée en mémoire. [pxPerMm] = pixels par mm de papier, si on le connaît. */
class LoadedMap(val bitmap: Bitmap, val pxPerMm: Double?, val isPdf: Boolean, val page: Int, val pageCount: Int)

object MapLoader {
    /** Côté maximal du bitmap : au-delà, certains téléphones ne savent plus l'afficher. */
    const val MAX_SIDE = 4096

    fun isPdf(context: Context, uri: Uri): Boolean {
        val type = context.contentResolver.getType(uri)
        if (type == "application/pdf") return true
        if (type != null && type.startsWith("image/")) return false
        // Type inconnu : on regarde la signature du fichier.
        return context.contentResolver.openInputStream(uri)?.use { s ->
            val head = ByteArray(5)
            s.read(head) == 5 && String(head, Charsets.US_ASCII) == "%PDF-"
        } ?: false
    }

    fun pdfPageCount(context: Context, uri: Uri): Int =
        context.contentResolver.openFileDescriptor(uri, "r")!!.use { fd ->
            PdfRenderer(fd).use { it.pageCount }
        }

    fun loadPdf(context: Context, uri: Uri, pageIndex: Int): LoadedMap {
        val fd = context.contentResolver.openFileDescriptor(uri, "r")
            ?: throw IllegalStateException("Impossible d'ouvrir le PDF")
        fd.use {
            PdfRenderer(fd).use { renderer ->
                val count = renderer.pageCount
                val idx = pageIndex.coerceIn(0, count - 1)
                renderer.openPage(idx).use { page ->
                    // Taille de page en points (1/72 pouce). On vise ~600 dpi, limité par MAX_SIDE.
                    val wPt = page.width.toDouble()
                    val hPt = page.height.toDouble()
                    val scale = min(600.0 / 72.0, MAX_SIDE / max(wPt, hPt))
                    val w = max(1, (wPt * scale).roundToInt())
                    val h = max(1, (hPt * scale).roundToInt())
                    val bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
                    bmp.eraseColor(Color.WHITE)
                    val m = Matrix().apply { setScale((w / wPt).toFloat(), (h / hPt).toFloat()) }
                    page.render(bmp, null, m, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                    val pxPerMm = (w / wPt) * 72.0 / 25.4
                    return LoadedMap(bmp, pxPerMm, true, idx, count)
                }
            }
        }
    }

    /** Image JPEG/PNG/WebP… [dpi] = résolution du scan ou de l'export, si connue. */
    fun loadImage(context: Context, uri: Uri, dpi: Double?): LoadedMap {
        val cr = context.contentResolver
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        cr.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
        val ow = bounds.outWidth
        val oh = bounds.outHeight
        if (ow <= 0 || oh <= 0) throw IllegalStateException("Format d'image non reconnu")
        var sample = 1
        while (max(ow, oh) / (sample * 2) >= MAX_SIDE) sample *= 2
        val opts = BitmapFactory.Options().apply {
            inSampleSize = sample
            inPreferredConfig = Bitmap.Config.ARGB_8888
        }
        var bmp = cr.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, opts) }
            ?: throw IllegalStateException("Impossible de décoder l'image")
        val side = max(bmp.width, bmp.height)
        if (side > MAX_SIDE) {
            val f = MAX_SIDE.toDouble() / side
            val scaled = Bitmap.createScaledBitmap(
                bmp, max(1, (bmp.width * f).roundToInt()), max(1, (bmp.height * f).roundToInt()), true
            )
            if (scaled !== bmp) bmp.recycle()
            bmp = scaled
        }
        val ratio = bmp.width.toDouble() / ow
        return LoadedMap(bmp, dpi?.let { it / 25.4 * ratio }, false, 0, 1)
    }
}
