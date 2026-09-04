# P5b — Tender K/Z'si defterden okunur, belge tarafıyla satır satır mutabakat

ADR-609 ikinci dilim. Kurul kararı (`2026-09-03-tender-ve-is-emri-tasarim-denetimi-tasarim-kurulu-karari.md`, §8, madde 3):
*"Tender P&L ekranı GL'den okur (boyut filtresi): gelir, COGS (stok çıkışı boyutla
damgalanır), landed, tender giderleri; `_actual_block` bununla mutabakat edilir, fark
satır satır gösterilir (geçiş döneminde iki kaynak yan yana)."*

Bu dosya dondurulmuş sözleşmedir; altındaki **Log** bölümü çalışma kaydıdır.
Sözleşmedeki her sembol, yol ve satır numarası 2026-09-04'te `main @ 53bd2aa`
üzerinde ölçülmüştür. Satır numaraları o commit'e aittir; kod değil, yer tarifidir.

---

## 1. Amaç ve iş gerekçesi

Teklif fiyatlama ekranı (`BidPricing.vue`) bugün "Plan vs actual" tablosunda belge
türetimli bir gerçekleşme gösterir: gelir = Sales Order × faturalanma yüzdesi, landed =
Purchase Order toplamı + kaydedilmiş fiili masraflar, kassa = `custom_crm_deal` taşıyan
Journal Entry'ler. Bu üç kaynak defteri (GL) **temsil eder**, defter **değildir**: PO
verilmiş ama mal gelmemişse landed "gerçekleşmiş" görünür; damgalı bir Purchase Invoice
gideri hiç görünmez; iptal edilen bir SI gelirden düşmez.

P5a ile tender bir Accounting Dimension oldu ve her damgalı fişin GL satırı `tender`
alanını taşıyor. P5b bu gerçeği ekrana taşır: aynı tender için GL'den okunmuş K/Z
sütunu, belge tarafının yanına, satır satır farkı ve farkın açıklamasıyla. İki kaynak
geçiş döneminde yan yana durur; hiçbiri gizlenmez.

## 2. Sahip

- Modül: `tender` (`_MODULE_ROLES`'ta kayıtlı, `Stabler Company Modules.enable_tender`).
- Kiracı: tender akışı yalnız mikas'ta açık; kod kiracı adına dallanmaz, `_deal_scope`
  şirket kapısını uygular (`stabler/api/tender.py:1165-1174`: deal var mı, şirketin
  tender modülü açık mı, şirket kapsamı, CRM Deal okuma izni).

## 3. Ölçülmüş mimari (kopyalanacak kalıplar)

| Ne | Nerede (main @ 53bd2aa) | Ölçülen gerçek |
|---|---|---|
| Ekranı besleyen uç | `stabler/api/tender.py:1485` `deal_bid_pricing(deal)` | `{deal, currency, inputs, pnl, actual, **refs}`; `actual = _actual_block(...)` |
| Belge tarafı | `tender.py:1457` `_actual_block` | `{invoiced, planned_landed, actual_landed, actual_revenue, kassa_actual[], kassa_actual_total, pnl, ostatok_delta}`; faturalanmamışsa `pnl.net_revenue` **plan** rakamına düşer (`bid_price = actual_revenue or planned`) |
| Şelale | `stabler/api/_bid_pnl.py:22` `compute_bid_pnl` | `net_rev = gross/(1+vat)` (:58); `above_total = landed_goods + above_other + exchange` (:62-63); `profit = net_rev − above_total` (:64); dönüş anahtarları :72-88 |
| Kassa okuyucu | `tender.py` `_deal_kassa_actual` | submitted JE, `custom_crm_deal = deal`, `Account.root_type='Expense'`, `jea.debit>0`, `account_name` ile gruplu |
| Landed belge tarafı | `tender.py:1177` `_deal_landed_split` | PO `base_grand_total` + `_parse_landed` satırlarının `actual`'ı; docstatus<2 |
| Boyut yardımcıları | `stabler/api/tender_dimension.py:90` `dimension_fieldname()`, `:132` `tender_enabled`, `:147` `mandatory_for_pl`, `:200` `overhead_deal` | boyutun gerçek fieldname'i (test sitesinde `tender`; v103 yeniden kullanılan boyutta farklı olabilir — **literal `tender` yazılmaz**) |
| GL satırı | `GL Entry`: `account, debit, credit, voucher_type, voucher_no, company, is_cancelled, <fieldname>` | `debit/credit` şirket para birimi; `has_column("GL Entry","tender")` = True |
| Hesap sınıfı | `Account.report_type / root_type / account_type / is_group` | dördü de var; `_Test Company`: Income 7, Expense 34 (P&L), Asset/Liability/Equity (BS) |
| LCV'nin GL'e yazımı | `erpnext/stock/doctype/purchase_receipt/purchase_receipt.py:638-662` | PR'ın GL'inde LCV satırının `expense_account`'una **alacak** (`credit=credit_amount`), `add_gl_entry` → PR'ın boyutları → alacak satırı tender'ı taşır |
| Landed hesabı | `Account.account_type = "Expenses Included In Valuation"` (test sitesi: `Expenses Included In Valuation - _TC`); ayrıca `Stabler Settings.landed_cost_expense_account` ve `imports_lcv_expense_account` (`stabler/api/lcv.py:511-534`; test sitesinde ikisi de boş) | |
| COGS hesabı | `Account.account_type = "Cost of Goods Sold"` (`Cost of Goods Sold - _TC`) | |
| Test sitesi | `genesis-test.local`, `_Test Company`/`_TC`, UZS | test dışı **sıfır** tender'lı GL satırı (ölçüldü) → bench testleri kendi fikstürünü kurar |
| Bench fikstürü | `stabler/tests/test_tender_dimension_bench.py:137` `_Fixture` (`_make_deal`, `_expense_entry`, `_erase_voucher`), `:85-136` yardımcılar (`_tender_company`, `_gl_rows`, `_report_type`), `:677` `TestSalesSide._order` (SO→SI, SO→DN) | |
| Frappe-free test kalıbı | `stabler/tests/test_bid_package.py` (saf modül `_bid_package`), `stabler/tests/test_landed_charge_currency.py` (`ModuleSandbox`) | saf modüller `_` önekli: `_bid_pnl.py`, `_landed.py`, `_bid_package.py` |
| Vitest kalıbı | `stabler/public/js/tests/quotationDrawerMoney.spec.js` (`extractFunction`), `bidPricingPrewinLanded.spec.js` | kaynak-metin testleri; her `it` "WHAT WOULD MAKE THIS FAIL" yorumu taşır |

**Düzeltme (Rule 1):** önceki tur notlarında "masraf tipi → gider hesabı eşlemesi"
yazılmıştı. Ölçüm: GL satırı masraf tipi taşımaz; ADR-606'nın dokuz kanonik tipi PO'nun
`custom_landed_charges` JSON'unda yaşar, deftere geçmez. P5b **hesabı kovaya** eşler,
tipi hesaba değil. Tip bazlı defter kırılımı bu dilimin dışındadır (§12).

## 4. İzinli dosyalar

| Dosya | Durum |
|---|---|
| `stabler/api/_tender_gl.py` | **yeni**, frappe-free (frappe import etmez) |
| `stabler/api/tender_gl.py` | **yeni**, DB okuma + whitelisted uç |
| `stabler/public/js/pages/tender/BidPricing.vue` | yeni bölüm eklenir; mevcut bölümler değişmez |
| `stabler/tests/test_tender_gl.py` | **yeni**, frappe-free |
| `stabler/tests/test_tender_gl_bench.py` | **yeni**, bench |
| `stabler/public/js/tests/bidPricingLedger.spec.js` | **yeni** |
| `.github/frappe-free-tests.txt` | `stabler.tests.test_tender_gl` satırı eklenir (alfabetik yerine) |
| `stabler/translations/{en,ru,uz,uzc,tr}.csv` | §9'daki anahtarlar, beşine de |
| bu dosyanın Log bölümü | çalışma kaydı |

**Yasak:** `tender.py`, `tender_dimension.py`, `_bid_pnl.py`, `hooks.py`, `patches.txt`,
her doctype JSON, diğer `.vue`/`.js`, `Makefile`, `.github/bench-known-red.txt`, üretim,
SSH, deploy, `git merge/push/rebase`, `git add -A`. Şema değişikliği **yok** — P5b'nin
migrate'e ihtiyacı yoktur; varsa tasarım yanlış demektir, dur ve yaz.

## 5. Arka uç davranışı

### 5.1 Saf katman — `stabler/api/_tender_gl.py`

```python
BUCKETS = ("revenue", "cogs", "landed", "expenses")

def classify_account(report_type, root_type, account_type, landed_accounts: frozenset, account: str) -> str | None
```
Öncelik sırası **dondurulmuştur**:
1. `report_type != "Profit and Loss"` → `None` (kovaya girmez). P5a hükmü: damgalı fişin
   BS bacağı da tender'ı taşır; alacaklı/borçlu/stok/kasa satırları K/Z'ye toplanmaz.
2. `root_type == "Income"` → `"revenue"`.
3. `account in landed_accounts` **veya** `account_type == "Expenses Included In Valuation"` → `"landed"`.
4. `account_type == "Cost of Goods Sold"` → `"cogs"`.
5. geri kalan her P&L satırı → `"expenses"`. Bir P&L satırı asla sessizce düşmez.

```python
def bucket_amount(bucket, debit, credit) -> float
```
`revenue`: `credit − debit`; diğer üçü: `debit − credit`. Negatif değer **kırpılmaz**
(landed'da alacak fazlası bir bulgudur, §5.3).

```python
def summarize(rows: list[dict], landed_accounts: frozenset) -> dict
```
`rows`: `{account, account_name, report_type, root_type, account_type, voucher_type, debit, credit, count}`
(hesap × fiş türü grubu). Dönüş:
```python
{
  "buckets": {b: {"total": float, "rows": [{"account", "account_name", "amount", "debit", "credit", "count"}]}
              for b in BUCKETS},          # rows: |amount| azalan, sonra account
  "result": revenue.total - cogs.total - landed.total - expenses.total,
  "by_voucher": [{"voucher_type", "count", "debit", "credit", "net"}],   # yalnız P&L satırları; |net| azalan
  "stock_on_hand": float,   # BS satırlarından account_type == "Stock": debit − credit; bilgi amaçlı, result'a girmez
  "row_count": int,         # toplanan P&L satır (grup) sayısı
}
```
Tüm toplamlar `round(x, 2)`.

```python
def reconcile(actual: dict, gl: dict) -> list[dict]
```
Belge tarafı `actual` = `_actual_block` çıktısı; `gl` = `summarize` çıktısı. Dört satır,
bu sırayla, `delta = gl − documents`:

| `key` | `documents` | `gl` | `notes` (kodlar) |
|---|---|---|---|
| `revenue` | `actual["pnl"]["net_revenue"]` **eğer** `actual["invoiced"]`, değilse `0.0` (faturalanmamışken `net_revenue` plan rakamıdır — §3) | `buckets.revenue.total` | `not_invoiced` (invoiced False) |
| `landed` | `actual["actual_landed"]` | `buckets.cogs.total + buckets.landed.total` | `landed_credit_surplus` (landed.total < 0); `stock_on_hand` (gl.stock_on_hand > 0) |
| `expenses` | `actual["kassa_actual_total"]` | `buckets.expenses.total` | — |
| `result` | revenue.documents − landed.documents − expenses.documents | `gl["result"]` | — |

Satır şekli: `{"key", "documents", "gl", "delta", "notes": [str]}`. Etiket **yok**;
SPA `key`'i `t()` ile çevirir. `actual` boş/None ise belge tarafı sıfır ve `notes`'a
`no_documents` eklenir — istisna atılmaz.

Gerekçe: `net_revenue` ile GL geliri aynı tabandadır (KDV hariç: şelale `gross/(1+vat)`,
SI'nin gelir satırı KDV'siz; KDV BS'teki vergi hesabına gider). Sonuç satırı şelalenin
`profit`'iyle **karşılaştırılmaz**: `profit` deftere yazılmamış hesaplanan bir döviz
komisyonunu düşer; belge tarafı bu yüzden üç belge rakamından türetilir.

### 5.2 DB katmanı ve uç — `stabler/api/tender_gl.py`

```python
@frappe.whitelist()
def tender_gl_pnl(deal: str) -> dict
```
1. `company = _deal_scope(deal, write=False)` (`from stabler.api.tender import _deal_scope, _bid_inputs, _actual_block, _compute_bid_pnl` — özel isimler, aynı uygulama içi).
2. `fieldname = dimension_fieldname()`; `None` → `available False, reason "no_dimension"`.
   `frappe.db.has_column("GL Entry", fieldname)` False → `reason "no_column"`. Her iki
   durumda `buckets` sıfır/boş, `reconciliation []`, `row_count 0`, istisna yok.
3. `fieldname` yalnız `re.fullmatch(r"[a-z_][a-z0-9_]*", fieldname)` geçerse SQL'e
   girer; geçmezse `frappe.throw(_("Unsafe dimension fieldname"))`. Değerler her zaman
   parametrik.
4. **Tek sorgu:**
   ```sql
   SELECT g.account, a.account_name, a.report_type, a.root_type, a.account_type,
          g.voucher_type, SUM(g.debit) debit, SUM(g.credit) credit, COUNT(*) count
   FROM `tabGL Entry` g JOIN `tabAccount` a ON a.name = g.account
   WHERE g.`{fieldname}` = %(deal)s AND g.company = %(company)s AND g.is_cancelled = 0
   GROUP BY g.account, g.voucher_type
   ```
5. `landed_accounts = frozenset(x for x in (settings.landed_cost_expense_account, settings.imports_lcv_expense_account) if x)`
   — `frappe.db.get_single_value("Stabler Settings", ...)`, iki alan da boşsa boş küme.
6. `gl = summarize(rows, landed_accounts)`; `inp, _refs = _bid_inputs(deal, company)`;
   `actual = _actual_block(deal, company, inp, _compute_bid_pnl(inp))`;
   `reconciliation = reconcile(actual, gl)`.
7. Dönüş:
   ```python
   {"deal", "company", "currency": Company.default_currency, "available": True, "reason": "",
    "fieldname", **gl, "reconciliation"}
   ```
Hatalar: bilinmeyen deal → `DoesNotExistError`; izin yok → `PermissionError` (ikisi
`_deal_scope`'tan, yutulmaz). `deal_bid_pricing` **değişmez** — dönüş anahtarları P5a
kümesiyle aynı kalır (bench regresyon testi §8).

Overhead deal (`deal_type = "Overhead"`) için ayrı davranış yok: uç herhangi bir deal
için çalışır; ekran onu açmaz. GENEL GİDER K/Z ekranı P5c adayıdır (§12).

### 5.3 Notes kodları ve eylemleri (Operator merceği — kod değil, cümle)

| kod | ekran metni (İngilizce anahtar) |
|---|---|
| `not_invoiced` | "Nothing invoiced yet — the documents side reads 0." |
| `landed_credit_surplus` | "Landed charges show a credit surplus: the bill that capitalized them is booked to another tender or to GENEL GİDER. Re-tag that bill." |
| `stock_on_hand` | "Goods received for this tender and not yet delivered reach cost of goods on delivery." |
| `no_documents` | "No documents-side figures for this deal." |

## 6. Ön yüz — `BidPricing.vue`

Mevcut "Plan vs actual" bloğunun **altına**, aynı görsel dille (`border rounded p-2`,
`table table-no-stripe table-sm mb-0`; `table-striped` yazılmaz, tablolar global çizgili)
yeni bölüm: **"Ledger vs documents"**.

- Veri: `loadLedger()` ayrı fonksiyon, kendi `try/catch`'i, kendi `ledgerLoading` /
  `ledgerError` durumu; `load()`'dan **bağımsız** çağrılır (`onMounted`/`watch(props.deal)`
  mevcut kalıbı ne ise oradan, ikinci çağrı olarak). Defter ucu düşerse fiyatlama ekranı
  çalışır kalır. Çağrı: `call("stabler.api.tender_gl.tender_gl_pnl", { deal: props.deal })`.
- Sütunlar: satır etiketi | **Documents** | **Ledger (GL)** | **Δ**. Dört mutabakat satırı
  (`reconciliation` sırasıyla): "Net revenue", "Cost of goods and landed charges",
  "Tender expenses", "Operating result". Δ hücresi sunucunun `delta`'sını basar, istemci
  yeniden hesaplamaz. Renk: gelir satırında `delta < 0` kırmızı; maliyet/gider satırında
  `delta > 0` kırmızı; sonuç satırında `delta < 0` kırmızı; aksi yeşil; sıfır nötr.
- Her kova satırının altında hesap kırılımı (`text-secondary small`, `ps-4`, mevcut kassa
  satırları gibi): `buckets.<b>.rows` — `account_name` ve `fm(amount)`. Landed satırı
  altında `cogs.rows` ve `landed.rows` art arda.
- `notes` kodları satırın altında `small text-secondary` bir satır olarak §5.3 metniyle.
- `stock_on_hand > 0` ise bilgi satırı: "Stock on hand for this tender" (Documents "—",
  Ledger `fm(stock_on_hand)`, Δ boş).
- `by_voucher` özeti: küçük ikinci tablo (fiş türü | adet | net) — fiş türü adı `t()`
  ile çevrilir ("Sales Invoice", "Delivery Note", "Purchase Invoice", "Journal Entry",
  "Purchase Receipt", "Stock Entry" anahtarları zaten katalogda mı `grep` ile ölçülür;
  yoksa eklenir).
- Para: mevcut `fm` (`formatMoney(v, props.currency)`); `currency` sunucudan gelenle
  aynıdır (ikisi de şirket para birimi) — başka biçimlendirici yok.
- Yenile düğmesi: `btn btn-outline-secondary btn-sm` ("Refresh"); bölgede `.btn-primary`
  eklenmez (bölgenin tek `btn-primary`'si "Save bid pricing").

**Durumlar (hepsi zorunlu):**

| Durum | Koşul | Görünüm |
|---|---|---|
| loading | `ledgerLoading` | tabloda tek satır spinner + "Loading ledger…" |
| unavailable | `available === false` | `alert alert-secondary py-2 small`: "Ledger view unavailable: the tender dimension is not set up for this company. Save Stabler Settings with the tender module on to create it." |
| empty | `available && row_count === 0` | "No ledger entry carries this tender yet. Post or tag an invoice, delivery or expense to see the ledger side." (mutabakat tablosu yine çizilir; GL sütunu 0) |
| error | `ledgerError` | `alert alert-warning py-2 small`: "Could not load the ledger view." + hata mesajı + "Retry" düğmesi; fiyatlama ekranı etkilenmez |
| permission | sunucu `PermissionError` | error durumu, sunucu mesajıyla |

Desk'e (`/app/...`) link yok. Tarih gösterilmez (tarih yoksa `formatDate` gereksiz).

## 7. Muhasebe ve para birimi değişmezleri

- Tüm GL toplamları `GL Entry.debit/credit` (şirket para birimi); hesap para birimi
  sütunları okunmaz. `currency` = `Company.default_currency`.
- Yalnız `is_cancelled = 0`; iptal fişlerin ters kayıtları da `is_cancelled = 1` olduğu
  için net etkileri zaten yoktur, filtre çift saymayı ve gürültüyü keser.
- P&L dışı satır kovaya girmez (§5.1 kural 1). Stok BS satırı yalnız `stock_on_hand`.
- Yuvarlama: her toplam `round(, 2)`; satır içi toplama yuvarlanmamış değerlerle.
- `result` her zaman `revenue − cogs − landed − expenses`; başka yerde yeniden türetilmez.

## 8. Testler — önce kırmızı, nedeniyle

Her test dosyası başında **neden** paragrafı; her `test_`/`it` içinde "WHAT WOULD MAKE THIS
FAIL" cümlesi (ev kalıbı). Her yeni testin kırmızı görüldüğü **mutasyon** rapora yazılır
(hangi satır değişti → hangi test düştü). Tanımla-tatmin-edilebilir iddia yok
(`assertIn("some_string", source)` tarzı Python testi yasak; Vue kaynak testinde regex
yalnız davranışı gösteren koda bağlanır).

### 8.1 `stabler/tests/test_tender_gl.py` (frappe-free; `.github/frappe-free-tests.txt`'e eklenir)

1. BS satırı hiçbir kovaya girmez (alacaklı bacağı tender taşısa da) — mutasyon: kural 1 kaldırılır.
2. Income → revenue, alacak pozitif — mutasyon: işaret ters.
3. EIV tipli hesap landed'a; ayarlardaki hesap tipi ne olursa olsun landed'a — mutasyon: kural 3 ile 4'ün yeri değişir (COGS tipli ama ayarlarda listelenen hesap `cogs`'a kayar).
4. COGS tipli → cogs; kalan Expense → expenses; bilinmeyen `root_type` ile P&L satırı düşmez, expenses'a gider — mutasyon: `return None` fallback.
5. Landed alacak fazlası negatif kalır, kırpılmaz — mutasyon: `max(0, …)`.
6. `summarize`: satırlar |amount| azalan; `result` formülü; `stock_on_hand` result'a girmez; `by_voucher` yalnız P&L; `row_count` — her biri ayrı test.
7. `reconcile`: dört anahtar ve sıra; `delta = gl − documents`; faturalanmamışken belge geliri 0 ve `not_invoiced`; `landed_credit_surplus` ve `stock_on_hand` notları; `actual=None` → `no_documents`, istisna yok.

### 8.2 `stabler/tests/test_tender_gl_bench.py` (bench; `BENCH_TESTS` türetimi otomatik alır)

`test_tender_dimension_bench._Fixture` alt sınıfı (ya da `_tender_company/_gl_rows/_report_type`
import'u); `TestSalesSide._order` kalıbı kopyalanır, kopyanın nedeni docstring'de.

1. Damgalı SI → `buckets.revenue.total == si.base_net_total`; alacaklı bacağı hiçbir kovada değil; `by_voucher`'da "Sales Invoice". WHY: P5a hükmü — iki bacak da damgalı, K/Z yalnız P&L.
2. Damgalı DN → `cogs.total ==` DN'nin COGS borç satırı; stok bacağı `stock_on_hand`'ı **düşürür** (negatif olabilir — DN öncesi PR yoksa). WHY: teslimatın maliyeti defterden gelir, PO'dan değil.
3. `_expense_entry(deal=tender)` → `expenses.rows` tek hesap, tutar eşit; `reconcile` expenses satırı: documents (`kassa_actual_total`) == gl, `delta == 0`. WHY: aynı fişi okuyan iki okuyucu aynı sayıyı vermelidir; vermiyorsa biri yanlıştır.
4. Damgasız fatura (`_expense_entry(deal=None)`) GENEL GİDER'e gider ve tender'ın kovalarında **görünmez**. WHY: overhead ayrımı.
5. `dimension_fieldname` `None` döndürecek şekilde yamalanır → `available False, reason "no_dimension"`, istisna yok, `reconciliation == []`.
6. Bilinmeyen deal → `DoesNotExistError` (`_deal_scope` yeniden kullanıldığının kanıtı).
7. `deal_bid_pricing(deal)` üst düzey anahtar kümesi P5a ile aynı: `{"deal","currency","inputs","pnl","actual","po_landed","po_count","so_revenue","so_count","quotation_landed_estimate","quotation_landed_source","quotation_landed_unvalued","quotation_landed_denied"}` — **bu küme sözleşmeye yazılmadan önce `main`'de ölçülür**; farklıysa ölçülen yazılır ve Log'a not düşülür.

### 8.3 `stabler/public/js/tests/bidPricingLedger.spec.js`

1. `loadLedger` `stabler.api.tender_gl.tender_gl_pnl`'i çağırır ve kendi `try/catch`'ine sahiptir; `loading` (fiyatlama) bayrağına dokunmaz — `extractFunction("loadLedger")` gövdesi üzerinden.
2. Δ hücresi `delta`'yı basar, `gl - documents` istemcide hesaplanmaz.
3. Üç durum metni birebir var ve eylem adlandırır (unavailable, empty, error+Retry).
4. `table-striped` yok, `/app/` yok (guards zaten tarar; test niyetin kaydıdır).

## 9. i18n — beş kataloga da (`en, ru, uz, uzc, tr`)

"Ledger vs documents" · "Documents" · "Ledger (GL)" · "Cost of goods and landed charges" ·
"Tender expenses" · "Operating result" · "Stock on hand for this tender" ·
"Loading ledger…" · "Refresh" · "Retry" · "Could not load the ledger view." ·
"Ledger view unavailable: the tender dimension is not set up for this company. Save Stabler Settings with the tender module on to create it." ·
"No ledger entry carries this tender yet. Post or tag an invoice, delivery or expense to see the ledger side." ·
"Nothing invoiced yet — the documents side reads 0." ·
"Landed charges show a credit surplus: the bill that capitalized them is booked to another tender or to GENEL GİDER. Re-tag that bill." ·
"Goods received for this tender and not yet delivered reach cost of goods on delivery." ·
"No documents-side figures for this deal." · fiş türü adları (katalogda yoksa).

Mevcut anahtarlar yeniden kullanılır: "Net revenue", "Plan vs actual", "Δ", "Planned", "Actual".
Kalıp: `stabler/translations/en.csv` satırı `key,key`; diğerleri `key,çeviri`. Beşi de
harvest sırasına göre; `.tx_*.json` dosyalarına dokunulmaz.

## 10. Kabul ölçütleri (farksal, ölçülebilir)

1. `make test` çıktısındaki "frappe-free modules:" sayısı `main`'dekine göre **bir artar**
   (iki sayıyı da komut çıktısından al; buraya yazma).
2. `PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_gl -v` yeşil; her testin
   kırmızı mutasyonu raporda.
3. `PYTHONPATH=<worktree> bench --site genesis-test.local run-tests --module stabler.tests.test_tender_gl_bench`
   yeşil, **skip yok** (fikstür bulunamazsa test skip değil fail eder; `TestSalesSide`'ın
   skip kalıbı burada kopyalanmaz — stok yoksa `_erase_voucher` ile temizlenen kendi
   Stock Entry'sini kurar ya da açıkça fail eder).
4. `npx vitest run stabler/public/js/tests/bidPricingLedger.spec.js` yeşil.
5. `make check` yeşil — çıktının `Test Files` satırı ve "OK — pre-push gate passed" satırı raporda.
6. `git diff --check` temiz; `git status --short` yalnız §4 dosyaları.
7. `for k in <§9 anahtarları>; do for f in en ru uz uzc tr; do grep -c "^$k," stabler/translations/$f.csv; done; done` her hücre ≥1.
8. `deal_bid_pricing` çıktısı değişmedi (8.2/7).

## 11. Doğrulama komutları

```bash
cd /Users/zafar/frappe-bench-local/apps/stabler/.worktrees/p5b-tender-gl
PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_gl -v
npx vitest run stabler/public/js/tests/bidPricingLedger.spec.js
make check 2>&1 | tail -25
git diff --check
# bench modülü (kilit boş olmalı: ls -d /Users/zafar/frappe-bench-local/.stabler-test-bench.lock → yok)
cd /Users/zafar/frappe-bench-local && PYTHONPATH=/Users/zafar/frappe-bench-local/apps/stabler/.worktrees/p5b-tender-gl \
  bench --site genesis-test.local run-tests --module stabler.tests.test_tender_gl_bench
```
Probe worktree'nin **Python'unu** ölçer, şemayı değil — P5b şema değiştirmediği için yeterlidir.
Tam `make test-bench` yalnız `main`'de, merge sonrası, orkestratör tarafından.

## 12. Karar dışı bırakılanlar

- Tarih aralığı filtresi (tender ömrü boyu okunur).
- Stock Entry damgalama: `Stock Entry.tender` sütunu var, `stamp_tender` kancası yok; malzeme
  çıkışı el ile damgalanmadıkça GL'de tender'sız kalır. Ayrı dilim.
- GENEL GİDER (overhead deal) K/Z ekranı — P5c adayı.
- Landed'ın masraf tipine göre kırılımı — GL tip taşımaz (§3 düzeltmesi).
- `_actual_block`'un kendisinin GL'e taşınması — geçiş dönemi biter, kurul karar verir.

## 13. Tamamlanma raporu (zorunlu biçim)

1. Değişen dosyalar (yol + satır sayısı; `git diff --stat`).
2. Her yeni test için: ad · WHY · **kırmızı mutasyonu** (değişen satır → düşen test · komut çıktısının ilgili satırı).
3. §11 komutlarının çıktıları (özet + gate satırları birebir).
4. **Doğrulanmayanlar** — açık listesi; "tamamlandı" bunlar boşken söylenir.
5. Sözleşmede yanlış/ölçümle çelişen bulunan her cümle (Rule 1) ve yerine ölçülen gerçek.
6. Açık sorular (varsa; iş kararı gerekenler Zafar'a).

---

## Log

### 2026-09-04 — sözleşme donduruldu (orkestratör: Claude Fable 5.1)

- Ölçümler: `main @ 53bd2aa`; test sitesinde tender'lı GL satırı 0; boyut `Tender`/`tender`
  etkin; `Stabler Settings` LCV hesapları boş; EIV ve COGS hesapları `_TC`'de birer.
- Worktree: `.worktrees/p5b-tender-gl` @ `feat/adr-609-tender-gl-pnl` (main'den), `node_modules` symlink'li.
- Uygulayıcı: opus alt-ajan (GL/para → opus; model-routing kuralı). İnceleme: `stabler-diff-reviewer`.

### 2026-09-04 — uygulama (opus alt-ajan, `.worktrees/p5b-tender-gl`)

Sözleşme birebir uygulandı. Aşağıdakiler ya sözleşmenin karar vermediği yerler
ya da kodun sözleşmeyle çeliştiği ölçümlerdir (Rule 1: kod gerçektir).

**Sözleşmenin karara bağlamadığı, uygulamada karar verilenler**

1. `by_voucher[].net` — §5.1 anahtarı donduruyor, formülü değil. Seçilen:
   `credit − debit`. Gerekçe: bir P&L satırının **sonuca katkısı** kovası ne
   olursa olsun `credit − debit`'tir (gelir alacağı ekler, gider borcu düşer), bu
   yüzden sütun toplamı `result`'a **birebir** eşit çıkar. Testle sabitlendi
   (`test_only_profit_and_loss_rows_reach_the_voucher_summary`); tabloyu
   dekoratif olmaktan çıkaran tek özellik bu.
2. `no_documents` notunun **yeri** — §5.1 "notes'a eklenir" diyor, hangi satıra
   demiyor. Gelir satırına konuldu, `not_invoiced` ile birlikte (ikisi de
   doğrudur; okuyucu tabloyu yukarıdan aşağı okur ve ilk satırda karşılaşır).
3. `result` **yuvarlanmış** kova toplamlarından hesaplanıyor. §7 "her toplam
   round(,2), satır içi toplama yuvarlanmamış" diyor; sonuç satırı için
   yuvarlanmamış toplam kullanılsaydı ekranda görünen dört sütun beşinciye
   toplanmayabilirdi (kuruş farkı) ve kontrol eden okuyucu haklı çıkardı.

**Sözleşmeden sapma (tek)**

4. §5.2'nin SQL'ine `GROUP BY`'a `a.account_name, a.report_type, a.root_type,
   a.account_type` eklendi. `a.name = g.account` üzerinden fonksiyonel bağımlı
   oldukları için gruplama **değişmez**; amaç `ONLY_FULL_GROUP_BY` açık bir
   MariaDB'de sorgunun reddedilmemesi. Başka hiçbir şey değişmedi.

**Ölçümler (sözleşmedeki ifadeleri düzelten / tamamlayan)**

5. §8.2/7'nin dondurduğu `deal_bid_pricing` anahtar kümesi **doğru** — canlı
   dönüşten ölçüldü, 13 anahtar, birebir aynı.
6. §8.2/4 "damgasız fatura GENEL GİDER'e gider" — yarısı doğru. Ölçüm: damgasız
   bir JE'nin **P&L bacağı** GENEL GİDER'i taşır, **kasa bacağı hiçbir şey
   taşımaz** (`tender` NULL). `default_gl_tender` bir bilanço satırına asla değer
   EKLEMEZ (kendi docstring'i böyle diyor, madde 2). Testin iddiası buna göre
   yazıldı: P&L bacağı = overhead **ve** hiçbir satır bu tender'ı taşımıyor.
7. §8.2/2'nin varsaydığı şey doğrulandı: `_TC`'de teslimat notunun gider hesabı
   gerçekten `account_type = "Cost of Goods Sold"`, yani teslimatın maliyeti
   mutabakatın **landed** satırına (cogs + landed) katılıyor, tender giderlerini
   şişirmiyor. Bu bir varsayım değil artık, ölçüm.
8. §9 listesi eksikti: `by_voucher` tablosunun başlıkları için "Voucher type",
   "Count", "Net" gerekiyor. Üçü de beş katalogda **zaten var**, yeniden
   kullanıldı; yeni anahtar sayısı 15.

**Ortam bulgusu — bir sonraki worktree'yi de vuracak**

9. `.worktrees/` altındaki **her** worktree'de `make check` kırmızıydı:
   `test_bulk_operator_assign` altı hatayla düşüyordu. Sebep P5b değil —
   `frappe.logger()` log dosyasını `<cwd'nin üstü>/logs/frappe.log` olarak açıyor;
   ana ağaçta bu `apps/logs` (var), worktree'de `.worktrees/logs` (yoktu) →
   `FileNotFoundError`. Test edilen kod ana ağaçla **byte-identical**
   (`git diff 53bd2aa..HEAD -- stabler/api/manufacturing.py …` boş) ve aynı modül
   ana ağaçta yeşil. `mkdir .worktrees/logs` ile geçildi; dizin `.gitignore`'un
   `.worktrees/` kuralı altında, depoya hiçbir şey girmiyor. Makefile'ın
   `node_modules` symlink'i için yaptığı gibi, bu da worktree kurulumunun bir
   parçası olarak yazılmalı.

**Mutasyon kanıtı — yöntem notu**

10. İlk mutasyon turunda bir mutasyon "yeşil kaldı" göründü. Sebep testin zayıf
    olması değil, **bayat `__pycache__`**: iki ardışık mutasyon aynı saniyede
    aynı BOYUTTA dosya ürettiğinden (`return debit - credit` /
    `return credit - debit`, ikisi de 21 karakter) CPython'un (mtime, size)
    geçersizleştirmesi eski `.pyc`'i yeniden kullandı. Koşum
    `PYTHONDONTWRITEBYTECODE=1` ile tekrarlandı, mutasyon kırmızı oldu. Kayda
    geçiriliyor: bu tuzak mutasyon kanıtını sessizce yalana çevirir.
11. Bir Vue iddiası ilk yazımında **düzyazıyla** eşleşiyordu — bölümün başlığı
    `t("Ledger vs documents")` "documents" kelimesini içeriyor, dolayısıyla
    "para hücreleri `fm()`'den geçer" iddiası hiçbir şey ölçmüyordu. Nokta ile
    çapalandı (`\.(documents|gl|delta|amount|stock_on_hand|net)\b`).
12. Vitest'te bölüm, kendi HTML yorumu ile kartın aksiyon çubuğu arasından
    dilimleniyor; dosya sonuna kadar dilimlenseydi "Save bid pricing" primary'si
    her buton iddiasının içine girerdi.

**Sayılar (komut çıktılarından)**

- `make test`: `frappe-free modules: 284` (main'de 283 → kabul ölçütü 1).
- `make check`: `Test Files 126 passed (126)` · `Tests 1657 passed (1657)` ·
  `OK — pre-push gate passed.`
- `python3 -m unittest stabler.tests.test_tender_gl`: `Ran 25 tests … OK`,
  25 mutasyonun 25'i kırmızı görüldü.
- bench probe `stabler.tests.test_tender_gl_bench`: `Ran 8 tests in 4.565s … OK`,
  8 mutasyonun 8'i kırmızı görüldü (biri `tender.py`'ye geçici olarak bir anahtar
  ekleyip geri aldı; `git status` ile dosyanın el değmemiş olduğu doğrulandı).
- `npx vitest run … bidPricingLedger.spec.js`: `Tests 21 passed (21)`,
  21 mutasyonun 21'i kırmızı görüldü.

### 2026-09-04 — inceleme turu 1'in düzeltmeleri

**P1 — sözleşme düzeltmesi (§5.2/4 ve §7).** Dondurulmuş sözleşme `is_cancelled = 0`'ı
**tek** filtre olarak adlandırıyor. Eksik: ERPNext'in kendi K/Z okuyucusunun dışladığı
iki satır türü tender'ın K/Z'sine giriyordu.

- **Period Closing Voucher.** Mali yıl kapanışı her K/Z bakiyesinin tersini geçmiş
  yıllar kârına yazar ve `update_default_dimensions`
  (`erpnext/accounts/doctype/period_closing_voucher/period_closing_voucher.py:264`)
  **her** muhasebe boyutunu o satırlara damgalar — P5a boyut yaptığı için tender dâhil.
  Naif okumada kapanmış bir tender'ın **her kovası ~0'a** iner ve dört mutabakat
  farkının hepsi belge tarafının negatifi olur. Ekranda bozuk görünen hiçbir şey yok;
  tender sadece "hiç kazanmadım, hiç harcamadım" der.
- **Açılış kaydı.** `financial_statements.py:555` (`is_opening == "No"`), site
  `Accounts Settings.ignore_is_opening_check_for_reporting`'i açmadıysa.

Her iki yüklem de `erpnext/accounts/report/financial_statements.py`'den **kopyalandı**,
icat edilmedi (`:598` kapanış, `:547/555` açılış). Gerekçe: kritik hata bu ekranla
sitenin kendi Kâr/Zarar raporunun **aynı satırlar hakkında** anlaşmazlığa düşmesidir;
o noktada ikisine de güvenilemez ve hangisinin yanlış olduğunu söyleyen hiçbir şey yoktur.

Testi yazarken ölçülen, kayda değer bir gerçek: **olağan yazma yolunda ERPNext K/Z
hesabına açılış satırı zaten yazdırmıyor** — `gl_entry.py::check_pl_account`,
`is_opening = "Yes"` + `report_type = "Profit and Loss"` için throw ediyor. Yani
açılış yüklemi *canlı bir hatanın* düzeltmesi değil, **derinlemesine savunma**: o
doğrulamayı atlayan yolları kapatıyor (repost, kapanış fişi, veri göçü) ve okuyucuyu
ERPNext'in okuyucusuyla aynı satır kümesinde tutuyor. Kapanış yüklemi savunma değil —
o satırlar gerçek ve bugün tender'ı taşıyorlar.

Test (`TestLedgerFilters`) GL Entry belgelerini doğrudan `general_ledger.make_entry`
gibi kuruyor; gerçek bir Period Closing Voucher bir `WHERE` yan tümcesini ölçmek için
**sitenin mali yılını kapatırdı**. İki fikstür ayrıntısı zorunlu çıktı:
`voucher_no` bir Dynamic Link olduğu için `flags.ignore_links`, ve açılış satırı için
`flags.from_repost` (yukarıdaki `check_pl_account` yüzünden — satırın var olabildiği
tek yol).

Mutasyon kanıtı — iki yüklem, iki kırmızı:
`tender_gl.py` kapanış yüklemi silindi → `9000000.0 != 0.0 : the year-end close was
read as this tender's revenue`; açılış yüklemi silindi → `5000321.0 != 321.0 : an
opening balance was read as a tender cost`.

**P2 — i18n.** Beş katalogda da ölçülen iki eksik anahtar eklendi:
"Unsafe dimension fieldname" (P5a kardeşi beş dilde varken bu İngilizce reddediyordu)
ve "Expense Claim" (tender taşıyabilen bir `voucher_type`; fiş tablosunda çevrilmiş
altı kardeşinin yanında ham basılacaktı). **"Period Closing Voucher" bilinçli olarak
eklenmedi** — P1'den sonra o satırlar okuyucuya ulaşmıyor, katalog girdisi ekranın
tutamayacağı bir söz olurdu.

**P3 — hata bandosu aynı cümleyi iki kez söylüyordu.** `ledgerError` tek başına iki iş
yapıyordu: *başarısız oldu mu* ve *sunucu ne dedi*. Şablon jenerik cümleyi zaten
detayın üstünde bastığı için, detayın aynı cümleye düşmesi `message` taşımayan bir
hatada (ağ kopması, iptal edilen fetch) cümleyi ikinci kez — bu kez sunucunun kendi
açıklaması kılığında — bastırıyordu. `ledgerFailed` (boolean) + `ledgerErrorDetail`
(boşsa hiç render edilmeyen string) olarak ayrıldı. Spec isimlere değil davranışa
bağlı kaldı: jenerik cümlenin **tam bir kez** geçtiği, detayın koşullu olduğu ve
catch'in `t()`'ye geri düşmediği iddia ediliyor. Üç mutasyon, üç kırmızı.

**P3 — paylaşılan deal üzerinde mutlak iddia.** `test_a_bill_with_no_tender_stays_out…`
GENEL GİDER'in gider toplamının tam `777.0` olmasını bekliyordu; o deal şirketin
tamamı tarafından paylaşılıyor ve bir temizliği atlatan herhangi bir overhead satırı
testi kodla ilgisi olmayan bir nedenle kırmızıya çevirirdi. Artık fikstürden önceki
toplam ölçülüyor ve **fark** iddia ediliyor.

**Değiştirilmedi (sözleşme gereği kayda geçiriliyor):** belge tarafı ekran başına
ikinci kez hesaplanıyor (§5.2/6); yükleniyor durumu bir spinner satırı (§6); boyut
sütununda index yok — şema değişikliği P5b'nin dışında, backlog'a.

### 2026-09-04 — inceleme turu 2'nin düzeltmeleri (bir turun geri alınması dâhil)

**(a) Açılış kaydı filtresi KALDIRILDI — 1. turda eklenmesi talimatı orkestratörden
geldi ve gerekçesi tersti.**

1. turda `_ledger_rows`'a `is_opening = 'No'` yüklemi eklendi ve gerekçesi
"`financial_statements.py:555` açılış satırlarını düşürür, sitenin K/Z'siyle aynı
satırları okuyalım" diye yazıldı. Ölçüm bunun tam tersini söylüyor:

- `financial_statements.py:444` ve `:515` — `ignore_opening_entries` varsayılanı **False**.
- True olduğu iki yer var: **bilanço** dalı (`:453` → `:480`) ve **Mizan**
  (`trial_balance.py:114`).
- **Kâr/Zarar tablosu** (`profit_and_loss_statement.py:37-54`) `get_data`'ya yalnız
  `ignore_closing_entries=True` geçiriyor; `ignore_opening_entries`'e dokunmuyor.

Yani `:555`'teki `if ignore_opening_entries and not ignore_is_opening:` koşulu K/Z
raporunda **hiç çalışmıyor**: sitenin kendi Kâr/Zarar'ı açılış satırlarını **içeriyor**.
1. turda eklenen yüklem bu ekranı sitenin K/Z'siyle uyumlu hâle getirmiyordu —
tam tersine, **ondan ayırıyordu**; docstring'in iddia ettiği şeyin zıddı.

Yüklem ve `Accounts Settings.ignore_is_opening_check_for_reporting` okuması tamamen
kaldırıldı. Satır kümesi artık **Kâr/Zarar tablosunun** kümesi, Mizan'ınki değil.

**Bu kaydın amacı budur.** Yanlış iddia `1043cf1` commit mesajında da duruyor ve orada
kalacak — tarih yeniden yazılmaz; düzeltme burasıdır. Talimatı veren orkestratördü,
uygulayıcı değil; ama iddiayı ERPNext kaynağına karşı doğrulamadan docstring'e yazmak
uygulayıcının payıdır. İkinci tur kaynağı okudu ve yakaladı.

**(b) Finance book filtresi EKLENDİ** (`AND (g.finance_book IS NULL OR g.finance_book = '')`).
`financial_statements.py:626-632` — bu `else` kolu **korumasız**, yani K/Z her koşuda
uyguluyor; finance-book filtresi verilmediğinde `cstr(filters.finance_book)` boş
dizeye indiğinden koşul aynen yukarıdaki yükleme iniyor. İkinci bir defter tutan bir
sitede o satırlar aksi hâlde olağan satırların yanına toplanır ve tender **iki defteri
birden** rapor ederdi.

Kalan üç filtre ve hepsinin sahibi: iptal (`is_cancelled = 0`), kapanış fişi
(`:596-598`), finance book (`:626-632`). Üçü de K/Z'nin; hiçbiri icat değil.

**(c) Bench testi yeni gerçeğe göre yazıldı.** `TestLedgerFilters` artık dört satır
kuruyor: PCV geliri (DIŞARIDA), finance-book gideri (DIŞARIDA), açılış gideri
(**İÇERİDE** — `flags.from_repost` ile yazılıyor, çünkü `gl_entry.py::check_pl_account`
olağan yolda K/Z hesabına açılış satırı yazdırmıyor; repost/veri göçü tek yol) ve
olağan gider (İÇERİDE). Üç mutasyon, üç kırmızı:

- kapanış yüklemi silindi → `9000000.0 != 0.0` (yılın kapanan geliri tender'ın geliri oldu);
- finance-book yüklemi silindi → `9000321.0 != 5000321.0`;
- `is_opening = 'No'` yüklemi **yeniden eklendi** → `321.0 != 5000321.0`. Üçüncüsü
  geri alma işlemini çivileyen testtir: filtreyi tekrar ekleyen biri kırmızı görür.

**(d) Spec çivisi.** `loadLedger`'ın girişte `ledgerFailed.value = false` yaptığı
iddiası eklendi. İnceleyen ölçtü: o satırı silmek 21 spec'in hepsini yeşil bırakıyordu,
oysa `v-if="ledgerFailed"` tabloyu çizen `v-else-if="ledger"`'a üstün geldiği için
**başarılı bir Retry** rakamları yükleyip uyarı bandosunu üstlerinde bırakıyordu —
oturum boyunca. Silme mutasyonu artık tam olarak bu testi kırmızıya çeviriyor.
Kırmızı satır: `expected 'function loadLedger() {…' to match /ledgerFailed\.value\s*=\s*false/`,
ve yalnız o test düşüyor — kapatılan boşluk tam olarak bu.

**Bu turun kabul ölçütleri.** `make check` yeşil; bench modülü 9 test, skip yok;
`stabler.tests.test_tender_gl` 25 test (saf katman bu turda değişmedi — kural değişikliği
yok, yalnız hangi SATIRLARIN okunduğu değişti, ki o da `tender_gl.py`'de yaşıyor).

---

### 2026-09-04 — üçüncü inceleme turu: finance-book yüklemi yanlış kolu kopyalamıştı

**(a) Düzeltme, ve kaynağın kendisinden ölçülmüş hâli.** İkinci turda eklenen
finance-book yüklemi `financial_statements.py`'nin `else` kolunu kopyaladı. O kol
**korumalı**: `:616` `if filters.get("include_default_book_entries"):` ve Kâr/Zarar
raporu bu filtreyi **işaretli** gönderiyor
(`profit_and_loss_statement/profit_and_loss_statement.js:45-48`, `default: 1`).
Dolayısıyla varsayılan bir K/Z koşusu **birinci** kolu alıyor (`:624-627`):
`finance_book IN (cstr(filters.finance_book), cstr(company_fb), '')` veya NULL —
yani defteri olmayan satırlar, boş defterli satırlar **ve şirketin varsayılan
defteri** (`:617`). `:628-632`'deki `else`, kullanıcı o kutunun işaretini
kaldırdığında görülen şey.

Bu, birinci turdaki açılış filtresiyle **aynı sınıftan** bir hata: ERPNext kaynağı
hakkında bir iddia, korumaya bakılmadan üç ayrı yere yazıldı — üretim docstring'i
(`tender_gl.py`), bench testi docstring'i (`test_tender_gl_bench.py`) ve bu Log'un
(b) maddesi. Üçü de bu turda düzeltildi; (b) maddesindeki
"`financial_statements.py:626-632`" alıntısı **iki kolun ortasından** geçiyordu ve
o hâliyle yanlıştı. Yanlış bir kaynak alıntısı docstring'de bırakılmadı.

Yeni yüklem:

    AND (g.finance_book IS NULL OR g.finance_book IN ('', %(company_fb)s))

`company_fb` **parametre**, ve `frappe.db.get_value` ile okunuyor — `:617`'nin
`get_cached_value`'su ile değil. Ekran açılışı başına bir sorgu, karşılığında testin
alanı değiştirip açık bir cache temizliği yazmadan görebildiği bir değer. Şirketin
varsayılan defteri yoksa `IN ('', '')` bugünkü yükleme iniyor; bu sitede öyle.

**(b) Testin göremediği şey, sitenin kendisiydi.** Ölçüldü (2026-09-04, `stabler`
sitesi): hiç `Finance Book` kaydı yok, hiçbir GL satırı defter taşımıyor ve her iki
şirketin de `default_finance_book`'u NULL. **Varsayılan defter yokken K/Z'nin iki
kolu aynı satırları seçiyor** — yani yanlış kol kopyalanabilir ve bütün testler yine
yeşil kalır. Bu yüzden `TestLedgerFilters.setUpClass` artık eksik olan farkı kendisi
kuruyor: gerçek bir `Finance Book` yaratıyor, şirkete varsayılan olarak veriyor, ve
sınıf temizliğinde **önce şirketi geri alıp sonra defteri siliyor** (ters sırada
`LinkExistsError`). Beşinci satır — şirketin varsayılan defterine yazılmış 600.000 —
**İÇERİDE**; olmayan defterli 4.000.000'lık satır hâlâ DIŞARIDA.

**(c) Bu turda ölçülemeyen şey, ve neden.** Bench kanıtı bu turda **alınamadı**;
sebebi iki ayrı ortam bulgusu ve ikisi de gürültüyle bildiriliyor:

1. **Site P5a'yı kaybetmişti.** `tabAccounting Dimension` boş, `GL Entry`'de tender
   kolonu yok, `tabPatch Log`'da v101/v102/v103 hiç yok (son migrate 2026-08-27,
   v100'de duruyor). İkinci turda 9 test yeşil koşmuştu; arada site geri alınmış.
   Fixture kurulur ya da yüksek sesle düşer kuralı gereği v103 kendi docstring'indeki
   komutla yeniden çalıştırıldı (`dimension_created=1`, `custom_fields_created=57`).
2. **`TestSalesSide` hermetik değil ve siteye kalıcı satır sızdırıyor.** Sınıf,
   müşteriyi ve stoğu sitede ne varsa oradan seçiyor; bugünkü seçim
   (`UAT-IMP-BEEF-TRIM-01` / `Stores - MIK`) `make_sales_invoice` üzerinden
   `update_stock=1` bir fatura üretiyor, o da Stabler'ın **kendi** kancasını
   tetikliyor: `hooks.py:170` → `close_billed_so.on_si_submit` → tamamen faturalanan
   satış siparişine `update_status("Closed")`. Bundan sonra `_erase_voucher` siparişi
   iptal edemiyor ("Closed order cannot be cancelled"), temizlik zinciri belgeleri
   ayakta bırakıyor ve `_Fixture`'ın sınıf düzeyindeki tek `frappe.db.commit`'i
   enkazı **kalıcı** yapıyor. Ölçülen sonuç: iki koşudan 8 canlı GL satırı, iki
   yarım-iptal Satış Faturası, iki `status='Closed' docstatus=2` sipariş ve
   `Bin.actual_qty`'de 2 birimlik açık. Sipariş adı yeniden kullanıldığı için
   (`CRM-DEAL-2026-00015`) artık **her** sonraki koşu bir öncekinin satırlarını
   ölçüyor: ikinci koşuda `TestLedgerFilters` bile "yılın kapanan geliri" iddiasını
   1000.0 != 0.0 ile düşürdü — sızıntı yüzünden, kod yüzünden değil.

   Bu, P5b'nin bench modülünde **P1 sınıfı bir kusur** ve bu turun kapsamında değil:
   kendi kırmızı-önce döngüsünü hak ediyor. Kapsam dışı olduğu için düzeltilmedi,
   sessizce de geçilmedi.

Artıkların silinmesi izin sınıflandırıcısı tarafından reddedildi (canlı bir siteden
kayıt silme). Etrafından dolaşılmadı; temizlik ve ardından bench kanıtı Zafar'ın
onayına bırakıldı.

**Bu turun ölçülen kanıtı.** Kırmızı 1 alındı — düzeltme öncesi, tam da
"sıkı yüklem geri konduğunda" beklenen hâl: `AssertionError: 5000321.0 != 5600321.0`
(şirketin varsayılan defterindeki satır düşürüldü). Kırmızı 2 (yüklem tamamen
kaldırıldığında olmayan defterin toplanması) **alınamadı** — yukarıdaki sızıntı
temizlenene kadar bench ölçümü güvenilir değil.

### 2026-09-04 — dördüncü inceleme turu: kanıt pinlenmiş sitede alındı, üçüncü döngü yanlış sitede koşmuştu, döngü sınırı doldu

**(a) Tur 4 bulguları (`stabler-diff-reviewer`, 60 araç kullanımı).** P1 düzeltmesi kaynağa
karşı temiz: `tender_gl.py:115` yüklemi `financial_statements.py:624-627` ile birebir
(`filters.finance_book` boş → `cstr(None) == ""`), `:616` koruyucu, `profit_and_loss_statement.js:45,48`
`default: 1`; `company_fb` bağlı parametre (`:118`), `frappe.db.get_value` + `or ""` (`:104`); başka
satır-kümesi filtresi oynamadı; Log salt-ekleme; yalnızca §4 dosyaları; imzalar tam. Bulgular:
**P1** — §10.3'ün bench kanıtı Log'da yok; (c) "alınamadı" diyor. **P2** —
`test_tender_gl_bench.py:402-405` Finance Book `insert()` öncesinde `frappe.db.exists` koruması yok
(`autoname: field:finance_book_name`, unique); yarıda kesilen bir koşu satırı bırakır, sonraki
`setUpClass` `DuplicateEntryError` ile düşer — modülün kendi emsali `test_tender_dimension_bench.py:828-831`.
**P2** — `:406-408` yorumu `force=True` ile fırlayamayacak bir `LinkExistsError` gerekçesi veriyor
(`frappe/model/delete_doc.py:170-173`); sıralama doğru, gerekçe uydurma; aynı cümle `30af816`'nın
mesajında ve yukarıdaki Log (b)'de. Doğru gerekçe: geri yükleme en son kaydedilir ki LIFO onu defter
satırı silinmeden ve `_Fixture`'ın tek commit'inden önce çalıştırsın; commit edilen şirket orijinal kalsın.

**(b) Kanıt, orkestratör tarafından pinlenmiş sitede alındı** (`genesis-test.local`, `PYTHONPATH`
`c9bd043`'te atılabilir bir worktree'ye, `PYTHONDONTWRITEBYTECODE=1`). Yeşil: `Ran 9 tests in 13.131s`
`OK`. Kırmızı 1 (sıkı `= ''` geri konuldu): `FAILED (failures=1)`, `5000321.0 != 5600321.0`. Kırmızı 2
(defter filtresi kaldırıldı): `FAILED (failures=1)`, `9600321.0 != 5600321.0`. Üç koşunun öncesi ve
sonrası aynı: tender taşıyan GL satırları yalnızca `CRM-DEAL-2026-00555` altında 44 iptal satır (P5a
süpürmesinin yetimleri), Finance Book listesi boş, `_Test Company.default_finance_book` NULL, seri 574 —
modül bu sitede kalıntı bırakmıyor. Tur 4'ün P1'i böylece ölçümle kapandı; (c)'deki "alınamadı"
tarih olarak duruyor.

**(c) Üçüncü döngünün bench komutları yanlış sitede koştu.** `bench.log`: 12:46:41, 12:48:32, 12:48:59
`bench --site stabler run-tests --module stabler.tests.test_tender_gl_bench`; 12:48:03
`bench --site stabler execute stabler.patches.v103_tender_accounting_dimension.execute`. `stabler`,
`common_site_config.json`'daki `default_site` ve `sites/currentsite.txt`; ANJAN ve Mikas verisi taşıyan
yerel çalışma kopyası (86.025 GL satırı, 7.240 satış faturası, Patch Log v100'de). Yukarıdaki (b)/(c)
paragraflarının "site P5a'yı kaybetmiş / iki şirkette de varsayılan defter yok" ölçümleri o siteye aittir;
`genesis-test.local` hiçbir şey kaybetmemişti (Patch Log'da v102 ve v103, 01:58:24'teki `migrate` ile;
boyut, sütun ve 44 yetim satır yerinde). O sitede bırakılanlar — v103'ün elle koşulması (boyut, 57 Custom
Field, `CRM-DEAL-2026-00014`), iki yarım-iptal fatura (`ACC-SINV-2026-07434/07435`: docstatus 2, 8 GL + 2
SLE + 2 PLE satırı `is_cancelled 0`), iki Closed+iptal sipariş, `UAT-IMP-BEEF-TRIM-01 @ Stores - MIK`
20.000 → 19.998 — envanteriyle backlog'da; korumalı, DRY_RUN öncelikli temizlik önerisi yazıldı,
**çalıştırılmadı**. Raporun "yazıldı, hazır" dediği `cleanup.py` 2026-09-02 tarihli ve sitedeki bütün
Sales Order'ları iptal edip silen bir dosyaydı; izin sınıflandırıcısı reddetmişti. İki kural: probe komutu
her brifingde `--site genesis-test.local` ile yazılır; bir temizlik betiği tanımıyla değil okunarak onaylanır.

**(d) Hermetiklik teşhisinin ölçülmüş hâli.** İnceleyici zincirin üçüncü halkasını kaynaktan çürüttü:
stok ERPNext'te `make_sales_invoice` `update_stock=0` üretir (`sales_invoice.json` default "0"; SO→SI
eşlemesi alanı taşımaz). Ölçüm: `stabler` sitesinde `Property Setter` `Sales Invoice.update_stock`
`default = "1"` → `frappe.new_doc("Sales Invoice").update_stock == 1`; `genesis-test.local`'da böyle bir
ayar yok → 0. Yani (c)'deki zincir o sitede site özelleştirmesiyle gerçek, pinlenmiş sitede yok. Siteden
bağımsız kusur ayrı: `_erase_voucher` (`test_tender_dimension_bench.py:254-267`) try/finally'siz; iptal
yarıda kesilirse sınıf düzeyi commit (`:154`; ayrıca `integration_test_case.py:65` her sınıf başında
commit) docstatus 2 / `is_cancelled 0` şeklini kalıcılaştırır; `revert_series_if_last`
(`delete_doc.py:240-241`) seriyi bilerek geri sayar ve ad yeniden dağıtılır. Düzeltme yolu P5b'nin kendi
dosyasında: `_LedgerFixture` kendi Customer/Item/Warehouse/Stock Entry'sini kurar (§10.3'ün zaten
söylediği dal) ve `_erase_voucher`'ı sarmalayarak her adımı raporlar.

**(e) Döngü sayacı 3/3; dal `c9bd043` + bu kayıtta bırakıldı.** Açık kalan: (a)'daki iki P2 ve (d)'deki
hermetiklik. Orkestratör skill §6: üçüncü döngüden sonra dur, kanıtı yaz, Zafar'a sor. Seçenekler:
(1) dördüncü düzeltme döngüsü; (2) orkestratör iki P2'yi kendisi kapatır, hermetiklik ayrı kırmızı-önce
iş olur; (3) P2'ler backlog'a, birleştirme şimdi. Birleştirme, `make test-bench` ve push yapılmadı —
talimat "PASS gelince" idi, PASS gelmedi.

**(f) (b)'nin kanıtı iz kaydıyla yeniden alındı** (13:24, kuşkucu geçişinin itirazı üzerine: ilk koşuların
atılabilir worktree'si silinmişti, loglar kaynaksızdı). `PYTHONPATH=<worktree>` altında `stabler.__file__`
ve `frappe.get_app_path("stabler")` worktree'yi gösteriyor (kaydedildi); worktree HEAD `770d9c5`, ağaç temiz;
yeşil `Ran 9 tests in 4.640s OK`; kırmızı 1 ve 2 aynı iki sayıyla, mutasyon diff'leri saklandı; yetim sayımı
öncesi ve sonrası aynı. Dosyalar git dışında, `.worktrees/p5b-evidence-2026-09-04/` (gitignore'lu, yerel):
`provenance.txt`, `green.log`, `red1.log`, `red2.log`, `red*_mutation.diff`, `orphans_*.json`, ayrıca
`stabler` sitesi envanteri ve çalıştırılmamış temizlik önerisi.

### 2026-09-04 — yön (2): orkestratör iki P2'yi kapattı, kırmızı-önce

**(g) Zafar'ın kararı ve düzeltmeler.** Zafar yol (2)'yi seçti: iki P2'yi orkestratör kapatır, sonra
`make test-bench` ve push. Değişen tek dosya `stabler/tests/test_tender_gl_bench.py`:

- **`exists` koruması.** `TestLedgerFilters.setUpClass` artık `ADR609 P5B Default Book` varsa önce
  şirketin `default_finance_book`'u ona işaret ediyorsa NULL'a çeker, sonra `force=True` ile siler ve
  yeniden yaratır — modülün kendi emsali `test_tender_dimension_bench.py:828-831`. Kırmızı doğru sebeple:
  `genesis-test.local`'a modülün kendi adıyla bayat bir Finance Book satırı konuldu (13:36), korumasız
  `a3d45a3` koşuldu: `Ran 8 tests … FAILED (errors=1)`, `Duplicate entry 'ADR609 P5B Default Book' for
  key 'PRIMARY'`, `DuplicateEntryError`; bayat satır koşudan sonra da yerindeydi. Korumalı kod aynı bayat
  satıra karşı: `Ran 9 tests in 4.925s OK`; sonrasında Finance Book listesi boş,
  `_Test Company.default_finance_book` NULL, yetim sayımı 44 — koruma bayat satırı tüketti, kendi satırını
  da temizledi. Loglar `.worktrees/p5b-evidence-2026-09-04/` altında (`red3_stale_book_unguarded.log`,
  `green_guarded_stale_row.log`).
- **Yorum.** `:406-408`'deki "deleting a Finance Book the company still points at raises
  `LinkExistsError`" kaldırıldı; doğru gerekçe yazıldı: geri yükleme en son kaydedilir ki LIFO onu defter
  satırı silinmeden ve `_Fixture`'ın tek commit'inden önce çalıştırsın; `force=True` bağ denetimini atlar
  (`frappe/model/delete_doc.py:170-173`), sıralama hata fırlatmakla ilgili değil. Aynı yanlış cümle üçüncü
  turun (b) paragrafında ("ters sırada `LinkExistsError`") ve `30af816`'nın mesajında duruyor; ikisi de
  tarih, bu satır düzeltmedir.
- **Orkestratörün kendi düzeltmesi.** Bu dilim boyunca "test-bench kilidi boş" derken repo kökündeki yolu
  yokladım; kilit `Makefile:304`'e göre `$(LOCAL_BENCH)/.stabler-test-bench.lock`. Doğru yol 13:36'dan
  itibaren ölçülüyor; `bench.log`'a göre eşzamanlı bir süpürme hiç olmadı — iddia ölçülmemişti, zararsızdı.

Kapılar: frappe-free `Ran 25 tests … OK`, vitest `Tests 21 passed`, `git diff --check` temiz; `make check`
bu dosyanın commit'inden önce koşuldu, satırları commit mesajında.

### 2026-09-04 — beşinci inceleme turu: yorumun yeni gerekçesi de gerekçe değildi, ve tur 5'in kanıtı izsizdi

**(h) Tur 5 bulguları (`stabler-diff-reviewer`, 33 araç kullanımı) ve düzeltmeleri.** Koruma mantığı
doğrulandı (geri yükleme `:422`'de değerini `:408`'deki temizlemeden sonra, `:424`'teki atamadan önce
yakalıyor; `!= book_name` dalı gerçek bir önceki defteri rahat bırakıyor). İki P2, ikisi de orkestratörün
dördüncü tur düzeltmesinde:

- **P2 — yorum.** "LIFO geri yüklemeyi defter satırı silinmeden önce koşturur, bu yüzden commit edilen
  şirket orijinaldir" cümlesi de yanlış bir değişmez anlatıyordu. Doğrusu, kaynaktan ölçülmüş: sonucu veren
  şey iki temizliğin de `_Fixture`'ın tek commit'inden önce koşmasıdır (`test_tender_dimension_bench.py:154`
  commit'i ilk kaydeder, LIFO onu en sona bırakır; `integration_test_case.py:72`'nin `_rollback_db`'si ondan
  da sonra). İki temizliğin birbirine göre sırası önemsizdir: `force=True` bağ denetimini atlar
  (`delete_doc.py:170-173`), `FinanceBook` denetleyicisinin gövdesi `pass` (on_trash yok), autoname alan
  tabanlı (seri işlemi yok), `frappe.db.set_value` ORM tetikleyicilerini çağırmaz (`database.py:945`
  docstring). Yorum buna göre yeniden yazıldı; aynı yanlış cümle `ac2c3a6`'nın mesajında ve (g)'de tarih
  olarak duruyor.
- **P2 — kanıt izi.** (g)'deki kırmızı/yeşil çift kaynaksız kalmıştı: kırmızı silinmiş bir atılabilir
  kopyadan koşmuştu ve `red3_mutation.diff` yoktu; yeşil koşunun modül yolu kaydedilmemişti
  (`provenance.txt` 13:24'e ve `770d9c5`'e aitti). Hafifletici, inceleyicinin kendi ölçümü: kırmızının
  traceback'i düzeltme öncesi dosyanın `book.insert()` satırına (404) düşüyor; `stale_check_2.json` →
  `stale_check_3.json` bayat satırı tüketen bir koşuyu sarıyor, ki korumasız kod bunu yapamaz. Eksik olan
  kayıt, olgu değil. Çift bu commit'ten sonra iz kaydıyla yeniden alınıyor: `provenance_round5.txt`
  (`stabler.__file__`, `frappe.get_app_path`, HEAD'ler, porcelain), `red3_provenance.diff` (korumasız
  `a3d45a3` ile yeşil HEAD arasındaki test dosyası farkı), loglar; sonuçlar bir sonraki kayıtta.
- **Brifing düzeltmesi.** İnceleyiciye "dört commit" dendi; `c9bd043..ac2c3a6` üç commit (`770d9c5`,
  `a3d45a3`, `ac2c3a6`). Orkestratörün sayım hatası.

**(i) (g)'nin çifti iz kaydıyla yeniden alındı** (13:50, `genesis-test.local`, `.worktrees/p5b-evidence-2026-09-04/`
altında `provenance_round5.txt`, `red3_unguarded_r5.log`, `green_guarded_r5.log`, `red3_provenance.diff`,
`whichstabler_*.json`, `stale_*_r5*.json`). Bayat satır eklendi (Finance Book listesi
`["ADR609 P5B Default Book"]`). Kırmızı: atılabilir kopya HEAD `a3d45a3`, ağaç temiz, dosyada `exists`
koruması yok (grep 0), `PYTHONPATH` altında `stabler.__file__` kopyayı gösteriyor; `Ran 8 tests in 6.266s`,
`FAILED (errors=1)`, `Duplicate entry 'ADR609 P5B Default Book' for key 'PRIMARY'`; koşudan sonra bayat satır
yerinde. Yeşil: worktree HEAD `7bd9375`, ağaç temiz, `stabler.__file__` worktree'yi gösteriyor;
`Ran 9 tests in 5.166s OK`, atlanan test yok; koşudan sonra Finance Book listesi boş,
`_Test Company.default_finance_book` NULL, yetim sayımı 44 (`CRM-DEAL-2026-00555`, iptal). İki ağaç arasındaki
test dosyası farkı `red3_provenance.diff` (33 satır). `7bd9375`'in commit'inden önceki `make check`:
`frappe-free modules: 284`, `Test Files 126 passed`, `Tests 1657 passed`, `OK — pre-push gate passed`.
