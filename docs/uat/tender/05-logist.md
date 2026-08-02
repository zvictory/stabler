# UAT · 05 — LOJİSTİK (Logist) rolü

**Kapsam:** Stabler ERP tender modülünde `logist` rol penceresi. Kazanılan ihalenin malını
yurt dışından getirip müşteriye teslim eden kişinin bir günü: sabah masası → sevkiyat
panosu → gecikme kovalama → belge zinciri → teslim.

**Test edilen sürüm:** `/mnt/user-data/uploads/stabler/` altındaki kaynak.
**Şirket:** Mikas · **Site:** `https://mikas.erpstable.com/stabler`
**Demo veri:** `seed_tender_demo.seed(company="Mikas")` — **UYARI:** bu seed lojistik tarafına
TEK BİR kayıt üretmiyor. Ayrıntı ve elle kurulum listesi: [§9 Demo'nun üretmediği kayıtlar](#9-demonun-üretmediği-kayıtlar).

> **Bu dokümanın ana bulgusu:** Lojistikçinin ekranı VAR ve çalışıyor, ama beslendiği veri
> yolu (tender'a etiketli Purchase Order + planlı landed transport gideri + intake teslim
> tarihi) demo'da hiç kurulmuyor. Ayrıca ekranın gösterdiği şey "sevkiyat" değil, **satın alma
> siparişi**: konteyner, taşıyıcı, konşimento, CMR gibi hiçbir lojistik nesnesi bu ekranda yok.

---

## 0. Test kullanıcısı ve rol haritası

Logist penceresi tek bir sözlük satırından geliyor:

```python
_TENDER_VIEW_ROLES = {
    "director":  ("System Manager", "Stabler Admin", "Sales Manager", "Stabler Tender Director"),
    "sourcing":  ("System Manager", "Stabler Admin", "Sales Manager", "Sales User"),
    "declarant": ("System Manager", "Stabler Admin", "Sales Manager", "Stabler Declarant"),
    "logist":    ("System Manager", "Stabler Admin", "Sales Manager", "Stabler Logist"),
}
```
— `stabler/api/tender.py:1725-1731`

**Kritik ayrım:** `System Manager` / `Stabler Admin` / `Sales Manager` DÖRT pencerenin de
anahtarını taşıyor. Bu dokümandaki "saf lojistikçi" = **yalnız `Stabler Logist` rolü olan**
kullanıcı. Bu üç rolden herhangi biri test hesabında varsa aşağıdaki YETKİ testlerinin
(§7) hiçbiri geçerli değildir.

`Stabler Logist` rolü yüklenen kaynak ağacında **yalnız `tender.py:1729`'da** geçiyor —
bu alt ağaçta rolü oluşturan bir fixture / doctype JSON yok. Rolün sitede elle var edilmiş
olması gerekiyor.

### UAT-000 · Test hesabı kurulumu (ön koşul, tüm senaryolar için)

**Ön koşul:** Administrator olarak giriş.

**Adımlar:**
1. `/app/role/new` → `Stabler Logist` rolünün var olduğunu doğrula; yoksa oluştur.
2. `/app/user/new` → `logist@mikas.uz`. Roller: **YALNIZ `Stabler Logist`**.
   `Sales Manager`, `Sales User`, `System Manager`, `Stabler Admin`,
   `Stabler Tender Director`, `Stabler Declarant` işaretli OLMAMALI.
3. Kullanıcıya `tender` modül erişimi ver (Stabler Settings → module map / allowed modules).
   `purchasing` modülünü **bilerek verme** — UAT-105 tam olarak bunu ölçüyor.
4. `User Permission` ile şirketi Mikas'a bağla.
5. `Purchase Order` ve `CRM Deal` doctype'larında `read` izni olduğunu doğrula
   (`logist_board` her satırda `frappe.has_permission("Purchase Order", "read", ...)`
   çalıştırıyor — izin yoksa liste sessizce boş kalır).
6. `bench --site mikas.erpstable.com execute stabler.maintenance.seed_tender_demo.seed`
7. **§9'daki elle kurulum listesini uygula** — aksi halde §1–§6'nın tamamı boş ekranda test edilir.

**Beklenen:** `stabler.api.tender.tender_views` çağrısı **`{"views": ["logist"]}`** döner —
tek elemanlı liste.
**Kırık belirtisi:** Listede `director` / `sourcing` / `declarant` da varsa hesap fazladan rol
taşıyor. §7'nin tamamı anlamsızlaşır — hesabı baştan kur.
**Kanıt:** `stabler/api/tender.py:1733-1735` (`_tender_views`), `1746-1749` (`tender_views`),
`1993-2018` (`_po_rows_for_views` içindeki satır bazlı `has_permission` süzgeci).

---

## 1. `/tender/logistics` — LogistBoard (asıl ekran)

**Ne gösteriyor:** Tek bir tablo. Satır = tender'a etiketli bir **Purchase Order**.
Sütunlar: PO · Tedarikçi · Tender · Nakliye · PO ETA · Teslim son tarihi · Durum
(`LogistBoard.vue:62-66`).

**Veriyi nereden alıyor:** tek uç nokta —
`stabler.api.tender.logist_board(company)` (`LogistBoard.vue:34` → `tender.py:2063-2121`).

Verinin zinciri:
```
Purchase Order (company=X, custom_crm_deal IS SET, docstatus<2)      tender.py:2005-2016
  → transport = custom_landed_charges içindeki type in ("transport","loading")  2073
  → eta       = PO.schedule_date                                                2075
  → delivery  = CRM Deal intake.delivery_deadline, yoksa Sales Order.delivery_date min  2082-2096
  → received  = PO.per_received >= 100                                          2074
  → late      = (not received) and eta and delivery and eta > delivery          2099
  → status    = delivered | late | in_transit                                   2100
```

### UAT-101 · Ekran açılıyor ve rol kapısını geçiyor

**Ön koşul:** rol = `Stabler Logist`, şirket = Mikas.
**URL:** `https://mikas.erpstable.com/stabler#/tender/logistics`

**Adımlar:**
1. Adres çubuğuna tam URL'i yaz, Enter.
2. Ağ sekmesinde `stabler.api.tender.logist_board` çağrısını izle.

**Beklenen:**
- HTTP 200; `{"currency": "UZS", "rows": [...]}` biçimi.
- Sayfa başlığı "Lojistika / Logistics" (`LogistBoard.vue:58`).
- Sekme başlığı `Logistics · Stabler` (`router.js:276` + `router.js:637-639`).
- Üstte TenderNav çubuğu görünür ve içinde **"Logistics" bağlantısı aktif** durumda
  (`TenderNav.vue:59-61`).

**Kırık belirtisi:**
- `PermissionError: Not permitted` → `_require_tender_view("logist", ...)` reddetti; ya rol
  yok, ya şirkette `enable_tender = 0`, ya da kullanıcı Mikas kapsamında değil
  (`tender.py:1738-1743` üç kapıyı da sırayla çalıştırıyor).
- `Tender module is not enabled for Mikas.` → şirket modül haritası kapalı (`tender.py:48-54`).
- Ekran açılıyor ama TenderNav'da "Logistics" YOK → `session.tenderViews` boş gelmiş;
  `ensureTenderViews()` şirketten önce koştu demektir (`TenderNav.vue:24-25`,
  `session.js:103-127`).

**Kanıt:** `tender.py:2063-2066`, `tender.py:1738-1743`, `LogistBoard.vue:30-42`,
`TenderNav.vue:59-61`, `router.js:276`.

---

### UAT-102 · Boş ekran ile "veri yok" ayrımı

Bu, demo veriyle çalışırken görülecek **varsayılan** durum.

**Ön koşul:** UAT-000 yapıldı, §9 elle kurulumu **yapılmadı**.

**Adımlar:**
1. `#/tender/logistics` aç.
2. Tabloyu ve altındaki boş durum kutusunu incele.

**Beklenen:**
- Tablo gövdesi boş, altında `EmptyState` ikon `ti-truck-delivery`, metin
  **"No shipments match these filters."** (`LogistBoard.vue:80`).
- Sağ üstte filtre özeti **görünmez** (query boş, `activeTenderFilters` boş dizi döner —
  `tenderBoardFilters.js:9-13`).

**Kırık belirtisi:** Boş durumda "filtrelerle eşleşmiyor" yazması **yanıltıcıdır**: gerçek
sebep hiç PO olmamasıdır, filtre değil. Metin ayrımı yapmıyor — bu ekranın bilinen zayıf
noktası ve UAT'ta not düşülmeli.

**Kanıt:** `LogistBoard.vue:46-48, 80`, `composables/tenderBoardFilters.js:9-13, 36-47`.

---

### UAT-103 · Dolu tablo — sütun sütun doğrulama

**Ön koşul:** §9 elle kurulumu yapıldı (en az 4 tender PO'su var).

**Adımlar:**
1. `#/tender/logistics` aç.
2. Her satır için ERPNext'teki PO ile karşılaştır (`/app/purchase-order/<PO>`).

**Beklenen (somut):**

| Sütun | Kaynak | Doğrulama |
|---|---|---|
| PO | `PO.name` | Birebir aynı |
| Vendor | `PO.supplier_name` | Birebir aynı |
| Tender | `_deal_label(deal)` = CRM Deal `organization` | `[DEMO]` ekli kurum adı; okuma izni yoksa boş → tabloda `—` |
| Transport | `custom_landed_charges` içinde `type ∈ {transport, loading}` toplamı | Şirket para birimiyle (`UZS`); hiç yoksa `—` |
| PO ETA | `PO.schedule_date` | `dd.mm.yyyy` (DateInput standardı) |
| Delivery deadline | intake `delivery_deadline`, yoksa min(SO.delivery_date) | seed'de `bugün+90` |
| Status | türetilmiş | `delivered` yeşil / `in_transit` mavi / `late` kırmızı |

- Satırlar **ETA'ya göre artan** sıralı gelir (`tender.py:2014` `order_by="schedule_date asc"`).
- Tutar `formatMoney(v, currency, user.language)` ile, `font-monospace` (`LogistBoard.vue:73`).

**Kırık belirtisi:**
- Transport sütunu her satırda `—` → ya `custom_landed_charges` kolonu yok (`has_landed = False`,
  `tender.py:1995`, patch v34 koşmamış), ya da giderler `customs` tipiyle girilmiş
  (o zaman deklarant ekranına düşer, lojistiğe değil).
- Teslim son tarihi her satırda `—` → CRM Deal'de intake `delivery_deadline` yok VE tender'a
  etiketli Sales Order yok. Bu durumda **`late` hesabı hiç çalışamaz** (2099 satırındaki
  `and delivery` koşulu düşer) → her açık PO sonsuza kadar `in_transit` görünür.
- Satır sayısı 2000'i geçiyorsa liste sessizce kesilir (`tender.py:2015` `limit_page_length=2000`).

**Kanıt:** `tender.py:1993-2018` (PO çekimi), `2072-2100` (satır türetimi),
`LogistBoard.vue:62-77`.

---

### UAT-104 · Durum rozetlerinin anlamı — "Delivered" YANLIŞ etiket

**Ön koşul:** Bir tender PO'sunda `per_received = 100` (mal depoya girdi), ama müşteriye
teslim (Delivery Note) HENÜZ YOK.

**Adımlar:**
1. `#/tender/logistics` aç, o PO satırının Durum rozetine bak.

**Beklenen:** Rozet **"Delivered / Teslim edildi"** (yeşil) gösterir.

**Bu bir hata belirtisidir.** `received = flt(p.per_received) >= 100` (`tender.py:2074`)
**tedarikçiden mal alındı** demektir — müşteriye teslim edildi demek DEĞİL. Müşteriye teslim
`Delivery Note` / `Sales Order.per_delivered` ile ölçülür ve bu ekranda hiç okunmuyor.
Lojistikçi tam da bu ikisini ayırt etmek zorunda; ekran ikisini tek rozette birleştiriyor.

**Kırık belirtisi:** Sahada "teslim ettim mi?" sorusuna bu ekrandan bakan lojistikçi, gümrükten
yeni çıkmış malı "teslim edilmiş" sayar. Rozet metni `stLabel("delivered") = t("Delivered")`
(`LogistBoard.vue:51`).

**Kanıt:** `tender.py:2074, 2100`, `LogistBoard.vue:50-51`.
Karşılaştırma: müşteri tarafı teslim sayacı gerçekte `tender_dashboard`'da var —
`execution["delivered"] / ["delivery_pending"]`, `SO.per_delivered >= 100` üzerinden
(`tender.py:2865-2868`) — ama LogistBoard'a bağlanmamış.

---

### UAT-105 · Satıra tıklama — tender-only lojistikçide KIRIK

Bu ekranın **tek eylemi** satıra tıklamak.

**Ön koşul:** `logist@mikas.uz` kullanıcısında `purchasing` modülü **KAPALI**
(UAT-000 adım 3), `tender` açık.

**Adımlar:**
1. `#/tender/logistics` aç.
2. Herhangi bir satıra tıkla.

**Beklenen (tasarım niyeti):** `/purchasing/orders/<PO>` açılır.

**Gerçekte olan:** Router muhafızı `to.matched` içinde `meta.module = "purchasing"` bulur
(`router.js:326-329`), kullanıcı bu modüle erişemez, ve tender drill-down istisnası da
çalışmaz — çünkü istisna hem `to.query.tender_only === "1"` hem de rota adının
`tenderDrilldownRoutes` kümesinde olmasını istiyor. Küme **çoğul** `"purchasing-orders"`
içeriyor; açılan rotanın adı **tekil** `"purchasing-order"` (`router.js:335`).
`openPo` da `tender_only` eklemiyor, yalnız mevcut query'i taşıyor (`LogistBoard.vue:52`).

Sonuç: kullanıcı `landingPath(session)` ile **tender listesinde olmayan bir sayfaya**
fırlatılır. `LANDING_ORDER` içinde `tender` anahtarı **hiç yok** (`router.js:518-537`) —
saf lojistikçide hiçbir anahtar eşleşmezse `"/error"` döner (`router.js:539-544`).

**Beklenen (kabul kriteri):** Ya PO formu açılır, ya da kullanıcıya anlaşılır bir "bu belgeye
erişiminiz yok" mesajı verilir. Sessiz `/error` yönlendirmesi KABUL EDİLMEZ.

**Kırık belirtisi:** Tıklamada sayfa `#/error`'a ya da alakasız bir modüle atlıyor; konsolda
hata yok (muhafız sessiz).

**Kanıt:** `LogistBoard.vue:52` (`openPo`), `router.js:335` (rota adı `purchasing-order`),
`router.js:613-635` (muhafız + drill-down istisnası), `router.js:518-544` (`LANDING_ORDER`,
`landingPath`).

---

### UAT-106 · URL filtreleri (`risk`, `due`, `status`) çalışıyor mu

`logist_board` her satıra üç filtre kancası koyuyor: `stage`, `status`, `risk`, `due`
(`tender.py:2117-2120`).

**Ön koşul:** Tabloda en az bir `late` satır var.

**Adımlar:**
1. `#/tender/logistics?due=late` aç.
2. Sağ üstteki filtre özetini ve "Clear filters" düğmesini kontrol et.
3. `#/tender/logistics?risk=risk` ile tekrarla.
4. `#/tender/logistics?status=in_transit` ile tekrarla.

**Beklenen:**
- Yalnız eşleşen satırlar kalır (`filterTenderRows`, `tenderBoardFilters.js:36-47`).
- Sağ üstte `due: late` yazan gri özet + "Clear filters" düğmesi (`LogistBoard.vue:58`).
- "Clear filters" query'yi tamamen temizler (`router.replace({query:{}})`, `LogistBoard.vue:53`).
- `?period=2026-08` filtresi `event_date` = `PO.transaction_date` üzerinden çalışır
  (`tender.py:2114`, `tenderBoardFilters.js:15-28`).

**Kırık belirtisi:** `?due=late` hiçbir şeyi süzmüyorsa satırlarda `due` alanı boş dönüyordur —
`late` hesabının (UAT-103 kırık belirtisi) hiç tetiklenmediğinin ikinci kanıtıdır.

**Kanıt:** `tender.py:2117-2120`, `LogistBoard.vue:46-48, 53, 58`,
`composables/tenderBoardFilters.js:1-47`.

---

### UAT-107 · Otomatik yenileme ve ESC davranışı

**Ön koşul:** Ekran açık.

**Adımlar:**
1. Ekranı açık bırak, sekmeyi arka plana al, 2 dakika bekle, geri dön.
2. Ekranda ESC tuşuna bas.

**Beklenen:**
- `useAutoRefresh(load)` 60 saniyede bir yeniler; `document.hidden` iken **durur**, sekmeye
  dönünce **bir kez** yeniler (STATE.md:61, WP-305).
- ESC → `/tender/board` (Sözleşme panosu) (`LogistBoard.vue:25`).

**Kırık belirtisi:** Arka planda da ağ istekleri akıyorsa overlap-guard kırılmış demektir;
ESC bir yere gitmiyorsa `useEscapeBack` bağlanmamıştır.

**Kanıt:** `LogistBoard.vue:12, 25, 42`, `STATE.md:61`.

---

## 2. `/tender/desk?view=logist` — Operasyon Masası

### Masa lojistikçiye ne gösteriyor: **herkese çıkan aynı liste**

`_desk_rules.build_plan(facts, today)` fonksiyonunun imzasında **rol/view parametresi yok**
(`_desk_rules.py:22`). Gövdesinde `view`, `role`, `logist` kelimesi **hiç geçmiyor** — altı
kural bloğu sabittir:

| # | kind | Kaynak | Lojistikçinin işi mi? |
|---|---|---|---|
| 1 | `bid_due` / `bid_soon` | CRM Deal `bid_deadline` | **Hayır** — teklif son tarihi, sourcing işi |
| 2 | `policy_gap` | `sq_count < 5` | **Hayır** — 5 teklif kuralı, sourcing işi |
| 3 | `no_parent` | ana tender'ı olmayan lot | **Hayır** — veri hijyeni |
| 4 | `won_no_po` | kazanılmış ama PO'suz lot | Kısmen — ama eylem sourcing'de |
| 5 | **`po_late`** | `PO.schedule_date < bugün` ve `per_received < 100` | **EVET** — tek gerçek lojistik kalemi |
| 6 | `invoice_due` | vadesi gelmiş Purchase/Sales Invoice | Hayır — muhasebe |
| 7 | `approval_pending` | bekleyen onaylar | Duruma göre |

`tender_desk.py`'de rol bazlı **tek** süzgeç var ve o da sourcing'e ait:

```python
if not oversight and view == "sourcing":
    deals = [d for d in deals if (d.get("assigned_to") == user or d.get("owner") == user)]
```
— `tender_desk.py:89-91`

`logist` için karşılığı **yok**. Yani lojistikçi masayı açtığında şirketteki **tüm** CRM
Deal'lerin teklif son tarihlerini, eksik tedarikçi tekliflerini ve öksüz lotlarını görür.

### UAT-201 · Masa açılıyor, rol seçici görünmüyor

**Ön koşul:** rol = `Stabler Logist`, şirket = Mikas.
**URL:** `https://mikas.erpstable.com/stabler#/tender/desk?view=logist`

**Adımlar:**
1. URL'i aç.
2. Sağ üstte rol seçici açılır kutuyu ara.
3. Başlık altındaki meta satırında görünüm adını oku.

**Beklenen:**
- Sayfa açılır (`_tender_views(user)` = `["logist"]`, boş değil → `tender_desk.py:35-37` geçer).
- **Rol seçici GÖRÜNMEZ** — şablon `v-if="deskData?.views && deskData.views.length > 1"`
  diyor (`OperationsDesk.vue:22`), liste tek elemanlı.
- Meta satırında ham `logist` yazar — `available_views = [{"id": v, "label": v}]`
  (`tender_desk.py:39`), çeviri anahtarı olmayan ham view id'si `t("logist")`'e girer
  (`OperationsDesk.vue:17`). Türkçe arayüzde bile İngilizce/ham `logist` görünür.

**Kırık belirtisi:** Açılır kutu görünüyorsa hesap fazladan rol taşıyor (UAT-000'e dön).
`Access denied to Operations Desk.` görüyorsan `_tender_views` boş dönmüş.

**Kanıt:** `tender_desk.py:27-44`, `OperationsDesk.vue:17, 21-32`.

---

### UAT-202 · Masada lojistik DIŞI kalemler çıkıyor (bilinçli olarak doğrulanmalı)

**Ön koşul:** `seed_tender_demo.seed("Mikas")` koşmuş (13 demo lot).

**Adımlar:**
1. `#/tender/desk?view=logist` aç.
2. "Günlük iş planı" listesindeki kalemlerin `kind` etiketlerini (satır altındaki küçük gri
   metin, `OperationsDesk.vue:135`) not al.

**Beklenen (mevcut davranış):**
- Listede `bid_due` (UTY-2026-4305, son tarih dün → `overdue`), `bid_due` bugün
  (UTY-2026-4308), `bid_soon` (UTY-2026-4310, 2 gün), ve `policy_gap` kalemleri **çıkar**.
- `policy_gap` demo'da **sourcing aşamasındaki iki lot için** çıkar (4308, 4309) çünkü
  seed hiç `Supplier Quotation` yaratmıyor → `sq_count = 0 < 5` (`_desk_rules.py:103-114`).
- Her kalemin rotası `/tender/crm?deal=...` (`_desk_rules.py:73, 85, 97, 111`) — yani
  lojistikçi kaleme tıkladığında **CRM kanban'ına** gider.
- `po_late` kalemi **çıkmaz** (demo'da PO yok).

**Kabul kriteri (ürün kararı gerektirir):** Lojistikçinin masası ya `po_late` ve
`approval_pending` ile sınırlanmalı, ya da kalemler "senin işin değil" diye işaretlenmeli.
Mevcut hâl, lojistikçiye teklif son tarihi kovalatıyor.

**Kırık belirtisi:** `bid_due` kalemine tıklayınca `/tender/crm` açılıyor ve orada
lojistikçi hiçbir şey yapamıyor (yalnız okur, kart sürükleyemez — bkz. UAT-703).

**Kanıt:** `_desk_rules.py:22` (imza — rol parametresi yok), `_desk_rules.py:42-114`,
`tender_desk.py:89-91` (yalnız sourcing süzgeci), `seed_tender_demo.py:51-71`.

---

### UAT-203 · `po_late` — masadaki tek gerçek lojistik kalemi

**Ön koşul:** §9 kurulumu yapıldı; en az bir PO `docstatus=1`, `schedule_date < bugün`,
`per_received < 100`.

**Adımlar:**
1. `#/tender/desk?view=logist` aç.
2. "Geciken" (overdue) bandında `po_late` kalemini bul.

**Beklenen (somut):**
- Başlık: `Late delivery: <PO adı>` (`_desk_rules.py:169`).
- Gerekçe: `Supplier <tedarikçi> delivery past by N day(s) (X% received)` (`_desk_rules.py:171`).
- Severity `overdue` → kırmızı bant, KPI şeridinde "Overdue" sayacına dahil.
- Rota: `/purchasing/orders/<PO>` (`_desk_rules.py:175`).

**Kırık belirtisi:**
- Kalem çıkmıyor ama PO gerçekten gecikmiş → `tender_desk.py:146-148` filtresi
  `docstatus: 1` ve `per_received < 100` istiyor; PO taslak (`docstatus=0`) ise **hiç
  görünmez**. LogistBoard ise taslakları gösterir (`docstatus < 2`, `tender.py:2012`).
  **İki ekran farklı PO kümesi üzerinde konuşuyor.**
- Kaleme tıklayınca `/error`'a düşüyor → UAT-105 ile aynı router muhafızı sorunu
  (rota adı `purchasing-order`, modül `purchasing`).

**Kanıt:** `_desk_rules.py:155-178`, `tender_desk.py:145-162`, `tender.py:2005-2016`,
`router.js:613-635`.

---

### UAT-204 · Masada TenderNav yok — geri dönüş yolu kayboluyor

**Adımlar:**
1. `#/tender/logistics` → TenderNav'dan "Operations desk"e tıkla.
2. Açılan sayfanın üstünde tender modül çubuğunu ara.

**Beklenen (kabul kriteri):** Modül çubuğu her tender ekranında olmalı.

**Gerçekte:** `OperationsDesk.vue` `TenderNav` **import etmiyor ve render etmiyor**. Aynı
şey `PoControlBoard.vue` için de geçerli. Çubuğu render edenler: LogistBoard, DeclarantQueue,
DirectorBoard, TenderFlow, MyTenders, TenderCrm.

Saf lojistikçi masaya girdikten sonra `/tender/logistics`'e dönmek için ya tarayıcı geri
tuşunu ya da elle URL yazmayı kullanmak zorunda. Kenar çubuğundaki tek tender maddesi
`/tender/board`'a gider (`Sidebar.vue:79`) — lojistikçinin ekranına değil.

**Kırık belirtisi:** Masadan lojistik panosuna tek tıkla dönüş yolu yok.

**Kanıt:** `grep -rn "TenderNav" stabler/public/js/` → OperationsDesk.vue ve
PoControlBoard.vue listede yok; `Sidebar.vue:79`; `TenderNav.vue:59-61`.

---

### UAT-205 · Takım yükü ve karar kutusu

**Adımlar:**
1. `#/tender/desk?view=logist` aç.
2. Sağ sütunda "Team load" panelini ara.

**Beklenen:**
- **"Team load" paneli GÖRÜNMEZ.** `team_load` yalnız `oversight` için doldurulur
  (`tender_desk.py:257-277`); saf lojistikçi oversight değil (`_OVERSIGHT_ROLES`,
  `tender.py:1752`) → boş dizi → `v-if="teamLoad.length"` düşer (`OperationsDesk.vue:197`).
- "Decision box" paneli görünür ama demo'da onay kaydı olmadığı için "No pending decisions".

**Kırık belirtisi:** Takım yükü görünüyorsa hesap oversight rolü taşıyor.

**Kanıt:** `tender_desk.py:257-277`, `tender.py:1752-1758`, `OperationsDesk.vue:197-218`.

---

## 3. Sevkiyat takibi: konteyner, taşıyıcı, ETA, teslim tarihi

### Bulgu: bu dört alandan yalnız İKİSİ var, ikisi HİÇ YOK

| Alan | Doctype / alan | LogistBoard'da var mı |
|---|---|---|
| **Konteyner no** | — (tender hattında YOK) | **YOK** |
| **Taşıyıcı / nakliyeci** | — (tender hattında YOK) | **YOK** |
| **ETA** | `Purchase Order.schedule_date` | VAR (`tender.py:2075`, `LogistBoard.vue:74`) |
| **Teslim tarihi (müşteriye)** | CRM Deal intake `delivery_deadline`, yoksa `Sales Order.delivery_date` | VAR ama **hedef tarih**, gerçekleşen değil (`tender.py:2082-2096`) |
| Nakliye tutarı | `PO.custom_landed_charges` içinde `type ∈ {transport, loading}` | VAR (planlanan tutar; `tender.py:2073`) |

**Sistemde bir konteyner altyapısı VAR — ama tender hattına bağlı DEĞİL.** Ayrı bir
`imports` modülü, `Import Container` / `Commercial Invoice` / `Import Truck` doctype'ları ve
9 durumlu bir lojistik hattı mevcut:

```
BOOKED → STUFFED → GATE_IN → ON_BOARD → IN_TRANSIT → DISCHARGED
→ AVAILABLE → ARRIVED_AT_IRAN → DELIVERED_TO_UZBEKISTAN
```
— `composables/status.js:128-152`; rotalar `router.js:218-221`
(`/imports/containers`, `.../ledger`).

`logist_board` bu doctype'ların **hiçbirine dokunmuyor** — yalnız `Purchase Order` okuyor
(`tender.py:1993-2018`). Tender lojistikçisi ile ithalat lojistiği iki ayrı dünya.

### UAT-301 · Konteyner / taşıyıcı alanı aranıyor

**Ön koşul:** §9 kurulumu yapıldı, tabloda satır var.

**Adımlar:**
1. `#/tender/logistics` aç.
2. Tablo başlıklarını say ve içeriklerini oku.

**Beklenen:** Tam **7 sütun**: PO · Vendor · Tender · Transport · PO ETA · Delivery deadline ·
Status (`LogistBoard.vue:62-66`, `SkeletonRows :cols="7"` satır 68).
Konteyner numarası, taşıyıcı adı, sefer/vagon numarası, Incoterm, konşimento no **YOK**.

**Kırık belirtisi (ürün eksiği):** Lojistikçi "hangi konteynerde, kim taşıyor?" sorusunu bu
ekrandan cevaplayamaz. Cevap yalnız `/imports/containers`'ta olabilir ve o modül `imports`
modül erişimi ister (`router.js:218`) — saf lojistikçide kapalı.

**Kanıt:** `LogistBoard.vue:62-66`, `tender.py:2101-2121` (dönen satırın TÜM alanları),
`composables/status.js:141-152`, `router.js:218-221`.

---

### UAT-302 · ETA'nın kaynağı doğru mu

**Adımlar:**
1. ERPNext'te bir tender PO'sunda `schedule_date`'i değiştir (`/app/purchase-order/<PO>`).
2. `#/tender/logistics`'i yenile (veya 60 sn otomatik yenilemeyi bekle).

**Beklenen:** "PO ETA" sütunu yeni tarihi gösterir.

**Kırık belirtisi:** PO çok satırlıysa ve satırlarda farklı `schedule_date` varsa, ekran
**yalnız başlıktaki** `schedule_date`'i gösterir (`tender.py:1998-2010` alan listesi). Kalem bazlı
farklı varış tarihleri kaybolur — kısmi sevkiyatta yanlış ETA.

**Kanıt:** `tender.py:1998-2010` (yalnız başlık alanları çekiliyor), `tender.py:2075`.

---

### UAT-303 · Teslim son tarihinin iki kaynağı çakışırsa

**Adımlar:**
1. Bir CRM Deal'de intake `delivery_deadline = bugün+60` yaz.
2. Aynı deal'e bağlı bir Sales Order'da `delivery_date = bugün+30` yaz.
3. `#/tender/logistics` aç.

**Beklenen:** Ekran **bugün+60** (intake) gösterir — intake her zaman önceliklidir, SO
yalnız intake boşken devreye girer (`tender.py:2082-2096`).

**Kırık belirtisi:** Müşteriyle imzalanan gerçek sözleşme SO'da (bugün+30) iken ekran daha
gevşek olan intake tarihini gösterir; lojistikçi 30 günlük gecikmeyi göremez. `late` hesabı
da bu gevşek tarihe göre yapılır (`tender.py:2099`).

**Kanıt:** `tender.py:2081-2099`. Karşılaştır: `_deal_deadlines` aynı seçimi yapıyor
(`tender.py:1581`) ama `_portfolio_deadlines` de öyle (`tender.py:2652-2657`) — tutarlı ama
tutarlı biçimde gevşek.

---

## 4. Belge zinciri (TenderDocumentChain)

### Bulgu: zincir VAR, ama lojistik evrakları zincirde YOK ve zincir lojistikçinin menüsünde YOK

`TenderDocumentChain.vue` altı kutu çiziyor:

```
Purchase execution : PO      → Receipt   → Invoice     (TenderDocumentChain.vue:19)
Sales execution    : Sales order → Delivery → Invoice  (TenderDocumentChain.vue:20)
```

Arkasındaki veri `tender_workspace(deal)` → `_purchase_document_chain` (`tender.py:755-790`)
+ `_sales_document_chain` (`tender.py:792-829`). Okunan doctype'lar tam olarak altı tane:
`Purchase Order`, `Purchase Receipt`, `Purchase Invoice`, `Sales Order`, `Delivery Note`,
`Sales Invoice`.

**Lojistikçinin evrakları:**

| Evrak | Zincirde var mı | Nerede |
|---|---|---|
| Konşimento (Bill of Lading / B/L) | **HAYIR** | Hiçbir yerde — kaynakta `bill_of_lading` geçmiyor |
| CMR | **HAYIR** | Hiçbir yerde |
| Packing list | **HAYIR** | Hiçbir yerde |
| Ticari fatura (tedarikçi) | Evet — `Purchase Invoice` | `tender.py:780-789` |
| Ticari fatura (müşteri) | Evet — `Sales Invoice` | `tender.py:818-827` |
| Mal kabul (GRN) | Evet — `Purchase Receipt` | `tender.py:772-780` |
| Müşteriye irsaliye | Evet — `Delivery Note` | `tender.py:809-818` |

Ayrıca CRM Deal intake içinde bir **belge kontrol listesi** alanı var
(`documents: [{label, required, done, date}]`, `tender.py:1416-1424`) — ihale evrakı için
tasarlanmış (ГТД, sertifika, kabul tutanağı, sözleşme, fatura; `tender.py:1415` yorumu).
Konşimento/CMR elle satır olarak eklenebilir ama bu **serbest metin**tir; hiçbir ekran
lojistik evrakı olarak ayırt etmez ve LogistBoard bu listeyi hiç okumaz.

### UAT-401 · Belge zinciri lojistikçinin menüsünde var mı

**Ön koşul:** rol = `Stabler Logist`.

**Adımlar:**
1. `#/tender/logistics` aç.
2. TenderNav çubuğundaki tüm bağlantıları say.

**Beklenen (somut liste):** Overview · Operations desk · Contract board · Logistics.
**"Tender PO control" GÖRÜNMEZ** — `v-if="can('sourcing')"` (`TenderNav.vue:53-55`).

Belge zinciri **yalnızca** `PoControlBoard.vue` içinde, `activeWorkspaceTab === 'delivery'`
sekmesinde render ediliyor (`PoControlBoard.vue:452-454`). Yani lojistikçi belge zincirine
**menüden ulaşamaz**.

**Kırık belirtisi:** Lojistikçi "bu tender'ın faturası kesildi mi, irsaliye çıktı mı?"
sorusunu kendi ekranından cevaplayamıyor.

**Kanıt:** `TenderNav.vue:37-61`, `PoControlBoard.vue:23, 315, 452-454`,
`TenderWorkspaceTabs.vue:14-19`.

---

### UAT-402 · Belge zincirine URL ile ulaşma (arka kapı)

**Ön koşul:** rol = `Stabler Logist`; `CRM Deal` read izni var.
**URL:** `https://mikas.erpstable.com/stabler#/tender/po-control?deal=<DEAL>&tab=delivery`

**Adımlar:**
1. URL'i elle yaz, Enter.
2. Sayfa açılıyor mu, "Delivery" sekmesi seçili mi kontrol et.

**Beklenen (mevcut davranış):** **Sayfa AÇILIR.**
- Router muhafızı yalnız `meta.module = "tender"` bakar, view kapısı yok (`router.js:271`).
- `po_control_board(deal)` ve `tender_workspace(deal)` **`_require_tender_view` çağırmıyor**;
  kapıları `_require_company` + `_require_tender` + `_assert_company_scope` + CRM Deal read
  izni (`tender.py:471-476`, `tender.py:941` → `_deal_scope` `tender.py:977-988`).
- "Delivery" sekmesinde PO/Receipt/Invoice ve SO/DN/Invoice kutuları dolu gelir.
- "Finance" sekmesi **görünmez**: `_can_view_tender_finance` oversight ya da
  `Accounts User/Manager` istiyor (`tender.py:2574-2577`); saf lojistikçi ikisi de değil →
  `tender_workspace` `finance` anahtarını hiç döndürmez → `hasFinance = false`
  (`TenderWorkspaceTabs.vue:18`).
- "Overview" sekmesindeki `TenderIntake` ve `BidPricing` **düzenlenebilir** görünür
  (`PoControlBoard.vue:318-319`).

**Kabul kriteri:** Bu bir **yetki sızıntısı adayı**dır. Ürün kararı: ya lojistikçiye Delivery
sekmesi menüden açıkça verilmeli, ya da `po_control_board` / `tender_workspace`'e
`_require_tender_view("sourcing", company)` eklenmeli. Mevcut hâl "menüde yok ama URL'le var".

**Kırık belirtisi:** Lojistikçi bu ekrandan `save_po_landed_charges` ile bir PO'nun planlı
landed maliyetini **değiştirebiliyorsa** (PO write izni varsa) sınır tamamen kalkmış demektir
— o uç noktanın kapısı da yalnız `_po_scope(po, write=True)` (`tender.py:442`,
`tender.py:348-360`), view kapısı yok.

**Kanıt:** `router.js:271`, `tender.py:464-476`, `tender.py:936-941`, `tender.py:977-988`,
`tender.py:434-442`, `tender.py:2574-2577`, `PoControlBoard.vue:265, 315-319, 452-454`.

---

### UAT-403 · Belge kontrol listesi demo'da ÇALIŞMIYOR

**Ön koşul:** seed koşmuş; herhangi bir demo deal.

**Adımlar:**
1. `#/tender/po-control?deal=<DEMO_DEAL>&tab=overview` aç (veya API'den
   `stabler.api.tender.deal_intake` çağır).
2. Dönen `docs` bloğuna bak.

**Beklenen (mevcut, HATALI davranış):**
```json
"docs": {"total": 4, "required": 0, "done_required": 0, "missing": []}
```
Yani "4 belge var, hiçbiri zorunlu değil, eksik yok".

**Sebep — şema uyuşmazlığı:** seed belgeleri `{"name": ..., "status": "ready"}` biçiminde
yazıyor (`seed_tender_demo.py:134-139`), oysa `_docs_summary` `label` / `required` / `done`
anahtarlarını okuyor (`tender.py:1478-1486`). seed JSON'u `_clean_intake`'ten geçirmediği
için (doğrudan `json.dumps`, `seed_tender_demo.py:182-184`) normalize de edilmiyor.

**Kırık belirtisi:** Belge kontrol listesi demo'da her zaman "eksiksiz" görünür — eksik evrak
uyarısı hiç test edilemez. Aynı sebeple `_clean_intake`'in `ready_at` türetimi de
(`tender.py:1425-1438`) demo verisiyle hiç tetiklenmez.

**Kanıt:** `seed_tender_demo.py:134-139, 182-184`, `tender.py:1416-1424`, `tender.py:1478-1486`.

---

## 5. Gümrükten çıkan malın teslime geçişi — deklarant → logist devri

### Bulgu: **DEVİR DİYE BİR ŞEY YOK.** İki ekran aynı PO listesini paralel gösteriyor.

Her iki pencere de **aynı yardımcıyı** çağırıyor:

```python
def _po_rows_for_views(company):   # tender.py:1993
    """Shared PO fetch for declarant/logist windows (all tenders)."""
```

Aynı filtre, aynı sıralama, aynı satırlar. Fark yalnız türetimde:

| | DeclarantQueue | LogistBoard |
|---|---|---|
| Uç nokta | `declarant_queue` (`tender.py:2020-2060`) | `logist_board` (`tender.py:2063-2121`) |
| Tutar sütunu | `customs` tipi landed gider | `transport` + `loading` tipi landed gider |
| Ek sütun | ТН ВЭД (HS) kodu | — |
| Zaman sütunu | **Days left** (`etaText`) | — (yalnız ham ETA) |
| Durum | `cleared` / `in_progress` / `pending` | `delivered` / `in_transit` / `late` |
| `cleared` tanımı | `per_received >= 100` (`tender.py:2032`) | aynı alan, `delivered` adıyla (`tender.py:2074`) |

**Sonuç:** "Gümrük tamamlandı, artık lojistiğin" diyen bir durum geçişi, bir buton, bir olay
kaydı, bir sahiplik alanı **yok**. Deklarantın ekranında `cleared` olan PO, lojistikçinin
ekranında **aynı anda** `delivered` olur — çünkü ikisi de `per_received >= 100`'ün adıdır.
Yani mal depoya girdiği anda hem "gümrükten çıktı" hem "teslim edildi" sayılır.

Ayrıca `declarant_queue`'daki `in_progress` durumu **gerçek bir gümrük durumu değil**;
"planlı `customs` tipli landed gider satırı var mı" demektir (`tender.py:2030, 2035`).
Kodun kendisi bunu `tender_dashboard`'da açıkça yazıyor:

```python
"customs_proxy": {"basis": "planned_landed_customs_charge_not_clearance", ...}
```
— `tender.py:2811-2816`

### UAT-501 · Aynı PO iki ekranda da açık

**Ön koşul:** UAT-000'e ek olarak `Stabler Declarant` rolüyle ikinci bir hesap
(`declarant@mikas.uz`). §9 kurulumu yapıldı.

**Adımlar:**
1. Deklarant hesabıyla `#/tender/customs` aç, bir PO'nun satırını not al.
2. Lojist hesabıyla `#/tender/logistics` aç, aynı PO'yu ara.

**Beklenen:** **Aynı PO her iki listede de vardır** — hiçbir devir/filtreleme yok.
İki liste satır kümesi olarak birebir aynıdır (aynı `_po_rows_for_views` sonucu).

**Kırık belirtisi (ürün eksiği):** Lojistikçi "bana devredilenler" diye bir liste göremiyor;
gümrüğü bitmemiş malı da bitmişi de aynı yerde görüyor.

**Kanıt:** `tender.py:1993-2018` (ortak yardımcı ve docstring'i), `tender.py:2024, 2067`
(ikisi de aynı çağrı), `DeclarantQueue.vue:34` vs `LogistBoard.vue:34`.

---

### UAT-502 · `per_received = 100` yapıldığında iki ekranda ne olur

**Adımlar:**
1. Bir tender PO'suna Purchase Receipt kes → `per_received = 100` olsun.
2. Deklarant hesabıyla `#/tender/customs`, lojist hesabıyla `#/tender/logistics` aç.

**Beklenen:**
- Deklarant ekranında rozet **"Cleared"** (yeşil) — `tender.py:2032, 2035`.
- Lojist ekranında rozet **"Delivered"** (yeşil) — `tender.py:2074, 2100`.
- Her iki değişiklik **aynı anda ve aynı tek alandan** olur.

**Kabul kriteri:** Gümrük çıkışı ile müşteriye teslimin ayrı ayrı işaretlenebilmesi
gerekiyor. Mevcut hâlde iki rol arasında hiçbir devir kaydı ve hiçbir ayrı durum yok.

**Kırık belirtisi:** Müşteriye hiç teslimat yapılmadan (Delivery Note yok) lojistik
panosunda "Teslim edildi" yazması.

**Kanıt:** `tender.py:2032-2035` (declarant), `tender.py:2074, 2099-2100` (logist),
`tender.py:2811-2816` (kodun kendi "bu clearance değil" uyarısı).

---

## 6. Gecikme: ETA kaçtığında lojistikçi nereden görür

### Bulgu: LogistBoard'ın `late` tanımı "ETA kaçtı" DEĞİL

```python
late = bool(not received and eta and delivery and eta > delivery)   # tender.py:2099
```

Bu, "**planlanan varış tarihi, müşteriye teslim son tarihinden SONRA**" demektir — yani
plan baştan tutmuyor demektir. **Bugünün tarihi bu hesaba hiç girmiyor.**

Sonuç: ETA'sı 3 hafta önce dolmuş, malı hâlâ gelmemiş bir PO, teslim son tarihi 60 gün sonra
olduğu sürece **`in_transit` (mavi)** görünür. Ekranda hiçbir gecikme sinyali yoktur.

**Karşılaştırma — DeclarantQueue bunu doğru yapıyor:**
```python
days = (eta - today_d).days                                          # tender.py:2034
risk = "risk" if days < 0 else ("warn" if days <= 7 else "good")     # tender.py:2042-2046
```
ve ekranda `etaText()` "N days late" / "N days left" yazıyor, hücre kırmızıya boyanıyor
(`DeclarantQueue.vue:52-57, 82`).

**LogistBoard'da `days_left` alanı ne backend'de üretiliyor ne frontend'de gösteriliyor.**
Tek görsel ipucu: teslim son tarihi hücresinin `status === 'late'` iken kırmızıya boyanması
(`LogistBoard.vue:75`) — ve o da yukarıdaki dar tanıma bağlı.

### UAT-601 · ETA geçmiş, teslim tarihi ileride → ekran sessiz kalıyor

**Ön koşul:** Tender PO'su: `schedule_date = bugün - 21`, `per_received = 0`;
bağlı CRM Deal intake `delivery_deadline = bugün + 60`.

**Adımlar:**
1. `#/tender/logistics` aç, o satırı bul.

**Beklenen (kabul kriteri):** ETA 21 gün kaçmış bir sevkiyat GÖRÜNÜR biçimde işaretlenmeli.

**Gerçekte olan:** Rozet **"In transit"** (mavi), teslim son tarihi hücresi **normal renkte**,
gecikme günü **hiçbir yerde yazmıyor**. Filtreler de yakalamaz: `risk = "good"`,
`due = "on_time"` (`tender.py:2119-2120`).

**Kırık belirtisi:** `#/tender/logistics?due=late` bu satırı **getirmez**.

**Kanıt:** `tender.py:2099-2100, 2120-2121`, `LogistBoard.vue:50-51, 75`.
Karşı örnek: `tender.py:2033-2040`, `DeclarantQueue.vue:52-57, 82`.

---

### UAT-602 · Gecikme aslında masada görünüyor (ama başka kuralla)

**Ön koşul:** UAT-601'deki PO, ek olarak **`docstatus = 1`** (onaylanmış).

**Adımlar:**
1. `#/tender/desk?view=logist` aç.
2. "Geciken" bandına bak.

**Beklenen:** `po_late` kalemi ÇIKAR — `_desk_rules.py:166` bugünü karşılaştırıyor:
```python
if sched_date and sched_date < today_date and per_received < 100.0:
```
Başlık `Late delivery: <PO>`, gerekçe `... past by 21 days (0% received)`.

**Bu, sistemdeki tek gerçek ETA gecikme uyarısıdır** — ve lojistikçinin ASIL ekranında değil,
masada duruyor.

**Kırık belirtisi:**
- PO taslak (`docstatus = 0`) ise masada da **çıkmaz** (`tender_desk.py:148`), oysa
  LogistBoard onu listeler (`tender.py:2012` `docstatus < 2`). İki ekran çelişir.
- Kaleme tıklayınca `/purchasing/orders/<PO>` → UAT-105'teki router muhafızı sorunu.

**Kanıt:** `_desk_rules.py:155-178`, `tender_desk.py:145-162`, `tender.py:2005-2016`.

---

### UAT-603 · Gecikme uyarısı e-posta / bildirim olarak geliyor mu

**Adımlar:**
1. Bir tender PO'sunun ETA'sını geçmişe al.
2. 24 saat bekle veya `hooks.py` scheduler kayıtlarını incele.

**Beklenen (kabul kriteri):** Gecikmede lojistikçiye bir bildirim gitmeli.

**Gerçekte:** Yüklenen kaynak ağacında lojistik gecikmesi için **hiçbir zamanlanmış görev,
bildirim ya da e-posta üretici yok**. Tek "canlılık" mekanizması ekran açıkken 60 saniyelik
`useAutoRefresh` (STATE.md:61). Lojistikçi ekrana bakmıyorsa gecikmeyi hiç öğrenmez.

**Kırık belirtisi:** Yok — özellik hiç yok. Eksik olarak §8'e yazıldı.

**Kanıt:** `tender.py` / `tender_desk.py` / `_desk_rules.py` içinde `sendmail`,
`notification`, `enqueue`, `scheduler_events` geçmiyor; `LogistBoard.vue:42`.

---

## 7. YETKİ — lojistikçi elle URL yazarsa

Ortak arka plan: **router'da rol/view muhafızı YOK.** `router.beforeEach` yalnız
`meta.module` bakıyor (`router.js:612-635`); tender'ın sekiz alt yolunun hepsinde
`module: "tender"` yazıyor (`router.js:265-276`). Yani `tender` modülüne erişen herkes
**her tender URL'ini açabilir**. Tek gerçek sınır, sayfanın çağırdığı uç noktanın kapısı.

**Menü tarafı (`TenderNav.vue:37-61`) saf lojistikçide ne gösterir:**

| Bağlantı | Koşul | Lojistikçide |
|---|---|---|
| Overview (`/dashboard`) | koşulsuz | **GÖRÜNÜR** |
| Operations desk (`/tender/desk`) | `tenderViews.length > 0` | **GÖRÜNÜR** |
| Process flow (`/tender/flow`) | `can('director')` | gizli |
| Contract board (`/tender/board`) | koşulsuz | **GÖRÜNÜR** |
| Director board (`/tender/portfolio`) | `can('director')` | gizli |
| Tender CRM (`/tender/crm`) | `can('director') \|\| can('sourcing')` | gizli |
| My tenders (`/tender/my-tenders`) | `can('sourcing')` | gizli |
| Tender PO control (`/tender/po-control`) | `can('sourcing')` | gizli |
| Customs queue (`/tender/customs`) | `can('declarant')` | gizli |
| Logistics (`/tender/logistics`) | `can('logist')` | **GÖRÜNÜR** |

`/tender/sourcing` (Sourcing comparison) menüde **hiç yok** — yalnız PoControlBoard içindeki
bir düğmeden erişiliyor (`PoControlBoard.vue:290-292`).

---

### UAT-701 · `/tender/flow` — **AÇILIR, VERİ GELİR (yetki sızıntısı)**

**Ön koşul:** rol = `Stabler Logist`, şirket = Mikas.
**URL:** `https://mikas.erpstable.com/stabler#/tender/flow`

**Adımlar:**
1. URL'i elle yaz, Enter.
2. Ağ sekmesinde `stabler.api.tender.tender_flow` yanıtını incele.

**Beklenen (kabul kriteri):** Menüde gizlenen ekran backend'de de reddedilmeli.

**Gerçekte olan — SIZINTI:**
- Menüde bağlantı **yok** (`TenderNav.vue:40-42`, `can('director')`).
- Router **geçirir** (`router.js:267`, yalnız `module: "tender"`).
- `tender_flow` kapıları: `_require_tender` + `_assert_company_scope` + `_require_company`
  (`tender.py:3015-3017`) — **`_require_tender_view` ÇAĞRILMIYOR**.
- Sonuç: **HTTP 200**, ekran dolu. Lojistikçi tüm ihale hattının adım adım açık iş sayısını,
  ortalama bekleme sürelerini, SLA aşımlarını ve darboğazı görür.

**Kırık belirtisi:** Bu testin "beklenen"i geçmiyorsa (yani 200 dönüyorsa) sızıntı
doğrulanmıştır. **Bu bir bulgu, kabul değil.**

**Kanıt:** `tender.py:3002-3017` (kapı listesinde view yok), `router.js:267`,
`TenderNav.vue:40-42`, `TenderFlow.vue:37`.

---

### UAT-702 · `/tender/portfolio` — **AÇILIR AMA VERİ GELMEZ (doğru red)**

**URL:** `https://mikas.erpstable.com/stabler#/tender/portfolio`

**Adımlar:**
1. URL'i elle yaz, Enter.
2. Ekranı ve ağ yanıtını incele.

**Beklenen:**
- Menüde bağlantı yok (`TenderNav.vue:44-46`).
- Router geçirir → **DirectorBoard bileşeni MOUNT olur**, `.stbl-ds` başlığı ve
  TenderNav çizilir (`DirectorBoard.vue:132-133`).
- `stabler.api.tender.tender_director_board` → **`PermissionError: Not permitted`**
  (`tender.py:1990` → `tender.py:1738-1743`).
- Kullanıcı **hata toast'ı görür ve boş pano ile kalır** — temiz bir "yetkin yok" sayfası
  değil.
- `tender_managers` ve `assign_tender` de aynı şekilde reddedilir (`tender.py:1764`,
  `tender.py:1788-1789`).

**Kırık belirtisi:** Ekranda gerçek portföy satırları görünüyorsa hesap `director` rolü de
taşıyor (UAT-000'e dön). Boş pano + hata yerine `/error`'a atılıyorsa router davranışı
değişmiştir.

**Kanıt:** `tender.py:1983-1991`, `tender.py:1738-1743`, `router.js:273`,
`DirectorBoard.vue:40, 130-133`, `TenderNav.vue:44-46`.

---

### UAT-703 · `/tender/crm` — **AÇILIR, TÜM KANBAN GELİR (yetki sızıntısı)**

**URL:** `https://mikas.erpstable.com/stabler#/tender/crm`

**Adımlar:**
1. URL'i elle yaz, Enter.
2. Yedi kulvarı (Intake · GO Decision · Sourcing · Bid Pricing · Submitted · Won · Lost) say.
3. Bir kartı başka kulvara **sürüklemeyi dene**.

**Beklenen (kabul kriteri):** Menüde gizlenen ekran backend'de reddedilmeli.

**Gerçekte olan — SIZINTI:**
- `crm_board` kapıları: `_require_tender` + `_assert_company_scope` + `_require_company`
  (`tender.py:2305-2307`) — **view kapısı YOK**.
- **HTTP 200**; şirketteki tüm tender deal'leri, sözleşme değerleri, teklif sayıları ve
  aşamaları görünür (demo'da 13 kart).
- Sürükleme `move_deal_stage` çağırır (`TenderCrm.vue:175`); bu uç noktanın kapısı CRM Deal
  **write** iznidir (`tender.py:2451`+). Saf lojistikçide write izni YOKSA reddedilir —
  yani okuma açık, yazma doctype iznine bağlı.

**Kırık belirtisi:** Sürükleme başarılı oluyorsa lojistikçiye CRM Deal write izni verilmiş
demektir; rol kurulumu hatalıdır (UAT-000 adım 5'i gözden geçir).

**Kanıt:** `tender.py:2288-2306`, `router.js:269`, `TenderCrm.vue:43, 175`,
`TenderNav.vue:47-49`.

---

### UAT-704 · `/tender/sourcing` — **AÇILIR, TEDARİKÇİ TEKLİFLERİ GELİR**

**URL:** `https://mikas.erpstable.com/stabler#/tender/sourcing`

**Adımlar:**
1. URL'i elle yaz, Enter.
2. Deal arama kutusuna bir tender adı yaz, seç.

**Beklenen:**
- Ekran açılır (`router.js:270`, `module: "tender"`).
- Arama `stabler.api.crm.list_deals` çağırır (`SourcingCompare.vue:27`) — bu uç noktaya
  WP-001 kapsamında `has_permission("CRM Deal","read")` eklendi (STATE.md §1); izin yoksa
  liste boş döner, hata değil.
- Deal seçilince `stabler.api.purchasing.tender_quotations` çağrılır
  (`SourcingCompare.vue:44`). Bu dosya yüklenen alt ağaçta **yok** — kapısı bu UAT'ta
  doğrulanamıyor, **sitede ayrıca test edilmeli**.

**Kabul kriteri:** `tender_quotations` yanıtı 200 ve dolu geliyorsa, lojistikçi tedarikçi
fiyat tekliflerini (rakip fiyatları) görüyor demektir — bu bir sızıntıdır ve ayrı bir bulgu
olarak kaydedilmelidir. `PermissionError` dönüyorsa kapı doğrudur.

**Kırık belirtisi:** Deal seçildiğinde tedarikçi/fiyat tablosu doluyorsa sızıntı doğrulanmıştır.

**Kanıt:** `router.js:270`, `SourcingCompare.vue:27, 44`, `TenderNav.vue` (bu yol menüde hiç
yok), `PoControlBoard.vue:290-292` (tek erişim düğmesi, o da lojistikçide gizli sayfada).

---

### UAT-705 · `/tender/po-control` — bkz. UAT-402 (açılır, belge zinciri gelir)

**Özet beklenen:** Sayfa açılır, Overview/Vendor & PO/Delivery sekmeleri çalışır,
Finance sekmesi görünmez. Kanıt ve ayrıntı UAT-402'de.

---

### UAT-706 · `/tender/customs` ve `/tender/my-tenders`

**URL 1:** `#/tender/customs` → `declarant_queue` → `_require_tender_view("declarant", ...)`
(`tender.py:2023`) → **`PermissionError` (doğru red)**. Ekran mount olur, tablo boş, toast
"Could not load the customs queue." (`DeclarantQueue.vue:36`).

**URL 2:** `#/tender/my-tenders` → `sourcing_my_tenders` →
`_require_tender_view("sourcing", ...)` (`tender.py:2126`) → **`PermissionError` (doğru red)**.

**Kırık belirtisi:** Bu iki ekrandan biri veri döndürüyorsa view kapısı kaldırılmıştır.

**Kanıt:** `tender.py:2020-2023`, `tender.py:2123-2126`, `router.js:275, 274`.

---

### UAT-707 · Yetki özet tablosu (tek bakışta)

| URL | Menüde | Router | Backend kapısı | Sonuç |
|---|---|---|---|---|
| `/tender/logistics` | **var** | geçer | `_require_tender_view("logist")` `tender.py:2066` | **200 — doğru** |
| `/tender/desk` | **var** | geçer | `_tender_views` boş değil `tender_desk.py:35-37` | **200 — doğru** |
| `/tender/board` | **var** | geçer | `so_board` (`tender.py:85-86`) | 200 |
| `/tender/flow` | yok | geçer | **view kapısı YOK** `tender.py:3015-3017` | **200 — SIZINTI** |
| `/tender/crm` | yok | geçer | **view kapısı YOK** `tender.py:2305-2307` | **200 — SIZINTI** |
| `/tender/po-control` | yok | geçer | **view kapısı YOK** `tender.py:471-476`, `977-988` | **200 — SIZINTI** |
| `/tender/sourcing` | yok | geçer | `crm.list_deals` + `purchasing.tender_quotations` (doğrulanamadı) | **sitede test et** |
| `/tender/portfolio` | yok | geçer | `_require_tender_view("director")` `tender.py:1990` | **403 — doğru** |
| `/tender/customs` | yok | geçer | `_require_tender_view("declarant")` `tender.py:2023` | **403 — doğru** |
| `/tender/my-tenders` | yok | geçer | `_require_tender_view("sourcing")` `tender.py:2126` | **403 — doğru** |

**Genel kırık belirtisi:** Üç "SIZINTI" satırının hiçbirinde kullanıcıya temiz bir "yetkiniz
yok" sayfası gösterilmiyor; ya veri geliyor ya da boş ekran + toast. Router'da view muhafızı
olmadığı için tutarlı bir davranış hiçbir yolda yok.

---

## 8. Tasarım katmanı — `.stbl-ds` LogistBoard'da YOK

`.stbl-ds` sınıfı `public/css/stabler-modernist.css` katmanını **açan anahtar**; katmandaki
her kural bu sarmalayıcıya scope'lu, sınıfı taşımayan ekran tek bir kural bile görmez
(`OperationsDesk.vue:2-5` yorumu).

**Taşınmış ekranlar (`.stbl-ds` var):** OperationsDesk (`:5`), DirectorBoard (`:132`),
TenderFlow (`:119`), TenderCrm (`:248`), TenderNav (`:29`).

**Taşınmamış ekranlar (`.stbl-ds` YOK):** **LogistBoard (`:57` → `container-xl py-3`)**,
DeclarantQueue (`:63`), PoControlBoard (`:281`), MyTenders (`:97`), SourcingCompare (`:67`).

Yani lojistikçinin **asıl ekranı taşınmamış**, ama üstündeki modül çubuğu (`TenderNav`)
taşınmış. Aynı ekranda iki tasarım dili yan yana.

### UAT-801 · Görsel kopukluk — çubuk ile gövde arasında

**Ön koşul:** rol = `Stabler Logist`.
**URL:** `https://mikas.erpstable.com/stabler#/tender/logistics`

**Adımlar:**
1. Ekranı aç, üstteki modül çubuğu ile altındaki tablo kartını yan yana incele.
2. DevTools → `<nav class="stbl-ds tender-modnav">` ve `<div class="container-xl py-3">`
   elemanlarını seç, hesaplanan tipografi/renk/kenarlık değerlerini karşılaştır.

**Beklenen (somut kopukluk noktaları):**
- **Çubuk** `ds-modnav` kurallarını alır, ekranın iç boşluğunu taşırıp tam genişliğe oturur
  (`TenderNav.vue:69-77`: `margin: -12px -12px 16px`, ≥992px'te `-16px -20px 18px`).
- **Gövde** `container-xl` içinde Tabler varsayılanlarıyla kalır — `h2`, `card`,
  `table card-table`, `badge bg-*-lt` (`LogistBoard.vue:58, 60-61, 76`).
- Sonuç: çubuk kenardan kenara, tablo kartı ortalanmış ve dar; iki blok **aynı sol kenara
  hizalanmaz**.
- Rozetler `bg-green-lt text-green` gibi **literal Tabler sınıfları** (`LogistBoard.vue:50`),
  masadaki `data-sev` tabanlı severity dili değil (`OperationsDesk.vue:114, 128`).

**Kırık belirtisi:** Kullanıcı masadan (`/tender/desk`, koyu başlıklı `ds-page-head`,
`ds-kpi` kartları) lojistik panosuna geçtiğinde **başka bir uygulamaya girmiş gibi** hisseder:
başlık tipografisi, kart kenarlıkları, boşluk ritmi ve rozet dili tümüyle değişir.

**Kanıt:** `LogistBoard.vue:57-58` (`.stbl-ds` yok), `TenderNav.vue:29, 66-77`,
`OperationsDesk.vue:2-5`, `DirectorBoard.vue:130-132`, `public/css/stabler-modernist.css`.

---

### UAT-802 · Boş durum bileşeni iki dilde

**Adımlar:**
1. `#/tender/logistics` boşken `EmptyState` kutusunu incele.
2. `#/tender/desk?view=logist` boşken `.ds-panel-foot.desk-state` kutusunu incele.

**Beklenen:** İkisi **farklı görünür** — LogistBoard `EmptyState.vue` bileşenini ikonla
kullanıyor (`LogistBoard.vue:80`), masa ise tasarım katmanının panel altlığını iki satırlık
dikey yığına çeviriyor (`OperationsDesk.vue:80-83`, `.desk-state` `:571-577`).

**Kırık belirtisi:** Aynı rolün iki ekranında "veri yok" iki farklı dille anlatılıyor.

**Kanıt:** `LogistBoard.vue:80`, `OperationsDesk.vue:80-83, 569-577`.

---

### UAT-803 · Skeleton (yükleniyor) durumu

**Adımlar:**
1. Ağı yavaşlat (DevTools → Slow 3G), `#/tender/logistics` aç.

**Beklenen:** 7 sütun × 6 satır iskelet çizilir (`SkeletonRows :cols="7" :rows="6"`,
`LogistBoard.vue:68`) ve tablo başlıkları zaten görünür durumdadır.
Masa ise `:rows="6" :cols="3"` kullanır (`OperationsDesk.vue:71`).

**Kırık belirtisi:** İskelet sütun sayısı tablo sütun sayısıyla uyuşmuyorsa yükleme sırasında
tablo zıplar.

**Kanıt:** `LogistBoard.vue:62-68`, `OperationsDesk.vue:71`.

---

## 9. Demo'nun üretmediği kayıtlar

### `seed_tender_demo.seed()` NE üretiyor

| Doctype | Adet | Kanıt |
|---|---|---|
| `CRM Deal` | **13** (UTY-2026-4301…4316) | `seed_tender_demo.py:51-71, 178-188` |
| `CRM Organization` | ≤5 (`[DEMO]` ekli alıcı kurumlar) | `seed_tender_demo.py:110-119` |
| `CRM Stage Event` | aşama yoluna göre değişken | `seed_tender_demo.py:211-248` |
| CRM Deal alanları | `custom_tender_intake`, `custom_tender_stage`, `custom_tender_stage_entered_at`, `custom_bid_pricing` | `seed_tender_demo.py:182-201` |

### `seed_tender_demo.seed()` NE ÜRETMİYOR — lojistik tarafı **tamamen boş**

Seed betiğinin **kendi çıktısı** bunu itiraf ediyor:

```python
print("\nVisible on: /tender/desk · /tender/crm · /tender/portfolio · /tender/flow")
```
— `seed_tender_demo.py:208`

**`/tender/logistics` bu listede YOK.** Dosya başındaki "NE ÜRETİYOR VE NEDEN" bloğu da
(`seed_tender_demo.py:9-24`) yalnız dört panodan söz ediyor: Operasyon Masası, Tender CRM,
Direktör panosu, Süreç akışı. Lojistik ve gümrük panoları hiç anılmıyor.

**Sonuç zinciri:**
```
seed hiç Purchase Order üretmiyor
  → _po_rows_for_views(company) boş liste döner        (tender.py:2005-2016)
  → logist_board {"rows": []} döner                     (tender.py:2071, 2122)
  → LogistBoard "No shipments match these filters."     (LogistBoard.vue:80)
  → declarant_queue da boş                              (tender.py:2033)
  → masada po_late kalemi hiç çıkmaz                    (tender_desk.py:146-162)
  → belge zinciri altı kutunun altısı da boş            (tender.py:755-829)
```

### Demo'nun üretmesi gereken kayıtlar (ekran dolu görünsün diye)

Aşağıdaki liste, **§1–§6'daki her senaryonun** en az bir kez tetiklenebilmesi için gereken
asgari kümedir. `seed_tender_demo.py` bunların **hiçbirini** üretmiyor.

| # | Doctype | Adet | Zorunlu alanlar | Hangi senaryoyu açar |
|---|---|---|---|---|
| 1 | `Supplier` | **3** | `[DEMO]` ekli ad, company=Mikas | PO'ların tedarikçisi; UAT-103 "Vendor" sütunu |
| 2 | `Item` | **2** | stok kalemi, `[DEMO]` | PO/SO satırları için |
| 3 | `Supplier Quotation` | **10** (4308'e 5, 4310'a 5) | `custom_crm_deal`, `docstatus=1` | Masada `policy_gap` kaleminin **kaybolmasını** test etmek (`_desk_rules.py:103`); UAT-704 |
| 4 | **`Purchase Order`** | **6** | `company`, **`custom_crm_deal`**, `supplier`, `schedule_date`, `docstatus` | **LogistBoard'ın TÜM satırları.** Dağılım aşağıda |
| 5 | `PO.custom_landed_charges` | 6 PO'nun **4'ünde** | `[{"type":"transport","amount":…},{"type":"loading",…},{"type":"customs","tnved":"8607.19",…}]` | UAT-103 "Transport" sütunu; UAT-501 deklarant/logist ayrımı |
| 6 | `Purchase Receipt` | **2** (PO#1 tam, PO#2 kısmi) | `purchase_order` bağı, `docstatus=1` | `per_received` üretir → UAT-104 "Delivered" rozeti; belge zinciri "Receipt" kutusu |
| 7 | `Purchase Invoice` | **2** | `purchase_order` bağı; biri `outstanding > 0`, `due_date < bugün` | Belge zinciri "Invoice"; masada `invoice_due` |
| 8 | **`Sales Order`** | **3** | `company`, **`custom_crm_deal`**, `delivery_date`, `docstatus=1` | UAT-303 teslim tarihi ikinci kaynağı; belge zinciri satış tarafı |
| 9 | `Delivery Note` | **1** | `against_sales_order` bağı | Belge zinciri "Delivery"; müşteriye gerçek teslimin `per_received`'dan AYRI olduğunu göstermek (UAT-104) |
| 10 | `Sales Invoice` | **1** | `sales_order` bağı | Belge zinciri satış faturası |
| 11 | CRM Deal intake `delivery_deadline` | mevcut 13 deal'de zaten var (`bugün+90`) | — | Ama **PO olmadan işe yaramıyor** (`seed_tender_demo.py:133`) |
| 12 | CRM Deal intake `documents` | **şema düzeltilmeli** | `{"label","required","done","date"}` — şu an `{"name","status"}` | UAT-403; `tender.py:1478-1486` |
| 13 | `Approval` / onay isteği | **2** | `reference_doctype = "Purchase Order"` | Masadaki "Decision box" ve `awaiting_me` sayacı (`tender_desk.py:189-192`) |

**6 Purchase Order'ın olması gereken dağılımı** (her durum kovasını doldurmak için):

| PO | `custom_crm_deal` | `docstatus` | `schedule_date` | `per_received` | intake `delivery_deadline` | LogistBoard durumu | Neyi test eder |
|---|---|---|---|---|---|---|---|
| PO-1 | 4314 (won) | 1 | bugün+20 | 0 | bugün+90 | `in_transit` | Normal satır |
| PO-2 | 4314 (won) | 1 | bugün+120 | 0 | bugün+90 | **`late`** | UAT-106 `?due=late`; ETA > teslim |
| PO-3 | 4315 (won) | 1 | **bugün−21** | 0 | bugün+90 | `in_transit` ⚠ | **UAT-601** — ETA kaçmış ama ekran sessiz |
| PO-4 | 4315 (won) | 1 | bugün−5 | 100 | bugün+90 | `delivered` | UAT-104 yanlış etiket |
| PO-5 | 4310 (priced) | **0 (taslak)** | bugün−3 | 0 | bugün+90 | `in_transit` | **UAT-602/203** — LogistBoard gösterir, masa göstermez |
| PO-6 | 4316 (lost) | 1 | bugün+10 | 40 | bugün+90 | `in_transit` | Kısmi kabul |

**Doğrulama komutu (seed sonrası):**
```bash
bench --site mikas.erpstable.com console
>>> frappe.db.count("Purchase Order", {"company":"Mikas","custom_crm_deal":["is","set"]})
```
**Beklenen:** `6`. Demo'nun mevcut hâlinde bu sayı **`0`**'dır.

**Ek kontrol:** `custom_crm_deal` ve `custom_landed_charges` kolonlarının var olduğunu
doğrula — yoksa `_po_rows_for_views` daha ilk satırda `([], False)` döner (`tender.py:1994-1995`)
ve LogistBoard hiçbir zaman dolmaz:
```bash
>>> frappe.db.has_column("Purchase Order", "custom_crm_deal")      # True olmalı (patch v34)
>>> frappe.db.has_column("Purchase Order", "custom_landed_charges") # True olmalı
```

---

## 10. Lojistikçinin yapamadıkları

Her madde kanıtlı; hiçbiri "iyileştirme önerisi" değil, **kaynakta olmayan** özelliktir.

1. **Konteyner / taşıyıcı / sefer bilgisi giremez ve göremez.** LogistBoard'ın döndürdüğü
   satırın tüm alanları: `po`, `supplier_name`, `deal`, `deal_label`, `transport`,
   `event_date`, `eta`, `delivery`, `received`, `stage`, `status`, `risk`, `due`
   (`tender.py:2101-2121`). Konteyner alanı yok. Sistemde `Import Container` doctype'ı ve
   9 durumlu bir hat VAR (`composables/status.js:141-152`, `router.js:218-221`) ama tender
   hattına bağlı değil.

2. **Konşimento (B/L), CMR, packing list yükleyemez / göremez.** Belge zinciri yalnız altı
   ERPNext doctype'ını tanıyor (`tender.py:755-829`); bu üç evrak kaynakta hiç geçmiyor.

3. **Hiçbir şey yazamaz — ekran salt okunur.** `LogistBoard.vue`'da tek `call()` var ve o da
   `logist_board` okuması (`LogistBoard.vue:34`). Kaydet/güncelle/durum değiştir düğmesi yok.
   Dosyanın kendi başlığı: "Read-only" (`LogistBoard.vue:3`).

4. **ETA'yı güncelleyemez.** ETA `PO.schedule_date`'tir; değiştirmek Purchase Order write
   izni + `purchasing` modülü ister. Lojistikçi rolünde ikisi de standart değil.

5. **"Malı teslim ettim" diyemez.** Teslim işareti `Delivery Note` kesmekten geçer; bu
   ekranda yok, `sales` modülü ister.

6. **Gecikmeyi kendi ekranından göremez** (ETA geçmiş ama teslim tarihi ileride olan durum) —
   `late` tanımı bugünü hiç kullanmıyor (`tender.py:2099`). Gecikme yalnız masada, `po_late`
   kuralıyla ve yalnız **onaylanmış** PO'lar için görünür (`tender_desk.py:148`,
   `_desk_rules.py:166`).

7. **Gecikme bildirimi almaz.** Zamanlanmış görev / e-posta / bildirim üreticisi yok; tek
   mekanizma ekran açıkken 60 sn'lik `useAutoRefresh` (STATE.md:61).

8. **Satıra tıklayıp PO'yu açamaz** (tender-only kullanıcıda): rota adı `purchasing-order`,
   drill-down istisnası ise `purchasing-orders` bekliyor ve `tender_only=1` query'si
   eklenmiyor → router `landingPath` ile başka yere atar; `LANDING_ORDER`'da `tender`
   anahtarı olmadığı için saf lojistikçide sonuç `/error`
   (`LogistBoard.vue:52`, `router.js:335, 613-635, 518-544`).

9. **Belge zincirine menüden ulaşamaz** — zincir yalnız `/tender/po-control`'ün "Delivery"
   sekmesinde, o da `can('sourcing')` ile gizli (`TenderNav.vue:53-55`,
   `PoControlBoard.vue:452-454`).

10. **Masadan lojistik panosuna tek tıkla dönemez** — `OperationsDesk.vue` `TenderNav`
    render etmiyor; kenar çubuğunun tek tender maddesi `/tender/board`'a gider
    (`Sidebar.vue:79`).

11. **Kendisine devredilen işleri ayıramaz.** Deklarant kuyruğu ile lojistik panosu aynı
    `_po_rows_for_views` sonucunu gösteriyor (`tender.py:1993`); "devir" kaydı, sahiplik
    alanı ya da durum geçişi yok.

12. **Masada kendi işini süzemez.** `_desk_rules.build_plan` rol parametresi almıyor
    (`_desk_rules.py:22`); `tender_desk.py`'deki tek rol süzgeci `sourcing`'e ait
    (`tender_desk.py:89-91`). Lojistikçi teklif son tarihi ve eksik tedarikçi teklifi
    kalemleriyle dolu bir liste görüyor.

13. **Finans rakamlarını göremez** — `_can_view_tender_finance` oversight ya da
    `Accounts User/Manager` istiyor (`tender.py:2574-2577`); `tender_workspace` finance
    bloğunu hiç döndürmez, sekme çizilmez (`TenderWorkspaceTabs.vue:18`).

14. **Görsel olarak yeni tasarım katmanının dışında** — `LogistBoard.vue` `.stbl-ds`
    taşımıyor (`:57`), ama üstündeki `TenderNav` taşıyor (`:29`). Aynı ekranda iki dil.

15. **Boş ekranın sebebini anlayamaz** — "No shipments match these filters." metni,
    filtre olmadığı hâlde "filtre" diyor (`LogistBoard.vue:80`).

---

## 11. Test kapanış listesi

| Senaryo | Konu | Beklenen sonuç |
|---|---|---|
| UAT-000 | Hesap kurulumu | `views == ["logist"]` |
| UAT-101 | Ekran açılıyor | 200 |
| UAT-102 | Boş durum | EmptyState + yanıltıcı metin notu |
| UAT-103 | Sütun doğrulama | 7 sütun, ETA sıralı |
| UAT-104 | "Delivered" rozeti | **Yanlış etiket — bulgu** |
| UAT-105 | Satıra tıklama | **`/error` — bulgu** |
| UAT-106 | URL filtreleri | `due`/`risk`/`status` süzer |
| UAT-107 | Otomatik yenileme + ESC | 60 sn / `/tender/board` |
| UAT-201 | Masa açılıyor | Rol seçici yok, ham `logist` etiketi |
| UAT-202 | Masada yabancı kalemler | **Rol süzgeci yok — bulgu** |
| UAT-203 | `po_late` | Tek gerçek lojistik kalemi |
| UAT-204 | Masada TenderNav yok | **Geri dönüş yolu yok — bulgu** |
| UAT-205 | Team load | Görünmemeli |
| UAT-301 | Konteyner/taşıyıcı | **Alan yok — bulgu** |
| UAT-302 | ETA kaynağı | Başlık `schedule_date` |
| UAT-303 | Teslim tarihi çakışması | intake önceliklidir |
| UAT-401 | Zincir menüde mi | **Hayır — bulgu** |
| UAT-402 | Zincire URL ile erişim | **Açılır — sızıntı** |
| UAT-403 | Belge kontrol listesi | **Şema uyuşmazlığı — bulgu** |
| UAT-501 | Deklarant/logist aynı liste | **Devir yok — bulgu** |
| UAT-502 | `per_received=100` | İki rozet aynı anda değişir |
| UAT-601 | ETA kaçtı | **Ekran sessiz — bulgu** |
| UAT-602 | Masada `po_late` | Çıkar (yalnız `docstatus=1`) |
| UAT-603 | Bildirim | **Yok — bulgu** |
| UAT-701 | `/tender/flow` | **200 — sızıntı** |
| UAT-702 | `/tender/portfolio` | 403 — doğru |
| UAT-703 | `/tender/crm` | **200 — sızıntı** |
| UAT-704 | `/tender/sourcing` | Sitede doğrula |
| UAT-705 | `/tender/po-control` | **200 — sızıntı** |
| UAT-706 | `/tender/customs`, `/tender/my-tenders` | 403 — doğru |
| UAT-801 | `.stbl-ds` kopukluğu | Çubuk taşınmış, gövde taşınmamış |
| UAT-802 | Boş durum dili | İki farklı bileşen |
| UAT-803 | Skeleton | 7×6 |
