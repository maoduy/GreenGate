package vn.greengate.app

/**
 * Port of proxy/timewindow.py. "HH:MM-HH:MM [days]; ..." -> is this minute allowed?
 * Days: T2..T7, CN (Vietnamese), Mon..Sun, 2..8. weekday 0 = Monday .. 6 = Sunday.
 * Malformed text throws IllegalArgumentException. Test vectors: docs/timewindow-vectors.json.
 */
object TimeWindow {
    data class Window(val start: Int, val end: Int, val days: Set<Int>)

    private val DAY = mapOf(
        "t2" to 0, "t3" to 1, "t4" to 2, "t5" to 3, "t6" to 4, "t7" to 5, "cn" to 6, "t8" to 6,
        "mon" to 0, "tue" to 1, "wed" to 2, "thu" to 3, "fri" to 4, "sat" to 5, "sun" to 6,
        "2" to 0, "3" to 1, "4" to 2, "5" to 3, "6" to 4, "7" to 5, "8" to 6)
    private val RANGE = Regex("""^\s*(\d{1,2})[:h](\d{2})\s*-\s*(\d{1,2})[:h](\d{2})\s*(.*)$""")

    private fun minutes(h: String, m: String): Int {
        val hh = h.toInt(); val mm = m.toInt()
        if (hh > 24 || mm > 59 || (hh == 24 && mm != 0)) throw IllegalArgumentException("gio khong hop le: $h:$m")
        return hh * 60 + mm
    }

    private fun days(textIn: String): Set<Int> {
        val text = textIn.trim().lowercase().replace("thứ", "t").replace("thu ", "t")
        if (text.isEmpty()) return (0..6).toSet()
        val out = HashSet<Int>()
        for (part in text.split(Regex("[,\\s]+"))) {
            if (part.isEmpty()) continue
            if ("-" in part) {
                val (a, b) = part.split("-", limit = 2)
                val da = DAY[a] ?: throw IllegalArgumentException("ngay khong hop le: $part")
                val db = DAY[b] ?: throw IllegalArgumentException("ngay khong hop le: $part")
                var i = da
                while (true) { out.add(i); if (i == db) break; i = (i + 1) % 7 }
            } else {
                out.add(DAY[part] ?: throw IllegalArgumentException("ngay khong hop le: $part"))
            }
        }
        return out
    }

    fun parse(text: String?): List<Window> {
        val windows = ArrayList<Window>()
        for (pieceRaw in (text ?: "").split(Regex("[;\n]+"))) {
            val piece = pieceRaw.trim()
            if (piece.isEmpty() || piece.startsWith("#")) continue
            val m = RANGE.matchEntire(piece) ?: throw IllegalArgumentException("khung gio khong hop le: $piece")
            windows.add(Window(minutes(m.groupValues[1], m.groupValues[2]),
                minutes(m.groupValues[3], m.groupValues[4]), days(m.groupValues[5])))
        }
        return windows
    }

    fun allowed(windows: List<Window>, weekday: Int, minute: Int): Boolean {
        if (windows.isEmpty()) return true
        for (w in windows) {
            if (w.start <= w.end) {
                if (weekday in w.days && minute >= w.start && minute < w.end) return true
            } else {
                if (weekday in w.days && minute >= w.start) return true
                if (((weekday - 1) % 7 + 7) % 7 in w.days && minute < w.end) return true
            }
        }
        return false
    }

    fun allowedNow(windows: List<Window>, now: Long = System.currentTimeMillis()): Boolean {
        val cal = java.util.Calendar.getInstance().apply { timeInMillis = now }
        val wd = (cal.get(java.util.Calendar.DAY_OF_WEEK) + 5) % 7   // Calendar: Sunday=1 .. Saturday=7
        val minute = cal.get(java.util.Calendar.HOUR_OF_DAY) * 60 + cal.get(java.util.Calendar.MINUTE)
        return allowed(windows, wd, minute)
    }
}
