# SO / SI Modern kapsam kararı — Klasik kalıcı

**Tarih:** 2026-08-21 · **Karar veren:** Zafar
**Yerine geçtiği belge:** `docs/plans/2026-08-18-satis-ve-para-formlari-tasarim-kurulu-karari.md`, **ADR-408**

---

## Karar

> **Klasik kalsın, Modern sadece msa ve mikas'ta.**

Bu, Satış Siparişi için geçerlidir. Satış Faturası ölçüldüğünde aynı daraltmanın
uygulanamayacağı görüldü ve Zafar aynı gün **A**'yı seçti: **SI Modern sekiz kiracıda
kalır.** Asimetri kasıtlıdır; gerekçesi aşağıda.

ADR-408'in bitişi — *"tek kiracıda açılır; iki hafta gözlem; sonra varsayılan olur ve
Klasik silinir"* — **geçersizdir**. Klasik silinmeyecek; kalan altı kiracının kalıcı
formu odur.

Bu belge yazılmadan önce ADR-408 hâlâ "Klasik silinir" diyordu. Anayasa *"on conflict,
this file wins"* kuralını taşıdığı için, bayat bir karar belgesi doğru kararın önüne
geçer — `make test`'in test sayısı vakasıyla aynı sınıf. ADR-408'e bu belgeye işaret
eden bir üst not düşüldü.

---

## Bugünkü ölçülen durum — karar bir tarif değil, bir hedef

İkisi de canlı olarak ölçüldü, belgeden okunmadı.

| | Bayrak | Bugün | Kararın gerektirdiği |
|---|---|---|---|
| **SO Modern** | `Stabler Company Modules.enable_modern_sales_order` | **8 kiracının hepsinde, her şirkette KAPALI** | msa + mikas'ta AÇIK |
| **SI Modern** | *yok* | **8 kiracının hepsinde, bayraksız AÇIK** | değişiklik yok — sekiz kiracıda kalır (A) |

SO'da Modern hiç açılmamış: karar bugünkü durumu kalıcılaştırıyor, üstüne iki kiracıda
açmayı ekliyor — ve o açma altı P0'a bağlı. SI'da Modern zaten her yerde ve bayraksız;
karar A bunu olduğu gibi bırakıyor, yani SI tarafında yazılacak kod yok.

---

## SO — karar uygulanabilir

`SalesOrderForm.vue` ince bir varyant seçici: `session.modules?.modern_sales_order`
okuyup Klasik veya Modern'i render ediyor. Bayrak sekiz kiracıda kapalı olduğu için
**Klasik zaten herkesin gördüğü form.** Karar, bugünkü durumu kalıcılaştırıyor ve
üstüne iki kiracıda Modern'i açmayı ekliyor.

### Açmadan önce kapanması gerekenler

ADR-408 bayrağı açmayı altı P0'a bağlamıştı; hiçbiri kapanmadı. Plan §5:
`P0-SO-1` … `P0-SO-6`, artı ADR-401, ADR-405 ve Anlaşma seçicisinin geri gelmesi.
**Bunlar kapanmadan msa ve mikas'ta Modern açılmaz.**

### Kararın yarattığı yeni bedel ve karşılığı

ADR-408 iki varyantı taşımayı **geçici** sayıyordu. Kalıcı olunca bedel de kalıcı ve
simetrik oluyor: her iki varyant da statik import ediliyor
(`SalesOrderForm.vue:17-18`), yani altı kiracı hiç render etmeyeceği Modern'i
(1 879 satır) indiriyor; msa ve mikas da hiç render etmeyeceği Klasik'i (1 413 satır).

Karşılığı: varyantlar `defineAsyncComponent` ile talep üzerine yüklenir, her kiracı
yalnız kendi varyantını indirir. Bu, `perf/so-variant-lazy-load` dalında yürüyor.
Rota katmanı değişmiyor — `router.js`'in 205 rotası statik `component:` taşımaya
devam ediyor.

### Klasik kalıcı olduğu için kapatılan kusur

ADR-408 *"bayrak açılmasa bile, çünkü Klasik'te de bug"* diyerek bir portu
listelemişti: `resolveRate`'in fiyat listesi → işlem parası çevrimi. Klasik
`res.currency`'yi hiç okumuyordu, yani UZS liste fiyatı USD siparişe ham yazılıyordu —
dövizli her siparişte ~12 000 katı, müşteri lehine.

**Kapatıldı** (`fix/so-classic-price-list-currency`, `8a02988` ile main'de). Çevrim
`composables/fx.js`'te `priceListRateForOrder` olarak tek yerde yaşıyor ve her iki
form da onu çağırıyor. Mutasyonla doğrulandı: çevrimi kaldırınca test `1 210 185`
yerine `100` bekliyor — kusurun kendi sayısı.

Klasik kalıcı olduğu için bu port bir borç kapatma değil, **kalan altı kiracının canlı
davranışının düzeltilmesiydi**.

---

## SI — karar: **Modern sekiz kiracıda kalır** (A)

İlk talimat SO ve SI'yı birlikte msa+mikas'a daraltıyordu. Ölçüm bunun SI'da
uygulanamaz olduğunu gösterdi ve Zafar 2026-08-21'de **A** seçeneğini seçti:
**SI Modern sekiz kiracıda kalsın.** Bayrak yazılmayacak.

### Neden SO'dan farklı — bu asimetri kasıtlıdır, tutarsızlık değildir

Bunu yazmamın sebebi şu: gerekçesi kayıtlı olmayan bir asimetri, ileride birinin
onu "düzeltip" SI'ya bayrak takmasını davet eder. Fark, tercihte değil, **yapıda**:

| | SO | SI |
|---|---|---|
| Kaç gerçek varyant var? | **İki** — `SalesOrderFormClassic.vue` (1 413) ve `SalesOrderFormModern.vue` (1 879), ikisi de tam form | **Bir** |
| Seçici | `SalesOrderForm.vue`, `enable_modern_sales_order` bayrağını okur | yok |
| Bayrağı kapatınca ne olur? | Klasik render edilir — çalışan bir form | **Doğrudan fatura oluşturulamaz** |

`SalesInvoiceFormModern.vue` bir varyant değil, tek yol. `router.js:344` ve `:351`,
`invoices/new` ve `invoices/:name/edit` rotalarının ikisini de ona bağlıyor ve hiçbir
bayrak yok. Eski `SalesInvoiceForm.vue` ona alternatif değil:

- `create_direct_sales_invoice` ve `update_sales_invoice` çağrılarının **ikisi de yok**;
  yalnızca `sales_invoice_detail`, `submit`, `cancel`, `amend`, `delete`,
  `create_sales_return` var.
- Kendi yorumu satırların *"genuinely read-only in Stabler as invoices are derived
  directly from Sales Orders"* olduğunu söylüyor (`:281`).
- Rotası yalnız `invoices/:name` — görüntüleme.

O ekran, **siparişten türeyen** faturaları görüntüleyip yaşam döngüsünü yöneten bir
ekran. SI'da Modern'i kapatmak bir kapsam daraltma değil, altı kiracıdan doğrudan
fatura oluşturmayı **geri çekmek** olurdu.

Kısaca: SO'da bayrak iki çalışan form arasında seçim yapar; SI'da bayrak, olmayan bir
forma geçiş yapardı.

### Kararın bedeli: SI Modern'in P0'ları artık dal borcu değil

A kararı `SalesInvoiceFormModern.vue`'yi **sekiz kiracının kalıcı ve tek** doğrudan
fatura yolu olarak sabitliyor. Plan §5'teki `P0-SI-*` maddeleri bu yüzden "terk
edilebilecek bir daldaki kusurlar" olmaktan çıkıp **sekiz kiracıda canlı kusurlar**
hâline geldi. Karar A ucuz olan seçenekti; bedeli bu.

### Planın bayat çıkan maddesi — §7-2

Plan §7-2 hâlâ *"`fix/si-custom-boxes` P0-SI-1 ile ölü; önce P0-SI-1 + P0-SI-2
düzeltilsin, sonra merge"* diyor. **Bu geçersiz, ölçüldü:**

- `git merge-base --is-ancestor fix/si-custom-boxes main` → dal **zaten main'de**
  (`57e512a`, *"the invoice screen lost the edits it was asked to submit, and rewrote
  the rates of any draft merely opened"*).
- P0-SI-1 main'de **kapalı**: `SalesInvoiceFormModern.vue:147-149` `detailApi`,
  `createApi`, `updateApi`'yi doğru sırada taşıyor.
- P0-SI-5 aynı commit'te kapanmış görünüyor (mesajın ikinci yarısı).
- P0-SI-4'ün "işlem parası session'a sabitlenmiş" yarısı da kapanmış: `:57` artık
  `model.value?.currency`'yi önce okuyor, ve toplam para birimiyle etiketli (`:382`).

Yani §7-2 Zafar'dan bir karar beklemiyor; iş yapılmış, belge geride kalmış.

### Karar A'nın açtığı ilk iş

P0-SI-4'ün **diğer** yarısı açık ve bugün SO formlarında kapatılan kusurun tıpatıp
aynısı: `:250` `row.rate = Number(res.price_list_rate)` yapıyor, `res.currency`'yi hiç
okumuyor — SO formlarının aksine `res.unresolved`'ı bile kontrol etmiyor. Bir para
biriminde kotalanmış fiyat listesi, başka bir para biriminde düzenlenen faturaya ham
iniyor; UZS/USD büyüklüklerinde ~12 000 kat.

Düzeltmesi hazır: `composables/fx.js` → `priceListRateForOrder`, bugün
`fix/so-classic-price-list-currency` ile indi, mutasyonla doğrulandı. İkinci bir kopya
yazılmayacak. Dal: `fix/si-modern-price-list-currency`.

### Karardan etkilenmeyen, hâlâ Zafar'da olan

Plan §7-5: **KDV/QQS satış faturasında ne zaman görünür olacak?** P0-SI-3 ekranın
gösterdiği NET ile deftere yazılan KDV'li grand total'ı ayırıyor. Kurul bunu tasarım
turunun kapsamına aldı ama vergi şablonu seçiminin bir ürün kararı olduğunu not etti.
Karar A bunu kapatmıyor — aksine, ekran kalıcı olduğu için daha da gerekli kılıyor.

## Değişmeyenler

- ADR-408'in **Klasik → Modern** taşıma listesi (`kur MoneyInput`, `loadingDoc`,
  Anlaşma seçici, `isFormValid` kapısı) geçerliliğini koruyor. Modern iki kiracıda
  çalışacaksa o dört madde yine gerekli — yalnız artık "silinecek formdan kurtarma"
  değil, "iki kalıcı formdan birini tamamlama".
- Plan §8'deki *"doğrulanan ve geçen"* listesi bu karardan etkilenmiyor.
