#!/usr/bin/env python3
"""
Compile the category block lists.

    python3 blocklists/build.py out/            # every category
    python3 blocklists/build.py out/ adult drugs

For each category in sources.json: download the sources, normalise to bare lower-case domains,
drop entries whose parent domain is already listed, and write

    <cat>.txt.gz   one domain per line (what a person can read and diff)
    <cat>.bin      sorted big-endian uint64 = first 8 bytes of sha1(domain) (what devices load)
    index.json     {cat: {count, sha256_bin, built, vi, default}}

The .bin is the on-device format on every platform: 8 bytes per domain, binary search, and a
lookup for host "a.b.c.d" tries d, c.d, b.c.d, a.b.c.d. Collisions between 64-bit hashes are
astronomically unlikely and only ever cause an extra block, never an extra allow.
"""
import gzip, hashlib, io, json, os, re, struct, sys, tarfile, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
_DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?\.)+[a-z0-9-]{2,63}$")
_SKIP = {"localhost", "localhost.localdomain", "local", "broadcasthost", "ip6-localhost", "ip6-loopback",
         "0.0.0.0", "ip6-localnet", "ip6-mcastprefix", "ip6-allnodes", "ip6-allrouters", "ip6-allhosts"}


def fetch(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "greengate-lists/1.0"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(5 * (i + 1))
    raise last


def norm(line):
    s = line.strip().lower()
    if not s or s[0] in "#!;[":
        return None
    s = s.split("#", 1)[0].strip()
    parts = s.split()
    if len(parts) >= 2 and re.match(r"^(0\.0\.0\.0|127\.0\.0\.1|::1?|::)$", parts[0]):
        s = parts[1]                      # hosts format
    elif len(parts) > 1:
        return None
    s = s.lstrip("*.").lstrip(".").rstrip(".")
    if s.startswith("||"):                # adblock style ||domain^
        s = s[2:].rstrip("^")
    if s in _SKIP or not _DOMAIN.match(s):
        return None
    return s.encode("idna").decode("ascii") if any(ord(c) > 127 for c in s) else s


def domains_from(blob, fmt):
    out = set()
    if fmt == "ut1":
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
            for m in tf.getmembers():
                if m.isfile() and os.path.basename(m.name) == "domains":
                    for line in tf.extractfile(m).read().decode("utf-8", "replace").splitlines():
                        d = norm(line)
                        if d:
                            out.add(d)
        return out
    for line in blob.decode("utf-8", "replace").splitlines():
        d = norm(line)
        if d:
            out.add(d)
    return out


def reduce_subdomains(doms):
    """Drop a.b.com when b.com is listed: the lookup walks parents anyway."""
    keep = set()
    for d in sorted(doms, key=lambda x: x.count(".")):
        parts = d.split(".")
        if any(".".join(parts[i:]) in keep for i in range(1, len(parts) - 1)):
            continue
        keep.add(d)
    return keep


def h64(domain):
    return struct.unpack(">Q", hashlib.sha1(domain.encode()).digest()[:8])[0]


def build(cat, spec, outdir, log=print):
    doms = set()
    for src in spec["sources"]:
        try:
            blob = fetch(src["url"])
            got = domains_from(blob, src["format"])
            log("  %-80s %8d" % (src["url"], len(got)))
            doms |= got
        except Exception as e:
            log("  %-80s FAILED %s" % (src["url"], e))
    if not doms:
        raise RuntimeError("no source of %s could be read" % cat)
    doms = reduce_subdomains(doms)
    with gzip.open(os.path.join(outdir, cat + ".txt.gz"), "wt", encoding="utf-8", compresslevel=9) as f:
        f.write("\n".join(sorted(doms)) + "\n")
    hashes = sorted(h64(d) for d in doms)
    raw = struct.pack(">%dQ" % len(hashes), *hashes)
    with open(os.path.join(outdir, cat + ".bin"), "wb") as f:
        f.write(raw)
    return {"count": len(doms), "sha256_bin": hashlib.sha256(raw).hexdigest(),
            "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "vi": spec.get("vi", cat), "default": bool(spec.get("default"))}


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "out")
    os.makedirs(outdir, exist_ok=True)
    cfg = json.load(open(os.path.join(HERE, "sources.json"), encoding="utf-8"))
    wanted = sys.argv[2:] or list(cfg["categories"])
    index_path = os.path.join(outdir, "index.json")
    index = json.load(open(index_path)) if os.path.exists(index_path) else {}
    failed = []
    for cat in wanted:
        print(cat)
        try:
            index[cat] = build(cat, cfg["categories"][cat], outdir)
            print("  -> %d domains" % index[cat]["count"])
        except Exception as e:
            print("  -> FAILED: %s" % e)
            failed.append(cat)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=1, ensure_ascii=False)
    if failed:
        print("failed:", ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
