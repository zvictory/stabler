# Satış Siparişi (Classic) — referans spesifikasyonu

> **Kaynak:** `stabler/public/js/pages/sales/SalesOrderFormClassic.vue` — 1379 satır
> (`<script setup>` 1–833, `<template>` 835–1379).
> **Damga:** commit `2e013ef`, 2026-08-01. Kaynak değişirse bu belge sessizce eskir;
> satır numaralarını kullanmadan önce dosyaya bakın.
>
> Bu belge **tarafsız envanterdir**: ne var, ne yapıyor, nereden geliyor. Yorum, öneri
> ve eleştiri burada değil — onlar `PROMPT_design_satis_siparisi.md`'de.

---

## 1 · Kimlik ve yol

| | |
|---|---|
| Rota | `/sales/orders/:name` ve `/sales/orders/new` |
| Rota bileşeni | `SalesOrderForm.vue` (~27 satırlık ince anahtar) |
| Anahtar | `enable_modern_sales_order` (`Stabler Company Modules`, varsayılan `0`) |
| `0` → | `SalesOrderFormClassic.vue` ← **bu belge** |
| `1` → | `SalesOrderFormModern.vue` (kapsam dışı) |
| Modül kapısı | `sales` — `meta: { module: "sales" }` |
| Sahibi kiracılar | anjan (ana üretim), dts, horeca — hepsinde açık |

İnce anahtar deseni, `router.js`'in "her `component:` statik olmalı" değişmezini
bozmadan iki varyantı yan yana tutmak için var.

---

## 2 · Sayfa iskeleti

`FormPage.vue` sarmalayıcısı (`:836-845`), tüm belge formlarının ortak kabuğu:

```
FormPage
  :title        = isCreate ? "New Sales Order" : "Sales Order"
  :doc-name     = route param
  :status       :docstatus   → başlıktaki durum rozeti
  :loading      → iskelet
  :error        → yükleme hatası bloğu
  :action-error → aksiyon hatası bloğu
  back-path     = "/sales/orders"
  #actions      → yapışkan alt çubuk (:1280-1377)
```

Sayfa gövdesi tek sütun, kart yok — alanlar doğrudan `FormPage` içeriğine akıyor.
Yalnız **Fulfilment & Billing** bölümü (`:1178`) bir `.card` içinde.

Dikey sıra:

1. Aksiyon hatası uyarısı (`:846`)
2. Durum şeridi + pipeline stepper (`:849-865`) — yalnız view
3. Uyarı katmanı (`:867`, `:880`, `:893`)
4. Başlık alanları (`:899-1002`)
5. Kur satırı (`:1005-1026`) — yalnız yabancı para
6. Özet datagrid (`:1029-1050`) — yalnız view
7. "Items" başlığı + iskonto anahtarı (`:1053-1059`)
8. `LineItemsEditor` (`:1061-1146`)
9. Çalışan toplam bloğu (`:1149-1167`) — yalnız düzenlenebilirken
10. Şartlar / notlar (`:1169-1173`)
11. `RelatedDocuments` (`:1175`) — yalnız view
12. Fulfilment & Billing kartı (`:1178-1277`) — yalnız `docstatus === 1`
13. Aksiyon çubuğu (`:1280-1377`)

---

## 3 · Durum şeridi (`:849-865`)

Yalnız `!isCreate && form`.

**Üst satır** — yatay, `gap-2`:
- Müşteri adı, `text-secondary`
- `has_reservations` → `badge bg-green-lt` + `ti-lock` + "Reserved"
- `paymentBadge` (`:771`) → gönderilmiş faturaların `outstanding_amount` toplamından
  hesaplanır:

| Koşul | Rozet | Sınıf | İkon |
|---|---|---|---|
| gönderilmiş fatura yok | *çizilmez* | — | — |
| `due ≤ 0,005` | Paid | `bg-green-lt` | `ti-check` |
| `due ≥ grand − 0,005` | Unpaid | `bg-red-lt` | `ti-clock` |
| arası | Partly paid | `bg-yellow-lt` | `ti-progress` |

**Alt satır** — `ul.steps.steps-counter`, dört adım:
`Quotation → Sales Order → Deliver → Invoice`.
Aktif adım `pipelineStage(form)` (`:755`) ile seçilir:

| Dönen | Koşul |
|---|---|
| `4` | gönderilmiş fatura var **veya** `per_billed ≥ 100` |
| `3` | `per_delivered > 0` **veya** `per_billed > 0` |
| `2` | diğer (varsayılan) |

`1` (Quotation) hiçbir zaman dönmez — adım çizilir ama bu ekranda asla aktif olmaz.

---

## 4 · Uyarı katmanı

| Blok | Satır | Koşul | Görünüm |
|---|---|---|---|
| Rezervasyon hataları | `:867-878` | `lastReservationErrors.length` | `alert alert-warning`, `ti-alert-triangle`, satır listesi: `item` (monospace) · `line N` · hata metni |
| Bağlı faturalar | `:880-890` | `form.sales_invoices.length` | `alert alert-info`, `ti-link`, her fatura `badge bg-blue-lt` router-link |
| İhale kaynağı | `:893-896` | `isCreate && form.crm_deal` | `alert bg-purple-lt text-purple`, `ti-flag`, "From tender deal: **{deal}**" |

`lastReservationErrors` yalnız `submitCreate` / `submitDoc` yanıtı
`reservation_errors` taşıdığında dolar (`:714`, `:722`).

---

## 5 · Başlık alanları (`:899-1002`)

Bootstrap `row g-3`. Her alan iki halde: `editable` → bileşen, değilse
`form-control-plaintext`.

| Alan | Genişlik | Düzenlenebilir bileşen | Salt-okunur görünüm | Zorunlu |
|---|---|---|---|---|
| **Customer** | `col-md-6` | `Typeahead` (`searchCustomers`, `open-on-focus`, `@pick=pickCustomer`, `@clear=clearCustomer`) | ad **kalın** + `· CUST…` monospace | evet |
| **Warehouse** | `col-md-6` | `Select` (`warehouses`, `value-key="name"`) | monospace | evet |
| **Agreement** | `col-md-6` | `Typeahead` (`searchAgreements`) | monospace | hayır |
| **Order date** | `col-md-3` | `DateInput` | `formatDateTime(...)` | hayır |
| **Price list** | `col-md-3` | `Select` (`priceLists`) | düz metin | hayır |
| **Currency** | `col-md-3` | `Select` (`currencies`) | monospace kalın + sembol | hayır |

**Agreement** alanı yalnız `agreementsEnabled` (`:44`,
`session.canAccessModule("agreements")`) iken çizilir.

**Customer typeahead option slot'u** (`:913-922`): `avatar avatar-xs bg-purple-lt`
içinde adın baş harfi + iki satır (ad kalın; altında `CUST… · customer_group`,
grup boşsa `—`).

**Price list ve Currency option'ları** para birimini / sembolü parantez içinde
gösterir: `Price (UZS)`, `USD ($)`.

> Not: `Order date` salt-okunurken `formatDateTime` kullanıyor (saat de basar),
> düzenlenirken `DateInput` (yalnız tarih).

---

## 6 · Kur satırı (`:1005-1026`)

Yalnız `isForeignCurrency` (`:268`) — işlem parası ≠ şirket taban parası.
anjan'da taban USD, işlemler UZS ⇒ neredeyse her siparişte görünür.

**Yön kuralı** — projede pazarlık dışı: ekranda **daima güçlü para solda**.

- Saklama yönü ERPNext'inki: `conversion_rate` = "1 belge parası = N taban parası"
  ⇒ UZS/USD çiftinde `0,000082632`. **Bu değişmez.**
- Sunum ve giriş yönü `composables/fx.js` ile çevrilir: `1 USD = 12 101,84 UZS`.
- `rateQuote` (`:282`) → `readableRate(exchangeRate, form.currency, base)`
- `displayExchangeRate` (`:294`) iki yönlü: `get` → `rateQuote.value`,
  `set` → `toLineRate(...)` ile ERPNext yönüne geri çevirir.

| Parça | Görünüm |
|---|---|
| Etiket | `Exchange rate` + küçük gri `(1 USD = ? UZS)` |
| Düzenlenebilir | `MoneyInput`, `:currency="rateDisplayCurrency"` |
| Salt-okunur | `1 USD = 12 101,84 UZS` — monospace |
| Yanında | `Total in USD: 245,74` — yalnız `grandTotalBase !== null` |

**Bilinmeyen kur asla `1` değildir.** `exchangeRate` `ref(null)` başlar (`:41`),
CBU çağrısı düşerse `null` kalır (`:344`) ve payload'a hiç girmez (`:189-223`).
Gerekçe koddaki Türkçe yorumda: `1` başlangıcı 945 000 UZS'lik bir siparişi USD
defterine 945 000 USD olarak yazdırıyordu.

**Yüklenirken kur izleyicileri susar.** `loadingDoc` (`:357`) bayrağı, `load()`
`form.currency`'yi doldurduğu anda tetiklenen izleyicinin (`:627`, `:636`) bugünkü
canlı kuru çekip belgenin defterlendiği kuru ezmesini engeller.

---

## 7 · Özet datagrid (`:1029-1050`)

Yalnız view. Tabler `.datagrid`, beş `.datagrid-item`:

| Başlık | İçerik | Biçim |
|---|---|---|
| Net total | `form.net_total` | monospace |
| Grand total | `form.grand_total` | monospace **kalın** |
| Advance paid | `form.advance_paid` | monospace |
| Delivered | `per_delivered` | monospace, `%` , 0 basamak |
| Billed | `per_billed` | monospace, `%` , 0 basamak |

---

## 8 · Satır tablosu

Başlık çubuğu (`:1053-1059`): `Items` (küçük, büyük harf, gri) + sağda
`form-check form-switch` → **Show discounts** (`showDiscounts`, `:35`).
Belge yüklenirken herhangi bir satırda iskonto varsa otomatik açılır (`:382`).

Tablo `LineItemsEditor.vue`'dan gelir — çekirdek sütunlar:

| # | Sütun | Genişlik | Hizalama |
|---|---|---|---|
| 1 | *(satır aksiyonları / sıralama)* | 80px | — |
| 2 | Item | 160–320px | sol |
| 3 | Qty | 120px | sağ |
| 4 | UOM | 150px | sol |
| 5 | Rate | 160px | sağ |
| — | ← `#header-extra` slot'u buraya girer | | |
| son | Amount | 150px | sağ |

Tablo `table-no-stripe` — global çizgili kuralının bilinçli istisnası.

### Beş slot

| Slot | Satır | İçerik |
|---|---|---|
| `#header-extra` | `:1073-1079` | view'da: **Reserved**, **Delivered**, **List rate** (120px, sağ). `showDiscounts` açıkken: **%** (80px), **Disc** (130px) |
| `#item-extra` | `:1081-1092` | ürün adının altında stok satırı: yükleniyorsa küçük spinner; yoksa `{free} avail · {actual} stock / {reserved} reserved`. Aşımda `text-danger fw-semibold`, normalde `text-secondary` |
| `#uom-extra` | `:1094-1100` | `conversion_factor > 1` ve `uom ≠ stock_uom` ise `1 Korobka = 20 Dona`, 0,72rem gri |
| `#row-extra` | `:1102-1136` | view'da: Reserved (`badge bg-green-lt`, yoksa `—`), Delivered, List rate (küçük gri). `showDiscounts` açıkken: iskonto % `<input type=number>`, iskonto tutarı `MoneyInput` |
| `#footer-extra` | `:1138-1145` | `badge bg-secondary-lt` satır sayısı + her birim için `badge bg-blue-lt` toplam adet |

### Stok müsaitliği

- `scheduleAvailability(line)` (`:562`) — 200 ms debounce, zamanlayıcılar `WeakMap`'te.
- `loadAvailability` → `stabler.api.inventory.item_availability`, `{ free, actual, reserved }`.
- `lineStockQty` (`:588`) = `qty × conversion_factor` — karşılaştırma **stok biriminde**.
- `isOverAvailable(line)` → `lineStockQty > availability.free`.
- `hasOverAvailable` / `overAvailableRows` — aksiyon çubuğunu ve submit kilidini besler.
- Depo değişince (`:644`) dokunulmamış satırların deposu güncellenir ve müsaitlik
  yeniden çekilir.

---

## 9 · Çalışan toplam bloğu (`:1149-1167`)

Yalnız `editable`. Sağa yaslı, `border rounded p-3`, `min-width: 260px`.

| Satır | Koşul | Biçim |
|---|---|---|
| Subtotal | daima | gri etiket / monospace değer |
| Discount | `totalDiscount > 0` | `text-success small`, `− tutar` |
| Grand total | daima | üst çizgi, kalın etiket, `font-monospace fw-bold fs-4` |
| `≈ {taban}` | `isForeignCurrency && grandTotalBase !== null` | küçük gri, sağa yaslı |

Hesap (`:306-327`):

```
lineAmount  = qty × rate
              ├ discount_percentage > 0 → qty × max(rate × (1 − pct/100), 0)
              └ discount_amount     > 0 → qty × max(rate − amt, 0)
subtotal      = Σ qty × rate               (iskonto öncesi)
grandTotal    = Σ lineAmount               (iskonto sonrası)
totalDiscount = subtotal − grandTotal
grandTotalBase= exchangeRate > 0 ? grandTotal × exchangeRate : null
```

`≈` satırı, CLAUDE.md'nin "taban para karşılığı gösterme" kuralının belgelenmiş tek
istisnasıdır; kur yoksa **hiç çizilmez** (`0` yazmaz).

---

## 10 · Fulfilment & Billing kartı (`:1178-1277`)

Yalnız `!isCreate && docstatus === 1`. Tek `.card`, başlık `Fulfilment & Billing`.

**a) Datagrid** (`:1184-1193`) — Grand total (kalın) + Advance paid.
*(Bu iki değer § 7'deki datagrid'de zaten var.)*

**b) İki ilerleme çubuğu** (`:1196-1211`) — her biri `height: 6px`:
- **Billed** → `progress-bar bg-green`, genişlik `min(per_billed, 100)%`
- **Delivered** → `progress-bar bg-blue`, genişlik `min(per_delivered, 100)%`
- Üstlerinde etiket (gri, küçük) ve sağda yüzde (monospace, yarı kalın)

**c) Satır detay tablosu** (`:1214-1237`) — `table table-sm table-vcenter`:

| Item | Ordered | Delivered | Billed amt | Reserved |
|---|---|---|---|---|
| monospace | sağ | sağ | sağ, para | `badge bg-green-lt` ya da `—` |

**d) Bağlı faturalar tablosu** (`:1240-1270`):

| Invoice | Date | Status | Total | Stock |
|---|---|---|---|---|
| router-link, monospace | `formatDate` | `getStatusBadgeClass('Sales Invoice', …)` | sağ, para | `moves stock` (yeşil) / `no stock movement` (turuncu) |

**e) "Neden hâlâ açık?"** (`:1273-1275`) — `whyStillOpen` (`:791`), `alert alert-warning`
+ `ti-info-circle`. İlk eşleşen döner:

| Sıra | Koşul | Metin |
|---|---|---|
| 1 | taslak fatura var | *Invoice not submitted yet.* |
| 2 | gönderilmiş faturaların birinde `update_stock = 0` | *Invoiced without stock movement — stock still reserved; needs a delivery/backfill or manual close.* |
| 3 | `billing_status ≠ "Fully Billed"` | *Partially billed — {pct}% invoiced.* |
| 4 | diğer | *Fully billed but auto-close did not run — use Close below.* |

`status === "Closed"` ise hiç çizilmez.

---

## 11 · Aksiyon çubuğu (`:1280-1377`)

`FormPage`'in `#actions` slot'u — yapışkan alt çubuk.

### Create modu (`:1281-1305`)

Butonların **üstünde**, tam genişlikte iki uyarı satırı:

1. `hasOverAvailable` → kırmızı, `ti-alert-triangle`:
   *"One or more lines exceed available stock. Reduce qty or choose a different warehouse."*
2. `hasOverAvailable && session.isAdmin` → onay kutusu
   *"Override — submit despite low stock (admin)"* (`forceOverStock`)

| Buton | Sınıf | Kilitlenme koşulu |
|---|---|---|
| Cancel | `btn btn-link link-secondary` | `actionRunning` |
| Save as draft | `btn btn-outline-primary ms-auto` | `actionRunning \|\| !isFormValid` |
| Submit & reserve stock | **`btn btn-primary`** | `actionRunning \|\| !isFormValid \|\| (hasOverAvailable && !(isAdmin && forceOverStock))` |

Admin override açıkken birincil butonun metni **"Force submit & reserve"** olur.

### View modu (`:1306-1376`)

Şablonda **yedi** buton tanımlı, hepsi koşullu:

| # | Buton | Sınıf | Görünme koşulu |
|---|---|---|---|
| 1 | Save changes | `btn-outline-primary` | `can.save` |
| 2 | Submit | **`btn-primary`** | `can.submit` |
| 3 | Create Invoice | **`btn-success`** | `canCreateInvoice` (`:765`: gönderilmiş **ve** `per_billed < 100`) |
| 4 | Cancel | `btn-outline-danger ms-auto` | `can.cancel` |
| 5 | Amend | `btn-outline-secondary` | `can.amend` |
| 6 | Close & release reserved stock | `btn-outline-secondary` | `canCloseSo` (`:784`: gönderilmiş, durum ∉ {Closed, On Hold, Cancelled}) |
| 7 | Delete | `btn-outline-danger` (+`ms-auto` yalnız `can.cancel` yokken) | `can.delete` |

`can.*` `useDocumentForm.js:293-303`'ten gelir:

```
save:   editable                       (yalnız docstatus 0)
submit: !isCreate && docstatus === 0
cancel: !isCreate && docstatus === 1
amend:  !isCreate && docstatus === 2
delete: !isCreate && docstatus === 0
```

**Yani hangi durumda hangi butonlar çizilir:**

| Durum | Çizilen butonlar (soldan sağa) | Sayı |
|---|---|---|
| draft (`0`) | Save changes `outline-primary` · **Submit** `primary` · Delete `outline-danger` (`ms-auto` alır, çünkü `can.cancel` yok) | 3 |
| submitted (`1`), `per_billed < 100` | **Create Invoice** `success` · Cancel `outline-danger` (`ms-auto`) · Close & release `outline-secondary` | 3 |
| submitted (`1`), `per_billed ≥ 100` | Cancel `outline-danger` (`ms-auto`) · Close & release `outline-secondary` | 2 |
| cancelled (`2`) | Amend `outline-secondary` | 1 |

**Aynı anda en fazla üç buton** çizilir; `btn-primary` ile `btn-success` **hiçbir
durumda yan yana gelmez.**

İki `ms-auto` boşluğu (buton 4 ve koşullu olarak buton 7) hangi butonların
çizildiğine göre yer değiştirdiğinden, çubuktaki sıralama tasarlanmış değil —
şablondaki kaynak sırası + o durumda hangi `ms-auto`'nun aktif olduğu belirler.
Submitted durumunda bu, yıkıcı **Cancel**'ı nötr **Close & release**'in *soluna*
koyar.

`Close & release` `useConfirm` ile onay ister (`:811`), sonra
`stabler.api.sales.close_sales_order` çağırır ve belgeyi yeniden yükler.

---

## 12 · Davranış ve iş kuralları

| Olay | Ne olur | Satır |
|---|---|---|
| Müşteri seçilir | `customer` + `customer_name` yazılır → `get_customer_defaults` `currency` ve `price_list`'i doldurur → `loadAgreements()`. Hata **ölümcül değil** | `:433` |
| Müşteri değişir (create) | dokunulmamış satırların kuru tazelenir | `:611` |
| Fiyat listesi değişir | `refreshLineRatesForPriceList()` — yalnız `!line.rateTouched` satırlar | `:479`, `:619` |
| Para birimi değişir | taban ile aynıysa `exchangeRate = 1`, değilse `fetchExchangeRate()`. Yükleme sırasında hiçbiri | `:627` |
| Sipariş tarihi değişir | yabancı parada kur o tarihe göre yeniden çekilir | `:636` |
| Depo değişir (create) | dokunulmamış satırların deposu güncellenir + müsaitlik yenilenir | `:644` |
| Ürün seçilir | `item_sales_meta` → birim, `conversion_factor`, `rate`; sonra odak **`data-field="qty"`** ile qty'ye geçer | `:503` |
| Birim tercihi | `enable_sales_box_uom` açıksa `conversion_factor > 1` olan **en büyük** birim seçilir; kapalıysa `stock_uom`. Kodda `"korobka"` gibi literal **yok** | `:487` |
| Qty / depo değişir | 200 ms debounce ile müsaitlik çekilir | `:562` |
| Yeni form + `?new_for=` / `?customer=` | müşteri önceden seçilir | `:657`, `:677` |
| Yeni form + `?crm_deal=` / `?agreement=` | ilgili alan doldurulur | `:679-680` |
| Varsayılan depo | adı `"tayyor mahsulot"` olan depo (büyük/küçük harf duyarsız) | `:52` |

Odak yönetimi notu (`:503` yorumu): Typeahead salt-okunur olduktan sonra konumsal
indeksleme ile odaklanma `rate` alanını bozuyordu; bu yüzden odak **alan adıyla**
(`data-field`) bulunuyor.

---

## 13 · API yüzeyi

12 uç nokta:

| Uç nokta | Ne için |
|---|---|
| `stabler.api.inventory.list_stock_warehouses` | depo listesi |
| `stabler.api.inventory.item_availability` | satır bazlı stok müsaitliği |
| `stabler.api.sales.list_price_lists` | fiyat listeleri (`selling_only=1`) |
| `stabler.api.sales.list_currencies` | para birimleri + semboller |
| `stabler.api.sales.list_agreements` | anlaşma araması |
| `stabler.api.sales.list_customers` | müşteri araması (limit 10) |
| `stabler.api.sales.get_customer_defaults` | müşterinin para birimi + fiyat listesi |
| `stabler.api.sales.get_currency_exchange_rate` | CBU kuru (tarihe göre) |
| `stabler.api.sales.get_item_price` | fiyat listesinden satır kuru |
| `stabler.api.sales.item_sales_meta` | birimler, `stock_uom`, `conversion_factor`, fiyat |
| `stabler.api.sales.create_sales_invoice` | "Create Invoice" |
| `stabler.api.sales.close_sales_order` | "Close & release reserved stock" |

Belge yaşam döngüsü ayrıca `useDocumentForm` üzerinden altı uç nokta daha kullanır
(`sales_order_detail`, `create/update/submit/cancel/amend/delete_sales_order`, `:247-260`).

`resolveRate` (`:460`) **hiçbir para çevirimi yapmaz** — `get_item_price`'ın döndürdüğü
sayıyı olduğu gibi yazar.

---

## 14 · Yeniden kullanılan paylaşımlı parçalar

**Bileşenler:** `FormPage` · `LineItemsEditor` · `MoneyInput` · `DateInput` ·
`Typeahead` · `Select` · `RelatedDocuments`

**Composable'lar:** `money.js` (`formatMoney`) · `fx.js` (`readableRate`, `toLineRate`,
`formatRate`) · `date.js` (`formatDate`, `formatDateTime`, `todayIso`) · `i18n.js` (`t`) ·
`items.js` (`itemSearcher`) · `status.js` (`getStatusBadgeClass`) · `useConfirm.js` ·
`useDocumentForm.js`

> **Blast radius:** `fx.js` **altı** para ekranında kullanımda; `LineItemsEditor` ve
> `MoneyInput` daha da fazlasında. Bu sözleşmelerde yapılacak bir değişiklik Satış
> Siparişi'nin dışına taşar.

---

## 15 · Durum matrisi

| Durum | Nasıl anlaşılır | Ekran |
|---|---|---|
| **create** | `isCreate`, rota `/new` | başlık alanları düzenlenebilir · kur satırı düzenlenebilir · çalışan toplam bloğu görünür · durum şeridi, özet datagrid, Fulfilment, RelatedDocuments **yok** · 3 aksiyon |
| **draft** (`docstatus 0`) | kayıtlı ama gönderilmemiş | create ile aynı düzenlenebilirlik + durum şeridi + özet datagrid + RelatedDocuments · Save changes / Submit / Delete |
| **submitted** (`docstatus 1`) | | her şey salt-okunur · Reserved/Delivered/List rate sütunları açılır · Fulfilment & Billing kartı çizilir · çalışan toplam bloğu **kaybolur** · Create Invoice / Cancel / Close & release |
| **cancelled** (`docstatus 2`) | | salt-okunur · Fulfilment kartı **çizilmez** (`docstatus === 1` şartı) · tek buton: Amend |
| **loading** | `loading` | `FormPage`'in iskeleti; form gövdesi hiç çizilmez |
| **load error** | `loadError` | `FormPage`'in hata bloğu |
| **action error** | `actionError` | sayfa üstünde `alert alert-danger` (`:846`) **ve** `FormPage`'in kendi bloğu — ikisi birden |
| **satır yok** | `items.length === 0` | `LineItemsEditor` boş gövde çizer; ayrı bir boş-durum tasarımı **yok** |

---

## 16 · i18n

Beş dil: **en, ru, uz, uzc, tr**. Bu dosyadaki her kullanıcıya görünen dize `t()`
içinden geçer. Parametreli olanlar:

- `t("Total in {0}", [currency])`
- `t("Row {n} ({item}): qty exceeds available stock (available {free}).", {...})`
- `t("Partially billed — {pct}% invoiced.", { pct })`

Çoğul: satır sayacı `items.length === 1 ? t('item') : t('items')` (`:1141`) —
İngilizce ikili çoğula göre; Rusça'nın üçlü çoğul kuralı **karşılanmıyor**.
