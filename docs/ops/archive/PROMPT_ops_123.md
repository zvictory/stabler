# Operasyon paketi — 1·Deploy → 2·Tenant menü düzeni → 3·Konteyner senkronu

> **✅ KOŞULDU — 2026-07-28.** İş 1 deploy edildi (yedek `/root/stabler-app-2026-07-28-1541.tgz`),
> İş 2 audit hedefle birebir çıktı (uygulama gerekmedi), İş 3'te sapmalı CI 0'dı.
> Dosya referans olarak duruyor; yeniden koşmak güvenli (idempotent) ama gereksiz.

Bu dosyanın tamamını Claude Code'a yapıştır, `~/frappe-bench-local/apps/stabler` içinden.
Üç iş sırayla; her işin sonunda çıktıyı göster. **ONAY yazan yerde bana sor, cevapsız geçme.**

---

# İŞ 1 — Deploy `80f1958`

## 1.0 durum

```bash
cd ~/frappe-bench-local/apps/stabler && git log --oneline -1 && git status --short | grep -v '^??' | head
```

Beklenen: HEAD `80f1958`, kirli izlenen dosya yok. Değilse dur, listeyi göster.
(Bu HEAD ayrıca şunları içerir: PI listesinde sevk/kalan/over-shipment kolonları,
PI formunda Sevkiyat eşleşmesi paneli, ve yeni `/imports/discrepancies` ekranı —
İş 1'in tarayıcı doğrulamasına şunu ekle: msa'da `#/imports/discrepancies` aç,
metrik çipleri gerçek sayılarla dolmalı ve bir sapan satırın CI/PI linkleri çalışmalı.)

## 1.1 ne gidiyor (son deploy'dan bu yana)

- `c885f78` + `fb37533` + `301351d` — **PI Group Container Status raporu onarımı**:
  fatal SQL kolonları (rapor şu an prod'da 500 atıyor), spec kova haritası, gerçek
  FCL, çalışan filtreler, çift satırlı ızgara (+tutar satırı), grup kodu grubu açar, i18n.
- `afe8fb9` — **PI sevkiyat UX**: PI listesinde Sevk % / Kalan / Over-shipment
  kolonları, PI formunda Sevkiyat eşleşmesi paneli.
- `80f1958` — **`/imports/discrepancies`**: PI ↔ CI sapmalar ekranı (anlaşma vs
  gerçek sevkiyat, metrik çipleri, CI/PI linkleri). PI-vs-PI compare kaldırıldı.
- Önceki hotfix'ler zaten canlıdaysa rsync fark göndermez — rsync idempotent.

## 1.2 yedek → dry-run → rsync → build

```bash
ssh ice-production 'tar czf /root/stabler-app-$(date +%F-%H%M).tgz -C /home/frappe/frappe-bench/apps stabler && ls -lht /root/stabler-app-*.tgz | head -1'

cd ~/frappe-bench-local/apps
rsync -rltznv --no-owner --no-group \
  --exclude-from=stabler/.rsync-exclude \
  stabler/ ice-production:/home/frappe/frappe-bench/apps/stabler/
# Exclude listesi TEK yerde durur: apps/stabler/.rsync-exclude (CLAUDE.md kuralı).
# Buraya satır satır kopyalama — 2026-07-28'de buradaki kopya eksik çıktı.
```

Dry-run çıktısını göster; kardeş dizin/`stable-erp-website/` görürsen dur.
Sonra aynı komut `n`+`v` olmadan (`-rltz`), ardından:

```bash
ssh ice-production 'chown -R frappe:frappe /home/frappe/frappe-bench/apps/stabler'
ssh ice-production 'cd /home/frappe/frappe-bench && bench build --app stabler'
```

## 1.3 migrate (idempotent — v59 emniyeti) + restart

Önceki deploy'un v59'u migrate edip etmediği belirsiz; patch'ler guard'lı,
7 sitede koşmak güvenli:

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && for s in anjan dts horeca laminor mikas msa smartbox; do
  echo "=== $s ==="; bench --site "$s.erpstable.com" migrate 2>&1 | tail -3; done'
ssh ice-production 'cd /home/frappe/frappe-bench && bench restart'
```

## 1.4 doğrula (msa, salt okuma)

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com console' <<'PY'
import frappe
frappe.set_user("Administrator")
company = frappe.get_all("Company", pluck="name", limit=1)[0]
from stabler.api.reports import get_pi_group_container_status_report as rep
r = rep(company)
print("gruplar:", r["totals"]["group_count"], "| konteyner:", r["totals"]["grand_containers"])
print("kovalar:", r["totals"]["grand_buckets"])
print("tutar kovalari:", {k: round(v, 2) for k, v in r["totals"]["grand_amounts"].items()})
# durusluk: toplam = kova toplamlari
assert r["totals"]["grand_containers"] == sum(r["totals"]["grand_buckets"].values())
for row in r["rows"]:
    assert row["container_total"] == sum(row["buckets"].values())
print("TUTARLILIK OK — toplam = kovalar toplami, her satirda")
PY
```

Tarayıcı: `https://msa.erpstable.com/stabler#/reports/pi-group-container-status`
→ çift satırlı tablo gerçek gruplarla dolu, alt satırlar $ tutarları, filtreler
gerçekten daraltıyor (bir tarih aralığı seç, satır sayısı değişmeli).

---

# İŞ 2 — Onaylı tenant × modül düzenini uygula

Kod yok, restart yok — sadece `Stabler Settings` verisi. Geri alınabilir
(modül kapatmak veri silmez).

## 2.1 önce AUDIT (salt okuma, 7 site)

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && for s in anjan dts horeca laminor mikas msa smartbox; do
  echo "=== $s ==="; bench --site "$s.erpstable.com" execute stabler.api.organization.audit_company_modules 2>&1 | tail -8; done'
```

Çıktıyı bana göster — **şirket adlarını buradan al** (aşağıdaki komutlarda
`<COMPANY>` yerine geçecek). Bir sitede birden çok şirket varsa dur ve sor.

## 2.2 fark tablosu

Audit çıktısı ile hedefi karşılaştırıp bana kısa tablo göster:
"site → kapanacak modüller / açılacak modüller". **ONAY almadan 2.3'e geçme.**

Hedef (onaylı):

| Site | Açık modüller (diğer her şey KAPALI) |
|---|---|
| anjan | money, sales, purchasing, inventory, manufacturing, hr |
| msa | money, sales, purchasing, inventory, imports |
| mikas | money, sales, purchasing, crm, tender |
| dts | money, sales, purchasing, inventory |
| horeca | money, sales, service, field_sales, inventory |
| laminor | money, sales, purchasing, inventory, imports |
| smartbox | HEPSİ (18/18 — test ortamı; `agreements` dahil) |

## 2.3 uygula (site başına tek komut; `<COMPANY>` = audit'teki ad)

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site anjan.erpstable.com execute stabler.api.organization.update_company_modules --kwargs "{\"company\": \"<COMPANY>\", \"money\": 1, \"sales\": 1, \"purchasing\": 1, \"inventory\": 1, \"manufacturing\": 1, \"hr\": 1, \"stock_reservation\": 0, \"compliance\": 0, \"field_sales\": 0, \"marketing\": 0, \"crm\": 0, \"service\": 0, \"bpm\": 0, \"remittance\": 0, \"installment\": 0, \"agreements\": 0, \"tender\": 0, \"imports\": 0}"'

ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com execute stabler.api.organization.update_company_modules --kwargs "{\"company\": \"<COMPANY>\", \"money\": 1, \"sales\": 1, \"purchasing\": 1, \"inventory\": 1, \"manufacturing\": 0, \"hr\": 0, \"stock_reservation\": 0, \"compliance\": 0, \"field_sales\": 0, \"marketing\": 0, \"crm\": 0, \"service\": 0, \"bpm\": 0, \"remittance\": 0, \"installment\": 0, \"agreements\": 0, \"tender\": 0, \"imports\": 1}"'

ssh ice-production 'cd /home/frappe/frappe-bench && bench --site mikas.erpstable.com execute stabler.api.organization.update_company_modules --kwargs "{\"company\": \"<COMPANY>\", \"money\": 1, \"sales\": 1, \"purchasing\": 1, \"inventory\": 0, \"manufacturing\": 0, \"hr\": 0, \"stock_reservation\": 0, \"compliance\": 0, \"field_sales\": 0, \"marketing\": 0, \"crm\": 1, \"service\": 0, \"bpm\": 0, \"remittance\": 0, \"installment\": 0, \"agreements\": 0, \"tender\": 1, \"imports\": 0}"'

ssh ice-production 'cd /home/frappe/frappe-bench && bench --site dts.erpstable.com execute stabler.api.organization.update_company_modules --kwargs "{\"company\": \"<COMPANY>\", \"money\": 1, \"sales\": 1, \"purchasing\": 1, \"inventory\": 1, \"manufacturing\": 0, \"hr\": 0, \"stock_reservation\": 0, \"compliance\": 0, \"field_sales\": 0, \"marketing\": 0, \"crm\": 0, \"service\": 0, \"bpm\": 0, \"remittance\": 0, \"installment\": 0, \"agreements\": 0, \"tender\": 0, \"imports\": 0}"'

ssh ice-production 'cd /home/frappe/frappe-bench && bench --site horeca.erpstable.com execute stabler.api.organization.update_company_modules --kwargs "{\"company\": \"<COMPANY>\", \"money\": 1, \"sales\": 1, \"purchasing\": 0, \"inventory\": 1, \"manufacturing\": 0, \"hr\": 0, \"stock_reservation\": 0, \"compliance\": 0, \"field_sales\": 1, \"marketing\": 0, \"crm\": 0, \"service\": 1, \"bpm\": 0, \"remittance\": 0, \"installment\": 0, \"agreements\": 0, \"tender\": 0, \"imports\": 0}"'

ssh ice-production 'cd /home/frappe/frappe-bench && bench --site laminor.erpstable.com execute stabler.api.organization.update_company_modules --kwargs "{\"company\": \"<COMPANY>\", \"money\": 1, \"sales\": 1, \"purchasing\": 1, \"inventory\": 1, \"manufacturing\": 0, \"hr\": 0, \"stock_reservation\": 0, \"compliance\": 0, \"field_sales\": 0, \"marketing\": 0, \"crm\": 0, \"service\": 0, \"bpm\": 0, \"remittance\": 0, \"installment\": 0, \"agreements\": 0, \"tender\": 0, \"imports\": 1}"'

ssh ice-production 'cd /home/frappe/frappe-bench && bench --site smartbox.erpstable.com execute stabler.api.organization.update_company_modules --kwargs "{\"company\": \"<COMPANY>\", \"money\": 1, \"sales\": 1, \"purchasing\": 1, \"inventory\": 1, \"manufacturing\": 1, \"hr\": 1, \"stock_reservation\": 1, \"compliance\": 1, \"field_sales\": 1, \"marketing\": 1, \"crm\": 1, \"service\": 1, \"bpm\": 1, \"remittance\": 1, \"installment\": 1, \"agreements\": 1, \"tender\": 1, \"imports\": 1}"'
```

## 2.4 doğrula

Audit'i tekrar koş (2.1'deki komut) → her site hedef tabloyla birebir olmalı.
Tarayıcıdan iki nokta kontrolü (admin OLMAYAN kullanıcıyla):
mikas'ta menüde Tender var / Manufacturing yok; msa'da Imports var / Tender yok.
(Kullanıcıların sayfa yenilemesi gerekir — boot payload'ı yeniden çekilmeli.)

---

# İŞ 3 — msa: geride kalan konteynerleri senkronla

Ölçülen sapma: 12 geride / 0 ileride, 4 CI'da. Sync yalnız GERİDE olanı iter,
hattı istasyon istasyon `doc.save()` ile yürür (controller kuralları çalışır),
hata olursa rollback + rapor.

## 3.1 yeniden ölç (salt okuma — sayılar değişmiş olabilir)

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com console' <<'PY'
import frappe
frappe.set_user("Administrator")
from stabler.stabler.imports_module import sea_lifecycle as sl
out = []
for ci in frappe.get_all("Commercial Invoice", fields=["name", "status"], limit_page_length=0):
    cnts = frappe.get_all("Import Container", filters={"commercial_invoice": ci.name},
                          fields=["name", "container_number", "status"], limit_page_length=0)
    if not cnts:
        continue
    s = sl.summarise(ci.status, cnts)
    if not s["in_sync"]:
        out.append((ci.name, ci.status, s["behind"], s["ahead"]))
print("sapmali CI:", len(out))
for name, st, b, a in out:
    print(f"  {name:24} CI={st:26} geride={b} ileride={a}")
PY
```

**İleride (ahead) > 0 görürsen DUR** — o elle çözülür, sync'e girmez.

## 3.2 dry-run (CI başına; 3.1'deki isimlerle)

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com console' <<'PY'
import frappe, json
frappe.set_user("Administrator")
from stabler.api.imports import sync_containers_to_ci
for ci in [<CI_LISTESI>]:  # 3.1 çıktısındaki isimler, ör: "CI-2026-00057", ...
    r = sync_containers_to_ci(ci, dry_run=1)
    print(ci, "->", json.dumps(r["planned"], indent=1)[:400])
PY
```

Planı bana göster: hangi konteyner hangi istasyonlardan geçecek. **ONAY al.**

## 3.3 uygula + doğrula

Aynı blok `dry_run=0` ile. Sonra 3.1'i tekrar koş → **sapmalı CI: 0** olmalı.
`failed` boş değilse hangi konteyner hangi geçişte takıldı, bana getir —
controller bir kuralı koruyordur, elle bakarız.

---

# Yapma

- İş 1'de dry-run çıktısını göstermeden gerçek rsync'e geçme.
- İş 2'de fark tablosunu göstermeden uygulama; `<COMPANY>` yerinde site adı değil
  **audit'teki şirket adı** olacak.
- İş 3'te ileride konteyner varken sync koşma; dry-run onayı olmadan `dry_run=0` yok.
