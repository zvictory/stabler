# MSA → Stabler: gerçek PI/CI ref numaralandırması + mutabakat (reconciliation) ajanı

**Sahip:** Zafar · **Tasarım:** Opus 4.8 (senior) · **Tarih:** 2026-07-18
**Modül:** imports (tenant: **msa**) · module-gated, company-scoped, ödemeler HARİÇ.

## Kararlar (kilitli)
1. **Numaralandırma = A** — Stabler doc `name` = gerçek MSA ref'i (auto-series YOK).
2. **Kaynak = canlı MSA DB, read-only** — SQLite dosyası.
3. **Kapsam = tarihsel PI + CI, tam satırlarla.**

## Doğrulanmış zemin (SQLite'tan okundu)
- DB: `/Users/zafar/Downloads/msaerp/db_production.sqlite3` (SQLite; `.env DB_HOST` boş). Salt-okunur açılır: `sqlite3 file:...?mode=ro`.
- Hacim: **36 PI · 523 PI satırı · 243 CI · 4194 CI satırı · 19 PI-grup · 732 konteyner.**
- Ref benzersizliği: **PI pi_number 36/36 benzersiz**, **CI ci_number 243/243 benzersiz** → A güvenli.
- Ref biçimleri: PI `FIR/25-26/29639-29647`, `PRO/MEPL/0538/25-26`, `HMA/PI/2229/2025-26`; CI `1119379443`, `CI/2026/0015`, `HMA/PI/2677/202425`. **`/` içeriyor.**
- ⚠️ **Tazelik:** en son `updated_at` 2026-05-22, dosya mtime 2026-06-07. Bu snapshot bugüne göre eski → *canlı sürekli* denetim için güncel dosya yolu teyit edilmeli (bkz. "Gerekenler").

## Ana teknik engel: ref'lerde `/`
Frappe `name` `/` içerebilir, ama şunları etkiler ve düzeltme gerektirir:
- SPA route `/imports/proformas/:name` → **`:name(.*)`** catch-all + tüm linklerde `encodeURIComponent`.
- REST çağrıları ismi URL-encode etmeli (Frappe encode'lu ismi çözer).

---

## Part A — Numaralandırma değişikliği (PI + CI)

**PI** (`proforma_invoice.json`):
- `autoname`: `format:PI-{YYYY}-{#####}` → **`field:supplier_pi_ref`**.
- `supplier_pi_ref`: **reqd + unique** yap (Frappe `name` benzersizliği zaten zorlar; alan reqd olmalı ki insert'te set olsun).
- Controller `autoname`/`validate`: ref boşsa net hata; trim; (opsiyonel) format doğrulama.

**CI** (`commercial_invoice.json`):
- `autoname`: `format:CI-{YYYY}-{#####}` → **`field:ci_number`**; `ci_number` reqd + unique.

**SPA:**
- `router.js`: `proformas/:name` → `proformas/:name(.*)` (ve CI için aynısı). Liste satır tıklaması `encodeURIComponent(row.name)`.
- Aynı encode CI form/route için.

**Mevcut kayıtlar:**
- Stabler'da gerçek-veri PI/CI **yoksa** (sadece test PI-2026-#### varsa) → rename yok, sadece autoname değişir + tarihsel import doğru isimle gelir. Test kayıtları silinir.
- Gerçek auto-named kayıt varsa → `frappe.rename_doc` (GL/CI-link cascade eder). **Önce teyit** (bkz. Gerekenler).

**Deploy:** doctype json değişikliği → `bench migrate`; controller `.py` → `restart`. Rename gerekiyorsa idempotent patch.

---

## Part B — Tarihsel migration (MSA SQLite → Stabler)

**Yeni modül:** `stabler/integrations/msa_migrate/` (imports-gated, msa company-scoped).
- `source.py` — SQLite'ı read-only açar, PI/LineItem/CI/CILineItem/PIGroup/Vendor satırlarını okur (saf okuma, yazma yok).
- `mapping.py` — MSA → Stabler alan eşlemesi (aşağıdaki tablolar; earlier research'ten).
- `loader.py` — ref'e göre **idempotent upsert** (Frappe), tam satırlarla, transaksiyon. Ödeme YAZMAZ.
- `run.py` — orkestrasyon: PIGroups → (Vendors zaten) → PIs(+lines) → CIs(+lines) → CI↔PI supersede link. Re-runnable.

**Eşleme (özet):**

| MSA (SQLite) | Stabler doctype/alan |
|---|---|
| `proformainvoice.pi_number` | `Proforma Invoice.name` (= supplier_pi_ref) |
| `.vendor_id` → vendor.code | `.supplier` |
| `.date` | `.pi_date` · `.status`→map · `.currency` · `.incoterm(+location)` · portlar · `.advance_percentage`→`advance_pct` · `.prepayment_type` |
| `.agreed_total/.docs_total/.cash_difference` | aynı (computed doğrulanır) |
| `.pi_group_id` → pigroup.code | `.import_pi_group` |
| `lineitem.*` (category, product_code, boxes, box_weight_kg, quantity_kg, agreed_price, docs_price) | `Proforma Invoice Item.*` (category, item, boxes, box_weight_kg, qty, rate, docs_price) |
| `commercialinvoice.ci_number` | `Commercial Invoice.name` (= ci_number) |
| `.pi_reference` / M2M `proforma_invoices` | CI↔PI supersede link |
| `cilineitem.*` | `Commercial Invoice Item.*` |

**Kurallar:** idempotent (ref'e göre upsert), earmark identity korunur (bank+cash==agreed — MSA'da yoksa docs/cash'ten türet), status merkezî map, ödeme/advance HARİÇ (sadece not).

---

## Part C — Sürekli mutabakat (reconciliation) "ajanı"

**Amaç:** cutover'a kadar "Stabler == MSA" güvencesi (ref bazında drift denetimi).

`stabler/integrations/msa_migrate/reconcile.py`:
- MSA (SQLite) ve Stabler'ı **ref anahtarıyla** karşılaştırır → 4 kova: **eksik** (MSA'da var, Stabler'da yok) · **tutar/satır uyuşmazlığı** · **status farkı** · **sadece-Stabler'da**.
- Çıktı: drift raporu (JSON + insan-okur log), imports-gated endpoint + CLI.
- **Schedule:** günlük — Frappe scheduler (`hooks.py scheduler_events.daily`) veya mcp scheduled-task. Yeni/değişen ref'leri raporlar; auto-import opsiyonel (varsayılan: raporla + onaya bırak).

**Nerede çalışır (infra kararı):** SQLite dosyası kullanıcı makinesinde; prod Stabler uzakta. Seçenekler: (a) ajan **lokal**de çalışır, hedef Stabler'a API ile yazar; (b) SQLite periyodik prod'a senkronlanır; (c) her ikisine erişen bir makinede. Cutover-dönemi aracı olduğu için (a) en pratik.

---

## Gerekenler (senden / netleşmesi lazım)
1. **SQLite güncel mi?** Dosya 2026-06-07, son kayıt 2026-05-22. MSA hâlâ kullanılıyorsa güncel DB yolu lazım; donmuşsa bu snapshot yeter (tek-sefer migration).
2. **İnfra:** reconciliation ajanı nerede koşacak + prod Stabler'a nasıl yazacak (lokal→prod API mı, SQLite senkron mu)?
3. **Mevcut Stabler PI/CI:** gerçek kayıt var mı (rename gerekir mi), yoksa sadece test verisi mi (silinir)?
4. **CI numarası kaynağı:** `ci_number` mı yoksa `pi_reference`/`bl_number` mı doc kimliği olsun? (öneri: `ci_number`.)

## WP kırılımı (beads epic'i — sırayla)
- **WP-A1** PI autoname=field:supplier_pi_ref (+reqd/unique) + SPA route `:name(.*)`/encode. *(bağımsız, deploy edilebilir)*
- **WP-A2** CI autoname=field:ci_number (+reqd/unique) + CI route encode.
- **WP-A3** (gerekirse) mevcut kayıt rename patch'i / test verisi temizliği.
- **WP-B1** `msa_migrate.source` + `mapping` (saf okuma + eşleme, unit-testli).
- **WP-B2** `loader` idempotent upsert (PI+lines) → **WP-B3** CI+lines + supersede link.
- **WP-B4** tam migration run + doğrulama (36 PI / 243 CI sayaç + tutar mutabakatı).
- **WP-C1** `reconcile` diff-by-ref + drift raporu (endpoint + CLI).
- **WP-C2** günlük schedule + rapor teslimi.

## Riskler
- `/` route/link regresyonu → smoke: `/`'li ref ile direct-URL aç/refresh.
- Ref çakışması ileride (yeni PI aynı ref) → Frappe insert hata verir; UX'te net mesaj.
- Stale SQLite → yanlış "eksik" alarmı; #1 netleşmeden C fazı canlı sayılmaz.
- rename cascade (varsa) → yedek + idempotent patch.
