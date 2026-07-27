# Deploy prompt — Stabler `f291556` (PI + CI sütun düzeni)

Bu dosyanın tamamını Claude Code'a yapıştır, `~/frappe-bench-local/apps/stabler` içinden.
Sıradan çıkma, ilk hatada dur.

---

## Ne gidiyor

Tek commit: **`f291556`** — Proforma ve Commercial Invoice listelerinde her
metrik kendi sütununa alındı, sıralama ve toplam satırı eklendi.

Değişen dosyalar:
- `stabler/api/imports.py` — `list_commercial_invoices`: PI ref + TIR sayısı + sunucu tarafı sıralama
- `stabler/public/js/pages/imports/ProformaInvoices.vue`
- `stabler/public/js/pages/imports/CommercialInvoices.vue`
- `stabler/translations/{en,ru,uz,uzc,tr}.csv` (13 yeni string × 5 dil)

## Şema etkisi

**Yok.** `patches.txt` ve doctype JSON'ları değişmedi.
→ **`bench migrate` ÇALIŞTIRMA.**

Backend değişikliği yalnızca bir SELECT sorgusu; yeni alan/kolon eklenmiyor.
`custom_proforma_invoice` alanı `frappe.db.has_column` ile korunuyor, yani o
alanın olmadığı bir sitede sorgu yine çalışır ve `PI ref` boş görünür.

## Adım 1 — yedek

```bash
ssh ice-production 'tar czf /root/stabler-app-$(date +%F-%H%M).tgz -C /home/frappe/frappe-bench/apps stabler && ls -lht /root/stabler-app-*.tgz | head -1'
```

## Adım 2 — rsync DRY RUN

Bench **`apps/`** dizininden. `apps/stabler/` içinden çalıştırırsan `stabler/`
iç Python modülüne çözülür ve sahte toplu silme listesi üretir.

```bash
cd ~/frappe-bench-local/apps
rsync -rltzn --no-owner --no-group \
  --exclude '.git' --exclude 'node_modules' --exclude 'dist' \
  --exclude '__pycache__' --exclude '*.pyc' --exclude '.claude' \
  --exclude '.tx_*.json' --exclude 'graphify-out' --exclude '.smoke' \
  --exclude 'tests' --exclude '*.tgz' --exclude '.DS_Store' \
  --exclude '.worktrees' --exclude '.superpowers' --exclude '.obsidian' \
  stabler/ ice-production:/home/frappe/frappe-bench/apps/stabler/
```

Kardeş dizin veya `stable-erp-website/` görürsen **dur**. Özeti bana göster.

## Adım 3 — rsync + chown

Aynı komut `n` olmadan (`-rltz`), sonra:

```bash
ssh ice-production 'chown -R frappe:frappe /home/frappe/frappe-bench/apps/stabler'
```

## Adım 4 — build

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench build --app stabler'
```

## Adım 5 — restart

`.py` değişti, bu yüzden restart **zorunlu**. 7 tenant'ta kısa kesinti olur —
düşük trafikli bir an seç.

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench restart'
```

## Adım 6 — backend duman testi

Yeni alanların gerçekten döndüğünü doğrula:

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com console' <<'PY'
from stabler.api import imports
res = imports.list_commercial_invoices(company="MSA", limit_page_length=3)
for r in res["rows"]:
    print(r["ci_number"], "| PI:", r.get("proforma_ref"), "| knt:", r["container_count"],
          "| TIR:", r.get("truck_count"), "| GRN:", r["has_grn"])
print("--- siralama testi (en buyuk kg) ---")
res2 = imports.list_commercial_invoices(company="MSA", limit_page_length=3,
                                        sort_by="total_kg", sort_dir="desc")
print([r["total_kg"] for r in res2["rows"]])
print("--- gecersiz sort_by guvenli mi ---")
res3 = imports.list_commercial_invoices(company="MSA", limit_page_length=1,
                                        sort_by="ci.name; DROP TABLE x--", sort_dir="asc")
print("OK, satir sayisi:", len(res3["rows"]))
PY
```

Beklenen: `proforma_ref` ve `truck_count` dolu geliyor, kg sıralaması azalan,
geçersiz `sort_by` hata vermeden varsayılana düşüyor (whitelist çalışıyor).

## Adım 7 — göz kontrolü

`https://msa.erpstable.com/stabler#/imports/proformas` (hard refresh: Cmd+Shift+R)

1. Sütunlar: **PI № / vendor · PI Date · Items · Boxes · kg · Agreed / gap ·
   Invoiced % · Status**. Kalem, kutu ve kg ayrı ayrı, sağa dayalı, rakamlar
   dikey hizalı.
2. Vendor kısa kod rozeti (`HMA`, `MIRHA`, `FAIR`); üstüne gelince tam ad tooltip.
3. Tarihin altında yaş (`82 days`).
4. `Agreed / gap`: üstte tutar, altında fark. Farkı olmayan satırda **`0`**
   yazıyor, düz yazı yok. `Ref: PI-2026-000xx` **hiçbir yerde görünmüyor.**
5. Başlıklara tıkla — sıralama çalışıyor, ok yönü değişiyor.
6. En altta **toplam satırı**: PI sayısı, vendor sayısı, kalem/kutu/kg toplamı,
   toplam tutar ve toplam fark.

Sonra `#/imports/commercial-invoices`:

7. Sütunlar: **CI № / vendor · PI ref · Date / ETA · Boxes · kg ·
   Agreed / gap · Cnt / truck · GRN · Status**.
8. `PI ref` dolu; bağlantısız CI'da `not linked` yazıyor.
9. `Date / ETA`: ETA satırı geçmişse kırmızı ve `... d late`, bir hafta içindeyse
   turuncu, uzaksa gri.
10. `Cnt / truck`: kutu ikonu + sayı, TIR ikonu + sayı. TIR yoksa 0 soluk gri.
11. Başlığa tıkla — **sayfa yenilenip sunucudan sıralı geliyor** (sayfalama
    başa dönüyor). Sayfa 2'ye geçip sıralamanın korunduğunu gör.
12. Alt toplam satırında **"this page only"** notu görünüyor — sayfalı liste
    olduğu için toplam yalnızca o sayfayı kapsıyor.

Dil değiştir (ru veya uz): yeni başlıklar (`PI ref`, `Date / ETA`,
`Cnt / truck`, `not linked`, `vendors`, `this page only`) çevrilmiş olmalı.

## Geri alma

Adım 1'deki tar'ı geri yükle, `chown -R frappe:frappe`,
`bench build --app stabler`, `bench restart`.

## Yapma

- `bench migrate` çalıştırma.
- Adım 2 çıktısını göstermeden Adım 3'e geçme.
- Adım 6'daki üçüncü testi (geçersiz `sort_by`) atlama — SQL enjeksiyon
  korumasının çalıştığını kanıtlayan tek kontrol o.
