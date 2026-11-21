package vn.greengate.app

import java.nio.ByteBuffer

/** Just enough DNS: parse the question, read A/AAAA answers, build replies. */
object Dns {
    const val TYPE_A = 1; const val TYPE_AAAA = 28; const val TYPE_HTTPS = 65

    class Query(val id: Int, val name: String, val type: Int, val qclass: Int, val questionEnd: Int, val raw: ByteArray)

    fun readName(b: ByteArray, start: Int): Pair<String, Int> {
        val sb = StringBuilder()
        var p = start
        var jumped = false
        var end = -1
        var hops = 0
        while (true) {
            if (p >= b.size) throw IllegalArgumentException("name overflow")
            val len = b[p].toInt() and 0xff
            if (len == 0) { p++; break }
            if (len and 0xC0 == 0xC0) {
                if (!jumped) end = p + 2
                p = ((len and 0x3f) shl 8) or (b[p + 1].toInt() and 0xff)
                jumped = true
                if (++hops > 20) throw IllegalArgumentException("pointer loop")
                continue
            }
            p++
            if (sb.isNotEmpty()) sb.append('.')
            sb.append(String(b, p, len, Charsets.ISO_8859_1))
            p += len
        }
        return sb.toString().lowercase() to (if (jumped) end else p)
    }

    fun parseQuery(b: ByteArray): Query? {
        if (b.size < 12) return null
        val id = ((b[0].toInt() and 0xff) shl 8) or (b[1].toInt() and 0xff)
        val qd = ((b[4].toInt() and 0xff) shl 8) or (b[5].toInt() and 0xff)
        if (qd < 1) return null
        val (name, p) = readName(b, 12)
        if (p + 4 > b.size) return null
        val type = ((b[p].toInt() and 0xff) shl 8) or (b[p + 1].toInt() and 0xff)
        val qclass = ((b[p + 2].toInt() and 0xff) shl 8) or (b[p + 3].toInt() and 0xff)
        return Query(id, name, type, qclass, p + 4, b)
    }

    /** A and AAAA rdata bytes from an upstream response, in order. */
    fun answers(b: ByteArray): List<Pair<Int, ByteArray>> {
        val out = ArrayList<Pair<Int, ByteArray>>()
        if (b.size < 12) return out
        val qd = ((b[4].toInt() and 0xff) shl 8) or (b[5].toInt() and 0xff)
        val an = ((b[6].toInt() and 0xff) shl 8) or (b[7].toInt() and 0xff)
        var p = 12
        for (i in 0 until qd) { p = readName(b, p).second + 4 }
        for (i in 0 until an) {
            p = readName(b, p).second
            if (p + 10 > b.size) break
            val type = ((b[p].toInt() and 0xff) shl 8) or (b[p + 1].toInt() and 0xff)
            val rdlen = ((b[p + 8].toInt() and 0xff) shl 8) or (b[p + 9].toInt() and 0xff)
            p += 10
            if (p + rdlen > b.size) break
            if (type == TYPE_A || type == TYPE_AAAA) out.add(type to b.copyOfRange(p, p + rdlen))
            p += rdlen
        }
        return out
    }

    /** Response to q with the given rdata records (same type as the question). Empty list = NOERROR/NODATA. */
    fun reply(q: Query, records: List<ByteArray>, ttl: Int, rcode: Int = 0): ByteArray {
        val question = q.raw.copyOfRange(12, q.questionEnd)
        val buf = ByteBuffer.allocate(12 + question.size + records.sumOf { 12 + it.size })
        buf.putShort(q.id.toShort())
        val flags = 0x8180 or (rcode and 0xf)      // QR, RD, RA
        buf.putShort(flags.toShort())
        buf.putShort(1); buf.putShort(records.size.toShort()); buf.putShort(0); buf.putShort(0)
        buf.put(question)
        for (r in records) {
            buf.putShort(0xC00C.toShort())          // pointer to the question name
            buf.putShort(q.type.toShort()); buf.putShort(q.qclass.toShort())
            buf.putInt(ttl); buf.putShort(r.size.toShort()); buf.put(r)
        }
        return buf.array()
    }

    fun blockedReply(q: Query): ByteArray = when (q.type) {
        TYPE_A -> reply(q, listOf(byteArrayOf(0, 0, 0, 0)), 10)
        TYPE_AAAA -> reply(q, listOf(ByteArray(16)), 10)
        else -> reply(q, emptyList(), 10)
    }
}
