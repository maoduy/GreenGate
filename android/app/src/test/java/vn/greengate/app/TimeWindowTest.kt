package vn.greengate.app

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.fail
import org.junit.Test
import java.io.File

/** Runs the shared vectors in docs/timewindow-vectors.json against the Kotlin port. */
class TimeWindowTest {
    @Test
    fun vectors() {
        val f = listOf("../../docs/timewindow-vectors.json", "../docs/timewindow-vectors.json", "docs/timewindow-vectors.json").map { File(it) }.first { it.exists() }
        val cases = JSONObject(f.readText()).getJSONArray("cases")
        var n = 0
        for (i in 0 until cases.length()) {
            val c = cases.getJSONObject(i); n++
            val text = c.getString("text")
            if (c.optBoolean("error")) {
                try { TimeWindow.parse(text); fail("expected error for '$text'") } catch (e: IllegalArgumentException) {}
            } else {
                val got = TimeWindow.allowed(TimeWindow.parse(text), c.getInt("weekday"), c.getInt("minute"))
                assertEquals("'$text' wd=${c.getInt("weekday")} min=${c.getInt("minute")}", c.getBoolean("allowed"), got)
            }
        }
        println("$n vectors ok")
    }

    @Test
    fun rules() {
        val r = Rules.build("Trang web,Ghi chú\nyoutube.com,,\nwww.Example.com/kids,,\n", "Kênh\n@TED\n", "x\nbad.test\n", null,
            "key,value\nmode,blacklist\nkeywords,+default,lauxanh\nschedule,07:00-21:00\n")
        assertEquals("blacklist", r.mode)
        assertEquals(setOf("youtube.com", "example.com"), r.allowed)
        assertEquals(true, r.inSet(r.blocked, "sub.bad.test"))
        assertEquals("sex", r.keywordHit("free-sex-videos.example"))
        assertEquals(null, r.keywordHit("sussex.ac.uk"))
        assertEquals("channels", r.youtube)
        assertEquals(1, r.schedule.size)
    }
}
