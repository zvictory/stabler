# Satış Siparişi Formu — bekleyen maddeleri tamamla

Önceki Opus oturumu (`d29aa83e`, commit `d8ca0cf`/`d8aef2c`) tasarımın iskeletini kurdu: iki sütunlu `.so-grid`, numaralı 3 bölüm bandı, sağ yapışkan ray (özet + rezerv), `SalesOrderLines.vue`. Denetiminden kalan **açık maddeleri** şimdi kapatıyoruz. Aldığınız kararlar: kapsamı = "veri doğruluğu + ana sapmalar"; kredi/vade yerine yalnızca **outstanding**; para birimi kuralını **gevşet** ve "≈ $X" baz satırını ekle.

## 1 · Teslim tarihi (🔴 kritik veri hatası — audit #1/#2)
`SalesOrderForm.vue`:
- `blankForm()` (satır 173): `delivery_date: ""` ekle.
- `fromDetail()` (satır 203) zaten okuyor — olduğu gibi kalsın.
- `toPayload()` (satır 235): `delivery_date: m.delivery_date || undefined` ekle.
- Bölüm 3 şablonu (satır 1203-1213): `delivery_date` için `DateInput` ekle; `remarks` textarea ile yan yana (iki sütun). View modda `formatDateTime`→`formatDate` (tarih yok, saat de yok).
- Adım göstergesi 99. satırdaki `Boolean(f.delivery_date)` artık tetiklenebilir → step 3/3 kapanır.

Backend hazır (`sales.py:3222` create, `:3449` update, `:3259` deliver_on fallback).

## 2 · Müşteri outstanding satırı (audit #12)
Backend `stabler/api/sales.py` → `get_customer_defaults` (satır 245) dönüşüne ekle:
- `_gl_balances_for_parties(company, [customer])` ile `balance_base` (temel para biriminde açık borç) al.
- Dönüşe `outstanding_base` (flt) ve `outstanding_currency` (account_currency) ekle. Kredi limiti/vade yok (kararınız).

Frontend `SalesOrderForm.vue`:
- `pickCustomer` (satır 434): `defaults.outstanding_base` sakla → `form.value.customer_outstanding`.
- Müşteri Typeahead altına, form-control-plaintext tarzı küçük mono satır: `≈ {formatMoney(outstanding_base, baseCurrency, lang)} {t("open debt")}`. Sıfırsa "borç yok". Prototipteki renk (yeşil/kırmızı) `data-short` tonuyla.

## 3 · Baz para birimi karşılık satırı (audit #9 para birimi — kural gevşetildi)
`SalesOrderForm.vue`:
- Yeni computed `baseGrandTotal`: yabancı para ise `grandTotal × Number(form.value.conversion_rate || exchangeRate.value)`, değilse 0.
- Özet panel grand total satırının (satır 1229) altına, `v-if="isForeignCurrency"`: küçük ikincil `≈ {formatMoney(baseGrandTotal, currency, lang)}`. `≈ ` öneki elle eklenecek (`formatMoney` vermiyor).
- AGENTS.md/CLAUDE.md "Currency display" kuralına **bu ekran için istisna** notu düşülecek (comment + doc).

## 4 · Boş durum bloğu (audit #11)
`SalesOrderLines.vue`: `items` içinde `item_code`'u olan satır yoksa tasarım katmanı `.ds-empty` ile "Henüz kalem yok" bloğu çiz (prototip satırındaki metin). Üst bileşenden `hasAnyItem` prop'u ya da yerel computed.

## 5 · Cleanup
- `SalesOrderForm.vue:1163-1174`: ölü `<input type="number">` (`v-if="editable"` ama `!editable` blok içinde) — sil.
- `SalesOrderForm.vue:1012`: `formatDateTime`→`formatDate` (transaction_date zaman taşımıyor).
- Bölüm 3 başlığındaki `optional`/`complete` etiketi teslim tarihi dolunca zaten doğru çalışacak.

## Yapılmayacak (kararınız dahilinde atlanıyor)
- #10 action bar (3→2 butona indirgeme), #13 rezerv panel border state, #3-#8 CLAUDE.md kural ihlalleri, Sevkiyat dropdown (backend custom alanı yok; remarks yeterli), credit limit/vade gün (yalnızca outstanding).

## Dosyalar
- `stabler/public/js/pages/sales/SalesOrderForm.vue` (delivery_date, outstanding satırı, baz para birimi satırı, cleanup)
- `stabler/public/js/pages/sales/SalesOrderLines.vue` (boş durum bloğu)
- `stabler/api/sales.py` (`get_customer_defaults` → outstanding_base)
- `stabler/translations/en.csv` (+ `ru`/`tr`/`uz`/`uzc`): `open debt`, `No open debt`, `No items yet`, `Add a product above` (varsa atla)

## Doğrulama
- `bench run-tests --app stabler --doctype design_layer_contract` (CSS kapsam sözleşmesi).
- Elle: yeni SO aç → müşteri seç → outstanding satırı görünsün; yabancı para seç → "≈ $X" satırı; Bölüm 3'te teslim tarihi gir → adım 3/3 dolsun; kaydet → backend'de delivery_date doğru.