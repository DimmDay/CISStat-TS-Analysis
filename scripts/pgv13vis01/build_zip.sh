#!/usr/bin/env bash
# scripts/pgv13vis01/build_zip.sh
#
# PGV13-VIS-01 — сборка поставки в download/ (паттерн VIS-02):
# ZIP файлов из scripts/pgv13vis01/files.txt + CRC32 + SHA256.
# Запуск из корня checkout. Агент коммит/push не выполняет.

set -euo pipefail

ZIP_PATH="${1:-/home/z/my-project/download/pgv13-vis01-73ff44d.zip}"
MANIFEST="scripts/pgv13vis01/files.txt"

# Манифест + worklog должны существовать; все файлы манифеста — тоже.
test -f "$MANIFEST"

rm -f "$ZIP_PATH"
# Детерминированный zip: только файлы манифеста (worklog — в нём же).
zip -q "$ZIP_PATH" -@ < "$MANIFEST"

# Целостность: CRC32 + SHA256 рядом с ZIP (паттерн VIS-02).
python3 - "$ZIP_PATH" << 'PYEOF'
import hashlib, sys, zlib
path = sys.argv[1]
data = open(path, "rb").read()
crc = f"{zlib.crc32(data) & 0xFFFFFFFF:08x}"
sha = hashlib.sha256(data).hexdigest()
open(path + ".crc32", "w").write(crc + "\n")
open(path + ".sha256", "w").write(sha + "  " + path.split("/")[-1] + "\n")
print(f"ZIP {path}: {len(data)} bytes, crc32={crc}, sha256={sha[:16]}…")
PYEOF

# Самопроверка содержимого: список совпадает с манифестом (+ worklog).
unzip -l "$ZIP_PATH" | tail -n +4 | awk '{print $4}' | grep -v '^$' | sort > /tmp/zip_contents.txt
# Worklog включён в манифест; вторым zip-вызовом дублирование безопасно.
sort "$MANIFEST" > /tmp/manifest_sorted.txt
if diff -q /tmp/manifest_sorted.txt /tmp/zip_contents.txt > /dev/null; then
  echo "ZIP contents match manifest: OK"
else
  echo "ZIP CONTENTS MISMATCH:"; diff /tmp/manifest_sorted.txt /tmp/zip_contents.txt; exit 1
fi
