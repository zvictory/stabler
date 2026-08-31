# Mikas Tender — Tasarım Dili ve Bilgi Mimarisi · Tasarım Kurulu Kararı (2026-09-01)

Talep (Zafar): *"kurul tender intake, RFQ, Quotations formları, detayları ve ilerisi için
claude design'a prompt versin, kurul onayladıktan sonra claude design tasarımları yapsın."*

Zafar'ın kapsam kararları (aynı gün, AskUserQuestion):
**kapsam** = tender modülünün tamamı · **yetki** = akış yeniden kurulabilir (backend
sözleşmeleri, rol kapıları ve 5/2 politikası sabit) · **çıktı** = önce bileşen dili,
sonra ekranlar.

Zafar'ın ek kısıtı (aynı gün, oturum içinde): **"ERPNext'te hiç değişiklik yapmadan
sadece Stabler SPA'da front işlerini yapacağız."** ADR-307 bunu karara bağlıyor.

**Kanıt rejimi.** `decision-review` skill'i, Rule 0: bu belgedeki hiçbir sayı, dosya adı
veya satır numarası hafızadan ya da bir ajan raporundan gelmiyor — hepsi 2026-09-01
oturumunda bir komutun ürettiği çıktıdan. Keşif ajanlarının **dört iddiası** ölçümle
yanlış çıktı; ADR'ler ayrıca bağımsız bir çürütme turundan geçti ve **kendi altı iddiam**
da orada yanlışlandı. Onun ikisi (`tgm-*` ↔ `ds-*` "birebir karşılık", ve "`ds-*`'ta
karşılaştırma tablosu yok") kararı doğrudan değiştirdi. Hepsi §4'ün CORRECTIONS
bloğunda, tek tek.

---

## KARAR ÖZETİ

Bu bir özellik işi değil, bir **dil** işi.

Tender modülünün **çoğu** tasarım sisteminin içinde duruyor — `TenderPage.vue:12`
`class="tender-page stbl-ds"` taşıyor ve onu sarmalayan her ekran kapsama giriyor — ama
ekranların çoğu dilini konuşmuyor: **27 tender `.vue` dosyasının 17'si sıfır `ds-*`.**

**Ve iki ekran kapsamın tamamen dışında.** `RfqPrint.vue` ve `BidPricing.vue`'da
`TenderPage` **0 kez** geçiyor — `.stbl-ds` atası yok, dolayısıyla
`stabler-modernist.css`'in hiçbir kuralı onlara uygulanmıyor (dosya kendi kurallarını
`.stbl-ds` altına kapatıyor, `stabler-modernist.css:13-16`). Onlar için iş "dili konuşmuyor" değil,
"sistem oraya hiç varmıyor".

Kalan 17'nin durumu farklı: onlar sarmalın **içinde**, ama yalnızca "köprü" katmanının
yeniden derisini alıyorlar (`stabler-modernist.css:894-1017`) — yani Tabler görünüyorlar.

Daha kötüsü: ihale girişinin **tek yazarı** olan en yeni form üçüncü bir lehçe icat etmiş.
`TenderMasterDrawer.vue` — `ds-*` **0**, `tgm-*` **46**, 777 satır, `<style scoped>` 658'de
başlıyor → **119 satırlık** blok. (Dosya `components/` altında, yukarıdaki 27'lik kümenin
dışında.)

Ve burada kendi ilk iddiam yanlıştı: "o 15 `tgm-*` sınıfının 9'unun zaten **birebir**
`ds-*` karşılığı vardı" demiştim. **Adları** karşılık buluyor, **değerleri** tutmuyor —
`.tgm-drawer` 720px / z-index 1050, `.ds-drawer` 542px / z-index 41. Bu fark, göçü bir
bul-değiştir işi olmaktan çıkarıp bir uzlaştırma kararına dönüştürüyor (ADR-302).

Önceki kurul (`2026-08-17`) bu göçü ADR-209'da sıraya koymuştu ama **1. adımı yanlış bir
olguya dayanıyor**: "giriş çekmecesi + kanban (zaten `ds-*`)". Kanban öyle
(`TenderCrm.vue`, `ds-*` 107); çekmece değil.

Bu dilimin işi: **kurul kararı + tasarım brief'i.** Kod değişmiyor.

---

## 1 · Envanter (ölçüldü 2026-09-01)

### 1.1 · Tasarım dili benimseme — 27 dosya

`for f in pages/tender/*.vue pages/tender/rfq/*.vue; do grep -o 'ds-[a-z-]*' $f | wc -l; done`

> **Kümenin sınırı.** Bu 27, `pages/tender/` ile `pages/tender/rfq/` altındaki dosyalardır.
> `TenderMasterDrawer.vue` **bu kümede değil** — `public/js/components/` altında yaşıyor
> (`ds-*` 0, `tgm-*` 46, 777 satır). Yani "17 dosya sıfır `ds-*`" sayısına çekmece
> **dahil değil**; çekmeceyle birlikte 18 olur. İki sayı iki farklı kümeye ait, toplanmaz.

| `ds-*` | Dosya |
|---:|---|
| 107 | `TenderCrm.vue` |
| 79 | `OperationsDesk.vue` |
| 64 | `TenderFunnel.vue` |
| 43 | `DirectorBoard.vue` |
| 34 | `TenderFlow.vue` |
| 27 | `TenderOverview.vue` |
| 4 | `TenderPage.vue` *(sarmalayıcı)* |
| 3 | `TenderNav.vue` |
| 1 | `RfqList.vue`, `MyTenders.vue` |
| **0** | `BidPricing` · `DeclarantQueue` · `LogistBoard` · `PoControlBoard` · `RfqDetail` · `RfqForm` · `RfqPrint` · `SourcingWorkspace` · `TenderCrmWrapper` · `TenderDocumentChain` · `TenderDocuments` · `TenderDocumentsPanel` · `TenderExecutionFlow` · `TenderExecutiveKpis` · `TenderIntake` · `TenderTrendChart` · `TenderWorkspaceTabs` |

**10 dosya dili konuşuyor, 17'si konuşmuyor.** Konuşanların ikisi (`RfqList`, `MyTenders`)
tek sınıflık, yani anlamlı benimseme **8 dosyada**.

### 1.2 · Üçüncü lehçe

`TenderMasterDrawer.vue`: `ds-*` **0**, `tgm-*` **46 kullanım / 15 farklı sınıf**.
`<style scoped>` 658. satırda başlıyor, dosya 777 satır → **119 satırlık blok**, içinde
`tgm-*` olmayan kurallar da var (`.modal-backdrop`, `.whitespace-nowrap`).

> **Bu tablonun ilk hâli "birebir karşılık" diyordu ve yanlıştı.** Çürütme turu
> kuralları yan yana okudu: adlar eşleşiyor, **değerler eşleşmiyor**. Ad eşleşmesini
> "bul-değiştir yeter" diye okumak çekmeceyi görünür biçimde bozardı.

| `tgm-*` | En yakın `ds-*` | Ölçülen fark |
|---|---|---|
| `tgm-drawer` | `ds-drawer` (`css:648`) | **720px → 542px**, **z-index 1050 → 41**. `data-size="lg"` 760px veriyor (`css:655`); z-index Bootstrap'ın 1040+ yığın bandının **altına** düşüyor |
| `tgm-drawer-body` | `ds-drawer-body` (`css:668`) | pratikte aynı |
| `tgm-drawer-header` | `ds-drawer-head` (`css:657`) | dolgu ve hizalama farklı |
| `tgm-drawer-title` | `ds-drawer-title` (`css:662`) | **18px → 22px**, üstüne 6px margin |
| `tgm-drawer-footer` | `ds-drawer-foot` (`css:669`) | dolgu farklı |
| `tgm-kicker` | `ds-drawer-kicker` (`css:661`) | 10.5px/uppercase/700 → 11px/vurgu rengi, caps ve bold yok |
| `tgm-section` | `ds-form-section` (`css:568`) | yalnız alt çizgi → 1px çerçeve + 14px alt boşluk + arka plan; **bitişik yığın → ayrık kartlar** |
| `tgm-sec-head` | `ds-form-section-head` | tipografi farklı |
| `tgm-sec-body` | `ds-form-body` | dolgu farklı |
| `tgm-file-chip` / `-list` / `-name` | **yok** | gerçek boşluk |
| `tgm-sec-num` | **yok** | numaralı bölüm başlığı |
| `tgm-drawer-dialog` / `-content` | **karşılığı olmamalı** | `ds-drawer` tek bir flex `<aside>`; bu ikisi **silinir**, yeniden adlandırılmaz |

### 1.3 · Rotalar ve rol kapıları

`grep -cE 'path: "/tender' router.js` → **18**, bunun **2'si yönlendirme** → **16 gerçek ekran**.

`TenderNav.vue`'daki kapılar (`v-if` ifadeleri, kaynaktan okundu):

| Rota | Kapı |
|---|---|
| `/tender/portfolio` | `can('director')` |
| `/tender/flow` | `can('director')` |
| `/tender/crm` | `can('director') \|\| can('sourcing')` |
| `/tender/my-tenders` · `/rfq` · `/sourcing` · `/po-control` | `can('sourcing')` |
| `/tender/customs` | `can('declarant')` |
| `/tender/logistics` | `can('logist')` |
| `/tender/desk` | `session.tenderViews.length > 0` (dört rolden herhangi biri) |
| `/tender/overview` · `/tender/board` | kapısız — tender'ı olan herkes |

> `/tender/board` (`router.js:295`) `SalesOrderBoard` bileşenini çiziyor — `pages/sales`
> altında, tender dosyası değil. "16 tender ekranı" sayısı onu içeriyor; envanterdeki
> 27 `.vue` içermiyor. Ayrıca `BidPricing.vue` ve `TenderIntake.vue`'nun hiç rotası yok.
| `/tender/documents` | `Sidebar.vue:85`, `canAccessModule("tender")` — nav'da değil, kenar çubuğunda |

### 1.4 · Çeviri uzaması (kendi ölçümüm, CSV'lerden)

| Anahtar | en | ru | uz | tr | en katı |
|---|---:|---:|---:|---:|---:|
| `RFQs` | 4 | 11 | **15** | 7 | **3.75×** |
| `My tenders` | 10 | 11 | 18 | 11 | 1.80× |
| `Approve` | 7 | 9 | 10 | 6 | 1.43× |
| `Sourcing workspace` | 18 | 23 | 17 | 21 | 1.28× |

`RFQs` → uz `Narx so'rovlari` (15), ru `Запросы цен` (11). **Sabit genişlikli nav/rozet/
düğme tasarlanamaz.**

---

## 2 · Doğrulanmış kusurlar

Her biri `dosya:satır` ile, kendi komutumla. Numaralı 18 madde var; **15 numara
çürütüldü ve üstü çizili bırakıldı** — silmiyorum, çünkü yanlış çıkan bir iddianın izi,
onun düzeltildiğinin tek kanıtı.

**Tasarım dili**
1. 27 ekranın 17'si sıfır `ds-*` (§1.1).
2. Üçüncü lehçe `tgm-*`, %60'ı gereksiz (§1.2).

**Yerleşim / erişilebilirlik**
3. `SourcingWorkspace.vue` karşılaştırma tablosu 9 sütun + satır başına 4 aksiyon düğmesi;
   dosyada `table-responsive` **0 kez** geçiyor (`grep -c`). Dizüstünde kontrolsüz taşıyor.
4. `LandedChargesEditor.vue:132` modalında `role="dialog"` / `aria-modal` /
   `aria-labelledby` yok; arka plan satır içi `style="background: rgba(0,0,0,0.5)"`.
   Yanındaki `QuotationEntryDrawer` doğru işaretli — aynı ekranda iki farklı standart.
5. `RfqList.vue` satır tıklaması yalnız `style="cursor:pointer"`; `tabindex` /
   `@keyup.enter` / `role="button"` yok. Klavyeyle erişilemiyor.
6. Etiket/girdi çiftleri `for`/`id` ile bağlı değil.

**Durumlar**
7. `RfqList.vue`: hata ile boş **aynı** görünüyor — catch yalnız toast atıp `rows`'u
   boşaltıyor, ardından gerçek boş listenin `EmptyState`'i çiziliyor.
8. `SourcingWorkspace.vue`: `decisionLoading` tanımlı ama şablonda hiç okunmuyor; ödül
   panelinin yükleme göstergesi yok.
9. `QuotationEntryDrawer.vue`: ilk çekişte yükleme bayrağı yok — çekmece boş formla açılıp
   alanlar sessizce doluyor.
10. Aynı dosyada iki yükleme kalıbı: `SourcingWorkspace.vue:576` `SkeletonRows`,
    `:472` düz "Loading RFQs…" metni.

**Tutarlılık**
11. `SourcingWorkspace.vue`: kazanan seçimi çıplak `<select>`, iki satır aşağısı teknik
    değerlendirme paylaşılan `Select` bileşeni.
12. `TenderIntake.vue:249` `volume` çıplak `<input type="number">` — `.claude/rules/10-frontend.md`
    #3'ün ihlali.
13. `QuotationEntryDrawer.vue:302` satır toplamı `.toLocaleString()` — `formatMoney` ve
    para birimi ondalık kuralı atlanıyor.

**Akış / bilgi mimarisi**
14. `PoControlBoard.vue`'dan `tender-sourcing` veya `tender-rfq-*`'ye **0** bağlantı
    (`grep -c` → 0). Oradaki kullanıcı URL yazmak zorunda.
15. ~~`RfqList.vue`'ya akış içinden bağlantı yok.~~ **GERİ ÇEKİLDİ** — `TenderNav.vue:56`
    `<router-link to="/tender/rfq">` her `TenderPage` ekranında çiziliyor, ve nav akışın
    parçası. İddia çürütme turunda düştü.
16. `TenderIntake.vue` zincirde değil — yalnız `PoControlBoard.vue:23,368`'de gömülü, yani
    **kazanım sonrası** bir ekranın içinde.

**Regresyon ağı**
17. Kapsamdaki 5 tender spec'inin (`sourcingWorkspace`, `sourcingAwardPanel`, `rfqDetail`,
    `rfqForm`, `quotationEntryDrawer`) **hiçbiri** bileşen mount etmiyor (`mount(` /
    `@vue/test-utils` sayımı: hepsinde 0). Repo'nun 76 spec'inin 17'si mount ediyor, yani
    kalıp mevcut ama bu ekranlarda kullanılmamış.
    **Kısmî istisna** (çürütme turu buldu): `sourcingAwardPanel.spec.js` (182 satır)
    şablondan çıkardığı `v-if` ifadelerini **çalıştırıyor**, yani ödül panelinin dallanma
    mantığı yeniden kurulursa kırılır. Geri kalanı için iddia ayakta: tasarımı bozan bir
    değişiklik tek bir testi bile kırmaz.

18. **İki ekran tasarım sisteminin kapsamı dışında.** `RfqPrint.vue` ve `BidPricing.vue`'da
    `TenderPage` 0 kez geçiyor → `.stbl-ds` atası yok → `stabler-modernist.css`'in hiçbir
    kuralı uygulanmıyor.

---

## 3 · Kararlar (ADR)

### ADR-301 — ADR-209'un 1. adımı düzeltilir; göç çekmeceden başlar
Önceki sıra "(1) giriş çekmecesi + kanban (zaten `ds-*`)" diyor. Kanban için doğru
(`TenderCrm.vue` 107), çekmece için yanlış (0). Çekmece hem en büyük tek borç hem de
ADR-201 gereği ihale girişinin **tek yazarı** — göç oradan başlar.

### ADR-302 — `tgm-*` emekli olur, ama **bul-değiştirle değil**
Yön doğru, ilk gerekçem yanlıştı: 9 sınıfın "birebir" karşılığı yok, **yakın** karşılığı
var ve değerler farklı (§1.2). Sınıf adlarını değiştirip bırakmak çekmeceyi 720px'ten
542px'e düşürür ve z-index'i 1050'den 41'e indirerek Bootstrap'ın yığın bandının altına
atar. Göç **kural kural uzlaştırma** işidir:
- `ds-drawer` `data-size="lg"` (760px) ile kullanılır; z-index kararı ayrıca verilir —
  çekmece Bootstrap modallarıyla aynı sayfada yaşıyor.
- `tgm-drawer-dialog` / `-content` **silinir**, yeniden adlandırılmaz: `ds-drawer` tek
  bir flex `<aside>`.
- `tgm-section` → `ds-form-section` görsel bir karar: bitişik yığından ayrık kartlara
  geçiş. Tasarımcı bunu onaylamalı, mühendis sessizce yapmamalı.
- `tgm-file-chip/-list/-name` `ds-*`'a **yeni bileşen** olarak eklenir (belge merkezinde
  de gerekiyor); `tgm-sec-num` için `ds-form-section` numaralandırma kazanır.

### ADR-303 — Sorun kelime dağarcığı değil, **benimseme**
İlk hâli "`ds-*`'ta bu üç bileşen yok" diyordu; çürütme turu yanlışladı ve ölçüm onu
doğruladı: `ds-table` **5**, `ds-panel` **7**, `ds-kanban` **1**, `ds-row` **2**,
`ds-band` **1** dosyada kullanılıyor. Karşılaştırma tablosu ise `class="table card-table"`
(`SourcingWorkspace.vue:561,701`) — yani çıplak Bootstrap. Kuyruk panoları da öyle.

Dolayısıyla karar tersine döner: **önce mevcut `ds-*` kullanılır.** Yeni bileşen ancak
tasarımcı somut bir yetersizlik gösterirse eklenir, ve o zaman gerekçesi "bu ekranda yoktu"
değil, "`ds-table` şunu yapamıyor" olmalıdır. Bugün bilinen tek gerçek boşluk dosya-eki
çipi (ADR-302).

### ADR-304 — Akış onarılır (üç değil, **iki** kopukluk)
Zafar tam yetki verdi. Doğrulanan iki kopukluk kapatılır: PO panosundan sourcing/RFQ'ya
bağlantı (kusur 14) ve `TenderIntake`'in zincirdeki yeri (kusur 16) — ya bağlanır ya
kaldırılır, ama öksüz kalmaz. Üçüncü iddia (RFQ listesi ulaşılamaz) çürütme turunda
düştü; nav zaten bağlıyor.

### ADR-305 — Hata durumu boştan ayrılır
Her ekranda üç ayrı durum: yükleniyor (`SkeletonRows`), boş (`EmptyState`), hata (ayrı,
yeniden dene eylemli). `RfqDetail.vue` ve `RfqPrint.vue` bunu bugün doğru yapıyor —
referans onlar, yenisi icat edilmez.

### ADR-306 — Regresyon ağı brief'in teslim şartıdır
Kusur 17 nedeniyle "tasarım uygulandı" iddiası bugün hiçbir testle doğrulanamaz. Brief,
her ekran için **gözlemlenebilir kabul ölçütü** üretmek zorunda (hangi durum hangi
elemanı gösterir), ve uygulama dilimi bunları mount eden testlere çevirir. Kalıp repoda
zaten var (76 spec'in 17'si).

### ADR-307 — ERPNext'e dokunulmaz; **bu iş için** yeni alan gerekmiyor
Zafar'ın kısıtı karara bağlanır. Ölçüldü: bugün main'e giren hiçbir değişiklik `stabler/`
ve `.github/` dışına çıkmadı, hiçbir doctype JSON'u değişmedi.

**Ama "yeni alan asla" bir politika olarak yazılmaz** — çürütme turu haklı olarak işaret
etti: bu repo `v68`, `v83` gibi patch'lerle ERPNext doctype'larına Custom Field ekliyor,
`Supplier Quotation.custom_rfq` bunlardan biri ve ADR-208'in dayandığı şey. Doğru ifade:
*bu iş için yeni alan gerekmiyor ve eklenmeyecek.*

**Ve kısıt gerçekten karşılanabiliyor.** CRM'de "RFQ gönderildi mi" göstermek yeni alan
istemiyor: `crm_board` (`tender.py:2688`) RFQ'ları mevcut `custom_crm_deal` üzerinden
sayabilir — `sourcing.list_rfqs` (`sourcing.py:469,498`) zaten tam bunu yapıyor. Değişiklik
`stabler/api` içinde kalır, sıfır DB, sıfır ERPNext.

**Dürüst sınır:** saf-ön-yüz kısıtının bir yeri kırılıyor. CRM'de "RFQ gönderildi mi"
göstermek için sunucunun o sayıyı **göndermesi** gerekiyor; `grep -c "rfq"
stabler/api/tender.py` → **0**. Bu birkaç satır `stabler/api` içinde kalır — ERPNext
değil, kendi uygulamamız, sıfır DB değişikliği. Tasarım bunu bir ekran olarak çizer;
uygulanıp uygulanmayacağı Zafar'ın kararı.

---

## 4 · Çıktı sözleşmesi

```
DECISIONS
  1. Göç çekmeceden başlar — ADR-209'un "zaten ds-*" premisi ölçümle yanlış (ds-* 0 / tgm-* 46).
  2. tgm-* emekli olur, ama kural kural uzlaştırmayla — adlar eşleşiyor, DEĞERLER eşleşmiyor.
  3. Sorun kelime dağarcığı değil benimseme: ds-table/ds-panel/ds-kanban zaten var, ekranlar
     çıplak Bootstrap kullanıyor. Yeni bileşen ancak kanıtlanmış boşluk için.
  4. Akıştaki İKİ ölçülmüş kopukluk kapatılır (üçüncüsü çürütüldü).
  5. Hata/boş/yükleniyor üç ayrı EKRAN ELEMANI; toast bunu karşılamaz.
  6. Brief her ekran için gözlemlenebilir kabul ölçütü üretir; uygulama onları mount eden
     testlere çevirir.
  7. ERPNext'e dokunulmaz; bu iş için yeni alan gerekmiyor ve eklenmeyecek.
  8. Tasarım SENTETİK veriyle çalışır — gerçek tender kaydı yok (Zafar, 2026-09-01).
     Kaynak serbest değil: `stabler/maintenance/seed_tender_demo.py`. Uydurma sayı yerine
     testle korunan, bilerek "güzel olmayan" bir küme.

ACCEPTANCE
  Her ölçüt "hiçbir şey yapmayan bir değişiklikle" sağlanamayacak biçimde YAZILDI —
  çürütme turu ilk hâlinin dördünü tam bu şekilde kırdı.

  1. TenderMasterDrawer'da `tgm-` sayısı 46 → 0  VE  `ds-drawer` + `ds-form-section`
     sayısı > 0  VE  çekmece `data-size="lg"` taşıyor.
     (Yalnız sınıfları silmek 1. koşulu sağlar, 2. ve 3.'yü sağlamaz — stilsiz çekmece
     bu kapıdan geçemez.)
  2. Sıfır `ds-*` taşıyan tender dosyası 17 → 0  VE  `RfqPrint.vue` ile `BidPricing.vue`
     bir `.stbl-ds` atası kazanıyor (bugün ikisinde de `TenderPage` 0).
  3. `SourcingWorkspace`'te `table-responsive` 0 → ≥1  VE  1280px genişlikte 9 sütunlu
     tablonun taşmadığını gösteren bir mount testi var.
  4. `PoControlBoard`'dan `tender-sourcing` veya `tender-rfq-*` bağlantı sayısı 0 → ≥1.
  5. `RfqList`'te başarısız yükleme, boş listeden FARKLI bir eleman gösteriyor — bir mount
     testi başarısız çağrıyı taklit edip iki durumun farklı render ettiğini iddia ediyor.
     (Bugün de bir toast var; toast bu ölçütü geçmez.)
  6. Kapsamdaki 5 tender spec'inde `@vue/test-utils` kullanan spec sayısı 0 → ekran başına ≥1.
  7. Değişen dosyaların hiçbiri `stabler/` dışında değil  VE  hiçbir doctype JSON'u
     değişmedi  VE  yeni patch dosyası yok.
     (Bu bugün doğru; ölçüt olarak duruyor çünkü İHLAL EDİLEBİLİR — bir Custom Field
     patch'i eklenirse kırmızı verir.)
  8. Teslim edilen her ekranda görünen her lot no, kurum adı, tedarikçi ve tutar
     `seed_tender_demo.py`'nin sabitlerinde BULUNABİLİYOR  VE  her ekran görseli
     "sentetik" işaretini taşıyor  VE  kümenin dürüstlük durumlarından en az üçü
     çiziliyor: politika boşluğu (6 lot geçemiyor), "ölçülemiyor" satırı (2 damgasız lot),
     ve geçmiş son tarih (-1 gün).
     (Sadece "güzel" bir ekran çizmek bu ölçütü geçemez — kümenin çirkin tarafı
     zorunlu.)

NOT DECIDED
  · ~~Veri ön koşulu.~~ **KARARA BAĞLANDI** (Zafar, 2026-09-01): gerçek kayıt yok,
    sentetik devam. Kaynak `seed_tender_demo.py`; brief §7.0 tek dala indirildi.
    Betiğin kendisi PROD'da çalıştırılmıyor — canlı siteye yazıyor, bu işin kapsamı
    değil ve ayrı onay ister. Tasarıma lazım olan verinin şekli, sabitlerde duruyor.
  · `ds-drawer`'ın z-index'i. 41, Bootstrap modal bandının (1040+) altında. Çekmece
    `LandedChargesEditor` gibi Bootstrap modallarıyla aynı sayfada yaşıyor. Bu bir tasarım
    kararı değil mimari karar; tasarımcı sorunu göstersin, çözümü mühendislik versin.
  · ADR-307'nin sınırı. CRM'de RFQ görünürlüğü birkaç satır `stabler/api` gerektiriyor
    (yeni alan değil — mevcut `custom_crm_deal` üzerinden sayım). Tasarım çizilir;
    uygulanması Zafar'ın kararı.

WOULD CHANGE MY MIND
  · ADR-302: `ds-drawer`'ın 760px + z-index uzlaştırmasıyla bile çekmecenin ihtiyacını
    karşılayamadığı gösterilirse — o zaman `tgm-*` bir boşluğun cevabıydı.
  · ADR-301: çekmecenin göçünün sourcing üçlüsünden daha pahalı olduğu gösterilirse,
    sıra değişir. Çekmece bugün EN UCUZ hedef: çalışan bir `ds-drawer` örneği kendi
    ana dosyasında duruyor (`TenderCrm.vue:578-721`).
  · ADR-303: tasarımcı `ds-table`'ın çok para birimli karşılaştırmayı yapamadığını somut
    olarak gösterirse, yeni bileşen gerekçelenir.

CORRECTIONS
  Kendi hatalarım:
  · Zafar'a "19 rota" dedim, ölçmemiştim. Gerçek: 18 girdi, 2'si yönlendirme → 16 ekran.
    Ayrıca `/tender/board` bir tender bileşeni bile değil (`SalesOrderBoard`, `pages/sales`).
  · "tgm-* ↔ ds-* birebir karşılık" dedim. Yanlış: adlar eşleşiyor, değerler eşleşmiyor
    (542px/z-41 vs 720px/z-1050). Bu ifade yıkıcı bir bul-değiştire izin veriyordu.
  · "ds-*'ta karşılaştırma tablosu/panel/kuyruk yok" dedim. Yanlış: ds-table 5, ds-panel 7,
    ds-kanban 1 dosyada kullanılıyor. Sorun benimseme.
  · "RFQ listesine akış içinden giriş yok" dedim. Yanlış: `TenderNav.vue:56` bağlıyor.
  · "tgm CSS 115 satır, 663'ten" dedim. Gerçek: blok 658-777 (119 satır), tgm olmayan
    kurallar dahil.
  · "Modül tasarım sisteminin içinde duruyor" dedim. `RfqPrint` ve `BidPricing` için yanlış.

  Keşif ajanlarının hataları:
  · "unassigned tablosunda table-responsive var" — dosyada 0 kez geçiyor.
  · "hiçbir spec bileşen mount etmiyor" — 76'nın 17'si mount ediyor; kapsamdaki 5 için doğru.
  · "19 dosyada sıfır ds-*" — kendi sayımım 17.
  · RU/UZ uzaması "2.75×" — kendi ölçümüm 3.75× (`RFQs` → uz `Narx so'rovlari`).
```

---

## 5 · Kapsam dışı

- **Kod uygulaması.** Bu dilim yalnız iki doküman üretir.
- **ADR-210 (Tender Master emekliliği), ADR-211 (garanti otomasyonu)** — önceki kurul
  bilerek erteledi; bu belge onları açmıyor.
- **Karanlık mod.** Repoda yok (`stabler.html:3` sabit `data-bs-theme="light"`), icat edilmiyor.
- **`has_min_5` anahtarının yeniden adlandırılması.** Bir JSON yanıt anahtarı, DB alanı
  değil (`grep -rn has_min_5 stabler/stabler/doctype/` → 0). Ayrı iş.
