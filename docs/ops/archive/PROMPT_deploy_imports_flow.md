# Deploy prompt — Stabler `c12530e` (MSA imports workflow panosu)

Bu dosyanın tamamını Claude Code'a yapıştır, `~/frappe-bench-local/apps/stabler` içinden.
Sıradan çıkma, her adımın çıktısını göster, ilk hatada dur.

**Seed YOK** — msa'da gerçek veri zaten var; sadece kod gidiyor, pano gerçek
sayılarla dolar. Şema değişikliği yok, migrate gerekmez.

## Adım 0 — durum

```bash
cd ~/frappe-bench-local/apps/stabler && git log --oneline -1 && git status --short | grep -v '^??' | head
```

Beklenen: HEAD `c12530e`, kirli izlenen dosya yok. Değilse listeyi göster ve dur.

## Ne gidiyor

Bir önceki deploy'dan (funnel v2 canlı — mikas'ta görüldü) bu yana üç commit:

- `01a29cf` — tender: huni sayısı tıklanınca **tam o kayıtlar** (My Tenders `?funnel_stage=`)
- `571dcf0` — CRM Deal `:Company` default onarımı (başka oturum)
- `c12530e` — **MSA imports workflow panosu**: `/imports/dashboard` tepesine
  kontrol panosu — PI / CI / Konteyner / TIR satırları, durum çipleri
  (tıkla → kendi listesi `?status=` ile), deniz sapması + çıkış kapısı rozetleri,
  GRN/LCV/gümrük kuyruğu. Salt-okunur `imports_flow` ucu.

## Adım 1 — yedek

```bash
ssh ice-production 'tar czf /root/stabler-app-$(date +%F-%H%M).tgz -C /home/frappe/frappe-bench/apps stabler && ls -lht /root/stabler-app-*.tgz | head -1'
```

## Adım 2 — rsync DRY RUN (bench `apps/` dizininden, `-v` şart)

```bash
cd ~/frappe-bench-local/apps
rsync -rltznv --no-owner --no-group \
  --exclude '.git' --exclude 'node_modules' --exclude 'dist' \
  --exclude '__pycache__' --exclude '*.pyc' --exclude '.claude' \
  --exclude '.tx_*.json' --exclude 'graphify-out' --exclude '.smoke' \
  --exclude 'tests' --exclude '*.tgz' --exclude '.DS_Store' \
  --exclude '.worktrees' --exclude '.superpowers' --exclude '.obsidian' \
  --exclude 'scratch' \
  stabler/ ice-production:/home/frappe/frappe-bench/apps/stabler/
```

Kardeş dizin veya `stable-erp-website/` görürsen **dur**. Özeti göster.

## Adım 3 — rsync + chown + build + restart

```bash
# ayni komut n ve v olmadan (-rltz), sonra:
ssh ice-production 'chown -R frappe:frappe /home/frappe/frappe-bench/apps/stabler'
ssh ice-production 'cd /home/frappe/frappe-bench && bench build --app stabler'
ssh ice-production 'cd /home/frappe/frappe-bench && bench restart'
```

Migrate yok (patches.txt değişmedi). Restart 7 tenant'ta kısa kesinti —
düşük trafik anı seç.

## Adım 4 — ucu gerçek veriyle doğrula (msa, salt okuma)

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com console' <<'PY'
import frappe
frappe.set_user("Administrator")
company = frappe.get_all("Company", pluck="name", limit=1)[0]
from stabler.api.imports import imports_flow
r = imports_flow(company)
print("kpi   :", r["kpi"])
print("ci    :", r["ci"])
print("trucks:", r["trucks"])
print("drift :", r["drift"], " gate:", r["gate"])
print("grn   :", r["grn"], " lcv:", r["lcv"])
# tutarlilik: chip toplamlari = dogrudan sayimlar
assert sum(r["ci"].values()) == frappe.db.count("Commercial Invoice", {"company": company, "docstatus": ["<", 2]})
assert sum(r["trucks"].values()) == frappe.db.count("Import Truck", {"company": company, "docstatus": ["<", 2]})
print("TUTARLILIK OK — chip toplamlari listeyle birebir")
PY
```

Beklenen: gerçek sayılar (CI ~244, drift daha önce ölçülen 12 geride / 0 ileride
civarı) ve `TUTARLILIK OK`.

## Adım 5 — tarayıcı (msa, admin olmayan Imports rollü kullanıcı)

`https://msa.erpstable.com/stabler#/imports/dashboard`:

1. Tepe: 4 KPI kartı (açık PI · denizde CI · yolda TIR · **kapıda bloklu**).
2. "İthalat iş akışı" kartı: PI / CI / Konteyner / TIR satırları, durum çipleri
   gerçek sayılarla.
3. **Bir çipe tıkla** (ör. CI satırında `IN_TRANSIT`) → CI listesi o status
   filtresiyle açılmalı ve **listedeki kayıt sayısı = çipteki sayı** olmalı.
   Aynısını TIR'da bir status ve PI'da `CONFIRMED` ile tekrarla.
4. CI satırında sarı "N konteyner faturadan geride" rozeti (drift ölçümündeki
   sayıyla aynı olmalı).
5. Dil ru/uz → yeni metinler çevrili.

## Geri alma

Adım 1 tar'ı → chown → `bench build --app stabler` → `bench restart`.

## Yapma

- Adım 2 çıktısını göstermeden Adım 3'e geçme.
- Adım 4'teki tutarlılık assert'lerini atlama — panonun tek varlık sebebi
  sayıların listeyle birebir olması.
- Çip doğrulamasını admin ile yapma (adminde her şey görünür, rol filtresi test edilmez).
