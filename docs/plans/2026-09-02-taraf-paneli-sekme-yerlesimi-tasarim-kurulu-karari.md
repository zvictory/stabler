# Taraf Paneli — RFQs / Quotations Sekme Yerleşimi · Tasarım Kurulu Kararı (2026-09-02)

Talep (Zafar): *"bu tablarin yukarida mi olsun, supplier pane icindemi ona kurul karar
versin istiyorum."*

Soru somut: tedarikçi detay panelindeki `RFQs` ve `Quotations` sekmeleri orada mı kalmalı,
yoksa üstteki sayfa sekme çubuğuna (`Suppliers · Orders · Receipts · Unbilled · Invoices ·
AP Aging`) mı taşınmalı?

**Kanıt rejimi.** `decision-review` skill'i, Rule 0: bu belgedeki hiçbir sayı, dosya adı
veya satır numarası hafızadan ya da bir ajan raporundan gelmiyor — hepsi 2026-09-02
oturumunda bir komutun ürettiği çıktıdan. Şüpheci ayrı bir ajan olarak koştu ve **kendi
üç iddiamı** yanlışladı; ikisi kararı doğrudan değiştirdi. Şüpheci'nin **kendi iki
iddiası** da ölçümle yanlış çıktı. Hepsi §5'te, tek tek.

---

## KARAR ÖZETİ

Sekmeler panelde kalıyor — ama bunu reponun kendi emsaline **rağmen** karara bağlıyoruz,
habersiz değil.

İlk taslağım "üst çubuk sayfa düzeyi, panel taraf düzeyi" diye bir ilkeye dayanıyordu.
**O ilke bu repoda yok; en yakın örnek onu çürütüyor.** Satış tarafında Quotation tek uç
noktadan **iki yüzeye** birden çıkıyor: `Customers.vue:65` panelde, `Quotations.vue:62`
üst düzey `/sales/quotations` rotasında, ikisi de `stabler.api.sales.list_quotations`.
Yani "tek uç nokta, iki yüzey" reponun mevcut deseni.

Karar yine de panelden yana, çünkü iki doctype **farklı eylemlerde** okunuyor — argüman
§3'te.

İkinci bulgu sorunun kendisinden büyük: sekme kapısı yanlış kiracılara açık. `tender`
8 kiracıdan **1'inde** açık (mikas), `purchasing` **7'sinde**; kapı `tender OR purchasing`
olduğu için **6 kiracı** iki sekmeyi de alıyor ve altısında da içerik **ölçülen sıfır**.

---

## 1 · Envanter (ölçüldü 2026-09-02)

| Olgu | Değer | Komut / kaynak |
|---|---|---|
| `/purchasing` alt rotaları | `suppliers, orders, orders/new, orders/:name, receipts, invoices, invoices/new, invoices/:name/print, invoices/:name, aging, unbilled-receipts, landed-cost-review/…` | `sed -n '360,392p' router.js` |
| — içinde `rfqs` / `quotations` | **yok** | aynı |
| `supplier_quotation_history` imzası | `(supplier, company=None)` | `purchasing.py:3295` |
| `supplier_rfq_history` imzası | `(supplier, company=None)` | `purchasing.py:3364` |
| Üst düzey RFQ ekranı | `/tender/rfq` → `RfqList.vue`, dört rota, hepsi `meta: { module: "tender" }` | `router.js:299-302` |
| RfqList'in uç noktası | `stabler.api.sourcing.list_all_rfqs` | `RfqList.vue:35` |
| `list_all_rfqs` imzası | `(company=None, deal=None, search=None, limit=200)`, `_require_tender(company)` | `sourcing.py:801` |
| — tedarikçi filtresi | **yok** | aynı |
| Şirket-geneli Supplier Quotation sorgusu | **var**: `list_unassigned_quotations(search, limit, company)` | `sourcing.py:1333` |
| — kapıları | `_require_tender` **+** `_require_tender_view("sourcing")` | `sourcing.py:1335-1337` |
| — kapsamı | deal'e bağlı teklifleri **dışlıyor** ("not tagged to any deal") | `sourcing.py:1334` |
| Panel sekme listesi | `extraTabs` süzülmeden ekleniyor | `PartyCenter.vue:768` |
| — nereye gidiyor | `:tabs="tabs"` → `v-for="tab in props.tabs"` | `PartyCenter.vue:1029`, `PartyTransactions.vue:278` |
| Sekme kapısı | `canAccessModule("tender") \|\| canAccessModule("purchasing")` | `Suppliers.vue:122` |
| Müşteri panelinde Quotations sekmesi | **var**, `api.quotes` üzerinden | `Customers.vue:65`, `PartyCenter.vue:766` |
| Aynı uç noktanın üst düzey yüzeyi | `/sales/quotations` → `Quotations.vue:62` | `router.js:340` |

### Kiracı matrisi (canlı, prod, 2026-09-02)

`bench --site <s> mariadb` ile sekiz stabler sitesinde tek tek ölçüldü:

| Site | `enable_tender` | `enable_purchasing` | Supplier Quotation | RFQ |
|---|---|---|---|---|
| mikas | **1** | 1 | 3 | 1 |
| anjan | 0 | 1 | 0 | 0 |
| dts | 0 | 1 | 0 | 0 |
| laminor | 0 | 1 | 0 | 0 |
| msa | 0 | 1 | 0 | 0 |
| smartbox | 0 | 1 | 0 | 0 |
| zuma | 0 | 1 | 0 | 0 |
| horeca | 0 | **0** | — | — |

`tender` **8'de 1**. `purchasing` **8'de 7**. Kapı `OR` olduğu için sekmeleri alan kiracı
sayısı **7**; bunların **6'sında** her iki tablo da boş.

---

## 2 · Lensler

**Sistem Mimarı.** İki uç nokta imzaca taraf-kapsamlı, ama bu bir *tercih*, bir kısıt
değil — `sourcing.py:1333` aynı doctype'ın şirket-geneli sorgusunun bu repoda yazılabilir
olduğunu zaten kanıtlıyor. Dolayısıyla "imza böyle" bir *gerekçe* değil, olsa olsa "şimdi
değil" demenin kolay yolu. Gerçek mimari soru §3'te.

**Geliştirme Ekibi.** Üste taşımak iki yeni liste uç noktası, iki ekran ve filtreler
demek; ardından `/tender/rfq` ile senkron tutma yükü. Panelde kalırsa "bu tedarikçi ne
istedi, ne teklif etti" tek tık. Sürtünme yönü nettir.

**DevOps.** Bir şey yok. Ortam bağımlılığı yok, koşulan bir şey yok.

**Operatör.** İki farklı insan, iki farklı soru. Satın almacı bir tedarikçinin sayfasında
"biz buna ne sorduk, o ne dedi" diye soruyor — doğası gereği tek tedarikçilik. İhaleci
"şirkette hangi RFQ'lar açık" diye soruyor — `/tender/rfq` bunu zaten karşılıyor. Mevcut
ayrım bu iki soruyu zaten ayırmış durumda. Ama operatörün asıl söyleyeceği şey şu: altı
kiracıda bu sekmeler her zaman boş ve orada olmaları kullanıcıya *var olmayan bir yol*
gösteriyor.

---

## 3 · Satış emsaline rağmen neden panel

Şüpheci haklı olarak şunu istedi: satış tarafındaki "iki yüzey" desenini takip
etmemek için yazılı bir argüman. İşte o argüman.

**İki doctype farklı eylemlerde okunuyor.**

Sales Quotation bir **hat** olarak taranıyor: "ne teklif ettik, hangisi açık, hangisi
süresi doluyor" şirket-geneli ve tekrarlayan bir soru, ve satışçının günlük işi. Üst düzey
`/sales/quotations` bunun karşılığı.

Supplier Quotation tek bir eylemde okunuyor: **bir lot için teklifleri karşılaştırmak.**
O karşılaştırmanın ekranı zaten var — `SourcingWorkspace`, `base_grand_total`'a göre
sıralayıp ihaleyi bağlıyor (`_landed.py:101`). Tedarikçi tekliflerini lotundan koparıp
şirket genelinde listelemek kimsenin sormadığı bir soruyu cevaplar.

Gerçekten ihtiyaç duyulan tek şirket-geneli okuma — "hangi teklifler henüz bir lota
bağlanmamış" — zaten var (`sourcing.py:1333`) ve **tam da onları bir lota geri sokmak
için** var. Yani şirket-geneli okuma bu doctype'ta bir varış noktası değil, bir onarım
adımı.

Emsal transfer olmuyor: benzeyen şey doctype'ın adı, okunma biçimi değil.

---

## 4 · Kararlar (ADR-501…504)

### ADR-501 — `RFQs` ve `Quotations` sekmeleri tedarikçi panelinde kalır

Üst çubuğa taşınmaz. Gerekçe §3. Bu karar "kanıt henüz taşımayı gerektirmiyor"
biçiminde, "taşınmamalı" biçiminde değil — tek tender kiracısında 3 teklif var ve bu
örneklem bir bilgi mimarisi genellemesini taşımaz.

### ADR-502 — `/purchasing/rfqs` ve `/purchasing/quotations` rotaları açılmaz

`/tender/rfq` zaten şirket-geneli RFQ listesini veriyor (`router.js:299`,
`sourcing.py:801`). İkinci bir kopya, farklı modül kapısıyla, ikisini senkron tutma
borcu doğurur. Şüpheci bu maddeyi kırmaya çalıştı ve kıramadı.

### ADR-503 — Şirket-geneli teklif listesi ihtiyacı, `list_unassigned_quotations`'ın genelleştirilmesiyle karşılanır

Yeni sorgu yazılmaz. `sourcing.py:1333` zaten şirket-geneli, izin denetimli,
`supplier_name`/`country` zenginleştirmesi ve `search` yapılmış hâlde. Eksik olan tek şey
deal'e bağlı teklifleri dışlayan davranışın parametreye alınması. Yeni bir sorgu yazmak
aynı doctype için ikinci bir şirket-geneli okuma yolu demek olurdu.

### ADR-504 — Sekme kapısı bölünür: `RFQs` → `tender`, `Quotations` → `tender OR purchasing`

`Suppliers.vue:122` şu an ikisini birden `tender OR purchasing`'e bağlıyor. Ölçüm: altı
kiracı `purchasing=1, tender=0` ve altısında da RFQ sayısı **0**. SPA'da RFQ oluşturmanın
tek yolu tender modülü — `purchasing.py` RFQ'ya yalnızca okumak için dokunuyor. Dolayısıyla
o altı kiracıda `RFQs` sekmesi kullanıcıya var olmayan bir yol gösteriyor.

`Quotations` aynı durumda **değil**: Supplier Quotation standart bir satın alma doctype'ı
ve bir purchasing kiracısı onu masaüstünden kullanmaya başlayabilir. Bugün altısında da 0,
ama yapısal bir engel yok — o yüzden kapısı dar tutulmuyor.

Bu ayrı bir değişiklik: önce kırmızı test, sonra kod.

---

## 5 · CORRECTIONS

### Kendi yanlışlarım (Şüpheci yakaladı)

| İddiam | Gerçek | Etki |
|---|---|---|
| "İki sekme yalnızca tedarikçide; `Customers.vue`'da `extraTabs` yok" | grep doğru, **çıkarım ters**. Müşteri panelinde Quotations sekmesi var, `api.quotes` üzerinden (`Customers.vue:65`, `PartyCenter.vue:766`) | Kararı değiştirdi: §3 yazılmak zorunda kaldı |
| "Üst çubuk sayfa düzeyi, panel taraf düzeyi — reponun ilkesi" | Böyle bir ilke **yok**; `list_quotations` tek uç noktadan iki yüzeye çıkıyor (`Quotations.vue:62`, `Customers.vue:65`) | İlke uydurmaydı; gerekçe değiştirildi |
| "Şirket-geneli Supplier Quotation listesi hiçbir yerde yok" | **Var**: `list_unassigned_quotations` (`sourcing.py:1333`) | ADR-503 "yeni yaz"dan "genelleştir"e döndü |

### Şüpheci'nin yanlışları (ölçümle)

| Şüpheci'nin iddiası | Ölçüm | Verdikt |
|---|---|---|
| "'3 teklif' bir `GROUP BY` kardinalitesi; toplam raporlanmamış `COUNT(*)` sütununda" | İlk sorgu `COUNT(*)`'ı **yazdırmıştı** (her satır 1). Kesin ölçüm: `SELECT COUNT(*) FROM tabSupplier Quotation` → **3** | **Yanlış.** İddia doğruydu |
| Karşı-kanıt: "`sourcing.py:868` mikas'ta 14 teklif ölçmüş" | O satır bir **göç durumu** yorumu (`_SQ_RFQ_FIELD` damgasız teklif sayısı), 2026-08-15 tarihli, canlı sayı değil | **Yanlış** — Rule 0'ın yasakladığı türden, bir yorumdan alınmış sayı |
| "4 doğrulanmış kiracı (anjan, msa, dts, horeca) + 2 belirsiz (laminor, smartbox)" — `(unverified)` işaretli | Canlı: sekmeleri alan **6** kiracı. horeca **almıyor** (`purchasing=0`); laminor ve smartbox **alıyor** (ikisi de 1) | **İki yönde de yanlış**; kendi işaretlediği gibi ölçülmemişti |

Şüpheci'nin ilk iki maddesi, skill'in kendi kayıtlarındaki uyarının aynısı: *"bir düzeltme,
yanlış iddiadan pahalıdır, çünkü inceleme yetkisiyle gelir."* Yine de net katkısı pozitif:
üç bloklayan itirazından ikisi kararı gerçekten değiştirdi.

---

## Çıktı sözleşmesi

```
DECISIONS
  1. ADR-501 — sekmeler tedarikçi panelinde kalır; çünkü Supplier Quotation tek eylemde
     (lot karşılaştırması) okunuyor ve o ekran zaten var (SourcingWorkspace, _landed.py:101),
     Sales Quotation ise bir hat olarak taranıyor. Satış emsaline rağmen, habersiz değil.
  2. ADR-502 — /purchasing/rfqs ve /purchasing/quotations açılmaz; çünkü /tender/rfq zaten
     şirket-geneli (router.js:299, sourcing.py:801). Şüpheci kıramadı.
  3. ADR-503 — şirket-geneli teklif okuması list_unassigned_quotations genelleştirilerek
     karşılanır (sourcing.py:1333), yeni sorgu yazılmaz.
  4. ADR-504 — RFQs sekmesi tender'a daraltılır, Quotations tender OR purchasing kalır;
     çünkü 6 kiracıda purchasing=1/tender=0 ve altısında da RFQ sayısı 0 (canlı ölçüm).

ACCEPTANCE
  ADR-501/502 — kod değişmiyor; kabul kriteri bu belgenin varlığı.
  ADR-503 — list_unassigned_quotations parametre kazandığında: aynı çağrı eski
     davranışla ÇAĞIRILDIĞINDA dönen satır kümesi bugünküyle birebir aynı kalmalı
     (deal'e bağlılar hâlâ dışlanmalı), yeni parametreyle satır sayısı ARTMALI.
     İkisi birden ölçülmeden kabul yok.
  ADR-504 — mikas'ta RFQs sekmesi görünmeye DEVAM etmeli; anjan'da (purchasing=1,
     tender=0) GÖRÜNMEMELİ. Quotations ikisinde de görünmeli. Üç gözlem, tek testte.

NOT DECIDED
  Supplier Quotation için üst düzey bir ekranın ileride gerekip gerekmeyeceği. Bugünkü
  tek tender kiracısında 3 teklif var; bu örneklem bir IA kararını taşımaz. Bunu ölçüm
  settle eder, tartışma değil — eşik §"WOULD CHANGE MY MIND"de.

  Suppliers.vue:695'teki para birimi hatası (base tutar, işlem para birimiyle
  etiketleniyor) bu kurulun konusu değil; ayrı iş olarak duruyor.

WOULD CHANGE MY MIND
  ADR-501 tersine döner eğer: mikas'ta Supplier Quotation sayısı üç haneye çıkar VE
  kullanıcılar bir lot bağlamı olmadan teklif aramaya başlarsa. İkincisi olmadan
  birincisi yetmez — sayı tek başına bir eylem değil.
  ADR-504 tersine döner eğer: bir purchasing kiracısında SPA dışından RFQ oluşturulmaya
  başlanırsa (bugün altısında da 0).

CORRECTIONS
  §5'te, altı madde: üçü benim, üçü Şüpheci'nin.
```
