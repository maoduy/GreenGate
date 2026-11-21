#!/bin/bash
# Build greengate_<version>_all.deb from the repo. Usage: linux/build-deb.sh [outdir]
# The package carries the proxy, the Linux scripts and the setup wizard; mitmproxy is
# installed into a venv by postinst (no Debian package of mitmproxy 12 exists).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$HERE/.." && pwd)
OUT=${1:-$ROOT/dist}; mkdir -p "$OUT"
VER=$(python3 -c 'import re;print(re.search(r"VERSION = \"([^\"]+)\"", open("'"$ROOT"'/proxy/greengate.py").read()).group(1))')
PKG=$(mktemp -d); trap 'rm -rf "$PKG"' EXIT
install -d "$PKG/DEBIAN" "$PKG/usr/share/greengate/proxy" "$PKG/usr/share/greengate/linux" "$PKG/usr/share/greengate/agent"
cp "$ROOT"/proxy/greengate.py "$ROOT"/proxy/policy.py "$ROOT"/proxy/timewindow.py "$ROOT"/proxy/sheetlog.py "$PKG/usr/share/greengate/proxy/"
cp "$HERE"/*.sh "$HERE"/*.service "$HERE"/*.timer "$PKG/usr/share/greengate/linux/"
[[ -d "$ROOT/agent" ]] && cp -r "$ROOT"/agent/* "$PKG/usr/share/greengate/agent/" 2>/dev/null || true
chmod 755 "$PKG"/usr/share/greengate/linux/*.sh
cat > "$PKG/DEBIAN/control" <<CTL
Package: greengate
Version: $VER
Section: net
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-venv, nftables, curl, libnss3-tools, systemd
Maintainer: GreenGate <greengate@users.noreply.github.com>
Homepage: https://github.com/maoduy/GreenGate
Description: GreenGate - bộ lọc web cho tài khoản của con, điều khiển bằng Google Sheet
 Chỉ cho phép (hoặc chặn) các trang web và kênh YouTube ghi trong Google Sheet của
 phụ huynh. Proxy chạy trong suốt bằng nftables cho các tài khoản được chọn.
CTL
cat > "$PKG/DEBIAN/postinst" <<'PI'
#!/bin/bash
set -e
# The real work (sheet id, accounts) needs answers, so installation is: 
#   sudo greengate-setup --sheet <link> --users <an,binh>
cat > /usr/local/bin/greengate-setup <<'S'
#!/bin/bash
exec /usr/share/greengate/linux/install.sh "$@"
S
chmod 755 /usr/local/bin/greengate-setup
echo "GreenGate đã được cài. Bước cuối: sudo greengate-setup --sheet <link Google Sheet> --users <tài khoản của con>"
PI
cat > "$PKG/DEBIAN/prerm" <<'PR'
#!/bin/bash
[ -x /usr/local/lib/greengate/uninstall.sh ] && /usr/local/lib/greengate/uninstall.sh || true
rm -f /usr/local/bin/greengate-setup
exit 0
PR
chmod 755 "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/prerm"
dpkg-deb --build --root-owner-group "$PKG" "$OUT/greengate_${VER}_all.deb" >/dev/null
echo "$OUT/greengate_${VER}_all.deb"
