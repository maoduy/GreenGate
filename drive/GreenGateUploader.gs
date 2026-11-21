/**
 * GreenGate – nhận ảnh màn hình từ máy con và lưu vào thư mục Google Drive của bố mẹ.
 *
 * Cài một lần (3 phút), xem drive/README.md:
 *   1. Mở Google Sheet GreenGate → Tiện ích mở rộng → Apps Script, dán toàn bộ file này.
 *   2. Sửa FOLDER bên dưới thành link (hoặc id) thư mục Drive của bạn.
 *   3. Triển khai → Triển khai mới → Ứng dụng web: "Thực thi với tư cách: Tôi",
 *      "Ai có quyền truy cập: Bất kỳ ai" → Triển khai → chép URL (…/exec).
 *   4. Dán URL vào tab `settings` của Sheet: khoá `uploadUrl`.
 *   5. (Tuỳ chọn, để máy con cập nhật NGAY khi bạn sửa Sheet) sửa RELAY bên dưới thành địa chỉ
 *      relay GreenGate của nhà bạn, rồi trong trình soạn Apps Script chọn hàm `setupTrigger` và bấm
 *      Chạy (một lần). Mỗi lần Sheet thay đổi, script báo relay, relay báo máy con đọc lại Sheet.
 *
 * Script chạy với tài khoản của bạn nên máy con KHÔNG có quyền gì trên Drive ngoài việc gửi ảnh
 * vào đây. Mỗi máy một thư mục con, mỗi ngày một thư mục: GreenGate/<máy>/<YYYY-MM-DD>/<HH-MM-SS>.jpg
 */
var FOLDER = "https://drive.google.com/drive/folders/<ID-THU-MUC-CUA-BAN>";
var MAX_BYTES = 1.5 * 1024 * 1024;   // ảnh lớn hơn bị từ chối
var MAX_PER_HOUR = 30;               // mỗi máy
var CLEAN_EVERY = 20;                // dọn ảnh cũ sau mỗi N lần tải lên
var RELAY = "";                      // ví dụ "https://relay.greengate.example"; để trống = chỉ polling 60 s

function doPost(e) {
  try {
    var body = JSON.parse(e.postData && e.postData.contents || "{}");
    if (body.v !== 1 || !body.image) return out({ ok: false, error: "bad request" });
    var device = clean(body.device || "may-con");
    var reason = body.reason === "parent" ? "parent" : "schedule";
    var keepDays = Math.max(1, Math.min(365, parseInt(body.keepDays, 10) || 30));
    if (!rateOk(device)) return out({ ok: false, error: "too many uploads this hour" });

    var bytes = Utilities.base64Decode(body.image);
    if (bytes.length > MAX_BYTES) return out({ ok: false, error: "image too large" });
    if (bytes.length < 4 || (bytes[0] & 255) !== 0xFF || (bytes[1] & 255) !== 0xD8) return out({ ok: false, error: "not a JPEG" });

    var when = body.ts ? new Date(body.ts) : new Date();
    if (isNaN(when.getTime())) when = new Date();
    var tz = Session.getScriptTimeZone();
    var day = Utilities.formatDate(when, tz, "yyyy-MM-dd");
    var name = Utilities.formatDate(when, tz, "HH-mm-ss") + (reason === "parent" ? "-bo-me" : "") + ".jpg";

    var root = folderById(FOLDER);
    var dev = sub(root, device);
    var dir = sub(dev, day);
    var blob = Utilities.newBlob(bytes, "image/jpeg", name);
    var file = dir.createFile(blob);
    file.setDescription(JSON.stringify({ user: body.user || "", platform: body.platform || "", reason: reason }));

    var n = bump(device);
    if (n % CLEAN_EVERY === 0) cleanup(dev, keepDays);
    return out({ ok: true, id: file.getId(), name: name, path: root.getName() + "/" + device + "/" + day });
  } catch (err) {
    return out({ ok: false, error: String(err) });
  }
}

function doGet() {
  return out({ ok: true, service: "GreenGate uploader", folder: FOLDER ? "set" : "missing" });
}

// ---------------------------------------------------------------- helpers
function out(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }

function clean(s) { return String(s).replace(/[\\\/:*?"<>|]/g, "-").trim().slice(0, 60) || "may-con"; }

function folderById(linkOrId) {
  var m = /[-\w]{25,}/.exec(String(linkOrId));
  if (!m) throw new Error("FOLDER chưa được đặt");
  return DriveApp.getFolderById(m[0]);
}

function sub(parent, name) {
  var it = parent.getFoldersByName(name);
  return it.hasNext() ? it.next() : parent.createFolder(name);
}

function rateOk(device) {
  var cache = CacheService.getScriptCache();
  var key = "rate:" + device + ":" + Math.floor(Date.now() / 3600000);
  var n = parseInt(cache.get(key) || "0", 10) + 1;
  cache.put(key, String(n), 3600);
  return n <= MAX_PER_HOUR;
}

function bump(device) {
  var props = PropertiesService.getScriptProperties();
  var n = parseInt(props.getProperty("count:" + device) || "0", 10) + 1;
  props.setProperty("count:" + device, String(n));
  return n;
}

function cleanup(devFolder, keepDays) {
  var cutoff = new Date(Date.now() - keepDays * 86400000);
  var days = devFolder.getFolders();
  while (days.hasNext()) {
    var d = days.next();
    var dt = new Date(d.getName() + "T23:59:59");
    if (!isNaN(dt.getTime()) && dt < cutoff) d.setTrashed(true);
  }
}

// ---------------------------------------------------------------- push "sheet changed" to the relay
/** Chạy một lần từ trình soạn thảo (chọn hàm này rồi bấm Chạy): tạo trigger onChange. */
function setupTrigger() {
  if (!RELAY) throw new Error("Điền RELAY trước");
  var ss = SpreadsheetApp.getActive();
  ScriptApp.getProjectTriggers().forEach(function (t) { if (t.getHandlerFunction() === "onSheetChanged") ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger("onSheetChanged").forSpreadsheet(ss).onChange().create();
  ScriptApp.newTrigger("onSheetChanged").forSpreadsheet(ss).onEdit().create();
  onSheetChanged();   // báo thử ngay
  return "OK: relay sẽ được báo mỗi khi Sheet thay đổi";
}

/** Gọi bởi trigger. Gộp các lần sửa liên tiếp trong 3 giây thành một lần báo. */
function onSheetChanged() {
  if (!RELAY) return;
  var cache = CacheService.getScriptCache();
  if (cache.get("hint-sent")) return;          // vừa báo rồi, máy con sẽ đọc bản mới nhất
  cache.put("hint-sent", "1", 3);
  var id = SpreadsheetApp.getActive().getId();
  try {
    UrlFetchApp.fetch(RELAY.replace(/\/+$/, "") + "/v1/sheet/" + id + "/changed",
      { method: "post", muteHttpExceptions: true, payload: "{}", contentType: "application/json" });
  } catch (err) {
    console.warn("relay hint failed: " + err);
  }
}
