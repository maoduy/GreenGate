package vn.greengate.app

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * The device's browsing history as seen at DNS level: one row per (host, minute), with a
 * hit count and whether it was blocked. Pruned by retentionDays. Read back as CSV for the
 * `history` relay command.
 */
class DnsLog(c: Context) : SQLiteOpenHelper(c, "dnslog.db", null, 1) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE q (minute INTEGER NOT NULL, host TEXT NOT NULL, blocked INTEGER NOT NULL, hits INTEGER NOT NULL, reason TEXT, PRIMARY KEY (minute, host, blocked))")
        db.execSQL("CREATE INDEX q_minute ON q(minute)")
    }
    override fun onUpgrade(db: SQLiteDatabase, a: Int, b: Int) {}

    private val pending = HashMap<Triple<Long, String, Int>, Pair<Int, String?>>()

    /** Buffered: flushed by the service every few seconds, never on the packet path. */
    @Synchronized fun record(host: String, blocked: Boolean, reason: String?) {
        val minute = System.currentTimeMillis() / 60000
        val k = Triple(minute, host, if (blocked) 1 else 0)
        val cur = pending[k]
        pending[k] = (cur?.first ?: 0) + 1 to (reason ?: cur?.second)
    }

    fun flush() {
        val batch: Map<Triple<Long, String, Int>, Pair<Int, String?>>
        synchronized(this) { if (pending.isEmpty()) return; batch = HashMap(pending); pending.clear() }
        val db = writableDatabase
        db.beginTransaction()
        try {
            for ((k, v) in batch) {
                db.execSQL("INSERT INTO q(minute,host,blocked,hits,reason) VALUES(?,?,?,?,?) ON CONFLICT(minute,host,blocked) DO UPDATE SET hits=hits+excluded.hits",
                    arrayOf(k.first, k.second, k.third, v.first, v.second))
            }
            db.setTransactionSuccessful()
        } finally { db.endTransaction() }
    }

    fun prune(retentionDays: Int) {
        val cutoff = System.currentTimeMillis() / 60000 - retentionDays.toLong() * 1440
        writableDatabase.execSQL("DELETE FROM q WHERE minute < ?", arrayOf(cutoff))
    }

    /** CSV for one month "MM-yyyy": date,time,host,blocked,hits,reason */
    fun monthCsv(month: String): String {
        flush()
        val sb = StringBuilder("date,time,host,blocked,hits,reason\n")
        val fmtD = SimpleDateFormat("yyyy-MM-dd", Locale.ROOT); val fmtT = SimpleDateFormat("HH:mm", Locale.ROOT)
        val mm = month.substring(0, 2).toInt(); val yyyy = month.substring(3).toInt()
        val cal = java.util.Calendar.getInstance(); cal.clear(); cal.set(yyyy, mm - 1, 1)
        val start = cal.timeInMillis / 60000; cal.add(java.util.Calendar.MONTH, 1); val end = cal.timeInMillis / 60000
        readableDatabase.rawQuery("SELECT minute,host,blocked,hits,reason FROM q WHERE minute>=? AND minute<? ORDER BY minute", arrayOf(start.toString(), end.toString())).use { cur ->
            while (cur.moveToNext()) {
                val d = Date(cur.getLong(0) * 60000)
                sb.append(fmtD.format(d)).append(',').append(fmtT.format(d)).append(',').append(cur.getString(1)).append(',')
                    .append(cur.getInt(2)).append(',').append(cur.getInt(3)).append(',').append(cur.getString(4) ?: "").append('\n')
            }
        }
        return sb.toString()
    }

    fun countToday(): Pair<Int, Int> {
        flush()
        val cal = java.util.Calendar.getInstance(); cal.set(java.util.Calendar.HOUR_OF_DAY, 0); cal.set(java.util.Calendar.MINUTE, 0)
        val start = cal.timeInMillis / 60000
        var ok = 0; var bl = 0
        readableDatabase.rawQuery("SELECT blocked, SUM(hits) FROM q WHERE minute>=? GROUP BY blocked", arrayOf(start.toString())).use { cur ->
            while (cur.moveToNext()) if (cur.getInt(0) == 1) bl = cur.getInt(1) else ok = cur.getInt(1)
        }
        return ok to bl
    }
}
