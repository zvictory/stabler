# UAT 04 — Ticari Direktör · kendi ekranlarının kabul testleri

**Kim test ediyor:** İhale portföyünün tamamından sorumlu ticari direktör. Karar
veren kişi. Aşağıdaki her senaryo, direktörün gün içinde gerçekten sorduğu bir
soruya karşılık gelir; test o sorunun ekranda **doğru sayıyla** cevaplanıp
cevaplanmadığını ölçer.

**Test sitesi / şirket:** `mikas.erpstable.com` · Company = `Mikas`
**Temel URL biçimi:** `https://mikas.erpstable.com/stabler#/tender/<ekran>`
(router hash modunda — `public/js/router.js:514`)

**Direktörün ekranları ve tam URL'leri** (`router.js:265-276`):

| Soru | Ekran | URL | Uç nokta |
|---|---|---|---|
| Portföyüm ne durumda? | DirectorBoard | `…/stabler#/tender/portfolio` | `tender.tender_director_board` + `tender.tender_funnel` |
| Süreç nerede tıkanıyor? | TenderFlow | `…/stabler#/tender/flow` | `tender.tender_flow` |
| Bugün ne var, kimin kararı bende? | OperationsDesk | `…/stabler#/tender/desk` | `tender_desk.operations_desk` |
| Hangi anlaşma nerede? | TenderCrm | `…/stabler#/tender/crm` | `tender.crm_board` |

**Rol matrisi** (`api/tender.py:1725-1731`, `1752`):

| Görünüm | Açan roller |
|---|---|
| `director` | System Manager · Stabler Admin · Sales Manager · **Stabler Tender Director** |
| `sourcing` | System Manager · Stabler Admin · Sales Manager · **Sales User** |
| Gözetim (`_OVERSIGHT_ROLES`) | System Manager · Stabler Admin · Sales Manager · Stabler Tender Director |

> **Rol seçimi kritik.** `Sales Manager` hem `director` hem `sourcing` görünümünü
> açar; `Stabler Tender Director` YALNIZ `director` açar. Rol kapısını sınayan
> senaryolar (D-13, D-16) **saf `Stabler Tender Director`** ile koşulmalıdır,
> aksi hâlde kapı test edilmiş olmaz. Sayı senaryolarında ikisi de eşdeğerdir
> (ikisi de `_is_tender_oversight` = True).

**Demo veri:**
```
bench --site mikas.erpstable.com execute stabler.maintenance.seed_tender_demo.seed
```
13 anlaşma: `4301 4302 4305 4306 4308 4309 4310 4311 4312 4313 4314 4315 4316`
(4303/4304/4307 bilerek yok). Kazanılan 2 (4314, 4315), kaybedilen 1 (4316),
süren 10. Her kayıtta ` [DEMO]` işareti var (`seed_tender_demo.py:43`).

---

## 0. Hesap tabanı — testten ÖNCE elle hesaplanan değerler

Bu bölümdeki sayılar demo verinin tanımından (`seed_tender_demo.py:51-71`) ve saf
kural modüllerinden (`_tender_sla.py`, `_tender_flow.py`, `_funnel.py`) elle
çıkarıldı. **Ekran bunlardan farklı gösterirse ekran kırıktır.**

### 0.1 · Aşama damgaları ve bekleme günleri

`N` = testin koşulduğu gün − seed'in çalıştırıldığı gün (aynı gün koşulursa N=0).
Damga `nowdate() − gün_önce_taşındı` olarak yazılıyor (`seed_tender_demo.py:196-201`),
bekleme `max(0, today − entered_at)` (`_tender_sla.py:58-71`) → her ölçülen değere
`N` eklenir.

| Lot | Aşama | Damga (gün önce) | N=0'da bekleme |
|---|---|---|---|
| 4301 | seen | 1 | 1 |
| 4302 | seen | 3 | 3 |
| 4305 | go | 4 | 4 |
| 4306 | go | 5 | 5 |
| 4308 | sourcing | 19 | 19 |
| 4309 | sourcing | 26 | 26 |
| 4310 | priced | 8 | 8 |
| 4311 | priced | 6 | 6 |
| 4312 | submitted | **damga YOK** | ölçülemiyor |
| 4313 | submitted | **damga YOK** | ölçülemiyor |
| 4314 / 4315 | won | 40 / 55 | akış tablosunda YOK (terminal) |
| 4316 | lost | 48 | akış tablosunda YOK (terminal) |

### 0.2 · Akış tablosunun elle hesabı (N=0)

Eşikler `_tender_sla.py:30-38`: seen 3 · go 5 · sourcing 14 · priced 3 · submitted 30.
Ortalama YALNIZ ölçülebilenlerden (`_tender_flow.py:39-41`).
Durum kuralı (`_tender_flow.py:56-76`): `ort > eşik` → **out**;
`ort ≥ eşik − max(1, eşik//4)` → **edge**; açık iş var + ortalama/eşik yok → **unknown**.

| Adım | Açık | Ölçülemeyen | Ortalama | Hesap | En kötü | Eşik | Kenar sınırı | Durum |
|---|---|---|---|---|---|---|---|---|
| seen | 2 | 0 | **2.0** | (1+3)/2 | 3 | 3 | 3−1 = **2** | 2.0 ≥ 2 → **edge** |
| go | 2 | 0 | **4.5** | (4+5)/2 | 5 | 5 | 5−1 = **4** | 4.5 ≥ 4 → **edge** |
| sourcing | 2 | 0 | **22.5** | (19+26)/2 | 26 | 14 | 14−3 = 11 | 22.5 > 14 → **out** |
| priced | 2 | 0 | **7.0** | (8+6)/2 | 8 | 3 | 3−1 = 2 | 7.0 > 3 → **out** |
| submitted | 2 | **2** | **—** | ölçülebilir yok | — | 30 | — | **unknown** |

**Darboğaz = ORAN ile** (`_tender_flow.py:79-93`; eşiği en çok aşan, farkla değil):

* sourcing: 22.5 / 14 = **1.607**
* priced: 7.0 / 3 = **2.333** ← **darboğaz `priced`**

Farkla hesaplansaydı sourcing kazanırdı (+8.5 gün vs +4.0 gün). Bu ayrım testin
çekirdeği: **darboğaz işareti `priced` satırında olmalı.**

`N > 0` için: seen N=2'de, go N=1'de de `out`a geçer; darboğaz `priced`te kalır
çünkü `(7+N)/3` her N için `(22.5+N)/14`ten büyüktür.

Ekran üstü KPI'lar (`TenderFlow.vue:76-115`): In process **10** · Over SLA
**2 steps** · Bottleneck **"Bid pricing"** · Not measurable **2**.

### 0.3 · Portföy panosunun elle hesabı

`won`/`lost` sayılması için intake'te **hem** `submitted_at` **hem** `submitted_by`
şart (`tender.py:2559-2561`); seed ikisini de yazıyor (`seed_tender_demo.py:144-150`).

| Sayaç | Hesap | Beklenen |
|---|---|---|
| Active tenders (`count`) | Görünen TÜM tender anlaşması, sonuçlananlar dâhil (`tender.py:1897`) | **13** |
| Result / win rate | `won / (won+lost) × 100` = 2/3 × 100, 1 hane yuvarlama (`tender.py:1958`) | **66.7 %** |
| — alt satır | `won` / `lost` / `pending` | **2 won / 1 lost · 0 pending** |
| Risk (`at_risk`) | `_deal_deadlines.risk == "risk"` olan lot sayısı | **1** (yalnız 4305) |
| Portfolio value | `so_revenue or bid_price` — SO yok, pricing JSON `unit_price` anahtarı hiçbir yerde okunmuyor | **0** (bkz. Sayı şüpheleri Ş-1) |
| Avg margin | `margin_on_revenue_pct` boş liste | **0 %** |
| Остаток | 0 | **0** |
| Unverified history | 0 → uyarı şeridi HİÇ çizilmez (`DirectorBoard.vue:159`) | **yok** |

Son tarih riski (`tender.py:1517-1545`, ofsetler `seed_tender_demo.py:75-85`):

| Risk | Lot(lar) | Neden |
|---|---|---|
| **risk** (At risk) | 4305 | teklif son tarihi −1 gün |
| **warn** (Deadline near) | 4308 (0 gün), 4311 (+6), 4310 (+2) | ≤ 7 gün |
| **good** (On track) | 4301, 4302, 4306, 4309, 4312, 4313 + 4314/4315/4316 (sonuçlandığı için `bid_done`) | — |

### 0.4 · Huni panelinin elle hesabı (aynı sayfada, DirectorBoard içine gömülü)

Huni damgayı DEĞİL, olguları kullanıyor (`_funnel.classify`, `tender.py:2210-2218`).
Demo **hiç Supplier Quotation belgesi yaratmıyor** → her lotta `sq_count = 0` →
`sourcing` aşaması hiç oluşmuyor:

| Aşama kutusu | Huni (classify) | Akış/CRM (damga) | Uyum |
|---|---|---|---|
| Under review (seen) | 2 | 2 | ✓ |
| GO — awaiting sourcing | **4** | 2 | ✗ |
| Collecting quotations | **0** | 2 | ✗ |
| Priced | 2 | 2 | ✓ |
| Submitted | 2 | 2 | ✓ |
| Won / Lost | 2 / 1 | 2 / 1 | ✓ |

Huni basamakları (`_funnel.summarise`, `rank`): Lots seen **13** → GO decision **11**
→ Sourcing started **7** → Bid submitted **5** → Won **2**.
Dönüşümler: 85 % · 64 % · 71 % · 40 %. Düşüşler: **−4 sourcing · −3 won · −2 go · −2 submitted**.
Open pipeline **10** · Risk **1** · Execution **0** · Win rate **66.7 %**.

---

## 1. "Portföyüm ne durumda?" → `/tender/portfolio`

### D-01 · Altı sayacın altısı da demo veriyle uyuşuyor

- **Ön koşul:** Rol `Stabler Tender Director` (veya `Sales Manager`), şirket `Mikas`,
  demo veri yüklü, `https://mikas.erpstable.com/stabler#/tender/portfolio`
- **Adımlar:**
  1. Sayfayı aç, iskelet satırların kaybolmasını bekle.
  2. Üstteki 6 kartlı KPI şeridini (3 sütun × 2 satır) sırayla oku.
  3. Her kartın en alt satırındaki kuralı (`ds-kpi-q`) not al.
- **Beklenen:**
  - **Active tenders = 13** · alt kural `tender_lot · result = null`
  - **Result = 66.7 %** · not satırı `2 won / 1 lost · 0 pending`
  - **Risk = 1** · alt kural `deadline < 48h · act_now`
  - **Portfolio value = 0** (şirket varsayılan para birimiyle biçimli)
  - **Avg margin = 0 %**
  - **Остаток = 0**
  - Sarı "unverified history" şeridi **çizilmez**.
- **Kırık belirtisi:** Win rate 66,7 dışında bir şey (örn. 15.4 % = 2/13 hesabı, ya da
  66 %/67 % = yuvarlama kaybı); Active tenders 10 yerine 13 değil de başka bir sayı;
  Result kartı `—` gösteriyor (o zaman `submitted_at`/`submitted_by` kanıtı okunmuyor).
- **Kanıt:** `api/tender.py:1948-1959` (KPI sözlüğü), `tender.py:2559-2561`
  (kanıt kuralı), `public/js/pages/tender/DirectorBoard.vue:77-112` (kart metinleri).

### D-02 · Portföy tablosu: 13 satır, risk sırası, sahipsiz yönetici hücresi

- **Ön koşul:** D-01 ile aynı ekran, filtre çubuğu boş (URL'de `?` sorgu yok).
- **Adımlar:**
  1. "Linked ERP documents" panelinin başlığındaki sayacı oku.
  2. Satırları yukarıdan aşağı, "Risk" sütunuyla birlikte oku.
  3. İlk satırın "Delivery deadline" ve "Manager" hücrelerine bak.
- **Beklenen:**
  - Panel başlığı **`13 / 13 tenders`**.
  - Sıralama `risk → delivery → deal` (`tender.py:1962-1968`): **1. satır 4305**
    ("At risk"), ardından 3 adet "Deadline near" (**4308, 4310, 4311** — teslim
    tarihleri eşit olduğu için anlaşma kimliği sırasıyla), sonra 9 adet "On track".
  - Kazanılan 2 satırda yeşil **Won**, 1 satırda kırmızı **Lost** rozeti.
  - Value / Margin / Landed / Остаток sütunlarının **13'ünde de 0** (bkz. Ş-1).
  - Delivery deadline **13 satırda da aynı tarih** = bugün + 90 gün.
  - Manager açılır listesi **13 satırda da "— Unassigned —"**.
- **Kırık belirtisi:** "At risk" satırı listenin ortasında; risk rozetleri yokken
  sıralama rastgele; satır sayısı 13'ten farklı (demo dışı kayıt sızmış olabilir —
  ` [DEMO]` etiketiyle doğrula).
- **Kanıt:** `tender.py:1962-1968`, `DirectorBoard.vue:166-227`,
  `seed_tender_demo.py:75-85` (son tarih ofsetleri), `seed_tender_demo.py:133`
  (teslim tarihi = +90 gün).

### D-03 · Aynı sayfadaki iki kazanma oranı birbirini tutuyor

- **Ön koşul:** D-01 ile aynı ekran. (Huni paneli DirectorBoard içine gömülü —
  `DirectorBoard.vue:164`.)
- **Adımlar:**
  1. Üst şeritteki "Result" kartındaki yüzdeyi oku.
  2. Aşağı kaydır, "Conversion funnel" panelinin alt satırındaki "Win rate"i oku.
  3. İkisinin yanındaki won/lost sayılarını karşılaştır.
- **Beklenen:** İkisi de **66.7 %**, ikisi de **2 won**, çözülmüş **3**.
  Huni KPI şeridi ayrıca: Open pipeline **10**, Risk **1**, Execution **0**.
- **Kırık belirtisi:** İki panel farklı yüzde gösteriyor. (Kapsamları farklı —
  üstteki tüm zaman, alttaki son 90 gün — ama demo verinin tamamı bugün
  yaratıldığı için **demo'da ikisi eşit olmak zorunda**. Eşit değilse pencere
  filtresi ya da kanıt kuralı bozuk.)
- **Kanıt:** `tender.py:1958` (pano), `_funnel.py:116` (huni),
  `tender.py:2219-2227` (pencere), `TenderFunnel.vue:69-74, 288-294`.

---

## 2. "Süreç nerede tıkanıyor?" → `/tender/flow`

### D-04 · Adım tablosunun beş satırı da elle hesabı tutuyor

- **Ön koşul:** Rol `Stabler Tender Director`, şirket `Mikas`, demo **bugün** yüklendi
  (N=0), `https://mikas.erpstable.com/stabler#/tender/flow`
- **Adımlar:**
  1. "Step performance" tablosunu yukarıdan aşağı oku; her satırda Open · Average
     wait · Worst · SLA sütunlarını not al.
  2. SLA hücresinin altındaki `threshold N days` alt yazısını da oku.
  3. Üstteki 4 KPI kartını oku.
- **Beklenen (0.2'deki tabloyla birebir):**

  | Satır | Open | Average wait | Worst | SLA rozeti | threshold |
  |---|---|---|---|---|---|
  | Intake — file opened | 2 | **2 days** | 3 days | **At the edge** | 3 days |
  | GO / NO-GO decision | 2 | **4.5 days** | 5 days | **At the edge** | 5 days |
  | Quotation gathering | 2 | **22.5 days** | 26 days | **Over SLA** | 14 days |
  | Bid pricing | 2 | **7 days** | 8 days | **Over SLA** | 3 days |
  | Bid submitted | 2 | **—** | **—** | **Not measurable** | 30 days |

  KPI şeridi: In process **10** · Over SLA **2 steps** · Bottleneck **Bid pricing**
  · Not measurable **2**.
- **Kırık belirtisi:** `submitted` satırında ortalama **0 days** yazıyor (damgasız
  kayıt sıfır sayılmış — `_tender_flow.py:7-12`'nin yasakladığı şey);
  `sourcing` satırı "Within" gösteriyor; ortalamalar tam sayıya yuvarlanmış
  (4.5 → 5); "In process" 13 (sonuçlanmışlar da sayılmış — tablo YALNIZ bekleyen
  işi anlatır, `_tender_flow.py:21`).
- **Kanıt:** `api/_tender_flow.py:24-53`, `api/_tender_sla.py:30-38, 58-71`,
  `TenderFlow.vue:157-201`, `seed_tender_demo.py:51-71`.
- **Not:** Test N gün sonra koşuluyorsa her "Average wait"e ve "Worst"a N ekle;
  N≥1'de `go`, N≥2'de `seen` de "Over SLA"ya döner ve "Over SLA" sayacı 3-4 olur.

### D-05 · Darboğaz ORANLA seçiliyor, farkla değil — işaret `Bid pricing` satırında

- **Ön koşul:** D-04 ile aynı ekran.
- **Adımlar:**
  1. "Bottleneck" KPI kartındaki metni oku.
  2. Tabloda hangi satırın **sol kenarında kırmızı şerit** olduğuna bak
     (`tr[data-bottleneck="1"] td:first-child` → `inset 3px 0 0 var(--ds-crit)`).
  3. Tarayıcı ağ sekmesinde `tender_flow` yanıtındaki `bottleneck` alanını oku.
- **Beklenen:** KPI **"Bid pricing"**, kırmızı şerit **Bid pricing** satırında,
  yanıtta `"bottleneck": "priced"`. Aşımı daha BÜYÜK olan `sourcing` (+8.5 gün)
  darboğaz **değildir**; `priced` eşiğinin 2.33 katına çıkmıştır (sourcing 1.61 kat).
- **Kırık belirtisi:** Darboğaz "Quotation gathering" (fark ile hesaplanmış);
  şerit iki satırda birden; şerit var ama KPI "none today" diyor.
- **Kanıt:** `api/_tender_flow.py:79-93` (oran, fark değil — gerekçesi 82-84.
  satırlarda yazılı), `TenderFlow.vue:96-105, 171`, `TenderFlow.vue:233-235` (şerit).

### D-06 · Akış tablosu ile CRM panosu aynı anlaşma kümesini sayıyor

- **Ön koşul:** İki sekme: `…#/tender/flow` ve `…#/tender/crm`.
- **Adımlar:**
  1. Akış tablosundaki Open sütununu topla.
  2. CRM panosunda seen/go/sourcing/priced/submitted kulvarlarındaki kartları say.
  3. Aynı sayfadaki (portfolio) huni kutularıyla da karşılaştır.
- **Beklenen:** Akış **2·2·2·2·2 = 10**, CRM kulvarları da **2·2·2·2·2** (+ won 2,
  lost 1 = 13 kart). İkisi eşit olmalı — `tender_flow` ile `crm_board` aynı küme
  ve aynı damga alanını okuyor.
- **Kırık belirtisi (demo'da BEKLENEN kırık):** Aynı `/tender/portfolio` sayfasındaki
  huni kutuları **GO 4 · Collecting quotations 0** diyor; akış ve CRM **GO 2 ·
  sourcing 2** diyor. Bu, huninin damgayı değil olguları kullanmasından ve demo'nun
  hiç teklif belgesi yaratmamasından geliyor → direktör aynı ekranda iki farklı
  gerçek görüyor. Bkz. Ş-2.
- **Kanıt:** `tender.py:3046-3057` (akış: `custom_tender_stage` öncelikli),
  `tender.py:2365-2373` (CRM: aynı öncelik), `tender.py:2210-2218` (huni: yalnız
  `classify`), `seed_tender_demo.py:122-151` (`sq_count` parametre olarak alınıyor
  ama intake'e hiç yazılmıyor, tek bir Supplier Quotation da yaratılmıyor).

---

## 3. "Ölçemediğim ne var?" → damgasız kayıtlar (4312, 4313)

### D-07 · `submitted` satırı ortalama yerine "—" ve "2 kayıtta damga yok" gösteriyor

- **Ön koşul:** `…#/tender/flow`, demo veri yüklü.
- **Adımlar:**
  1. "Bid submitted" satırındaki adım adının **altındaki** küçük gri satırı oku.
  2. Average wait ve Worst hücrelerine bak.
  3. SLA sütunundaki rozeti ve alt yazısını oku.
  4. Üstteki "Not measurable" KPI kartını oku.
- **Beklenen:**
  - Adım adının altında: **`2 without a stage stamp — not averaged`**
  - Average wait: **`—`** (sıfır DEĞİL, boş DEĞİL, tire)
  - Worst: **`—`**
  - SLA rozeti: **`Not measurable`** (`Empty` DEĞİL — bekleyen 2 iş VAR),
    altında **`threshold 30 days`**
  - KPI: **Not measurable = 2**, kart tonu uyarı (`soon`), alt yazı
    "moved before the stage clock existed — left out of the averages"
  - Bu satır darboğaz olamaz (durumu `out` değil).
- **Kırık belirtisi:** Ortalama **0 days** ya da **30 days**; rozet **Empty**
  (bekleyen iş yokmuş gibi) ya da **Within** (iyimser yalan); alt satır hiç yok —
  o zaman direktör 2 kaydın ölçülmediğini bilmeden ortalamalara güvenir.
- **Kanıt:** `_tender_flow.py:39-52` (ortalama yalnız ölçülebilenlerden),
  `_tender_flow.py:56-76` (`empty` ≠ `unknown` ayrımı ve gerekçesi),
  `_tender_sla.py:58-71` (damga yoksa None), `TenderFlow.vue:175-177, 181-191`,
  `tender.py:3073-3075`, `seed_tender_demo.py:64-66, 192-194`.

### D-08 · Damga yazınca satır ölçülebilir hâle geliyor (ters yön)

- **Ön koşul:** `…#/tender/crm`, 4312 kartı `submitted` kulvarında.
- **Adımlar:**
  1. 4312 kartını `priced` kulvarına sürükle, sonra tekrar `submitted`e sürükle.
  2. `…#/tender/flow` sekmesini yenile.
- **Beklenen:** `submitted` satırı: Open 2, **ölçülemeyen 2 → 1**, Average wait
  artık bir sayı (**0 days**, çünkü bugün taşındı), Worst 0 days, rozet **Within**;
  KPI "Not measurable" **2 → 1**. Aynı kulvara geri bırakmak saati sıfırlamaz —
  yalnız gerçek aşama değişimi damga yazar.
- **Kırık belirtisi:** Ölçülemeyen sayısı düşmüyor (damga yazılmamış); ya da 4313
  de ölçülebilir olmuş (dokunulmayan kayıt değişmiş).
- **Kanıt:** `tender.py:2476-2493` (damga YALNIZ `previous != stage` iken yazılıyor,
  gerekçe 2480-2483), `tender.py:2467-2468` (geçersiz aşama adı reddediliyor).

---

## 4. "Bugün kimin kararı bende bekliyor?" → `/tender/desk`

### D-09 · Temiz demo'da karar kutusu boş ve bunu dürüstçe söylüyor

- **Ön koşul:** Rol `Stabler Tender Director`, şirket `Mikas`, demo veri yüklü,
  bekleyen onay talebi YOK, `https://mikas.erpstable.com/stabler#/tender/desk`
- **Adımlar:**
  1. Üstteki 4 sayaç kartını oku.
  2. Sağ sütunda "Decision box" panelini bul.
  3. Sağ sütunun en üstünde dolu (renkli) "Waiting for your signature" bloğunun
     çizilip çizilmediğine bak.
  4. "Daily work plan" listesini oku.
- **Beklenen:**
  - Sayaçlar: **Today = 2** · **Overdue = 0** · **Awaiting my approval = 0** ·
    **Waiting others = 0**
  - "Decision box" başlığında sayaç **0**, gövdesinde **"No pending decisions"**.
  - Dolu imza bloğu **çizilmez** (sıfırken vurgu yanlış aciliyet üretir —
    `OperationsDesk.vue:156`).
  - Günlük plan **tam 2 kalem**, ikisi de `policy_gap`: başlık
    "Missing supplier quotes: <anlaşma kimliği>", gerekçe **"0/5 quotes collected
    (minimum 5 required)"**, önem **Today**, sahip = anlaşma sahibi (Administrator).
    Bunlar 4308 ve 4309 (tek `sourcing` damgalı iki lot).
  - "Next 7 days" şeridi: bugün **2**, kalan 6 gün **—**.
- **Kırık belirtisi:** Plan boş (o zaman `custom_tender_stage` okunmuyor); plan
  13 kalem (her lot için üretilmiş); "Bid due" kalemleri görünüyor — demo'da teklif
  son tarihleri masaya HİÇ ulaşmaz (Ş-3), dolayısıyla `bid_due`/`bid_soon`
  görünüyorsa ya veri farklı ya kod değişmiş.
- **Kanıt:** `api/tender_desk.py:212-243` (sayaçlar), `api/_desk_rules.py:102-114`
  (policy_gap), `OperationsDesk.vue:323-359` (kart metinleri), `OperationsDesk.vue:156-195`.

### D-10 · Gerçek bir onay bekleyince sayaç ve kutu doluyor

- **Ön koşul:** Başka bir kullanıcı (ör. Sales User) `Mikas`'ta onay gerektiren
  bir kayıt (Purchase Order / Purchase Invoice) gönderip **bekleyen onay talebi**
  oluşturmuş olmalı. Direktör olarak `…#/tender/desk`.
- **Adımlar:**
  1. "Awaiting my approval" sayacını oku, karta tıkla (filtre uygular).
  2. "Decision box" satırına tıkla.
  3. Aynı testi, **onay talebi direktöre değil bir başkasına atanmışken** tekrarla.
- **Beklenen:**
  - Sayaç **1**, "Waiting for your signature" bloğu çizilir, kutuda 1 satır:
    üstte referans doctype, altında "Requested by <kullanıcı>", en altta referans adı.
  - Satıra tıklamak ilgili belgeye götürür (`/purchasing/orders/<ad>` vb.).
- **Kırık belirtisi (yapısal — demo'da doğrulanacak):** Talep **başkasına**
  atanmışken de sayaç artıyor. Gözetim rolünde filtre `… or oversight` yüzünden
  **her zaman doğru**; yani kart "Awaiting my approval" diyor ama şirketteki TÜM
  bekleyen onayları sayıyor. Kartın alt kuralı "approval assigned to you" yazıyor —
  bu ifade gözetim rolü için yanlış. Bkz. Ş-4.
  Ayrıca kartın filtresi plan listesinde `kind = "approval_pending"` arıyor; direktör
  bu karta tıklayınca **plan listesi** onay kalemlerini gösterir, karar kutusu değişmez.
- **Kanıt:** `tender_desk.py:225-233` (`decisions` filtresi ve `waiting_others`),
  `tender_desk.py:238-243`, `_desk_rules.py:213-247`, `OperationsDesk.vue:311-316, 343-357`.

### D-11 · "Waiting others" sayacı tıklanınca liste boş kalıyor

- **Ön koşul:** D-10 ile aynı durum (en az bir bekleyen onay var).
- **Adımlar:** "Waiting others" kartına tıkla, plan listesine bak.
- **Beklenen (kural gereği):** Direktörün BAŞKASINDAN beklediği kalemler.
- **Kırık belirtisi (kodda doğrulandı):** Liste **her zaman boş**. Filtre
  `i.kind === "waiting_others"` arıyor ama `_desk_rules.build_plan` böyle bir `kind`
  hiç üretmiyor (ürettikleri: `bid_due`, `bid_soon`, `policy_gap`, `no_parent`,
  `won_no_po`, `po_late`, `invoice_due`, `approval_pending`). Üstelik gözetim
  rolünde `waiting_others` sayacı da yapısal olarak **daima 0** (her onay önce
  `decisions`e giriyor, `a not in decisions` hiç sağlanmıyor).
- **Kanıt:** `OperationsDesk.vue:314-316`, `_desk_rules.py:42-247` (kind listesi),
  `tender_desk.py:230-233`.

---

## 5. "Ekibim ne kadar yüklü?" → masa "Team load" paneli

### D-12 · Team load paneli tek satır ve 13 açık lot gösteriyor

- **Ön koşul:** Rol `Stabler Tender Director` (gözetim), `…#/tender/desk`,
  demo veri `bench execute` ile yüklenmiş (yani anlaşmaların `owner` alanı
  `Administrator`).
- **Adımlar:**
  1. Sağ sütunda "Team load" panelini bul.
  2. Satır sayısını, kullanıcı adını ve sağdaki sayıyı oku.
  3. Satırın kırmızı (gecikme) işaretli olup olmadığına bak.
  4. Panel dip notunu oku.
- **Beklenen:**
  - **Tam 1 satır**: kullanıcı = anlaşmaların sahibi (`Administrator`),
    **open_lots = 13**, çubuk **%100** (en yoğun kuyruğa göre oranlanıyor),
    **kırmızı işaret YOK** (`overdue_lots = 0`).
  - Dip not: "Bar is relative to the busiest queue" · "red = has overdue".
- **Kırık belirtisi / bu senaryonun asıl bulgusu:**
  - **13 yanlış sayıdır** — 2 kazanılan + 1 kaybedilen kapanmış olmalı; doğru açık
    yük **10**'dur. Masa sonucu `custom_tender_result` **sütunundan** okuyor,
    sonuç ise intake JSON'ında duruyor → hiçbir lot "kapanmış" sayılmıyor.
  - **overdue_lots her zaman 0** — teklif son tarihi de sütunda aranıyor, JSON'da
    yazılı (4305 bir gün gecikmiş olmasına rağmen kırmızı işaret çıkmaz).
  - **won_lots hesaplanıyor ama ekranda hiç gösterilmiyor** (panel yalnız
    `open_lots` çiziyor).
  - Panel birden çok satır gösteriyorsa sitede demo dışı anlaşmalar var demektir.
- **Kanıt:** `tender_desk.py:257-277` (team load), `tender_desk.py:80-86`
  (sütun okuma), `seed_tender_demo.py:144-151` (sonuç intake JSON'ında),
  `OperationsDesk.vue:197-218, 425-432`.

---

## 6. "Kim neyi kaybetti, neden?" → kayıp analizi

### D-13 · Kaybedilen lotun gerekçesini aramak

- **Ön koşul:** Rol `Stabler Tender Director`, `…#/tender/portfolio`; kaybedilen lot
  4316 (`Signal va aloqa boshqarmasi [DEMO]`).
- **Adımlar:**
  1. Portföy tablosunda kırmızı **Lost** rozetli satırı bul.
  2. Satırdaki tüm sütunlarda kayıp gerekçesi / rakip / rakip fiyatı arayan bir
     alan ara.
  3. Satıra tıkla (PO kontrol ekranına gider), orada da ara.
  4. "Where we lose them" panelini oku.
- **Beklenen (bugünkü sürümde):**
  - Satırda **yalnız `Lost` rozeti** var; gerekçe, rakip, kaybedilen fiyat **yok**.
  - "Where we lose them" paneli **lot bazlı değil, ADIM bazlı** düşüş gösteriyor:
    **−4 Sourcing started (64 % conversion)** · **−3 Won (40 %)** ·
    **−2 GO decision (85 %)** · **−2 Bid submitted (71 %)** (sıra: düşüş büyüklüğü).
    "Won" satırının açıklaması: "Submitted and lost — the bid was in, the result
    went the other way."
  - **Hiçbir ekran "4316 neden kaybedildi" sorusuna cevap vermiyor.** Bu bir kabul
    kriteri: direktör bu bilgiyi ERP'den ALAMAZ, o yüzden test "yok" durumunu
    doğrulamalı, var sanmamalı.
- **Kırık belirtisi:** Panelde −4'ün başında başka bir adım varsa huni sıralaması
  bozuk; düşüşü olmayan bir adım listeleniyorsa filtre bozuk (`r.drop > 0`).
- **Kanıt:** `TenderFunnel.vue:168-187, 297-312` (adım bazlı kayıp),
  `DirectorBoard.vue:196-201` (satırda yalnız rozet), `tender.py:2498-2499`
  (tender ekseninde `lost` yazılırken gerekçe alanı YOK), `api/crm.py:444-458`
  (`loss_reason` yalnız satış-statü ekseninde yazılıyor, tender ekranları okumuyor).

---

## 7. "Bir lotu birine atayabilir miyim?" → atama

### D-14 · Atama YALNIZ Direktör panosundan yapılıyor

- **Ön koşul:** Rol `Stabler Tender Director`, `…#/tender/portfolio`; sitede en az
  bir etkin `Sales User` veya `Sales Manager` kullanıcısı olmalı.
- **Adımlar:**
  1. Portföy tablosunun en sağındaki "Manager" sütunundaki açılır listeyi aç.
  2. Bir kullanıcı seç.
  3. Sayfayı yenile, hücreyi tekrar oku.
  4. Aynı işlemi `…#/tender/crm` kartlarında ve `…#/tender/flow` satırlarında ara.
- **Beklenen:**
  - Açılır listede **yalnız `Sales User` / `Sales Manager` rolü olan, etkin,
    `Administrator` ve `Guest` dışı** kullanıcılar, tam adlarına göre alfabetik.
  - Seçince "Assigned." bildirimi; yenilemeden sonra seçim **kalıcı**.
  - Boş seçenek ("— Unassigned —") atamayı **kaldırır** ve `assigned_at`/`assigned_by`
    alanlarını temizler.
  - **Tender CRM ve Süreç akışı ekranlarında atama arayüzü YOKTUR** — atama tek
    yerde yapılır.
- **Kırık belirtisi:** Liste boş (site kullanıcı rollerini taşımıyor ya da
  `tender_managers` çağrısı sessizce düşmüş — `DirectorBoard.vue:52` hatayı yutuyor);
  seçim yenilemede kayboluyor; `Stabler Tender Director` rolü olan bir kullanıcı
  listede görünüyor (o rol atama hedefi değildir); atanan kullanıcı listede yoksa
  hücre **boş** görünür ve atama görünmez olur.
- **Kanıt:** `tender.py:1761-1782` (`tender_managers`, rol filtresi),
  `tender.py:1785-1818` (`assign_tender`; `_is_tender_oversight` kapısı 1789),
  `DirectorBoard.vue:54-63, 213-223`.

### D-15 · Atamanın etkisi nerede görünür, nerede GÖRÜNMEZ

- **Ön koşul:** D-14'te 4310 lotu `sales.user@…` adlı bir `Sales User`'a atandı.
- **Adımlar:**
  1. Direktör olarak `…#/tender/desk` → "Team load" paneline bak.
  2. Aynı ekranda plan kalemlerinin "owner" hücrelerine bak.
  3. `sales.user@…` ile giriş yap, `…#/tender/my-tenders` aç.
- **Beklenen:**
  - **My tenders:** o kullanıcı yalnız kendisine atanan lotları görür (gözetim
    rolü olmadığı için `assigned_to` filtresi uygulanır) → **1 satır**.
  - **Team load:** panel **DEĞİŞMEZ** — hâlâ tek satır, `Administrator`, 13 lot.
  - **Plan kalemlerinin owner'ı:** değişmez (`Administrator`).
- **Kırık belirtisi / bulgunun kendisi:** Atama intake JSON'ına yazılıyor
  (`assigned_to`), masa ise `assigned_to` **sütununu** okuyup yoksa `owner`a
  düşüyor. Yani direktörün yaptığı dağıtım "Ekibim ne kadar yüklü?" sorusunun
  cevabına HİÇ yansımıyor. Bkz. Ş-3.
- **Kanıt:** `tender.py:1800-1801` (JSON'a yazma), `tender.py:2137-2138`
  (My tenders JSON'dan okuyor), `tender_desk.py:79, 262` (masa sütundan okuyor).

### D-16 · Direktörün huni kutusuna tıklaması (rol kapısı)

- **Ön koşul:** **Saf `Stabler Tender Director`** (Sales Manager/Sales User rolü
  OLMADAN), `…#/tender/portfolio`.
- **Adımlar:**
  1. Huni panelinde herhangi bir aşama kutusuna tıkla (ör. "Priced — ready to bid").
  2. Açılan sayfayı ve varsa hata bildirimini oku.
  3. Üst gezinti çubuğunda "My tenders" bağlantısının olup olmadığına bak.
- **Beklenen (tasarım niyeti):** O aşamadaki lotların listesi açılır.
- **Kırık belirtisi (kodda doğrulandı):** Kutu `/tender/my-tenders` yoluna gidiyor;
  o ekranın uç noktası `sourcing` görünümü istiyor; `Stabler Tender Director`
  `sourcing` görünümünü **açmıyor** → **"Not permitted"** hatası. Üstelik aynı
  bağlantı gezinti çubuğunda direktöre gösterilmiyor (`v-if="can('sourcing')"`),
  yani ekran erişemeyeceği bir yere yönlendiriyor. `Sales Manager` ile test
  edilirse bu kusur GÖRÜLMEZ.
- **Kanıt:** `TenderFunnel.vue:192-201` (yönlendirme), `tender.py:2126`
  (`_require_tender_view("sourcing", …)`), `tender.py:1727` (rol listesinde
  Tender Director yok), `TenderNav.vue:50-52`.

---

## 8. "Şirkete özel SLA eşiği koyabilir miyim?" → Stabler Settings

> **Kapsam uyarısı:** `stabler/stabler/doctype/stabler_settings/stabler_settings.py`
> bu inceleme paketinde YOK. Aşağıdaki beklentiler `tender.py:3013, 3067`
> (`stage_sla_for(company)` çağrısı) ve `_tender_sla.sla_for` (`_tender_sla.py:74-86`)
> sözleşmesinden çıkarıldı. Ayarın kaydedilme biçimi (boş satır silinir mi,
> boş değer olarak saklanır mı) burada test edilecek asıl belirsizliktir.

### D-17 · Şirkete özel eşik akış tablosunu ve darboğazı değiştiriyor

- **Ön koşul:** Rol `Stabler Tender Director` + Stabler Settings yazma yetkisi
  (pratikte `System Manager` / `Stabler Admin`), demo veri N=0,
  `https://mikas.erpstable.com/app/stabler-settings` → **Per-Company Tender Stage SLA**
  tablosu, şirket `Mikas`.
- **Adımlar:**
  1. Önce `…#/tender/flow` aç, "Bid pricing" satırını not al (Over SLA · threshold 3).
  2. Ayarlarda `Mikas` için `priced` eşiğini **10** yap, kaydet.
  3. `…#/tender/flow` sayfasını **Refresh** düğmesiyle yenile.
  4. Ağ sekmesinde `tender_flow` yanıtındaki `stage_sla` alanını oku.
- **Beklenen:**
  - "Bid pricing" satırı: Average wait **7 days** (değişmez), threshold **10 days**,
    rozet **Within** (kenar sınırı 10 − max(1, 2) = 8; 7 < 8).
  - "Over SLA" KPI **2 → 1**.
  - **Darboğaz `Bid pricing` → `Quotation gathering`e taşınır** (tek `out` satırı
    kaldığı için oran karşılaştırmasını o kazanır), kırmızı şerit satır değiştirir.
  - Yanıtta `"stage_sla"` içinde `priced: 10` görünür.
- **Kırık belirtisi:** Eşik yenilemeden sonra hâlâ 3; başka bir adımın eşiği de
  değişmiş; darboğaz `priced`te kalmış (satır artık `out` değilken darboğaz
  olamaz — `_tender_flow.py:88`).
- **Kanıt:** `tender.py:3067, 3076`, `_tender_sla.py:74-86`,
  `_tender_flow.py:40, 86-93`, `TenderFlow.vue:194-197, 204`.

### D-18 · **Boş hücre "kapalı" demektir — "varsayılana dön" DEĞİL**

- **Ön koşul:** D-17'nin ardından, `Mikas` için `priced` satırı ayarlarda mevcut.
- **Adımlar:**
  1. `priced` eşiği hücresini **tamamen boşalt** (silme, sıfırlama değil — hücreyi
     boş bırak), kaydet.
  2. `…#/tender/flow` yenile, "Bid pricing" satırını oku.
  3. Aynı testi hücreye **0** yazarak tekrarla, kaydet, yenile.
  4. Aynı testi **-1** yazarak tekrarla.
  5. Ağ yanıtındaki `stage_sla` alanını her adımda oku.
- **Beklenen (kural: `sla_for` 0/negatif/çözülemeyen → `None`):**
  - Her üç durumda da "Bid pricing" satırı:
    SLA rozeti **`Not measurable`**, alt yazı **`not tracked`** (eşik satırı YOK),
    Average wait yine **7 days** (ölçüm sürüyor, eşik yok).
  - Bu adım **darboğaz olamaz** ve "Over SLA" sayacına girmez → KPI **1**
    (yalnız sourcing), darboğaz **Quotation gathering**.
  - **Beklenen KIRIK durum tam olarak şu:** satır yenilendiğinde
    **`threshold 3 days`** geri gelirse, boş hücre "varsayılana dön" olarak
    yorumlanmış demektir. Bu bir hatadır: `_tender_sla.py:79-80` boşaltmayı
    "yönetici bu adımı takipten çıkarıyor" olarak tanımlıyor.
  - İkinci kırık biçimi: satır **`Over SLA` · threshold 0 days** gösterirse
    sıfır "sıfır gün sabır" olarak yorumlanmış, her anlaşma anında gecikmiş sayılır.
- **Kırık belirtisi:** Yukarıdaki iki kırık biçiminden biri; ya da boş hücre
  kaydedilemiyor (form zorunlu alan diyor) — o zaman "takipten çıkarma" özelliği
  arayüzden erişilemez demektir, kural var ama kapı yok.
- **Kanıt:** `_tender_sla.py:74-86` (`value > 0` değilse `None`; gerekçe 78-79.
  satırlarda yazılı), `_tender_flow.py:40, 50` (limit `None` → `state = "unknown"`),
  `_tender_flow.py:88` (`not row["sla_days"]` → darboğaz adayı değil),
  `TenderFlow.vue:194-197` (`v-else` dalı `not tracked` yazıyor),
  `tender.py:3076` (`stage_sla` yanıtta görünür — ekranı değil sözleşmeyi doğrular).

### D-19 · Eşik başka şirkete sızmıyor

- **Ön koşul:** Sitede ikinci bir tender şirketi varsa (yoksa senaryo "uygulanamaz"
  olarak kapatılır). `Mikas` için `sourcing = 30` ayarla.
- **Adımlar:**
  1. `Mikas` şirketiyle `…#/tender/flow` aç, "Quotation gathering" satırını oku.
  2. Şirket seçiciden ikinci şirkete geç, aynı satırı oku.
- **Beklenen:** `Mikas`'ta threshold **30 days**, rozet **Within** (22.5 < 30−7);
  ikinci şirkette threshold **14 days** (varsayılan). "Over SLA" KPI `Mikas`'ta
  **1** (yalnız priced).
- **Kırık belirtisi:** Her iki şirkette de 30 görünüyor (ayar kiracıya değil
  siteye yazılmış).
- **Kanıt:** `tender.py:3067` (`stage_sla_for(company)` — şirket parametreli),
  `_tender_sla.py:23-25` (varsayılanlar yalnız ayar yokken geçerli),
  `tender.py:3016` (`_assert_company_scope`).

---

## Direktörün soramadığı sorular

Aşağıdakiler **ekranlarda yok**. Test sırasında "olmalıydı" diye aranmamalı; UAT
bunları eksik olarak kaydeder.

1. **"4316'yı neden kaybettik?"** — Tender ekseninde kayıp gerekçesi alanı yok.
   `move_deal_stage` `lost` yazarken yalnız `intake["result"]="lost"` kaydediyor
   (`tender.py:2498-2499`). `CRM Deal.loss_reason` alanı var ama yalnız satış-statü
   ekseninde yazılıyor (`crm.py:444-458`) ve **hiçbir tender ekranı okumuyor**.
2. **"Kime kaybettik / rakip fiyatı neydi?"** — Rakip kavramı hiçbir uç noktada,
   hiçbir alanda yok (paket genelinde `competitor` geçmiyor).
3. **"Kazanma oranım geçen çeyreğe göre nasıl?"** — Direktör panosunun win rate'i
   dönemsiz (tüm zaman, `tender.py:1958`). Huni panelinin 90 günlük penceresi var
   ama `/tender/portfolio` sayfasında bu pencereyi değiştiren bir denetim YOK
   (`DirectorBoard.vue:164` bileşeni varsayılan `days=90` ile çağırıyor,
   `TenderFunnel.vue:32-35`). Aylık eğilim yalnız `tender_dashboard` uç noktasında
   var (`_monthly_trend`, `tender.py:2613`), direktörün bu üç ekranında değil.
4. **"Bu adımda en çok bekleyen hangi lot?"** — Akış tablosu `worst_days` sayısını
   gösteriyor ama **hangi lot olduğunu söylemiyor** ve satırlar tıklanabilir değil
   (`_tender_flow.py:42-52` yalnız toplam döndürüyor; `TenderFlow.vue:168-199`
   bağlantı içermiyor).
5. **"SLA'yı aşan işler kimde?"** — Akış satırlarında sahip/atanan bilgisi yok;
   adım performansı ile ekip yükü hiçbir ekranda kesişmiyor.
6. **"Kişi başına kazanma oranı?"** — `team_load` `won_lots` hesaplıyor ama panel
   yalnız `open_lots` çiziyor (`OperationsDesk.vue:202-213`); üstelik `won_lots`
   demo verisinde yapısal olarak 0 (bkz. Ş-3).
7. **"Kararı buradan onaylayayım"** — Karar kutusu satırları yalnız yönlendirme
   yapıyor; masada onayla/reddet eylemi yok (`OperationsDesk.vue:496-508`).
8. **"Portföy değerini para birimi bazında kırayım"** — Tek para birimi (şirket
   varsayılanı) var, kur kırılımı ekranlarda yok (`tender.py:1885, 1960`).

---

## Sayı şüpheleri

Test sırasında sayı uyuşmazlığı görülürse önce buraya bakılmalı; hepsi kod
okumasıyla saptandı, sitede doğrulanmalı.

**Ş-1 · Direktör panosunda tüm para sütunları 0 çıkacak.**
Demo `custom_bid_pricing` alanına `{"unit_price": …, "margin_pct": 12}` yazıyor
(`seed_tender_demo.py:186`). `_compute_bid_pnl` **`unit_price` anahtarını hiç
okumuyor**; `margin` modunda fiyat `landed_goods`tan geri çözülüyor
(`tender.py:1113-1120`), demo'da PO olmadığı için `landed_goods = 0` →
`bid_price = 0`, `ostatok = 0`, `margin_on_revenue_pct = 0`. Sonuç: 13 satırın
13'ünde Value/Landed/Остаток **0**, "Portfolio value" **0**, "Avg margin"
**0 %** — oysa demo lotlarında 480 mln – 3,15 mlrd arası sözleşme değerleri
`intake.contract_value` içinde yazılı ve **Tender CRM kartları bu değeri
gösteriyor** (`tender.py:2383`). Aynı iki ekran aynı lota farklı değer biçiyor.
*Kanıt:* `tender.py:1917, 1088-1155, 2383`, `seed_tender_demo.py:185-186`.

**Ş-2 · Huni ile akış/CRM aşama sayıları demo'da çelişiyor.**
Huni `_funnel.classify` kullanıyor ve `sourcing` için **Supplier Quotation belgesi**
şart (`_funnel.py:48`); demo hiç SQ belgesi yaratmıyor. Sonuç: huni **GO 4 /
sourcing 0**, akış ve CRM **GO 2 / sourcing 2**. Ayrıca huninin "0/5 politika"
rozeti (`sourcing_policy_gap`) **0** çıkar — hiçbir lot `sourcing` sayılmadığı için —
oysa Operasyon Masası aynı iki lot için "0/5 quotes" uyarısı üretiyor. Demo'nun
kendi belgesi bu riski yazıyor ama önlemi eksik: `_intake()` `sq_count` parametresini
alıp **hiç kullanmıyor**.
*Kanıt:* `tender.py:2210-2218, 2232-2233` vs `tender.py:3046-3057`, `2365-2373`;
`seed_tender_demo.py:122-151, 178-184`; `_desk_rules.py:102-114`.

**Ş-3 · Operasyon Masası, tender modülünün yazmadığı sütunları okuyor.**
`tender_desk.py:57-60` şu alanları arıyor: `assigned_to`, `custom_tender_master`,
`custom_lot_no`, `custom_bid_deadline`, `custom_delivery_deadline`,
`custom_tender_result`, `custom_tender_risk`. Bu adlar **paketin başka hiçbir
yerinde yazılmıyor**; tender verisi `custom_tender_intake` JSON'unda duruyor.
Sonuçlar: masa hiçbir teklif son tarihi görmez (`bid_due`/`bid_soon` kalemi hiç
üretilmez, 4305 bir gün gecikmiş olmasına rağmen), `won_without_po` daima boş,
`orphan_lots` daima boş, `team_load` sonuç ayrımı yapamaz (13 lotun 13'ü "açık"),
atama masaya hiç yansımaz. `custom_tender_result` yoksa `status` sütununa
düşüyor — CRM Deal statüsü (ör. "Qualification") sonuçla aynı şey değil.
*Kanıt:* `tender_desk.py:57-60, 80-86, 121, 117, 202, 262-276`;
`seed_tender_demo.py:128-151` (verinin gerçek yeri); `tender.py:1800` (atamanın yeri).

**Ş-4 · "Awaiting my approval" gözetim rolünde şirketin TÜM bekleyen onaylarını sayıyor.**
Filtre `a.get("assigned_to") == user or a.get("requested_by") != user or oversight`
— direktör için son terim daima doğru. Kartın alt kuralı "approval assigned to you"
yazıyor; sayı bunu karşılamıyor. Aynı nedenle `waiting_others` yapısal olarak
daima 0 ve o kartın filtresi hiçbir zaman eşleşmeyen bir `kind` arıyor.
*Kanıt:* `tender_desk.py:225-233, 238-243`; `OperationsDesk.vue:314-316, 343-357`;
`_desk_rules.py:213-247`.

**Ş-5 · "Active tenders = 13" kendi kuralını yalanlıyor.**
Kartın alt kuralı `tender_lot · result = null`, notu "seen through to awaiting
result"; oysa `visible_count` sonuç kontrolünden ÖNCE artıyor, yani kazanılan 2 ve
kaybedilen 1 de sayılıyor. Dürüst açık portföy **10** (huninin "Open pipeline"
sayacı ve akışın "In process" sayacı bunu doğru veriyor). Aynı sayfada 13 ve 10
yan yana duruyor.
*Kanıt:* `tender.py:1894-1897, 1949`; `_funnel.py:106`; `tender.py:3072`;
`DirectorBoard.vue:81-84`.

**Ş-6 · `/tender/flow` ve `/tender/crm` uç noktalarında `director` rol kapısı yok.**
`tender_flow` ve `crm_board` yalnız modül + şirket kapısı uyguluyor
(`tender.py:3015-3017`, `2305-2307`); `_require_tender_view("director", …)`
çağrılmıyor — oysa gezinti çubuğu "Process flow" bağlantısını yalnız direktöre
gösteriyor (`TenderNav.vue:40-42`). Yani `Sales User` bu iki ekranı doğrudan URL
ile açabilir. Direktörün sayılarını etkilemez ama "bu ekran bana özel" varsayımını
bozar; kabul kriteri olarak karar verilmeli.
*Kanıt:* `tender.py:1738-1743` (kapının kendisi), `3015-3017`, `2305-2307`,
`TenderNav.vue:40-46`.

**Ş-7 · Masa satır başlıkları lot numarası yerine anlaşma kimliği gösteriyor.**
`lots_fact` içinde `"label": d.get("name")` → plan kalemleri
"Missing supplier quotes: CRM-DEAL-…-00005" der; direktör hangi lot olduğunu
(UTY-2026-4308) göremez. Lot numarası intake'te var (`lot_no`) ama masa oraya
bakmıyor.
*Kanıt:* `tender_desk.py:197-198`; `_desk_rules.py:47`; `seed_tender_demo.py:129`.

---

## Koşum sırası ve ön hazırlık

1. `unseed` → `seed` (aynı gün, N=0 için). Çıktıdaki 13 satırı ve
   `moved=no stamp` yazan iki satırı (4312, 4313) doğrula.
2. D-04 → D-07 (akış; en çok elle hesap içeren blok, veri henüz taze).
3. D-01 → D-03 (portföy).
4. D-09 → D-12 (masa).
5. D-14 → D-16 (atama; veriyi değiştirir).
6. D-17 → D-19 (SLA ayarı; ayarları geri al: `priced` ve `sourcing` satırlarını sil).
7. D-08 en sona bırakılabilir — damga yazarak demo veriyi kalıcı değiştirir.
