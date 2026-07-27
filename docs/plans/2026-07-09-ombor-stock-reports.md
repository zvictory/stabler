# Ombor (Stok Hareket) Raporları — Report Center'a yeni "Ombor" sekmesi

**Tarih:** 09.07.2026 · **Kaynak:** ANJAN ombor-dashboard adaptasyonu (yüklenen 3 spec)
**Karar:** Yüklenen spec'ler Desk Query Report anlatıyor. Stabler'ın demir kuralı "asla Desk"
olduğu için bunları **native SPA raporu** olarak kuruyoruz: whitelisted endpoint (api/reports.py)
+ 3 Vue sayfası + ReportsHub'a yeni grup. Aynı SQL mantığı, Desk yerine SPA yüzeyi.

## Ortak kaynak
Üçü de `tabStock Ledger Entry`: `is_cancelled = 0`, `posting_date` aralığı, opsiyonel `warehouse`,
**+ zorunlu `company` filtresi** (tenant izolasyonu — spec'te yoktu, Stabler'da ŞART). MariaDB 10.3+
(CTE + window fn) mevcut. Endpoint sözleşmesi: `_shape(columns, rows, totals, meta)` (bkz. reports.py).

## Endpoint kuralları (blueprint §2.0)
`@frappe.whitelist()` → `_require_company(company)` → `_assert_company_scope(company)` →
`frappe.has_permission("Stock Ledger Entry","read")` → **parametrik** `frappe.db.sql` (f-string YASAK) →
`_shape(...)`. Modül: inventory. `frappe.db.commit()` yok.

---

## Rapor 1 — `stock_movement_summary` (Ombor Harakat Xulosasi)
Ürün bazlı: açılış → SE/PI/CN girişi → SI çıkışı → tuzatish (recon) → yakuniy.
Mantık: open = ilk SLE'de `qty_after_transaction − actual_qty`; close = son SLE'de `qty_after_transaction`;
se_in/pi_in/cn_in = voucher_type'a göre `actual_qty>0` toplamı; si_out = Sales Invoice `actual_qty<0` mutlak;
recon = `close − (open+se+pi+cn−si)`.

```sql
WITH sle AS (
  SELECT item_code, warehouse, actual_qty, qty_after_transaction, voucher_type,
    ROW_NUMBER() OVER (PARTITION BY item_code, warehouse ORDER BY posting_date, posting_time, creation) AS rn_asc,
    ROW_NUMBER() OVER (PARTITION BY item_code, warehouse ORDER BY posting_date DESC, posting_time DESC, creation DESC) AS rn_desc
  FROM `tabStock Ledger Entry`
  WHERE is_cancelled = 0 AND company = %(company)s
    AND posting_date BETWEEN %(from_date)s AND %(to_date)s
    AND (%(warehouse)s = '' OR warehouse = %(warehouse)s)
),
bounds AS (SELECT item_code,
    SUM(CASE WHEN rn_asc=1 THEN qty_after_transaction-actual_qty ELSE 0 END) AS opening,
    SUM(CASE WHEN rn_desc=1 THEN qty_after_transaction ELSE 0 END) AS closing
  FROM sle GROUP BY item_code),
moves AS (SELECT item_code,
    SUM(CASE WHEN voucher_type='Stock Entry' AND actual_qty>0 THEN actual_qty ELSE 0 END) AS se_in,
    SUM(CASE WHEN voucher_type='Purchase Invoice' AND actual_qty>0 THEN actual_qty ELSE 0 END) AS pi_in,
    SUM(CASE WHEN voucher_type='Sales Invoice' AND actual_qty>0 THEN actual_qty ELSE 0 END) AS cn_in,
    SUM(CASE WHEN voucher_type='Sales Invoice' AND actual_qty<0 THEN -actual_qty ELSE 0 END) AS si_out
  FROM sle GROUP BY item_code)
SELECT b.item_code, i.item_name,
  ROUND(b.opening,2) opening, ROUND(m.se_in,2) se_in, ROUND(m.pi_in,2) pi_in,
  ROUND(m.cn_in,2) cn_in, ROUND(m.si_out,2) si_out,
  ROUND(b.closing-(b.opening+m.se_in+m.pi_in+m.cn_in-m.si_out),2) recon, ROUND(b.closing,2) closing
FROM bounds b LEFT JOIN moves m ON m.item_code=b.item_code LEFT JOIN `tabItem` i ON i.name=b.item_code
WHERE (m.se_in<>0 OR m.pi_in<>0 OR m.cn_in<>0 OR m.si_out<>0)
ORDER BY i.item_name;
```
Kolonlar (_shape): Mahsulot(link item), Nomi, Boshlang'ich Qoldiq, SE Kirim, PI Kirim, CN Qaytish,
SI Chiqim, Tuzatish, Yakuniy Qoldiq — hepsi Float (recon işaretli). totals: her sütun toplamı.

## Rapor 2 — `stock_daily_kpi` (Kunlik Kirim-Chiqim KPI)
4 satır: tür × yönalish × yozuv soni × jami miqdor. (SPA'da hem 4 KPI kartı hem tablo olarak gösterilebilir.)
```sql
SELECT turi, yonalish, COUNT(*) cnt, ROUND(SUM(miqdor),2) jami FROM (
  SELECT
    CASE WHEN voucher_type='Stock Entry' AND actual_qty>0 THEN 'Stock Entry'
         WHEN voucher_type='Sales Invoice' AND actual_qty<0 THEN 'Sales Invoice'
         WHEN voucher_type='Sales Invoice' AND actual_qty>0 THEN 'Credit Note'
         WHEN voucher_type='Purchase Invoice' AND actual_qty>0 THEN 'Purchase Invoice'
         ELSE 'Boshqa' END AS turi,
    CASE WHEN voucher_type='Sales Invoice' AND actual_qty<0 THEN 'Chiqim'
         WHEN voucher_type='Sales Invoice' AND actual_qty>0 THEN 'Qaytish' ELSE 'Kirim' END AS yonalish,
    ABS(actual_qty) miqdor
  FROM `tabStock Ledger Entry`
  WHERE is_cancelled=0 AND company=%(company)s
    AND posting_date BETWEEN %(from_date)s AND %(to_date)s
    AND (%(warehouse)s='' OR warehouse=%(warehouse)s)
    AND voucher_type IN ('Stock Entry','Sales Invoice','Purchase Invoice')
) x WHERE turi<>'Boshqa' GROUP BY turi, yonalish ORDER BY turi;
```

## Rapor 3 — `stock_ledger_detail` (Stok Defteri Detali)
Ham SLE akışı + tıklanabilir hujjat. **Hujjat linki Desk'e (/app) DEĞİL, SPA içi belge görünümüne**
yönlenmeli (voucher_type→route: Sales Invoice→/sales/invoices/<no>, Purchase Invoice→
/purchasing/invoices/<no>, Stock Entry→/inventory/stock-entries/<no> vb.; route yoksa link'siz metin).
```sql
SELECT posting_date, posting_time, item_code, warehouse, voucher_type, voucher_no,
  ROUND(actual_qty,2) actual_qty, ROUND(qty_after_transaction,2) qty_after
FROM `tabStock Ledger Entry`
WHERE is_cancelled=0 AND company=%(company)s
  AND posting_date BETWEEN %(from_date)s AND %(to_date)s
  AND (%(warehouse)s='' OR warehouse=%(warehouse)s)
  AND (%(voucher_type)s='' OR voucher_type=%(voucher_type)s)
ORDER BY posting_date DESC, posting_time DESC
LIMIT %(limit)s;   -- sınırsız YASAK: sayfalama/limit zorunlu (audit §2.1 dersi)
```

## SPA katmanı
- 3 sayfa: `pages/reports/StockMovementSummary.vue`, `StockDailyKpi.vue`, `StockLedgerDetail.vue`.
  Desen: mevcut `SalesByItem.vue`/`DrillReport.vue`. Filtreler: DateInput (from/to, dd.mm.yyyy),
  Warehouse seçici (list_stock_warehouses zaten var), Rapor 3'te voucher_type Select. Auto-apply
  (ListToolbar deseni), SkeletonRows, XLSX export (professional-excel-export). Miqdor sütunları
  `font-monospace`, negatif kırmızı. Tarih `formatDate`. Rapor 2 opsiyonel 4 KPI kartı + tablo.
- router.js: 3 rota, `meta:{module:"inventory"}` (ZORUNLU — direct-URL guard).
- ReportsHub.vue: `groups`'a yeni grup `{ label: t("Ombor"), items:[...3 kart...] }` (icon ör. ti-building-warehouse).
- i18n: tüm yeni etiketler t() ile, 5 CSV'ye harvest (en/ru/uz/uzc/tr). Uzbek etiketler: "Ombor harakat
  xulosasi", "Kunlik kirim-chiqim KPI", "Stok defteri detali", "Boshlang'ich qoldiq", "Tuzatish", "Yakuniy qoldiq"...

## Kabul
- 3 endpoint: company-scope + has_permission("Stock Ledger Entry") + parametrik + limit; f-string SQL yok.
- 3 sayfa module:"inventory" ile gated; direct-URL refresh açılıyor; Excel export çalışıyor.
- Rapor 3 hujjat linki SPA içi route (asla /app); route yoksa düz metin.
- 5 dil harvest; Agent OS gate PASS; bench build exit 0.
- ReportsHub'da "Ombor" grubu 3 kartla görünüyor.
