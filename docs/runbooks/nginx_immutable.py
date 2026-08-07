#!/usr/bin/env python3
"""Faz 2 — hash'li build ciktisina immutable cache, 7 stabler kiracisinda.

Idempotent: blok zaten varsa dosyaya dokunmaz.
Yedek: <conf>.bak-immutable-<ts> (yalniz gercekten degistirilen dosyalar icin).
"""

import re
import shutil
import sys
import time

CONFS = [
	"anjan.erpstable.com-erpnext.conf",
	"dts.erpstable.com-erpnext.conf",
	"horeca.erpstable.com-erpnext.conf",
	"laminor.erpstable.com.conf",
	"mikas.erpstable.com.conf",
	"msa.erpstable.com-erpnext.conf",
	"smartbox.erpstable.com.conf",
]

BLOCK = """    # Hash'li build ciktisi: dosya adi icerik hash'i tasir -> bayat kod riski yok.
    # Hash'siz yollar (vendor/, css, gorseller) asagidaki /assets blogundan
    # servis edilmeye devam eder; onlara immutable vermek deploy sonrasi bayat
    # dosya demek olurdu.
    location ~ ^/assets/[^/]+/dist/ {
        try_files $uri =404;
        add_header Cache-Control "public, max-age=31536000, immutable";
    }

"""

ANCHOR = re.compile(r"^([ \t]*)location /assets \{", re.M)
ts = time.strftime("%Y%m%d-%H%M%S")
changed, skipped, failed = [], [], []

for name in CONFS:
	path = "/etc/nginx/conf.d/" + name
	try:
		with open(path) as fh:
			src = fh.read()
	except OSError as exc:
		failed.append((name, str(exc)))
		continue

	if "dist/" in src and "immutable" in src:
		skipped.append(name)
		continue

	m = ANCHOR.search(src)
	if not m:
		failed.append((name, "location /assets bulunamadi"))
		continue

	shutil.copy2(path, f"{path}.bak-immutable-{ts}")
	out = src[: m.start()] + BLOCK + src[m.start() :]
	with open(path, "w") as fh:
		fh.write(out)
	changed.append(name)

print(f"degisti  ({len(changed)}): {', '.join(changed) or '-'}")
print(f"atlandi  ({len(skipped)}): {', '.join(skipped) or '-'}")
print(f"BASARISIZ({len(failed)}): {failed or '-'}")
sys.exit(1 if failed else 0)
