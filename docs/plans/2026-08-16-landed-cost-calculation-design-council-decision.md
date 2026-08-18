# Landed Cost Calculation Formu — Tasarım Kurulu Kararı (2026-08-16)

Talep (Zafar): "MSA'da landed cost hesaplamasını şu anda CI formu üzerinden yapmaya
çalışıyoruz. QuickBooks tarzı ayrı bir LC calculation formu açılsın; tüm LC ile
alakalı bill ve masrafları orada allocate edelim, allocation method'lara göre olsun."

Kurul: muhasebe/maliyet, backend mimari, frontend/UX, migrasyon-risk, şeytanın avukatı.
Başkan doğrulaması: kod tabanı + ERPNext v15 kaynağı canlı okundu (aşağıdaki her
`dosya:satır` referansı bu oturumda teyit edildi).

Zafar'ın önceden verdiği kapsam kararları (kurul bunları tartışmadı, içinde tasarladı):

- **D1** — Kapsam: Imports + Purchasing **birleşik**. Tek form hem CI/Container/GRN
  hem Purchase Receipt kaynağını alacak.
- **D2** — CI formunda yalnız **read-only landed cost özeti + link** kalacak; tüm
  masraf girişi ve allocation yeni forma taşınacak.
- **D3** — Çıktı: karar dokümanı + tıklanabilir mockup + beads issue'ları.

---

## KARAR: ACCEPT — ama sıra değişiyor. Faz 0 önce.

Form yapılacak, D1/D2 korunuyor. Ancak kurul, teşhisin eksik olduğunu buldu:
**bugün üretimde SPA'dan landed cost voucher submit edilemiyor.** Yeni form da bu
kusurun üstüne kurulursa, "submit edilemeyen taslak üreten" dördüncü ekran olur.

Bu yüzden iş sırası şu: **Faz 0 (P0 düzeltmesi) → Faz 1 (method seçimi + kalıcılık)
→ Faz 2+ (yeni doctype ve tam form).** Faz 0 ve Faz 1 birlikte ~1 haftalık iştir ve
genel muhasebeye dokunan üç kusurun üçünü de kapatır. Yeni form bu temelin üstüne
oturur, onun yerine geçmez.

İkinci sert bulgu: mimarın önerdiği voucher üretim mekanizması **ERPNext'te yasak**
çıktı (ADR-002). Düzeltilmiş strateji aşağıda; bu, formun neye benzeyeceğini değil
ama kaç voucher üreteceğini değiştiriyor ve `GRN LCV Ref` ile cancel yolunu etkiliyor.

---

## P0 · SPA landed cost voucher'ı submit edemiyor — bugün üretimde

`submit_landed_cost_voucher` whitelisted (`stabler/api/lcv.py:308`) ve JS'e bağlı
(`public/js/api/lcv.js:26`, `api/imports.js:87`). Ama tüm kod tabanında **tek bir
yerden** çağrılıyor:

```
stabler/public/js/pages/imports/LandedCostReview.vue:95   ← ÖLÜ DOSYA
```

`router.js:193` bu dosyayı değil, `pages/purchasing/LandedCostReview.vue`'yu import
ediyor ve onu hem `/imports/landed-cost/:grn` (`router.js:245`) hem
`/purchasing/landed-cost-review/...` (`router.js:359`) rotalarına bağlıyor. Routed
kopyada `createLcv` (:89) ve `cancelLcv` (:108) var, **submit yok**. Kendi toast'ı
durumu itiraf ediyor:

```
:99   "Draft voucher {lcv} created — it still needs accountant submit in the books."
:345  "The voucher is created as a draft; an accountant reviews and submits it in the books."
```

Sonuç: her voucher taslakta duruyor ve birisi Frappe Desk'te tamamlıyor. Repo
anayasası Desk'e yönlendirmeyi **yasaklıyor** (`AGENTS.md`, "No Frappe Desk
redirects, ever"), yani bu iş bugün kural dışı bir yoldan yapılıyor.

Ölü dosya aynı zamanda **zengin olan kopya**: `unitCostAnalysis` kartı (Total Net
Weight / Base Receipt Cost per kg / Final Landed Cost per kg / +%) ve Submit butonu
sadece onda var (433 satır vs. 353).

**Karar (Faz 0):** Submit routed component'e taşınacak, ölü dosya **aynı PR'da**
silinecek, toast metinleri 5 dilde düzeltilecek. Aksi halde yeni form, tek Submit
butonunu barındıran ölü bir dosyanın yanında dördüncü akış olarak doğar.

## P1 · `distribute_charges_based_on` sabit kodlu `"Qty"`

```
stabler/stabler/imports_module/lcv_math.py:399
    def build_lcv_payload(*, company, purchase_receipts, components,
                          expense_account, distribute_based_on="Qty"):
stabler/stabler/imports_module/lcv_math.py:412
    "distribute_charges_based_on": distribute_based_on,
stabler/api/lcv.py:291
    distribute_based_on="Qty",          ← tek çağrı yeri, sabit
```

`distribute_charges_based_on` **hiçbir `.vue`/`.js` dosyasında geçmiyor.** Parametre
zaten var, sadece hiç kullanılmıyor. Bugüne kadar submit edilmiş her voucher, karışık
UOM'lu satırlarda Qty ile dağıtıldı — 12 adet + 3 ton + 400 m toplanıp 415 "birim"
üzerinden bölündü.

**Karar:** Faz 1'de select olarak açılacak ve seçim kalıcı yazılacak.

## P2 · Allocation method hiçbir yerde saklanmıyor

`calculate_ci_landed_cost_uzs` (`api/imports.py:3271-3380`) dört method destekliyor
— `By Weight` (default) / `By Value` / `By Quantity` / `Equal` — ama **display-only**;
hiçbir şey post etmiyor, seçim ephemeral Vue state, reload'da `By Weight`'e dönüyor.
`Commercial Invoice Item`'da tek bir landed cost alanı yok.

Denetçi 8 ay sonra "bu SKU neden 2,14 $/kg navlun taşıyor?" diye sorduğunda cevap
verecek kayıt bugün veritabanında **yok**.

## P3 · CI formunda aynı sayfada iki çelişen landed sayı

```
CommercialInvoiceForm.vue:1061
    itemLandedCostPerKg(row) → round4(row.rate + costOverviewData.operational.per_kg)
```

Items grid'i düz ortalama uplift gösteriyor; alttaki "Landed cost (UZS)" tablosu
seçilen method'a göre bambaşka bir sayı gösteriyor. İkisi birbirini bilmiyor.
D2 kapsamında ikisi de kaldırılıyor — ama Faz 0'da bile 5 satırlık düzeltmeyle
tutarlı hale getirilebilir.

---

## ADR-001 — Yeni doctype: `Landed Cost Calculation` (submittable)

Üç seçenek tartışıldı:

| | Yaklaşım | Sonuç |
|---|---|---|
| A | Yeni submittable `Landed Cost Calculation`, submit'te LCV üretir | **SEÇİLDİ** |
| B | Yeni doctype yok; `Container Cost Line` + yeni allocation child table | Elendi |
| C | Doctype yok; ERPNext LCV'yi custom Vue ile doğrudan sür | Elendi |

**B neden elendi:** `Container Cost Line`, `Import Container`'ın child'ı. Yapısal
olarak bir Purchase Receipt kaynağı taşıyamaz — D1'in tam da istediği şey. B'yi
seçmek purchasing masraflarını JSON blob'da bırakmak demek: `Purchase Order
.custom_landed_charges` (v35), `Supplier Quotation.custom_landed_charges` (v69),
`Purchase Receipt.custom_landed_cost_settings` (v48). Sonuncusunun include haritası
**charge label'ıyla anahtarlı** (`lcv.py:236`) — aynı isimli iki masraf çakışıyor,
label değişince include state sessizce kopuyor.

**C neden elendi:** `distribute_charges_based_on` doküman seviyesinde tek bir Select.
Charge satırı bazında method vermek için `Landed Cost Taxes and Charges`'a custom
field + `set_applicable_charges_for_item` override'ı gerekir — envanter
değerlemesini belirleyen tek fonksiyonu monkeypatch etmek, her ERPNext yükseltmesinde
yeniden doğrulanmak zorunda. Ayrıca LCV'nin `items` tablosu her reload'da
`get_items_from_purchase_receipts()` ile yeniden üretiliyor; elle girilmiş satır
tutarları yok oluyor.

**A'nın geri dönüş maliyeti düşük:** LCC saf bir *upstream üretici*. Muhasebe gerçeği
LCV'de kalıyor, GL'e dokunulmuyor. Vazgeçmek = `create_calculation` çağrısını
kesmek, doctype'ları silmek; her LCV yerinde kalır.

## ADR-002 — ERPNext kısıtı: "Distribute Manually" tek tax satırı kabul ediyor

Bu, kurulun ilk turda **yanlış** kurduğu ve doğrulamada düzeltilen maddedir.
ERPNext version-15 kaynağından birebir
(`erpnext/stock/doctype/landed_cost_voucher/landed_cost_voucher.py`):

```python
# :41
distribute_charges_based_on: DF.Literal["Qty", "Amount", "Distribute Manually"]

# :187-215  — Distribute Manually seçiliyse ERPNext hesabı HİÇ yapmıyor
def set_applicable_charges_on_item(self):
    if self.get("taxes") and self.distribute_charges_based_on != "Distribute Manually":
        ...
        if total_charges != self.total_taxes_and_charges:
            diff = self.total_taxes_and_charges - total_charges
            self.get("items")[item_count - 1].applicable_charges += diff   # kalan → SON satır

# :217-222  — ve tek tax satırı dayatıyor
def validate_applicable_charges_for_item(self):
    if self.distribute_charges_based_on == "Distribute Manually" and len(self.taxes) > 1:
        frappe.throw(_("Please keep one Applicable Charges, when 'Distribute Charges
          Based On' is 'Distribute Manually'. For more charges, please create another
          Landed Cost Voucher."))

# :247-256  — tolerans
diff = flt(flt(self.total_taxes_and_charges) - flt(total_applicable_charges), precision)
if abs(diff) < (2.0 / (10**precision)):
    self.items[-1].applicable_charges += diff
else:
    frappe.throw(_("Total Applicable Charges ... must be same as Total Taxes and Charges"))

# :259-260  — kontrol validate'te DEĞİL, submit'te
def on_submit(self):
    self.validate_applicable_charges_for_item()
```

Üç sonuç, üçü de tasarımı bağlıyor:

1. Çoklu tax satırı + Distribute Manually **submit'te patlar**. Draft temiz kaydolur,
   patlama en geç anda gelir. Ön kontrol bizim olmak zorunda.
2. Tax satırlarını tek satıra toplayıp kısıtı aşmak **yasak**.
   `capitalized_components()` (`imports_module/hooks.py:829-911`) `Landed Cost Taxes
   and Charges.description` + `base_amount` okuyup `apply_gtd_customs_precedence()`
   netlemesini buradan sürüyor. Component'leri birleştirmek, zaten kapitalize edilmiş
   gümrük vergisinin bir sonraki build'de **tekrar** teklif edilmesi demek — sessiz
   çifte kapitalizasyon.
3. Native yolda kalan kuruş **son satıra** yazılıyor; bizim largest-remainder
   sözleşmemiz orada geçersiz.

**Karar — voucher emisyon stratejisi (hibrit, gruplu):**

| Charge grubu | Voucher | `distribute_charges_based_on` | Tax satırı |
|---|---|---|---|
| Hepsi `By Value` | 1 voucher | `Amount` | N satır, her biri `description = cost_component` |
| Hepsi `By Quantity` | 1 voucher | `Qty` | N satır |
| Weight / Volume / Equal / Manual / Direct | **charge satırı başına 1 voucher** | `Distribute Manually` | tam 1 satır, `applicable_charges` bizden |

Gerçekçi bir MSA sevkiyatı (16 masraf / 3 konteyner / 43 kalem): en iyi 2 voucher,
tipik **~12**, en kötü 16. Etkileri:

- `GRN LCV Ref` zaten child table — 1 yerine 12 satır. `landed_cost_calculation`
  (Link) + `charge_row` (Data) alanları eklenecek ki her voucher kendi masrafına
  kadar izlenebilsin.
- `Container Cost Line.lcv_ref` **değişmiyor** ve daha temiz oluyor: 1 cost line →
  1 voucher, bugünkü çok-satır-tek-voucher belirsizliği kalkıyor.
- Cancel doğası gereği **kısmi** olabiliyor. `cancel_calculation` ters sırada
  ilerleyecek, resumable olacak, yarıda kalırsa `lcv_status = "Partially Cancelled"`
  yazacak — yarım gerçek yazmayacak.

## ADR-003 — Allocation basis charge satırı seviyesinde

Doküman seviyesinde tek basis **aritmetik olarak yetersiz**. Aynı sevkiyatta navlun
ağırlıkla, ad valorem gümrük vergisi gümrük değeriyle, sertifika eşit, demuraj
doğrudan tek konteynere dağıtılır. Tek basis bunu ifade edemez.

Doküman seviyesinde bir **`default_allocation_method`** kalır (varsayılan `By Value`)
— her satır onu miras alır, "hiç karar vermeden çalışan yol" korunur. Satır bazında
override serbesttir ve satır sayacı UI'da kaç voucher üretileceğini canlı gösterir.

## ADR-004 — İki aşamalı allocation korunacak, tek ekranda gösterilecek

Bugün iki bağımsız aşama var: (a) bill/masraf → konteyner
(`_imports_rules.py:703 allocate_by_weight`), (b) konteyner masrafı → receipt kalemi
(LCV). Kurul **birleştirmeyi reddetti**:

- Konteyner başlı başına bir maliyet objesi. Demuraj, THC, depolama konteyner
  gerçeğidir; ekip itirazları konteyner numarası üzerinden tartışıyor.
- Receipt'ler konteynerle 1:1 değil (kısmi GRN, bölünmüş konteyner). Birleştirmek
  "MSKU1234 kaça mal oldu" sorusunu cevapsız bırakır.
- `Container Cost Line` + `lcv_ref` zaten **aşama-1 defteri ve tüketim işareti**.
  Birleştirmek çalışan mutabakatı çöpe atar.

18.000 $ / 3 konteyner / 40 SKU örneği: aşama-1 kg ile 24.000 / 31.000 / 26.000 ⇒
81.000 kg üzerinden 5.333,33 / 6.888,89 / 5.777,78. Aşama-2 her konteynerin tutarını
**yalnız o konteynerin kalemlerine** dağıtır. İki aşama aynı driver'ı kullanınca
sonuç birleşik hesapla aynı çıkar; aşama-1 ağırlık, aşama-2 değer olunca ayrışır —
ve gümrük dosyası ile demuraj talebi konteyner numarası üzerinden yürür.

`source_type = Purchasing` iken aşama-1 tamamen gizlenir.

## ADR-005 — Yuvarlama ve mutabakat sözleşmesi

- Her masraf UZS'ye **bir kez**, voucher tarihindeki kurla çevrilir; kur satıra
  yazılır, post anında yeniden türetilmez. `line_company_amount` `None` dönerse
  (kur yok) → **sert blok**, satır adıyla.
- Hassasiyet 2 hane (mevcut `lcv_math.py` genelindeki `round(x, 2)` ile uyumlu).
- **Manual-basis voucher'larda** largest-remainder: `i = 1..n−1` için
  `share_i = round(C × d_i / Σd, 2)`, kalan kuruşlar en büyük ondalık artığı olan
  satırlara birer birer, eşitlikte `idx` küçük olana. Deterministik.
- **Native-basis voucher'larda** ERPNext'in kendi formülü ve `items[-1]` kuralı
  kullanılacak — preview aynı formülü çalıştırmazsa 43 satırda kuruş kuruş sapar.
  `allocation.py` bu yüzden `remainder: Literal["largest_remainder","last_row"]`
  parametresi alacak.
- **Submit öncesi zorunlu invariant** (`==`, `< 0.01` değil):
  `Σ share = C` her masraf satırında; `Σ aşama-2 = Σ aşama-1 = Σ include=1 satırlar`.
  Hedef, ERPNext'in `2/(10**precision)` toleransının **içinde** kalmak; böylece onun
  `items[-1] += diff` düzeltmesi ispatlanabilir şekilde no-op olur ve para sessizce
  son satıra kaymaz.
- Pozitif masraf için negatif pay yasak. Ama **iade/credit note negatif masraf olarak
  girilir ve meşru negatif pay üretir** — bugünkü blanket "negatif satırı reddet"
  kuralı bunu yanlışlıkla bloke ediyor, düzeltilecek.

---

## Allocation method kataloğu

`C` = masraf, hedef satır `i`, driver `d_i`, `share_i = C × d_i / Σd`.

| Method | Driver | Ne zaman | Kırılma noktası | v1 |
|---|---|---|---|---|
| **By Value / Amount** | satır tutarı, **tek** voucher kuruyla | sigorta, ad valorem vergi, akreditif/banka, komisyon | 0 değerli satır (numune) hiç yük almaz; `Σ=0` → böl-sıfır, blok | ✅ |
| **By Quantity** | stok UOM'unda `qty` — bugünkü sabit `Qty` | yalnız gerçekten homojen satırlar | karışık UOM anlamsız toplam; hedef sette >1 stok UOM varsa **uyar** | ✅ |
| **By Net Weight** | `boxes × box_weight_kg` / `total_kg` | navlun, THC, depolama, demuraj, liman | `box_weight_kg = 0` bedavacı; **kalem seviyesinde eşit-bölme fallback'i kaldırılacak** — 40 SKU'ya sessiz eşit dağıtım görünmez bir yanlış beyandır | ✅ |
| **Equal** | `n` | belge başı ücretler: tek GTD, sertifika, gümrükleme | 2 $'lık SKU ile 40.000 $'lık SKU aynı 37 $'ı taşır — **asla default olmayacak** | ✅ |
| **Manual / satır bazlı** | elle mutlak veya % | pazarlıklı bölüşüm, tek alıcıdan kaynaklı demuraj | kısmi giriş; `Σ = C` kuruşuna kadar tutmadan post açılmaz | ✅ |
| **Direct assignment** | tek satıra `share = C` | "Iran Inspection, MSKU1234" — **en sık gerçek vaka** | matematik değil UI riski: 2 tıktan uzaksa kullanıcı Equal seçip 39 SKU'yu kirletir | ✅ |
| **By Volume / CBM** | **driver yok** — ne `Import Container Item` ne `Commercial Invoice Item`'da CBM var | LCL, hava | önce Float kolon gerekir. Yapılırsa ham CBM değil **chargeable weight** (`max(kg, CBM×167)`) | v2 |
| **By customs value** | GTD istatistik değeri | Uzbek vergi/aksiz yeniden hesabı | By Value ile karıştırılmayacak, ayrı driver | v2 |

**v1 zorunlu: value, quantity, net weight, equal, manual, direct.** Gerisi v2.

## Muhasebe guardrail'leri — blok mu, uyarı mı

| Kural | Davranış |
|---|---|
| İade edilebilir KDV (`is_vat_component`, `lcv_math.py:49`) + include açık | **BLOK.** IAS 2 §11: alış maliyeti iade edilebilir vergileri içermez. İade edilemeyen ithalat KDV'si ayrı isimli bir component olacak, adında "vat" geçmeyecek |
| Hesap tipi ≠ *Expenses Included In Valuation* | **BLOK**, hesap adıyla (`imports.py:9414` mevcut kontrol) |
| GTD precedence devreye giriyor | **UYAR + açık onay.** Farkı göster: "GTD vergisi 412.300.000, 3 manuel satırın 398.000.000'ını değiştiriyor; +14.300.000 kapitalize edilecek." Kullanıcının baktığı ekranda sessiz supersede olmaz |
| `supersede_billed` çakışması | **BLOK**, çözüm zorunlu. Arka planda sessiz düşürmek doğru, kullanıcı arayüzünde yanlış |
| `lcv_ref` dolu (tüketilmiş) | **BLOK.** Submitted → read-only + voucher linki. Draft → cancel-and-rebuild, asla yerinde edit |
| Dönem kontrolü | **BLOK.** *Accounts Frozen Upto* öncesi posting; receipt tarihinden önceki posting |
| Cancelled voucher | `release_cost_lines_for_lcv` (`hooks.py:404-413`) `lcv_ref`'i temizlemeli. Temizlemezse masraflar **kalıcı olarak** askıda kalır — mevcut tasarımın en yüksek olasılıklı sessiz kayıp noktası, bench testi yazılacak |
| GRN sonrası geç gelen masraf | **UYAR, sayıyla.** "200 adetten 14'ü stokta; 8,4 mn UZS'nin %93'ü stoğa değil COGS'a gidiyor" (IAS 2 §34). CFO için ekrandaki en değerli satır bu |

## Denetlenebilirlik — neyin kalıcı yazılacağı

Bugün **hiçbir şey** yazılmıyor. Yazılacaklar:

- **Parent**: kaynak dokümanlar, posting tarihi, toplamlar, submitter, durum.
- **Charge satırı**: kaynak (PI / Import Expense / manuel), component, hesap, orijinal
  para birimi + tutar, **kur + kurun kaynağı + kur tarihi**, UZS tutar, include, basis, hedef.
- **Allocation sonuç tablosu** — asıl denetim cevabı. Her `(masraf, konteyner, kalem)`
  için değişmez bir satır: `driver_value`, `driver_total`, `computed_share_uzs`,
  `residual_adjustment`, birim ve kg başına etki, LCV adı + LCV item satırı.
  "Neden 2,14 $/kg?" → tek sorgu, kod yeniden koşmadan.
- **Driver'lar sayı olarak snapshot'lanır** (`box_weight_kg = 12.5`), referans olarak
  değil. Item master'ın gelecek ay değişmesi geçmişi oynatmayacak.
- `Commercial Invoice Item`'a `landed_cost_uzs` / `landed_rate_uzs` /
  `landed_cost_per_kg` — D2'nin read-only kartı kalıcı gerçeği göstersin diye.

---

## Veri modeli

**`Landed Cost Calculation`** — submittable, `format:LCC-{YYYY}-{#####}`

| alan | tip | not |
|---|---|---|
| `company` | Link Company | reqd |
| `posting_date` | Date | reqd, default Today |
| `source_type` | Select | `Imports\nPurchasing`, reqd |
| `commercial_invoice` / `import_container` / `grn_checklist` | Link | `depends_on: source_type=="Imports"` |
| `purchase_receipt` | Link | `depends_on: source_type=="Purchasing"` |
| `source_key` | Data | ro, hidden — `f"{source_type}:{primary}"`, **`docstatus=0` için unique index** |
| `currency` / `exchange_rate` | Link / Float | |
| `default_allocation_method` | Select | 7 değer, default `By Value` |
| `expense_account` | Link Account | reqd, `_assert_valuation_account` ile doğrulanır |
| `charges` / `targets` / `allocations` / `vouchers` | Table | dört child |
| `total_charges` / `total_allocated` / `rounding_difference` / `voucher_count` | Currency / Int | ro |
| `lcv_status` | Select | `Not Posted\nPosted\nPartially Cancelled\nCancelled`, ro |
| `amended_from` | Link | ro |

**`Landed Cost Charge`** (child): `charge_component` Select (13 değer — `Container
Cost Line.cost_component` ile **tek paylaşılan sabitten**), `description`, `supplier`,
`currency` reqd, `amount` reqd, `exchange_rate`, `base_amount` ro,
`allocation_method` Select (7 + `Use Default`), `include_in_landed_cost` default 1,
`expense_account` (satır override), `assign_to_container`, `source_doctype` Select
(`Container Cost Line\nImport Expense\nPurchase Invoice\nPO Charge\nManual`),
`source_name` ro, `purchase_invoice` ro, `import_expense` ro, `customs_declaration` ro,
`is_gtd_customs` ro, `emits_own_voucher` Check ro.

**`Landed Cost Target`** (child, PR kalemi başına): `purchase_receipt`,
`purchase_receipt_item`, `item_code`, `qty`/`stock_qty` ro, `uom`/`stock_uom`,
`rate`/`amount` ro, **`net_weight_kg` düzenlenebilir** (default `Item.weight_per_unit
× stock_qty` veya CI `boxes × box_weight_kg`), **`volume_cbm` düzenlenebilir**,
`import_container`, `applicable_charges` ro, `driver_source` ro.

**`Landed Cost Allocation`** (child, denetim + override grain'i): `charge_row`,
`charge_component` ro, `target_row`, `item_code` ro, `purchase_receipt` ro,
`driver_value` ro, `computed_amount` ro, `manual_amount` (dolu olması = override),
`final_amount` ro, `is_overridden` ro.

**`Landed Cost Voucher Ref`** (child, ADR-002'nin sonucu): `voucher` Link LCV,
`charge_row`, `basis` Select, `tax_row_count` Int, `total` Currency, `status` Select
(`Posted\nCancelled\nFailed`).

**Karıştırma yasağı** (`validate_source_exclusivity`): `Imports` → `commercial_invoice`
zorunlu, `purchase_receipt` yasak; `import_container`/`grn_checklist` aynı CI'ya
çözülmeli. `Purchasing` → `purchase_receipt` zorunlu, imports alanları yasak. Her
`targets` satırının PR'ı beyan edilen kaynağa ait olmalı.

## Allocation motoru ve API

Matematik `stabler/stabler/imports_module/allocation.py` — **frappe-free**, sadece
stdlib, `.github/frappe-free-tests.txt`'e eklenir (`lcv_math.py` ile aynı disiplin):

```python
def driver_values(targets, method, *, assign_to=None) -> list[float]
def allocate_one(amount, targets, method, *, assign_to=None, overrides=None,
                 precision=2, remainder="largest_remainder") -> dict
def allocate(charges, targets, *, default_method, overrides=None, precision=2) -> dict
def roll_up(allocations, targets) -> dict[str, float]
def validate_allocatable(charges, targets) -> list[str]
```

ERPNext'e bakan her varsayım tek dosyada izole edilir:
`stabler/stabler/imports_module/lcv_adapter.py` → `preflight_vouchers(plan) -> list[str]`,
her preview'da ve `submit_calculation` içinde ilk `insert()`'ten önce koşar. Kontrol
ettikleri: Manual voucher'larda `len(taxes) == 1`; `Σ applicable_charges −
total_taxes_and_charges == 0` (ERPNext toleransının içinde); negatif pay yok;
her include'lu masrafın en az bir sıfır-olmayan driver'lı hedefi var.

**`lcv_math.py`'den olduğu gibi yeniden kullanılacak** (yeniden yazılmayacak):
`is_vat_component`, `is_uzbekistan_customs_duty`, `apply_gtd_customs_precedence`,
`line_company_amount`, `unvaluable_line_names`, `unconsumed`, `supersede_billed`,
`aggregate_components`, `build_lcv_payload` (parametre zaten var — sadece `:412`
sabitini bırakmak yeterli).

**API** — `stabler/api/landed_cost.py`:

| endpoint | döner |
|---|---|
| `build_from_source(source_type, source_name, exchange_rate=None)` | yazmadan tam önizleme |
| `create_calculation(...)` | idempotent — aynı `source_key` için mevcut draft'ı döner |
| `preview_allocation(payload)` | stateless yeniden hesap |
| `save_calculation(name, payload)` | |
| `set_manual_amount(name, charge_row, target_row, amount)` | |
| `preflight_calculation(name)` | `{ok, plan:[{basis,charge_rows,tax_rows,total}], errors}` — SPA "N voucher oluşacak" yazar |
| `submit_calculation(name)` | `{lcc, vouchers:[...], count}` — voucher'ları **delege eder**, `lcv.submit_landed_cost_voucher` tek submit primitifi kalır |
| `cancel_calculation(name)` | `{cancelled:[], failed:[], lcv_status}` — resumable |

**Geriye uyum:** `lcv.py`'nin beş imzası **iki release boyunca dondurulur**. Yeni
yetenek yalnız eski default'lu opsiyonel kwarg olarak gelir
(`allocation_method="Qty"`), asla pozisyonel değişiklik olarak.
`GRNChecklistDetail.vue` dokunulmadan çalışmaya devam eder; `get_landed_cost_review`
yanıtına `"calculation": {"name","docstatus"}` eklenir.

`compute_next_lcv()` (`hooks.py:913`) draft LCV insert etmeyi bırakıp
`create_calculation` çağırır — ama **`Stabler Company Modules.enable_landed_cost_form`
bayrağının arkasında.** Deploy olmadan geri alınabilir.

---

## UI/UX — `LandedCostCalc.vue`

Zihinsel model **üç adım**: kaynağı seç → masrafları topla → dağıt ve post et.
Sticky bir adım rayı bunu her an ekranda tutar, ama wizard değil — scroll-spy.

**Bölgeler:** başlık (FormPage) · adım rayı · Adım 1 kaynak seçici (seçilince tek
satıra çöker, "+ İkinci kaynak ekle" ghost aksiyonu) · 4 KPI (ölü dosyadan
kurtarılan `unitCostAnalysis`: toplam net kg, temel maliyet/kg, landed maliyet/kg,
artış %) · Adım 2 masraf grid'i · GTD kartı · Adım 3 allocation önizleme · uyarı
şeridi · sticky footer (`Taslak kaydet` outline + **`Landed cost post et`** primary).

**Masraf grid'i kolonları:** ☑ · Kaynak (`PINV-00123 · satır 3` chip → SPA rotası,
**asla `/app/...`**) · Masraf tipi · Açıklama · Tedarikçi · Tarih · Tutar+kur
(MoneyInput) · Kur → UZS · Tutar (UZS, **kendi kolonu** — gri alt satır değil,
"tek para birimi" kuralı böyle korunuyor) · İade edilebilir KDV · **Dağıtım şekli** ·
**Uygulanacak hedef** (Tümü / Konteyner / Kalem grubu / Seçili kalemler) · Durum ·
kebab. Bill'den gelen satır 2px mavi sol kenarlık + kolonları **statik metin**
(disabled input değil — gri input tıklamaya davet eder, metin etmez).

**Allocation önizleme:** Kalem (sticky) · Konteyner · Miktar · Ağırlık · Hacim ·
Pay % · **Önceki birim maliyet** · Dağıtılan · **Sonraki birim maliyet** · Δ birim ·
**Δ %** · ▸ (masraf bazlı katkı alt satırları — her sayı kendisini üreten masrafa
kadar izlenebilir). Eksik ağırlık sessiz 0 değil, amber hücre.

**Manuel override:** o masraf için Dağıtılan hücresi MoneyInput olur, altta sticky
şerit: `4.850.000 / 5.000.000 girildi · 150.000 kaldı`. Dengesizken **Post kapalı,
Taslak kaydet açık**; iki yardımcı: *Kalanı değere göre dağıt* / *Gerisini sıfırla*.
Tek tek hücreler `is-invalid` işaretlenmez — her değer tek başına geçerli, yanlış
olan toplam.

**Canlı hesap — bugünkü hatayı tekrarlamadan.** Tüm aritmetik saf client fonksiyonu
(`composables/landedCost.js`), Vue `computed` ile sürülür. Sunucuya sayfa ömrü
boyunca **üç kez** dokunulur: tek toplu yükleme (bugünkü beş paralel refetch yerine),
kaydet, post. Debounce yok, keystroke round-trip yok. 2000 satır üstünde otomatik
hesap kapanır, `Recalculate` butonu çıkar.

**Post sonrası** sayfa read-only render edilir — input'lar *metinle değiştirilir*,
disable edilmez. Footer `Voucher'ı aç` + `Düzeltme oluştur`'a döner.

**Rotalar:** `/imports/landed-cost` (liste) · `/imports/landed-cost/new` ·
`/imports/landed-cost/:name` · `/purchasing/landed-cost` + `/:name`.
⚠️ `router.js:245`'teki mevcut `landed-cost/:grn` `/new`'i yutuyor —
`/imports/landed-cost-review/:grn` olarak yeniden adlandırılıp bir release redirect
bırakılacak. `GRNChecklistDetail.vue:317`'nin URL şekli **hiç değişmeyecek**.

**CI formundan silinen** (D2): "Landed cost (UZS)" tablosu, Import Expenses tablosu,
"Expenses without bills", "Shipment Cost Breakdown", tüm Capitalize butonları, üç
masraf giriş akışı ve `itemLandedCostPerKg` kolonu. **Yerine gelen tek kart:**
başlık + StatusBadge (Başlamadı / Taslak / Post edildi); dört monospace sayı (mal
değeri · landed masraf UZS + `16 masraf` alt sayacı · toplam landed · artış % chip);
üç kategori satırı (Navlun / Gümrük / Diğer); bir satır `Dağıtım: değer (12) ·
ağırlık (3) · manuel (1)`; alt link `Landed cost hesabını aç →`.
**Sıfır input, sıfır primary buton.**

**Kural uyumu:** her bölgede tam bir `.btn-primary`; global stripe'a dokunulmuyor;
her para alanı MoneyInput; tarihler DateInput/formatDate; para hücreleri
`font-monospace`; badge'ler `getStatusBadgeClass`; liste sayfası ListToolbar +
auto-apply + `⌘K` + SkeletonRows; `t()` anahtarları İngilizce.

**Ölü/çift dosya hükmü:** `pages/imports/LandedCostReview.vue` — `unitCostAnalysis`
ve Submit taşındıktan sonra **silinir**. `pages/purchasing/LandedCostReview.vue` —
üç paneli yeni formun C/E/G bölgelerine birebir oturuyor; rotası bir release redirect
kalır, sonra silinir. Net −786 satır. `LandedChargesEditor.vue` **olduğu gibi
bırakılır** (teklif anı what-if modal'ı, farklı işi var) — sadece sabitleri
paylaşılır, komponent değil.

**<768px:** adım rayı gerçek stepper olur, masraf grid'i kart'a döner, önizleme
tablo kalır (karşılaştırma zaten amaç) ama **manuel giriş kapalı** — 43 tutarı
telefonda yazmak gerçek bir iş akışı değil.

---

## Migrasyon ve rollout

Sonraki boş patch numarası **v87** (`patches.txt` `v86_remittance_pickup_code_hash`
ile bitiyor; v70 atlanmış).

| # | Patch | Amaç | İdempotans |
|---|---|---|---|
| v87 | `v87_lcv_pre_migration_snapshot` | Şirket/konteyner/component bazında kapitalize toplam + satır sayısı → JSON | Bugünün dosyası varsa atlar; salt okuma |
| v88 | `v88_lcv_form_company_flag` | `Stabler Company Modules.enable_landed_cost_form = 0` (v62 deseni) | `has_column` guard; iki kez = no-op. **Yarıda kalırsa bayrak 0 = eski form. Güvenli tarafa düşer** |
| v89 | `v89_lcv_allocation_fields` | LCV'ye `custom_allocation_method`, `custom_source_document_type/_document`, `custom_form_version` | `Custom Field` exists guard; additive |
| v90 | `v90_container_cost_line_charge_id` | `charge_id` backfill (stabil kimlik) | `WHERE charge_id IS NULL`, 500'lük chunk + commit; resumable |
| v91 | `v91_pr_landed_settings_schema2` | `includes` label→`charge_id`; `includes_legacy_labels` saklanır; `"schema": 2` | `schema==2` sentinel; okuyucu `schema`'ya göre dallanır |
| v92 | `v92_po_landed_charges_charge_id` | PO/SQ JSON masraflarına `charge_id` | Anahtar varsa atla; eski okuyucuya inert |
| v93 | `v93_lcv_backfill_qty_method` | Mevcut tüm LCV'lere `custom_allocation_method='Qty'` | Tarihsel **gerçeği** yazar, tahmin uydurmaz |
| v94 | `v94_lcv_post_migration_verify` | v87 toplamlarını yeniden hesapla, diff raporla | **`frappe.log_error`, asla raise etmez** — raise eden patch 7 kiracının `bench migrate`'ini kilitler |

**Cutover: kiracı bazlı feature flag.** Big-bang, paylaşılan bench yüzünden diskalifiye
— 3. kiracıdaki hatalı bir dağıtımın bedeli yedi kiracıyı birden etkileyen bir
`bench restart`. Bayrak deseni repoda zaten var (v62), company bazında ve **flip için
restart gerekmiyor**.

Kapılar: **G0** snapshot (tek restart, Zafar onayı) → **G1** v88–v94 bayrak kapalı,
davranış birebir aynı → **G2** en düşük hacimli kiracıda aç, 5 iş günü, muhasebeci
tam bir CI→GRN→LCV çevrimini imzalar → **G3** iki kiracı daha → **G4** kalan dört →
**G5** CI formu read-only özete düşer (D2) → **G6** bir ay-sonu kapanışı sonrası eski
yollar emekli.

**Mutabakat sorguları** (v87 öncesi / v94 sonrası birebir aynı çıkmalı):

```sql
-- A1 kapitalize tutar parmak izi
SELECT parent AS container, cost_component, ROUND(SUM(amount_uzs),2), COUNT(*)
FROM `tabContainer Cost Line` WHERE include_in_landed_cost = 1 GROUP BY 1,2;
-- A2 tüketim
SELECT COUNT(*), SUM(lcv_ref IS NOT NULL AND lcv_ref<>''), SUM(include_in_landed_cost=0)
FROM `tabContainer Cost Line`;
-- A3 voucher docstatus dağılımı — KIPIRDAMAYACAK
SELECT docstatus, COUNT(*) FROM `tabLanded Cost Voucher` GROUP BY docstatus;
-- A5 GL değişmezliği — migrasyon hiçbir şey post etmez
SELECT account, ROUND(SUM(debit-credit),2) FROM `tabGL Entry` WHERE is_cancelled=0 GROUP BY account;
```

Artı label→id round-trip assertion'ı (asıl önemli olan): her PR için
`before_labels == {label_of(cid) for cid in after.includes}`, simetrik fark boş.

**Geri dönüş:** v87 dosya sil · v88 bayrağı 0'la (**restart yok**) · v89 custom
field'ları sil · v91 `includes_legacy_labels`'dan geri yaz (**bu yüzden legacy harita
iki release yaşamalı**) · v92/v93 anahtar/kolon temizle · frontend fazları bayrakla.

⛔ **Geri döndürülemez çizgi:** kullanıcı bir LCV submit ettiği an GL kaydı vardır.
ERPNext cancel silmez, ters kayıt atar. Yani submit sonrası "rollback" = cancel +
ters kayıt + yeniden post; bu bir kod geri alma değil, dönem kapanışıyla etkileşen bir
**muhasebe olayıdır**. Submitted LCV üretebilen her faz kiracı bazlı bayrakla ve
muhasebecinin onayıyla açılır.

**Dış entegrasyon:** `integrations/one_c/*` ve `didox_submission.py` grep'i Purchase
Receipt / LCV / Container Cost Line'a **hiçbir referans** göstermiyor. Yine de bu
modüller bir gün referans vermeye başlarsa fail eden bir guard testi eklenecek.

## Test planı

**`make test` (frappe-free):** `test_allocation.py` — yedi method'un tümünde
toplam korunumu, `100.00` ve `0.01`'in üçe bölünmesi, largest-remainder
determinizmi ve `idx` eşitlik kuralı, sıfır-driver → `fallback="equal"`, override
pin + kalanın yeniden dağılımı, aşırı pin hata verir, `Direct Assignment` boş
hedefte sıfırlamaz hata verir, charge bazında method bağımsızlığı.
`test_lcv_adapter.py` — gruplama→plan eşlemesi ve `remainder="last_row"`
paritesinin ERPNext formülüyle birebir tutması. `test_pr_includes_schema_migration`
— label→id saf dönüşümü (yinelenen label, boş label, Kiril label, round-trip).
`test_allocation_method_frozen`, `test_lcv_endpoint_signature_guard` (AST),
`test_no_external_sync_coupling`.

**`make test-bench` (DB):** kaynak-dışlayıcılık throw'u; `docstatus=0` unique guard;
16 masraflık fixture'ın **öngörülen voucher sayısını** üretmesi ve her Manual
voucher'ın tam 1 tax satırı + ayrı `description` taşıması; `lcv_ref` damgalama ve
cancel'da bırakma; amend zinciri; ikinci LCC'nin yalnız tüketilmemiş masrafları
görmesi; valuation dışı hesabın reddi; **her patch'in iki kez koşturulup ikincisinin
no-op olması**; kiracı izolasyonu.

⚠️ Bu iş DB'ye bağımlı. `make check` tek başına ispat değildir — bead'lerde
`make test-bench` açıkça talep edilecek.

---

## Fazlama

| Faz | İçerik | Boy | Bağımlılık |
|---|---|---|---|
| **F0** | **P0:** submit'i routed component'e bağla, ölü dosyayı sil, toast metinlerini 5 dilde düzelt. `itemLandedCostPerKg` çelişkisini kapat | S | — |
| **F1** | `distribute_charges_based_on` select + GRN Checklist/PR'da kalıcı + `build_lcv_payload`'a geçir + submit'te dondur | S | F0 |
| **F2** | v87–v88 snapshot + bayrak (kapalı). Kullanıcıya görünmez | S | — |
| **F3** | v89–v94 kimlik/şema migrasyonu + doğrulama + `make test` ekleri. Hâlâ görünmez | M | F2 |
| **F4** | Yeni form **read-only**, bayrak arkasında: birleşik CI/Container/GRN + PR görünümü, KPI kartı | M | F3 |
| **F5** | Yazma yolu: masraf girişi, include/exclude, **satır bazlı allocation method**, preflight, çoklu voucher emisyonu, submit | L | F4 |
| **F6** | CI formu → read-only özet kart + link (D2); üç masraf giriş akışının kaldırılması | M | F5, G4 |
| **F7** | Dedup: 3 cost-line tablosu → 1, 2 bill tablosu → 1, 2 API wrapper → 1, `CATEGORY_LABELS`/`money`/`masked` ortak modüle | S | F6 |
| **F8** | i18n backfill — 5 dil (en/ru/uz/uzc/tr), string'ler durulduktan sonra | S | F7 |

Her faz `main`'e bağımsız merge edilir ve **commit başına `make check` yeşil** kalır.

---

## Kaydedilen muhalefet

Şeytanın avukatı **SHIP REDUCED** oyu verdi ve bu tutanağa geçiyor:

> Sorun ifadesi bir ekranı tarif ediyor, bir kusuru değil. GL'e dokunan üç kusur
> (submit yok, Qty sabit, method saklanmıyor) toplam ~50 satır kod ve bir custom
> field ile kapanıyor — yeni doctype maliyetinin belki %3'ü. Rota
> `/imports/landed-cost/:grn` zaten var, `build_lcv_payload` parametreyi zaten
> alıyor. Yeni form gelmeden bunlar kapanmazsa, form da submit edilemeyen taslak
> üreten dördüncü ekran olur.

Kurul bu itirazı **kabul etti ve sıralamaya çevirdi** — F0/F1 tam olarak bu. Formun
iptali için değil, formdan **önce** koşması için.

Aynı üye üç mismatch'i de kayda geçirdi ve bunlar tasarımda karşılandı: QuickBooks
tek aşamada ve fatura anında dağıtır (bizde konteyner katmanı + GRN sonrası geç
masraf var → ADR-004 + `create_additional_lcv`); QuickBooks kur var sayar (bizde
kur yokluğu birinci sınıf durum → ADR-005 sert blok); QuickBooks'ta GTD precedence
ve IAS 2 §11 KDV dışlaması yok (guardrail tablosu).

Ve kendi oyuna karşı en güçlü argümanı da verdi — kurul buna katılıyor:

> Eğer MSA'nın gerçek şikâyeti ağırlık bazlı dağıtımın **zorunlu** olmasıysa —
> ağır düşük değerli kargonun hafif yüksek değerliyi sübvanse etmesi Özbekistan'da
> gerçek bir değerleme sorunu — o zaman Qty/Amount cevabın küçük hali değil, yanlış
> cevabın hızlı hali olur.

Zafar'ın talebi ("allocation method'lara göre olması lazım") tam olarak bunu işaret
ettiği için F1 bir varış noktası değil, F5'e giden yolda ölçülebilir bir ara adımdır.

---

## Zafar'ın kararı gereken açık maddeler

1. **Tarihsel `Qty` dağıtımı maddi mi?** Bugüne kadar submit edilmiş her LCV karışık
   UOM'da Qty ile dağıtıldı. Kaç voucher, ne tutar, ağırlık bazlı yeniden hesap neyi
   değiştirirdi? Maddi ise bu bir IAS 8 önceki dönem hatası, backlog maddesi değil.
   **Ters risk daha büyük olabilir:** voucher'lar DRAFT açılıp otomatik submit
   edilmiyor — kaç tanesi hiç submit edilmemiş halde duruyor? O sayı büyükse envanter
   **şu anda** eksik değerlenmiş demektir ve öncelik form değil o sayıdır.
2. **Dağıtım şeklini kim değiştirebilir?** Kurulun önerisi: submit'te dondurulur;
   değişiklik yalnız cancel + zorunlu gerekçe ile; şirket seviyesinde default
   `Stabler Settings`'te; `_assert_cost_visible` arkasında.
3. **Landed cost hangi aya düşecek?** Navlun Eylül'de faturalanıp GRN Ağustos'ta,
   voucher Kasım'da submit edilebiliyor. Öneri: posting date default
   `max(receipt date, charge doc date)`, dönem kilidi öncesi post blok, ve
   **dağıtılmamış masraf yaşlandırma listesi** (`include_in_landed_cost=1` +
   `lcv_ref` boş, belge tarihine göre yaşlandırılmış). Bu liste ay-sonu kapanış
   kontrolüdür ve bugün yok.
4. **Pilot kiracı hangisi olsun?** G2 kapısı için en düşük hacimli kiracı.

---

Referanslar: `stabler/api/lcv.py`, `stabler/stabler/imports_module/lcv_math.py`,
`stabler/stabler/imports_module/hooks.py`, `stabler/api/imports.py`,
`stabler/api/_imports_rules.py`, `stabler/public/js/pages/imports/CommercialInvoiceForm.vue`,
`stabler/public/js/pages/{imports,purchasing}/LandedCostReview.vue`,
`stabler/public/js/router.js`, `stabler/patches.txt`,
ERPNext v15 `erpnext/stock/doctype/landed_cost_voucher/landed_cost_voucher.py`.

---
---

# EK — 2026-08-16, ikinci tur

Zafar: *"NetSuite landed cost'u nasıl çözüyor? Kurul bunu da tartışsın. Benim amacım
sadece QuickBooks tarzı olsun değil, en uygun LC calculation yapalım."*

Doğru itiraz: "QuickBooks tarzı" bir **uygulama** tercihiydi, **model** tercihi değil.
Kurul beş ERP'yi birincil kaynaklardan inceledi. Sonuç: bir ADR güçlendi, biri düzeltildi,
biri yeni eklendi, ve teşhislerimizden biri **yanlıştı**.

## E1 · Beş ERP'nin landed cost modeli

| | Belge modeli | **Masraf satırı bazında baz?** | Çok aşamalı? | Manuel override | Hacim/CBM | Geç gelen maliyet |
|---|---|---|---|---|---|---|
| **SAP B1** | Kendi belgesi; GRPO'ya **ve başka bir LC belgesine** zincirlenir | **Evet — 6 method** | Değer kaskadı (gümrük öncesi/sonrası); konteyner yok | Projected Customs düzenlenebilir; "Amount to Balance" sıfırlanmadan post edilemez | **Var** | İkinci LC belgesi zincirle; satılmış stok davranışı belgelenmemiş |
| **Odoo** | Kendi kaydı, bağımsız valide edilir | **Evet — `split_method` maliyet satırında** (equal / by_quantity / by_current_cost_price / by_weight / by_volume) | Yok | Evet | **Var** | Kalan miktara oranla; satılan pay gidere, **geçmiş yeniden ifade edilmez** |
| **Dynamics 365 BC** | Belge değil — satır tipi `Charge (Item)` + atama alt kaydı | Evet — 4 method (Equally / By Amount / By Weight / By Volume), **geliştiriciyle genişletilebilir** | Yok, ama her adımda charge post edilebilir | `Qty. to Assign` (miktar güdümlü) | **Var** | **Tam geriye dönük COGS yeniden ifadesi** |
| **Acumatica** | Kendi release edilebilir belgesi → Inventory Adjustment + AP faturası | **Evet — 4 method + `None`** | Yok; makbuz tiplerini karıştıramaz | **Evet — satır başına `Inventory ID`** | **Var** | **Tahmin → Landed Cost Variance**; satılan pay orantılı, yeniden ifade yok |
| **ERPNext** *(bizim platform)* | Kendi submittable doctype'ı | **Hayır — belge başına tek** | Yok | Evet, zorunlu denkleştirmeyle | **Yok** | **SLE + GL'in tam yeniden post'u** |
| **NetSuite** | Item Receipt / Vendor Bill üzerinde subtab veya satır alt kaydı | İşlem seviyesinde **hayır** ("bir işlem aynı anda tek method"); **Estimated Landed Cost şablonlarında evet** | Yok | Evet (Landed Cost per Line) | **Yok** — iki blog "var" diyor, **Oracle'ın kendi listelerine göre yanlış** | **Geriye dönük COGS**: *"eğer bu kalemlerin bazıları satıldıysa, fulfillment'lardaki maliyet etkisi yeni değeri içerecek şekilde güncellenir"* |

## E2 · NetSuite — detayda ne yapıyor

- **Allocation method'ları, birebir:** `Weight`, `Quantity`, `Value`. Formüller Oracle'ın
  kendi ifadesiyle: Weight = (kalem ağırlığı / uygun kalemlerin toplam ağırlığı) × toplam
  landed cost; Quantity = (toplam landed cost / uygun kalem sayısı) × satır miktarı;
  Value = (kalem değeri / toplam değer) × toplam landed cost.
- **`Source` alanı:** `This Transaction` (yalnız Advanced Receiving kullanılmıyorsa),
  `Other Transaction`, `Other Transaction (exclude tax)` — ve dokümantasyonun kanonik alan
  listesinde **olmayan ama iki çalışan örnekte yük taşıyan** bir dördüncü: `Manual`.
- **Cost Category** kaydı, `Cost Type = Landed`. Gider hesabı Oracle'ın ifadesiyle
  *"bir ara/holding hesabı olarak tasarlanmıştır ... genellikle bir COGS hesabı değildir"*.
- **Estimated Landed Cost** (paid SuiteApp, Supply Chain Management): `Landed Cost Template`
  kaydı, **Item** üzerine bağlanır, ve **her cost category kendi allocation method'unu
  alır** — artı iki ekstra method: `Flat Amount` ve `% Value`. Bu, NetSuite'te masraf
  bazında baza izin veren **tek** belgelenmiş yol.
- **Bir tedarikçi faturası yalnız BİR item receipt'e kaynaklık edebilir.** Zaten tahsis
  edilmiş faturalar seçim listesinden **filtrelenir** — bir tüketim işareti. Çoklu makbuz
  için Oracle'ın önerdiği yol `Source = Manual`.
- **Geç gelen maliyet: geriye dönük.** Blok yok, varyans hesabı yok — COGS yeniden ifade
  edilir.
- **Denetim izi:** GL Impact'in `Memo` alanı landed cost ve item kodunu taşır; Inventory
  Valuation raporunda kategori adı ve sıfır miktarla görünür. Ama **allocation paydası
  (kullanılan toplam ağırlık/değer) saklanmaz** — kayıttan yeniden hesap üretilemez.
- **Uyarı, bizim için:** Oracle birebir — *"Purchase orders received through inbound
  shipments are not supported"* (ELC tarafından). NetSuite'in konsinye katmanı ile maliyet
  motoru birbirini tanımıyor.

([Entering Landed Cost on a Transaction](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N2418831.html) ·
[Landed Cost Allocation per Line](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_3728979515.html) ·
[Landed Cost Categories](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N2417902.html) ·
[Estimated Landed Cost](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_4576786578.html) ·
[Creating Landed Cost Templates](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_4576805263.html) ·
[ELC Considerations](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/bridgehead_4576788130.html) ·
[Billed Separately With a Cost Estimate](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/article_162021562398.html))

## E3 · DÜZELTME — "Qty sabit kodlu" teşhisi eksikti

Ana dokümanda P1 olarak yazdığımız *"karışık UOM'lu satırlarda 12 adet + 3 ton + 400 m
toplanıp 415 birim üzerinden bölündü"* iddiası **ithalat tarafı için yanlış.**

```
stabler/stabler/imports_module/receipt_math.py:28    STOCK_UOM = "Kg"
                                            :103-105 "uom": STOCK_UOM,
                                                     "stock_uom": STOCK_UOM,
                                                     "conversion_factor": 1,
```

Purchase Receipt satırının `qty`'si **kilogram**. ERPNext'in `Qty` dağıtımı `item.qty`
kullanıyor. Yani ithalatta **bugünkü sabit `Qty`, aslında ağırlık bazlı dağıtımdır** —
ve navlun, THC, depolama, demuraj için **doğru bazdır**.

Karışık-UOM eleştirisi ithalatta değil, **purchasing/tender tarafında** geçerli
(`lcv.py`'nin `"Purchase Receipt"` dalı) — orada UOM'lar gerçekten karışık.

**Ama asıl sorun bu düzeltmeyle küçülmüyor, şekil değiştiriyor ve keskinleşiyor.**
Et ithalatında:

| Masraf | Doğru baz | `Qty`(=kg) ile ne olur |
|---|---|---|
| Navlun, THC, depolama, demuraj | **ağırlık** | ✅ doğru |
| Gümrük vergisi (ad valorem), aksiz, sigorta, banka/akreditif | **değer** | ❌ ucuz-ağır kalemlere aşırı yükleme |
| Sertifika, gümrükleme, tek GTD ücreti | **eşit / doğrudan** | ❌ |

Karışık bir sığır konteynerinde kemikli et ile bonfile **aynı kiloda 4 kata kadar** değer
farkı taşır. Ad valorem masrafları kilo ile dağıtmanın birim maliyet hatası kolaylıkla
**%10–20** — MSA'nın brüt marjından büyük.

**Sonuç: tek bir dropdown (`Qty` | `Amount`) yeterli bir düzeltme DEĞİL.** Navlun ağırlık,
gümrük vergisi değer isterken belge seviyesinde tek baz ikisini birden ifade edemez.
Dropdown 30 günlük listede kalıyor çünkü bugünden iyi ve S boyutunda — ama **ADR-003
(masraf satırı bazında baz) bir konfor değil, doğruluk gereğidir.**

## E4 · ADR'lerin durumu

| ADR | Durum |
|---|---|
| **ADR-001** — yeni submittable `Landed Cost Calculation` doctype | **Geçerli ama yeniden sıralandı.** Beş ERP'nin dördü landed cost'u kendi belgesi yapıyor; model doğru. Sıralama için bkz. satın alma zinciri kararı ADR-109 |
| **ADR-002** — ERPNext `Distribute Manually` tek tax satırı; hibrit voucher emisyonu | **Geçerli, doğrulandı.** ERPNext bu kısıtta beş ERP arasında yalnız kalıyor |
| **ADR-003** — baz **masraf satırı** seviyesinde | **GÜÇLENDİ — beşte dördü zaten böyle yapıyor.** Odoo `split_method`'u maliyet satırında tutuyor; SAP B1 satır başına 6 method; BC satır başına 4; Acumatica satır başına 4 + `None`. **ERPNext tek istisna.** Ve E3'teki et hesabı bunu konfordan gereğe çeviriyor |
| **ADR-004** — iki aşamalı (masraf → konteyner → kalem) | **Emsalsiz — beşinin hiçbirinde konteyner katmanı yok.** Bu bizim tasarımımız; çalınacak prior art yok. Dürüstçe kaydedilir: risk bizde |
| **ADR-005** — yuvarlama ve mutabakat | **Geçerli.** ERPNext'in `2/(10**precision)` toleransı ve `items[-1]` kalanı hâlâ bağlayıcı |

## E5 · YENİ — ADR-006 · SAP B1'in gümrük kaskadı çalınacak

SAP Business One'ın *Cash Value **Before** Customs* / *Cash Value **After** Customs* çifti
ve **Actual Customs'ın Projected Customs'ı geçersiz kılıp farkı satırlara orantılı
dağıtması**, bizim GTD gereksinimimizin birinci sınıf alan olarak çözülmüş hali. Bugün
`apply_gtd_customs_precedence()` ile elde yazdığımız mantık, SAP'ta ürünün kendisi.

Alınacak: **iki aşamalı değer kaskadı.** Gümrük vergisi beyan değeri üzerinden hesaplanır;
sonraki masraflar (iç nakliye, depolama) **gümrük sonrası değer** üzerinden dağıtılabilir.
SAP'ın *Customs Affects Inventory* bayrağı da tam olarak bizim iade edilebilir/edilemez
KDV anahtarımız.

**SAP'ın tuzağı, alınmayacak:** belge seviyesinde **tek kur**. Navlun USD, demuraj IRR,
gümrük UZS iken ölümcül. ERPNext'in `Landed Cost Taxes and Charges` tablosundaki
**satır başına `account_currency` + `exchange_rate` + `base_amount`** beşinin en iyisi —
korunacak.

## E6 · YENİ — ADR-007 · ERPNext'in repost motoru korunacak, varyans modeli alınmayacak

Geç gelen maliyette iki okul var:

- **Acumatica / Odoo:** satılmış payı bir **varyans hesabına** yaz, geçmişi yeniden ifade
  etme.
- **ERPNext / BC / NetSuite:** **geriye dönük yeniden ifade et.** ERPNext'in
  `update_landed_cost()` fonksiyonu SLE ve GL'i ters çevirip yeniden post ediyor ve
  `repost_future_sle_and_gle(via_landed_cost_voucher=True)` çağırıyor.

**ERPNext modeli korunuyor, ama sınırlandırılıyor.** MSA'nın devir hızı yüksek ve
konteynerler belgeler gelmeden sık sık satılıyor; Acumatica tarzı varyans, konteyner
başına brüt marjı — sahibin fiilen yönettiği sayıyı — kalıcı olarak yanlış gösterirdi.

Sınır: **`Accounts Frozen Upto` kapanışta kurulur.** Açık dönem içinde repost çalışır ve
COGS yeniden ifade edilir. Dönem donduktan sonra fark, cari ayda **dönem gideri** olarak
`Landed Cost Variance`'a yazılır. **Bir navlun faturası için kapanmış dönem asla
açılmaz.**

## E7 · Hiçbir ERP'nin vermediği bazlar

Beşinin hiçbirinde **yok**, yani yapılacaksa bizim yapacağımız:

- **hacimsel/chargeable weight** (`max(kg, CBM×167)`) — hava ve LCL için
- **konteyner numarasına göre dağıtım**
- **HS kodu grubuna göre dağıtım** (SAP B1'in *Customs Group*'u en yakın akraba ama o
  kalem başına vergi **oranını** sürüyor, bir bölüştürme bazını değil)

Ve dikkat: **hacim/CBM için sürücü kolonu bizde de yok** — ne `Import Container Item`'da
ne `Commercial Invoice Item`'da CBM alanı var. v2.

## E8 · Sonuç

Modele bakınca MSA'nın hedefi **QuickBooks değil**: iskelet olarak **Acumatica**
(bağımsız release edilebilir belge, birden çok makbuzdan satır çeker, her masraf satırı
kendi method'unu taşır, satır bir kaleme sabitlenebilir, ve tasarımı *"bazı landed cost'lar
mal geldiğinde bilinir, bazıları sonra öğrenilir"* varsayımı üzerine kurulu), **motor
olarak ERPNext'in repost'u**, **gümrük katmanı olarak SAP B1'in kaskadı**, ve **baz
yerleşimi olarak Odoo'nun maliyet-satırı `split_method`'u**.

QuickBooks bu karşılaştırmada referans değil — konsinye katmanı, karantina, GR/IR
yaşlandırması ve gümrük nesnesi hiçbiri yok. "QuickBooks tarzı" ifadesinden alınacak tek
şey doğruydu: **tek ekranda topla, önce/sonra birim maliyeti göster.** O da mockup'ta
zaten var.
