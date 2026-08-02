# Mikas tender UAT — özet ve koşum sırası

Aradığın kelime: bu iş **UAT** (User Acceptance Testing / kabul testi). Her rol için
yazılan adım-adım metne **test senaryosu** ya da **kabul senaryosu** denir. *User
story* farklı bir şey — o gereksinim yazma biçimi ("<rol> olarak <şunu> istiyorum
ki <şu fayda> olsun"); senin tarif ettiğin, yazılmış bir sistemi rol rol gezip
doğrulama, yani UAT. Rol rol gezmenin adı da **rol bazlı uçtan uca senaryo**
(persona-based end-to-end walkthrough).

Altı rol ajanı kodu okudu ve **177 senaryo** yazdı:

| Dosya | Rol | Senaryo | Bulgu |
|---|---|---|---|
| `01-uiux.md` | UI/UX | 40 | 19 eksik, 15 şüphe |
| `02-tender-uzmani.md` | İhale uzmanı (uçtan uca) | 26 | 13 iş akışı kopukluğu |
| `03-sourcing.md` | Tedarik | 32 | 5 yetki + 12 fonksiyonel |
| `04-direktor.md` | Direktör | 19 | beklenen değerler elle hesaplandı |
| `05-logist.md` | Lojistik | 33 | 3 yetki sızıntısı |
| `06-deklarant.md` | Gümrük beyannamecisi | 27 | 2 yetki sızıntısı |

---

## Altı ajanın BİRBİRİNDEN BAĞIMSIZ aynı yere işaret ettiği üç şey

Bunlar en yüksek güvenilirlikteki bulgular: farklı rollerden bakan ajanlar aynı
kırığı ayrı ayrı buldu. Üçünü de kendim doğruladım.

### 1. Operasyon Masası, hiç kimsenin yazmadığı sütunları okuyor

`stabler/api/tender_desk.py:59-60` şu alanları CRM Deal **sütunlarından** okuyor:
`custom_bid_deadline`, `custom_delivery_deadline`, `custom_tender_result`,
`assigned_to`.

Doğrulama: `grep -rn` ile bakıldığında bu adlar **yalnız `tender_desk.py` içinde ve
kendi testinde** geçiyor. `stabler/patches/` altında bu sütunları yaratan **hiçbir
yama yok** — yani sütunlar veritabanında mevcut bile değil. Tender modülünün geri
kalanı (24 ayrı yerde) her şeyi `custom_tender_intake` JSON'una yazıyor.

Sonucu: masanın teklif son tarihi, teslim tarihi ve sonuç kuralları **hiçbir gerçek
kayıtta tetiklenemez**. Demo veride süresi dün geçmiş lot (UTY-2026-4305) masada
uyarı üretmiyor; CRM aynı lota "Risk" derken masa onu hiç göstermiyor. "Team load"
13 lotun 13'ünü açık sayıyor (doğrusu 10, çünkü sonuç sütunu boş).

Bu tek kırık, üç ajanın raporunda ayrı ayrı ilk sırada.

### 2. `tender_flow` ve `crm_board` uç noktalarında rol kapısı yok

`tender.py:3028-3030` — `tender_flow` yalnız `_require_tender`,
`_assert_company_scope`, `_require_company` çağırıyor. `_require_tender_view("director", …)`
**yok**. `crm_board` (2302) da aynı durumda.

Ön yüz `TenderNav.vue`'da bağlantıyı `can('director')` ile gizliyor; router
muhafızı yalnız `meta.module`'e bakıyor. Yani menüde görünmüyor ama **URL'yi elle
yazan sourcing / logist / deklarant kullanıcısı 200 ve dolu veri alıyor** —
şirketin tüm SLA tablosu ve kanban'ı. Üç ajan bunu birbirinden bağımsız buldu.

Sourcing tarafında bir de şu var: `move_deal_stage` (2451) geçiş kuralı taşımıyor,
yani tedarikçi bir kartı `won`/`lost`'a sürükleyip direktörün kazanma oranını
değiştirebiliyor.

### 3. Demo veri dört panodan yalnız ikisini besliyor

`seed_tender_demo.py` 13 CRM Deal + organizasyon + aşama olayı üretiyor. **Sıfır**
Purchase Order, **sıfır** Supplier Quotation, **sıfır** atama.

Sonucu: `/tender/logistics` ve `/tender/customs` seed sonrası **boş kalıyor** —
ikisi de Purchase Order okuyor. `/tender/my-tenders` boş (atama yok). Tüm CRM
kartlarında "0/5 quotes" yazıyor çünkü `_intake()` aldığı `sq_count` parametresini
kullanmıyor. Direktör panosunun para sütunları 0 çıkıyor.

Seed'in kendi çıktı satırı bunu zaten itiraf ediyor: *"Visible on: /tender/desk ·
/tender/crm · /tender/portfolio · /tender/flow"* — logistics ve customs listede yok.
Ben bu betiği "tüm bölümlerde görünecek" diye yazdım; dördünü kapsıyor, altısını
değil. Bu benim eksiğim.

---

## Direktör panosu için elle hesaplanmış beklenen değerler

Ekran bunlardan farklı gösterirse kırık demektir. Hesap demo veriden çıkarıldı.

| Ekran · alan | Beklenen | Hesap |
|---|---|---|
| portfolio · Aktif ihale | 13 | tüm tender anlaşmaları |
| portfolio · Kazanma oranı | %66,7 | 2 won / (2 won + 1 lost) |
| portfolio · Risk | 1 | yalnız 4305 (son tarih −1 gün) |
| flow · seen | 2 açık · ort. 2,0 · eşik 3 → **kenar** | (1+3)/2 |
| flow · go | 2 açık · ort. 4,5 · eşik 5 → **kenar** | (4+5)/2 |
| flow · sourcing | 2 açık · ort. 22,5 · eşik 14 → **aştı** | (19+26)/2, oran 1,607 |
| flow · priced | 2 açık · ort. 7,0 · eşik 3 → **aştı** | (8+6)/2, oran 2,333 |
| flow · submitted | 2 açık · **2 ölçülemeyen** · ortalama **—** | damga yok |
| flow · darboğaz | **Bid pricing** | 2,333 > 1,607 — oran, fark değil |
| flow KPI | Süren 10 · Eşik aşan 2 · Ölçülemeyen 2 | |

Darboğazın `priced`'da çıkması testin can alıcı noktası: `sourcing` mutlak olarak
daha geç (22,5 gün > 7 gün) ama eşiğine göre daha az geç. Ekran `sourcing` derse
oran değil fark hesaplıyor demektir.

---

## Koşum sırası (local bench, sonra prod)

**1 — Local bench'te ortamı kur.** Mikas sitesinde `bench migrate` (v66, v67 ve SLA
alt tablosu gelsin), sonra `bench --site <mikas-local> execute
stabler.maintenance.seed_tender_demo.seed`. Şirket kaydının **tam adı** ne ise onu
kullan; `seed()` `Company` kaydına birebir bakıyor.

**2 — Önce üç kırığı düzelt, sonra senaryoları koştur.** Yukarıdaki 1 ve 3 numaralı
kırıklar düzeltilmeden masayı, lojistiği ve gümrüğü test etmenin anlamı yok — boş
ekranı doğrulamış olursun. 2 numaralı yetki açığı ise prod'a çıkmadan kapanmalı.

**3 — Rol rol gez.** Her dosyadaki senaryoları sırayla uygula. Her senaryonun
**Kanıt** satırı hangi dosya:satırın o davranışı garanti ettiğini söylüyor —
beklenen çıkmazsa doğrudan oraya bak.

**4 — Aynı listeyi prod'da smoke olarak tekrarla.** Local'de yeşil olan senaryolar
prod'da kısa bir geçişle doğrulanır; senaryolar tekrar kullanılabilir kalır.

**5 — Tarayıcıda ajanla koşum.** Deploy bittiğinde aynı seti Claude in Chrome ile
gerçek tarayıcında rol rol oynatabiliriz — senaryolar zaten adım adım yazılı.

---

## Takvim şeridi (senin istediğin "takvimde task görmek")

`/tender/desk` içinde **"Next 7 days"** şeridi zaten var (`OperationsDesk.vue:220-240`)
ama yalnız **sayı** gösteriyor; işlerin kendisi sadece tooltip'te
(`week` computed, `:447` — `items.map(i => i.title).join("\n")`). Backend zaten
`calendar[].items` gönderiyor, yani veri elde.

Yapılacak: günü tıklanabilir yap → plan listesi o güne filtrelensin; şeritte gün
başına işlerin başlıkları ve severity rengi görünsün. Bu, yeni ekran açmadan
"takvimde task görmek" isteğini karşılıyor.

**Ama önce yukarıdaki 1 numaralı kırık düzelmeli** — masa son tarihleri okuyamadığı
sürece takvim şeridi de boş kalır. Şerit zenginleşse bile içine koyacak iş yok.
