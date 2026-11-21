import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "proxy"))
import policy
fails = 0
def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails += 1
s = policy.parse_settings([["Khoá", "Giá trị"], ["chế độ", "chặn danh sách"], ["danh mục", "adult, gambling"],
                           ["từ khoá", "+default, roblox"], ["safesearch", "tắt"], ["youtube", "hạn chế"],
                           ["giờ", "07:00-21:00"], ["refreshSeconds", "2 phút"], ["shorts", "cho phép"]])
check("vietnamese aliases", s.mode == "blacklist" and s.categories == ["adult", "gambling"] and not s.safesearch
      and s.youtube == "restricted" and s.schedule == "07:00-21:00" and s.refreshSeconds == 120 and not s.shorts)
d = policy.Settings()
check("defaults whitelist", d.mode == "whitelist" and d.effective_categories() == () and d.safesearch and d.refreshSeconds == 60)
d.mode = "blacklist"
check("blacklist default categories", d.effective_categories() == policy.DEFAULT_CATEGORIES)
check("youtube default follows channels", d.effective_youtube(True) == "channels" and d.effective_youtube(False) == "restricted")

# Drive upload settings (SPEC §8): defaults, aliases, validation
d2 = policy.Settings()
check("screenshotEvery default 15", d2.screenshotEvery == 15 and d2.screenshotHours == "" and d2.uploadUrl == "" and d2.driveFolder == "")
s2 = policy.parse_settings([["chụp mỗi", "30 phút"], ["giờ chụp", "07:00-22:00"],
                            ["drive", "https://script.google.com/macros/s/AKfycb123/exec"],
                            ["thư mục drive", "https://drive.google.com/drive/folders/1bmX"]])
check("drive aliases", s2.screenshotEvery == 30 and s2.screenshotHours == "07:00-22:00"
      and s2.uploadUrl.endswith("/exec") and s2.driveFolder.startswith("https://drive.google.com/"))
s3 = policy.parse_settings([["uploadUrl", "ftp://nope"], ["screenshotEvery", "0"]])
check("uploadUrl must be https", s3.uploadUrl == "" and any("uploadUrl" in e for e in s3.errors) and s3.screenshotEvery == 0)
s4 = policy.parse_settings([["uploadUrl", "http://127.0.0.1:18796/exec"]])
check("loopback uploadUrl allowed for tests", s4.uploadUrl == "http://127.0.0.1:18796/exec")
k = policy.Keywords(["roblox"])
check("keyword host substring", k.hit_url("www.pornhub.com", "/") == "porn")
check("keyword no false positive sussex", k.hit_url("www.sussex.ac.uk", "/") is None)
check("keyword in google query", k.hit_url("www.google.com", "/search?q=phim+sex+viet") in ("phim sex", "sex viet"))
check("keyword essex ok", k.hit_url("www.google.com", "/search?q=essex+history") is None)
check("keyword 18+", k.hit_url("www.google.com", "/search?q=18%2B+movies") == "18+")
check("keyword extra token in path", k.hit_url("example.com", "/roblox/x") == "roblox")
check("keyword youtube search", k.hit_url("www.youtube.com", "/results?search_query=sexy+dance") == "sexy")
check("safesearch google", policy.safesearch_rewrite("www.google.com", "/search?q=cats") == "/search?q=cats&safe=active")
check("safesearch google already", policy.safesearch_rewrite("www.google.com", "/search?q=cats&safe=active") is None)
check("safesearch bing", policy.safesearch_rewrite("www.bing.com", "/search?q=x") == "/search?q=x&adlt=strict")
check("safesearch ddg", policy.safesearch_rewrite("duckduckgo.com", "/?q=x") == "/?q=x&kp=1")
check("safesearch untouched host", policy.safesearch_rewrite("www.ted.com", "/search?q=x") is None)
check("looks_like_settings", policy.looks_like_settings([["mode", "blacklist"]]) and not policy.looks_like_settings([["Trang web", "x"], ["bbc.com", ""]]))
# category store with a tiny hand-made list
import struct, tempfile
tmp = tempfile.mkdtemp(); os.makedirs(os.path.join(tmp, "lists"))
hashes = sorted(policy.h64(x) for x in ["bad.example", "evil.org"])
open(os.path.join(tmp, "lists", "adult.bin"), "wb").write(struct.pack(">%dQ" % len(hashes), *hashes))
cs = policy.CategoryStore(tmp, log=lambda *a: None, base_url="file:///nonexistent/")
cs.set_enabled(["adult"])
check("category parent match", cs.match("x.y.bad.example") == "adult" and cs.match("evil.org") == "adult")
check("category no match", cs.match("good.example") is None and cs.match("notbad.example") is None)
# deepInspect (SPEC §2): default on; Vietnamese alias; search engines always decrypted
d4 = policy.Settings()
check("deepInspect default on", d4.deepInspect and d4.to_dict()["deepInspect"] is True)
s4 = policy.parse_settings([["kiểm tra sâu", "tắt"]])
s5 = policy.parse_settings([["deepInspect", "on"]])
check("deepInspect alias off/on", s4.deepInspect is False and s5.deepInspect is True)
check("safesearch_host", policy.safesearch_host("www.google.com.vn") and policy.safesearch_host("duckduckgo.com")
      and policy.safesearch_host("www.bing.com") and not policy.safesearch_host("www.ted.com")
      and not policy.safesearch_host("googleapis.com"))

# sheet tab map (SPEC §1): htmlview items -> {name: gid}; export-by-gid URL; '' for a missing tab
html = ('items.push({name: "websites", pageUrl: "https:\\/\\/x\\/htmlview\\/sheet?headers\\x3dtrue&gid=0", gid: "0",initialSheet: ("0" == gid)});'
        'items.push({name: "c\\u00e0i \\x26 \\"t\\"", pageUrl: "u", gid: "12",initialSheet: false});')
g = policy.sheet_tab_gids(html)
check("sheet_tab_gids", g == {"websites": "0", 'cài & "t"': "12"} and policy.sheet_tab_gids("") == {})
check("sheet_tab_url", policy.sheet_tab_url("S", "websites", g).endswith("/export?format=csv&gid=0")
      and policy.sheet_tab_url("S", "apps", g) == "" and "gviz" in policy.sheet_tab_url("S", "apps"))

print("%d failures" % fails); sys.exit(1 if fails else 0)
