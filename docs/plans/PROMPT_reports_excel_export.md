# Vazifa: barcha Report Center hisobotlariga Excel (.xlsx) eksportini ulash

Stabler SPA'da P&L / Balance hisobotlari (`money/Reports.vue`) allaqachon server tomonda
yasaladigan professional `.xlsx` eksportiga ega. Xuddi shu mexanizmni **Sales by Customer**
va `ReportTable` ishlatadigan barcha boshqa hisobotlarga ulab chiq. Hech narsa noldan
yozilmaydi — infratuzilma tayyor, faqat sim ulanmagan.

## Tayyor infratuzilma (o'zgartirma, faqat foydalan)

- Komponent: `stabler/public/js/components/ReportTable.vue` — `:report-key` propi berilganda
  "Excel" tugmasini ko'rsatadi va `export_report_xlsx?report_key=…&filters=…` ni ochadi.
  Propslar: `reportKey: String`, `exportFilters: Object`.
- Backend: `stabler/api/export.py` → `export_report_xlsx(report_key, filters)` +
  `REPORT_EXPORTS` registratsiyasi. Generic branch `_call_source(spec["source"], filters)`
  natijasidan `{columns, rows, totals, meta}` ni o'qiydi — ya'ni `{columns,rows,totals,meta}`
  qaytaradigan har qanday report funksiyasi qo'shimcha kod talab qilmaydi.
- Namuna (ishlaydigan): `stabler/public/js/pages/reports/DrillReport.vue` —
  `const exportFilters = computed(() => ({ ... }))` va
  `<ReportTable :report-key="summaryReportKey" :export-filters="exportFilters" />`.

## 1) Frontend — summary jadvallarini ulash

Quyidagi sahifalarda `<ReportTable>` ga `:report-key` va `:export-filters` qo'sh. Filtrlar —
o'sha sahifa report'ni chaqirishda yuboradigan aynan o'sha parametrlar (`company`,
`from_date`, `to_date`, va h.k.). `exportFilters` ni `computed` qilib yoz.

| Fayl | report-key (summary) | export-filters |
|------|----------------------|----------------|
| `pages/reports/SalesByCustomer.vue` | `sales_by_customer` | `{ company, from_date: range.from_date, to_date: range.to_date }` |
| `pages/reports/SalesByItem.vue` | `sales_by_item` | `{ company, from_date, to_date }` |
| `pages/reports/ItemAbc.vue` | `item_abc` | sahifaning filtrlari |
| `pages/reports/InventoryExpiry.vue` | `inventory_expiry` | sahifaning filtrlari |

Misol (`SalesByCustomer.vue`):
```js
const exportFilters = computed(() => ({
  company: activeCompany.value,
  from_date: range.value.from_date,
  to_date: range.value.to_date,
}));
```
```html
<ReportTable
  :columns="summary.columns" :rows="summary.rows" :totals="summary.totals"
  :currency="summary.meta?.currency || 'UZS'" :language="lang()" :loading="loading"
  report-key="sales_by_customer" :export-filters="exportFilters"
  export-name="sales_by_customer" @drill="onSummaryDrill" />
```

## 2) Frontend + backend — detail (drill) jadvallarini ulash

Detail jadvali (masalan `sales_by_customer_detail`) `REPORT_EXPORTS` da YO'Q. Har bir detail
uchun:

- **Backend** (`stabler/api/export.py`, `REPORT_EXPORTS`): yangi kalit qo'sh, `source` =
  detail funksiyasi (masalan `stabler.api.reports.sales_by_customer_detail`),
  `title`, `roles: None`, `date_filters` summary bilan bir xil. Generic branch yetarli
  (detail funksiyalari `{columns, rows, totals, meta}` qaytaradi — tekshir).
- **Frontend**: detail `<ReportTable>` ga `:report-key` + `:export-filters` qo'sh.
  export-filters drill parametrini ham o'z ichiga olishi shart (masalan `customer: detailCustomer`
  yoki `item: detailItem`).

Kalitlar: `sales_by_customer_detail`, `sales_by_item_detail` (va shu naqshda ItemAbc detali
bo'lsa). `InventoryExpiry` bitta jadval — detali yo'q, faqat 1-bo'lim.

## 3) Valyuta — original valyutada chiqsin

`build_report_workbook` `meta.currency` (company base) ni ishlatmasin, balki qatorning o'z
`currency` maydonini ishlatsin (P&L da bo'lgani kabi original valyuta). Agar `excel_export.py`
da pul ustunlari yagona `currency` bilan formatlanayotgan bo'lsa, qator-darajadagi
`row["currency"]` mavjud bo'lsa o'shanga ustuvorlik ber (frontend `ReportTable.fmt` da
qilinganidek). Aks holda eksportda UZS summalar `$` bilan chiqadi.

## 4) i18n

`ReportTable` `t("Excel")` va `t("Professional Excel export with current filters")` ni
ishlatadi. Agar 5 tilning (en/ru/uz/uzc/tr) CSV'larida yo'q bo'lsa qo'sh.

## 5) Tekshiruv (majburiy)

- `python3 -m py_compile stabler/api/export.py`.
- Har o'zgargan `.vue` uchun `<script setup>` ni `node --check` dan o'tkaz; template tag/modal
  balansini tekshir.
- Har bir report uchun: `export_report_xlsx`'ni shu report_key + real filtrlar bilan
  chaqirib, qaytgan workbook'ni ochib ko'r — sarlavhalar, qatorlar soni ekrandagi bilan mos,
  summalar **original valyutada** (UZS → сўм/UZS, `$` emas), totals qatori to'g'ri.
- Permission: `_check_roles(spec)` har bir yangi kalit uchun ishlashini tasdiqla
  (`roles: None` = umumiy ko'rish, lekin `export_report_xlsx` baribir Guest'ni bloklaydi).
- CSV eksporti avvalgidek ishlashini regressiya sifatida tekshir.

## Qattiq qoidalar (CLAUDE.md)

- `git add -A` YO'Q — faqat aniq fayllar. Translations'ни 5 ta CSV sifatida alohida stage qil.
- Yangi user-facing satrlarni 5 tilning hammasida tarjima qil.
- Deploy: rsync + backup tar (`--delete` YO'Q); `.py` o'zgarsa `bench restart` (butun bench'ni
  blip qiladi). `migrate` shart emas (yangi doctype/patch yo'q).
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## Qamrov tashqarisi (alohida ish)

`SalesReports.vue`, `Customers.vue`, `Suppliers.vue`, `AgingTable.vue`, `AttendanceMatrix.vue`
— bular `ReportTable` ishlatmaydi, o'z eksport tugmalari bor. Ularni shu vazifaga aralashtirma.
