# Satış ve Para Formları — Tasarım Kurulu Kararı (2026-08-18)

Talep (Zafar): "new sales order form'u görelim… o formu düzeltmeyi öneriyorum, kurul ne der,
expense ve transfer formları dahil, sales order SI bunları da görelim."

İncelenen dört ekran (+ iki varyant), hepsi kaynak üzerinde tam okundu:

| Ekran | Dosya | Satır | Nerede yaşıyor |
|---|---|---|---|
| Satış Siparişi — **Modern** | `pages/sales/SalesOrderFormModern.vue` | 1877 | `main` @ `f8c7748`, bayrak `modern_sales_order` **VARSAYILAN KAPALI** |
| Satış Siparişi — Klasik | `pages/sales/SalesOrderFormClassic.vue` | 1373 | `main`, 7 kiracının tamamının gördüğü varsayılan |
| Satış Faturası — **Modern** | `pages/sales/SalesInvoiceFormModern.vue` | 571 | **`main`'de YOK** — yalnız `fix/si-custom-boxes` @ `5cd750b` |
| Satış Faturası — görüntüleyici | `pages/sales/SalesInvoiceForm.vue` | ~520 | `main` |
| Gider | `pages/money/Expenses.vue` | 1397 | `main` |
| Transfer | `pages/money/Transfers.vue` | 1062 | `main` |

Kurul: satış operasyonu (telefondaki katip), muhasebe/hazine, çok-kiracı güvenlik,
form/etkileşim tasarımı + a11y, şüpheci-denetçi.

**Kanıt rejimi.** Her kusur iddiası dört bağımsız denetçi tarafından `dosya:satır`
düzeyinde çıkarıldı; ardından **başkan tarafından bağımsız çürütme turuna** sokuldu
(görev: iddiayı yanlışla). O tur **iki iddiayı çürüttü ve bir tanesini indirdi** —
aşağıda "Çürütülen iddialar" başlığı altında kayıtta duruyorlar, çünkü ikisi de kulağa
en çok "P0" gibi gelen iddialardı. Sandbox'ta bench/DB yok; davranış teyidi
`make test-bench` + canlı bench koşusuna işaretlidir.

---

## KARAR ÖZETİ

> **Dört ekranın hiçbiri bugünkü hâliyle kabul edilmiyor, ama hiçbiri yeniden
> tasarlanmıyor da.**
>
> Satış Siparişi Modern formunun **tasarımı doğru** — yapışkan toplam çubuğu,
> sıfır-maliyetli rezervasyon paneli, dürüst adım göstergesi, karar anında müşteri
> borcu. Geri alınma sebebi tasarım değil: yeniden yazım sırasında Klasik'te **var
> olan dört koruma silindi** (kur girişi, `loadingDoc` yeniden-giriş kilidi,
> Anlaşma seçici, satır geçerlilik kapısı). Bayrak bu dördü geri gelene kadar
> açılmaz.
>
> Satış Faturası Modern formu **merge edilmez**: `detailApi` ve `updateApi` yer
> değiştirmiş — düzenleme rotası her kiracıda, her taslakta %100 ölü.
>
> Gider ekranının kur alanı **etiketiyle çelişen bir değer gösteriyor**; operatörün
> etikete uyacak şekilde düzeltmesi girişi ~10⁸ katı hatalı postalıyor.
>
> Transfer ekranı dördünün en iyi kurulmuşu — ve tek P0'ı sessiz bir kur hatası.
>
> **Ortak kök tek cümle:** bu dört ekran bir form sözleşmesini paylaşmıyor. Kur bloğu,
> aksiyon çubuğu, durum rozeti, kaydetme sözlüğü, para biçimleyici ve liste araç
> çubuğu **her ekranda ayrı ayrı yeniden icat edilmiş** — biri doğru, biri ters, biri
> hiç yok. Bu dilimin işi yeni ekran çizmek değil, **bu altı sözleşmeyi tek yere
> indirmek**.

---

## 1 · Bugün dört ekran kodda nasıl duruyor

| | SO Klasik | SO Modern | SI Modern | Gider | Transfer |
|---|---|---|---|---|---|
| Kur **girişi** | ✅ `MoneyInput` `:1005` | ❌ **hiç yok** (0 hit) | ❌ hiç yok | ⚠️ var, **ters değer** `:1091` | ✅ var, yön doğru `:916` |
| Kur **yönü** | ✅ `readableRate`/`toLineRate` | ✅ gösterimde | — (FX yok) | ❌ `fxBaseCur` çevriliyor, değer çevrilmiyor | ✅ `fromIsBase` `:152` |
| Fiyat listesi → işlem parası çevrimi | ❌ **çevrim yok** `:459-476` | ✅ `resolveRate` `:563-584` | ❌ `res.currency` okunmuyor | — | — |
| Yükleme yeniden-giriş kilidi | ✅ `loadingDoc` ×5 | ❌ **0 hit** | ❌ yok | — | ✅ `hydrating` `:405-414` |
| Satır geçerlilik kapısı | ✅ 3 `:disabled` | ❌ tanımlı, **hiç bağlı değil** | ⚠️ form seviyesi, tıklama sonrası | ⚠️ `canSubmit` yalnız boşluk | ⚠️ aynı |
| Anlaşma seçici | ✅ `:938-959` | ❌ **0 hit**, alan sessizce düşüyor | — | — | — |
| `ListToolbar` | (form) | (form) | (form) | ❌ **0 hit** + yasak "Apply" | ❌ **0 hit** + yasak "Apply" |
| Merkezî durum rozeti | ⚠️ `paymentBadge` yerel harita | ❌ **iki** yerel harita | ✅ merkezî (sonuç yanlış) | ❌ yerel harita, `t()` yok | ❌ yerel harita, `t()` yok |
| `Pagination` | — | — | — | ❌ 0 hit, `limit=50` görünmez | ❌ 0 hit, `limit=50` görünmez |
| Yetki bilgisi aksiyonlarda | ❌ yok | ❌ yok | ❌ yok | ❌ yok | ❌ yok |

Son satır kasıtlı olarak baştan sona kırmızı — bkz. §3 ve ADR-402.

---

## 2 · P0 — kabulü bloke eden bulgular

### 2.1 · Satış Siparişi Modern

**P0-SO-1 · Kaydedilmiş bir siparişi AÇMAK, para birimini ve fiyat listesini sessizce yeniden yazıyor.**
`SalesOrderFormModern.vue:473` — `loadDoc()` sonunda:
```js
if (form.value.customer) await fetchCustomerDefaults(form.value.customer);
```
ve `fetchCustomerDefaults` kaydedilmiş belgeyi koşulsuz eziyor (`:519-520`):
```js
form.value.currency  = defaults.default_currency || "";
form.value.price_list = defaults.resolved_price_list || "";
```
`grep -c fetchCustomerDefaults SalesOrderFormClassic.vue` → **0**. Klasik bu çağrıyı
yalnız `pickCustomer` içinde, yani kullanıcının açık eylemiyle yapıyor (`Classic:434-444`).

ERPNext'te `Customer.default_currency` opsiyoneldir ve çoğu kayıtta boştur → USD bir
taslak açıldığında `form.currency = ""` olur, `currency` watcher'ı tetiklenir, tüm satır
fiyatları yeniden çekilir, `toPayload` bir sonraki kayıtta `currency: undefined` +
`conversion_rate: 1` gönderir. **Sipariş sessizce taban paraya, kur 1 ile döner.**

**P0-SO-2 · Yeni yabancı para siparişinde ekran `1 USD = 1 сўм` diyor; sunucuya doğru kur gidiyor.**
Bu bir tutarsızlık değil, iki ayrı değişken:
```js
// :361-367  — GÖSTERİM ve satır çevrimi buradan
const docRate = Number(form.value?.exchange_rate);
if (isForeignCurrency.value && docRate > 0) return docRate;
```
```js
// :276-278  — PAYLOAD buradan
conversion_rate: … (exchangeRate.value > 0 ? exchangeRate.value : undefined)
```
`blankForm()` `exchange_rate: 1` yazıyor (`:180`) ve create yolunda **onu yeniden yazan
hiçbir şey yok** (`:448-449` `exchangeRate` ref'ini yazıyor, `form.exchange_rate`'i değil).
Kullanıcı yabancı para seçer seçmez `docRate === 1 > 0` → `activeRate` **1** döner:

1. `resolveRate` (`:576-577`) UZS liste fiyatını `/1` ile "çevirip" **USD satır fiyatı**
   olarak yazıyor — 12 000 katı hata, `unconverted` bayrağı dönmediği için uyarı da yok.
2. Yapışkan çubuktaki `≈` satırı (`:1541`) tam kur katı yanlış.
3. Kur alıntısı (`:1531`) `1 USD = 1 сўм` basıyor.

Sunucu doğru kuru saklıyor ve bu yanlış satır fiyatlarını onunla çarpıyor.
**Klasik bu hataya düşemez** (tek kur değişkeni, `loadDocInner` belgeden tohumluyor).

**P0-SO-3 · "Kuru elle girin" diyen mesaj, kur girişi olmayan bir ekranda.**
`:1535` — `t("Exchange rate unavailable — line prices were not converted. Enter the rate manually.")`
`grep -c MoneyInput SalesOrderFormModern.vue` → **0**. Tüm şablonda tek `<input>` var, o da
admin'in stok-aşımı onay kutusu (`:1549`).

Klasik'te doğru kurulmuş hâli duruyor (`Classic:1005-1009` + `displayExchangeRate`
getter/setter `Classic:293-303`, `toLineRate` ile geri çevirim). Kur gerçekten
bulunamadığında Modern **çıkmaz sokak**: sipariş ya terk edilir ya çevrilmemiş fiyatla
kaydedilir. Ev deseni açık — `Expenses.vue:1091` ve `Transfers.vue:916` ikisi de
`MoneyInput` veriyor; Modern SO, çapraz-kur postalayan tek ekran olurdu ki elle kur
girilemesin.

**P0-SO-4 · Yükleme yeniden-giriş kilidi silindi; taslak açmak satır fiyatlarını yeniden fiyatlıyor.**
`grep -c loadingDoc` → Modern **0**, Klasik **5** (`:356, 360, 365, 624, 633`). Klasik'in
kilidi bir olay üzerine yazılmış — dosyadaki yorum sipariş numarasını veriyor
(`Classic:351-355`: "2026-05890 11 973,9'da bağlandı ama 12 006,39 gösterdi").

Modern'in watcher'ları korumasız (`:778-792`): `load()` `form.value`'yu bütün olarak
değiştirdiği için `price_list` ve `currency` watcher'ları yükleme ortasında ateşliyor,
`refreshLineRatesForPriceList` `!line.rateTouched` filtresiyle çalışıyor ve `fromDetail`
yüklenen **her** satıra `rateTouched: false` yazıyor (`:230`). Sonuç: **pazarlıkla
girilmiş fiyatlar bugünün liste fiyatına döner**, üstelik başlık dokunulmamış belgede
"kaydedilmemiş değişiklik" yazar (`:1032`).

**P0-SO-5 · Tek ekranda iki farklı "Grand total", ikisi de aynı etiketle.**
`:1539` yapışkan çubukta, 24px kalın, istemci hesabı:
```js
const grandTotal = computed(() => (form.value?.items || []).reduce((s, l) => s + lineAmount(l), 0));
```
`:1212` ve `:1426` sunucunun `form.grand_total`'ı — aynı `t("Grand total")` etiketiyle.
Sunucu `net_total` ile `grand_total`'ı ayırıyor (`:1207` vs `:1211`), yani vergi/masraf
var; istemcinin sayısı en iyi ihtimalle **net**, yanlış etiketli ve **daha büyük
puntoyla**. Yapışkan çubukta `v-if` yok (`:1519`), yani gönderilmiş ve iptal edilmiş
belgelerde de çiziliyor — orada sapma garantili.

Klasik istemci toplamını `v-if="editable"` ile kapatıyor (`Classic:1143`).

**P0-SO-6 · Başarısız kredi sorgusu yeşil "Borç yok" olarak çiziliyor.**
`:524-526` hatayı yutuyor, `customer_outstanding` `blankForm`'daki `0`'da kalıyor
(`:192`); şablon yalnız varlığa bakıyor (`:1133`) ve `v-else` dalı yeşil noktayla
`t("No open debt")` yazıyor (`:1142`, `.so-debt > i { background: var(--ds-ok) }` `:1849`).
Üçüncü bir "bilinmiyor" durumu yok. Satışçıya, bakiyesi sorgulanamamış müşteri için
olumlu bir yeşil onay gösteriliyor.

Ayrıca aynı çip **çevrilmiş** bakiyeyi basıyor: `outstanding_currency` okunuyor,
saklanıyor (`:522`) ve **hiç kullanılmıyor** (`grep` → yalnız yazım siteleri); çip
şirket taban parasında render ediyor (`:1139`) — kural 8 ihlali.

### 2.2 · Satış Faturası Modern (`fix/si-custom-boxes` @ `5cd750b`)

**P0-SI-1 · `detailApi` ile `updateApi` yer değiştirmiş — düzenleme rotası ölü doğmuş.**
`SalesInvoiceFormModern.vue:139-152`:
```js
detailApi: "stabler.api.sales.update_sales_invoice",   // YÜKLEME yazma ucunu çağırıyor
updateApi: "stabler.api.sales.sales_invoice_detail",   // KAYIT okuma ucunu çağırıyor
```
`/sales/invoices/SINV-xxxx/edit` açılışında `load()` → `update_sales_invoice(name=…)`
`modified` olmadan → `_common.py:59-60` `frappe.throw("Stale request: reload the document.")`
→ `FormPage.vue:92` **kartın tamamını** (Geri düğmesi dahil) tek kırmızı kutuyla
değiştiriyor. Kimsenin dokunmadığı bir taslakta, uygulama içi çıkışı olmayan bir çıkmaz.

İkinci sıra (birinci düzeltilir düzeltilmez ortaya çıkar): `saveDraft()` okuma ucuna
POST atar, Frappe eşleşmeyen kwarg'ları düşürür, okuma çalışır, `useDocumentForm.js:141`
`toast.success(t("Document updated successfully."))` basar ve **hiçbir şey yazılmaz.**

Testler yeşil, çünkü `test_modern_direct_invoice_form.py:55-63` yalnız **uç adlarının
dosyada geçtiğini** doğruluyor — hangi anahtara bağlandığını değil. CLAUDE.md'nin
"kırmızıyı doğru sebeple gör" kuralının tam olarak önlemek için var olduğu tuzak.

**P0-SI-2 · Düzenle düğmesi SO'dan doğmuş faturalarda da açık; kaydetmek SO bağını yok ediyor.**
`SalesInvoiceForm.vue:427` düğmeyi `can.delete` (yani docstatus 0) ile kapılıyor —
faturanın nasıl doğduğuna bakmıyor. `update_sales_invoice` satırların tamamını
değiştiriyor (`sales.py:2489`) ve `_direct_invoice_item_rows` satır sözlüğünde
`so_detail`, `sales_order`, `discount_percentage`, `discount_amount`,
`custom_length/width/height/pieces` **yok**. Sonuç: **SO'nun `per_billed`'ı ilerlemeyi
durdurur, stok rezervasyonu gönderimde serbest bırakılmaz**, satır iskontoları iz
bırakmadan silinir.

**P0-SI-3 · Ekrandaki tek sayı NET; sunucu KDV'li grand total saklıyor.**
`grep -in "tax|vat|qqs|net_total|grand_total" SalesInvoiceFormModern.vue` → **0 hit**.
Alt bilgideki tutar `Σ qty × rate` (`:290-292`) — yani `net_total` — ve **etiketsiz**
(`:361-363` çıplak `<span>`). Katip bir sayıyı onaylıyor, Gönder'e basıyor, saniyeler
sonra Klasik görüntüleyicide **farklı ve daha büyük** bir grand total okuyor; ekranda
onu açıklayan bir KDV satırı yok.

**P0-SI-4 · İşlem para birimi şirket tabanına sabitlenmiş; fiyat listesinin parası yok sayılıyor.**
`:53` `session.currency` (taban) doğrudan faturanın işlem parası olarak gidiyor (`:98`);
para seçici yok (0 hit). Fiyat listesi açılır menüsü parayı **etikette gösteriyor**
(`:190`) ama `get_item_price`'ın döndürdüğü `res.currency` **hiç okunmuyor** (0 hit).
UZS defterli şirkette USD fiyat listesi seçilince `4.42` UZS faturaya **4 сўм/kg**
olarak iniyor — ve `MoneyInput` UZS'yi tam sayı biçimlediği için yanlış bile görünmüyor.

**P0-SI-5 · Kaydedilmiş taslağı açmak her satırı bugünün fiyatına çekiyor.**
`:256` `watch(() => model.value.price_list, refreshAllRates)` + `load()`'ın modeli bütün
olarak değiştirmesi → `"" → "Retail"` geçişi watcher'ı ateşler, `fetchRate` her satırın
`rate`'ini ezer. Dün anlaşılan fiyat, yeniden açılınca sessizce bugünün fiyatı olur.
**SO Modern'deki P0-SO-4 ile aynı kusur, aynı sebep, iki ayrı dosyada.**

**P0-SI-6 · Koli ⇄ kg gidiş-dönüşü kayıplı ve kutu sıfırlanınca miktar eskisinde kalıyor.**
`:274-286` — her iki koruma da `b > 0`. Kutu hücresi silinince `custom_boxes: 0` yazılır
ama `qty` ve `box_kg` eski değerlerinde kalır: fatura **sıfır kolide 140 kg** iddia eder.
Ayrıca 7 × 20 = 140 → kg 139,5'e düzeltilince `box_kg = 19.93` olur, 7 × 19,93 = 139,51 ≠ 139,5.

**P0-SI-7 · Yazılan koli sayısı hiçbir okuma yüzeyinde yok; baskı çelişkili bir koli rakamı hesaplıyor.**
`grep -rn "custom_boxes|custom_box_kg" public/js --include=*.vue` → tek hit
`SalesInvoiceFormModern.vue:126-130`. `SalesInvoiceForm.vue`'da `box` **0 hit**.
`InvoicePrint.vue:23-33` koliyi **ürün adındaki `(\d+)` regex'inden** türetiyor ve
`t("Per box")` altında `rate / pcs` basıyor — `rate` kilo başına olduğu için 20 kg'lık
50 000 сўм/kg kutu müşterinin faturasında **2 500 сўм** yazıyor. 400 kat sapma, ters
yönde. Aynı regex `Waybill.vue:27-40`'ta da var.

Devir notu (`docs/plans/2026-08-18-HANDOFF-msa-direct-invoice.md`) prod'da koli taşıyan
son satırın **2026-07-28** olduğunu ölçmüş — yazma yolu onarıldı, **okuma yolu hâlâ kopuk**.

**P0-SI-8 · Rozet docstatus ile renkleniyor: "Overdue" faturalar yeşil.**
`FormPage.vue:66-71` `docstatus` sayı olduğunda `STATUS_MAP.docstatus`'a kısa devre
yapıyor (`status.js:392-393`), yani `"Sales Invoice"` haritası (`status.js:95-103`,
`Overdue: bg-red-lt`) **formdan hiç ulaşılmıyor**. Etiket `t(status)` olduğu için
gönderilmiş vadesi geçmiş fatura **yeşil "Overdue"** çiziyor; aynı fatura listede
kırmızı. Bu `main`'de de canlı.

### 2.3 · Gider

**P0-EXP-1 · Kur alanının değeri etiketiyle çelişiyor; etikete uydurmak ~10⁸ katı yanlış postalıyor.**
`Expenses.vue:302-314` kanonik alıntıyı doğru kuruyor ama değeri çevirmiyor:
```js
if (raw >= 1) { base = baseCurrency; R = raw; } else { base = payCurrency; R = 1 / raw; }
fxBaseCur.value = base;  cbuRate.value = R;
form.value.exchange_rate = raw;      // :314 — DAİMA raw, hiç R değil
```
Baskın Özbek yapılandırmasında (taban UZS, ödeme hesabı USD) `raw ≈ 0,0000772` →
`fxBaseCur = "USD"`, `cbuRate = 12 953`. Operatörün gördüğü tek kontrol:

> `1 USD =`  `[USD] 0.00`  ·  `CBU: 12 953`

`0.00` ölçülmüş: `MoneyInput`'a `:currency="payCurrency"` (USD) veriliyor,
`maxFractionDigits` yok → 2 hane. Otomatik yol doğru postalıyor (`:675`
`exchange_rate: 1/rate`, backend `money.py:2730-2733` ile uyumlu). Öldüren şey UI'nin
davet ettiği **elle düzeltme**: etikete ve CBU ipucuna uyup `12953` yazıldığında 100 $
gider `100 × 1/12953 = 0,0077 UZS` olarak postalanır. `canSubmit` yalnız `> 0` bakıyor
(`:277`), tek çapraz kontrol olan `tfoot` taban sütunu (`:1330-1332`)
`fmtAmt(0.0077, "UZS")` → **`"0"`** basıyor.

`Transfers.vue` bunu `fromIsBase` (`:152`) + yön farkında `derive()` (`:218-227`) ile
doğru çözmüş. Gider'de karşılığı yok.

**P0-EXP-2 · "Save & clear" hiçbir şey kaydetmiyor — ve bir kez kullanıldıktan sonra birincil düğmenin varsayılanı oluyor.**
`:624-639`:
```js
persistSaveMode(afterAction);          // :626 — ÖNCE localStorage'a yazıyor
if (afterAction === "clear") {
    form.value = blankForm();          // :630 — formu siliyor
    …
    return;                            // :638 — hiçbir API çağrısı yok
}
```
`SAVE_MODE_KEY` kalıcı olduğu için, bir kez seçildikten sonra büyük birincil düğmenin
**etiketi "Save & clear", davranışı "at"** olur. 6 satırlık gider yazan kullanıcı,
birincil düğmeye basınca — diyalog yok, toast yok, geri alma yok — hepsini kaybeder.

### 2.4 · Transfer

**P0-TRF-1 · Başarısız kur çağrısı yutuluyor; ÖNCEKİ para çiftinin kuru yenisine uygulanıyor.**
`:294-296` `catch` yalnız `console.error` yazıyor; `cbuRate`, `fxBaseCur`,
`form.exchange_rate` ve `AUTO` rozeti **eski değerlerinde kalıyor**, hesap watcher'ı
`derive()`'i yine de koşturuyor (`:307`). `get_exchange_rate_for_currencies` eksik çiftte
**throw ediyor** (`money.py:3057-3061`).

Senaryo: USD→UZS (12 950 state'te) yapıldıktan sonra EUR→UZS'ye geçilir, EUR kuru yok,
çağrı sessizce patlar. `fxBaseCur` hâlâ `"USD"` → `fromIsBase` false → `derive()`
`to_amount = from_amount / 12950` hesaplar. Ekran hâlâ `CBU: 12 950` ve mavi **`AUTO`**
rozetiyle kurun otoriter olduğunu iddia ediyor. `canSubmit` geçiyor, transfer başka bir
para çiftine ait kurla, ters yönde postalanıyor. Gider bu yolda `rateError` gösteriyor
(`:319`); Transfer'de `rateError` diye bir şey **yok**.

### 2.5 · Gider + Transfer ortak

**P0-MONEY-1 · Liste "Amount" sütunu iki para birimini toplayabiliyor ve yanlış parayla etiketleyebiliyor.**
`money.py:2604-2611`:
```sql
COALESCE((SELECT SUM(credit_in_account_currency) … ), je.total_credit) AS total_amount,
COALESCE((SELECT account_currency … LIMIT 1), c.default_currency)    AS currency
```
`fx_balance.py:150-153` **her** Journal Entry kaydında bir `fx-rounding-auto` artık satırı
ekliyor. Alacak tarafına düştüğünde `SUM` `1 000 000 UZS + 0,02 USD` yapıyor ve
**`ORDER BY`'sız `LIMIT 1`** para etiketini rastgele seçiyor: 1 000 000 сўм'lik gider
`$1,000,000.02` olarak render edilebiliyor. Kural 10'un ("iki parayı tek sayıda toplayan
toplam P0'dır") birebir ihlali. Her iki sayfa da bunu `formatMoney`'e korumasız veriyor.

**P0-MONEY-2 · Satıra tıklamak, gönderilmiş belgeyi sessizce iptal edip yeniden postalayan bir forma düşürüyor.**
Her iki listede de **salt-okunur yol yok**: satır tıklaması `openInForm(r.name)`
(`Expenses:900`, `Transfers:709`) → amend formu. Form içinde **docstatus rozeti yok**,
yani taslak ile postalanmış GL belgesi düzenlenirken görsel olarak ayırt edilemiyor.
Alt düğme `t("Save & close")` diyor. `amend_expense_entry` (`money.py:2900-2926`)
`source.cancel()` çağırıp yerine yenisini yazıyor — **onay diyaloğu yok**. Oysa daha az
yıkıcı olan `cancelEntry` ve `deleteEntry` ikisi de `confirm()` ile kapılı
(`:778-785`, `:799-806`).

**P0-MONEY-3 · Maker-checker eşiğini aşan bir amend parayı defterden düşürüyor, haberi sonradan veriyor.**
`amend_*` kaynağı iptal ediyor, `submit_or_route(doc)` ise `requires_approval(doc)` ise
yenisini **Taslak** bırakıyor (`approvals.py:353-370`). Net etki: orijinal iptal, yenisi
postalanmamış, defter o tutar kadar eksik. UI'nin bu konudaki tek katkısı tıklama
sonrası bir toast: `toast.warning(t("Saved — pending approval before it posts."))` (`:696`).
Eşik istemci tarafında bilinebilir (`baseEquivalent` zaten hesaplanıyor, `:260-265`);
hiçbir whitelisted uç bu yapılandırmayı SPA'ya vermiyor.

**P0-MONEY-4 · Amend, formun modelleyemediği her bacağı sessizce atıyor ve ithalat geri-bağını koparıyor.**
`openEditFromDetail` (`Expenses:571-596`) voucher'ı **ilk alacak** + **tüm borçlar**
şeklinde yeniden kuruyor; ikinci alacak bacağı, maliyet merkezi, boyut düşüyor — ve
`amend_expense_entry` orijinali iptal ettikten sonra bu indirgenmiş hâli postalıyor.
`list_bank_entries`'in Gider filtresi "Asset Purchase VEYA herhangi bir Expense-kök
hesaba dokunan" (`money.py:2546-2554`), Transfer ise onun değili — yani şirketteki
**her** `Bank Entry` bu iki listeden birinde ve hepsi tek tıkla kayıplı amend'e açık.

İthalat için somut: payload `commercial_invoice` gönderiyor ama `import_expense`
göndermiyor (`:654-671`), yani `custom_import_expense` — `money.py:2778-2782`'de
"bu voucher'ın zaten bir Import Expense ebeveyni olduğunun işareti, saygı görmeli"
diye tarif edilen alan — kayboluyor. Spawn hook'unun idempotency anahtarı
`{"journal_entry": doc.name}` (`imports_module/hooks.py:1417`) ve amend **yeni ad**
ürettiği için koruma ıskalıyor: **ikinci bir Import Expense doğuyor.**

---

## 3 · Kusurların ortak kökü — dört ekran, altı kopyalanmış sözleşme

Yukarıdaki 21 P0'ın 17'si dört bağımsız hata değil; **altı sözleşmenin ekran başına
yeniden icat edilmesinin** semptomu.

| # | Sözleşme | Kaç ayrı uygulama | Hangisi doğru |
|---|---|---|---|
| 1 | **Kur bloğu** (giriş + yön + hata) | 4 (SO Klasik, SO Modern, Gider, Transfer) | SO Klasik yönde, Transfer türetmede; **hiçbiri ikisi birden değil** |
| 2 | **Aksiyon çubuğu grameri** | 5 | hiçbiri (§4 ADR-403) |
| 3 | **Durum rozeti** | 4 yerel harita + 1 merkezî-ama-yanlış | hiçbiri |
| 4 | **Kaydetme sözlüğü** | `Save & close` / `Record & close` / `Save Draft` — ve Gider'in amend'i "Save & close" derken Transfer'inki de öyle diyor, oysa create'i "Record & close" | hiçbiri |
| 5 | **Para biçimleyici** | paylaşılan `formatMoney` **+** sayfa-yerel `fmtAmt`/`fmtRate`, aynı kartın içinde yan yana | `formatMoney` |
| 6 | **Liste araç çubuğu** | `ListToolbar` (5 money sayfası) vs elle "Apply" (Gider, Transfer) | `ListToolbar` |

Ve hepsinin altında yedincisi:

**`can.*` hiçbir yetki bilgisi taşımıyor.** `useDocumentForm.js:293-305`:
```js
save: editable.value,                    // = isCreate || docstatus === 0
submit: !isCreate.value && isDraft,
cancel: !isCreate.value && isSubmitted,  … 
```
Tamamı **yalnız docstatus**. `sales_invoice_detail` hiçbir `can_write`/`permissions`
anahtarı dönmüyor (`sales.py:1628-1693`, 0 hit). Gider/Transfer aksiyonları da
`docstatus`-only (`Expenses:1012-1018`, `Transfers:812-818`), oysa sunucu gerçekten
`_assert_can_write("Journal Entry", …, "cancel")` istiyor (`money.py:2881, 2891, 2901, 2916`).

Sonuç dört ekranda aynı: **iptal yetkisi olmayan bir katibe etkin bir "İptal" düğmesi
gösteriliyor**, tehlike diyaloğunu onaylıyor, ve karşılığında ham bir
`frappe.PermissionError` metni alıyor. Bu, Havale kurulunun D5 bulgusunun
(`2026-08-16-remittance-design-council-decision.md`) birebir tekrarı — orada da karar
"UI ana aksiyonu backend'in `allowed_actions` cevabından alır" idi ve hiçbir yerde
uygulanmadı.

---

## 4 · Kararlar (ADR)

### ADR-401 — Tek kur bloğu bileşeni; dört kopya emekli edilir
Yeni `components/ExchangeRateBlock.vue` (ya da `composables/fx.js`'in genişletilmiş
sözleşmesi). Tek uygulamada dört değişmez:
1. **Gösterim daima güçlü yönde** — `1 USD = 12 101,85 UZS`, asla `0,000082632`.
2. **Giriş etiketle aynı yönde** ve `toLineRate` ile ERPNext yönüne geri çevrilir —
   bugün yalnız `SalesOrderFormClassic.vue:293-303` böyle.
3. **Kur bilinmiyorsa `null`**, asla `1`'e düşülmez, ve elle giriş **her zaman
   erişilebilir** — P0-SO-3'ün tek kalıcı cevabı.
4. **Başarısız çekim durumu sıfırlar** ve inline hata gösterir — `AUTO` rozeti stale
   kurun üstünde kalamaz (P0-TRF-1).

Beş ekran (SO ×2, SI, Gider, Transfer) bu tek bileşeni kullanır. `Expenses.vue:302-314`
ve `Transfers.vue:262-297` silinir.

### ADR-402 — Aksiyon görünürlüğü sunucudan gelir: `allowed_actions`
Belge detay uçları (`sales_order_detail`, `sales_invoice_detail`, `_load_bank_entry`)
cevaba `allowed_actions: ["save","submit","cancel","amend","delete","create_invoice",…]`
ekler; `useDocumentForm.can` bunu okur, docstatus'tan **türetmeyi bırakır**. İstemci
tarafı rol kontrolü **reddedildi**: `_MODULE_ROLES` haritasındaki boşluk (devir notu,
`direct_invoicing` vakası) istemci tarafı rol mantığının bu kod tabanında güvenilmez
olduğunu zaten gösterdi.

Kapsam: dört ekranın tamamı + Havale (kurulun D5'i böylece kapanır).

### ADR-403 — Tek aksiyon çubuğu grameri, dört durumun her biri için tasarlanır
Kural, hepsi test edilebilir:
- **Bölge başına tek dolgulu düğme.** Gönderilmiş SO'da `btn-success` "Create Invoice"
  tek dolgulu düğme olarak birincil rolü üstleniyor (`Modern:1579`, `Classic:1324`) —
  bu kural 4'ün kendi örneğidir, düzeltilir.
- **Yıkıcı aksiyon asla nötr aksiyonun solunda değil.** Bugün gönderilmiş SO'da Klasik
  `ms-auto`'yu Cancel'a koyduğu için nötr "Close & release" onun **sağına** düşüyor;
  Modern'de `ms-auto` hiç yok (0 hit) ve Delete, Submit'ten 12px uzakta duruyor.
- **`flex-wrap` zorunlu.** `.so-sticky-actions` (`Modern:1817-1821`) sarmıyor;
  gönderilmiş durumda 5 düğme + RU/UZC uzunluğu taşırıyor.
- **"Cancel" kelimesi iki anlamda kullanılamaz.** `Classic:1290` "formu terk et",
  `Classic:1338` "belgeyi iptal et".
- Dört durumun (create / taslak / gönderilmiş / iptal) **her biri için yerleşim
  çizilir**; sıralama kaynak sırasına ve `ms-auto`'nun nereye düştüğüne bırakılmaz.

### ADR-404 — Tek kaydetme sözlüğü
`Save & close` / `Save & new` / `Save & clear` — beş ekranda aynı. `Record & …` ve
`Save Draft` emekli. **`Save & clear` ya gerçekten kaydeder ya da adı `Discard & new`
olur** (P0-EXP-2); üçüncü seçenek yok. Ve `persistSaveMode` yalnız **başarılı bir
kayıttan sonra** yazar.

### ADR-405 — Yükleme sırasında watcher'lar susar
`useDocumentForm` bir `hydrating` bayrağı yayınlar; `price_list`, `currency`,
`customer` watcher'ları ondan geçer. Bugün üç ayrı çözüm var: Klasik `loadingDoc`
(`:356-365`), Transfer `hydrating` (`:405-414`), SO Modern ve SI Modern **hiçbiri**.
Tek yere iner. Bu, P0-SO-1, P0-SO-4 ve P0-SI-5'in ortak cevabıdır.

### ADR-406 — Para biçimlemesi tek yoldan: `formatMoney` / `formatRate`
`Expenses.vue:98-112` ve `Transfers.vue:186-201`'deki yerel `fmtAmt`/`fmtRate` silinir.
Ölçülmüş sebep: `tr` yerelinde aynı değer yan yana `1 234 567.50` (yerel) ve
`1.234.567,50` (paylaşılan) olarak çiziliyor — Türkçe'de `.` binlik ayırıcı olduğu için
biri bir buçuk **milyar** okunuyor.

### ADR-407 — Gider ve Transfer, kendi modülünün standardına döner
`ListToolbar` + otomatik uygulanan filtre (Apply düğmesi silinir) + `SkeletonRows` +
`Pagination` + `StatusBadge`. Referans dört satır: `PaymentEntries.vue:94` ve `:100-108`.
Bunlar `/money` içinde **kendi modüllerinin tek aykırısı** — `Approvals`, `Budgets`,
`BudgetVsActual`, `FxRevaluation`, `PaymentEntries` hepsi zaten uyumlu.

### ADR-408 — `modern_sales_order` bayrağı: düzeltilir ve tek varyanta inilir
İki 1400-1900 satırlık varyantı süresiz taşımak seçenek değil — ikisi de statik import
ediliyor (`SalesOrderForm.vue:17-18`), yani **7 kiracının hepsi hiç görmeyeceği 66 KB'ı
indiriyor.** Karar: Modern, ADR-401 + ADR-405 + P0-SO-5/6 kapandıktan ve Anlaşma
seçicisi geri geldikten sonra tek kiracıda açılır; iki hafta gözlem; sonra varsayılan
olur ve **Klasik silinir**.

Klasik'ten Modern'e **taşınacak** olan: kur `MoneyInput`'u (`:1005-1009`), `loadingDoc`
(→ ADR-405), Anlaşma seçici (`:938-959`), `isFormValid` kapısı (`:1291/1295/1305`).
Modern'den Klasik'e **taşınacak** olan (bayrak açılmasa bile, çünkü Klasik'te de bug):
`resolveRate`'in fiyat listesi → işlem parası çevrimi (`Modern:563-584`; Klasik
`:459-476` `res.currency`'yi hiç okumuyor, UZS liste fiyatını USD siparişe ham yazıyor).

### ADR-409 — Satış Faturası: satır ızgarası faturaya özel kalır, klavye sözleşmesi paylaşılır
Devir notu (`2026-08-18-HANDOFF-msa-direct-invoice.md`) `LineItemsEditor`'a koli
öğretmenin altı kiracının SO ekranına dokunmak olacağını, ve bunu kilitleyen bir test
olduğunu kaydediyor. **Bu sınır korunur.** Ama bugün SI ızgarasının **hiç `@keydown`'ı
yok**: SO'da öğrenilen ↑/↓ sütun gezinme, Esc, Tab-ile-yeni-satır, Enter-ekle
(`LineItemsEditor.vue:120-244`) faturada çalışmıyor. Klavye davranışı ve satır-içi
doğrulama ortak bir composable'a çıkar; **sütunlar ayrı kalır, davranış ayrı kalmaz.**

### ADR-410 — Koli okuma yolu kapatılır; ürün adı regex'i silinir
`custom_boxes` / `custom_box_kg` `SalesInvoiceForm.vue` görüntüleyicisine, `InvoicePrint.vue`'ya
ve `Waybill.vue`'ya bağlanır; `/\((\d+)\)\s*$/` regex'i (`InvoicePrint.vue:23-33`,
`Waybill.vue:27-40`) silinir. Bugün yazılan alan hiçbir ekranda okunmuyor ve baskı,
müşteriye `box_kg²` katı yanlış bir koli fiyatı gösteriyor.

---

## 5 · Kapatılması zorunlu — D maddeleri

Ekran başına, P0 olmayan ama tasarım turunda **çözülmüş olarak çıkması gereken** kusurlar.

### Satış Siparişi Modern
- **D1** Ürün sayısı kendisiyle çelişiyor: `itemsSummaryLabel` dolu satırları sayıyor
  (`:110`), yapışkan çubuk hepsini (`:1523`). Yeni siparişte başlık **"0 items"**,
  alt bilgi **"Grand total · 1 item"**.
- **D2** "Step 3/3"ü tamamlayan alan, varsayılan **kapalı** bir katlamanın içinde ve
  başlığı **"optional"** yazıyor (`openDelivery = ref(false)` `:49`; `:1344`).
- **D3** Bölüm başlığı `4 ·` diye numaralanmışken sayaç `Step X/**3**` diyor
  (`sectionsDone` 3 girdi `:99-106`, şablonda 4 bölüm).
- **D4** Katlanmış başlık **tüm remarks gövdesini** kesmeden basıyor (`:1347-1348`,
  `.so-fold-meta`'da `max-width`/`overflow` yok).
- **D5** Aynı sayı çoklu: grand total ×3, advance paid ×2, delivered % ×2, billed % ×2,
  bağlı faturalar hem çip hem tablo, satır-başı reserved ×2. "Reserved" kelimesi tek
  ekranda **üç farklı anlamda** (rozet `:1052`, sütun `:1276`, bölüm başlığı `:1374`).
- **D6** Belge durumuna göre **iki farklı satır tablosu**: `SalesOrderLines` (editable)
  vs `LineItemsEditor` (read-only) — sütun sırası ve klavye davranışı yalnız teamülle
  aynı. Klasik ikisinde de `LineItemsEditor` kullanıyor.
- **D7** "Quotation" pipeline adımı **erişilemez** — `pipelineStage` yalnız 2/3/4
  döndürüyor (`:923-931`), `:1059`'daki `active` sınıfı hiç uygulanmıyor.
- **D8** Sayılar tek ekranda üç ayrı biçimde: `r.need` ham, `r.free`
  `toLocaleString()` (**tarayıcı** yereli), para `formatMoney(…, user.language)`
  (`:1395`). Rusça arayüzlü, en-US tarayıcılı kullanıcı `1,234 m² available` yanında
  `1 234 567,00 сўм` okuyor.
- **D9** `v-for` anahtarları çakışıyor: `:key="r.code"` (`:1387`) satır başına
  üretiliyor, aynı ürün iki satırda ise iki kart aynı anahtarla; `:key="it.name"`
  (`:1465`) — `fromDetail` `name`'i hiç taşımıyor, **her satır `undefined`**.
- **D10** Devam eden `refreshLineRatesForPriceList` kullanıcının yazdığı fiyatı eziyor:
  `!line.rateTouched` filtresi **bir kez** değerlendiriliyor, sonra N ardışık `await`
  geliyor (`:592-599`). `pickCustomer` üç watcher'ı aynı anda ateşleyip **üç eşzamanlı
  seri döngü** başlatıyor — debounce yok, iptal yok, ilerleme göstergesi yok.
- **D11** Odak için **global DOM sorgusu**: `document.querySelector(".so-lines tbody, …")`
  (`:705-708`) — bileşenin dışına uzanıyor, `index` üç `await` öncesinde yakalanmış.
- **D12** Dokunma hedefi: `.so-disc-btn { min-height: 34px }` (`:1830`) — 40px altı.
- **D13** Devre dışı düğmenin gerekçesi yalnız `title` ile veriliyor (`:1238-1239`);
  devre dışı düğme odaklanamaz, `title` okunmaz — klavye ve dokunma kullanıcısı için
  sebepsiz ölü düğme.
- **D14** `beforeRouteLeave`/`beforeunload` **0 hit** — form "kaydedilmemiş değişiklik"
  yazıyor (`:1032`) ama çıkışta uyarmıyor.
- **D15** Tek ekranda üç tasarım dili: `.ds-form-section` (1-4), Tabler `.datagrid`
  (`:1205`), ham Tabler `.card` (`:1417`).

### Satış Faturası
- **D16** Kısıtlama afişi **yanlış sebebi** suçluyor ve kullanıcı metnine kiracı adı
  gömüyor: `t("Direct Sales Invoicing is only enabled for MSA. For company '{0}'…")`
  (`:395-402`) — oysa `canAccessModule("imports")` rol kapısı da aynı afişi ateşliyor.
  Backend'in kendi mesajı (`sales.py:2340`) kiracı-nötr; ekranınki değil.
- **D17** Devre dışı hâl yalnız görsel: `opacity-50 pe-none` (`:407`). `pointer-events`
  tab sırasını kaldırmıyor — klavye kullanıcısı kaydedilemeyecek bir forma tam bir
  fatura yazabiliyor. `opacity-50` gövde metninde WCAG AA kontrastını da bozuyor.
- **D18** `for=`/`id=` **0 hit**, `aria-` **0 hit**. Altı `<label>` sahipsiz; ızgarada
  satır başına dört etiketsiz sayısal alan.
- **D19** Bu ekranın getirdiği **her yeni dize dört dilde çevrilmemiş** (ru/uzc/tr/uz'da
  0 hit): `Save Draft`, `Save & Submit`, `BOXES`, `BOX KG`, `TOTAL KG`, `ITEM CODE / NAME`,
  `Add Item`… Yarısı zaten çevrili bir dizenin kopyası (`Save as draft` beş dilde var).
- **D20** Sabit sütun genişlikleri ~940px topluyor (`:468-475`), telefon birincil veri
  girişi yüzeyinde yatay kaydırıyor; RATE hücresi 140px'e `MoneyInput`'un para eklentili
  input-group'unu sığdırmaya çalışıyor.
- **D21** Modern formda **Print / Waybill / RelatedDocuments / Payment / Didox / Return /
  Cancel / Amend / Delete yok** (hepsi 0 hit). "Create"in dışındaki her şey Klasik
  görüntüleyiciye gidiş-dönüş gerektiriyor.
- **D22** `?customer=` / `?new_for=` derin bağlantıları (`:161-165`) id'yi set ediyor ama
  `pickCustomer` çağırmıyor: müşteri adı boş, Typeahead ham kodu gösteriyor, varsayılan
  fiyat listesi ve satır fiyatları çekilmiyor.
- **D23** Tek kalan satırın çöp düğmesi **kalıcı devre dışı** (`:553`) — son satırı
  temizlemenin yolu yok.
- **D24** Üçüncü kopya: `components/NewDirectInvoiceModal.vue:42` bayt-bayt aynı satır
  literalini ve kendi `recomputeQty`/`recomputeBoxKg`'sini taşıyor (`:152-163`), iki
  sayfada mount ediliyor ama `directInvoiceOpen` **hiçbir yerde `true` yapılmıyor**.
  Backend'de tek satır kurucu var; frontend'de üç tane.

### Gider
- **D25** Ek/fiş yok: `attach` 0, `upload` 0, `<input type="file">` 0. Maker-checker
  kuyruğu olan bir sistemde onaylayıcıya karşılaştıracak hiçbir şey verilmiyor.
- **D26** Vergi yok (`tax|vat` anlamlı 0 hit) — KDV/stopaj alanı ve vergi önizlemesi yok.
- **D27** Borç tarafı modellenemiyor: alacak bacağı daima Banka/Kasa/Özkaynak
  (`:528-531`). **Ödenmemiş gider bu ekranda kaydedilemiyor** — nakit esaslı. Kasıtlıysa
  ekranın bunu söylemesi gerekiyor (bkz. §7, Zafar kararı).
- **D28** Aynı dosya kendisiyle çelişiyor: `:571` `is_fx_rounding` satırını filtreliyor,
  `:999` postings tablosu filtrelemiyor — kullanıcı "Exchange Gain/Loss 0,02" diye
  açıklanmamış üçüncü bir satır görüyor.
- **D29** İthalat kategorisi **çıplak `<select>`** (`:1153-1157`), oysa sayfadaki her
  seçici paylaşılan `Select.vue` (`:1071`).
- **D30** Klavye: satır silme düğmesi `tabindex="-1"` (`:1256-1261`) — klavye-öncelikli
  bir satır editöründe satır silmenin klavye yolu yok. `handleLineKeyDown` (`:210-229`)
  input indekslerini sabit kodluyor; `assetMode`'da her şey bir kayıyor ve **Memo Tab
  ile erişilemez** oluyor.
- **D31** Split düğmenin okla açılan yarısı **boş** ve `aria-label`'sız
  (`:1376-1382`) — ekran okuyucu yalnız "button" diyor.
- **D32** `submitCreate`'de yeniden-giriş kilidi yok (`:624`); `:disabled` yalnız
  düğmelerde, dropdown öğelerinde değil (`:1384`).
- **D33** Kayıttan sonra `markFormPristine()` çağrılmıyor (`:628-639`) — ilk "Save & new"
  sonrası boş formdan çıkmak bile **her seferinde** "Discard unsaved changes?" açıyor.
  Bu, gerçek diyaloğu görmezden gelmeyi öğretir.

### Transfer
- **D34** Listede **From ve To hesabı sütun değil** (`:711-721`) — transferi transfer
  yapan iki bilgi listede yok.
- **D35** `swap()` yazılmış tutarları uyarısız siliyor (`:424-434`).
- **D36** Tarih watcher'ı `rateManuallyEdited`'ı sıfırlıyor (`:317`) — elle yazılmış kur,
  tarih değişince sessizce eziliyor.
- **D37** Özet satırı yalan söyleyebiliyor: kur çekimi patladığında `to_amount` null olup
  **"1 000 USD → 1 000 UZS"** çiziliyor (`:999`). `canSubmit` göndermeyi engelliyor ama
  ekran bunu olgu olarak gösteriyor.
- **D38** Kur iki farklı hassasiyette, birkaç santim arayla: özet `1.0825` (`:1001`),
  input `1.08` (`:916-923`).
- **D39** Swap kontrolü — parayı ters çeviren, ekrandaki en sonuçlu düğme — `btn-icon
  btn-sm` (`:935`), mevcut en küçük boy.

### Gider + Transfer ortak
- **D40** Yükleme **boşlukta spinner**: `<div class="card-body text-center py-5"><div class="spinner-border">`
  (`Expenses:863`, `Transfers:673`). Tablo başlığı kayboluyor, kart spinner'a çöküyor.
  `SkeletonRows` Gider'de import edilmiş ama yalnız form içinde kullanılmış (`:1190`);
  Transfer'de **0 hit**.
- **D41** Yerel durum haritası `t()`'den geçmiyor: `Draft / Submitted / Cancelled`
  **beş dilde de İngilizce** (`Expenses:719-724`, `Transfers:528-533`). Üstelik
  `list_bank_entries` `docstatus < 2` filtreliyor (`money.py:2570`), yani "Cancelled"
  dalı listeden hiç erişilemiyor.
- **D42** `EmptyState` başlıkları sabit İngilizce (`Expenses:874-875`, `Transfers:684`).
  Depo genelinde 316 doğru `:title="t(...)"` kullanımına karşı 10 ham kullanım var;
  bu ikisi o ondan.
- **D43** Sayfalama yok, 50 satır sınırı görünmez (`limit = ref(50)`, hiç bağlanmamış,
  `rows.length` hiç gösterilmiyor). 90 günlük aralık filtreleyen kullanıcı en yeni 50
  kaydı görüyor, **kırpıldığına dair hiçbir işaret yok**.
- **D44** Sıralama kontrolü ve aciliyet sıralaması yok — sabit `ORDER BY posting_date DESC`
  (`money.py:2615`), durum filtresi yok. "Hangi kayıtlarım onay bekliyor?" sorusu bu iki
  ekrandan cevaplanamıyor.
- **D45** `useFocusTrap` bir **overlay'e değil, tam sayfaya** uygulanmış (`Expenses:51`,
  `Transfers:49`) — form açıkken kenar çubuğu ve global navigasyon klavyeyle erişilemiyor.
- **D46** Detay alt bilgisinde `btn-primary` yok; bölge `btn-outline-primary` (Amend) +
  `btn-outline-danger` (Delete/Cancel) — **kırmızı maviyi bastırıyor**, yani renk birincil
  rolü üstleniyor ve üstlendiği aksiyon geri alınamaz olan.
- **D47** 390px'te liste aksiyon çubuğu sarmıyor (`flex-wrap` 0 hit); iki `DateInput` +
  iki düğme sarmayan bir `.card-header` içinde. Duyarlı sütun gizleme de yok
  (`d-none d-md` 0 hit): 6 sütunlu Gider tablosu yatay kayıyor ve **en işe yaramaz sütun
  (`#`, monospace belge no) en solda, en çok yeri kaplayarak** duruyor.
- **D48** Şirket değişimi formu temizlemiyor (`Expenses:826-833`, `Transfers:639-643`) —
  `form.payment_from` eski şirketin hesabında kalıyor, `payCurrency` yeni şirketin
  tabanına düşüyor, `isCrossCurrency` operatörün altında değişiyor.

---

## 6 · Çürütülen iddialar — kayıt için

Bu üçü denetim turundan "P0" olarak çıktı, başkanın çürütme turunda **düştü**. Bir daha
gündeme gelmesin diye kaydediliyorlar.

- **ÇÜRÜTÜLDÜ · "`frameless` prop'u doğrulama mesajlarını yutuyor."** İddia:
  `SalesOrderFormModern.vue:1018`'in bespoke `frameless` prop'u `actionError` bölgesini
  bastırıyor, dolayısıyla müşterisiz Submit'e basınca hiçbir şey görünmüyor.
  **Yanlış.** `components/form/FormPage.vue:95` — `frameless` dalı `actionError`
  alert'ini **çiziyor**:
  `<div v-if="frameless" class="form-page-frameless"><div v-if="actionError" class="alert alert-danger mb-3">`.
  Doğrulama mesajları görünüyor.
- **ÇÜRÜTÜLDÜ · "Modern, Klasik'in yetki kapılarını atlıyor (`can.save`/`can.submit`)."**
  İddia: Modern iki yazma aksiyonunu yalnız `editable` ile kapıladığı için okuma-yetkili
  kullanıcı Kaydet/Gönder görüyor. **Yanlış** — `useDocumentForm.js:299` `save: editable.value`,
  yani `can.save` ile `editable` **aynı ifade**. Modern ile Klasik arasında yetki farkı yok.
  Gerçek bulgu bundan daha kötü ve §3'te duruyor: `can.*` **hiçbir** ekranda yetki
  taşımıyor. Bulgu düşürülmedi, taşındı ve genişletildi (ADR-402).
- **İNDİRİLDİ (P0 → gözlem) · "Modern tek sütun olduğu için katip yavaşlıyor."**
  Kodda kanıtı yok. Yerinde ölçüm olmadan yerleşim tercihine dair hiçbir iddia bu
  dokümana P0 olarak giremez. Tasarım turunun §8 başarı ölçütü bunu ölçülebilir hâle
  getiriyor.

---

## 7 · Zafar'ın kararı gereken maddeler

1. **SO Modern: düzeltilsin mi, terk mi edilsin?** Kurulun önerisi düzeltmek (ADR-408) —
   tasarım doğru, borç dört maddede toplanmış ve hepsi Klasik'ten taşınacak kod. Ama iki
   varyantı taşımanın maliyeti gerçek (7 kiracıya 66 KB ölü kod) ve karar sizin.
2. **SI Modern dalı: düzeltilip merge mi, yoksa `main`'de yeniden mi?**
   `fix/si-custom-boxes` P0-SI-1 ile ölü; devir notu `make test-bench`'in de
   koşulamadığını kaydediyor. Kurul: **önce P0-SI-1 + P0-SI-2 düzeltilsin, uç bağlamasını
   doğru sebeple kırmızı gören bir test yazılsın, sonra merge, sonra `test-bench`.**
3. **Gider ekranı nakit esaslı mı kalacak?** Bugün ödenmemiş gider (tedarikçiye borç)
   kaydedilemiyor (D27). Kasıtlıysa ekranda söylenmeli; değilse ayrı bir iş paketi.
4. **Gidere fiş eki gelecek mi?** Onay kuyruğu var, onaylayıcının bakacağı belge yok (D25).
5. **KDV/QQS satış faturasında ne zaman görünür olacak?** P0-SI-3 bugün ekranın
   gösterdiği sayı ile deftere yazılan sayıyı ayırıyor; kurul bunu tasarım turunun
   kapsamına aldı ama vergi şablonu seçiminin ürün kararı olduğunu not ediyor.

---

## 8 · Doğrulanan ve geçen — tekrar sorgulanmasın

Kayıt için. Bunlar dört denetçi tarafından ayrı ayrı kontrol edildi ve **doğru** bulundu.

**Dört ekranın tamamında:** Frappe Desk bağlantısı **0** (`/app/` 0 hit, `window.open`
0 hit) · çıplak `<input type="date">` **0**, her tarih `DateInput` + `formatDate`/`formatDateTime`
· elle `table-striped` **0** · şirket kapsamı istemcide ve sunucuda gerçek ve eksiksiz
(`_require_company` + `_assert_company_scope` her mutasyon ucunda; **kiracı izolasyon
açığı bulunamadı**) · para hücreleri `text-end font-monospace`, tutar kırpılmıyor.

**Satış Siparişi Modern:** `≈` satırının mekaniği doğru — kur yoksa `null` döner ve
**hiçbir şey çizilmez** (`:405`, `:1541`), tek satır, canlı türetilmiş, sabit kur yok ·
kur yönü `readableRate`/`formatRate` üzerinden, elle ters çevirme yok, saklama ERPNext
yönünde · `btn-primary` sayısı **1** · renk hiçbir yerde tek başına anlam taşımıyor
(borç çipi, rezervasyon rozeti, ilerleme çubukları, adım çubukları — hepsi metinle
çiftlenmiş, dekoratif noktalar `aria-hidden`) · `t()` kapsamı tam (şablonda yalnız `·` ve
`—` düz metin) · iyimser kilitleme `closeSalesOrder`'da `modified` gönderiyor · yıkıcı
kapatma `useConfirm` + `danger: true` ile onaylı · ürün değişiminde boyut alanları
temizleniyor (`:619-631`) · 24 import'un 24'ü kullanılıyor.

**Satış Faturası:** `≈` / `base_grand_total` / `base_currency` → **0 hit** — SO'ya özel
istisna **kopyalanmamış** (kural 8 geçti) · tek para girişi `MoneyInput` (`:536-542`),
`type="number"` alanları koli/kg/adet, parasal değil · gönderim onayı iki yolda da var ve
Taslak Kaydet gerçekten ayrı düğme · sunucu toplamları elle hesaplamayı reddediyor,
`doc.save()` `validate()` koşturuyor · kiracı izolasyonu her SI mutatöründe.

**Transfer:** iki bacak dürüst modellenmiş (bir alacak + bir borç, `money.py:3022-3039`)
ve **ikisi de postalanmadan önce ekranda** — iki hesap, iki tutar, iki para, iki canlı
bakiye + özet satırı; dördünün en iyi tasarlanmış parçası · From == To **iki kez**
engelli (UI `optionDisabled` + `canSubmit`, sunucu `money.py:2949-2950`) — bu, dosyalardaki
tek kapının hepsinin ulaşması gereken standartta olanı · aynı para bacakları ayrışamıyor
(`derive()` zorluyor, To input devre dışı, payload atlıyor, sunucu 0,01 toleransla
yeniden kontrol ediyor) · geçmiş kaydı amend ederken `hydrating` + `recent = ["recv","amt"]`
kuru **geçmiş tutarlardan türetiyor**, bugünün CBU'suyla yeniden fiyatlamıyor
(`:405-414`) — iki dosyadaki en özenli state yönetimi.

**Gider:** hesap seçimi iyi kurulmuş — gruplu `Typeahead` (Gider / Varlık / Özkaynak),
hesap numarası ve para birimi seçenekte görünür, klavye-öncelikli hayalet satır girişi,
satır başına para uyuşmazlığı uyarısı (ödeme hesabı seçilmeden ve varlık modunda doğru
şekilde susuyor) · yıkıcı aksiyonlar `confirm({danger:true})` ile kapılı ve sonrasında
listeyi tazeliyor · `SkeletonRows` sütun aritmetiği kullanıldığı yerde doğru · amend
`is_fx_rounding` satırını doğru dışlıyor (sentetik bacak yığılmıyor) · `useEscapeBack`
davranışı iki ekranda birebir aynı.

---

## 9 · Sıradaki adım

Bu kararın uygulama karşılığı **kod değil, bir tasarım turu**. Kurulun ürettiği brief:

> `docs/design/PROMPT_design_satis_ve_para_formlari.md`

Tek birleşik brief, dört ekran — çünkü §3'teki altı sözleşmenin tek oturumda
tasarlanması, tutarlılığın tek garantisi. Çıktı **kod değil tasarım**; uygulama ayrı
onay noktası (CLAUDE.md: "What to work on next comes from Zafar").

**Kanıt uyarısı, CLAUDE.md gereği:** yukarıdaki P0'ların tamamı DB yoluna dokunuyor.
`make check` bunların hiçbiri için kanıt **değildir**; P0-SO-1/2/4, P0-SI-1/2/5,
P0-EXP-1, P0-TRF-1 ve P0-MONEY-1/4 `make test-bench` + canlı bench koşusu ister.
