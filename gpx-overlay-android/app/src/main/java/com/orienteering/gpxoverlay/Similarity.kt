package com.orienteering.gpxoverlay

import kotlin.math.atan2
import kotlin.math.hypot

/**
 * Transformation de similitude (rotation + échelle uniforme + translation) :
 *   x' = a·x − b·y + tx
 *   y' = b·x + a·y + ty
 */
data class Similarity(val a: Double, val b: Double, val tx: Double, val ty: Double) {

    val scale: Double get() = hypot(a, b)
    val rotationDeg: Double get() = Math.toDegrees(atan2(b, a))

    fun applyX(x: Double, y: Double) = a * x - b * y + tx
    fun applyY(x: Double, y: Double) = b * x + a * y + ty

    /** Valeurs au format android.graphics.Matrix (3x3, ligne par ligne). */
    fun toMatrixValues(): FloatArray = floatArrayOf(
        a.toFloat(), (-b).toFloat(), tx.toFloat(),
        b.toFloat(), a.toFloat(), ty.toFloat(),
        0f, 0f, 1f,
    )

    companion object {
        /**
         * Similitude qui envoie au mieux (moindres carrés) chaque point src[i] sur dst[i].
         * Il faut au moins deux points distincts. Les tableaux sont au format x0,y0,x1,y1…
         */
        fun fit(src: DoubleArray, dst: DoubleArray): Similarity? {
            require(src.size == dst.size && src.size % 2 == 0)
            val n = src.size / 2
            if (n < 2) return null
            var sx = 0.0; var sy = 0.0; var dx = 0.0; var dy = 0.0
            for (i in 0 until n) {
                sx += src[2 * i]; sy += src[2 * i + 1]
                dx += dst[2 * i]; dy += dst[2 * i + 1]
            }
            sx /= n; sy /= n; dx /= n; dy /= n
            var num1 = 0.0; var num2 = 0.0; var den = 0.0
            for (i in 0 until n) {
                val x = src[2 * i] - sx
                val y = src[2 * i + 1] - sy
                val u = dst[2 * i] - dx
                val v = dst[2 * i + 1] - dy
                num1 += x * u + y * v
                num2 += x * v - y * u
                den += x * x + y * y
            }
            if (den < 1e-12) return null
            val a = num1 / den
            val b = num2 / den
            return Similarity(a, b, dx - (a * sx - b * sy), dy - (b * sx + a * sy))
        }
    }
}
