# UAT · 06 — GÜMRÜK BEYANNAMECİSİ (Declarant) rolü

**Kapsam:** Stabler ERP tender modülünde `declarant` rol penceresi. Bir gümrük
beyannamecisinin bir günü: sabah masası → gümrük kuyruğu → beyanname dosyası →
evrak kontrolü → vergi/harç hesabı → malı lojistiğe devir.

**Test edilen sürüm:** `/mnt/user-data/uploads/stabler/` altındaki kaynak.
**Şirket:** Mikas · **Demo veri:** `seed_tender_demo.seed(company="Mikas")`.

> **ÖNCE OKU:** Bu rolün ana ekranı olan `/tender/customs`, demo veriyle
> **her zaman boş açılır**. Sebebi §9'da kanıtla yazılı. Bu dosyadaki
> senaryoların çoğu, önce §9'daki elle veri kurulumu yapılmadan
> "boş ekran" sonucundan öteye geçmez. Bunu bir hata sanıp geri bildirim
> yazmadan önce §9'u koşun.

---

## 0. Test kullanıcısı ve rol haritası

Deklarant penceresi `_TENDER_VIEW_ROLES` sözlüğünden geliyor:

```
"declarant": ("System Manager", "Stabler Admin", "Sales Manager", "Stabler Declarant"),
```
— `stabler/api/tender.py:1728`

Gözetim (oversight) rolleri ayrı listede — `Stabler Declarant` bu listede **YOK**:

```
_OVERSIGHT_ROLES = ("System Manager", "Stabler Admin", "Sales Manager", "Stabler Tender Director")
```
— `stabler/api/tender.py:1752`

**Kritik ayrım:** `System Manager` / `Stabler Admin` / `Sales Manager` rollerinden
biri varsa kullanıcı DÖRT pencereyi birden görür (`director`, `sourcing`,
`declarant`, `logist`) ve bu dosyadaki yetki testlerinin hiçbiri anlam taşımaz.
Bu dokümandaki **"saf deklarant"** = *yalnız* `Stabler Declarant` rolü olan kullanıcı.

> ### UAT-600 · Test hesabı kurulumu (ön koşul, tüm senaryolar için)
>
> **Ön koşul:** Administrator olarak giriş.
> **Adımlar:**
> 1. `/app/user/new` → `declarant@mikas.uz` kullanıcısı oluştur.
> 2. Roller: **YALNIZ** `Stabler Declarant`. `Sales Manager`, `Sales User`,
>    `System Manager`, `Stabler Admin`, `Stabler Tender Director`, `Stabler Logist`
>    işaretli OLMAMALI.
> 3. `User Permission` ile şirketi Mikas'a bağla.
> 4. Mikas'ta `tender` modülünün açık olduğunu doğrula (Stabler Settings → module map).
> 5. Kullanıcının `Purchase Order` **read** iznini not et (var mı yok mu — §1.4 ve
>    §6 bu ayrımın üstünde duruyor).
> 6. `bench --site mikas.erpstable.com execute stabler.maintenance.seed_tender_demo.seed`
>
> **Beklenen:** `stabler.api.tender.tender_views` çağrısı `{"views": ["declarant"]}`
> döner — **tek elemanlı** liste.
> **Kırık belirtisi:** Listede `sourcing` veya `director` da varsa hesaba fazladan
> rol verilmiştir; §7'deki yetki testlerinin hiçbiri geçerli olmaz, baştan kur.
> **Kanıt:** `stabler/api/tender.py:1725-1735` (`_TENDER_VIEW_ROLES`, `_tender_views`),
> `1746-1749` (`tender_views`).

> ### UAT-600b · Giriş sonrası nereye düşüyor
>
> **Ön koşul:** `declarant@mikas.uz` girişli.
> **URL:** `https://mikas.erpstable.com/stabler/#/`
>
> **Adımlar:** Giriş yap, adres çubuğunun nereye gittiğine bak.
>
> **Beklenen (kaynağa göre):** Yönlendirme `landingPath(session)` ile hesaplanıyor
> ve `LANDING_ORDER` listesinde **`tender` anahtarı hiç yok** — liste
> `dashboard, money, sales, purchasing, imports, inventory, manufacturing, hr,
> field_sales, marketing, crm, service, bpm, remittance, installment, compliance`.
> Yani **yalnız tender modülü açık** bir kullanıcı için döngü hiç eşleşmez ve
> fonksiyon `"/error"` döner.
> **Kırık belirtisi:** Giriş sonrası boş/hata sayfası ("/error"). Bu durumda
> deklarant sisteme girip ekranını bulamaz; tek yolu URL'yi elle yazmak.
> Kullanıcıya `dashboard` modülü de açıksa `/dashboard`'a düşer — bunu doğrula
> ve hangi modüllerin açık olduğunu rapora yaz.
> **Kanıt:** `stabler/public/js/router.js:519-537` (`LANDING_ORDER`, tender yok),
> `539-544` (`landingPath`, eşleşme yoksa `"/error"`).

---

## 1. `/tender/customs` — Gümrük kuyruğu (DeclarantQueue)

Ekran kendi başlığında kendini "read-only" ilan ediyor:

```
// Declarant window — customs queue: every tender PO awaiting/clearing customs,
// with ТН ВЭД code, customs charge and arrival ETA. Read-only.
```
— `DeclarantQueue.vue:2-3`

### UAT-601 · Kuyruk açılıyor, doğru uç noktadan besleniyor

**Ön koşul:** rol = `Stabler Declarant`, şirket = Mikas.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/customs`

**Adımlar:**
1. Adres çubuğuna `/tender/customs` yaz, Enter.
2. Tarayıcı ağ sekmesini aç, `/api/method/...` çağrısını yakala.
3. Sayfa başlığını ve tablo sütunlarını oku.

**Beklenen:**
- Sayfa açılır. Başlık: **"Customs queue"** (`Gümrük kuyruğu`).
- Tek bir çağrı gider: `stabler.api.tender.declarant_queue`, gövde
  `{company: "Mikas"}`.
- Yanıt şekli: `{"currency": "<Mikas varsayılan para birimi>", "rows": [...]}`.
- Tablo **8 sütun**, sırasıyla: `PO` · `Vendor` · `Tender` · `HS code (ТН ВЭД)` ·
  `Customs` (sağa dayalı) · `PO ETA` · `Days left` · `Status`.
- Üstte `TenderNav` modül çubuğu görünür.

**Kırık belirtisi:** 403 / "Not permitted" → kullanıcıda `Stabler Declarant`
rolü yok ya da Mikas'ta tender modülü kapalı. Toast: *"Could not load the
customs queue."*
**Kanıt:** `DeclarantQueue.vue:34` (çağrı), `62-72` (başlık + sütunlar),
`35-38` (hata toast'ı); `tender.py:2020-2023` (uç nokta + `_require_tender_view("declarant", ...)`),
`2060` (dönüş şekli).

---

### UAT-602 · Kuyruğa NE düşüyor — satır seçme kuralı

**Ön koşul:** UAT-601 geçmiş.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/customs`

Kuyruğun kaynağı `_po_rows_for_views(company)`; filtre tam olarak şu:

```python
filters={"company": company, "custom_crm_deal": ["is", "set"], "docstatus": ["<", 2]},
order_by="schedule_date asc",
limit_page_length=2000,
```
— `tender.py:2010-2016`

**Adımlar:**
1. Mikas'ta bir Purchase Order aç, `custom_crm_deal` alanını **BOŞ** bırak, kaydet+onayla.
2. `/tender/customs` sayfasını yenile, bu PO'yu ara.
3. Aynı PO'ya bir CRM Deal bağla, tekrar yenile.
4. Bir PO'yu **taslak** (docstatus = 0) bırak, kuyruğa bak.
5. Bir PO'yu **iptal et** (docstatus = 2), kuyruğa bak.

**Beklenen:**
- (1-2) CRM Deal'e bağlı **olmayan** PO kuyrukta **görünmez**. Beyannamecinin işi
  ihale dışı bir ithalat ise sistem onu hiç göstermiyor.
- (3) Deal bağlanınca PO kuyruğa düşer.
- (4) **Taslak PO da kuyrukta görünür** (`docstatus < 2` taslağı kapsıyor) —
  henüz onaylanmamış, tedarikçiye gitmemiş bir sipariş beyanname kuyruğunda.
- (5) İptal edilen PO kuyruktan düşer.
- Kuyruk **2000 satırda kesiliyor**; ekranda "daha fazla var" uyarısı yok,
  sayfalama yok.

**Kırık belirtisi:** Taslak PO'nun kuyrukta çıkması bir hata değil, tasarım
sonucu — ama beyannameci "bu daha sipariş bile edilmemiş" diyorsa doğru
davranış `docstatus == 1` olmalı. Bulgu D2 olarak raporla.
**Kanıt:** `tender.py:1993-2017` (`_po_rows_for_views`), özellikle `2012` (filtre)
ve `2015` (limit).

---

### UAT-603 · Sıralama kuralı — ETA'ya göre artan, riske göre DEĞİL

**Ön koşul:** Kuyrukta en az 4 PO var; biri ETA'sı geçmiş, biri 3 gün sonra,
biri 60 gün sonra, birinin `schedule_date` alanı **boş**.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/customs`

**Adımlar:**
1. Kuyruğu aç, satırların sırasına bak.
2. `Days left` sütununda kırmızı/sarı yanan satırların nerede durduğunu not et.
3. Sütun başlıklarına tıklamayı dene.

**Beklenen:**
- Sıralama **yalnız** `schedule_date ASC` (PO ETA artan). SQL sıralaması ön yüzde
  hiç değiştirilmiyor — `filterTenderRows` yalnız süzüyor, sıralamıyor.
- `schedule_date` **boş** olan PO'lar (MariaDB'de NULL, ASC'de önce gelir)
  **listenin en başında** ve `PO ETA` / `Days left` sütunlarında `—` gösterir.
  Yani tarihi olmayan, sırası belirsiz kayıtlar en tepede oturuyor.
- Sütun başlıkları **tıklanamaz** — sıralama düğmesi yok.
- Gecikmiş satır (`days_left < 0`) `Days left` hücresinde **kırmızı**
  (`text-red`), 0-7 gün arası **sarı** (`text-yellow`). Ama satır **yukarı
  taşınmaz**; kırmızı satır listenin ortasında kalabilir.

**Kırık belirtisi:** Beyannameci "en acil olan" satırı görmek için tüm listeyi
gözle taramak zorunda. Riske göre sıralama yok; `risk` alanı API'den geliyor
(`tender.py:2036-2040`) ama ekranda **yalnız URL filtresi** olarak kullanılıyor,
sıralamada kullanılmıyor.
**Kanıt:** `tender.py:2014` (`order_by="schedule_date asc"`);
`DeclarantQueue.vue:48` (`filteredRows` yalnız filtre), `82` (renk sınıfları),
`68-72` (başlıklarda `@click` yok); `composables/tenderBoardFilters.js:36-47`
(`filterTenderRows` sıralama yapmıyor).

---

### UAT-604 · Durum rozeti gerçekte neyi söylüyor

**Ön koşul:** Kuyrukta üç farklı PO: (a) landed-charge planı hiç olmayan,
(b) `customs` tipli bir masraf satırı olan, (c) `per_received = 100` olan.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/customs`

Durum tek bir satırda türetiliyor:

```python
cleared = flt(p.per_received) >= 100
status = "cleared" if cleared else ("in_progress" if customs_total else "pending")
```
— `tender.py:2032, 2035`

**Adımlar:**
1. (a) PO'nun `Status` rozetine bak.
2. (b) PO'ya `/tender/po-control` üzerinden `customs` tipli, tutarı > 0 bir
   masraf satırı ekle. Kuyruğu yenile.
3. (c) PO için Purchase Receipt kes (`per_received = 100`). Kuyruğu yenile.
4. (b)'deki masraf satırının tutarını **0** yap (yalnız ТН ВЭД kodu kalsın).
   Kuyruğu yenile.

**Beklenen:**
- (a) `Pending` — sarı rozet (`bg-yellow-lt text-yellow`).
- (b) `In progress` — mavi rozet (`bg-blue-lt text-blue`).
- (c) `Cleared` — yeşil rozet (`bg-green-lt text-green`).
- (4) Rozet **`Pending`'e geri döner** — çünkü `customs_total` sıfırdır. ТН ВЭД
  kodu girilmiş olmasına rağmen "gümrük başlamadı" görünür.

**Kırık belirtisi (asıl bulgu):** Bu üç durum gümrük işleminin gerçek durumu
DEĞİL:
- `In progress` = "birisi bu PO'ya planlanmış bir gümrük masrafı yazdı".
  Beyanname verilmiş olmasıyla ilgisi yok.
- `Cleared` = "mal **depoya girdi**" (`per_received >= 100`). Bunu **ambar**
  yapar, beyannameci değil. Beyannameci hiçbir şeyi "cleared" işaretleyemez.
- Ekranın kendi yorumu bu; kaynak da bunu itiraf ediyor: dashboard tarafında aynı
  hesap `"basis": "planned_landed_customs_charge_not_clearance"` etiketiyle
  dönüyor ve yorum satırı *"No native PO-level customs clearance field exists in
  this install"* diyor.
**Kanıt:** `tender.py:2030-2035` (türetme), `2810-2816` (`customs_proxy` ve
`basis` etiketi); `DeclarantQueue.vue:50-51` (rozet sınıfları/etiketleri).

---

### UAT-605 · ТН ВЭД (HS) kodu sütunu — ilk bulduğunu yazıyor

**Ön koşul:** Bir PO'da iki farklı `customs` satırı, iki **farklı** ТН ВЭД kodu.
Ayrıca bir PO'da `transport` tipli bir satıra ТН ВЭД kodu yaz.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/customs`

Kod seçimi:

```python
tnved = next((c["tnved"] for c in charges if c.get("tnved")), "")
```
— `tender.py:2031`

**Adımlar:**
1. İki kodlu PO'nun `HS code (ТН ВЭД)` hücresine bak.
2. `transport` satırına kod yazılmış PO'nun aynı hücresine bak.

**Beklenen:**
- (1) **Yalnız ilk** kod görünür; ikincisi ekranda hiç yok. Çok kalemli bir
  beyannamede birden çok tarife pozisyonu olması normaldir — ekran bunu
  gösteremez.
- (2) `transport` satırındaki kod **gümrük kodu olarak** gösterilir; filtre
  `c["type"] == "customs"` demiyor, yalnız `c.get("tnved")` diyor.

**Kırık belirtisi:** Beyannameci ekrandaki koda güvenip beyannameyi yanlış
tarife pozisyonundan hazırlar. Sütun `font-monospace` ile "kesin veri" gibi
görünüyor.
**Kanıt:** `tender.py:2031` (tip kontrolü yok); `DeclarantQueue.vue:79`
(`{{ r.tnved || "—" }}`); karşılaştırma için `tender.py:2030` (`customs_total`
**tip kontrolü yapıyor**: `if c["type"] == "customs"`).

---

### UAT-606 · "Tender" sütunu — CRM izni yoksa boş

**Ön koşul:** İki kullanıcı: (A) saf deklarant (CRM Deal read **yok**),
(B) `Stabler Declarant` + CRM Deal read izni olan kullanıcı.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/customs`

```python
can_read_deal = bool(deal and frappe.has_permission("CRM Deal", "read", doc=deal))
"deal_label": _deal_label(deal) if can_read_deal else "",
```
— `tender.py:2042, 2048`

**Adımlar:**
1. (A) ile aç, `Tender` sütununa bak.
2. (B) ile aç, aynı sütuna bak.

**Beklenen:**
- (A) Tüm `Tender` hücreleri `—`. Beyannameci hangi ihaleye ait olduğunu
  göremez; elinde yalnız PO numarası vardır.
- (B) Hücrede **kurum adı** görünür (`_deal_label` sırasıyla `organization` →
  `lead_name` → deal id döndürür) — yani `O'zbekiston temir yo'llari AJ [DEMO]`
  gibi. **Lot numarası görünmez**, oysa ihaleyi ayırt eden şey lot numarasıdır
  (`custom_tender_intake.lot_no`).
- Aynı kurumun üç lotu varsa üç satır **aynı** metni gösterir.

**Kırık belirtisi:** (B) durumunda üç ayrı beyanname dosyası ekranda ayırt
edilemez.
**Kanıt:** `tender.py:1850-1855` (`_deal_label`), `2042-2048`;
`DeclarantQueue.vue:78`.

---

### UAT-607 · Satıra tıklayınca ne oluyor (modül duvarı)

**Ön koşul:** Saf deklarant; `purchasing` modülünün açık olup olmadığı UAT-600
adım 5'te not edilmiş.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/customs`

```js
function openPo(name) { router.push({ name: "purchasing-order", params: { name }, query: { ...route.query } }); }
```
— `DeclarantQueue.vue:58`

**Adımlar:**
1. Herhangi bir satıra tıkla (satır `cursor:pointer`).
2. Adres çubuğunu izle.

**Beklenen:**
- Hedef `/purchasing/orders/<PO adı>`. Bu rota `module: "purchasing"` taşıyor.
- **`purchasing` modülü kapalıysa:** yönlendirme muhafızı devreye girer,
  `landingPath(session)`'a atar. Tender bu listede olmadığı için kullanıcı
  `/error`'a ya da erişebildiği ilk modüle savrulur — **beyanname dosyası
  açılmaz**.
- **`purchasing` açıksa:** Purchase Order formu açılır; bu form tender ekranı
  değil, standart satınalma formudur.
- Muhafızdaki tek istisna `tender_only=1` sorgu parametreli **liste** rotaları
  (`purchasing-orders` vb.); tekil `purchasing-order` bu istisnada **yok**.

**Kırık belirtisi:** Tıklama sessizce başka bir sayfaya atıyor ya da hiçbir şey
olmuyor. Rolün kuyruktan dosyaya inen tek yolu bu tıklama.
**Kanıt:** `DeclarantQueue.vue:58, 75`; `router.js:335` (rota),
`router.js:612-635` (modül muhafızı ve `tenderDrilldownRoutes` istisnası —
`purchasing-order` listede yok), `519-544` (`LANDING_ORDER` / `landingPath`).

---

### UAT-608 · Filtreler, boş durum ve otomatik yenileme

**Ön koşul:** Kuyrukta en az 1 satır var.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/customs?risk=risk`

**Adımlar:**
1. URL'ye `?risk=risk` ekle → yalnız gecikmiş satırlar kalmalı.
2. `?due=soon` dene → yalnız 7 gün içindekiler.
3. `?status=cleared` dene.
4. `?period=2026-08` dene (PO `transaction_date` ayına göre).
5. Sağ üstteki "Clear filters" düğmesine bas.
6. Süzgeci hiçbir satırın geçemeyeceği bir değere ayarla (`?risk=risk` + hiç
   gecikmiş yokken).
7. Sayfayı açık bırak, 60 sn bekle, ağ sekmesine bak.

**Beklenen:**
- (1-4) İstemci tarafı süzme çalışır; desteklenen anahtarlar tam olarak
  `stage, period, risk, due, status, from_date, to_date`.
- Süzgeç etkinken başlığın sağında `risk: risk` gibi bir özet + "Clear filters"
  düğmesi belirir. **Süzgeç yokken düğme de görünmez** — yani ekranda hiç filtre
  arayüzü yoktur; filtreler yalnız URL'den ya da başka ekranların derin
  bağlantılarından gelir.
- (5) Sorgu tamamen temizlenir.
- (6) Boş durum: ikon + **"No purchase orders match these filters."**
- (7) 60 saniyede bir `declarant_queue` yeniden çağrılır (sekme gizliyken durur).
- `Esc` tuşu → `/tender/board`'a döner.

**Kırık belirtisi:** Kuyruk **hiç filtre yokken de boşsa** ekran yine
*"…match these filters"* der ve kullanıcıyı olmayan bir filtreyi aramaya
gönderir. Gerçek sebep §9'daki veri eksikliğidir. Bulgu D6.
**Kanıt:** `DeclarantQueue.vue:46-48, 59, 64` (filtre özeti/temizleme),
`87` (boş durum metni), `41-42` (`onMounted` + `useAutoRefresh`), `25`
(`useEscapeBack(null, "/tender/board")`);
`composables/tenderBoardFilters.js:1` (anahtar listesi);
`STATE.md:61` (auto-refresh 60 sn, `document.hidden`'da durur).

---

## 2. `/tender/desk?view=declarant` — Operasyon Masası

### UAT-611 · Masa açılıyor, rol seçici görünmüyor

**Ön koşul:** rol = `Stabler Declarant`, şirket = Mikas.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/desk?view=declarant`

**Adımlar:**
1. URL'yi yaz, Enter.
2. Sağ üstteki rol seçici açılır kutuyu ara.
3. Başlık satırındaki görünüm adına bak.
4. `?view=director` yazıp yenile.

**Beklenen:**
- Sayfa açılır; başlık **"What should I do today?"**.
- **Rol seçici GÖRÜNMEZ:** şablon `v-if="deskData?.views && deskData.views.length > 1"`
  diyor, saf deklarantta `views = [{"id":"declarant","label":"declarant"}]`.
- Üst satırda görünüm adı: `declarant`.
- (4) `?view=director` → `_require_tender_view("director", ...)` **PermissionError**
  atar; masa gövdesinde kırmızı hata satırı (`role="alert"`) görünür,
  metin "Not permitted".

**Kırık belirtisi:** `?view=director` ile veri gelirse yetkilendirme kırıktır —
derhal raporla.
**Kanıt:** `tender_desk.py:35-44` (`_tender_views`, boşsa throw, `view` verilmişse
`_require_tender_view`); `OperationsDesk.vue:21-32` (seçici koşulu), `17` (görünüm
adı), `79` (hata satırı), `261, 275-298` (`view` sorgu parametresi → çağrı).

---

### UAT-612 · `_desk_rules.py`'de deklaranta özel kural VAR MI

**Ön koşul:** UAT-611 geçmiş, demo veri yüklü.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/desk?view=declarant`

**Adımlar:**
1. Günlük iş planındaki kalemlerin `kind` etiketlerini (satır altındaki küçük
   gri yazı) tek tek not et.
2. Aynı sayfayı `Sales Manager` bir kullanıcıyla `?view=sourcing` ile aç ve
   listeleri karşılaştır.

**Beklenen (kaynağa göre):**
- Üretilen kalem türleri **tam olarak altı tane** ve **hiçbiri gümrükle ilgili
  değil**: `bid_due`, `bid_soon`, `policy_gap`, `no_parent`, `won_no_po`,
  `po_late`, `invoice_due`, `approval_pending`.
- `_desk_rules.build_plan` içinde `declarant`, `customs`, `tnved`, `ГТД`
  kelimeleri **hiç geçmiyor**.
- `operations_desk` içindeki tek rol filtresi **sourcing'e özel**:
  ```python
  if not oversight and view == "sourcing":
      deals = [d for d in deals if (d.get("assigned_to") == user or d.get("owner") == user)]
  ```
  `declarant` için **hiçbir daraltma yok** → deklarant, şirketteki **tüm**
  lotların teklif son tarihlerini, sahipsiz lotları, geciken PO'ları ve
  **ödenmemiş satınalma faturalarının kalan tutarlarını** görür.
- Sıralama: `severity` (overdue → today → soon → info) → `due` → `title`.
- Kalemlere tıklayınca `/tender/crm?deal=...`, `/purchasing/orders/...`,
  `/purchasing/invoices/...` rotalarına gider — deklarantın modül izni yoksa
  bunlar UAT-607'deki duvara çarpar.

**Kırık belirtisi (asıl bulgu):** Beyannamecinin masası, beyannameci işi
göstermiyor; teklif son tarihleri ve fatura ödemeleri gösteriyor. Rolün masası
ile rolün işi arasında bağ yok.
**Kanıt:** `_desk_rules.py:42-247` (altı kural bloğu, gümrük yok),
`249-256` (sıralama); `tender_desk.py:89-91` (yalnız sourcing daraltması),
`212-219` (facts sözlüğü — gümrükle ilgili hiçbir olgu yok),
`_desk_rules.py:73, 175, 200` (rota üretimi).

---

### UAT-613 · Karar kutusu ve takım yükü

**Ön koşul:** Sistemde en az bir bekleyen onay var.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/desk?view=declarant`

**Adımlar:**
1. "Karar" bölümüne bak — kaç kalem var, kimin talebi.
2. Takım yükü (team load) tablosunu ara.

**Beklenen:**
- Takım yükü **boş** — yalnız `oversight` rollerine dolduruluyor, deklarant
  oversight değil.
- Karar kutusu koşulu `a.get("assigned_to") == user or a.get("requested_by") != user or oversight`
  — ikinci şart neredeyse her zaman doğru olduğu için deklarant, **kendisiyle
  ilgisi olmayan bekleyen onayları da** görür.

**Kırık belirtisi:** Deklarant onaylayamayacağı kararları listede görüyor.
**Kanıt:** `tender_desk.py:225-233` (karar/bekleyen ayrımı), `257-277`
(takım yükü yalnız oversight).

---

## 3. Beyanname dosyası ve evrak zinciri

### UAT-621 · Gerekli evrak listesi nerede — ve deklarant ona ulaşabiliyor mu

**Ön koşul:** Saf deklarant girişli.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/customs`

**Adımlar:**
1. Kuyruktaki bir satırdan evrak listesine gitmeye çalış.
2. `TenderNav` çubuğunda evrak/belge sözü geçen bir bağlantı ara.
3. Elle `https://mikas.erpstable.com/stabler/#/tender/po-control?deal=<DEAL_ID>`
   yaz (DEAL_ID'yi Administrator'dan al).

**Beklenen:**
- (1) **Kuyruktan evrak listesine giden hiçbir bağlantı yok.** Ekranda evrak
  sütunu, sayacı ya da uyarısı yok — 8 sütunun hiçbiri belge ile ilgili değil.
- (2) Çubukta `can('declarant')` koşullu **tek** bağlantı var: "Customs queue".
  Evrak ekranı yok.
- (3) `/tender/po-control` rotası **yalnız modül** ile korunuyor; menüde
  `can('sourcing')` ile gizli ama **URL elle yazılırsa açılır**. Sayfa açılınca
  `tender_workspace` ve `po_control_board` çağrılır; ikisi de `_deal_scope` ile
  **CRM Deal read** izni ister.
  - CRM Deal read **varsa**: sayfa açılır, içinde `TenderIntake` (evrak kontrol
    listesi) ve `TenderDocumentChain` (belge zinciri) görünür.
  - CRM Deal read **yoksa**: "Not permitted" toast'ı, sayfa boş kalır.

**Kırık belirtisi:** Deklarantın evrak listesine ulaşmasının belgelenmiş bir
yolu yok; ulaşabildiği hâlde bunu ancak URL'yi elle yazarak yapıyor.
**Kanıt:** `DeclarantQueue.vue:67-72` (8 sütun, belge yok);
`TenderNav.vue:56-58` (deklarantın tek bağlantısı), `50-55` (po-control
`can('sourcing')` ile gizli); `router.js:271` (rota yalnız `module: "tender"`);
`PoControlBoard.vue:32` (deal sorgu parametresinden), `85-86` (çağrılar),
`318` (`TenderIntake`), `453` (`TenderDocumentChain`);
`tender.py:977-986` (`_deal_scope`).

---

### UAT-622 · Evrak kontrol listesinde fatura / packing list / menşe / sözleşme var mı

**Ön koşul:** CRM Deal read izni olan bir kullanıcı (yoksa Administrator ile
yapıp deklarantın göremediğini not et).
**URL:** `https://mikas.erpstable.com/stabler/#/tender/po-control?deal=<DEAL_ID>`
→ "Tender intake" bölümü.

**Adımlar:**
1. Evrak bölümünü aç.
2. "Standart set ekle" düğmesine bas (`seedDocs`).
3. Gelen etiketleri dört gümrük belgesiyle karşılaştır: fatura, packing list,
   menşe şahadetnamesi, sözleşme.

**Beklenen — standart set tam olarak şu altı etiket:**

```js
const STD_DOCS = ["Shartnoma", "Protokol", "Muvofiqlik sertifikati", "ГТД", "Qabul dalolatnomasi", "Hisob-faktura"];
```
— `TenderIntake.vue:91`

| Beklenen gümrük evrağı | Standart sette var mı |
|---|---|
| Sözleşme | **VAR** — `Shartnoma` |
| Fatura (invoice) | **VAR** — `Hisob-faktura` |
| Beyanname (ГТД) | **VAR** — `ГТД` (belgenin kendisi, bir onay kutusu olarak) |
| Uygunluk sertifikası | **VAR** — `Muvofiqlik sertifikati` |
| **Packing list** | **YOK** |
| **Menşe şahadetnamesi** | **YOK** |
| Konşimento / CMR / TIR | **YOK** |

- Liste serbest metin: her satır `{label, required, done, date}`. Eksik iki
  belgeyi elle eklemek mümkün, ama **standart** değil ve her ihalede yeniden
  yazılması gerekir.
- Liste **anlaşma (CRM Deal) düzeyinde**, PO düzeyinde değil. Bir ihalede üç
  ayrı sevkiyat / üç ayrı beyanname varsa üçünün evrağı **tek** listede karışır.

**Kırık belirtisi:** Beyannameci packing list ve menşe belgesini sistemde
takip edemez.
**Kanıt:** `TenderIntake.vue:91-95` (`STD_DOCS`, `seedDocs`), `257` (boş metin);
`tender.py:1414-1425` (`documents` normalizasyonu: `label/required/done/date`),
`1478-1486` (`_docs_summary`).

---

### UAT-623 · TenderDocumentChain gerçekte neyi izliyor

**Ön koşul:** UAT-621 (3) açılabilmiş.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/po-control?deal=<DEAL_ID>`
→ belge zinciri bölümü.

**Adımlar:**
1. İki sütunlu zincir kutusunu bul.
2. Her sütunun üç grubunu oku.

**Beklenen:**
- Sol: **"Purchase execution"** → `PO` · `Receipt` · `Invoice`.
- Sağ: **"Sales execution"** → `Sales order` · `Delivery` · `Invoice`.
- Her satırda: belge no (monospace) · tarih · tutar. Boş grupta
  **"No linked documents"**.
- **Bu zincir MUHASEBE belgelerini izliyor** — satınalma siparişi, mal kabul,
  fatura. Gümrük evrağını (fatura nüshası, packing list, menşe, beyanname)
  **izlemiyor**; bileşende `customs`, `tnved`, `document`, `checklist` gibi bir
  kavram hiç yok.
- Eksik evrak burada **kırmızı yanmaz** — bileşende hiçbir kırmızı/uyarı sınıfı
  yok; eksiklik yalnız gri "No linked documents" yazısıyla belirtilir.

**Kırık belirtisi:** "Belge zinciri" adı beyannameciyi yanıltıyor; aradığı
evrak burada değil.
**Kanıt:** `TenderDocumentChain.vue:18-21` (iki taraf, üç grup),
`34-42` (satırlar + "No linked documents"), dosyanın tamamında renk/uyarı
sınıfı yok.

---

### UAT-624 · Eksik evrak NEREDE kırmızı yanıyor

**Ön koşul:** Bir CRM Deal'de `go_no_go = "go"` ve en az bir `required=1,
done=0` belge var.
**URL:** (a) `.../stabler#/tender/customs` (b) `.../stabler#/tender/desk?view=declarant`
(c) `.../stabler#/tender/crm`

**Adımlar:** Üç ekranı da aç, eksik evrak uyarısı ara.

**Beklenen:**
- (a) **Gümrük kuyruğunda uyarı YOK** — ekranda evrak kavramı yok.
- (b) **Masada uyarı YOK** — `_desk_rules.build_plan`'da `documents` diye bir
  kural yok; `_intake_attention` bir `{"kind": "documents", "missing": [...],
  "severity": "warn"}` kalemi üretiyor ama bu **`tender_dashboard`'ın
  `attention` listesine** gidiyor, masaya değil.
- (c) Tender CRM kartlarında bir **belge ilerleme yüzdesi** var, ama farklı bir
  şemadan okuyor:
  ```python
  doc_progress = round((len([d for d in docs if d.get("status") == "ready"]) / max(1, len(docs))) * 100) if docs else 50
  ```
  Oysa `_clean_intake` belgelere **`status` alanı hiç yazmıyor**; yazdığı alan
  `done`. Sonuç: intake ekranından kaydedilmiş bir evrak listesinde
  `doc_progress` **her zaman 0** çıkar (belge varsa) ya da **50** (belge yoksa).

**Kırık belirtisi (asıl bulgu):** Eksik evrak beyannamecinin hiçbir ekranında
kırmızı yanmıyor. Uyarı yalnız yönetici gösterge panelinin `attention`
listesinde, `warn` şiddetiyle var.
**Kanıt:** `tender.py:2597-2599` (`_intake_attention` → `documents` kalemi),
`2955-2965` (`attention` yalnız `tender_dashboard` çıktısında);
`_desk_rules.py:42-247` (belge kuralı yok);
`tender.py:2387-2388` (`d.get("status") == "ready"`) vs `1415-1425`
(`done` yazılıyor, `status` yazılmıyor) — şema uyuşmazlığı.

---

## 4. Beyanname durumu nerede tutuluyor

### UAT-631 · Tender tarafında beyanname durumu alanı VAR MI

**Ön koşul:** Administrator (alan aramak için).
**URL:** `https://mikas.erpstable.com/stabler/#/tender/customs`

**Adımlar:**
1. `/app/purchase-order` doctype alanlarında `custom_customs_*`,
   `custom_declaration_*` benzeri bir alan ara.
2. Deklarant kuyruğu yanıtındaki `status` alanının veritabanında karşılığını ara.

**Beklenen — tender modülünde beyanname durumu için kalıcı alan YOK:**

| Aranan | Bulunan | Kanıt |
|---|---|---|
| Beyanname durumu alanı (PO) | **Yok.** `declarant_queue`'nun döndürdüğü `status` her istekte yeniden **hesaplanıyor**, hiçbir yere yazılmıyor | `tender.py:2035` |
| Gümrük çıkış (clearance) alanı | **Yok** — kaynak açıkça yazıyor: *"No native PO-level customs clearance field exists in this install"* | `tender.py:2810-2813` |
| Saklanan tek gümrük verisi | `Purchase Order.custom_landed_charges` içindeki JSON dizisi: `{type:"customs", label, amount, actual, tnved, cif, duty_pct, excise_pct, vat_pct, vat_recoverable, actual_voucher_type, actual_voucher}` | `tender.py:256-302`, `240` (alan adı) |
| "hazırlanıyor / verildi / onaylandı / itiraz" | Tender modülünde **hiçbiri yok** | — |

- `pending / in_progress / cleared` üçlüsü bu dört durumun karşılığı **değil**
  (bkz. UAT-604): sırasıyla "masraf planı yok", "masraf planı var", "mal depoya
  girdi" demek.
- **İtiraz / redde karşı başvuru için sistemde hiçbir kavram yok.**

**Ayrı bir modülde gerçek bir beyanname doctype'ı VAR ama tender'a bağlı değil:**
`Customs Declaration` — durumları `Draft` / `Submitted` / `Under Review` /
`Approved` / `Rejected`; ekranları `/imports/customs`, `/imports/customs/new`,
`/imports/customs/:name` ve **`module: "imports"`** ile korunuyor.
Tender kodunda bu doctype'a **hiçbir referans yok**; deklarant kuyruğu onu ne
okuyor ne yazıyor.

**Kırık belirtisi:** Beyannameci "beyanname verildi" bilgisini sisteme
yazamıyor; ertesi gün açtığında ekran yine "In progress" der.
**Kanıt:** `tender.py:2035` (türetilen `status`), `2810-2816` (alan yokluğu
itirafı), `240, 256-302` (`custom_landed_charges` şeması);
`composables/status.js:193-199` (`Customs Declaration` durum sözlüğü);
`router.js:229-231` (imports rotaları, `module: "imports"`);
`tender.py` içinde `Customs Declaration` araması → 0 sonuç.

---

### UAT-632 · İmports modülündeki beyanname ekranına erişim

**Ön koşul:** Saf deklarant girişli.
**URL:** `https://mikas.erpstable.com/stabler/#/imports/customs`

**Adımlar:** URL'yi elle yaz, Enter.

**Beklenen:**
- `imports` modülü kapalıysa → muhafız `landingPath`'e atar (UAT-600b'deki
  `/error` riski).
- `imports` açıksa → gerçek Beyanname listesi açılır; ama bu ekran tender
  ihaleleriyle bağlantısız, `custom_crm_deal` bağı yok.
**Kırık belirtisi:** Rolün adı "gümrük beyannamecisi" ama beyanname ekranı
başka bir modülde ve tender rol haritasında hiç geçmiyor.
**Kanıt:** `router.js:229-231`, `612-635`; `_TENDER_VIEW_ROLES` (`tender.py:1725-1730`)
içinde `imports` ile ilgili hiçbir şey yok.

---

## 5. Gümrük vergisi / harç hesabı

### UAT-641 · Hesap makinesi VAR — ama deklarantın menüsünde değil

**Ön koşul:** CRM Deal read + Purchase Order write izni olan kullanıcı.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/po-control?deal=<DEAL_ID>`

**Adımlar:**
1. Bir PO kartında landed-charge düzenleyicisini aç.
2. Satır tipini `customs` seç.
3. ТН ВЭД koduna gerçek bir kod yaz, alanı terk et (`lookupHsRate` tetiklenir).
4. `CIF` (gümrük kıymeti) gir.
5. "Hesapla"ya bas (`applyCustoms`).
6. Kaydet.

**Beklenen — formüller:**
```
duty   = CIF × duty_pct / 100
excise = CIF × excise_pct / 100
vat    = (CIF + duty + excise) × vat_pct / 100
capitalized = duty + excise + (KDV indirilebilir DEĞİLSE vat)
```
- (3) `hs_rate_lookup` `HS Duty Rate` tablosuna bakar, en güncel
  `effective_from` satırını alır; bulursa `duty_pct` / `vat_pct` / `excise_pct`
  otomatik dolar, yanında "from HS table · <tarih>" yazar.
- Kod tabloda yoksa ya da **`HS Duty Rate` doctype'ı kurulu değilse**:
  `{found: false, ...hepsi 0}` döner, ekranda "not in HS table — enter manually".
- (5) `amount` alanına yalnız **capitalized** yazılır (yuvarlanmış). KDV
  indirilebilirse maliyete **girmez**, ayrı bir "recoverable VAT" toplamında
  gösterilir.
- Sunucu tarafı aynı hesabı `po_landed_charges` içinde tekrar yapar ve
  `recoverable_vat` döndürür.

**Ama:**
- Bu düzenleyici **`/tender/po-control`** ekranında; `TenderNav`'da bu bağlantı
  `v-if="can('sourcing')"` ile korunuyor → **deklarant menüde göremez**.
- Deklarantın kendi ekranında yalnız **tek bir sayı** var: `Customs` sütunundaki
  `customs_total` (tüm `customs` satırlarının `amount` toplamı, salt okunur).
  Vergi kırılımı (duty / excise / KDV / indirilebilir KDV) kuyrukta **hiç yok**.
- Harç / ordino / ambar / terminal ücreti için ayrı bir kavram yok; yalnız
  serbest metinli `label` alanı ve `_CHARGE_TYPES` listesindeki genel tipler
  (`broker`, `storage`, `loading`, `bank`, `other`).

**Kırık belirtisi:** Beyannameci vergiyi hesaplayan ekranı menüsünde bulamıyor;
bulsa bile o ekranın yazma yolu `Purchase Order` **write** izni istiyor.
**Kanıt:** `PoControlBoard.vue:188-205` (`customsCalc`, `applyCustoms`),
`228-245` (`lookupHsRate`), `146-153` (`editorRecoverableVat`), `265` (kaydet);
`tender.py:363-397` (`hs_rate_lookup`, `378` doctype yokluk kontrolü),
`400-433` (`po_landed_charges`, `412-420` `recoverable_vat`),
`435-460` (`save_po_landed_charges` → `_po_scope(po, write=True)`),
`348-360` (`_po_scope`), `241-253` (`_CHARGE_TYPES`);
`TenderNav.vue:53-55` (po-control `can('sourcing')`).

---

### UAT-642 · Deklarant landed-charge yazabiliyor mu

**Ön koşul:** Saf deklarant. `Purchase Order` write izninin durumu not edilmiş.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/po-control?deal=<DEAL_ID>`

**Adımlar:**
1. Sayfayı aç (URL elle).
2. Düzenleyiciyi aç, bir `customs` satırı ekle, kaydet.

**Beklenen:**
- Yazma izni `_po_scope(po, write=True)` → `frappe.has_permission("Purchase Order",
  "write", doc=po)` ile belirlenir. **Rol penceresi (`declarant`) burada hiç
  sorulmuyor** — kapı tamamen Frappe PO iznine bağlı.
- `Stabler Declarant` rolüne PO write verilmişse **kaydeder** (onaylanmış PO'da
  bile — alan `allow_on_submit` örtüsü, `update_modified=False` ile yazılıyor).
- Verilmemişse "Not permitted".

**Kırık belirtisi:** İki uç da sorunlu: yazabiliyorsa deklarant satınalma
belgesine dokunuyor; yazamıyorsa gümrük vergisini sisteme girecek kimse yok
(sourcing kullanıcısı girmek zorunda).
**Kanıt:** `tender.py:435-442` (`save_po_landed_charges` → `_po_scope(write=True)`),
`348-360`, `446-452` (`db.set_value`, `update_modified=False`).

---

## 6. Malı lojistiğe devir

### UAT-651 · Devir mekanizması var mı

**Ön koşul:** Kuyrukta `In progress` durumda bir PO var.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/customs`

**Adımlar:**
1. Satırda "devret", "tamamla", "lojistiğe gönder" gibi bir düğme ara.
2. Satıra sağ tıkla / uzun bas — bağlam menüsü ara.
3. Aynı PO'nun `/tender/logistics` ekranında **şu anda** görünüp görünmediğini
   kontrol et (Administrator ya da `Stabler Logist` bir kullanıcıyla).

**Beklenen:**
- (1-2) **Hiçbir eylem düğmesi yok.** Ekranın tamamı salt okunur; şablonda
  `<button>` yalnız "Clear filters" için var.
- (3) **PO zaten lojistik ekranında.** `logist_board` da `_po_rows_for_views`
  ile **aynı** PO kümesini okuyor; tek fark hangi masraf tiplerini topladığı
  (`transport` + `loading`) ve durumu neye göre türettiği (`received` /
  `late` / `in_transit`).

**Sonuç:** Devir diye bir şey **yok**. İki rol aynı kayıtlara aynı anda
bakıyor; "beyannameci işini bitirdi" bilgisi hiçbir yerde tutulmuyor,
dolayısıyla lojistikçiye bir sinyal de gitmiyor. Beyannamecinin işinin bittiğini
sistemde gösteren tek dolaylı işaret `per_received >= 100`, onu da ambar
üretiyor.

**Kırık belirtisi:** Lojistikçi malın gümrükten çıkıp çıkmadığını ekrandan
öğrenemez; telefonla sorar.
**Kanıt:** `DeclarantQueue.vue:62-90` (salt okunur şablon, tek düğme `59`);
`tender.py:2020-2060` (`declarant_queue` — yazma yok) ve `2063-2120`
(`logist_board` — **aynı** `_po_rows_for_views(company)` çağrısı, `2068`);
`tender.py:1993-2017` (paylaşılan kaynak, docstring: *"Shared PO fetch for
declarant/logist windows"*).

---

## 7. YETKİ · Deklarant başka URL'leri elle yazarsa

Yönlendirme muhafızı **yalnız modüle** bakıyor; rol penceresine (`view`)
bakmıyor. Dört tender rotasının dördü de `module: "tender"` taşıyor, dolayısıyla
**dördü de tarayıcıda AÇILIR**. Fark, arkadaki uç noktanın ne dediğinde.

| URL | Menüde görünür mü | Sayfa açılır mı | Backend ne der | Sonuç |
|---|---|---|---|---|
| `/tender/flow` | **Hayır** (`can('director')`) | **Evet** | `tender_flow` **view kapısı YOK** | **VERİ GELİR — açık** |
| `/tender/crm` | **Hayır** (`can('director') \|\| can('sourcing')`) | **Evet** | `crm_board` **view kapısı YOK** | **VERİ GELİR — açık** |
| `/tender/portfolio` | **Hayır** (`can('director')`) | Evet (boş) | `tender_director_board` → `_require_tender_view("director")` | Toast: "Not permitted" |
| `/tender/sourcing` | **Menüde HİÇ YOK** (hiçbir rol için bağlantı yok) | **Evet** | `crm.list_deals` → `crm` modülü + CRM Deal read; `purchasing.tender_quotations` (paket dışı) | Modül iznine bağlı |
| `/tender/board` | **Evet** (koşulsuz) | Evet | `so_board` yalnız tender modülü ister | Açılır |
| `/tender/po-control` | Hayır (`can('sourcing')`) | **Evet** | `_deal_scope` → CRM Deal read | İzne bağlı (bkz. UAT-621) |
| `/tender/my-tenders` | Hayır (`can('sourcing')`) | Evet (boş) | `sourcing_my_tenders` → `_require_tender_view("sourcing")` | Toast: "Not permitted" |
| `/tender/logistics` | Hayır (`can('logist')`) | Evet (boş) | `logist_board` → `_require_tender_view("logist")` | Toast: "Not permitted" |

### UAT-661 · `/tender/flow` — süreç akışı (YÜKSEK)

**Ön koşul:** Saf deklarant girişli.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/flow`

**Adımlar:**
1. `TenderNav` çubuğunda "Process flow" bağlantısını ara → **olmamalı**.
2. URL'yi elle yaz, Enter.
3. Ağ sekmesinde `stabler.api.tender.tender_flow` yanıtına bak.

**Beklenen (mevcut kaynağa göre — GÜVENLİK BULGUSU):**
- Menüde bağlantı yok.
- **Sayfa açılır ve DOLU gelir.** `tender_flow` gövdesindeki kapılar yalnız:
  ```python
  _require_tender(company)
  _assert_company_scope(company)
  _require_company(company)
  ```
  `_require_tender_view(...)` **çağrılmıyor**. Deklarant, şirketin tüm ihale
  hattını, adım başına bekleme sürelerini ve SLA aşımlarını görür.

**Kırık belirtisi (beklenen doğru davranış):** `_require_tender_view("director",
company)` olmalıydı. Bu satır eklenene kadar menü gizlemesi yalnız kozmetik.
**Kanıt:** `tender.py:3003-3017` (kapı listesi, view kapısı yok);
`TenderNav.vue:40-42` (`can('director')` ile gizleme);
`router.js:267` (rota yalnız `module: "tender"`), `612-635` (muhafız yalnız modüle bakıyor).

### UAT-662 · `/tender/crm` — Tender CRM panosu (YÜKSEK)

**Ön koşul:** Saf deklarant girişli.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/crm`

**Adımlar:**
1. URL'yi elle yaz.
2. Kanban kulvarlarını say, kartlardaki tutarlara bak.
3. Bir kartı başka bir kulvara **sürüklemeyi** dene.

**Beklenen (GÜVENLİK BULGUSU):**
- **Pano açılır ve dolu gelir** — `crm_board` da view kapısı taşımıyor
  (`_require_tender, _assert_company_scope, _require_company`). Yedi kulvar,
  sözleşme tutarları, teklif sayaçları görünür.
- (3) Sürükleme `move_deal_stage` çağırır; o da rol penceresine bakmaz, yalnız
  `CRM Deal` **write** iznine bakar. Deklaranta CRM Deal write verilmişse
  **ihale aşamasını değiştirebilir**.

**Kırık belirtisi:** Beyannameci ihale fiyat/tutar bilgisini ve aşama kontrolünü
görüyor.
**Kanıt:** `tender.py:2289-2307` (`crm_board` kapıları), `2451-2460`
(`move_deal_stage` kapıları); `TenderCrm.vue:43` (çağrı), `175` (aşama taşıma);
`TenderNav.vue:47-49`.

### UAT-663 · `/tender/portfolio` — Direktör panosu

**Ön koşul:** Saf deklarant girişli.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/portfolio`

**Adımlar:** URL'yi elle yaz, ekranı ve ağ sekmesini izle.

**Beklenen:**
- Menüde bağlantı yok. **Sayfa iskeleti açılır** (bileşen monte olur), ama
  `tender_director_board` **PermissionError** atar → kırmızı toast
  ("Not permitted"), tablo boş.
- Sayfa ayrıca `tender_managers` çağırır; o da `_require_tender_view("director")`
  ile reddedilir — ama `catch { }` ile **sessizce yutulur**, ikinci bir uyarı
  çıkmaz.
- **Dikkat:** Bu ekranda `TenderFunnel` bileşeni de var; `tender_funnel` uç
  noktasının kapılarını ayrıca doğrula — huni verisi gelirse şirket geneli
  sızıntısı vardır.

**Kırık belirtisi:** Tabloda satır görünürse yetkilendirme kırıktır.
**Kanıt:** `tender.py:1984-1990` (`_require_tender_view("director")`),
`1762-1764` (`tender_managers` aynı kapı);
`DirectorBoard.vue:40-43` (toast), `50-52` (sessiz `catch`).

### UAT-664 · `/tender/sourcing` — Teklif karşılaştırma

**Ön koşul:** Saf deklarant girişli.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/sourcing`

**Adımlar:**
1. `TenderNav`'da bu bağlantıyı ara → **hiçbir rolde yok**.
2. URL'yi elle yaz.
3. Anlaşma arama kutusuna bir şey yaz.

**Beklenen:**
- Bağlantı menüde hiç yok (çubuğun 11 bağlantısının hiçbiri `/tender/sourcing`
  değil) — ama rota var ve `module: "tender"` ile korunuyor, yani **açılır**.
- Sayfa boş durumla açılır: "Pick a tender deal to compare quotations."
- (3) Arama `stabler.api.crm.list_deals` çağırır → `_require_crm()` **`crm`
  modülü** ister + `CRM Deal` read ister.
  - `crm` modülü kapalıysa: "Not permitted", arama sonuç vermez → ekran
    kullanılamaz.
  - Açıksa: anlaşma listesi gelir, seçince `stabler.api.purchasing.tender_quotations`
    çağrılır. **Bu fonksiyonun gövdesi incelenen pakette yok** — kapısı canlı
    sitede doğrulanmalı.

**Kırık belirtisi:** Tedarikçi teklif fiyatları deklaranta açılıyorsa raporla.
**Kanıt:** `router.js:270`; `TenderNav.vue:28-62` (bağlantı listesinde yok);
`SourcingCompare.vue:27, 44, 152`; `crm.py:281-285` (`_require_crm` + CRM Deal read),
`crm.py:19-21`.

---

## 8. `.stbl-ds` tasarım katmanı

### UAT-671 · DeclarantQueue tasarım katmanına taşınmış mı

**Ön koşul:** Saf deklarant girişli.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/customs`

**Adımlar:**
1. Geliştirici araçlarını aç, sayfanın kök `<div>`'ini incele.
2. `stbl-ds` sınıfını ara.
3. Aynı işlemi `/tender/desk` ve `/tender/portfolio` için tekrarla.

**Beklenen:**
- **Kuyruğun kök sarmalayıcısı `stbl-ds` TAŞIMIYOR:**
  ```html
  <div class="container-xl py-3">
  ```
  — `DeclarantQueue.vue:63`
- Sayfadaki `stbl-ds` **yalnız `TenderNav`'ın kendi kökünde** var
  (`<nav class="stbl-ds tender-modnav">`). Yani ekranda **üst çubuk yeni
  tasarımda, içerik eski Tabler dilinde** — `card`, `table card-table`,
  `badge bg-green-lt` gibi ham Tabler sınıfları.
- Karşılaştırma: `/tender/desk` → `<div class="operations-desk-page stbl-ds">`,
  `/tender/portfolio` → `<div class="director-board-page stbl-ds">`,
  `/tender/crm` → `stbl-ds`, `/tender/flow` → `stbl-ds`.

**Taşınmış / taşınmamış tender ekranları:**

| Ekran | `.stbl-ds` |
|---|---|
| OperationsDesk | **VAR** (`:5`) |
| DirectorBoard | **VAR** (`:132`) |
| TenderCrm | **VAR** (`:248`) |
| TenderFlow | **VAR** (`:119`) |
| TenderNav | **VAR** (`:29`) |
| **DeclarantQueue** | **YOK** |
| LogistBoard | **YOK** |
| PoControlBoard | **YOK** |
| MyTenders | **YOK** |
| TenderIntake / TenderDocumentChain | **YOK** |

**Kırık belirtisi:** Deklarant çubuktan içeriğe geçerken iki farklı görsel dil
görür (yazı tipi ölçeği, kart kenarları, rozet biçimi). Beyannamecinin **ana
ekranı**, taşınmamış dört ekrandan biri.
**Kanıt:** `DeclarantQueue.vue:63` (kök sınıf), `65` (TenderNav);
`TenderNav.vue:29`; `OperationsDesk.vue:2-5` (katmanı açan sınıfın açıklaması);
`DirectorBoard.vue:130-132`; `TenderCrm.vue:248`; `TenderFlow.vue:119`.

---

## 9. Demo veri bu rolü test edebiliyor mu

### **HAYIR.** `seed_tender_demo.py` gümrük tarafına TEK BİR KAYIT üretmiyor.

### UAT-681 · Demo sonrası kuyruk boş (kanıt senaryosu)

**Ön koşul:** `seed_tender_demo.seed(company="Mikas")` koşulmuş, saf deklarant girişli.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/customs`

**Adımlar:**
1. Seed komutunun konsol çıktısını oku (son satır).
2. `/tender/customs` sayfasını aç.
3. `/tender/desk?view=declarant` sayfasını aç.

**Beklenen:**
- (1) Seed'in kendi çıktısı gümrüğü zaten dışarıda bırakıyor:
  ```
  Visible on: /tender/desk · /tender/crm · /tender/portfolio · /tender/flow
  ```
  — `/tender/customs` ve `/tender/logistics` bu listede **yok**.
- (2) Kuyruk **0 satır**, boş durum: "No purchase orders match these filters."
- (3) Masa dolu görünür ama içindeki hiçbir kalem gümrükle ilgili değil
  (UAT-612).

**Neden:** Seed'in ürettiği **tüm** doctype'lar:

| Doctype | Adet | Kanıt |
|---|---|---|
| `CRM Deal` | 13 | `seed_tender_demo.py:51-71` (`DEMO_LOTS`), `179` |
| `CRM Organization` | ≤5 | `:116` |
| `CRM Stage Event` | değişken (aşama yolu kadar) | `:229` |

Dosyanın tamamında `frappe.new_doc` yalnız bu üç satırda geçiyor. **Purchase
Order yok** → `_po_rows_for_views` boş liste döner → `declarant_queue.rows = []`.

**Kanıt:** `seed_tender_demo.py:116, 179, 229` (üç `new_doc`), `208` (görünürlük
listesi); `tender.py:1995-2016` (PO sorgusu), `2025-2027` (boş liste → boş çıktı).

---

## Demo'nun üretmediği kayıtlar

Deklarant kuyruğunun **dolu ve anlamlı** görünmesi için seed'e eklenmesi gereken
minimum küme. Adetler, ekranın gösterdiği her ayrımın en az bir örneğini
üretecek şekilde seçildi (mevcut seed'in tender tarafında yaptığı gibi).

### A. Ön koşul kayıtları (PO yaratılabilsin diye)

| Kayıt tipi | Adet | Neden bu adet |
|---|---|---|
| `Supplier` | **3** | Vendor sütununda ayırt edilebilir isim; ayrıca `landed_charges.supplier` (deklarant/broker) alanı için |
| `Item` (satınalma kalemi) | **2** | PO satırı zorunlu; iki farklı ТН ВЭД kodu iki kaleme bağlanabilsin |
| `Warehouse` | 1 (varsa mevcut) | PO satırı için |
| `HS Duty Rate` | **3** | `hs_rate_lookup` `found: true` dönebilsin (`tender.py:378-388`); aksi hâlde her kodda "not in HS table" yazar |

### B. Deklarant kuyruğunu dolduran kayıtlar

Her PO **zorunlu olarak**: `company = Mikas`, `custom_crm_deal = <demo deal>`,
`docstatus = 1`, `schedule_date` dolu, `custom_landed_charges` JSON dolu.

| # | Adet | Kurulum | Ekranda ürettiği ayrım |
|---|---|---|---|
| 1 | **2 PO** | landed charge **yok** | `Status = Pending` (sarı), `Customs = —`, `HS code = —` |
| 2 | **2 PO** | `customs` satırı: `amount > 0`, `tnved` dolu, `cif/duty_pct/vat_pct` dolu | `Status = In progress` (mavi), tutar ve kod dolu |
| 3 | **2 PO** | `per_received = 100` (submit edilmiş **Purchase Receipt** ile) | `Status = Cleared` (yeşil) |
| 4 | **1 PO** | `schedule_date = bugün − 5` | `Days left` = "5 days late", **kırmızı** |
| 5 | **1 PO** | `schedule_date = bugün + 3` | `Days left` = "3 days left", **sarı** |
| 6 | **1 PO** | `schedule_date = bugün + 45` | normal (renksiz) |
| 7 | **1 PO** | `schedule_date` **BOŞ** | `PO ETA = —`, `Days left = —`, **listenin en başında** (NULL, ASC) — sıralama kusurunu görünür kılar |
| 8 | **1 PO** | `docstatus = 0` (taslak) | Taslağın kuyrukta göründüğünü kanıtlar (UAT-602) |
| 9 | **1 PO** | `customs` satırında `amount = 0`, `tnved` **dolu** | `Status = Pending` ama kod dolu — UAT-604 (4) kusurunu görünür kılar |
| 10 | **1 PO** | `transport` satırında `tnved` dolu, `customs` satırı yok | Yanlış tipten kod okunduğunu kanıtlar (UAT-605) |
| 11 | **1 PO** | iki `customs` satırı, iki **farklı** `tnved` | Yalnız ilkinin gösterildiğini kanıtlar (UAT-605) |
| 12 | **1 PO** | `custom_crm_deal` **BOŞ** | Kuyrukta **görünmemeli** — negatif kontrol (UAT-602) |

**Toplam: 15 Purchase Order** (bazıları birden çok ayrımı taşıyabilir; 4-7
numaralı ETA varyasyonları 1-3'teki PO'lara dağıtılırsa **8 PO** yeterli olur),
**2 Purchase Receipt** (3 numara için), **3 Supplier**, **2 Item**,
**3 HS Duty Rate**.

### C. Evrak / masa tarafı için ek

| Kayıt | Adet | Neden |
|---|---|---|
| `custom_tender_intake.documents` — **`_clean_intake` şemasıyla** (`label/required/done/date`) | 13 deal'in en az 4'ünde | Mevcut seed `{name, status}` yazıyor (`:134-139`); `_clean_intake` (`tender.py:1415-1425`) yalnız `label` okur, gerisini **siler**. Bu hâliyle evrak listesi kayıtta bir kere düzenlenince **boşalır**. |
| Eksik evrak örneği (`required=1, done=0`) | ≥2 deal | `_intake_attention`'ın `documents` kalemini üretebilmesi için (`tender.py:2597-2599`) |
| `Customs Declaration` (imports modülü) | **0** üretiliyor | Tender ile bağı olmadığı için kuyruğu etkilemez; ama §4'ün canlı testi için en az 1 kayıt gerekir |

### D. Seed dosyasına eklenmesi gereken güvenlik/temizlik notu

Yeni kayıtlar da ` [DEMO]` işaretini taşımalı (Supplier adı, Item adı, PO
`custom_remarks` vb.) ve `unseed()` bunları da silmeli — bugünkü `unseed`
yalnız `CRM Deal`, `CRM Stage Event` ve `CRM Organization` siliyor
(`seed_tender_demo.py:251-278`).

---

## Beyannamecinin yapamadıkları

Her madde kanıtla; hiçbiri "yapılmalı" önerisi değil, **bugünkü kaynakta yok** tespiti.

1. **Beyanname durumunu (hazırlanıyor / verildi / onaylandı / itiraz) sisteme
   yazamıyor.** Tender tarafında böyle bir alan yok; `status` her istekte
   `per_received` ve masraf planından **hesaplanıyor**.
   *Kanıt:* `tender.py:2032-2035`, `2810-2813` (*"No native PO-level customs
   clearance field exists in this install"*).

2. **Bir malı "gümrükten çıktı" işaretleyemiyor.** `cleared` ambarın mal kabulüne
   bağlı (`per_received >= 100`).
   *Kanıt:* `tender.py:2032`.

3. **İtiraz / redde karşı başvuru kaydı tutamıyor.** Sistemde bu kavram yok;
   imports modülündeki `Customs Declaration` bile yalnız `Rejected` durumuna
   sahip, itiraz sürecine değil.
   *Kanıt:* `composables/status.js:193-199`.

4. **Kendi ekranından hiçbir şey yazamıyor.** `/tender/customs` salt okunur;
   tek düğme "Clear filters".
   *Kanıt:* `DeclarantQueue.vue:2-3` (docstring: "Read-only"), `62-90`.

5. **Gümrük vergisi hesaplayacağı ekranı menüsünde bulamıyor.** Hesap makinesi
   `/tender/po-control` içinde, o bağlantı `can('sourcing')` ile gizli.
   *Kanıt:* `PoControlBoard.vue:188-205`; `TenderNav.vue:53-55`.

6. **Vergi kırılımını (gümrük vergisi / ÖTV / KDV / indirilebilir KDV) kendi
   kuyruğunda göremiyor** — yalnız tek toplam sayı.
   *Kanıt:* `tender.py:2030` (`customs_total`), `DeclarantQueue.vue:80`.

7. **Evrak kontrol listesine kendi ekranından ulaşamıyor**; ulaşsa bile liste
   PO düzeyinde değil, anlaşma düzeyinde.
   *Kanıt:* `DeclarantQueue.vue:67-72`; `TenderIntake.vue:91`; `tender.py:1414-1425`.

8. **Packing list ve menşe şahadetnamesini standart listede takip edemiyor.**
   *Kanıt:* `TenderIntake.vue:91` (altı etiket, ikisi yok).

9. **Eksik evrağı hiçbir ekranında kırmızı göremiyor.** Uyarı yalnız
   `tender_dashboard.attention` içinde `warn` şiddetiyle var.
   *Kanıt:* `tender.py:2597-2599`; `_desk_rules.py:42-247` (belge kuralı yok).

10. **Malı lojistiğe devredemiyor.** Devir eylemi yok; iki pano aynı PO kümesini
    aynı anda okuyor.
    *Kanıt:* `tender.py:1993-2017` (paylaşılan fetch), `2066-2068`.

11. **Çok kalemli beyanname yapamıyor** — bir PO için yalnız tek ТН ВЭД kodu
    gösteriliyor.
    *Kanıt:* `tender.py:2031`.

12. **İhale dışı bir ithalatı gümrükleyemiyor** — `custom_crm_deal` boş olan PO
    kuyruğa hiç düşmüyor.
    *Kanıt:* `tender.py:2012`.

13. **Masasında kendi işini göremiyor.** `_desk_rules` deklaranta özel tek bir
    kural içermiyor; masa teklif son tarihleri ve fatura ödemeleri gösteriyor.
    *Kanıt:* `_desk_rules.py:42-247`; `tender_desk.py:89-91, 212-219`.

14. **Kuyruğu önceliğe göre sıralayamıyor** — sıralama sabit `schedule_date ASC`,
    sütun başlıkları tıklanamaz, tarihsiz kayıtlar en tepede.
    *Kanıt:* `tender.py:2014`; `DeclarantQueue.vue:68-72`.

15. **Kuyruğu ekrandan filtreleyemiyor** — filtre arayüzü yok, yalnız URL
    parametresi.
    *Kanıt:* `DeclarantQueue.vue:64` ("Clear filters" yalnız filtre etkinken).

16. **2000'den fazla PO'da ne olduğunu bilemiyor** — sayfalama ve uyarı yok.
    *Kanıt:* `tender.py:2015`.

17. **Hangi ihaleye baktığını lot numarasından ayırt edemiyor** — `Tender`
    sütunu kurum adı gösteriyor (izni varsa), lot no değil.
    *Kanıt:* `tender.py:1850-1855`.

---

## Bulgu özeti (öncelik sırasıyla)

| # | Bulgu | Şiddet | Ana kanıt |
|---|---|---|---|
| **D1** | `/tender/flow` ve `/tender/crm` deklaranta tamamen açık — backend'de view kapısı yok; menü gizlemesi kozmetik | **Yüksek** | `tender.py:3015-3017`, `2305-2307` |
| **D2** | Beyanname durumu için hiçbir alan yok; `pending/in_progress/cleared` üçlüsü gümrük değil, masraf planı + ambar kabulü türevi | **Yüksek** | `tender.py:2032-2035`, `2810-2813` |
| **D3** | Rolün ana ekranı salt okunur; deklarant hiçbir şey yazamıyor, hiçbir şeyi devredemiyor | **Yüksek** | `DeclarantQueue.vue:2-3`, `62-90` |
| **D4** | Demo veri gümrük tarafına 0 kayıt üretiyor → rol hiç test edilemiyor | **Yüksek** | `seed_tender_demo.py:116,179,229`, `208` |
| **D5** | `_desk_rules`'da deklaranta özel kural yok; masa yanlış işi gösteriyor, üstelik tüm şirket faturalarını açıyor | **Orta-Yüksek** | `_desk_rules.py:42-247`, `tender_desk.py:89-91` |
| **D6** | ТН ВЭД kodu tip kontrolü yapmadan ilk satırdan okunuyor; çok kalemli beyanname gösterilemiyor | **Orta-Yüksek** | `tender.py:2031` vs `2030` |
| **D7** | Vergi hesap makinesi deklarantın menüsünde yok (`can('sourcing')` arkasında) | **Orta** | `TenderNav.vue:53-55`, `PoControlBoard.vue:188-205` |
| **D8** | Evrak listesinde packing list ve menşe şahadetnamesi yok; liste PO değil deal düzeyinde | **Orta** | `TenderIntake.vue:91`, `tender.py:1414-1425` |
| **D9** | Evrak şema uyuşmazlığı: `crm_board` `d.status` okuyor, `_clean_intake` `done` yazıyor → ilerleme her zaman 0 | **Orta** | `tender.py:2387-2388` vs `1415-1425` |
| **D10** | Sıralama sabit `schedule_date ASC`; tarihsiz kayıtlar en tepede, gecikmiş satır ortada kalıyor | **Orta** | `tender.py:2014`, `DeclarantQueue.vue:82` |
| **D11** | Satıra tıklama `/purchasing/orders/...`'a gidiyor; `purchasing` modülü kapalıysa kullanıcı `landingPath`'e savruluyor (`tender` LANDING_ORDER'da yok → `/error`) | **Orta** | `DeclarantQueue.vue:58`, `router.js:519-544, 612-635` |
| **D12** | Taslak PO'lar (docstatus=0) beyanname kuyruğunda görünüyor | **Düşük-Orta** | `tender.py:2012` |
| **D13** | `.stbl-ds` DeclarantQueue'da YOK — çubuk yeni, içerik eski tasarım dilinde | **Düşük-Orta** | `DeclarantQueue.vue:63` vs `TenderNav.vue:29` |
| **D14** | Boş durum metni "…match these filters" — hiç filtre yokken de aynı metin | **Düşük** | `DeclarantQueue.vue:87` |
| **D15** | `Tender` sütunu kurum adı gösteriyor, lot no değil; aynı kurumun lotları ayırt edilemiyor | **Düşük** | `tender.py:1850-1855` |
| **D16** | 2000 satır limiti sessiz; sayfalama yok | **Düşük** | `tender.py:2015` |
| **D17** | `TenderExecutionFlow.vue` pakette **hiçbir dosya tarafından import edilmiyor** | **Düşük** | Paket genelinde 0 referans |

---

## Doğrulanamayan noktalar (canlı sitede koşulmalı)

Bu maddelerin gövdesi incelenen pakette **yok**; yalnız çağrıldıkları kanıtlandı.

1. **`_can_access_module` / modül haritası** → `stabler/api/organization.py` (paket dışı).
   `Stabler Declarant` rolünün `tender`, `purchasing`, `crm`, `imports`, `dashboard`
   modüllerinden hangilerine eriştiği buradan belli oluyor. UAT-600b, UAT-607,
   UAT-632, UAT-664 sonuçlarının **tamamı** bu haritaya bağlı.

2. **`_assert_company_scope`** → `stabler/api/approvals.py` (paket dışı).
   Başka bir şirketin `company` parametresiyle `declarant_queue` çağrılması
   testi fiilen koşulmalı.

3. **`stabler.api.purchasing.tender_quotations`** → `stabler/api/purchasing.py` (paket dışı).
   `/tender/sourcing`'in deklaranta ne sızdırdığı buradan belli oluyor (UAT-664).

4. **`HS Duty Rate` doctype'ı kurulu mu** — `hs_rate_lookup` doctype yoksa
   sessizce `found: false` dönüyor (`tender.py:378`). Canlı sitede tabloda kaç
   satır olduğu ve `effective_from` tarihleri kontrol edilmeli (UAT-641).

5. **`Customs Declaration` doctype'ı ve imports modülü ekranları**
   (`pages/imports/CustomsDeclarations.vue`, `CustomsDeclarationForm.vue`) pakette
   yok — yalnız rota kaydı ve durum sözlüğü görülebiliyor. §4'ün tamamı canlı
   sitede doğrulanmalı.

6. **`useAutoRefresh.js` / `useEscapeBack.js`** composable'ları pakette yok;
   60 sn periyodu `STATE.md:61`'den okundu, ölçülmeli (UAT-608).

7. **Dashboard ekranı** (`Dashboard.vue`) pakette yok. `tender_dashboard`
   çıktısındaki `my_work.customs_workload_open` (yalnız `declarant` görünümünde
   dolduruluyor — `tender.py:2979`) ve `attention` listesi orada gösteriliyorsa,
   deklarantın eksik evrak uyarısını **görebildiği tek yer** orasıdır; canlı
   sitede kontrol edilmeli.
