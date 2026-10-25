package com.orienteering.gpxoverlay

import android.app.Activity
import android.util.Base64
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class GarminActivityTest {

    private val gpx = """<gpx><trk><trkseg>
        <trkpt lat="45.0" lon="5.0"><time>2024-05-01T10:00:00Z</time></trkpt>
        <trkpt lat="45.001" lon="5.0"><time>2024-05-01T10:01:00Z</time></trkpt>
        </trkseg></trk></gpx>""".toByteArray()

    @Test
    fun opensGarminConnect() {
        val a = Robolectric.buildActivity(GarminActivity::class.java).setup().get()
        val web = a.findViewById<android.webkit.WebView>(R.id.web)
        assertEquals(GarminActivity.START_URL, shadowOf(web).lastLoadedUrl)
        assertTrue(web.settings.javaScriptEnabled)
        assertFalse(web.settings.allowFileAccess)
    }

    @Test
    fun exportedFileIsReturned() {
        val a = Robolectric.buildActivity(GarminActivity::class.java).setup().get()
        a.pageUrl = "https://connect.garmin.com/app/activity/123"
        val token = a.bridge.arm("activity_123")
        a.bridge.onData(token, Base64.encodeToString(gpx, Base64.DEFAULT), "application/gpx+xml")
        org.robolectric.shadows.ShadowLooper.idleMainLooper()
        assertTrue(a.isFinishing)
        assertEquals(Activity.RESULT_OK, shadowOf(a).resultCode)
        val f = File(shadowOf(a).resultIntent.data!!.path!!)
        assertTrue(f.name.endsWith("activity_123.gpx"))
        assertEquals(2, TrackParser.parse(f.inputStream()).points.size)
    }

    @Test
    fun bridgeNeedsTheOneTimeCode() {
        val a = Robolectric.buildActivity(GarminActivity::class.java).setup().get()
        a.pageUrl = "https://connect.garmin.com/app/activity/123"
        val data = Base64.encodeToString(gpx, Base64.DEFAULT)
        // Sans export demandé, ou avec un faux code (script tiers) : ignoré.
        a.bridge.onData(null, data, "")
        a.bridge.onData("faux", data, "")
        val token = a.bridge.arm("x")
        a.bridge.onData("faux", data, "")
        org.robolectric.shadows.ShadowLooper.idleMainLooper()
        assertFalse(a.isFinishing)
        // Le bon code fonctionne une seule fois.
        a.bridge.onError(token, "test")
        a.bridge.onData(token, data, "")
        org.robolectric.shadows.ShadowLooper.idleMainLooper()
        assertFalse(a.isFinishing)
    }

    @Test
    fun dataFromOtherSitesIsIgnored() {
        val a = Robolectric.buildActivity(GarminActivity::class.java).setup().get()
        a.pageUrl = "https://exemple.com/piege"
        val token = a.bridge.arm("x")
        a.bridge.onData(token, Base64.encodeToString(gpx, Base64.DEFAULT), "application/gpx+xml")
        org.robolectric.shadows.ShadowLooper.idleMainLooper()
        assertFalse(a.isFinishing)
    }

    @Test
    fun onlyRealGarminHostsAreTrusted() {
        val a = Robolectric.buildActivity(GarminActivity::class.java).setup().get()
        fun ok(u: String) = a.isGarmin(android.net.Uri.parse(u))
        assertTrue(ok("https://connect.garmin.com/app/activities"))
        assertTrue(ok("https://sso.garmin.com/portal"))
        assertTrue(ok("https://garmin.com"))
        assertFalse(ok("http://connect.garmin.com/"))          // non chiffré
        assertFalse(ok("https://evilgarmin.com/"))             // domaine imité
        assertFalse(ok("https://connect.garmin.com.evil.net/")) // sous-domaine piège
        assertFalse(ok("https://garmin.com@evil.net/"))         // identifiant dans l'URL
    }
}
