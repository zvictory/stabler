# Ombor Stok Raporları — Uygulama Promptu (Cowork, model: Sonnet)
# Report Center'a yeni "Ombor" sekmesi: 3 native SPA raporu. Bağımsız Haiku doğrulayıcı ile.
# Kullanım: "---" arası bloğu yeni Cowork oturumuna yapıştır.

---

Sen Stabler SPA'sına 3 stok-hareket raporu ekliyorsun (Report Center'da yeni "Ombor" grubu).
Çalışma klasörü: /Users/zafar/frappe-bench-local/apps/stabler.

## 0. BAŞLANGIÇ (oku)
1. Tam spec + adapte edilmiş SQL: `docs/plans/2026-07-09-ombor-stock-reports.md` — OKU, birebir uygula.
2. Kurallar: `STATE.md`, `CLAUDE.md` (Centralized status / Money / Date / No-Desk blokları), `stabler_final_blueprint.md` §2.0.
3. Desen dosyalarını OKU: `api/reports.py` (`_shape`, mevcut whitelisted rapor endpoint'leri, company scope + has_permission deseni), `pages/reports/SalesByItem.vue` + `DrillReport.vue` (filtre+tablo+export deseni), `pages/ReportsHub.vue` (`groups` yapısı), `api/inventory.py::list_stock_warehouses` (ombor seçici), `composables/date.js` (formatDate).

## 1. Backend — 3 endpoint (api/reports.py'ye ekle)
Plan dosyasındaki SQL'leri kullan. Her biri: `@frappe.whitelist()` + `_require_company(company)` +
`_assert_company_scope(company)` + `frappe.has_permission("Stock Ledger Entry","read")` (yoksa throw) +
**parametrik** `frappe.db.sql(..., {params}, as_dict=True)` (f-string/% ile string enjeksiyonu YASAK) +
`_shape(columns, rows, totals, meta)` döndür. `frappe.db.commit()` YOK.
- `stock_movement_summary(company, from_date, to_date, warehouse="")` — Rapor 1.
- `stock_daily_kpi(company, from_date, to_date, warehouse="")` — Rapor 2 (4 satır).
- `stock_ledger_detail(company, from_date, to_date, warehouse="", voucher_type="", limit=500)` — Rapor 3; **limit zorunlu** (sınırsız sorgu yasak).
SQL'deki kolon alias'larını `_shape` kolon formatına çevir (Desk "Label:Type:Width" sözdizimini KULLANMA —
o Desk'e özgü; _shape'in kendi {key,label,type} yapısını kullan). Rapor 1'de her sütun için `totals`.

## 2. Frontend — 3 sayfa + router + hub
- `pages/reports/StockMovementSummary.vue`, `StockDailyKpi.vue`, `StockLedgerDetail.vue`.
  - Filtre: DateInput from/to (dd.mm.yyyy), Warehouse seçici (list_stock_warehouses), Rapor 3'te voucher_type Select ("" = hepsi). Auto-apply (ListToolbar deseni), SkeletonRows, Excel export.
  - Miqdor sütunları `font-monospace`; negatif değer kırmızı; tarih `formatDate`. Rapor 2: 4 KPI kartı + tablo.
  - **Rapor 3 hujjat linki SPA İÇİ route olmalı** (voucher_type→ilgili SPA rotası; Sales Invoice→/sales/invoices/<no>, Purchase Invoice→/purchasing/invoices/<no>, Stock Entry→/inventory/stock-entries/<no>). Route eşleşmezse düz metin — ASLA /app/ (Desk) linki.
- `router.js`: 3 rota, hepsi `meta:{module:"inventory"}` (direct-URL guard için ZORUNLU).
- `pages/ReportsHub.vue`: `groups`'a yeni grup ekle — `{ label: t("Ombor"), items: [3 kart: title/description/to/icon] }`. icon ör. `ti-building-warehouse`.
- i18n: TÜM yeni etiketleri t() ile sar; `bench --site <site> execute stabler.translations.harvest.run` çalıştır; 5 CSV'de (en/ru/uz/uzc/tr) doldur. Uzbek görünür etiketler plan dosyasında.

## 3. KABUL (bağımsız Haiku doğrulayıcı koşturur)
- 3 endpoint company-scoped + has_permission("Stock Ledger Entry") + parametrik (f-string SQL grep → 0) + Rapor 3 limit'li.
- 3 sayfa direct-URL refresh ile açılıyor (route-param guard); Excel export çalışıyor; miqdorlar monospace; tarih dd.mm.yyyy.
- Rapor 3 hujjat linki SPA içi (grep: yeni sayfalarda `/app/` → 0).
- ReportsHub'da "Ombor" grubu 3 kartla görünüyor; 3 rota da meta:{module:"inventory"}.
- 5 dil harvest edildi; Agent OS gate PASS (`APP_ROOT=$(pwd) agent-os/loop/guardrails/verify.sh`); `bench build --app stabler` exit 0.
- git add -A yok (explicit path); handler-içi commit yok.

## 4. KAPANIŞ
Commit "feat(reports): Ombor stok hareket raporları (movement summary + daily KPI + ledger detail)" + trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
Rapor: endpoint listesi, sayfa listesi, hangi voucher→route eşlemeleri kuruldu, harvest edilen anahtar sayısı. Sonra `graphify update .` (graf tazeliği). DUR.

---

# Operatör Notu (Zafar için)
- Yüklenen spec Desk Query Report anlatıyordu; Stabler "asla Desk" kuralı gereği native SPA raporuna adapte edildi (aynı SQL, SPA yüzeyi). Plan: docs/plans/2026-07-09-ombor-stock-reports.md.
- Önizlemeyi bu oturumda gördün; uygulama sonrası gerçek veriyle lokal `bench build` + sayfa açılışıyla teyit.
- Kritik fark: Rapor 3'ün "tıklanabilir hujjat" davranışı Desk Dynamic Link yerine SPA içi rotaya bağlandı — Desk kuralını korur.
