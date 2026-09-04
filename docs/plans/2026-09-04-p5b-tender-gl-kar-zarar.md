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
