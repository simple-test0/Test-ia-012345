package com.orienteering.gpxoverlay

import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Matrix
import android.net.Uri
import android.os.Looper
import android.os.SystemClock
import android.view.MotionEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.fakes.RoboMenuItem
import java.io.File

/** Scénario complet : ouvrir une carte + un GPX, ajuster, caler par points, dessiner. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w400dp-h700dp-mdpi")
class MainActivityTest {

    private fun resourceFile(name: String): File {
        val url = javaClass.classLoader!!.getResource(name)
        return File(url.toURI())
    }

    /** Attend la fin des chargements en arrière-plan. */
    private fun waitFor(cond: () -> Boolean) {
        val end = System.currentTimeMillis() + 20_000
        while (!cond() && System.currentTimeMillis() < end) {
            shadowOf(Looper.getMainLooper()).idle()
            Thread.sleep(20)
        }
        shadowOf(Looper.getMainLooper()).idle()
        assertTrue("délai dépassé", cond())
    }

    private fun openVia(activity: MainActivity, menuId: Int, file: File) {
        activity.onOptionsItemSelected(RoboMenuItem(menuId))
        val started = shadowOf(activity).nextStartedActivityForResult
        assertEquals(Intent.ACTION_OPEN_DOCUMENT, started.intent.action)
        shadowOf(activity).receiveResult(started.intent, Activity.RESULT_OK, Intent().setData(Uri.fromFile(file)))
    }

    private fun touch(v: OverlayView, action: Int, vararg xy: Float) {
        val n = xy.size / 2
        val props = Array(n) { MotionEvent.PointerProperties().apply { id = it; toolType = MotionEvent.TOOL_TYPE_FINGER } }
        val coords = Array(n) { MotionEvent.PointerCoords().apply { x = xy[2 * it]; y = xy[2 * it + 1] } }
        val t = SystemClock.uptimeMillis()
        val e = MotionEvent.obtain(t, t, action, n, props, coords, 0, 0, 1f, 1f, 0, 0, 0, 0)
        v.dispatchTouchEvent(e)
        e.recycle()
    }

    private fun screenshot(v: OverlayView, name: String): Bitmap {
        val b = Bitmap.createBitmap(v.width, v.height, Bitmap.Config.ARGB_8888)
        v.draw(Canvas(b))
        File("build/test-screens").mkdirs()
        File("build/test-screens/$name.png").outputStream().use { b.compress(Bitmap.CompressFormat.PNG, 100, it) }
        return b
    }

    @Test
    fun fullScenario() {
        val controller = Robolectric.buildActivity(MainActivity::class.java).setup()
        val activity = controller.get()
        val overlay = activity.findViewById<OverlayView>(R.id.overlay)
        assertTrue(overlay.width > 0 && overlay.height > 0)
        screenshot(overlay, "0_vide")

        openVia(activity, R.id.open_map, resourceFile("carte_test.jpg"))
        waitFor { overlay.mapBitmap != null }
        openVia(activity, R.id.open_gpx, resourceFile("trace_test.gpx"))
        waitFor { overlay.track != null }
        assertEquals(241, overlay.track!!.points.size)
        screenshot(overlay, "1_charge")

        // Le texte des stats est rempli.
        val stats = activity.findViewById<android.widget.TextView>(R.id.stats).text.toString()
        assertTrue(stats, stats.contains("km"))

        // Mode « Ajuster trace » : un glissé déplace la trace.
        activity.findViewById<android.widget.Button>(R.id.btnTrace).performClick()
        assertEquals(OverlayView.Mode.TRACE, overlay.mode)
        val before = Matrix(overlay.traceMatrix)
        touch(overlay, MotionEvent.ACTION_DOWN, 100f, 100f)
        touch(overlay, MotionEvent.ACTION_MOVE, 150f, 130f)
        touch(overlay, MotionEvent.ACTION_UP, 150f, 130f)
        assertNotEquals(before, overlay.traceMatrix)

        // Deux doigts : rotation de la trace.
        val rot0 = overlay.traceRotationDeg()
        touch(overlay, MotionEvent.ACTION_DOWN, 100f, 300f)
        touch(overlay, MotionEvent.ACTION_POINTER_DOWN or (1 shl MotionEvent.ACTION_POINTER_INDEX_SHIFT), 100f, 300f, 300f, 300f)
        touch(overlay, MotionEvent.ACTION_MOVE, 100f, 300f, 300f, 340f)
        touch(overlay, MotionEvent.ACTION_POINTER_UP or (1 shl MotionEvent.ACTION_POINTER_INDEX_SHIFT), 100f, 300f, 300f, 340f)
        touch(overlay, MotionEvent.ACTION_UP, 100f, 300f)
        assertEquals(rot0 + Math.toDegrees(Math.atan2(40.0, 200.0)), overlay.traceRotationDeg(), 0.5)

        // Échelle : PDF/dpi connu → px par mètre = dpi/25,4 × ratio × 1000/10000.
        overlay.setTraceScale(0.5)
        assertEquals(0.5, overlay.traceScale(), 1e-6)

        // Calage par 2 points : on touche 2 points de la trace puis leurs cibles.
        activity.findViewById<android.widget.Button>(R.id.btnCalib).performClick()
        assertEquals(OverlayView.Mode.CALIBRATE, overlay.mode)
        val t = overlay.track!!
        val viewM = overlay.javaClass.getDeclaredField("viewMatrix").apply { isAccessible = true }.get(overlay) as Matrix
        /** Position actuelle à l'écran du point i de la trace. */
        fun screenOf(i: Int): FloatArray {
            val p = floatArrayOf(t.local[2 * i], t.local[2 * i + 1])
            overlay.traceMatrix.mapPoints(p); viewM.mapPoints(p)
            return p
        }
        val targets = HashMap<Int, FloatArray>()
        for (i in listOf(0, 120)) {
            val src = screenOf(i)
            val dst = floatArrayOf(src[0] + 20, src[1] + 10)
            targets[i] = dst
            touch(overlay, MotionEvent.ACTION_DOWN, src[0], src[1]); touch(overlay, MotionEvent.ACTION_UP, src[0], src[1])
            assertTrue(overlay.waitingForMapPoint)
            touch(overlay, MotionEvent.ACTION_DOWN, dst[0], dst[1]); touch(overlay, MotionEvent.ACTION_UP, dst[0], dst[1])
        }
        // Pour vérifier le calage : la cible du 1er point est restée fixe sur la carte.
        val ta = targets[0]!!; val tb = targets[120]!!
        assertEquals(2, overlay.calibrationCount)
        // Après calage, les deux points de la trace tombent sur leurs cibles.
        for ((i, target) in listOf(0 to ta, 120 to tb)) {
            val p = screenOf(i)
            assertEquals(target[0], p[0], 1.5f); assertEquals(target[1], p[1], 1.5f)
        }
        screenshot(overlay, "2_calage")
        activity.findViewById<android.widget.Button>(R.id.btnDone).performClick()

        // Export : l'image composée a la taille de la carte.
        val out = overlay.renderComposite()
        assertNotNull(out)
        assertEquals(overlay.mapBitmap!!.width, out!!.width)

        // La session est sauvegardée puis restaurée.
        val saved = Matrix(overlay.traceMatrix)
        controller.pause().stop().destroy()
        val restored = Robolectric.buildActivity(MainActivity::class.java).setup().get()
        val ov2 = restored.findViewById<OverlayView>(R.id.overlay)
        waitFor { ov2.mapBitmap != null && ov2.track != null }
        val v1 = FloatArray(9).also { saved.getValues(it) }
        val v2 = FloatArray(9).also { ov2.traceMatrix.getValues(it) }
        for (k in 0 until 9) assertEquals(v1[k], v2[k], 1e-3f)
    }
}
