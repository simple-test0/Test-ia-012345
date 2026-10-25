package com.orienteering.gpxoverlay

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID

/** Une séance d'analyse : une carte, une trace, leur calage et les postes. */
data class Session(
    val id: String,
    val name: String?,
    val savedAt: Long,
    val mapUri: String?,
    val mapPage: Int,
    val mapName: String?,
    val trackUri: String?,
    val trackName: String?,
    val matrix: FloatArray?,
    val controls: List<FloatArray>,
    val scaleDen: Int,
    val dpi: Int,
    val distanceM: Double?,
    val durationMs: Long?,
) {
    /** Titre affiché : nom choisi, sinon les fichiers. */
    val title: String
        get() = name ?: listOfNotNull(mapName, trackName).joinToString(" · ").ifEmpty { "Session" }
}

/** Liste des sessions, enregistrée en JSON dans le stockage de l'app (avec une miniature par session). */
class SessionStore(private val dir: File) {

    private val file = File(dir, "sessions.json")

    init { dir.mkdirs() }

    fun thumbFile(id: String) = File(dir, "$id.png")

    fun list(): List<Session> {
        if (!file.exists()) return emptyList()
        return try {
            val arr = JSONArray(file.readText())
            (0 until arr.length()).mapNotNull { fromJson(arr.getJSONObject(it)) }.sortedByDescending { it.savedAt }
        } catch (_: Exception) {
            emptyList()
        }
    }

    fun get(id: String): Session? = list().firstOrNull { it.id == id }

    fun findByFiles(mapUri: String?, trackUri: String?): Session? =
        list().firstOrNull { it.mapUri == mapUri && it.trackUri == trackUri }

    fun upsert(s: Session) {
        val all = list().filter { it.id != s.id }.toMutableList()
        all.add(0, s)
        // On garde les 30 sessions les plus récentes.
        all.drop(MAX_SESSIONS).forEach { thumbFile(it.id).delete() }
        write(all.take(MAX_SESSIONS))
    }

    fun rename(id: String, name: String?) {
        val all = list().map { if (it.id == id) it.copy(name = name?.trim()?.ifEmpty { null }) else it }
        write(all)
    }

    fun delete(id: String) {
        write(list().filter { it.id != id })
        thumbFile(id).delete()
    }

    /** Fichiers (URI) utilisés par au moins une session : à ne pas effacer. */
    fun referencedUris(): Set<String> = list().flatMap { listOfNotNull(it.mapUri, it.trackUri) }.toSet()

    private fun write(all: List<Session>) {
        val arr = JSONArray()
        all.forEach { arr.put(toJson(it)) }
        val tmp = File(dir, "sessions.json.tmp")
        tmp.writeText(arr.toString())
        tmp.renameTo(file)
    }

    private fun toJson(s: Session) = JSONObject().apply {
        put("id", s.id)
        s.name?.let { put("name", it) }
        put("savedAt", s.savedAt)
        s.mapUri?.let { put("mapUri", it) }
        put("mapPage", s.mapPage)
        s.mapName?.let { put("mapName", it) }
        s.trackUri?.let { put("trackUri", it) }
        s.trackName?.let { put("trackName", it) }
        s.matrix?.let { m -> put("matrix", JSONArray().apply { m.forEach { put(it.toDouble()) } }) }
        put("controls", JSONArray().apply { s.controls.forEach { c -> put(JSONArray().put(c[0].toDouble()).put(c[1].toDouble())) } })
        put("scaleDen", s.scaleDen)
        put("dpi", s.dpi)
        s.distanceM?.let { put("distanceM", it) }
        s.durationMs?.let { put("durationMs", it) }
    }

    private fun fromJson(o: JSONObject): Session? = try {
        Session(
            id = o.getString("id"),
            name = o.optString("name").ifEmpty { null },
            savedAt = o.optLong("savedAt"),
            mapUri = o.optString("mapUri").ifEmpty { null },
            mapPage = o.optInt("mapPage"),
            mapName = o.optString("mapName").ifEmpty { null },
            trackUri = o.optString("trackUri").ifEmpty { null },
            trackName = o.optString("trackName").ifEmpty { null },
            matrix = o.optJSONArray("matrix")?.let { a -> FloatArray(a.length()) { a.getDouble(it).toFloat() } }?.takeIf { it.size == 9 },
            controls = o.optJSONArray("controls")?.let { a ->
                (0 until a.length()).map { i -> a.getJSONArray(i).let { floatArrayOf(it.getDouble(0).toFloat(), it.getDouble(1).toFloat()) } }
            } ?: emptyList(),
            scaleDen = o.optInt("scaleDen", 10000),
            dpi = o.optInt("dpi", 300),
            distanceM = if (o.has("distanceM")) o.getDouble("distanceM") else null,
            durationMs = if (o.has("durationMs")) o.getLong("durationMs") else null,
        )
    } catch (_: Exception) {
        null
    }

    companion object {
        const val MAX_SESSIONS = 30
        fun newId(): String = UUID.randomUUID().toString()
    }
}
