# SO / SI Modern kapsam kararı — Klasik kalıcı

**Tarih:** 2026-08-21 · **Karar veren:** Zafar
**Yerine geçtiği belge:** `docs/plans/2026-08-18-satis-ve-para-formlari-tasarim-kurulu-karari.md`, **ADR-408**

---

## Karar

> **Klasik kalsın, Modern sadece msa ve mikas'ta.**

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
| **SI Modern** | *yok* | **8 kiracının hepsinde, bayraksız AÇIK** | msa + mikas dışında KAPALI |

İkisi de kararın söylediği yerde değil — ve **ters yönlerde**. SO'da Modern hiç
açılmamış, SI'da Modern zaten her yerde.

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

## SI — karar bu hâliyle uygulanamaz

**Bu, kararın uygulanmasını bloke eden bulgudur.**

`SalesInvoiceFormModern.vue` bir varyant değil. `router.js:344` ve `:351`,
`invoices/new` ve `invoices/:name/edit` rotalarının **ikisini de** ona bağlıyor ve
**hiçbir bayrak yok**. Yani sekiz kiracının hepsi bugün doğrudan satış faturasını onunla
oluşturuyor ve düzenliyor.

Eski `SalesInvoiceForm.vue` ona alternatif değil:

- `create_direct_sales_invoice` ve `update_sales_invoice` çağrılarının **ikisi de yok**;
  yalnızca `sales_invoice_detail`, `submit`, `cancel`, `amend`, `delete`,
  `create_sales_return` var.
- Kendi yorumu satırların *"genuinely read-only in Stabler as invoices are derived
  directly from Sales Orders"* olduğunu söylüyor (`:281`).
- Rotası yalnız `invoices/:name` — görüntüleme.

O ekran, **siparişten türeyen** faturaları görüntüleyip yaşam döngüsünü yöneten bir
ekran. Doğrudan fatura oluşturan tek yol Modern.

**Sonuç:** "SI Modern sadece msa ve mikas'ta" dendiğinde kalan altı kiracı doğrudan
satış faturası **hiç oluşturamaz** — geri düşecekleri bir Klasik yoktur.

### Zafar'ın cevaplaması gereken

1. **SI Modern sekiz kiracıda kalsın mı?** (SO'dan farklı olduğu kabul edilerek — SO'da
   iki gerçek varyant var, SI'da yok.) En ucuz yol; kararın SO yarısı aynen yürür.
2. **Yoksa altı kiracı doğrudan fatura oluşturmayı gerçekten kaybetsin mi?** O zaman
   bu bir kapsam daraltma değil, bir **özellik geri çekmesi**dir ve kullanıcıya
   söylenmesi gerekir.
3. **Yoksa önce bir Klasik SI yazma formu mu yazılsın?** En pahalı yol; SI Modern'i
   kapatmadan önce yapılması gerekir, tersi değil.

(1) seçilirse bir bayrağa gerek yok. (2) veya (3) seçilirse `Stabler Company Modules`
üzerinde `enable_modern_sales_invoice` alanı, `_MODULE_FIELDS` girdisi ve bir patch
gerekir — SO'nun `enable_modern_sales_order` deseniyle aynı.

Ayrıca plan §7-2 hâlâ açık: `fix/si-custom-boxes` dalı `P0-SI-1` ile ölü. Kurulun
önerisi *"önce P0-SI-1 + P0-SI-2 düzeltilsin, uç bağlamasını doğru sebeple kırmızı gören
bir test yazılsın, sonra merge, sonra `test-bench`"*. Bu karardan bağımsız ve hâlâ
geçerli.

---

## Değişmeyenler

- ADR-408'in **Klasik → Modern** taşıma listesi (`kur MoneyInput`, `loadingDoc`,
  Anlaşma seçici, `isFormValid` kapısı) geçerliliğini koruyor. Modern iki kiracıda
  çalışacaksa o dört madde yine gerekli — yalnız artık "silinecek formdan kurtarma"
  değil, "iki kalıcı formdan birini tamamlama".
- Plan §8'deki *"doğrulanan ve geçen"* listesi bu karardan etkilenmiyor.
