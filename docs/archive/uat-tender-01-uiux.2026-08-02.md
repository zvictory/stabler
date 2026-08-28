> **ARŞİV — 2026-08-28. Bu doküman yazıldığı gün zaten bayattı; okumadan önce şunu bil.**
>
> Gezinti bölümünün dayandığı kusurlar (G-02, G-03, G-08, G-09 ve D-01…D-05) tek bir
> refactor'la kapanmıştı: `95b1ab2` — *"ten screens, ten hand-rolled shells — one bar,
> one place"*. O commit **2 Ağustos 11:45**'te main'e girdi; bu doküman aynı gün
> **16:21**'de eklendi — yani düzeltmeden dört buçuk saat sonra, düzeltmeden önceki
> durumu anlatarak. `git merge-base --is-ancestor 95b1ab2 777a896` sırayı doğruluyor.
>
> Kendi kanıtı olarak gösterdiği grep de yanlıştı: "TenderNav repo genelinde yalnız 6
> dosyada geçiyor" denmişti; bugün `TenderNav` yalnız **iki** yerde import ediliyor
> (`TenderPage.vue`, `Sidebar.vue`) ve `TenderPage` kabuğu üzerinden **her** routed
> tender ekranında render ediliyor — `OperationsDesk`, `LogistBoard`, `DeclarantQueue`,
> `MyTenders`, `PoControlBoard` dahil.
>
> Ayakta kalan tek gerçek maddesi G-11: *Overview* bağlantısı `/dashboard`'a çıkıp
> nav'ı düşürüyor — ve `TenderNav.vue:39-41`'deki yorum bunun kasıtlı olduğunu söylüyor.
>
> Arşivlenme sebebi: 2026-08-28'de bir kod taramasını yanlış yönlendirdi, kapanmış işi
> açık kusur gibi gösterdi. Tender'ın bugünkü durumu için koda ve
> `docs/plans/2026-08-17-mikas-tender-workflow-formlari-tasarim-kurulu-karari.md`'ye bak.

---

# UAT 01 — Tender operasyon panoları · UI/UX kabul testleri

**Kapsam:** Tender modülünün yeni ekranları (Operasyon Masası, Tender CRM, Direktör
Panosu, Süreç Akışı) ve bunların modül gezinmesi (`TenderNav.vue`), kenar çubuğu
(`Sidebar.vue`) ve router (`router.js`) ile tutarlılığı.

**Test sitesi / şirket:** `mikas.erpstable.com` · Company = `Mikas`
**Temel URL biçimi:** `https://mikas.erpstable.com/stabler#/tender/<ekran>`
**Demo veri:** `bench --site mikas.erpstable.com execute stabler.maintenance.seed_tender_demo.seed`
13 anlaşma üretir: `UTY-2026-4301, 4302, 4305, 4306, 4308, 4309, 4310, 4311, 4312,
4313, 4314, 4315, 4316` (4303/4304/4307 bilerek yok). Her demo kaydının adında
` [DEMO]` geçer (`seed_tender_demo.py:43`).

**Test rolleri** (`api/tender.py:1725-1731`):

| Görünüm | Rolü açan roller |
|---|---|
| `director` | System Manager · Stabler Admin · Sales Manager · **Stabler Tender Director** |
| `sourcing` | System Manager · Stabler Admin · Sales Manager · **Sales User** |
| `declarant` | System Manager · Stabler Admin · Sales Manager · **Stabler Declarant** |
| `logist` | System Manager · Stabler Admin · Sales Manager · **Stabler Logist** |

Test için dört ayrı kullanıcı gerekir; "Sales Manager" dördünü birden açtığı için
rol kapılarını **Sales Manager ile test etmeyin**.

**Diller:** en · ru · tr · uz · uzc (Sidebar.vue:32-38). Dil değişimi tam sayfa
yeniden yükleme yapar (Sidebar.vue:210).

**Not:** Bu pakette `SalesOrderBoard.vue`, `TenderFunnel.vue`, `TenderWorkspaceTabs.vue`,
`SkeletonRows.vue`, `EmptyState` dışındaki bazı ortak bileşenler ve `composables/i18n.js`
YOK. Onlara dayanan davranışlar aşağıda "doğrulanamadı" olarak işaretlendi; iddiaya
çevrilmedi.

---

## 1. Gezinti tutarlılığı

Mimari karar: **kenar çubuğu yalnız MODÜLÜ gösterir**, alt-navigasyon sayfanın ÜST
menüsündedir. `Sidebar.vue:45-61` bu kararı yazıyla da anlatıyor.

### G-01 · Kenar çubuğunda tender tek satır

- **Ön koşul:** Rol `Stabler Tender Director`, şirket `Mikas`,
  `https://mikas.erpstable.com/stabler#/dashboard`
- **Adımlar:**
  1. Giriş yap, kenar çubuğunu aç (dar ekranda hamburger).
  2. "Operasyon" (Operations) grubunu gözle tara.
  3. "Tender" satırının altında iç içe bir alt liste açılıp açılmadığına bak.
- **Beklenen:** "Operasyon" grubunda tam olarak şu 7 satır, bu sırada: Satınalma ·
  İthalat · **Tender** · Envanter · Üretim · Servis · Süreçler (Sidebar.vue:103).
  "Tender" satırı `ti-gavel` çekiç ikonu taşır (Sidebar.vue:79). Tender'ın **hiçbir
  alt satırı yoktur** — "Operasyon Masası", "Direktör Panosu", "Gümrük kuyruğu" gibi
  girdiler kenar çubuğunda GÖRÜNMEZ.
- **Kırık belirtisi:** Tender altında 8 alt satır çizilir (eski mimari), ya da
  "Kontrol Kulesi" adında bir satır belirir.
- **Kanıt:** `public/js/components/Sidebar.vue:79` (tek `items` girdisi),
  `Sidebar.vue:65-96` (liste modül düzeyinde, alt yol yok).

### G-02 · Kenar çubuğundan tender'a giriş noktası

- **Ön koşul:** Rol `Stabler Tender Director`, şirket `Mikas`,
  `https://mikas.erpstable.com/stabler#/dashboard`
- **Adımlar:**
  1. Kenar çubuğunda "Tender"e tıkla.
  2. Adres çubuğundaki hash'i oku.
  3. Sayfanın en üstünde `ds-modnav` çubuğu (solda kalın "Tender" yazısı + yatay
     bağlantı şeridi) var mı bak.
- **Beklenen:** URL `.../stabler#/tender/board` olur (Sidebar.vue:79 → router.js:268,
  `Contract board`). Kenar çubuğundaki "Tender" satırı aktif işaretlenir
  (`tenderActive`, Sidebar.vue:61 + 259).
- **Kırık belirtisi:** **Bilinen açık** — `/tender/board` rotası `SalesOrderBoard`
  bileşenini render eder (router.js:268) ve `TenderNav` bu bileşende import
  EDİLMEZ (repo genelinde `TenderNav` yalnız 6 dosyada geçiyor). Modül üst menüsü
  hiç çizilmez; kullanıcı tender'a girdiği ilk ekranda alt-navigasyonu göremez ve
  modülün diğer ekranlarına gidecek hiçbir bağlantı bulamaz. Not: `SalesOrderBoard.vue`
  bu pakette yok, doğrulama site üzerinde yapılmalı.
- **Kanıt:** `public/js/components/Sidebar.vue:79`, `public/js/router.js:268`,
  `public/js/pages/tender/TenderNav.vue` (import eden dosyalar: TenderCrm:14,
  MyTenders:18, DeclarantQueue:18, TenderFlow:24, DirectorBoard:22, LogistBoard:18).

### G-03 · Operasyon Masası'nda üst menü

- **Ön koşul:** Rol `Stabler Tender Director`, şirket `Mikas`,
  `https://mikas.erpstable.com/stabler#/tender/desk`
- **Adımlar:**
  1. URL'yi doğrudan aç.
  2. Sayfanın en üst 60px'ine bak: "Tender" markası + yatay sekme şeridi var mı?
  3. Sayfa başlığını oku.
- **Beklenen:** En üstte `ds-modnav` şeridi, altında `ds-page-head` içinde
  "Operasyon Masası · Mikas" üst etiketi ve `Bugün ne yapmalıyım?` (`What should I
  do today?`) H1 başlığı.
- **Kırık belirtisi:** **Bilinen açık** — `OperationsDesk.vue` şablonunun kökü
  `<div class="operations-desk-page stbl-ds">` ve ilk çocuk doğrudan
  `<header class="ds-page-head">`. `TenderNav` ne import edilmiş ne render
  edilmiştir. Sayfa üst menüsüz açılır; kullanıcı Operasyon Masası'ndan CRM'e,
  Direktör panosuna veya Gümrük kuyruğuna geçemez, yalnız tarayıcı geri tuşu kalır.
- **Kanıt:** `public/js/pages/tender/OperationsDesk.vue:1-6` (şablon kökü),
  `OperationsDesk.vue:245-252` (import listesinde TenderNav yok).

### G-04 · Üst menü ↔ router eşleşmesi (director)

- **Ön koşul:** Rol `Stabler Tender Director` (Sales Manager DEĞİL), şirket `Mikas`,
  `https://mikas.erpstable.com/stabler#/tender/portfolio`
- **Adımlar:**
  1. Üst menüdeki bağlantıları soldan sağa say ve metinlerini not al.
  2. Her birine sırayla tıkla, açılan URL'yi ve sayfa H1'ini not al.
- **Beklenen:** `director` görünümüne sahip, `sourcing`/`declarant`/`logist`
  taşımayan bir kullanıcıda üst menü tam olarak **5 bağlantı** çizer:

  | # | Metin | Gittiği URL | Açılan H1 |
  |---|---|---|---|
  | 1 | Genel bakış (`Overview`) | `#/dashboard` | Dashboard |
  | 2 | Operasyon masası | `#/tender/desk` | Bugün ne yapmalıyım? |
  | 3 | Süreç akışı | `#/tender/flow` | Tender süreç akışı |
  | 4 | Sözleşme panosu (`Contract board`) | `#/tender/board` | — |
  | 5 | Direktör panosu | `#/tender/portfolio` | Direktör panosu |

  "Tender CRM" de görünür (director VEYA sourcing yeter, TenderNav.vue:47), yani
  toplam 6 bağlantı + "Tender" markası. `My tenders`, `Tender PO control`,
  `Customs queue`, `Logistics` çizilmez.
- **Kırık belirtisi:** Menüde çizilen bir bağlantı 404/NotFound'a düşerse ya da
  router'daki `/tender/sourcing` (Sourcing comparison) menüde belirirse eşleşme
  bozuktur.
- **Kanıt:** `public/js/pages/tender/TenderNav.vue:35-61` (bağlantılar ve `v-if`
  kapıları), `public/js/router.js:265-276` (rotalar).

### G-05 · Aktif sekme işaretlemesi

- **Ön koşul:** Rol `Stabler Tender Director`, şirket `Mikas`,
  `https://mikas.erpstable.com/stabler#/tender/flow`
- **Adımlar:**
  1. Üst menüde "Süreç akışı"na bak.
  2. "Direktör panosu"na tıkla, sonra tekrar üst menüye bak.
  3. "Tender CRM"e tıkla, üst menüyü tekrar oku.
- **Beklenen:** Aktif sekme **tek** olur ve üç işaret birden taşır: metin rengi
  koyulaşır (`--ds-tx`), font-weight 600, ve altında **3px kalınlığında vurgu rengi
  (`--ds-acc`) alt çizgi** belirir. Diğer sekmeler `--ds-tx2` gri ve şeffaf alt
  çizgilidir.
- **Kırık belirtisi:** Aynı anda iki sekme altı çizili; ya da hiçbiri
  işaretlenmiyor (vue-router `active-class` yerine `exact-active-class` gerekiyor
  olabilir); ya da `/tender/portfolio`dayken `/tender/board` da aktif görünüyor
  (prefix eşleşmesi kazası).
- **Kanıt:** `TenderNav.vue:35-61` (`active-class="active"`),
  `public/css/stabler-modernist.css:216-221` (`.ds-modnav a.active`).

### G-06 · Bir role görünmeyen bağlantı gerçekten çizilmiyor mu (sourcing)

- **Ön koşul:** Rol yalnız `Sales User` (Sales Manager / System Manager / Stabler
  Admin YOK), şirket `Mikas`, `https://mikas.erpstable.com#/tender/crm`
- **Adımlar:**
  1. Üst menüdeki bağlantıları say.
  2. Sayfa kaynağında (DevTools → Elements) `.ds-modnav` altındaki `<a>` sayısını
     doğrula — CSS ile gizlenmiş ama DOM'da duran bağlantı olmamalı.
  3. Adres çubuğuna elle `#/tender/portfolio` yaz ve Enter'a bas.
- **Beklenen:** Menüde 5 bağlantı: Genel bakış · Operasyon masası · Sözleşme
  panosu · Tender CRM · Benim tenderlarım · Tender PO kontrol (yani 6 — `sourcing`
  hem CRM hem my-tenders hem po-control açar). "Süreç akışı" ve "Direktör panosu"
  **DOM'da hiç yoktur** (`v-if`, `v-show` değil). Adım 3'te sayfa yine de açılır —
  aşağıya bakınız.
- **Kırık belirtisi:** Bağlantı DOM'da var ama `display:none` ile gizlenmiş; ya da
  `session.tenderViews` henüz dolmadan menü çizildiği için ilk 200-300 ms tüm
  bağlantılar görünüp sonra kayboluyor (yanıp sönme).
- **Kanıt:** `TenderNav.vue:24` (`can()` = `session.tenderViews.includes`),
  `TenderNav.vue:25` (`onMounted → ensureTenderViews`), `Sidebar.vue:63` (liste her
  sayfada önceden çekiliyor, yanıp sönmeyi bu engelliyor),
  `api/tender.py:1733-1735` (`_tender_views`).

### G-07 · Menüde olmayan ekran doğrudan URL ile açılıyor mu

- **Ön koşul:** Rol yalnız `Stabler Declarant`, şirket `Mikas`
- **Adımlar:**
  1. `https://mikas.erpstable.com/stabler#/tender/customs` — açıldığını doğrula.
  2. Üst menüde "Direktör panosu" olmadığını doğrula.
  3. Adres çubuğuna `https://mikas.erpstable.com/stabler#/tender/portfolio` yaz.
- **Beklenen (kod ne yapıyor):** Router kapısı yalnız `meta.module === "tender"`e
  bakar (router.js:612-613); rol görünümü (`director`) İSTEMEZ. Sayfa **açılır**,
  `TenderNav` çizilir (içinde Direktör panosu bağlantısı yine yok), tablo API
  çağrısı `tender_director_board` yapılır. Sunucu tarafı kapı
  `_require_tender(company)` + doküman düzeyi izinler; `_require_tender_view("director")`
  bu uçta **çağrılmıyor** — sayfa dolabilir.
- **Kırık belirtisi:** Yetkisiz kullanıcı direktör KPI'larını (portföy değeri, kazanma
  oranı, `Остаток`) görüyorsa güvenlik kusuru; kırmızı bir toast ile boş sayfa
  görüyorsa UX kusuru (yetkisiz durumu için ekranda metin yok, yalnız toast var).
- **Kanıt:** `public/js/router.js:273` (rota yalnız `module: "tender"`),
  `public/js/router.js:612-635` (guard), `api/tender.py:1984` (`tender_director_board`
  imzası), `DirectorBoard.vue:42-46` (hata → yalnız toast).

### G-08 · Eski `/tender/director` yolu

- **Ön koşul:** Herhangi bir tender rolü, şirket `Mikas`
- **Adımlar:**
  1. Adres çubuğuna `https://mikas.erpstable.com/stabler#/tender/director` yaz.
  2. Enter'a bas ve nereye düştüğüne bak.
- **Beklenen (kod ne yapıyor):** `#/dashboard`'a **sessizce** yönlendirilir. Hiçbir
  uyarı, hiçbir toast yok; kullanıcı tender modülünden tamamen çıkmış olur ve üst
  menü kaybolur.
- **Kırık belirtisi:** Bu davranışın kendisi kusurdur: `Sidebar.vue:45-56` yorumu bu
  redirect'i eski mimarinin kusuru olarak anlatıyor ("menüden tıklayan kullanıcı
  sessizce panoya düşüyordu") ama rota hâlâ yerinde. Doğrusu `/tender/portfolio`'ya
  yönlendirmek olurdu.
- **Kanıt:** `public/js/router.js:272`, `public/js/components/Sidebar.vue:50-53`.

### G-09 · Modül kökü `/tender`

- **Ön koşul:** Rol `Stabler Tender Director`, şirket `Mikas`
- **Adımlar:**
  1. Adres çubuğuna `https://mikas.erpstable.com/stabler#/tender` yaz (alt yol yok).
  2. Sayfayı ve kenar çubuğunu oku.
- **Beklenen (kod ne yapıyor):** Router'da `/tender` diye bir rota **yok**; istek
  `/:pathMatch(.*)*` → `NotFound` bileşenine düşer. Aynı anda kenar çubuğundaki
  "Tender" satırı **aktif** işaretli kalır (`route.path === "/tender"` dalı).
  Sonuç: aktif modül vurgusu altında "Bulunamadı" sayfası.
- **Kırık belirtisi:** Yukarıdaki tablo. Diğer 14 modülün hepsinde `/modul` kökü
  bir hub'a ya da bir redirect'e sahip (`/sales` → `/sales/customers` router.js:304,
  `/imports` → `/imports/dashboard` router.js:205, `/money` → `/money/accounts`
  router.js:282). Tender'da karşılığı yok.
- **Kanıt:** `public/js/router.js:265-276` (tender rotaları — `/tender` yok),
  `public/js/router.js:510` (catch-all), `public/js/components/Sidebar.vue:61`.

### G-10 · Yetim rota: Sourcing comparison

- **Ön koşul:** Rol `Sales User`, şirket `Mikas`,
  `https://mikas.erpstable.com/stabler#/tender/crm`
- **Adımlar:**
  1. Kanban'da herhangi bir karta tıkla, sağdan çekmece açılsın.
  2. Çekmecenin altındaki birincil düğmeye ("Tedarik karşılaştırma") tıkla.
  3. Açılan sayfanın üst menüsüne bak.
- **Beklenen:** `#/tender/sourcing?deal=<CRM-DEAL-...>` açılır (router.js:270,
  `SourcingCompare`).
- **Kırık belirtisi:** Bu rota **üst menüde hiç yok** (TenderNav.vue:35-61 listesinde
  `/tender/sourcing` geçmiyor) ve `SourcingCompare.vue` `TenderNav` import etmiyor.
  Kullanıcı tender içindeyken üst menüsüz bir ekrana düşer ve geri dönüş için
  yalnız tarayıcı geri tuşu kalır (bu ekranda `useEscapeBack` de yok).
- **Kanıt:** `TenderCrm.vue:576-580` (çekmece düğmesi), `public/js/router.js:270`,
  `TenderNav.vue:35-61`, `public/js/pages/sales/SourcingCompare.vue` (TenderNav
  importu yok — repo genelindeki grep sonucuna göre).

### G-11 · "Genel bakış" tender'ın dışına çıkarıyor

- **Ön koşul:** Rol `Stabler Tender Director`, şirket `Mikas`,
  `https://mikas.erpstable.com/stabler#/tender/portfolio`
- **Adımlar:**
  1. Üst menüde soldaki ilk bağlantıya ("Genel bakış") tıkla.
  2. Yeni sayfada üst menüyü ara.
  3. Tender'a dönmek için hangi yolu kullandığını not al.
- **Beklenen:** `#/dashboard` açılır. Tender üst menüsü **tamamen kaybolur** —
  `TenderNav` yalnız tender sayfalarında render ediliyor. Dönüş yolu yalnız kenar
  çubuğudur.
- **Kırık belirtisi:** Menünün ilk maddesi kullanıcıyı menüden çıkaran tek maddedir;
  `ds-modnav`'ın diğer 9 maddesi modül içinde kalır. Bir modül navigasyonunun
  içinden modülü terk eden bir sekme, sekme metaforunu bozar. TenderNav.vue:33-34
  yorumu bunun bilinçli olduğunu söylüyor ("Konumu değil VARLIĞI garanti") — kabul
  kararı ürün sahibine ait.
- **Kanıt:** `public/js/pages/tender/TenderNav.vue:33-35`.

### G-12 · SPA sınırı — `/app/` sızıntısı yok

- **Ön koşul:** Herhangi bir tender rolü, şirket `Mikas`
- **Adımlar:**
  1. Sırayla `#/tender/desk`, `#/tender/crm`, `#/tender/portfolio`, `#/tender/flow`,
     `#/tender/my-tenders`, `#/tender/customs`, `#/tender/logistics`,
     `#/tender/po-control` ekranlarını aç.
  2. Her ekranda DevTools konsolunda çalıştır:
     `[...document.querySelectorAll('a[href]')].filter(a=>a.getAttribute('href').includes('/app/')).map(a=>a.outerHTML)`
  3. CRM'de bir kartı aç, çekmecedeki bağlantıları da aynı testten geçir.
- **Beklenen:** Her ekranda boş dizi `[]`. Tüm gezinme `router-link` veya
  `router.push` ile hash yolları üzerinden yapılır.
- **Kırık belirtisi:** Herhangi bir `href="/app/..."` — kullanıcıyı Frappe desk
  arayüzüne atar ve SPA oturumundan çıkarır.
- **Kanıt:** `grep -rn "/app/" public/js api maintenance` → sonuç yok (kaynak
  ağacında hiç geçmiyor). Belge zincirinde açılan bağlantılar
  `TenderDocumentChain.vue:24` (`/purchasing/orders/...`, `/sales/orders/...`),
  masa satırları `api/_desk_rules.py:73,180,199,239` (`/tender/crm?deal=`,
  `/purchasing/orders/`, `/purchasing/invoices/`) — hepsi SPA yolu.

---

## 2. Tasarım katmanı (`.stbl-ds`) uyumu

### Kodun söylediği: hangi ekran içeride, hangisi dışarıda

`.stbl-ds` opt-in: `stabler-modernist.css` içindeki **her** kural `.stbl-ds`
sarmalayıcısına scope'lu (örn. satır 202, 223, 297, 362, 382, 859). Sınıfı
taşımayan ekran katmandan tek kural görmez.

| Ekran / URL | Bileşen | `.stbl-ds` | `TenderNav` | Kanıt |
|---|---|---|---|---|
| `#/tender/desk` | OperationsDesk.vue | **VAR** (kök) | **YOK** | OperationsDesk.vue:5 |
| `#/tender/crm` | TenderCrm.vue | **VAR** (kök) | VAR (ilk çocuk) | TenderCrm.vue:248-249 |
| `#/tender/flow` | TenderFlow.vue | **VAR** (kök) | VAR (ilk çocuk) | TenderFlow.vue:119-120 |
| `#/tender/portfolio` | DirectorBoard.vue | **VAR** (kök) | VAR (ilk çocuk) | DirectorBoard.vue:132-133 |
| — (bileşen) | TenderNav.vue | **VAR** (kendi kökü) | — | TenderNav.vue:29 |
| `#/tender/my-tenders` | MyTenders.vue | **YOK** (Tabler `container-xl`) | VAR (başlıktan SONRA) | MyTenders.vue:97-99 |
| `#/tender/customs` | DeclarantQueue.vue | **YOK** (Tabler) | VAR (başlıktan SONRA) | DeclarantQueue.vue:63-65 |
| `#/tender/logistics` | LogistBoard.vue | **YOK** (Tabler) | VAR (başlıktan SONRA) | LogistBoard.vue:57-59 |
| `#/tender/po-control` | PoControlBoard.vue | **YOK** (Tabler) | **YOK** | PoControlBoard.vue:281 |
| ↳ gömülü | TenderIntake.vue | **YOK** (Tabler card) | — | TenderIntake.vue:139-141 |
| ↳ gömülü | BidPricing.vue | **YOK** (Tabler card) | — | BidPricing.vue:138-140 |
| ↳ gömülü | TenderDocumentChain.vue | **YOK** (Tabler card) | — | TenderDocumentChain.vue:29-31 |
| `#/tender/board` | SalesOrderBoard.vue | doğrulanamadı (dosya pakette yok) | **YOK** | router.js:268 |
| `#/tender/sourcing` | SourcingCompare.vue | **YOK** | **YOK** | router.js:270 |

Özet: **4 ekran + 1 bileşen göç etti, 8 ekran/parça etmedi.**

### D-01 · Göç etmiş dört ekranın kendi arasında tutarlılığı

- **Ön koşul:** Rol `Stabler Tender Director`, şirket `Mikas`, demo veri yüklü,
  `https://mikas.erpstable.com/stabler#/tender/portfolio`
- **Adımlar:**
  1. Direktör panosunu aç, KPI şeridini ve H1'i ekran görüntüsüne al.
  2. Üst menüden "Süreç akışı"na geç, aynı iki bölgeyi ekran görüntüsüne al.
  3. "Tender CRM"e geç, tekrarla.
  4. Adres çubuğundan `#/tender/desk` aç, tekrarla.
- **Beklenen:** Dördünde de aynı görsel dil: H1 başlık fontu `--ds-font-head`,
  KPI kartları 1px `--ds-ln` çizgiyle ayrılmış ızgara (`ds-kpis`), her kartın üst
  kenarında 3px anlam çubuğu, sayı `--ds-mono` 34px tabular. Direktör panosu
  `data-cols="3"` ile **6 sayaç 3×2**, diğer üçü `data-cols="4"` ile **4 sayaç tek
  sıra**.
- **Kırık belirtisi:** Bir ekranda KPI'lar Tabler kartları gibi yuvarlak köşeli ve
  gölgeli çıkıyorsa `.stbl-ds` kökten düşmüştür.
- **Kanıt:** `stabler-modernist.css:223-232` (`ds-kpis` ızgarası),
  `DirectorBoard.vue:150`, `TenderFlow.vue:136`, `TenderCrm.vue:286`,
  `OperationsDesk.vue:42`.

### D-02 · Göç etmemiş ekrana geçişte görsel kopukluk — adım adım

- **Ön koşul:** Rol `Stabler Logist` **ve** `Stabler Tender Director` (menüde her
  iki bağlantı görünsün), şirket `Mikas`,
  `https://mikas.erpstable.com/stabler#/tender/portfolio`
- **Adımlar:**
  1. Direktör panosundayken sayfanın üst 200px'ini not al: `ds-modnav` çubuğu tam
     genişlikte, gövde `padding: 1rem`.
  2. Üst menüden "Lojistik"e tıkla.
  3. Sayfa yüklendiğinde ekranı **yukarıdan aşağı** oku ve şu dört kopma noktasını
     tek tek işaretle.
- **Beklenen (kopmanın tam yeri):**
  1. **En üstte artık `ds-modnav` YOK.** Onun yerine önce Tabler `container-xl py-3`
     başlığı gelir: `<h2>Lojistik</h2>` (LogistBoard.vue:58). Modül navı bu
     başlığın **ALTINDA** çizilir (LogistBoard.vue:59) — yani sayfa "başlık →
     menü → içerik" sırasıyla açılır, oysa diğer dört ekranda "menü → başlık →
     içerik".
  2. **Negatif marj taşması.** `TenderNav` kendini `margin: -12px -12px 16px`
     (≥992px'de `-16px -20px 18px`) ile içerik sütununun dışına taşırmak üzere
     tasarlandı; `container-xl` içinde sayfa ortasında durduğu için çubuk H2
     başlığının üstüne 12-16px biner ve konteyner kenarlarından taşar.
  3. **İki tipografi yan yana.** Çubuğun içi `--ds-font-head` 21px kalın "Tender"
     markası ve 14.5px `--ds-tx2` sekmeler; hemen üstündeki H2 Tabler'ın gövde
     fontu. Aynı ekran iki farklı başlık fontu gösterir.
  4. **Tablo dili değişir.** `ds-table` yerine Tabler `table card-table` gelir:
     satır yüksekliği, başlık büyük-harf/letter-spacing, hover rengi, sayı
     hizalaması (mono/tabular yerine `font-monospace`) farklıdır; durum göstergesi
     `ds-chip` (renkli 7px kare + kenarlık) yerine Tabler `badge bg-*-lt` yumuşak
     dolgulu rozete döner (LogistBoard.vue:50, 76).
- **Kırık belirtisi:** Yukarıdakiler hâlihazırda mevcut durumdur; test bunları
  **belgelemek** için var. Kabul kararı: bu üç ekran ya göç etmeli ya da
  `TenderNav` bu ekranlarda kökün ilk çocuğu olmalı.
- **Kanıt:** `TenderNav.vue:66-77` (negatif marj), `LogistBoard.vue:57-59`,
  `DeclarantQueue.vue:63-65`, `MyTenders.vue:97-99`,
  `stabler-modernist.css:202-221` (`ds-modnav`), `css:382-395` (`ds-table`),
  `css:399-411` (`ds-chip`).

### D-03 · Göç etmiş ekranın İÇİNDE göç etmemiş bileşen

- **Ön koşul:** Rol `Sales User`, şirket `Mikas`, **demo veri YÜKLÜ DEĞİL** (ya da
  aramaya hiçbir karta uymayan bir metin yazılmış),
  `https://mikas.erpstable.com/stabler#/tender/crm`
- **Adımlar:**
  1. Ekranı aç. Kart yoksa boş durum çizilecektir.
  2. Boş durum bloğunu incele: yuvarlak disk + ikon + başlık.
  3. Aynı sayfadaki `ds-kpi` kartlarıyla yan yana kıyasla.
- **Beklenen:** `EmptyState` bileşeni 144px çapında **radial-gradient yuvarlak
  disk**, gölge (`box-shadow: 0 6px 20px`), 1.1rem yarı-kalın başlık ile çizilir ve
  rengini `--tblr-body-color` / Tabler tonlarından alır — `.stbl-ds` katmanının
  değişkenlerinden (`--ds-tx`, `--ds-ln`) DEĞİL.
- **Kırık belirtisi:** Göç etmiş bir ekranın ortasında yumuşak gradyanlı, gölgeli,
  yuvarlak bir "illüstrasyon" belirir; oysa katmanın boş-durum dili düz
  `ds-panel-foot` metnidir (OperationsDesk.vue:80-83, DirectorBoard.vue:229-232).
  Aynı modülde iki farklı boşluk dili.
- **Kanıt:** `TenderCrm.vue:306-311` (EmptyState kullanımı),
  `public/js/components/EmptyState.vue:75-90,121-148` (Tabler tokenları),
  `OperationsDesk.vue:80-83` ve `DirectorBoard.vue:229-232` (katmanın kendi dili).

### D-04 · Köprü kuralı: form kontrolleri yalnız `.stbl-ds` altında değişir

- **Ön koşul:** Rol `Stabler Tender Director`, şirket `Mikas`
- **Adımlar:**
  1. `#/tender/portfolio` aç, tablodaki "Yönetici" sütununda bir `<select>` bul.
  2. Görünümünü not al (yükseklik, kenarlık, köşe yarıçapı, etiket tipografisi).
  3. `#/tender/po-control` aç, bir tender seç, "Landed cost plan" düzenleyicisini
     aç ve içindeki `form-select` / `form-control` alanlarını not al.
- **Beklenen:** İkisi de aynı temel bileşenden (Tabler `.form-select`) geliyor ama
  yalnız ilkinin görünümü katman tarafından yeniden giydiriliyor. Direktör
  panosundaki select `ds-input` sınıfı taşır ve `min-height: 34px`e sıkıştırılmıştır
  (DirectorBoard.vue:214-222 + 310-314); PO kontrol modalındaki alanlar ham Tabler
  kalır.
- **Kırık belirtisi:** PO kontrol modalındaki alanların da tipografisi değişmişse
  köprü kuralı `.stbl-ds` dışına sızmıştır — göçün "yayılma yarıçapı sıfır"
  garantisi kırılır ve 93 form ekranı aynı anda etkilenir.
- **Kanıt:** `stabler-modernist.css:889-905` (köprü bölümü açıklaması ve
  `.stbl-ds .form-label` kuralı), `DirectorBoard.vue:214`.

### D-05 · Göç durumu regresyon kontrol listesi

- **Ön koşul:** Herhangi bir tender rolü
- **Adımlar:** Her URL'de DevTools konsolunda çalıştır:
  `document.querySelector('.page-body')?.querySelector('.stbl-ds') ? 'DS' : 'TABLER'`
  (ya da daha basit: `!!document.querySelector('.operations-desk-page.stbl-ds')` gibi
  ekran-özel bir kontrol).
- **Beklenen:** Yukarıdaki tabloyla birebir aynı sonuç: `desk/crm/flow/portfolio` →
  DS; `my-tenders/customs/logistics/po-control/board/sourcing` → TABLER (yalnız üst
  navigasyon çubuğu DS).
- **Kırık belirtisi:** Bir ekran listede olmayan tarafa geçmişse ya bir göç sessizce
  yapılmış ya da geri alınmıştır; iki durumda da bu tablo güncellenmeli.
- **Kanıt:** Bölüm başındaki tablo (dosya:satır sütunu).

---

## 3. Boş / yükleniyor / hata / yetkisiz durumları

### Kodun söylediği: hangi ekranda hangi durum var

| Ekran | Yükleniyor | Boş | Hata (ekranda) | Yetkisiz (ekranda) | Şirket seçili değil |
|---|---|---|---|---|---|
| OperationsDesk | VAR (`SkeletonRows` 6×3) | VAR (2 satır metin) | VAR (`role="alert"`) | VAR | VAR |
| TenderCrm | VAR (`SkeletonRows` 4) | VAR (`EmptyState`) | **YOK** (yalnız toast) | **YOK** | **YOK** (`load()` sessizce çıkar) |
| DirectorBoard | VAR (tablo içi iskelet 9×6) | VAR (2 satır metin) | **YOK** (yalnız toast) | **YOK** | **YOK** |
| TenderFlow | VAR (`SkeletonRows` 5) | **YOK** (boş `<tbody>`) | **YOK** (yalnız toast) | **YOK** | **YOK** |

Kanıt: OperationsDesk.vue:71-84 / TenderCrm.vue:302-311, 39-51 / DirectorBoard.vue:190,
229-232, 36-47 / TenderFlow.vue:153-201, 33-43.

### S-01 · Operasyon Masası — dört durumun dördü

- **Ön koşul:** Rol `Stabler Tender Director`, şirket `Mikas`,
  `https://mikas.erpstable.com/stabler#/tender/desk`
- **Adımlar:**
  1. **Yükleniyor:** DevTools → Network → "Slow 3G". Sayfayı yenile.
  2. **Boş:** Ağ normale dön; KPI şeridinde "Bekleyen onay" (`Awaiting my approval`)
     kartına bas, sonuç sıfırsa listeyi izle. (Kesin boş için: `unseed()` çalıştır.)
  3. **Hata:** DevTools → Network → `stabler.api.tender_desk.operations_desk`
     isteğini "Block request URL" ile engelle, "Yenile" düğmesine bas.
  4. **Yetkisiz:** Tender modülü kapalı bir şirkete geç (kenar çubuğu şirket
     seçici).
  5. **Şirketsiz:** Şirket seçicisini boşalt (mümkünse) veya hiç şirketi olmayan
     bir kullanıcıyla gir.
- **Beklenen:**
  1. "Günlük iş planı" paneli altında **6 satır × 3 sütun** gri iskelet; sağ
     sütunda "Karar kutusu" altında **4 satır × 2 sütun** iskelet; "Yenile"
     düğmesinin metni `Yükleniyor…` olur ve düğme devre dışı kalır.
  2. Panel altlığında iki satır alt alta: **"Bugün için planlanmış iş yok"** ve
     **"Bu görünümdeki her şey güncel."** Büyük "Sıradaki iş" kartı hiç çizilmez.
  3. Aynı yerde tek satır, `role="alert"` taşıyan hata metni: sunucudan gelen
     mesaj, yoksa **"Operasyon masası yüklenemedi."**
  4. **"Tender modülüne erişim yok."** metni. (Bu kontrol `loading`'den sonra
     geldiği için hata metnini bastırır.)
  5. **"Lütfen aktif bir şirket seçin."**
- **Kırık belirtisi:** Boş liste yerine sonsuz iskelet (yükleme bayrağı `finally`
  ile düşmüyor); hata durumunda KPI şeridinin hâlâ eski sayıları göstermesi;
  yetkisiz kullanıcıya boş beyaz panel.
- **Kanıt:** `OperationsDesk.vue:71` (iskelet), `:73-75` (yetkisiz), `:76-78`
  (şirketsiz), `:79` (hata), `:80-83` (boş), `:294` (hata metni fallback),
  `:33-35` (düğme durumu).

### S-02 · Operasyon Masası — metinler i18n'den mi geliyor

- **Ön koşul:** Rol `Stabler Tender Director`, şirket `Mikas`, demo veri yüklü,
  `https://mikas.erpstable.com/stabler#/tender/desk`
- **Adımlar:**
  1. Kenar çubuğu alt menüsünden dili **Türkçe**'ye çevir (sayfa yeniden yüklenir).
  2. Sayfa **çerçevesini** oku: H1, KPI etiketleri, bant başlıkları, panel adları.
  3. Sayfanın **satırlarını** oku: iş kaleminin başlığı, altındaki gerekçe satırı,
     onun altındaki küçük gri satır.
  4. Aynı adımları `ru` ve `uzc` için tekrarla.
- **Beklenen (çerçeve):** H1 = "Bugün ne yapmalıyım?", KPI etiketleri "Bugün",
  "Geciken", "Bekleyen onay", "Diğerlerini bekleyen"; bantlar "Geciken", "Bugün",
  "Yakında", "İzlemede"; kısa kodlar OVD/TDY/SOON/WCH.
- **Kırık belirtisi:** **Bilinen açık** — satır metinleri sunucuda İngilizce sabit
  string olarak üretiliyor ve hiçbir çeviri katmanından geçmiyor. Türkçe arayüzde
  şunlar İngilizce kalır:
  - Başlık: `Bid due: <deal>` / `Late delivery: <PO>` / `Approval required: …` /
    `Won lot awaiting Purchase Order: …` / `Orphan lot without parent tender: …` /
    `Invoice payment due: …`
  - Gerekçe: `Deadline past by 3 days` / `0/5 quotes · deadline today` /
    `Requested by <user>` / `Overdue by 5 days (Outstanding: 12,000.00)`
  - Üçüncü satır (`ds-row-ev`) **ham makine anahtarı** gösterir: `bid_due`,
    `policy_gap`, `po_late`, `approval_pending`, `won_no_po`, `no_parent`,
    `invoice_due`.
  - Rol görünümü seçicisinde seçenek metinleri ham id: `director`, `sourcing`,
    `declarant`, `logist`.
- **Kanıt:** `api/_desk_rules.py:66-113` (başlık/gerekçe f-string, çeviri yok),
  `api/_desk_rules.py:145-152, 174-181, 197-210, 234-247`,
  `OperationsDesk.vue:101` ve `:135` (`{{ item.kind }}` doğrudan basılıyor),
  `api/tender_desk.py:38` (`available_views` etiketi = ham id),
  `OperationsDesk.vue:29-31` (`t(v.label || v.id)`).

### S-03 · Tender CRM — dört durum

- **Ön koşul:** Rol `Sales User`, şirket `Mikas`,
  `https://mikas.erpstable.com/stabler#/tender/crm`
- **Adımlar:**
  1. **Yükleniyor:** Slow 3G ile yenile.
  2. **Boş:** Arama kutusuna `zzzz-yok` yaz.
  3. **Boş (gerçek):** `unseed()` sonrası aç.
  4. **Hata:** `stabler.api.tender.crm_board` isteğini engelle, "Yenile"ye bas.
  5. **Yetkisiz:** Tender kapalı bir şirkete geç.
- **Beklenen:**
  1. KPI şeridinin altında 4 satırlık iskelet (`crm-state` sarmalayıcısında).
  2. Adım 2'de **hiçbir boş durum çizilmez** — `EmptyState` koşulu `!cards.length`
     (ham liste), filtre sonucu değil. Kanban tüm kulvarları çizer, her kolonun
     altında küçük mono `boş` (`empty`) yazar; liste görünümünde `<tbody>` boş kalır.
  3. `EmptyState`: ikon `ti-address-book`, başlık **"Tender anlaşması bulunamadı."**,
     alt metin **"Mikas için aktif tender bulunamadı."**
  4. **Ekranda hiçbir şey değişmez.** Yalnız sağ üstte kırmızı toast:
     "Tender CRM yüklenemedi." Kartlar kaybolur, KPI'lar sıfırlanır (`cards` boş),
     kullanıcı bunun bir hata mı yoksa gerçekten veri yokluğu mu olduğunu ayırt
     edemez.
  5. Aynı: toast + boş ekran; "erişim yok" metni yoktur.
- **Kırık belirtisi:** 4 ve 5 numaralı davranışlar kusurdur (bkz. Eksikler).
  Ek olarak 2'de: filtre sıfır sonuç verdiğinde kullanıcıya "filtre yüzünden boş"
  denmiyor.
- **Kanıt:** `TenderCrm.vue:302-311` (durum blokları), `:39-51` (`load()` — hata
  yalnız toast, `activeCompany` yoksa sessiz `return`), `:385-387` (kolon boş metni),
  `:68-84` (filtre).

### S-04 · Direktör Panosu — dört durum

- **Ön koşul:** Rol `Stabler Tender Director`, şirket `Mikas`,
  `https://mikas.erpstable.com/stabler#/tender/portfolio`
- **Adımlar:**
  1. Slow 3G ile yenile.
  2. Bir filtre uygula (dashboard'dan gelen `?risk=...` gibi bir sorgu ekle) ve
     hiçbir satırın eşleşmemesini sağla.
  3. `stabler.api.tender.tender_director_board` isteğini engelle ve otomatik
     yenilemeyi bekle.
- **Beklenen:**
  1. Tablo gövdesinde **9 sütun × 6 satır** iskelet; `hide-first-on-mobile`
     nedeniyle dar ekranda ilk sütun iskeleti gizlenir.
  2. Panel altlığında iki satır: **"Bu filtrelere uyan tender yok."** ve
     **"Filtreleri temizleyin ya da başka bir gösterge paneli dönemi seçin."**
     Başlıkta sayaç `0 / 13 tender` okur.
  3. Yalnız toast: "Direktör panosu yüklenemedi." Tablo eski verisiyle ekranda
     kalır (`data` değişmez) — **bayat veri sessizce gösterilir**, "son okuma"
     saati de eski değerde donar.
- **Kırık belirtisi:** 3 numaralı davranış kusurdur: otomatik yenileme
  (`useAutoRefresh`) sessizce başarısız olurken ekran güncel görünmeye devam eder.
  Beklenen: "son okuma" bölgesinde bayatlık uyarısı.
- **Kanıt:** `DirectorBoard.vue:190` (iskelet), `:229-232` (boş), `:36-47`
  (`load()` — hata durumunda `data` korunuyor), `:41` (`lastReadAt`), `:65`
  (`useAutoRefresh`).

### S-05 · Süreç Akışı — eksik boş durum

- **Ön koşul:** Rol `Stabler Tender Director`, şirket `Mikas`, **demo veri
  YÜKLÜ DEĞİL** (`unseed()` çalıştırılmış),
  `https://mikas.erpstable.com/stabler#/tender/flow`
- **Adımlar:**
  1. Sayfayı aç, iskeletin geçmesini bekle.
  2. "Adım performansı" panelini oku.
- **Beklenen (kod ne yapıyor):** `_tender_flow.step_rows` **her zaman 5 satır**
  döndürür (`WORKING_STAGES` sabit), veri olmasa bile. Yani boş sitede tablo şu 5
  satırla çizilir: "Giriş — dosya açıldı", "GO / NO-GO kararı", "Teklif toplama",
  "Teklif fiyatlama", "Teklif gönderildi"; her satırda Açık = 0, ortalama/en kötü
  `—`, SLA sütununda **"Boş"** (`Empty`) durumu.
- **Kırık belirtisi:** Ekranda hiçbir zaman "veri yok" mesajı çıkmaz; tamamen boş
  bir kiracıda bile 5 satırlık dolu görünen bir tablo vardır. Buna karşılık API
  gerçekten hata verirse (istek engellenirse) `data` null kalır, `steps` boş dizi
  olur ve tablo **başlık satırı + tamamen boş gövde** olarak çizilir — bu, "boş"
  durumu için tasarlanmış bir görünüm değildir.
- **Kanıt:** `api/_tender_flow.py:19` (`WORKING_STAGES`), `:26-52` (`step_rows` her
  aşama için satır üretir), `:55-72` (`_state` → `empty`),
  `TenderFlow.vue:56` (`steps` fallback `[]`), `:157-201` (koşulsuz tablo),
  `TenderFlow.vue:61-67` (`STATE_LABEL`).

### S-06 · Demo veriyle Süreç Akışı'nın beklenen çıktısı (regresyon çapası)

- **Ön koşul:** Rol `Stabler Tender Director`, şirket `Mikas`, `seed()` taze
  çalıştırılmış, `https://mikas.erpstable.com/stabler#/tender/flow`
- **Adımlar:**
  1. KPI şeridindeki dört sayıyı oku.
  2. Tabloyu satır satır oku; "SLA" sütunundaki durum kelimelerini ve sol kenardaki
     kırmızı şeridi not al.
- **Beklenen (eşikler: seen 3 · go 5 · sourcing 14 · priced 3 · submitted 30 —
  `_tender_sla.py:31-37`; demo gün değerleri `seed_tender_demo.py:51-71`):**

  | Adım | Açık | Ortalama | SLA durumu |
  |---|---|---|---|
  | Giriş — dosya açıldı | 2 | 2.0 gün | **Sınırda** (`edge`) |
  | GO / NO-GO kararı | 2 | 4.5 gün | **Sınırda** (`edge`) |
  | Teklif toplama | 2 | 22.5 gün | **SLA aşıldı** (`out`) |
  | Teklif fiyatlama | 2 | 7.0 gün | **SLA aşıldı** (`out`) |
  | Teklif gönderildi | 2 | — | **Ölçülemiyor** (`unknown`), altında "2 damgasız — ortalamaya katılmadı" |

  KPI'lar: "Süreçte" = **10**, "SLA aşıldı" = **2 adım**, "Darboğaz" =
  **Teklif fiyatlama** (oran 7.0/3 = 2.33 > 22.5/14 = 1.61), "Ölçülemiyor" = **2**.
  Tabloda "Teklif fiyatlama" satırının ilk hücresinde **3px kırmızı sol şerit** olur.
- **Kırık belirtisi:** Darboğaz "Teklif toplama" görünüyorsa oran yerine fark
  kullanılıyordur; "Teklif gönderildi" satırı 0 gün ortalama gösteriyorsa
  ölçülemeyen kayıtlar ortalamaya katılmıştır (`_tender_flow.py:11-15` bunu açıkça
  yasaklıyor); won/lost adımları tabloda görünüyorsa `WORKING_STAGES` bozulmuştur.
- **Kanıt:** `api/_tender_flow.py:19,26-52,55-72,75-91`, `api/_tender_sla.py:31-37`,
  `maintenance/seed_tender_demo.py:51-71`, `TenderFlow.vue:171` (darboğaz işareti),
  `stabler-modernist.css` (`tr[data-bottleneck="1"]` kuralı TenderFlow.vue:233-235
  içinde scoped).

### S-07 · Dil matrisi — beş dilde çerçeve metinleri

- **Ön koşul:** Rol `Stabler Tender Director`, şirket `Mikas`, demo veri yüklü
- **Adımlar:** Her dil için (`en`, `ru`, `tr`, `uz`, `uzc`):
  1. Kenar çubuğu → kullanıcı menüsü → dili seç, sayfanın yeniden yüklenmesini bekle.
  2. `#/tender/portfolio`, `#/tender/flow`, `#/tender/crm`, `#/tender/desk`
     ekranlarını sırayla aç.
  3. Her ekranda: H1, KPI etiketleri, tablo başlıkları, panel altlığındaki kaynak
     beyanını oku.
- **Beklenen:** Çerçeve metinlerinin hepsi seçilen dilde. `Остаток (net remaining)`
  **her dilde aynı kalır** (bilinçli Rusça terim, DirectorBoard.vue:107,183).
  Panel altlıklarındaki teknik kaynak beyanları da her dilde İngilizce/mono kalır:
  `tender_lot · quotation · sales_order · purchase_order` (DirectorBoard.vue:235),
  `crm_deal · custom_tender_stage_entered_at` (TenderFlow.vue:205) — bunlar bilinçli
  sabit, çeviri beklenmez.
- **Kırık belirtisi:** KPI kartlarının alt satırındaki "kural" metinleri
  (DirectorBoard.vue:83,90,94,99,104,109) çevrilmemiş çıkarsa: bunların bir kısmı
  zaten kasten ham SQL benzeri ifadedir (`tender_lot · result = null`), ama
  `t()`den geçen notlar (`seen through to awaiting result`) çevrilmiş olmalıdır.
- **Kanıt:** `Sidebar.vue:32-38, 200-211` (dil değişimi), `DirectorBoard.vue:77-112`,
  `TenderFlow.vue:76-115`.

---

## 4. Erişilebilirlik ve okunabilirlik

### A-01 · Severity yalnız renkle mi anlatılıyor (Operasyon Masası)

- **Ön koşul:** Rol `Stabler Tender Director`, şirket `Mikas`, demo veri yüklü,
  `https://mikas.erpstable.com/stabler#/tender/desk`
- **Adımlar:**
  1. Chrome DevTools → Rendering → "Emulate vision deficiencies" →
     **Achromatopsia** (tam renk körlüğü).
  2. İş planı listesinde her satırın sol sütununu oku.
  3. Bantları (grup başlıklarını) oku.
  4. "Sıradaki iş" kartının üst satırını oku.
- **Beklenen:** Renk kaldırıldığında bilgi kaybı olmaz, çünkü üç işaret birden var:
  - **Metin:** her satırda 3-4 harflik kod — `OVD` / `TDY` / `SOON` / `WCH`
    (OperationsDesk.vue:375-382).
  - **Şekil:** severity kutucuğu dolu kare (crit/today), 1.5px **kenarlıklı** kare
    (soon), 1px **noktalı** kenarlık (info) — üç farklı şekil
    (css:300-307).
  - **Bant:** grup başlığında tam kelime ("Geciken" / "Bugün" / "Yakında" /
    "İzlemede") + kural açıklaması ("son tarih geçti — bugün harekete geç").
  - Lider kart: "Sıradaki iş · Geciken" biçiminde tam metin.
- **Kırık belirtisi:** Kod harfleri yerine boş `<span>`; ya da `sevShort()` bilinmeyen
  bir severity'de **boş string** döndürdüğü için renk körü kullanıcı hiçbir metin
  görmüyor (OperationsDesk.vue:381 — `|| ""`). Sunucu `SEVERITY` listesi dışında bir
  değer üretirse (bugün üretmiyor) satır sessizce etiketsiz kalır.
- **Kanıt:** `OperationsDesk.vue:131, 366-382`,
  `stabler-modernist.css:297-307`, `api/_desk_rules.py:10` (`SEVERITY`).

### A-02 · SLA durumu (Süreç Akışı)

- **Ön koşul:** Rol `Stabler Tender Director`, `#/tender/flow`, demo veri yüklü
- **Adımlar:**
  1. Achromatopsia simülasyonunu aç.
  2. "SLA" sütunundaki 5 hücreyi oku.
  3. "Ortalama bekleme" sütunundaki değerleri oku.
- **Beklenen:** SLA hücresi **her zaman kelime** taşır: "İçinde" / "Sınırda" /
  "SLA aşıldı" / "Ölçülemiyor" / "Boş" (`ds-sla` mono, büyük harf) ve altında eşik
  satırı ("eşik 14 gün" veya "izlenmiyor"). "Ortalama bekleme" hücresinde renk tek
  başına kalır (`ds-wait` yalnız `edge`/`out`ta renkleniyor) ama aynı satırın SLA
  hücresi kelimeyi verdiği için bilgi kaybı yok.
- **Kırık belirtisi:** SLA hücresinde yalnız renkli bir nokta/çubuk; ya da
  "Ölçülemiyor" ile "Boş" aynı kelimeye indirgenmiş (ikisi ayrı olmalı —
  `_tender_flow.py:55-64`).
- **Kanıt:** `TenderFlow.vue:61-67, 192-198`, `stabler-modernist.css:859-865`.

### A-03 · Risk göstergesi (Tender CRM) — etiket ile kural uyuşmuyor

- **Ön koşul:** Rol `Sales User`, `#/tender/crm`, demo veri yüklü
- **Adımlar:**
  1. Liste görünümüne geç ("Liste" düğmesi).
  2. "Son tarih riski" sütununu oku; her satırdaki metni not al.
  3. Achromatopsia ile tekrarla.
  4. Üstteki "Son tarih" (`Deadline`) KPI kartının sayısını ve alt satırındaki
     kuralı oku.
- **Beklenen (erişilebilirlik):** Her risk hücresi `ds-chip` içinde **kelime**
  taşır: "Yolunda" / "Uyarı" / "Risk (<=48s)" / "Süresi doldu". Chip'in solunda
  7px `currentColor` kare vardır, yani renk + metin birlikte.
- **Kırık belirtisi (içerik):** **Bilinen açık** — KPI kartının alt satırı
  "son teklif tarihine 48 saat kaldı ya da geçti" diyor; `risk` etiketi de
  "Risk (<=48s)" diyor. Gerçek sunucu kuralı farklı: `risk` **yalnız son tarih
  geçmişse** verilir, 7 güne kadar olan her şey `warn`dır. Demo veriyle:
  - `UTY-2026-4305` (son tarih **dün**) → `risk` ✔
  - `UTY-2026-4308` (son tarih **bugün**) → `warn` ✘ (48 saat içinde ama sayılmıyor)
  - `UTY-2026-4310` (son tarih **2 gün sonra**) → `warn` ✘
  Yani "Son tarih" KPI'sı **1** gösterir, oysa notu okuyan kullanıcı **3** bekler.
- **Kanıt:** `TenderCrm.vue:128-133` (KPI notu), `:233-244` (`riskLabel`),
  `:58-62` (`KPI_TESTS.deadline` = `risk` veya `expired`),
  `api/tender.py:1528-1535` (`_milestone`: `days < 0 → risk`, `days <= 7 → warn`),
  `maintenance/seed_tender_demo.py:75-85` (`DEADLINE_OFFSETS`).

### A-04 · Tıklanabilirlik sinyali — KPI kartları

- **Ön koşul:** Rol `Stabler Tender Director`
- **Adımlar:**
  1. `#/tender/desk` aç, KPI kartlarının üzerine gel; imleci ve arka planı not al.
  2. Bir karta tıkla; listenin filtrelendiğini ve kartın koyulaştığını doğrula.
  3. `#/tender/portfolio` aç, aynı hareketleri 6 KPI kartında dene.
  4. `#/tender/flow` aç, 4 KPI kartında dene.
- **Beklenen:** Tıklanabilir kartlar `<button>`, `aria-pressed` taşır ve basılıyken
  koyu zemin + beyaz metin olur (`css:233-235`). Tıklanamayan kartlar imleç
  değiştirmemelidir.
- **Kırık belirtisi:** **Bilinen açık** — `.ds-kpi` sınıfı CSS'te koşulsuz
  `cursor: pointer` ve `:hover { background: #fafbfc }` taşıyor. Direktör panosu
  (`<div class="ds-kpi">`, DirectorBoard.vue:151) ve Süreç akışı
  (`<div class="ds-kpi">`, TenderFlow.vue:137) kartları **düğme değil**: imleç el
  şekline döner, arka plan hover'da değişir, ama tıklama hiçbir şey yapmaz.
  Klavyeyle odaklanılamaz da (tabindex yok). Operasyon Masası ve CRM'de kartlar
  gerçekten `<button>` (OperationsDesk.vue:44-51, TenderCrm.vue:287-295).
- **Kanıt:** `stabler-modernist.css:229-235`, `DirectorBoard.vue:151`,
  `TenderFlow.vue:137`, `OperationsDesk.vue:44-51`, `TenderCrm.vue:287-295`.

### A-05 · Kanban kartı klavyeyle kullanılabiliyor mu

- **Ön koşul:** Rol `Sales User`, `#/tender/crm`, demo veri yüklü, **fare
  kullanmadan**
- **Adımlar:**
  1. Sayfa yüklendikten sonra Tab tuşuyla ilerle; odağın sırayla arama kutusuna,
     Kanban/Liste düğmelerine, Yenile'ye, 4 KPI kartına, sonra kartlara gittiğini
     doğrula.
  2. Bir kartta Enter'a bas.
  3. Çekmece açıldıktan sonra Tab'a basmaya devam et; odağın nereye gittiğini izle.
  4. `Esc` tuşuna bas.
- **Beklenen:** Adım 2'de çekmece açılır (`@keydown.enter` ve `@keydown.space`
  bağlı, `role="button" tabindex="0"`).
- **Kırık belirtisi:** **Üç açık birden:**
  1. Çekmece açıldığında **odak taşınmıyor** — odak arkadaki kartta kalır, ekran
     okuyucu `role="dialog" aria-modal="true"` bir panelin açıldığını duyurmaz.
  2. **Odak tuzağı yok** — Tab, çekmecenin dışındaki kartlara ve kenar çubuğuna
     kaçar; `aria-modal` bunu iddia etmesine rağmen.
  3. **`Esc` çekmeceyi kapatmıyor** — `TenderCrm.vue` `useEscapeBack` import
     etmiyor (DirectorBoard.vue:29, MyTenders.vue:25, DeclarantQueue.vue:25,
     LogistBoard.vue:25, PoControlBoard.vue:30 ediyor). Kapatmanın tek yolu ✕
     düğmesi, "Kapat" düğmesi veya arka plana tıklamaktır.
  4. Ayrıca **sürükle-bırak ile aşama değiştirmenin klavye alternatifi yok**
     (`draggable="true"` + `dragstart`, klavye eşdeğeri tanımlı değil) — kart
     taşımak yalnız fare/dokunmatik ile mümkün.
- **Kanıt:** `TenderCrm.vue:338-349` (kart), `:448-459` (çekmece, odak yönetimi
  yok), `:211-214` (`closeDrawer`), `:1-20` (import listesinde `useEscapeBack` yok),
  `:157-182` (drag & drop).

### A-06 · Takvim şeridi bilgisini yalnız tooltip'te tutuyor

- **Ön koşul:** Rol `Stabler Tender Director`, `#/tender/desk`, demo veri yüklü
- **Adımlar:**
  1. Sağ sütunda "Önümüzdeki 7 gün" panelini bul.
  2. Bir güne fareyle gel, tooltip'i oku.
  3. Aynı bilgiye klavye ile ulaşmayı dene (Tab ile güne odaklan).
  4. Dokunmatik cihazda (veya DevTools cihaz emülasyonunda) aynı bilgiyi almayı dene.
- **Beklenen (kod ne yapıyor):** Gün kutusu üç şey gösterir: gün kısaltması (Pzt,
  Sal…), iki haneli gün numarası, ve iş sayısı (yoksa `—`). Bugünün kutusu
  `--ds-crit-t` arka planla, hafta sonları `opacity: .55` ile ayrılır.
- **Kırık belirtisi:** Hangi işlerin o güne düştüğü **yalnız `title` özniteliğinde**
  (en fazla 2 kalem, `api/tender_desk.py:264`). Gün kutusu `<div>`, odaklanılamaz,
  `tabindex` yok → klavye ve dokunmatik kullanıcı bu bilgiye hiç ulaşamaz. Ayrıca
  bugün kutusu **kırmızımsı** (`--ds-crit-t`) zemin alır: renk körü kullanıcı için
  "bugün" ile "kritik" aynı sinyale benzer; ayırt edici metin yok.
- **Kanıt:** `OperationsDesk.vue:225-238` (`:title="day.tooltip"`, `:447`),
  `stabler-modernist.css:354-359`, `api/tender_desk.py:258-265`.

### A-07 · Ekip yükü çubuğu

- **Ön koşul:** Rol `Stabler Tender Director` (gözetim rolü), `#/tender/desk`
- **Adımlar:**
  1. "Ekip yükü" panelini bul (yalnız gözetim rolünde çizilir).
  2. Achromatopsia ile çubukları oku.
  3. Panel altlığındaki açıklamayı oku.
- **Beklenen:** Her satırda kullanıcı adı + oransal çubuk + sağda **sayı** (açık lot
  adedi). Sayı olduğu için çubuk uzunluğu tek bilgi kaynağı değildir. Altlıkta iki
  açıklama: "Çubuk en yoğun kuyruğa göredir" ve "kırmızı = gecikmiş var".
- **Kırık belirtisi:** "Gecikmiş var" durumu **yalnız `data-warn="1"` üzerinden
  renkle** anlatılıyor; satırda "gecikmiş" diye bir metin ya da ikon yok. Renk körü
  kullanıcı hangi ekip üyesinin gecikmiş işi olduğunu göremez — altlıktaki
  "kırmızı = gecikmiş var" açıklaması da renge referans verdiği için ona
  yardımcı olmaz.
- **Kanıt:** `OperationsDesk.vue:202-217` (`:data-warn`), `:425-432` (`teamLoad`),
  `api/tender_desk.py:267-278` (`overdue_lots`).

### A-08 · Rozet metinleri (göç etmemiş ekranlar)

- **Ön koşul:** Rol `Stabler Declarant`, `#/tender/customs`, demo veri yüklü
- **Adımlar:**
  1. Achromatopsia ile "Durum" sütununu oku.
  2. "Kalan gün" sütununu oku.
  3. `#/tender/logistics` için tekrarla.
- **Beklenen:** Durum rozetleri her zaman kelime taşır: "Temizlendi" / "Devam
  ediyor" / "Beklemede" (DeclarantQueue.vue:51); lojistikte "Teslim edildi" /
  "Yolda" / "Gecikti" (LogistBoard.vue:51). "Kalan gün" hücresi de metindir:
  "3 gün kaldı" / "5 gün gecikti" / "bugün" — renk (`text-red` / `text-yellow`)
  yalnız vurgudur, tek bilgi kaynağı değildir.
- **Kırık belirtisi:** Bilinmeyen bir durum kodu gelirse rozet **ham makine
  anahtarını** basar (`|| s`, DeclarantQueue.vue:51) — kullanıcıya `in_progress`
  gibi bir string görünür.
- **Kanıt:** `DeclarantQueue.vue:50-57, 82-83`, `LogistBoard.vue:50-51, 75-76`.

### A-09 · Tedarik politikası ölçeri (5 kutucuk)

- **Ön koşul:** Rol `Sales User`, `#/tender/crm`, demo veri yüklü
- **Adımlar:**
  1. Kanban'da herhangi bir kartın alt bölümündeki 5 kutucuklu ölçere bak.
  2. Yanındaki metni oku.
  3. Achromatopsia ile tekrarla.
- **Beklenen:** Ölçerin yanında **her zaman** `N/5 teklif` yazar
  (TenderCrm.vue:371); dolu/boş kutucuk ayrımı `data-on` ile yapılır (dolgu farkı,
  yalnız renk değil). Politika tamamsa `data-full="1"` ile ölçer bütün olarak
  vurgulanır ama sayı zaten metindedir.
- **Kırık belirtisi:** Demo veriyle **hepsi `0/5` gösterir** — bkz. Şüphe #11:
  seed dosyası `sq_count` değerini hiçbir yere yazmıyor, gerçek Supplier Quotation
  kaydı üretmiyor. Bu bir a11y kusuru değil, veri kusurudur, ama bu senaryoyu
  "5/5 dolu ölçer" ile test etmeyi imkânsız kılar.
- **Kanıt:** `TenderCrm.vue:153-154, 367-372`,
  `maintenance/seed_tender_demo.py:122` (`sq_count` parametresi kullanılmıyor),
  `api/tender.py:2328-2352` (sq sayımı Supplier Quotation tablosundan).

---

## 5. Responsive davranış

### R-01 · Operasyon Masası — iki sütun tek sütuna

- **Ön koşul:** Rol `Stabler Tender Director`, `#/tender/desk`, demo veri yüklü
- **Adımlar:**
  1. Pencereyi 1440px genişlikte aç; iş planı ile yan sütunun oranını not al.
  2. Pencereyi yavaşça daralt, 993px ve 991px'te ekranı karşılaştır.
  3. 375px'e (iPhone SE) indir.
- **Beklenen:**
  - ≥993px: `desk-grid` iki sütun, **1.62fr / 1fr** oranı.
  - ≤992px: tek sütun — iş planı üstte, karar kutusu / ekip yükü / 7 gün altta.
  - ≤992px'te ayrıca: KPI şeridi 4 sütundan **2×2**'ye düşer, H1 28px'e iner,
    liste satırı `54px 1fr 22px` ızgarasına geçer ve sahip/tarih bloğu ikinci
    satıra sarkar (`ds-row-right` → `grid-column: 2`).
- **Kırık belirtisi:** 992px'in hemen altında yatay kaydırma çubuğu; ya da yan
  sütun panelleri iş planının üstüne çıkıyor (sıra `desk-side` şablonda ikinci
  olduğu için altta olmalı).
- **Kanıt:** `OperationsDesk.vue:539-556`, `stabler-modernist.css:445-452`.

### R-02 · 7 günlük takvim şeridi dar ekranda

- **Ön koşul:** `#/tender/desk`, 375px genişlik
- **Adımlar:**
  1. Cihaz emülasyonunu iPhone SE (375px) yap.
  2. "Önümüzdeki 7 gün" paneline in.
  3. Gün kutularının içindeki üç satırı (gün adı, gün no, sayı) oku.
- **Beklenen (kod ne öngörüyor):** `ds-week` **sabit `repeat(7, minmax(0,1fr))`**
  ızgarası; dar ekran için **hiçbir media query yok**. 375px'te panelin iç
  genişliği ~343px, 7 sütuna bölününce **kutu başına ~49px**, iç boşluk `10px 8px`
  düşünce içerik için ~33px kalır.
- **Kırık belirtisi:** 17px'lik gün numarası (`ds-week-n`) ve 3 harfli gün
  kısaltması bu genişliğe sığmaz — kırpılma, taşma veya satır kaydırma görülür.
  `minmax(0,1fr)` taşmayı engeller ama metin kesilir. Karşılaştırma: KPI şeridi
  (css:445-452), aşama ızgarası (css:548-551), form ızgaraları (css:805-810) ve
  akış diyagramı (css:877-879) için dar ekran kuralı **var**; takvim şeridi için
  **yok**.
- **Kanıt:** `stabler-modernist.css:354-360` (tek `ds-week` bloğu, media query
  içermiyor), `OperationsDesk.vue:225-238`.

### R-03 · Kanban dar ekranda

- **Ön koşul:** Rol `Sales User`, `#/tender/crm`, demo veri yüklü, 375px genişlik
- **Adımlar:**
  1. Kanban görünümünde ol.
  2. Kolon şeridini parmakla/fareyle yatay kaydır.
  3. Sayfanın kendisinin yatay kayıp kaymadığını kontrol et (gövde `overflow-x`).
  4. Bir kartı başka bir kulvara sürüklemeyi dene.
- **Beklenen:** `ds-kanban` yatay kaydırmalı bir şerittir (`display: flex;
  overflow-x: auto`); her kolon **sabit 268px** (`flex: 0 0 268px`) — daralmaz.
  375px'te yaklaşık **1.3 kolon** görünür, kalan 5 kulvar yatay kaydırma ile gelir.
  Sayfanın kendisi kaymaz, yalnız şerit kayar.
- **Kırık belirtisi:**
  - Kaydırma çubuğu görünmüyorsa (macOS overlay scrollbar) kullanıcı 7 kulvarın
    varlığını hiç fark etmez — kaydırma göstergesi/gölge yok.
  - **Sürükle-bırak + yatay kaydırma çakışması:** dokunmatik cihazda kartı
    kulvarın dışına sürüklerken otomatik kaydırma (auto-scroll) tanımlı değil;
    görünmeyen bir kulvara kart taşımak imkânsızdır.
  - `ds-col` genişliği sabit olduğu için 268px'ten dar cihazlarda (320px eksi
    sayfa padding'i) kolon kenarı kırpılır.
- **Kanıt:** `stabler-modernist.css:362-370`, `TenderCrm.vue:315-324` (drop
  hedefi kolonun kendisi), `TenderCrm.vue:618-627`.

### R-04 · Direktör panosu tablosu dar ekranda

- **Ön koşul:** Rol `Stabler Tender Director`, `#/tender/portfolio`, demo veri yüklü
- **Adımlar:**
  1. 1440px'te 9 sütunun hepsini say: Sıra · Tender · Değer · Ciro marjı · Landed ·
     Остаток · Teslim son tarihi · Risk · Yönetici.
  2. 767px'e daralt; sütun sayısını tekrar say.
  3. Tabloyu yatay kaydır; sayfanın kendisinin kaymadığını doğrula.
  4. "Yönetici" sütunundaki `select`'i aç.
- **Beklenen:**
  - ≤768px: **"Sıra" sütunu tamamen gizlenir** (`board-ord { display:none }`), 8
    sütun kalır.
  - Tablo `board-scroll` sarmalayıcısı içinde **kendi başına** yatay kayar; sayfa
    kaymaz (yorum bunu açıkça söylüyor: "sayfayı değil TABLOYU kaydır").
  - "Yönetici" sütunu 190px sabit; select 34px yüksekliğinde. Select'e tıklamak
    satır tıklamasını **tetiklemez** (`@click.stop`).
- **Kırık belirtisi:** Sayfa gövdesi yatay kayıyorsa `board-scroll` etkisiz;
  select'e tıklayınca PO kontrol ekranına atlıyorsa `@click.stop` düşmüş; iskelet
  satırları dar ekranda 9 sütunu zorluyorsa `hide-first-on-mobile` çalışmıyor.
- **Kanıt:** `DirectorBoard.vue:269-272, 302-307, 324-328, 190, 213`.

### R-05 · Modül üst menüsü dar ekranda

- **Ön koşul:** Rol `System Manager` (dört görünüm birden açılsın → menü en uzun
  hâlinde), şirket `Mikas`, `#/tender/logistics`, 375px genişlik
- **Adımlar:**
  1. Üst menüyü say: marka + 10 bağlantı çizilmeli.
  2. Şeridi sağa kaydır, son bağlantının ("Lojistik") görünür olduğunu doğrula.
  3. Sayfayı yenile ve **kaydırmadan** şeridin başlangıç konumuna bak.
- **Beklenen:** `ds-modnav` `overflow-x: auto` ve tüm `<a>` öğeleri
  `white-space: nowrap` — şerit yatay kayar, sarmaz.
- **Kırık belirtisi:** **Aktif sekme görünür alanın dışında kalır.** Şerit her
  yüklemede en soldan başlar; aktif sekmeyi görünüre getiren bir `scrollIntoView`
  yok. `#/tender/logistics`teyken 375px'de kullanıcı yalnız "Tender · Genel
  bakış · Ope…" kadarını görür ve hangi ekranda olduğunu üst menüden anlayamaz —
  aktif işaret (alt çizgi) ekranın dışındadır. Dar ekran için "daha fazla"
  menüsü veya kaydırma göstergesi de yok.
- **Kanıt:** `stabler-modernist.css:202-221`, `TenderNav.vue:28-63` (JS ile
  kaydırma yok), `TenderNav.vue:66-77` (yalnız marj kuralları).

### R-06 · Çekmece (drawer) dar ekranda

- **Ön koşul:** Rol `Sales User`, `#/tender/crm`, demo veri yüklü
- **Adımlar:**
  1. 1024px genişlikte bir kart aç; çekmece genişliğini not al.
  2. 639px'e daralt; çekmeceyi tekrar aç.
  3. Çekmece içindeki "Aşama ilerlemesi" şeridine bak (7 aşama).
- **Beklenen:**
  - ≥641px: çekmece sağdan 542px genişlikte gelir, solunda 2px koyu kenar.
  - ≤640px: çekmece **tam ekran** olur (`width: 100vw`), sol kenarlık kalkar.
  - 7 aşamalı adım şeridi **sarar** (`flex-wrap: wrap`, her adım `flex: 1 1 25%`
    → 4+3 düzeni); ilk 4 adımın üst kenarlığı kaldırılmıştır. Aşama adları
    kırpılmaz.
- **Kırık belirtisi:** Aşama adları "GO DECİ…" gibi kırpılıyorsa
  `TenderCrm.vue:721-732` kuralı düşmüştür (yorum bu kusuru açıkça anlatıyor);
  tam ekran çekmecede kapatma düğmesi erişilemiyorsa `ds-drawer-head` sabit
  kalmamıştır.
- **Kanıt:** `stabler-modernist.css:641-649, 691-695`,
  `TenderCrm.vue:718-732`.

### R-07 · Göç etmemiş tabloların dar ekran davranışı

- **Ön koşul:** Rol `Stabler Declarant`, `#/tender/customs`, demo veri yüklü,
  375px genişlik
- **Adımlar:**
  1. 8 sütunlu gümrük tablosunu aç (PO · Tedarikçi · Tender · ТН ВЭД · Gümrük ·
     PO ETA · Kalan gün · Durum).
  2. Yatay kaydırmayı dene: önce tablonun üzerinde, sonra sayfanın kenarında.
  3. `#/tender/logistics` (7 sütun) ve `#/tender/my-tenders` (5 sütun) için
     tekrarla.
  4. Karşılaştırma: `#/tender/po-control` → "Tedarikçi karşılaştırma (landed)"
     tablosu (8 sütun) için tekrarla.
- **Beklenen (kod ne öngörüyor):** PO kontrol ekranındaki karşılaştırma tablosu
  `<div class="table-responsive">` içinde — kendi başına yatay kayar.
- **Kırık belirtisi:** **Gümrük kuyruğu, Lojistik ve Benim tenderlarım
  tablolarında `table-responsive` sarmalayıcısı YOK** — tablo doğrudan
  `card-body p-0` içinde. 8 sütunlu gümrük tablosu 375px'te ya sayfayı yatay
  kaydırır ya da hücreleri okunamayacak kadar sıkıştırır; "PO ETA" ve "Kalan gün"
  sütunları `text-nowrap` taşıdığı için sıkışamaz ve taşmayı zorlar.
- **Kanıt:** `DeclarantQueue.vue:66-88` (sarmalayıcı yok),
  `LogistBoard.vue:60-81` (yok), `MyTenders.vue:100-118` (yok),
  `PoControlBoard.vue:413-447` (`table-responsive` var).

---

## Eksikler — kodda karşılığı yok

Bu maddeler için ekranda test edilecek bir davranış **bulunmadı**. Senaryo
yazılmadı; ürün kararı gerekiyor.

1. **`/tender` modül kökü yok.** Diğer 14 modülün hepsinde `/modul` bir hub'a ya da
   ilk alt ekrana redirect ediyor (`router.js:205, 282, 304, 331, 350, 369, 379,
   409, 428, 441, 451, 463, 474, 489, 498`). Tender'da karşılığı yok; `#/tender`
   NotFound'a düşüyor. `TenderNav.vue:5-7` yorumu "her modülün bir `*Home.vue`
   hub'ı var" diyor — tender'ın yok.
2. **Operasyon Masası'nda modül üst menüsü yok.** `OperationsDesk.vue` `TenderNav`
   import etmiyor. Yeni mimarinin ana ekranı, mimarinin gezinme kuralına uymuyor.
3. **`/tender/board` ve `/tender/sourcing`'de modül üst menüsü yok.** İlki kenar
   çubuğunun tender'a giriş noktası (`Sidebar.vue:79`), ikincisi CRM çekmecesinin
   birincil eylemi (`TenderCrm.vue:576-580`).
4. **Üst menüde "Tedarik karşılaştırma" (`/tender/sourcing`) girdisi yok.** Rota
   var (`router.js:270`), iki ekrandan bağlantı var, menüde yok.
5. **Tender CRM'de hata durumu yok.** API çökerse ekran boş kalır, yalnız toast
   çıkar; kullanıcı "veri yok" ile "yüklenemedi"yi ayıramaz (`TenderCrm.vue:46-48`).
   Aynı eksik Direktör Panosu (`:42-44`) ve Süreç Akışı'nda (`:38-40`).
6. **Tender CRM'de "yetkisiz" ve "şirket seçili değil" durumları yok.**
   `load()` `activeCompany` yoksa sessizce çıkıyor (`TenderCrm.vue:40`) — ekran
   sonsuz "boş" görünür. Karşılaştırma: OperationsDesk.vue:73-78'de ikisi de var.
7. **Süreç Akışı'nda boş durum yok.** Tablo koşulsuz çiziliyor
   (`TenderFlow.vue:157`); API hatasında başlıklı ama gövdesi tamamen boş bir tablo
   kalıyor.
8. **Filtre sonucu boş ile veri yok ayrımı Tender CRM'de yok.** `EmptyState` koşulu
   `!cards.length` (`TenderCrm.vue:307`), `filteredCards` değil.
9. **Operasyon Masası satır metinleri i18n dışı.** Başlık, gerekçe ve `kind`
   sunucuda İngilizce üretiliyor ve hiçbir çeviri katmanından geçmiyor
   (`api/_desk_rules.py` boyunca). Beş dilin dördünde bu satırlar İngilizce kalır.
10. **Rol görünümü seçicisinin etiketleri ham id.** `api/tender_desk.py:38`
    `{"id": v, "label": v}` üretiyor; kullanıcıya `director` / `sourcing` /
    `declarant` / `logist` görünür.
11. **Lot numarası (UTY-2026-43xx) yeni panoların hiçbirinde görünmüyor.** CRM
    kartının başlığı `_deal_label()` = organizasyon adı (`api/tender.py:1850-1855`),
    alt satırı CRM Deal id'si. Operasyon Masası satır başlığı da deal id'si
    (`api/tender_desk.py:200` → `"label": d.get("name")`). Lot no yalnız intake
    JSON'unun içinde yaşıyor ve PO kontrol ekranındaki intake düzenleyicisinde
    görünüyor (`TenderIntake.vue:48`). Sonuç: demo veride dört kart aynı başlığı
    taşır ("O'zbekiston temir yo'llari AJ [DEMO]" — 4301, 4305, 4310, 4315) ve
    birbirinden ayırt edilemez.
12. **Takvim şeridi için dar ekran kuralı yok** (`css:354-360`).
13. **Modül üst menüsünde aktif sekmeyi görünüre kaydırma yok** ve dar ekran için
    taşma menüsü yok (`TenderNav.vue`).
14. **Çekmecede odak yönetimi / odak tuzağı / Esc kapatma yok**
    (`TenderCrm.vue:448-459`).
15. **Kanban'da klavye ile aşama değiştirme yok** (`TenderCrm.vue:157-182`).
16. **Ekip yükü satırında "gecikmiş" durumu için metin yok** — yalnız
    `data-warn` rengi (`OperationsDesk.vue:202-217`).
17. **Gümrük kuyruğu / Lojistik / Benim tenderlarım tablolarında
    `table-responsive` yok.**
18. **`aria-live` bölgesi yok.** Filtre değişince "N kalem" sayacı sessizce
    güncelleniyor; ekran okuyucu değişimi duyurmaz (`OperationsDesk.vue:65-68`).
19. **Bayat veri uyarısı yok.** Otomatik yenileme başarısız olunca "son okuma"
    saati donuyor ama ekran hâlâ güncelmiş gibi duruyor
    (`DirectorBoard.vue:36-47`).

---

## Kod okumasından çıkan şüpheler

Sırayla: en ciddi olandan başlayarak.

### Ş-01 · Operasyon Masası son tarih okumasını yanlış yerden alıyor (yüksek)

`tender_desk.py` teklif son tarihini **CRM Deal kolonundan** okuyor:
`custom_bid_deadline` / `bid_deadline` / `expected_closing`
(`api/tender_desk.py:57-58, 83, 202`). Buna karşılık modüldeki diğer her uç son
tarihi **intake JSON'undan** okuyor: `intake.get("bid_deadline")`
(`api/tender.py:1584, 2246, 2581, 2640`) ve seed de yalnız JSON'a yazıyor
(`seed_tender_demo.py:132`).

Sonuç: demo veride masanın `bid_deadline` alanı `None` kalır → `_desk_rules`
**hiçbir** `bid_due` / `bid_soon` kalemi üretmez (`_desk_rules.py:56-100`). Yani
CRM ekranı `UTY-2026-4305` için "Risk" chip'i gösterirken, Operasyon Masası aynı
lot için tek satır bile göstermez. "İki ekranın farklı sayı göstermesi ikisine de
güveni bitirir" ilkesi (TenderFlow.vue:8-9) tam burada kırılıyor.
**Doğrulama:** seed'i çalıştır, `#/tender/desk` ve `#/tender/crm` ekranlarını
karşılaştır. Eğer kolon başka bir yerde (hooks / patch) JSON'dan senkronlanıyorsa
bu şüphe düşer — o dosyalar bu pakette yok.

### Ş-02 · "Bekleyen onay" sayacı fazla sayıyor, "Diğerlerini bekleyen" direktörde hep 0 (yüksek)

```python
decisions = [a for a in all_pending_approvals
             if a.get("assigned_to") == user or a.get("requested_by") != user or oversight]
```
(`api/tender_desk.py:228-231`)

`or a.get("requested_by") != user` koşulu, **bana atanmamış** onayları da "benim
kararım" sayıyor: başkasına atanmış her talep KPI'ya giriyor. Kartın alt satırı
"onay sana atanmış" (`OperationsDesk.vue:348`) diyor — sayı bu kuralı taşımıyor.

Devamında:
```python
waiting_others = [a for a in all_pending_approvals
                  if a.get("requested_by") == user and a not in decisions]
```
`oversight` True olan bir kullanıcıda `decisions` **tüm** talepleri kapsadığı için
`waiting_others` **her zaman boş** olur. Direktör "Diğerlerini bekleyen" sayacını
kalıcı olarak `0` görür; o KPI'ya basınca liste de boş gelir.
**Doğrulama:** iki farklı kullanıcıyla bekleyen onay oluştur, direktör olarak
`#/tender/desk` aç; dört sayacın toplamı ile listedeki kalem sayısını kıyasla.

### Ş-03 · Panolar tenderı adıyla göstermiyor (yüksek)

`api/tender_desk.py:200` → `"label": d.get("name")` (CRM Deal id'si),
`api/tender.py:1850-1855` → `_deal_label` = organizasyon adı. Lot numarası
(`UTY-2026-4301`) yalnız intake JSON'unda. Demo veride bu, dört adet birbirinin
aynısı başlıklı CRM kartı ve `Bid due: CRM-DEAL-2026-000xx` biçiminde masa satırları
üretir. Kullanıcı hangi lotla uğraştığını ekrandan okuyamaz.

### Ş-04 · CRM "Son tarih" KPI'sının notu kuralı yanlış anlatıyor (orta-yüksek)

KPI notu: "son teklif tarihine 48 saat kaldı ya da geçti" (`TenderCrm.vue:132`);
chip etiketi "Risk (<=48s)" (`TenderCrm.vue:236`). Sunucu kuralı:
`days < 0 → risk`, `0 <= days <= 7 → warn`, aksi `good`
(`api/tender.py:1528-1535`). 48 saat kavramı kodun hiçbir yerinde yok. Demo veride
KPI **1** gösterir, oysa 48 saat kuralı uygulansaydı **3** olurdu (4305, 4308, 4310).
Tasarımın "her rakam kendi sorgusunu taşır" ilkesi burada tersine dönüyor: rakam
yanlış sorguyu beyan ediyor.

### Ş-05 · `expired` riski en düşük önem seviyesine düşürülüyor (orta)

```js
case "expired": return "info";
```
(`TenderCrm.vue:227-228`) — süresi dolmuş bir son tarih, `ds-chip[data-tone="info"]`
ile en sönük tona (noktalı kenarlık, gri) düşüyor; `risk` ise `crit`. Süresi geçmiş
bir teklif, riskten daha az acil gösteriliyor. Ayrıca sunucu tarafı hiçbir yerde
`expired` üretmiyor (`_milestone` yalnız `good`/`warn`/`risk`/`none` döndürüyor,
`api/tender.py:1518-1543`) — yani bu dal ölü kod, ama `KPI_TESTS.deadline` onu
sayıyor (`TenderCrm.vue:60`).

### Ş-06 · Ham makine anahtarları ekranda (orta)

`OperationsDesk.vue:101` ve `:135` → `{{ item.kind }}`. Kullanıcı `ds-row-ev`
satırında `bid_due`, `policy_gap`, `po_late`, `won_no_po`, `no_parent`,
`invoice_due`, `approval_pending` görür. `_desk_rules.py` bu alanları makine
anahtarı olarak üretiyor (`:66, 109, 122, 145, 174, 199, 234`); insan okunur
karşılığı hiçbir yerde tanımlı değil.

### Ş-07 · `/tender/director` hâlâ dashboard'a yönlendiriyor (orta)

`router.js:272` → `{ path: "/tender/director", redirect: "/dashboard" }`.
`Sidebar.vue:50-53` bu davranışı eski mimarinin kusuru olarak anlatıyor
("menüden tıklayan kullanıcı sessizce panoya düşüyordu") ama redirect kaldırılmamış.
Direktör panosunun gerçek adresi `/tender/portfolio` (`router.js:273`) — eski
yer imi/paylaşılan bağlantı kullanıcıyı modülün dışına atar.

### Ş-08 · `#/tender` kökü NotFound, ama kenar çubuğu "Tender" aktif (orta)

`Sidebar.vue:61` → `route.path === "/tender" || route.path.startsWith("/tender/")`.
İlk dal için router'da rota yok (`router.js:265-276`), catch-all'a düşer
(`router.js:510`). Kullanıcı "Bulunamadı" sayfasında, kenar çubuğunda Tender aktif
vurgulu durur. Ek olarak kenar çubuğu tender'a `/tender/board` ile giriyor
(`Sidebar.vue:79`) — modülün ana ekranı olarak "Sözleşme panosu" seçilmiş, oysa
mimarinin ana ekranı Operasyon Masası (TenderNav.vue:37-39 ve
`seed_tender_demo.py:208`'in listelediği ilk ekran).

### Ş-09 · Tıklanamayan KPI kartlarında `cursor: pointer` (orta-düşük)

`.stbl-ds .ds-kpi { cursor: pointer }` koşulsuz (`css:229-232`). Direktör
panosunda (`DirectorBoard.vue:151`) ve Süreç Akışı'nda (`TenderFlow.vue:137`)
kartlar `<div>`; tıklama işlevi yok, `tabindex` yok. İmleç ve hover arka planı
tıklanabilirlik vaat ediyor, kart cevap vermiyor. Karşı örnek: OperationsDesk ve
TenderCrm'de kartlar `<button aria-pressed>`.

### Ş-10 · Modül navı üç ekranda sayfa başlığının altında (orta-düşük)

`MyTenders.vue:98-99`, `DeclarantQueue.vue:64-65`, `LogistBoard.vue:58-59` —
`<h2>` önce, `<TenderNav />` sonra. Diğer üç ekranda nav kökün ilk çocuğu
(`TenderCrm.vue:248-249`, `TenderFlow.vue:119-120`, `DirectorBoard.vue:132-133`).
`TenderNav.vue:66-77`'deki negatif marj ("çubuk EKRANIN üstünde durur") bu üç
ekranda başlığın üstüne binmeye çalışır.

### Ş-11 · Seed teklif verisi üretmiyor (orta-düşük)

`DEMO_LOTS` her satırda `sq_sayısı` ve `ülke_sayısı` taşıyor
(`seed_tender_demo.py:45, 51-71`) ama `_intake()` `sq_count` parametresini
**kullanmıyor** (`:122-151`) ve `seed()` döngüsü `countries` değişkenini hiç
okumuyor (`:178`). Hiçbir Supplier Quotation kaydı oluşturulmuyor. Oysa
`crm_board` teklif sayısını gerçek Supplier Quotation tablosundan sayıyor
(`api/tender.py:2328-2352`). Sonuç: demo veride
- CRM kartlarının hepsi `0/5 teklif` gösterir,
- "Tedarik politikası" KPI'sı `0/13` çıkar,
- `_funnel.classify` `sq_count`'a bakan `sourcing` dalını hiç kullanamaz
  (`api/_funnel.py:48`) — kurtaran şey `custom_tender_stage` kolonunun
  doğrudan yazılması (`seed_tender_demo.py:191`),
- Operasyon Masası'nda `policy_gap` kalemleri "0/5 teklif toplandı" der ki teknik
  olarak doğru ama seed'in iddia ettiği senaryo değil.

### Ş-12 · Seed `custom_lot_no` yazmıyor → "sahipsiz lot" kuralı hiç tetiklenmiyor (düşük)

`tender_desk.py:117` → `if d.get("custom_lot_no") and not d.get("custom_tender_master")`.
Seed `custom_lot_no` kolonuna hiçbir şey yazmıyor (yalnız intake JSON'una
`lot_no`, `seed_tender_demo.py:129`). Dolayısıyla `orphan_lots` daima boş; masanın
"Sahipsiz lot" (`no_parent`, severity `info`) satırı demo veride hiç görünmez.
Modülün docstring'i (`seed_tender_demo.py:15`) "sahipsiz kalmış lotlar" ürettiğini
iddia ediyor.

### Ş-13 · Modül navının ilk maddesi modülden çıkarıyor (düşük)

`TenderNav.vue:35` → `<router-link to="/dashboard">Overview</router-link>`.
Sekme metaforu içinde, tıklandığında sekme şeridinin tamamen kaybolduğu tek
madde. `TenderNav.vue:33-34` yorumu bunun bilinçli olduğunu yazıyor; yine de
kullanıcı testinde doğrulanması gereken bir karar.

### Ş-14 · Router'da kullanılmayan import (kozmetik)

`router.js:5` → `import Module from "./pages/Module.vue";` — `routes` dizisinde
`Module` hiç kullanılmıyor. Muhtemelen modül hub'ı mimarisinden kalan bir artık;
Ş-08'deki eksik `/tender` hub'ıyla birlikte değerlendirilmeli.

### Ş-15 · `filter` sorgu parametresi geri tuşuyla sıfırlanmıyor (kozmetik)

`OperationsDesk.vue:517-524` → `watch(() => route.query.filter, (newFilter) => {
if (newFilter && ...) })`. Koşul `newFilter` **truthy** olduğunda çalışıyor;
kullanıcı filtreli bir URL'den filtresiz bir URL'e geri döndüğünde
(`?filter=overdue` → `?`) `activeFilter` `overdue` olarak kalır. Ekran URL ile
çelişir.
