# UAT 02 — Tender iş akışı · uçtan uca kabul testleri (ihale uzmanı gözüyle)

**Kapsam:** Bir ihale lotunun tam yaşam döngüsü — ilan görüldü → git/gitme →
tedarik → fiyatlandırma → teklif → sonuç → sözleşme → sipariş → gümrük → lojistik
→ teslim → kapanış (plan/fiili) — ve bu döngünün Stabler tender modülünde
gerçekten hangi ekranda, hangi uç noktayla, hangi belgeyle karşılandığı.

**Test sitesi / şirket:** `mikas.erpstable.com` · Company = `Mikas`
**Temel URL biçimi:** `https://mikas.erpstable.com/stabler#/tender/<ekran>`
**Demo veri:**
`bench --site mikas.erpstable.com execute stabler.maintenance.seed_tender_demo.seed`

### Bu belgede kullanılan kısaltmalar

| Kısaltma | Karşılığı |
|---|---|
| Deal | `CRM Deal` — bu modülde bir **lot** demektir |
| SQ | `Supplier Quotation` (tedarikçi teklifi) |
| SO | `Sales Order` (bizim müşteriye sözleşmemiz) |
| PO | `Purchase Order` (tedarikçiye siparişimiz) |
| PR / PInv | `Purchase Receipt` / `Purchase Invoice` |
| DN / SI | `Delivery Note` / `Sales Invoice` |
| ГТД | Gümrük beyannamesi (kodda `customs` tipi landed satırı) |

---

## 0. Ortam, roller ve demo verinin GERÇEK içeriği

### 0.1 Rol → görünüm haritası

`api/tender.py:1725-1730`:

| Görünüm | Rolü açan roller |
|---|---|
| `director` | System Manager · Stabler Admin · Sales Manager · **Stabler Tender Director** |
| `sourcing` | System Manager · Stabler Admin · Sales Manager · **Sales User** |
| `declarant` | System Manager · Stabler Admin · Sales Manager · **Stabler Declarant** |
| `logist` | System Manager · Stabler Admin · Sales Manager · **Stabler Logist** |

Ayrıca **"oversight"** (portföyün tamamını görme) ayrı bir kavram:
`_OVERSIGHT_ROLES = System Manager · Stabler Admin · Sales Manager · Stabler Tender
Director` (`tender.py:1752`). Düz bir `Sales User` yalnız **kendisine atanmış**
lotları görür (`sourcing_my_tenders`, `tender.py:2130-2138`).

Finans sekmesi ayrı kapı: oversight **veya** `Accounts User` / `Accounts Manager`
(`_can_view_tender_finance`, `tender.py:2574-2576`).

> **UAT kuralı:** Rol kapılarını `Sales Manager` ile test etmeyin — dört görünümü
> birden açar. Dört ayrı test kullanıcısı gerekir.

### 0.2 Rol → ekran → uç nokta matrisi

| Ekran | URL | Uç nokta | Rol kapısı |
|---|---|---|---|
| Operasyon masası | `#/tender/desk` | `tender_desk.operations_desk` | herhangi bir tender görünümü (`tender_desk.py:35-37`) |
| Süreç akışı | `#/tender/flow` | `tender.tender_flow` | menüde `director` (TenderNav.vue:40); **uç noktada rol yok**, yalnız modül (`tender.py:3015`) |
| Tender CRM (kanban) | `#/tender/crm` | `tender.crm_board`, `tender.move_deal_stage` | menüde `director`\|`sourcing`; uç noktada yalnız modül (`tender.py:2305`) |
| Direktör panosu | `#/tender/portfolio` | `tender.tender_director_board`, `tender_managers`, `assign_tender`, `tender_funnel` | `director` (`tender.py:1989`) |
| Benim ihalelerim | `#/tender/my-tenders` | `tender.sourcing_my_tenders` | `sourcing` (`tender.py:2126`) |
| Tedarik karşılaştırma | `#/tender/sourcing?deal=<Deal>` | `purchasing.tender_quotations` | (bu pakette kaynak yok) |
| Tender PO kontrol / çalışma alanı | `#/tender/po-control?deal=<Deal>&tab=<sekme>` | `tender_workspace`, `po_control_board`, `deal_intake`, `save_deal_intake`, `deal_bid_pricing`, `save_deal_bid_pricing`, `bid_package`, `po_landed_charges`, `save_po_landed_charges`, `hs_rate_lookup`, `landed_actual_from_voucher` | Deal okuma/yazma + modül (`_deal_scope`, `tender.py:977-986`) |
| Sözleşme panosu | `#/tender/board` (+ `?tender=1`) | `tender.so_board`, `move_so_stage`, `so_stage_save`, `so_stage_delete` | modül (`tender.py:89`) |
| Gümrük kuyruğu | `#/tender/customs` | `tender.declarant_queue` | `declarant` (`tender.py:2023`) |
| Lojistik | `#/tender/logistics` | `tender.logist_board` | `logist` (`tender.py:2066`) |

**Yönlendirme notu:** `#/tender/director` artık `/dashboard`'a yönleniyor
(`router.js:272`); direktör panosunun gerçek adresi `#/tender/portfolio`
(`router.js:273`).

### 0.3 Demo verinin tam içeriği — ne VAR, ne YOK

`seed_tender_demo.py:51-71` 13 anlaşma üretir (4303/4304/4307 bilerek yok):

| Lot | Alıcı | Damgalı aşama | Kaç gündür | Teklif son tarihi | Tutar (intake) |
|---|---|---|---|---|---|
| UTY-2026-4301 | O'zbekiston temir yo'llari AJ | seen | 1 gün | +21 gün | — |
| UTY-2026-4302 | Toshkent vagon ta'mirlash zavodi | seen | 3 gün | +11 gün | — |
| UTY-2026-4305 | O'zbekiston temir yo'llari AJ | go | 4 gün | **−1 gün (GEÇMİŞ)** | 1 840 000 000 |
| UTY-2026-4306 | Signal va aloqa boshqarmasi | go | 5 gün | +18 gün | 640 000 000 |
| UTY-2026-4308 | Signal va aloqa boshqarmasi | sourcing | **19 gün (eşik 14 — AŞMIŞ)** | **bugün** | 920 000 000 |
| UTY-2026-4309 | Qurilish materiallari kombinati | sourcing | **26 gün (AŞMIŞ)** | +25 gün | 410 000 000 |
| UTY-2026-4310 | O'zbekiston temir yo'llari AJ | priced | **8 gün (eşik 3 — AŞMIŞ)** | +2 gün | 3 150 000 000 |
| UTY-2026-4311 | Neft mahsulotlari bazasi | priced | **6 gün (AŞMIŞ)** | +6 gün | 780 000 000 |
| UTY-2026-4312 | Neft mahsulotlari bazasi | submitted | **damga YOK** | +32 gün | 480 000 000 |
| UTY-2026-4313 | Toshkent vagon ta'mirlash zavodi | submitted | **damga YOK** | +9 gün | 1 120 000 000 |
| UTY-2026-4314 | Qurilish materiallari kombinati | won | 40 gün | +21 gün | 2 270 000 000 |
| UTY-2026-4315 | O'zbekiston temir yo'llari AJ | won | 55 gün | +21 gün | 1 650 000 000 |
| UTY-2026-4316 | Signal va aloqa boshqarmasi | lost | 48 gün | +21 gün | 890 000 000 |

**Demo verinin ÜRETMEDİĞİ şeyler** (`seed_tender_demo.py` içinde tek bir
`Supplier Quotation`, `Sales Order`, `Purchase Order`, `Purchase Receipt` ya da
`Customs` kaydı yaratılmıyor — dosyadaki tek belge üretimi `CRM Deal`,
`CRM Organization` ve `CRM Stage Event`):

- **0 Supplier Quotation.** `DEMO_LOTS` tuple'ındaki `sq_sayısı` ve `ülke_sayısı`
  kolonları (5, 3, 6 …) **hiçbir yerde kullanılmıyor** — `seed()` (satır 178-202)
  o iki değişkeni okuyup atıyor. Yani "5 teklif toplandı" iddiası veride yok.
- **0 Sales Order** → sözleşme panosu (`#/tender/board`) demo veriyle **boş**.
- **0 Purchase Order** → PO kontrol, gümrük kuyruğu ve lojistik panosu demo
  veriyle **boş**.

Bu, aşağıdaki senaryoların **SEN-12'den sonrasının demo veriyle test
edilemeyeceği** anlamına gelir; o senaryolar için el ile SO/PO açmanız gerekiyor
(adımları senaryolarda yazılı).

### 0.4 Aşama eşikleri (SLA)

`api/_tender_sla.py:30-38`:

```
seen 3 · go 5 · sourcing 14 · priced 3 · submitted 30
won / lost → eşik YOK (bilinçli, satır 36-38)
```

Kiracı bunları `Stabler Settings` üzerinden `stage_sla_for(company)` ile ezebilir
(`tender.py:3067`). `0` veya negatif = "takip etme" (`_tender_sla.py:80-86`).

---

## 1. FAZ 1 — İLAN GÖRÜLDÜ (`seen`)

### SEN-01 · Yeni lotun panoda görünmesi

- **Ekran:** `https://mikas.erpstable.com/stabler#/tender/crm`
- **Uç nokta:** `stabler.api.tender.crm_board`
- **Kim:** director veya sourcing (menü kapısı TenderNav.vue:47)
- **Üretilen belge:** Yok — bu ekran sadece okuyor. Lotun kendisi bir `CRM Deal`
  kaydıdır ve **tender modülünde açılamaz**; `#/crm/deals` üzerinden ya da
  `crm.save_deal` ile açılır.
- **Ön koşul:** `seed()` çalıştırılmış; rol `Stabler Tender Director`.
- **Adımlar:**
  1. `#/tender/crm` aç.
  2. "Intake" kulvarını say.
  3. Bir karta tıkla → sağdan çekmece açılsın.
- **Beklenen:** Intake kulvarında **2 kart** (UTY-2026-4301, 4302). Kart üzerinde
  alıcı kurum adı, `0/5 quotes` ölçer (5 kutucuk, hepsi boş) ve `Readiness 25%`
  (4301 için: 4 belgenin 1'i hazır) görünür.
- **Kırık belirtisi:**
  - Kartın alt satırında **son tarih hiç yazmıyor** → bu KIRIK, bkz. **KOP-03**.
    `crm_board` `deadline_info.get("deadline")` okuyor ama `_deal_deadlines`
    böyle bir anahtar döndürmüyor.
  - Kulvar başlığı `seen` gibi ham anahtar gösteriyorsa çeviri kaynağı bozulmuş
    (TenderCrm.vue:148-151 lane etiketinden okumalı).
- **Kanıt:** `api/tender.py:2309-2317` (7 kulvar), `tender.py:2379-2381` (deadline
  bug), `tender.py:2387-2388` (doc_progress), `TenderCrm.vue:367-378`.

### SEN-02 · Lot künyesinin (intake) doldurulması + UZEX çekme

- **Ekran:** `#/tender/po-control?deal=<Deal>&tab=overview` → "Deadline control"
  kartındaki **Tender details** düğmesi
- **Uç nokta:** `tender.deal_intake` (oku) · `tender.save_deal_intake` (yaz) ·
  `stabler.api.uzex.fetch_lot` (UZEX'ten çek)
- **Kim:** Deal üzerinde `write` yetkisi olan herkes (`_deal_scope(write=True)`,
  `tender.py:1626`). Ayrı bir tender rolü ARANMIYOR.
- **Üretilen belge:** **Hiçbiri.** Künye `CRM Deal.custom_tender_intake` alanına
  JSON olarak yazılıyor (`tender.py:1634-1636`). Ayrı bir doctype yok.
- **Ön koşul:** UTY-2026-4301'in Deal adını not edin (kart üzerinde `CRM-DEAL-…`).
- **Adımlar:**
  1. `#/tender/po-control?deal=<Deal>` aç, "Tender details" bas.
  2. UZEX lot URL'sini yapıştır → **Fetch**.
  3. Lot no, alıcı, ihale son tarihi, teslim son tarihi, garanti tutarı ve iade
     tarihi, **satın alma yöntemi** (auction / shop / selection / tender), günlük
     ceza %, sertifika gerekli mi doldur.
  4. Belge listesinde **Standard set** bas → 6 satır gelir: Shartnoma, Protokol,
     Muvofiqlik sertifikati, ГТД, Qabul dalolatnomasi, Hisob-faktura.
  5. Kaydet.
- **Beklenen:** Üst şeritte "Documents 0/6" sarı rozeti; milestone çipleri
  (Bid deadline / Contract / PO ETA / Delivery deadline) gün sayacı ile çizilir.
- **Kırık belirtisi (KRİTİK):**
  - Kaydettikten sonra `#/tender/crm`'e dönün: **kartın tutarı 0 oldu.**
    `_clean_intake` `contract_value` anahtarını tanımıyor
    (`_INTAKE_KEYS_STR` 1344-1356, `_INTAKE_KEYS_NUM` 1357-1365), bu yüzden ilk
    kayıtta siliniyor. Bkz. **KOP-04**.
  - Demo lotunda "Standard set" basmadan önce belge rozeti hiç çıkmaz — çünkü
    demo belgeleri `{name, status}` şemasında, backend `{label, required, done}`
    bekliyor. Bkz. **KOP-05**.
- **Kanıt:** `tender.py:1371-1440` (`_clean_intake`), `TenderIntake.vue:91-97`
  (STD_DOCS), `seed_tender_demo.py:134-139` (demo belge şeması).

### SEN-03 · Lotun bir uzmana dağıtılması

- **Ekran:** `#/tender/portfolio` → tablonun son sütunundaki **Manager** açılır
  listesi
- **Uç nokta:** `tender.tender_managers` (liste) · `tender.assign_tender` (ata)
- **Kim:** yalnız **oversight** (`_is_tender_oversight`, `tender.py:1789`).
  Aday listesi `Sales User` + `Sales Manager` rolündeki aktif kullanıcılar
  (`tender.py:1766-1781`).
- **Üretilen belge:** Yok — `custom_tender_intake.assigned_to/_at/_by`.
- **Ön koşul:** En az bir kullanıcıya `Sales User` rolü verilmiş olmalı.
- **Adımlar:**
  1. `#/tender/portfolio` aç.
  2. UTY-2026-4308 satırında Manager = test kullanıcısı seç.
  3. `Sales User` kullanıcısıyla giriş yap → `#/tender/my-tenders`.
- **Beklenen:** `Sales User` **yalnız kendisine atanan** lotu görür; atama
  yapılmadan önce liste **tamamen boştur** (`tender.py:2137-2138`).
- **Kırık belirtisi (KRİTİK):** Atama sonrası o lotun **belge kontrol listesi
  boşalır** ve tutarı sıfırlanır — `assign_tender` `_clean_intake(intake, intake)`
  çağırıyor (`tender.py:1799`), bu da etiketi olmayan demo belgelerini eliyor ve
  `contract_value`'yu düşürüyor. Bkz. **KOP-04/KOP-05**.
- **Kanıt:** `tender.py:1785-1818`, `DirectorBoard.vue:54-63`.

---

## 2. FAZ 2 — GİDİLECEK Mİ (`go` / `no_go`)

### SEN-04 · GO kararı — İKİ farklı yol, İKİ farklı sonuç

Aynı iş kararının kodda **iki ayrı girişi** var ve **aynı kaydı üretmiyorlar.**

**Yol A — Künyeden karar (denetim izli):**
- **Ekran:** `#/tender/po-control?deal=<Deal>` → Tender details → **Decision = Go**
- **Uç nokta:** `tender.save_deal_intake`
- **Beklenen:** `go_no_go="go"`, **`go_no_go_at` + `go_no_go_by` sunucu tarafında
  damgalanır** (`tender.py:1387-1400`). Karar değişmediği sürece damga korunur.

**Yol B — Kanbanda kartı "GO Decision" kulvarına sürükleme:**
- **Ekran:** `#/tender/crm`
- **Uç nokta:** `tender.move_deal_stage`
- **Beklenen:** `custom_tender_stage="go"`, `custom_tender_stage_entered_at`
  güncellenir, bir `CRM Stage Event` yazılır, intake'e `go_no_go="go"` düşer.
- **Kırık belirtisi:** `go_no_go_at` / `go_no_go_by` **yazılmaz** —
  `move_deal_stage` `_clean_intake`'i atlayıp doğrudan `json.dumps` ediyor
  (`tender.py:2495-2504`). Sonuç: Direktör panosunun ve gösterge panelinin dönem
  filtreleri bu kararı **hiç görmez** (`_tender_event_dates` `decided` alanı boş,
  `tender.py:2536-2546`; `tender_dashboard` `acquisition["go"]` sayacı
  `tender.py:2736-2737`).

- **Kim:** Yol A → Deal write; Yol B → Deal write + modül. Hiçbirinde "director"
  rolü ARANMIYOR. Bir `Sales User` GO/NO-GO kararını tek başına verebilir.
- **UAT adımı:** UTY-2026-4301'i Yol B ile `go`'ya sürükleyin, sonra
  `#/tender/portfolio` üzerinde dönem filtresi uygulayın (`?period=YYYY-MM`).
  Lot listeden **düşer** — çünkü `event_dates.decided` boştur.
- **Kanıt:** `tender.py:2450-2507`, `tender.py:1388-1400`,
  `composables/tenderBoardFilters.js:19-28`.

### SEN-05 · Portal (Telegram/UZEX) üzerinden gelen GO kararı

- **Uç nokta:** `tender.set_tender_go_no_go_from_trusted_source` — **whitelist
  DEĞİL** (`tender.py:1688`), yani SPA'dan çağrılamaz; UZEX webhook'u çağırır.
- **Beklenen:** Karar `_clean_intake(..., audit_actor=actor)` ile yazılır, yani
  damgada **entegrasyon aktörü** görünür (`tender.py:1707`).
- **UAT:** Webhook'u tetikleyip `custom_tender_intake.go_no_go_by` alanının
  oturum kullanıcısı DEĞİL, entegrasyon aktörü olduğunu doğrulayın.

---

## 3. FAZ 3 — TEDARİK / FİYAT TOPLAMA (`sourcing`)

### SEN-06 · Tedarikçi tekliflerinin lota bağlanması

- **Ekran:** Supplier Quotation ekranı **tender modülünde YOK.** SQ,
  `Supplier Quotation.custom_crm_deal` alanı ile lota bağlanıyor; bu alanı yazan
  bir tender ekranı yok (SPA'daki hiçbir `.vue` `custom_crm_deal`
  göndermiyor — bkz. **KOP-07**).
- **Uç nokta (okuma):** `purchasing.tender_quotations`
- **Kim:** sourcing
- **Üretilen belge:** `Supplier Quotation` (ERPNext masaüstü ya da purchasing
  modülü üzerinden, el ile).
- **Ön koşul:** UTY-2026-4308 için 5 SQ, en az 2 farklı ülkeden tedarikçi.
- **Adımlar:**
  1. ERPNext masaüstünden 5 adet Supplier Quotation aç,
     `custom_crm_deal = <4308'in Deal adı>` yaz.
  2. `#/tender/crm` yenile.
- **Beklenen:** Kartın ölçer çubuğu `5/5 quotes` dolar; `has_min_5` ve
  `has_2_countries` ikisi de sağlanınca ölçer "tam" işaretlenir
  (`tender.py:2400-2401`, `TenderCrm.vue:367`). Politika: **en az 5 teklif,
  en az 2 ülke** (`TenderCrm.vue:124`).
- **Kırık belirtisi:** Ülke sayısı `Supplier.country` alanından geliyor
  (`tender.py:2347-2351`); tedarikçilerde ülke boşsa `country_count=0` kalır ve
  politika hiç sağlanmaz.
- **Kanıt:** `tender.py:2330-2351`, `tender.py:2398-2401`.

### SEN-07 · Aynı lota gelen tekliflerin karşılaştırılması

- **Ekran:** `https://mikas.erpstable.com/stabler#/tender/sourcing?deal=<Deal>`
- **Uç nokta:** `stabler.api.purchasing.tender_quotations`
- **Kim:** modül erişimi olan herkes (`router.js:270`; ekranın kendi rol kapısı yok)
- **Beklenen:** Tablo: Tedarikçi · Ülke · Tutar · **Baz para birimi tutarı** ·
  Geçerlilik · Durum. En ucuz satır `cheapest` rozeti ve yeşil satır ile
  işaretlenir. Üstte iki politika rozeti: `Quotations n/5`, `Countries n/2`.
- **İkinci giriş noktası:** `#/tender/po-control?deal=…&tab=vendor-po` sayfasının
  en üstündeki "Supplier quotations" kartı aynı veriyi rozet olarak gösterir
  (`PoControlBoard.vue:323-335`) — ama orada **fiyat yok**, sadece tedarikçi adı.
- **Üçüncü giriş noktası:** `#/tender/crm` kart çekmecesindeki "Sourcing Summary"
  tablosu (`TenderCrm.vue:531-553`).
- **Kırık belirtisi:** `deal` parametresi olmadan ekran boş bir arama kutusu
  gösterir; kanbandan gelen bağlantı `deal` taşır (`TenderCrm.vue:576-580`),
  doğrudan menüden girişte lot **elle aranmalıdır**.
- **Kanıt:** `SourcingCompare.vue:37-51`, `SourcingCompare.vue:100-141`.

### SEN-08 · Tedarik politikası boşluğunun operasyon masasına düşmesi

- **Ekran:** `#/tender/desk`
- **Uç nokta:** `tender_desk.operations_desk` → kural motoru `_desk_rules.build_plan`
- **Beklenen:** `custom_tender_stage = "sourcing"` VE `sq_count < 5` olan her lot
  için **"Missing supplier quotes"** kalemi, severity `today`
  (`_desk_rules.py:103-114`). Demo veride bu **tam 2 kalem** üretir (4308, 4309).
- **Kırık belirtisi:** Demo veride masada bu 2 kalemden **başka hiçbir şey yok** —
  4305'in teklif son tarihi dün geçmiş olmasına rağmen "Bid due" kalemi
  çıkmıyor. Bkz. **KOP-01** (masa, künye JSON'unu hiç okumuyor).
- **Kanıt:** `tender_desk.py:55-87` (okunan alanlar), `_desk_rules.py:42-114`.

---

## 4. FAZ 4 — TEKLİF FİYATLANDIRMA (`priced`)

### SEN-09 · Sözleşme P&L şelalesi ile teklif fiyatının çıkarılması

- **Ekran:** `#/tender/po-control?deal=<Deal>&tab=overview` → "Tender bid pricing"
  kartı
- **Uç nokta:** `tender.deal_bid_pricing` (oku) · `tender.save_deal_bid_pricing` (yaz)
- **Kim:** Deal write.
- **Üretilen belge:** Yok — `CRM Deal.custom_bid_pricing` JSON alanı
  (`tender.py:1331-1333`).
- **Adımlar:**
  1. **Margin → price** modunda: hedef marj % gir (varsayılan 20).
  2. "Use POs' landed" bağlantısı ile maliyet tabanını lota bağlı PO'ların landed
     toplamından çek (`BidPricing.vue:113`).
  3. Vergi parametrelerini aç: KDV %12, borsa komisyonu %0.15, kâr vergisi %15,
     temettü vergisi %5 (`tender.py:967-974`).
  4. "Other costs (before profit)" ve "Costs after dividends" satırlarını ekle.
  5. Kaydet.
- **Beklenen şelale (tam sıra, `tender.py:1088-1155`):**
  `Договор (brüt)` − KDV → `Чистая выручка` − landed − borsa komisyonu − diğer
  üst-çizgi giderleri → **`Прибыль`** − kâr vergisi → `Чистая прибыль` −
  temettü vergisi → `Дивиденды` − alt-çizgi giderleri → **`Остаток`**.
  Ters yön (`Price → margin`) için `bid_price` girilir, marj hesaplanır.
- **Kritik matematik kontrolü:** `mode="margin"` iken payda
  `(1 − m) − (1 + KDV) × borsa` (`tender.py:1118`). Marj %85 üstüne çıkarıldığında
  payda ≤ 0 olur ve fonksiyon **hata vermeden 0 döndürür** (satır 1119) — ekranda
  teklif fiyatı `0` görünür. UAT'ta marj 90 girip bunu doğrulayın.
- **Kırık belirtisi:** Kaydettikten hemen sonra lot `#/tender/crm`'de "Bid Pricing"
  kulvarına **atlar**, çünkü sınıflandırma "custom_bid_pricing alanı dolu mu"
  diye bakıyor, içeriğine değil (`_funnel.classify`, `_funnel.py:46-47`;
  `tender.py:2363`). Yani **sıfır marjla boş bir kayıt bile lotu "fiyatlandı"
  yapar.**
- **Kanıt:** `tender.py:1088-1155`, `tender.py:1300-1336`, `BidPricing.vue:85-108`.

### SEN-10 · Evrak setinin (başvuru paketi) hazırlanması

- **Ekran:** Aynı kart → **"Prepare application package"** düğmesi
- **Uç nokta:** `tender.bid_package`
- **Kim:** Deal **read** yeterli (`_deal_scope(write=False)`, `tender.py:1237`).
- **Üretilen belge:** `bid_<lot_no>.docx` — **private File** olarak `CRM Deal`'e
  eklenir (`tender.py:1281`). Teklif mektubu + fiyat tablosu.
- **Ön koşul:** Lot no, alıcı kurum, son tarih, başlangıç fiyatı gibi UZEX
  alanları (`custom_uzex_lot_no`, `custom_uzex_customer_org`, `custom_uzex_deadline`,
  `custom_uzex_start_price`, `custom_uzex_portal`) dolu olmalı (`tender.py:1246-1260`).
- **Beklenen:**
  - Eksik alan varsa: sarı uyarı kutusunda **`missing[]` listesi**, dosya
    üretilmez (`BidPricing.vue:273-275`).
  - Tamamsa: indirilebilir `.docx` bağlantısı.
- **Kırık belirtisi:** Sunucuda `python-docx` kurulu değilse paket "ready" döner
  ama dosya yoktur; ekranda sadece `warnings` satırı çıkar
  (`tender.py:1283-1285`).
- **ÖNEMLİ İŞ NOTU:** Bu paket **portala gönderilmiyor.** Kod açıkça diyor:
  "No portal submission — the human signs (E-IMZO) and uploads"
  (`tender.py:1234-1235`). İmza ve yükleme sistem dışında, elle.

---

## 5. FAZ 5 — TEKLİF VERİLDİ (`submitted`)

### SEN-11 · Teklif verildi damgasının kaydedilmesi — **UI'DAN YAPILAMAZ**

- **Uç nokta:** `tender.mark_tender_submitted` (`tender.py:1648`)
- **Kim:** yalnız `director` veya `sourcing` görünümü olanlar (`tender.py:1652-1653`)
- **Ürettiği kayıt:** `submitted_at` + `submitted_by` + `submission_reference`
  (portal referans no) — satır kilidi (`SELECT … FOR UPDATE`) ile eşzamanlı
  yazımlara karşı korunmuş, tekrar çağrılırsa ilk kaydı döndürür
  (`tender.py:1656-1666`).
- **Kırık belirtisi (EN KRİTİK BULGU):** SPA'daki **hiçbir ekran bu uç noktayı
  çağırmıyor.** Yüklenen tüm `.vue`/`.js` dosyalarında `mark_tender_submitted`
  geçmiyor. Kullanıcının tek yapabildiği, kanbanda kartı "Submitted" kulvarına
  sürüklemek — ama `move_deal_stage` yalnız `submitted_at` yazıyor,
  **`submitted_by` yazmıyor** (`tender.py:2503`).
- **Sonucu:** `_has_submission_evidence` iki alanı da arıyor
  (`tender.py:2559-2561`) → **False**. Yani:
  - Direktör panosunda kazanma oranı hesabına girmez (`tender.py:1899-1908`).
  - Gösterge paneli `acquisition["submitted"]` sayacı artmaz (`tender.py:2741-2742`).
  - Lot "unverified_history" olarak sayılır (`tender.py:1907-1908`).
- **UAT adımı:** UTY-2026-4310'u kanbanda "Submitted"a sürükleyin, sonra
  `#/tender/portfolio` açın. Satırda yeşil "Won/Lost" yerine sarı
  **"Unverified"** rozeti çıkar (`DirectorBoard.vue:199-201`) ve üstte
  "N tenders carry unverified history" uyarısı belirir
  (`DirectorBoard.vue:159-161`).
- **Kanıt:** `tender.py:1648-1685`, `tender.py:2495-2504`, `tender.py:2559-2561`.

---

## 6. FAZ 6 — KAZANILDI / KAYBEDİLDİ (`won` / `lost`)

### SEN-12 · Sonucun işlenmesi ve kazanma oranı

- **Ekran (yol A):** `#/tender/po-control?deal=…` → Tender details → Result =
  Won/Lost/Pending → Kaydet
- **Ekran (yol B):** `#/tender/crm` → kartı "Won" veya "Lost" kulvarına sürükle
- **Uç nokta:** `save_deal_intake` / `move_deal_stage`
- **Kim:** Deal write. **Direktör onayı aranmıyor.**
- **Beklenen (yol A):** `result` + `result_at` + `result_by` damgalanır
  (`tender.py:1388-1400`).
- **Beklenen (yol B):** yalnız `intake["result"]` yazılır; `result_at`/`result_by`
  **yazılmaz** (`tender.py:2498-2499`).
- **Kazanma oranı doğrulaması (demo veri):**
  - Direktör panosu: won 2 (4314, 4315), lost 1 (4316) → **win_rate %66.7**
    (`tender.py:1958`). Bu sayı yalnız demo verinin `submitted_by` alanını
    seed'in elle yazması sayesinde doğru çıkıyor (`seed_tender_demo.py:144-148`).
  - Aynı işlemi UI'dan yapan bir kullanıcı bu sayıya **hiç katkı yapamaz** (SEN-11).
- **Kırık belirtisi:** `#/tender/portfolio` üstünde "Result 0% win rate" ve
  altında "N tenders carry unverified history" ikilisi → sonuçlar giriliyor ama
  katılım kanıtı yok.
- **Kanıt:** `tender.py:1894-1908`, `tender.py:1948-1959`, `DirectorBoard.vue:86-89`.

---

## 7. FAZ 7 — SÖZLEŞME (Договор → Sales Order)

### SEN-13 · Kazanılan lotun sözleşmeye dönüşmesi — **OTOMASYON YOK**

- **Ekran:** Yok. Sözleşme `#/sales/orders/new` ekranından açılır.
- **Uç nokta:** `stabler.api.sales.create_sales_order`
- **Kim:** sales modülü kullanıcısı (tender rolleri yetmez).
- **Üretilen belge:** `Sales Order`, `custom_crm_deal = <Deal>` alanı ile lota
  bağlanmalı.
- **Kodun gerçeği:**
  - `api/tender.py` içinde **hiçbir yerde** Sales Order üretilmiyor. Dosyadaki
    tüm belge yaratma çağrıları: `Stabler SO Stage` (varsayılan kulvarlar) ve
    `CRM Stage Event`. Başka hiçbir doctype üretilmiyor.
  - `crm.py`'deki kazanma otomasyonu (`_maybe_convert_won_deal`, `crm.py:506-513`)
    yalnız bir **Customer** yaratıyor — sipariş değil. Üstelik bu otomasyon
    **CRM statü ekseninde** (`transition_deal`, `crm.py:672-681`) tetikleniyor;
    tender kanbanındaki `move_deal_stage` onu **çağırmıyor**.
  - `SalesOrderForm.vue` `crm_deal` alanını **yalnız URL sorgusundan** alıyor
    (`SalesOrderForm.vue:731`) ve tender ekranlarının hiçbiri
    `/sales/orders/new?crm_deal=…` bağlantısı üretmiyor.
- **Adımlar (elle):**
  1. UTY-2026-4314'ün Deal adını kopyala.
  2. Adres çubuğuna elle yaz:
     `#/sales/orders/new?crm_deal=<Deal adı>` → mor "From tender deal" şeridi
     görünmeli (`SalesOrderForm.vue:949-953`).
  3. Müşteri, kalemler, teslim tarihi gir → Kaydet + Onayla.
- **Beklenen:** SO onaylandıktan sonra `#/tender/board` panosunda "New"
  kulvarında kart; `#/tender/po-control?deal=…&tab=delivery` sekmesinde
  "Sales execution → Sales order" satırında görünür.
- **Kırık belirtisi:** `crm_deal` sorgusu olmadan açılan SO lota **hiç
  bağlanmaz**; sonrasında düzeltmenin SPA'da yolu yoktur (form yalnız `isCreate`
  durumunda bu alanı gösteriyor). Bkz. **KOP-06**.
- **Kanıt:** `tender.py:2413-2448` (üretilen tek belge tipi CRM Stage Event),
  `crm.py:506-513`, `SalesOrderForm.vue:264`, `SalesOrderForm.vue:731`.

### SEN-14 · Sözleşme panosu (yürütme kulvarları)

- **Ekran:** `#/tender/board` · tender filtresi için `#/tender/board?tender=1`
- **Uç nokta:** `tender.so_board` · `tender.move_so_stage` · `so_stage_save` ·
  `so_stage_delete`
- **Kim:** modül erişimi olan herkes.
- **Varsayılan kulvarlar** (ilk açılışta tembel tohumlanıyor,
  `tender.py:28-36, 56-73`): New · Procurement · Delivery · Acceptance ·
  Invoicing · **Paid (is_won)** · **Closed (is_closed)**.
- **Beklenen:**
  - Her kart: SO no, müşteri, tutar, teslim tarihi, **Delivered %** ve
    **Billed %** çubukları (`SalesOrderBoard.vue:184-191`).
  - Tender kaynaklı SO'larda mor bayrak rozeti (`SalesOrderBoard.vue:177`).
  - Kartı başka kulvara sürükle → `move_so_stage` → `custom_board_stage` yazılır.
  - Kulvar sil → içinde SO varsa doctype `on_trash` engeller (`tender.py:200-207`).
- **Kırık belirtisi / tuzak:**
  - `?tender=1` **sadece filtreyi değil, belge durumu tabanını da değiştiriyor:**
    normal modda yalnız `docstatus=1` (onaylı), tender modunda `docstatus<2`
    (taslaklar dahil) — `tender.py:98-102`. İki mod arasında geçiş yaptığınızda
    kart sayısı beklenmedik biçimde artar.
  - Tender CRM çekmecesindeki "Contract board" bağlantısı `?tender=1`
    **taşımıyor** (`TenderCrm.vue:581`) → lot bağlamı kayboluyor, şirketin tüm
    SO'ları geliyor.
  - Huni ekranındaki yürütme sayıları yalnız `docstatus=1` sayıyor
    (`tender.py:2266`) → `?tender=1` panosuyla **farklı sayı** gösterir.
- **Kanıt:** `tender.py:85-148`, `tender.py:151-164`, `_funnel.py:123-146`.

---

## 8. FAZ 8 — SİPARİŞ (Purchase Order + landed cost planı)

### SEN-15 · Tedarikçi siparişinin açılması ve lota bağlanması

- **Ekran:** `#/purchasing/orders/new` — **tender modülünde bu adımın ekranı yok.**
- **Üretilen belge:** `Purchase Order`, `custom_crm_deal = <Deal>`.
- **Kodun gerçeği:** PO'nun lota bağlanması, `po_control_board`,
  `declarant_queue`, `logist_board`, `_deal_landed`, `tender_dashboard` — yani
  tender modülünün **yürütme yarısının tamamı** — bu alanın dolu olmasına bağlı
  (`tender.py:518`, `2012`, `1000`, `2777`). Ama bu alanı yazan bir tender
  ekranı yok; PO formunda da bir "tender lotu" seçici bulunmuyor.
- **Kırık belirtisi:** PO açıldı ama `custom_crm_deal` boş → PO kontrol panosu
  "No purchase orders tagged to this tender yet." der
  (`PoControlBoard.vue:444`); gümrük ve lojistik kuyrukları o PO'yu **hiç
  göstermez**. Bkz. **KOP-07**.

### SEN-16 · Landed cost (varış maliyeti) planının kurulması

- **Ekran:** `#/tender/po-control?deal=<Deal>&tab=vendor-po` → PO kartındaki
  **para raporu** ikonu → "Landed cost plan" modalı
- **Uç nokta:** `tender.po_landed_charges` (oku) · `tender.save_po_landed_charges`
  (yaz) · `tender.hs_rate_lookup` (ТН ВЭД oranı) ·
  `tender.landed_actual_from_voucher` (fiili tutarı defterden çek)
- **Kim:** PO üzerinde `write` (`_po_scope`, `tender.py:348-360`).
- **Üretilen belge:** Yok — `Purchase Order.custom_landed_charges` JSON alanı
  (`tender.py:445-452`). Onaylanmış PO'da bile yazılabilir (allow_on_submit
  overlay); muhasebe belgesine dokunmaz.
- **Gider tipleri (11 adet, `tender.py:241-253`):** transport · customs ·
  certification · insurance · storage · declarant · legal · broker · loading ·
  bank · other.
- **Adımlar:**
  1. "Add cost item" → tip = **customs** seç.
  2. ТН ВЭД kodunu gir → **arama** düğmesi → `hs_rate_lookup` `HS Duty Rate`
     tablosundan gümrük vergisi / akziz / KDV oranlarını çeker; en güncel
     `effective_from` satırı kazanır (`tender.py:380-397`).
  3. Gümrük değeri (CIF) gir.
  4. **"VAT recoverable (registered)"** anahtarını kontrol et.
  5. Nakliye satırı ekle, sağlayıcı olarak bir `Supplier` seç.
  6. "Actual" kolonunda PInv/PE/JE tipi seç, belge no yaz, indir ikonuna bas →
     tutar defterden okunur ve salt-okunur olur.
  7. Kaydet.
- **Beklenen hesap (`tender.py:414-420` + `PoControlBoard.vue:192-202`):**
  - `duty = CIF × duty%` , `excise = CIF × excise%` ,
    `KDV = (CIF + duty + excise) × vat%`
  - **KDV geri alınabilir ise landed maliyete GİRMEZ** — yalnız duty + akziz
    kapitalize olur (IAS 2 §11 gerekçesi `tender.py:288-294`'te yazılı).
    Ekran geri alınabilir KDV'yi ayrı yeşil satırda gösterir.
  - `landed_total = base_grand_total + Σ planlanan giderler`
  - `actual_landed = base_grand_total + Σ fiili giderler`
- **Kırık belirtisi:**
  - Kaydetme, **tutarı 0 olan satırları sessizce atar**
    (`PoControlBoard.vue:257`: `.filter(l => Number(l.amount))`). Yani "ГТД
    açılacak ama tutar henüz belli değil" satırı kaydedilemez.
  - `save_po_landed_charges` `update_modified=False` ile yazıyor
    (`tender.py:451`) → PO'nun "son değiştirme" damgası hareket etmez, plan
    değişikliği belge geçmişinde görünmez.
- **Kanıt:** `tender.py:256-302`, `tender.py:400-461`, `PoControlBoard.vue:156-274`.

### SEN-17 · Tedarikçi karşılaştırması ve PO kontrol panosu

- **Ekran:** `#/tender/po-control?deal=<Deal>&tab=vendor-po`
- **Uç nokta:** `tender.po_control_board`
- **Kulvarlar:** Draft · To receive · Partially received · Completed —
  PO'nun kendi durumundan türetilir, **elle taşınamaz** (`_po_lane`,
  `tender.py:227-235`).
- **Rozetler:** `cheapest` (en düşük landed) · `draft` · `delayed`
  (onaylı + `per_received<100` + `schedule_date` geçmiş) · `received` ·
  `partial:%` · `billed` (`tender.py:546-561`).
- **"Vendor comparison (landed)" tablosu — İŞİN KALBİ:**
  Tedarikçi · Mal (baz) · Giderler · **Landed** · en ucuza göre fark % ·
  **teklif tutarı (SQ)** · teslim · PO adedi. Sıralama **landed maliyete göre
  ucuzdan pahalıya** (`tender.py:648`).
  `delta_pct = (PO toplam − SQ toplam) / SQ toplam × 100` — yani "teklif
  verdiğinden ne kadar sapmış" (`tender.py:622`).
- **Beklenen:** SQ'ler ve PO'lar farklı para birimlerinde olsa bile karşılaştırma
  **baz para biriminde** yapılır (`tender.py:612-617`).
- **Kırık belirtisi:** `custom_crm_deal` alanı henüz migrate edilmemişse uç nokta
  hata vermez, **boş ama düzgün şekilli bir pano** döner (`tender.py:488-496`) —
  yani "veri yok" ile "alan yok" ekranda ayırt edilemez.
- **Kanıt:** `tender.py:464-667`, `PoControlBoard.vue:407-448`.

---

## 9. FAZ 9 — GÜMRÜK (ГТД)

### SEN-18 · Gümrük kuyruğu (declarant penceresi)

- **Ekran:** `https://mikas.erpstable.com/stabler#/tender/customs`
- **Uç nokta:** `tender.declarant_queue`
- **Kim:** `declarant` (`Stabler Declarant`)
- **Üretilen belge:** **Hiçbiri.** Ekran **salt okunur**; `Customs Declaration`
  doctype'ı imports modülünde var (`router.js:229-231`) ama tender kuyruğu
  **onunla hiç konuşmuyor.**
- **Ekranın gösterdiği:** PO no · tedarikçi · lot · **ТН ВЭД** · gümrük tutarı ·
  PO ETA · kalan gün · durum.
- **Durum türetimi (`tender.py:2032-2035`):**
  - `cleared` → PO `per_received >= 100`
  - `in_progress` → planlanmış bir gümrük gideri **tutarı var**
  - `pending` → gümrük gideri satırı yok
- **ÖNEMLİ İŞ NOTU:** Kodun kendi itirafı — "No native PO-level customs clearance
  field exists in this install. This is workload evidence from planned landed
  customs charges, **not clearance**" (`tender.py:2810-2813`). Yani gümrükte
  "işlem başladı" demek, birinin planda bir tutar yazmış olması demek. Gerçek
  beyanname numarası, tarihi ya da çıkış izni sistemde tutulmuyor.
- **Ön koşul (demo veriyle test edilemez):** En az 1 PO, `custom_crm_deal` dolu,
  `customs` tipinde bir landed satırı ve `tnved` kodu (SEN-16).
- **Kırık belirtisi:**
  - ТН ВЭД kolonu, PO'nun **ilk** `tnved` taşıyan satırından okunuyor
    (`tender.py:2031`) — çok kalemli, farklı HS kodlu bir PO'da yalnız biri
    görünür.
  - `days_left` PO'nun `schedule_date` alanından; ГТД'nin kendi son tarihi diye
    bir kavram yok.
- **Kanıt:** `tender.py:2020-2060`, `DeclarantQueue.vue:66-88`.

---

## 10. FAZ 10 — LOJİSTİK VE TESLİM

### SEN-19 · Sevkiyat panosu (logist penceresi)

- **Ekran:** `https://mikas.erpstable.com/stabler#/tender/logistics`
- **Uç nokta:** `tender.logist_board`
- **Kim:** `logist` (`Stabler Logist`)
- **Üretilen belge:** Hiçbiri — salt okunur.
- **Ekranın gösterdiği:** PO · tedarikçi · lot · **nakliye tutarı** (landed
  planındaki `transport` + `loading` satırlarının toplamı, `tender.py:2073`) ·
  PO ETA · **lotun teslim son tarihi** · durum.
- **Gecikme kuralı:** `late = teslim alınmamış AND PO ETA > lotun teslim son
  tarihi` (`tender.py:2099`) — yani tedarikçi bize sözleşmemizden SONRA
  getirecekse kırmızı.
- **Teslim son tarihinin kaynağı (öncelik sırası, `tender.py:2081-2096`):**
  1. Lot künyesindeki `delivery_deadline`
  2. Yoksa lota bağlı SO'ların en erken `delivery_date` değeri
- **KRİTİK KAVRAM UYARISI:** Bu panoda **"Delivered"**, PO'nun
  `per_received >= 100` olması demektir (`tender.py:2100`) — yani **tedarikçiden
  bize mal geldi**, müşteriye teslim ettik değil. Müşteriye teslim ayrı bir
  eksende: SO'nun `per_delivered` yüzdesi ve `Delivery Note` belgeleri
  (`#/tender/board` kartlarındaki mavi çubuk, `SalesOrderBoard.vue:185-186`).
  **İhale uzmanı bu iki "teslim"i karıştırmamalı; sistem onları aynı kelimeyle
  adlandırıyor.**
- **Kanıt:** `tender.py:2063-2120`, `LogistBoard.vue:60-81`.

### SEN-20 · Belge zinciri (satınalma ve satış tarafı bir arada)

- **Ekran:** `#/tender/po-control?deal=<Deal>&tab=delivery`
- **Uç nokta:** `tender.tender_workspace` → `purchase_execution` /
  `sales_execution`
- **Beklenen iki sütun:**
  - **Purchase execution:** PO → Purchase Receipt → Purchase Invoice
  - **Sales execution:** Sales Order → Delivery Note → Sales Invoice
- **Bağ kurma mantığı (`tender.py:697-752`):** Üst belgeler şirket + docstatus
  ile süzülüyor; kalem tablosundan `purchase_order` / `sales_order` /
  `against_sales_order` sütunları tek sorguda okunuyor.
- **Kırık belirtisi:**
  - PR ve PInv satırları **tıklanamıyor** — yalnız ilk seviyedeki sipariş
    bağlantılı (`TenderDocumentChain.vue:37-38`).
  - Bir fatura birden çok siparişe bağlıysa listede tekrar edebilir; toplamlar
    ayrı bir tekilleştirmeden (`_unique_invoice_rows`, `tender.py:830-841`)
    geçiyor ama **ekrandaki liste geçmiyor**.
- **Kanıt:** `tender.py:755-827`, `TenderDocumentChain.vue:34-43`.

### SEN-21 · Finans sekmesi (AP / AR / marj)

- **Ekran:** `#/tender/po-control?deal=<Deal>&tab=finance`
- **Kim:** oversight **veya** `Accounts User`/`Accounts Manager`
  (`tender.py:950`, `2574-2576`). Sekme yetkisi yoksa **hiç çizilmiyor**
  (`PoControlBoard.vue:108`).
- **Beklenen 4 kutu:** Borçlar (AP toplam + açık) · Alacaklar (AR toplam + açık) ·
  **Planlanan marj** (bid pricing'in `profit` değeri) · **Fiili fatura marjı**
  (`AR toplam − AP toplam`, `tender.py:931`).
- **Kırık belirtisi:** "Planned margin" = teklif fiyatlandırmasındaki `Прибыль`;
  "Actual margin" = fatura farkı. İkisi **farklı tanımlar** (biri vergi öncesi
  kâr, diğeri brüt fatura farkı) ama ekran yan yana ve aynı biçimde gösteriyor.

### SEN-22 · Plan vs fiili kapanışı

- **Ekran:** `#/tender/po-control?deal=<Deal>&tab=overview` → "Tender bid pricing"
  kartının altındaki **"Plan vs actual"** tablosu
- **Uç nokta:** `tender.deal_bid_pricing` → `actual` bloğu
- **Fiili tarafın kaynakları (`tender.py:1182-1206`):**
  - Fiili hasılat = `Σ SO.base_grand_total × per_billed%` (`tender.py:1021-1031`)
  - Fiili landed = PO baz tutarı + landed planındaki **`actual`** sütunu
  - **Kassa giderleri** = `custom_crm_deal` etiketli, ONAYLI Journal Entry'lerin
    gider hesaplarına borçları, hesap adına göre gruplanmış
    (`tender.py:1047-1078`)
- **Beklenen:** Tablo 4 sütun — Planlanan · Fiili · Δ; en altta **Остаток**
  farkı. Kassa satırları hesap bazında tek tek listelenir
  (`BidPricing.vue:258-259`).
- **Kırık belirtisi:** Fiili hasılat 0 iken sistem plandaki teklif fiyatını fiili
  yerine koyuyor (`tender.py:1190`: `actual_revenue or planned_pnl["bid_price"]`)
  → henüz hiç fatura kesilmemiş bir lotta "fiili marj = planlanan marj" görünür.
  Ekran bunu yalnız küçük gri "actual so far" notuyla söylüyor
  (`BidPricing.vue:251`).

---

## 11. İZLEME EKRANLARI

### SEN-23 · Süreç akışı — nerede tıkandık

- **Ekran:** `https://mikas.erpstable.com/stabler#/tender/flow`
- **Uç nokta:** `tender.tender_flow`
- **Beklenen (demo veri, seed günü):**

| Adım | Açık | Ort. bekleme | En kötü | Eşik | Durum |
|---|---|---|---|---|---|
| Intake — file opened (`seen`) | 2 | 2,0 gün | 3 | 3 | **edge** (sınırda) |
| GO / NO-GO (`go`) | 2 | 4,5 gün | 5 | 5 | **edge** |
| Quotation gathering (`sourcing`) | 2 | 22,5 gün | 26 | 14 | **out** |
| Bid pricing (`priced`) | 2 | 7,0 gün | 8 | 3 | **out** |
| Bid submitted (`submitted`) | 2 | — | — | 30 | **unknown** (2 damgasız) |

- **Darboğaz = `priced`** — mutlak fark değil **oran** kullanılıyor: 7/3 = 2,33
  vs sourcing 22,5/14 = 1,61 (`_tender_flow.py:79-93`).
- **KPI şeridi:** In process **10** · Over SLA **2** · Bottleneck **Bid pricing** ·
  Not measurable **2**.
- **"edge" eşiği:** son çeyrek, ama en az 1 gün —
  `avg >= limit − max(1, limit//4)` (`_tender_flow.py:74`). 3 günlük eşikte
  `3 − max(1, 0) = 2`, yani 2 günde uyarı başlar.
- **Kırık belirtisi:** "Not measurable" satırı 0 gösteriyorsa damgasız kayıtlar
  ortalamaya 0 gün olarak katılmış demektir — bu, tıkanmış bir adımı sağlıklı
  gösterir (`_tender_sla.py:58-71` bunu açıkça yasaklıyor).
- **Rol notu:** Menüde yalnız `director` görüyor (TenderNav.vue:40) ama
  **uç noktada rol kapısı yok** (`tender.py:3015`) — URL'yi bilen her tender
  kullanıcısı açabilir.
- **Kanıt:** `_tender_flow.py:24-93`, `_tender_sla.py:30-38`, `tender.py:3002-3077`.

### SEN-24 · Huni ve "nerede kaybediyoruz"

- **Ekran:** `#/tender/portfolio` içine gömülü `TenderFunnel.vue`
- **Uç nokta:** `tender.tender_funnel` (varsayılan pencere **90 gün**, 7-366
  arası sıkıştırılıyor — `tender.py:2185`)
- **Tek-aşama kuralı:** Bir lot **tam olarak bir** kutuda sayılır. Öncelik:
  `result > submitted > priced > sourcing > go > seen` (`_funnel.py:34-52`).
  `lost` huni sayımında `submitted` seviyesine denk (`_funnel.py:55-67`) —
  yani kaybedilen bir teklif "katıldı" sayılır ama "kazandı" sayılmaz.
- **Beklenen (demo veri) — DİKKAT, CRM panosuyla UYUŞMUYOR:**

| Aşama | Huni (`tender_funnel`) | Tender CRM / Süreç akışı |
|---|---|---|
| seen | 2 | 2 |
| go | **4** | **2** |
| sourcing | **0** | **2** |
| priced | 2 | 2 |
| submitted | 2 | 2 |
| won / lost | 2 / 1 | 2 / 1 |

Sebep: `tender_funnel` **kaydedilmiş aşamayı hiç okumuyor**, yalnız olgulardan
türetiyor (`tender.py:2210-2218`); `crm_board` ve `tender_flow` ise
`kaydedilmiş or türetilmiş` diyor (`tender.py:2373`, `tender.py:3046-3047`).
Demo veride 4308/4309 için SQ kaydı olmadığından huni onları "go"da sayıyor.
Bkz. **KOP-02**.

- **Politika boşluğu rozeti:** `sourcing` aşamasındaki lotlarda `sq_count < 5` ise
  "N below policy" (`tender.py:2232-2233`). Huni 4308/4309'u sourcing'e
  koymadığı için **demo veride bu rozet çıkmaz**, ama operasyon masasında aynı
  iki lot için uyarı çıkar (SEN-08). İki ekran aynı politikayı farklı sayıyor.
- **Kanıt:** `_funnel.py:34-118`, `tender.py:2169-2285`, `TenderFunnel.vue:89-137`.

### SEN-25 · Direktör panosu — portföyün parası

- **Ekran:** `#/tender/portfolio`
- **Uç nokta:** `tender.tender_director_board`
- **6 sayaç:** Aktif ihale · Kazanma oranı · Risk · Portföy değeri · Ortalama marj
  · Остаток.
- **Beklenen (demo veri):** Aktif **13** · Win rate **%66.7** · Risk **1**
  (UTY-2026-4305, teklif son tarihi dün geçmiş).
- **Kırık belirtisi (KRİTİK):** Portföy değeri **0**, ortalama marj **%0**,
  Остаток **0** çıkar. Sebep: değer `SO hasılatı` ya da hesaplanan `bid_price`'tan
  geliyor (`tender.py:1917`); demo veride SO da PO da yok, `landed_goods=0`
  olduğu için `_compute_bid_pnl` `bid_price=0` döndürüyor. Aynı lotların
  `#/tender/crm` kartlarında **14,15 mlrd UZS** yazıyor (intake `contract_value`,
  `tender.py:2383`). **Aynı portföy, iki ekranda iki farklı para.** Bkz. **KOP-08**.
- **Sıralama:** risk (risk > warn > good > none) → teslim tarihi → deal adı
  (`tender.py:1962-1968`).
- **Kanıt:** `tender.py:1884-1970`, `DirectorBoard.vue:77-112`.

### SEN-26 · Operasyon masası — "bugün ne yapmalıyım"

- **Ekran:** `https://mikas.erpstable.com/stabler#/tender/desk`
- **Uç nokta:** `tender_desk.operations_desk`
- **Kim:** herhangi bir tender görünümü; rol seçici birden çok görünümü olanda
  çıkar (`OperationsDesk.vue:21-32`).
- **Kural motorunun ürettiği 6 kalem tipi (`_desk_rules.py`):**
  `bid_due` (son tarih geçti/bugün) · `bid_soon` (≤3 gün) · `policy_gap`
  (sourcing + <5 teklif) · `no_parent` (üst ihalesi olmayan lot) ·
  `won_no_po` (kazanıldı, PO açılmamış) · `po_late` (PO gecikmiş) ·
  `invoice_due` · `approval_pending`.
- **Beklenen (demo veri):** **Tam 2 kalem** — 4308 ve 4309 için "Missing supplier
  quotes".
- **Kırık belirtisi (KRİTİK):** 4305'in teklif son tarihi **dün geçmiş**,
  4308'inki **bugün** — ama masada "Bid due" kalemi **çıkmıyor.** Masa son
  tarihleri `CRM Deal.custom_bid_deadline` / `bid_deadline` / `expected_closing`
  **kolonlarından** okuyor (`tender_desk.py:83`), oysa tender modülünün tek
  gerçek kaynağı `custom_tender_intake` JSON'u. Aynı şekilde `won_no_po`
  `custom_tender_result` kolonuna bakıyor (`tender_desk.py:85`) ve o kolon hiçbir
  zaman yazılmıyor → **kazanılmış iki lot (4314, 4315) için "PO açılmadı" uyarısı
  hiç çıkmaz.** Bkz. **KOP-01**.
- **Takım yükü:** yalnız oversight görür; `open_lots` / `overdue_lots` /
  `won_lots` aynı hatalı kolonlardan türediği için demo veride herkesin
  `open_lots` sayısı 13, `won_lots` 0 çıkar (`tender_desk.py:258-277`).
- **Kanıt:** `tender_desk.py:55-87, 195-221`, `_desk_rules.py:42-153`.

---

## 12. İş sorularına kodun verdiği cevaplar

### S1. Bir lotu bir aşamadan diğerine taşıdığımda geçmiş kaydediliyor mu?

**Kısmen — evet ama tek bir yoldan ve sessizce başarısız olabiliyor.**

- `move_deal_stage` (yani kanban sürüklemesi) her **gerçek** aşama değişiminde
  bir `CRM Stage Event` yazıyor: `axis="tender_stage"`, `from_tender_stage`,
  `to_tender_stage`, `changed_at`, `changed_by` (`tender.py:2413-2447`).
- Aynı kulvara geri bırakmak sayacı **sıfırlamıyor** — `previous != stage`
  kontrolü var (`tender.py:2484`); gerekçesi kodda yazılı: "bekleyen işi genç
  göstermek, en çok bakılması gereken anlaşmayı en az dikkat çeker hâle getirir".
- Damga (`custom_tender_stage_entered_at`) ve olay kaydı **aynı `moved_at`
  değerini** paylaşıyor (`tender.py:2474`).
- **CRM statü ekseni ayrı:** `crm.py:461-489` `axis="status"` ile
  `from_stage`/`to_stage` alanlarına yazıyor. **İki eksen aynı log tablosunda ama
  farklı sütunlarda** — `crm.py:475-477`'de bu bilinçli olarak açıklanmış.
  Yani tender aşama geçmişini sorgularken `axis='tender_stage'` filtresi
  ZORUNLU.

**Kaydedilmeyen geçmiş:**
- Olay yazımı **yutulabilir bir hata**: `except Exception` → `frappe.log_error`
  (`tender.py:2443-2447`). Aşama yine de değişir, geçmiş kaybolur. Error Log'a
  düşer ama kullanıcı hiçbir şey görmez.
- `custom_tender_stage` kolonu yoksa **hiçbir şey kaydedilmez** — olay yazımı
  `if frappe.db.has_column(...)` bloğunun içinde (`tender.py:2476-2493`).
- **Künyeden yapılan aşama değişiklikleri (`save_deal_intake`) hiç olay
  üretmiyor.** GO kararını "Tender details" formundan verirseniz `CRM Stage Event`
  yazılmaz; yalnız `go_no_go_at`/`go_no_go_by` damgası kalır.
- **Sales Order kulvar hareketleri hiç kaydedilmiyor:** `move_so_stage` sadece
  `custom_board_stage` alanını `db.set_value` ile eziyor (`tender.py:162`) —
  sözleşmenin "Procurement'ta kaç gün beklediği" sorusunun cevabı sistemde yok.
- Demo seed geçmişi taklit ediyor: her lot için `seen → … → mevcut aşama`
  zincirini `CRM Stage Event` olarak yazıyor (`seed_tender_demo.py:211-248`).
  Ama `unseed()` bu olayları **doğrudan SQL ile siliyor**
  (`seed_tender_demo.py:262-264`) çünkü doctype `on_trash` ile değişmezliği
  koruyor.

### S2. Aşama eşikleri (SLA) nerede uygulanıyor, nerede uygulanMIYOR?

**Uygulandığı tek yer: `#/tender/flow` (Süreç akışı) ekranı.**

| Yer | SLA uygulanıyor mu | Kanıt |
|---|---|---|
| `#/tender/flow` adım tablosu (avg/worst/state/bottleneck) | **EVET** | `tender.py:3067-3077`, `_tender_flow.py:24-93` |
| `_tender_sla.severity()` (crit/today/soon/info dili) | Tanımlı ama **hiçbir yerden çağrılmıyor** | `_tender_sla.py:105-124` |
| `_tender_sla.overdue_by()` | Tanımlı ama **çağrılmıyor** | `_tender_sla.py:89-102` |
| `#/tender/crm` kartları | **HAYIR** — "risk" son tarih milestone'undan, aşama yaşından değil | `tender.py:2379-2381` |
| `#/tender/portfolio` "Risk" sayacı | **HAYIR** — `_deal_deadlines` (teklif/teslim tarihleri) | `tender.py:1921-1922` |
| `#/tender/desk` günlük plan | **HAYIR** — yalnız teklif son tarihi ve PO gecikmesi | `_desk_rules.py:56-114` |
| Huni "urgent" rozeti | **HAYIR** — `_deal_deadlines(...)["risk"] == "risk"` | `tender.py:2230-2231` |
| Gümrük / lojistik kuyrukları | **HAYIR** — PO `schedule_date`'e 7 gün sabit eşik | `tender.py:2036-2040` |
| Bildirim / e-posta / görev üretimi | **HİÇ YOK** | — |

**Sonuç:** SLA aşımı **hiçbir kişiyi uyarmıyor, hiçbir iş kalemi üretmiyor.**
Yalnız bir kişi `#/tender/flow` ekranını açarsa görünür. `priced` adımının
eşiği iki katına çıkmış olsa bile ne operasyon masasında bir satır belirir, ne
lotun sahibi bilgilendirilir.

**UAT doğrulaması:** `Stabler Settings` üzerinden `sourcing` eşiğini 5'e düşürün
(`stage_sla_for`). `#/tender/flow` tablosunda eşik değişir; başka **hiçbir
ekranda** hiçbir şey değişmez.

### S3. Bir teklifin belge hazırlığı (evrak seti) nasıl ölçülüyor, eksik evrak nerede görünüyor?

**İki ayrı, birbirini tanımayan ölçüm var.**

**Ölçüm A — backend'in resmî ölçümü (`_docs_summary`, `tender.py:1478-1486`):**
- Şema: `{label, required, done, date}` (`_clean_intake`, `tender.py:1415-1424`)
- `required` = zorunlu evrak sayısı, `done_required` = tamamlanan,
  `missing[]` = eksiklerin adları.
- Görüldüğü yerler:
  - `#/tender/po-control` → "Documents n/m" rozeti (`TenderIntake.vue:144-146`)
  - `tender_dashboard` → `attention` kuyruğunda `kind="documents"` kalemi,
    yalnız `go_no_go == "go"` ise (`tender.py:2597-2599`)
  - `_has_ready_evidence` → "hazır" sayılması için üç şart birden: GO kararı +
    eksik evrak yok + `ready_at`/`ready_by` sunucu damgası (`tender.py:2564-2571`)

**Ölçüm B — Tender CRM kartındaki `doc_progress` (`tender.py:2387-2388`):**
- Şema: `{status: "ready"}` — **tamamen farklı alan adı.**
- Formül: `hazır sayısı / toplam × 100`; belge hiç yoksa **%50** varsayılıyor
  (evet, sabit 50).
- Kartlardaki yüzde çubuğu ve "Readiness" KPI filtresi
  (`TenderCrm.vue:61`, `374-378`) bunu kullanıyor.

**Çakışma:** `TenderIntake.vue` **A şemasında** yazıyor
(`TenderIntake.vue:66-68, 94`), demo seed **B şemasında** yazıyor
(`seed_tender_demo.py:134-139`). Sonuç:

| Kaynak | CRM kartı `doc_progress` | PO-control "Documents n/m" |
|---|---|---|
| Demo veri (B şeması) | **%25-100 arası doğru** | **hiç rozet yok** (required = 0) |
| UI'dan kaydedilmiş (A şeması) | **her zaman %0** | **doğru** |

Yani hangi ekranın doğru söylediği, künyeyi kimin yazdığına bağlı.

**Standart evrak seti** (`TenderIntake.vue:91`, "Standard set" düğmesi):
Shartnoma · Protokol · Muvofiqlik sertifikati · **ГТД** · Qabul dalolatnomasi ·
Hisob-faktura.

**Eksik evrakın görünmediği yerler:** Direktör panosu, huni, operasyon masasının
günlük plan listesi, gümrük kuyruğu. `tender_dashboard`'ın `attention` kuyruğu
tek merkezi görünüm ve o da `#/tender/desk` ekranında **kullanılmıyor** (masa
`tender_desk.operations_desk` çağırıyor, `tender.tender_dashboard` değil).

### S4. Kazanılan bir ihale sözleşmeye/siparişe nasıl dönüşüyor — otomatik mi, elle mi, hiç mi?

**Cevap: TAMAMEN ELLE — ve elle yapmanın da SPA'da bir düğmesi yok.**

Kanıtlar:
1. `api/tender.py` **hiçbir yerde** `Sales Order`, `Purchase Order`,
   `Supplier Quotation` ya da `Customs Declaration` üretmiyor. Dosyadaki tek
   `new_doc`/`insert` çağrıları `Stabler SO Stage` (satır 63-72) ve
   `CRM Stage Event` (satır 2428-2442).
2. `move_deal_stage` kartı "Won"a taşıdığında **yalnız** `intake["result"]="won"`
   yazıyor (`tender.py:2498-2499`). Ne müşteri, ne sözleşme, ne görev.
3. CRM tarafındaki kazanma otomasyonu (`_maybe_convert_won_deal`, `crm.py:506-513`)
   bir **Customer** yaratıyor — sipariş değil — ve yalnız `transition_deal`
   yolundan tetikleniyor (`crm.py:681`); tender kanbanı onu çağırmıyor.
4. `SalesOrderForm.vue` lot bağını yalnız `?crm_deal=` URL parametresinden
   alıyor (`SalesOrderForm.vue:731`) ve **hiçbir tender ekranı bu bağlantıyı
   üretmiyor** (tüm `.vue` dosyalarında `orders/new` bağlantısı: 0 adet).
5. Tek "hatırlatma" mekanizması `_desk_rules` içindeki `won_no_po` kuralı
   (`_desk_rules.py:132-153`) — o da `custom_tender_result` kolonuna bakıyor,
   tender modülü ise `custom_tender_intake` JSON'una yazıyor → **kural hiç
   ateşlenmiyor**.

**Pratik sonuç:** Kazanılan lot ile sözleşme arasındaki bağ, kullanıcının
adres çubuğuna elle `?crm_deal=CRM-DEAL-2026-000xx` yazmasına bağlı. Yazmazsa
lot ile SO arasında hiçbir bağ kurulmaz ve PO kontrol panosu, gümrük kuyruğu,
lojistik panosu, finans sekmesi, plan-fiili karşılaştırması — **hepsi boş kalır.**

### S5. Aynı lota birden fazla tedarikçiden fiyat geldiğinde karşılaştırma nerede?

**Üç ayrı yerde, üç farklı derinlikte:**

| Yer | Ne gösteriyor | Uç nokta |
|---|---|---|
| `#/tender/sourcing?deal=…` | **Tam tablo:** tedarikçi, ülke, tutar, baz tutar, geçerlilik, durum, `cheapest` rozeti + 5/2 politika rozetleri | `purchasing.tender_quotations` |
| `#/tender/crm` → kart çekmecesi → "Sourcing Summary" | Kısa tablo: tedarikçi, ülke, tutar, cheapest | `purchasing.tender_quotations` |
| `#/tender/po-control?deal=…&tab=vendor-po` üst kart | **Yalnız tedarikçi adları** rozet olarak — fiyat YOK | `tender_workspace.sourcing` |

**Sipariş sonrası karşılaştırma ayrı ve daha güçlü:** aynı sayfadaki
"Vendor comparison (landed)" tablosu (`tender.py:619-648`), tedarikçileri
**varış maliyetine (landed)** göre sıralıyor ve her tedarikçinin PO toplamını
kendi verdiği SQ toplamıyla karşılaştırıp `delta_pct` (sapma %) üretiyor.

**Boşluklar:**
- "En ucuz" seçimi **kaydedilmiyor.** Tabloda tıklayınca `selectedVendor`
  işaretleniyor ama bu yalnız tarayıcı hafızasında
  (`PoControlBoard.vue:428`) — sunucuya gitmiyor, "neden bu tedarikçi seçildi"
  kararının kaydı yok.
- Teklifler **kalem/pozisyon bazında karşılaştırılamıyor** — yalnız belge
  toplamları. Çok kalemli bir lotta hangi tedarikçinin hangi kalemde ucuz
  olduğu görülemiyor.
- Politika (5 teklif / 2 ülke) **hiçbir yerde zorlayıcı değil**: sağlanmadan da
  fiyatlandırma yapılabilir, teklif "submitted"a taşınabilir, PO açılabilir.
  Yalnız sarı rozet ve operasyon masasında bir uyarı satırı çıkar.

---

## 13. İş akışı kopuklukları

> Her madde: **belirti → sebep → kanıt (dosya:satır) → iş sonucu**

### KOP-01 · Operasyon masası, tender künyesini hiç okumuyor (P0)

- **Belirti:** Demo veride teklif son tarihi dün geçmiş (4305) ve bugün olan
  (4308) lotlar için masada **hiçbir uyarı yok**; kazanılmış iki lot için "PO
  açılmadı" uyarısı yok.
- **Sebep:** `tender_desk.operations_desk` son tarihi `custom_bid_deadline` /
  `bid_deadline` / `expected_closing` **kolonlarından**, sonucu
  `custom_tender_result` / `status` kolonundan okuyor. Tender modülünün tek
  yazdığı yer ise `CRM Deal.custom_tender_intake` **JSON alanı**.
- **Kanıt:** `tender_desk.py:55-87` (okunan alan listesi),
  `tender_desk.py:202-207` (fact haritalama), `tender.py:1634-1636` (yazılan yer).
- **İş sonucu:** "Bugün ne yapmalıyım" ekranı, ihale son tarihlerini bilmiyor.
  Süresi geçen teklifin tek görünür olduğu yer `#/tender/portfolio`'nun "Risk"
  sayacı.

### KOP-02 · Huni, kaydedilmiş aşamayı yok sayıyor (P0)

- **Belirti:** Direktör panosundaki huni `go=4, sourcing=0` derken, Tender CRM
  kanbanı ve Süreç akışı `go=2, sourcing=2` diyor.
- **Sebep:** `tender_funnel` yalnız `_funnel.classify` kullanıyor;
  `crm_board` ve `tender_flow` ise `custom_tender_stage or classify`.
- **Kanıt:** `tender.py:2210-2218` (funnel), `tender.py:2365-2373` (crm_board),
  `tender.py:3046-3057` (flow).
- **İş sonucu:** Kullanıcı bir kartı elle "Sourcing"e taşıdığında huni onu
  görmez; iki ekran aynı portföy için farklı sayı gösterir ve "nerede
  kaybediyoruz" analizi yanlış aşamayı işaret eder.

### KOP-03 · Kanban kartlarında son tarih hiç görünmüyor (P1)

- **Belirti:** `#/tender/crm` kartlarında ve liste görünümünün "Deadline Risk"
  sütununda **hep boş / "—"**, oysa "Deadline" KPI sayacı 1 gösteriyor.
- **Sebep:** `crm_board` `deadline_info.get("deadline")` okuyor;
  `_deal_deadlines` yalnız `{milestones, risk, today}` döndürüyor — `deadline`
  diye bir anahtar yok.
- **Kanıt:** `tender.py:2379-2380` (okuma), `tender.py:1604` (dönüş sözleşmesi),
  `TenderCrm.vue:362`, `TenderCrm.vue:430`.
- **İş sonucu:** Sürüklenip bırakılan bir panoda **en kritik bilgi olan son
  tarih** hiç görünmüyor; kullanıcı hangi kartın acil olduğunu ancak KPI sayısına
  bakıp tahmin ediyor.

### KOP-04 · Künyeyi kaydetmek lot tutarını siliyor (P0)

- **Belirti:** Demo lotu açıp künyeye tek bir not ekleyip kaydedince, o lotun
  Tender CRM kartındaki tutar 0'a düşüyor. Aynı şey **atama** yapıldığında da
  oluyor.
- **Sebep:** `_clean_intake` yalnız beyaz listedeki alanları koruyor;
  `contract_value` ne `_INTAKE_KEYS_STR` ne `_INTAKE_KEYS_NUM` içinde. Yine de
  `crm_board` kart değerini oradan okuyor.
- **Kanıt:** `tender.py:1344-1365` (beyaz liste), `tender.py:1379-1381`
  (yeniden inşa), `tender.py:2383` (okuma), `tender.py:1799` (assign_tender de
  aynı fonksiyonu çağırıyor).
- **İş sonucu:** Portföy değeri, lot dokunuldukça sessizce erimeye başlar.

### KOP-05 · Evrak seti iki farklı şemada (P0)

- **Belirti:** Aynı lot bir ekranda "%100 hazır", diğerinde "zorunlu evrak yok".
- **Sebep:** `{label, required, done}` (backend/UI) vs `{name, status}` (seed).
  `_clean_intake` etiketi olmayan satırları **tamamen atıyor**
  (`tender.py:1422-1423`), yani demo verisi ilk kayıtta yok oluyor.
- **Kanıt:** `tender.py:1415-1424`, `tender.py:1478-1486`, `tender.py:2387-2388`,
  `seed_tender_demo.py:134-139`.
- **İş sonucu:** "Evrakımız tam mı" sorusunun tek bir doğru cevabı yok.

### KOP-06 · Teklif verildi damgası UI'dan üretilemiyor (P0)

- **Belirti:** Kanbandan "Submitted"a taşınan lot, Direktör panosunda
  "Unverified" kalıyor; kazanma oranına ve gösterge paneline hiç yansımıyor.
- **Sebep:** Katılım kanıtı `submitted_at` **VE** `submitted_by` gerektiriyor;
  ikisini birlikte yazan tek fonksiyon `mark_tender_submitted` ve o
  **hiçbir ekrandan çağrılmıyor**. `move_deal_stage` yalnız `submitted_at`
  yazıyor.
- **Kanıt:** `tender.py:1648-1685` (tek doğru yazıcı), `tender.py:2503` (eksik
  yazım), `tender.py:2559-2561` (kanıt kuralı). Frontend'de
  `mark_tender_submitted` çağrısı: **0 adet**.
- **İş sonucu:** Kazanma oranı, katılım sayısı, aylık trend — üçü de sıfır
  kalır. Sistemin en çok bakılan yönetim rakamı üretilemiyor.

### KOP-07 · SQ / SO / PO lota bağlanamıyor (P0)

- **Belirti:** Tedarik, sipariş, gümrük ve lojistik ekranları çoğu kurulumda boş.
- **Sebep:** Üç doctype de `custom_crm_deal` alanı ile lota bağlanıyor; bu alanı
  yazan **hiçbir SPA ekranı yok** (Sales Order formundaki gizli URL parametresi
  hariç). PO ve SQ formlarında lot seçici bulunmuyor.
- **Kanıt:** `tender.py:518` (PO filtresi), `tender.py:605-611` (SQ filtresi),
  `tender.py:1554-1557` (SO filtresi); frontend'de `custom_crm_deal` yazan çağrı
  yok (yalnız `SalesOrderForm.vue:264` `crm_deal` alanını payload'a koyuyor,
  onun kaynağı da URL).
- **İş sonucu:** Modülün "yürütme" yarısına veri girmenin tek yolu ERPNext
  masaüstü.

### KOP-08 · Aynı lot iki panoda iki farklı tutar (P1)

- **Belirti:** Tender CRM 14,15 mlrd UZS portföy toplamı gösterirken Direktör
  panosu 0 gösteriyor.
- **Sebep:** CRM kartı `intake.contract_value`'yu, Direktör panosu
  `SO hasılatı or hesaplanan bid_price`'ı okuyor.
- **Kanıt:** `tender.py:2383` vs `tender.py:1917`.
- **İş sonucu:** "Portföyümüzde ne kadar iş var" sorusuna hangi ekrana
  baktığınıza göre iki farklı cevap.

### KOP-09 · Sözleşme kulvar hareketleri geçmişsiz (P1)

- **Belirti:** "Bu sözleşme Procurement aşamasında kaç gün bekledi" sorusunun
  cevabı yok.
- **Sebep:** `move_so_stage` yalnız `custom_board_stage`'i eziyor; ne damga, ne
  olay kaydı.
- **Kanıt:** `tender.py:151-164` (karşılaştırın: `move_deal_stage`,
  `tender.py:2474-2493`).
- **İş sonucu:** Süreç akışı ekranı teklif aşamalarını ölçüyor ama **yürütme
  aşamalarını hiç ölçmüyor** — sözleşme sonrası tıkanma görünmez.

### KOP-10 · Gümrük yalnız "planlanmış tutar" olarak var (P1)

- **Belirti:** Beyanname numarası, tarihi, çıkış izni sistemde yok; "gümrükte
  işlem var" demek, birinin plana tutar yazmış olması demek.
- **Sebep:** Kodun kendi notu: "No native PO-level customs clearance field exists
  in this install... **not clearance**".
- **Kanıt:** `tender.py:2810-2817`, `tender.py:2032-2035` (durum türetimi).
  İmports modülünde `Customs Declaration` doctype'ı var (`router.js:229-231`)
  ama tender akışıyla bağı yok.
- **İş sonucu:** Gümrük gecikmesi ile "kimse plana tutar yazmamış" durumu ayırt
  edilemiyor.

### KOP-11 · "Teslim" iki farklı şey (P1)

- **Belirti:** Lojistik panosu "Delivered" derken kastettiği tedarikçiden mal
  girişi; müşteriye teslim başka ekranda, başka çubukta.
- **Kanıt:** `tender.py:2100` (`delivered` = PO `per_received>=100`) vs
  `SalesOrderBoard.vue:185-186` (SO `per_delivered`).
- **İş sonucu:** Lojistikçi "teslim edildi" der, ihale uzmanı müşteriye teslim
  anlar; ceza (`penalty_pct_per_day`) hesabı yanlış tarihten başlatılabilir.

### KOP-12 · Süreç akışı ekranı menüde kapalı, uç noktada açık (P2)

- **Belirti:** `#/tender/flow` menüde yalnız `director` görüyor, ama URL'yi bilen
  her tender kullanıcısı açabiliyor.
- **Kanıt:** `TenderNav.vue:40` (menü kapısı) vs `tender.py:3015`
  (`_require_tender` — rol görünümü kontrolü yok).
- **Not:** Aynı durum `crm_board` (`tender.py:2305`) ve `so_board`
  (`tender.py:89`) için de geçerli — bunlarda görünüm kapısı yok.

### KOP-13 · Ölü / bağlantısız ekranlar (P2)

- `TenderExecutionFlow.vue` — hiçbir yerden import edilmiyor (SPA'da 0 kullanım);
  ayrıca `tender-portfolio` rotasına `status=won` sorgusu gönderiyor, oysa
  `filterTenderRows` `status` filtresini `row.status` ile karşılaştırıyor ve
  Direktör panosu satırları `status` alanını `_tender_filter_evidence` üzerinden
  ("" ya da "unverified_history") dolduruyor.
- `#/tender/director` → `/dashboard`'a yönleniyor (`router.js:272`); eski
  yer imleri kullanıcıyı panoya atar, sessizce.
- `so_stage_reorder` uç noktası (`tender.py:210-221`) hiçbir ekrandan
  çağrılmıyor — kulvar sırası yalnız yeni kulvar eklerken verilen `position`
  ile belirleniyor.

---

## 14. Bir ihale uzmanının bu sistemde YAPAMADIĞI şeyler

1. **Yeni bir lot açamaz.** Tender modülünde "Yeni ihale/lot" düğmesi yok; lot
   bir `CRM Deal` ve `#/crm/deals` üzerinden açılıyor. Tender ekranları yalnız
   var olanı okuyor.
2. **"Teklifi verdim" diyemez.** Katılımı kanıtlayan tek fonksiyon
   (`mark_tender_submitted`, portal referans numarasıyla birlikte) arayüze
   bağlanmamış. Kanbandan sürükleme yarım kayıt üretiyor (KOP-06).
3. **Kazandığı ihaleyi tek tıkla sözleşmeye çeviremez.** Ne "Sözleşme oluştur"
   düğmesi var, ne otomasyon. Bağı kurmanın tek yolu adres çubuğuna elle
   `?crm_deal=…` yazmak (S4).
4. **Tedarikçi teklifini (SQ) sisteme tender ekranından giremez.** SQ'yu lota
   bağlayan alanı yazan bir ekran yok; ERPNext masaüstü gerekiyor (KOP-07).
5. **Tedarikçi siparişini (PO) lota bağlayamaz.** Aynı sebep; PO formunda lot
   seçici yok.
6. **"Bu tedarikçiyi seçtim, çünkü…" kararını kaydedemez.** Karşılaştırma
   tablosundaki seçim yalnız tarayıcıda; gerekçe alanı, onay adımı, kayıt yok.
7. **Kalem bazında teklif karşılaştıramaz.** Yalnız belge toplamları
   karşılaştırılıyor.
8. **5 teklif / 2 ülke politikasını zorunlu kılamaz.** Politika sağlanmadan
   fiyatlandırma, teklif ve sipariş serbest; yalnız sarı rozet çıkıyor.
9. **SLA aşımından haberdar olamaz.** Ne bildirim, ne e-posta, ne görev, ne de
   operasyon masasında satır. Yalnız `#/tender/flow` ekranını açan görür (S2).
10. **Teklif son tarihi yaklaşan lotu günlük iş listesinde göremez.** Operasyon
    masası künye JSON'unu okumadığı için son tarih uyarıları hiç üretilmiyor
    (KOP-01).
11. **Gümrük beyannamesini (ГТД) sisteme giremez.** Beyanname no/tarih/çıkış
    izni için alan yok; gümrük durumu planlanmış tutardan tahmin ediliyor
    (KOP-10).
12. **Teklifini portala gönderemez.** E-IMZO imzası ve yükleme sistem dışında,
    elle (`tender.py:1234-1235`). Sistem yalnız `.docx` paketi üretiyor.
13. **Garanti (kafolat) hareketini takip edemez.** `guarantee_amount` ve
    `guarantee_return` yalnız künyede metin/sayı; ne banka teminat mektubu
    kaydı, ne bloke/iade muhasebe hareketi. Milestone "iade edildi" sayılması
    tamamen türetme: teslim tamamlandı **veya** ihale kaybedildi
    (`tender.py:1591-1595`).
14. **Ceza (penalty) hesaplayamaz.** `penalty_pct_per_day` künyede saklanıyor
    ama hiçbir hesaplamada kullanılmıyor — kod tabanında tek geçtiği yerler
    alan tanımı ve form girdisi.
15. **Sözleşme yürütmesinde nerede tıkandığını ölçemez.** Sözleşme panosu kulvar
    geçmişi tutmuyor (KOP-09); süreç akışı yalnız teklif öncesi 5 adımı ölçüyor
    (`_tender_flow.py:21`).
16. **Aynı ihalenin birden çok lotunu bir arada yönetemez** (bu pakette):
    `tender_master` uç noktası CRM çekmecesinden çağrılıyor
    (`TenderCrm.vue:194-197`) ama üst ihale kaydını yaratan/düzenleyen bir ekran
    rotalarda yok; `_desk_rules` "orphan lot" uyarısı da
    `custom_lot_no` + `custom_tender_master` kolonlarına bağlı ve tender modülü
    o kolonlara yazmıyor.
17. **Kaybedilen ihalenin sebebini kaydedemez.** `loss_reason` alanı CRM statü
    ekseninde var (`crm.py:453`, `486`) ama tender künyesinde yok; kanbandan
    "Lost"a sürüklemek hiçbir sebep sormuyor.
18. **Herhangi bir raporu dışa aktaramaz.** Tender ekranlarında tek bir Excel/CSV
    dışa aktarma düğmesi yok (`DrillReport` altyapısı var ama tender raporu
    tanımlanmamış — `router.js:246-262`).

---

## 15. Hızlı regresyon kontrol listesi (demo veri üzerinde beklenen sayılar)

`seed()` çalıştırıldıktan hemen sonra, düzeltme yapılmadan:

| Ekran | Alan | Beklenen (bugünkü kod) | Doğru olan |
|---|---|---|---|
| `#/tender/crm` | kulvar sayıları | 2·2·2·2·2·2·1 | ✔ |
| `#/tender/crm` | kart son tarihi | **hep boş** | ✘ KOP-03 |
| `#/tender/crm` | Pipeline tutarı | ~14,15 mlrd UZS | ✔ |
| `#/tender/portfolio` | Aktif ihale | 13 | ✔ |
| `#/tender/portfolio` | Win rate | %66,7 | ✔ |
| `#/tender/portfolio` | Risk | 1 (UTY-2026-4305) | ✔ |
| `#/tender/portfolio` | Portföy değeri / marj / Остаток | **0 · %0 · 0** | ✘ KOP-08 |
| `#/tender/portfolio` → huni | go / sourcing | **4 / 0** | ✘ KOP-02 |
| `#/tender/flow` | darboğaz | Bid pricing | ✔ |
| `#/tender/flow` | Over SLA | 2 adım (sourcing, priced) | ✔ |
| `#/tender/flow` | Not measurable | 2 | ✔ |
| `#/tender/desk` | plan kalemi sayısı | **2** (yalnız policy_gap) | ✘ KOP-01 |
| `#/tender/board` | kart sayısı | 0 | demo SO üretmiyor |
| `#/tender/customs` | satır sayısı | 0 | demo PO üretmiyor |
| `#/tender/logistics` | satır sayısı | 0 | demo PO üretmiyor |

**Temizlik:** `bench --site mikas.erpstable.com execute
stabler.maintenance.seed_tender_demo.unseed` — yalnız adında ` [DEMO]` geçen
kayıtları siler (`seed_tender_demo.py:251-278`).
