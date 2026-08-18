# Mikas Tender — İş Akışı ve Form Katmanı · Tasarım Kurulu Kararı (2026-08-17)

Talep (Zafar): "mikas tender workflow ve formları için mevcut codebase üzerinde çalışalım
ve mockuplar oluşturalım yeni planımıza göre."

Plan kaynağı (Zafar'ın işaret ettiği iki doküman):
`docs/uat/2026-08-10-belge-merkezi/belge_merkezi_draft.html` (7 bead: vgk.7 → .4) ·
`docs/design/tender-flow-map.html` (birleşik süreç haritası, bd `stabler-0b2`).

Kurul: kamu ihale operasyonu (UZEX), sourcing & procure-to-pay, form/etkileşim tasarımı,
şüpheci-denetçi.

**Kanıt rejimi:** aşağıdaki her kusur iddiası kaynak okumasıyla `dosya:satır` düzeyinde
doğrulandı, ardından **bağımsız bir çürütme turundan** geçirildi (görev: iddiayı yanlışla).
O tur iki iddiayı kısmen düzeltti (#3 ve #5 aşağıda düzeltilmiş hâlleriyle duruyor) ve
**yeni bir kusur buldu** (#7). Sandbox'ta bench/DB yok — davranış teyidi `make test-bench` +
canlı bench koşusuna işaretlidir. D-2 gereği hiçbir dosya veya endpoint adı hafızadan yazılmadı.

---

## KARAR ÖZETİ

> **İki kaynak planın da işi bitmiştir.** `belge_merkezi_draft.html`'in 7 bead'i ship;
> `tender-flow-map.html`'in "sıradaki işler" listesi (A: tek seviyeli navigasyon,
> B: RFQ→teklif prefill / tur-bazlı takip / ödül→PO) de ship — `TenderMasterBoard.vue` ve
> `composables/tenderMaster.js` depoda yok, `sourcing.get_quotation_defaults`
> (`stabler/api/sourcing.py:508`), `Supplier Quotation.custom_rfq`
> (`stabler/patches/v83_sq_rfq_link.py:27`) ve `purchasing.create_po_from_quotation`
> (`stabler/api/purchasing.py:2861`) yerinde.
>
> **Yeni planın konusu bu yüzden bir özellik değil, bir sözleşmedir.** Zincir kapandı;
> kırık olan, ekranların o zincire yazdığı verinin sözleşmesi. Bugün ihale girişini iki
> ayrı form yazıyor, sunucu sanitizer'ı ikisinin de alanlarının bir kısmını **sessizce
> düşürüyor**, ve kanban çekmecesinden yapılan bir düzenleme GO kararını, garantiyi,
> FX bloğunu ve **belge kontrol listesinin tamamını** siliyor.
>
> Bu dilimin işi: **tek yazar, açık sözleşme, kararın verildiği yerde form** — ve ancak
> ondan sonra form katmanının tek tasarım diline (`ds-*`) taşınması.

---

## 1 · Bugün akış kodda nasıl işliyor

| # | Aşama | Ekran | Uç (whitelisted) | Depolama | Durum |
|---|---|---|---|---|---|
| 1 | İhale girişi | `components/TenderMasterDrawer.vue` (kanban "New tender", 4 bölüm) | `crm.save_deal` + `tender.save_deal_intake` | CRM Deal + `custom_tender_intake` JSON | ✅ ship |
| 1b | İhale künyesi/değerlendirme | `pages/tender/TenderIntake.vue` — **PO kontrol panosuna gömülü** (`PoControlBoard.vue:22,315`) | `tender.deal_intake` / `save_deal_intake` | aynı JSON | ⚠️ ikinci yazar |
| 2 | Kanban | `TenderCrm.vue` (wrapper 7 satırlık geçiş) | `tender.crm_board` — 13 şerit, `tender.py:2557-2571` | Deal `custom_tender_stage` | ✅ ship |
| 2b | Atama | kart çekmecesi | `tender.tender_managers` / `assign_tender` | intake JSON (`assigned_*`) | ✅ ship |
| 3 | RFQ | `pages/tender/rfq/*.vue` | `sourcing.create_rfq` / `list_rfqs` / `get_rfq` / `mark_rfq_sent` / `rfq_print` | Request for Quotation + `custom_crm_deal` | ✅ ship |
| 4 | Teklif girişi | `components/QuotationEntryDrawer.vue` | `sourcing.get_quotation_defaults` → `save_supplier_quotation(rfq=)` | Supplier Quotation + `custom_rfq` | ✅ ship |
| 5 | Karşılaştırma + landed | `SourcingWorkspace.vue` | `purchasing.tender_quotations` → `_landed.rank_quotations_landed` | hesap (kalıcı değil) | ✅ ship |
| 6 | Ödül + onay | `SourcingWorkspace.vue` ödül paneli | `sourcing.save_sourcing_decision` / `approve_sourcing_decision` | `Tender Sourcing Decision` | ✅ ship |
| 7 | Ödül → PO | aynı panel | `purchasing.create_po_from_quotation` (idempotent) | Purchase Order + `custom_crm_deal` | ✅ ship |
| 8 | Teklif fiyatlama | `BidPricing.vue` | `tender.deal_bid_pricing` / `save_deal_bid_pricing` / `bid_package` | intake JSON | ✅ ship |
| 9 | Belge merkezi | `TenderDocuments.vue` + `TenderDocumentsPanel.vue` | `tender_documents.*` (6 uç) | Deal JSON `.documents` **+ Tender Master `custom_tender_documents`** | ✅ ship |
| 10 | Kazanım sonrası | `DeclarantQueue` / `LogistBoard` / `PoControlBoard` | `tender.declarant_queue` / `logist_board` / `po_control_board` | türetilmiş (PO, GTD, Freight) | ✅ ship |
| 11 | Post-win şerit türetmesi | kanban | `crm_board` `phase:"post"` şeritleri | `v81_crm_deal_customs_freight_refs.py` linkleri | ✅ ship |

Yani **zincirin hiçbir halkası kopuk değil.** Kırık olan aşağıda.

---

## 2 · Nerede kırılıyor — 7 doğrulanmış kusur

Hepsinin kaynağı tek dosyada buluşuyor: `stabler/api/tender.py::_clean_intake` (`:1355-1418`)
ve onun beslediği `save_deal_intake` (`:1622`).

| # | Kusur | Kanıt | Etkisi |
|---|---|---|---|
| 1 | **Kanban çekmecesinden yapılan her düzenleme değerlendirme verisini siler.** `_clean_intake` çıktısını sıfırdan kurar: `out = {k: str(data.get(k) or "")… for k in _INTAKE_KEYS_STR}` (`tender.py:1366-1368`). Gönderilmeyen anahtar **korunmaz, boşaltılır**. `TenderMasterDrawer` payload'ı (`TenderMasterDrawer.vue:255-278`) bu anahtarların **hiçbirini** taşımıyor. | `_INTAKE_KEYS_STR` (`:1280-1292`), `_INTAKE_KEYS_NUM` (`:1293-1301`) | `lot_no`, `buyer`, `bid_deadline`, `delivery_deadline`, `guarantee_amount`, `guarantee_return`, `penalty_pct_per_day`, `go_no_go`, `result`, `won_price`, `purchase_method`, `notes`, tüm FX bloğu → **boşalır**. `go_no_go` boşalınca `go_no_go_at`/`by` damgası da siliniyor (`:1385-1387`) — karar kaydı ve kim/ne zaman izi birlikte gidiyor. **Ayrıca Deal'in kendi alanları:** `openEditDrawer` çekmeceye kısmi bir nesne veriyor (`TenderCrm.vue:301-307` — `tender_no` ve `source` yok), çekmece de bunları `crm.save_deal`'e boş/varsayılan gönderiyor → `CRM Deal.tender_no` silinir, `source` "UZEX"e döner. |
| 2 | **Aynı düzenleme belge kontrol listesini de siler.** Çekmece `documents: []` gönderiyor (`TenderMasterDrawer.vue:279`); `_merge_client_documents` client listesinde olmayan satırı düşürüyor (docstring `:1315-1316`, döngü `:1331-1352`). Boş liste = "hepsini sil". | `tender.py:1407` | Yüklenmiş dosya/waiver kayıtlarına bağlı satırlar dahil, hazır olma yüzdesi ve deklarant/lojist kuyruğunun beslendiği liste sıfırlanır. |
| 3 | **İhale Giriş Merkezi'nin B ve C bölümünün yarısı hiçbir yere yazmıyor.** `_clean_intake` çıktısının **tam** anahtar listesi: 11 `_INTAKE_KEYS_STR` + 7 `_INTAKE_KEYS_NUM` + `cert_required` + `go_no_go_at/by` + `result_at/by` + `submitted_at/by` + `submission_reference` + `assigned_to/_name/_at/_by` + `documents` + `items` + `ready_at/by`. İçinde `title`, `publication_date`, `submission_deadline`, `tender_files` **yok**. | `tender.py:1355-1418` | `title`, `publication_date` ve **yüklenen ihale dosyalarının listesi** hiç kaydedilmiyor; çekmece düzenlemede bunları geri okumaya çalışıyor (`TenderMasterDrawer.vue:159-176`) ve okuma hep boş dönüyor. *(Çürütme turu düzeltmesi: `estimated_total`, `currency`, `source`, `tender_no` **kaydediliyor** — ama intake'e değil, `crm.save_deal` üzerinden Deal alanlarına, `crm.py:463` / `_DEAL_MUTABLE_FIELDS:79-108`.)* |
| 4 | **İki isimli tek son tarih — ve ikisi de yazılmıyor.** Giriş ekranı `submission_deadline` gönderiyor (whitelist'te yok → düşüyor); sistemin okuduğu anahtar `bid_deadline` (`_milestone("bid", …, intake.get("bid_deadline"), …)`, `tender.py:1569`). `save_deal` `tender_deadline` alanını kabul ediyor ama çekmece onu hiç göndermiyor. `bid_deadline`'ı yalnız PO panosuna gömülü eski panel yazıyor (`TenderIntake.vue:51,292`). | ↑ | Giriş ekranında girilen son başvuru tarihi **hiçbir yere ulaşmıyor**: risk çipi, SLA ve son-tarih kolonu onu göremez. |
| 5 | **Kart değeri pratikte 0.** `crm_board` değeri `flt(intake.get("contract_value") or intake.get("budget"))` ile okuyor (`tender.py:2750`); bu iki anahtar `_clean_intake` çıktısında yok. Tek yedek yol `annual_revenue` kolonu (`:2751-2752`) — **hiçbir Stabler kodu o alana yazmıyor** ve `save_deal` onu kabul etmiyor. Çekmecenin `estimated_total`'ı `deal_value`'ya gidiyor, ama `crm_board` `deal_value`'yu **hiç okumuyor**. | `tender.py:2750-2752`, `:2769` | Sanitizer'dan geçen her kayıtta kart değeri, şerit toplamı ve KPI şeridi **0**. Dahası kanban düzenleme turu, 0 olan kart değerini `deal_value`'ya geri yazıyor. |
| 6 | **Karar formu, kararın verilmediği ekranda.** GO/NO-GO, garanti, ceza %/gün ve satın alma yöntemi yalnız `TenderIntake.vue`'da — o da yalnız `PoControlBoard.vue:315`'ten mount ediliyor, yani **kazanım sonrası** ekranından. | `PoControlBoard.vue:22,315` | Katılma kararı pre-win'de veriliyor, formu post-win ekranında. Ayrıca bu panel ham Bootstrap: `buyer` düz `<input type="text">` (`TenderIntake.vue:292`), Customer doctype'ına bağlı değil — giriş çekmecesindeki Typeahead ile çelişiyor (`TenderMasterDrawer.vue:331`). |
| 7 | **Kart hazırlık yüzdesi artık var olmayan bir anahtarı sayıyor.** `crm_board` `doc_progress`'i `len([d for d in docs if d.get("status") == "ready"])` ile hesaplıyor (`tender.py:2754-2756`); ama depolanan satırları `parse_doc_requirements` normalize ediyor ve çıktısında **`status` anahtarı yok** — tamamlanma `done` alanında (`_tender_documents.py:99-118`; `status` yalnız *girdi* toleransı, `:105`). | `tender.py:2754-2756` vs `_tender_documents.py:105,118` | Belge satırı olan her kartta hazırlık **%0** görünüyor; hiç satırı olmayan kartta ise sabit **%50**. Yani boş kontrol listesi, tamamlanmış olandan iyi görünüyor. Belge merkezinin kendi ekranı doğru hesaplıyor (`readiness_pct`, `_tender_documents.py:182`) — iki ekran aynı ihale için farklı yüzde gösteriyor. |

**Yan bulgu — form katmanı tek dilde değil.** Tender'ın 27 dosyasının 19'unda hiç `ds-*`
sınıfı yok (ham Bootstrap/Tabler ile kalanlar: `BidPricing`, `DeclarantQueue`, `LogistBoard`,
`PoControlBoard`, `SourcingWorkspace`, `TenderIntake`, `TenderDocuments`,
`TenderDocumentsPanel`, `TenderDocumentChain`, `TenderExecutionFlow`, `TenderExecutiveKpis`,
`TenderTrendChart`, `TenderWorkspaceTabs` ve dört `rfq/*.vue`). `StatusIcon.vue`,
`FilterChips.vue` ve `KpiCard.vue` tender'da **hiç** kullanılmıyor; KPI şeritleri elle
yazılmış `ds-kpi*` markup'ı. `ListToolbar` yalnız `rfq/RfqList.vue:17`'de.

---

## 3 · Kusurların ortak kökü

Tek bir cümle: **bir JSON alanı, iki yazar, üçüncü bir yerde saklı sözleşme.**

```
TenderMasterDrawer.vue ──┐
                         ├──> tender.save_deal_intake ──> _clean_intake(whitelist) ──> CRM Deal.custom_tender_intake
TenderIntake.vue ────────┘                                       ▲
                                                                 │
                    sözleşme burada yaşıyor ve hiçbir ekran onu bilmiyor
```

`_clean_intake` "temizleyici" değil, fiilen **şema**: whitelist'te olmayan anahtar sessizce
yok oluyor, whitelist'te olup gönderilmeyen anahtar sessizce boşalıyor. Bu iki davranış
ayrı ayrı savunulabilir (biri XSS/forge koruması, diğeri tam-nesne PUT semantiği) ama
**birlikte** şunu üretiyor: iki ekrandan biri kaydettiğinde diğerinin verisi kayboluyor,
ve hiçbir hata mesajı çıkmıyor.

Bu yüzden aşağıdaki kararların sırası önemli: önce sözleşme, sonra ekran, en sonda kozmetik.

---

## 4 · Referans model (kısa)

Kurumsal sourcing paketleri bu problemi "olay" (event) kavramıyla çözüyor: SAP Ariba
Sourcing'de talep tek bir düz kayıt değil, RFI/RFP/açık eksiltme türlerinden bir **event**
nesnesidir ve teklifler o event'e asılır ([SAP Learning — Introducing Events within SAP
Ariba Guided Sourcing](https://learning.sap.com/learning-journeys/introducing-sap-ariba-guided-sourcing-projects/introducing-events-within-sap-ariba_dd65e098-dd00-4ba3-ba37-99f06e13f4f1)).
Bizde bu kap zaten var ve doğru yere konmuş: **RFQ = tur**, cevap `Supplier Quotation.custom_rfq`
ile tura bağlanıyor (`v83_sq_rfq_link.py:27`, `sourcing.get_rfq` tur-bazlı `responded`).
Yani mimari doğru; eksik olan bunun ekranda görünmemesi (ADR-208).

İkinci referans noktası daha bizim tarafımızdan: ERPNext'in kendi modelinde ihale-öncesi
verinin tamamı **alanlarda** yaşar, JSON overlay'de değil. Biz overlay'i bilerek seçtik
(doctype maliyeti); bedeli, overlay'in şemasının kod içinde saklı kalması. ADR-202 bu bedeli
ödemeyi değil, **görünür kılmayı** öneriyor.

---

## 5 · Kararlar (ADR)

### ADR-201 — İhale girişi tek yüzey: `TenderMasterDrawer` kalır, `TenderIntake.vue` düzenleme yetkisini kaybeder

Kanban çekmecesi ("New tender" / "Edit") ihale girişinin **tek yazarı** olur.
`TenderIntake.vue` — bugün `PoControlBoard.vue:315`'te gömülü — **salt-okuma özete**
dönüşür: son tarih/garanti/FX/GO kaydını gösterir, düzenleme kontrolü taşımaz.

*Reddedilen alternatif:* iki formu da bırakıp payload'ları birleştirmek. İki formu senkron
tutma maliyeti kalıcıdır ve kusur #1 ile #2 tekrar üretilebilir hale gelir.

### ADR-202 — Intake sözleşmesi görünür olur; sunucu sessizce düşürmez

Üç değişiklik, birlikte:

1. **Whitelist genişler** — `title`, `publication_date`, `estimated_total`, `tender_files`
   sözleşmeye girer (bugün düşüyorlar, kusur #3).
2. **Bilinmeyen anahtar sessizce düşmez.** Gönderilen ama sözleşmede olmayan anahtar
   `frappe.throw` ile reddedilir. "Kaydettim" diyen ama kaydetmeyen bir form, kaydetmeyi
   reddeden bir formdan daha pahalıdır.
3. **Kısmi güncelleme PATCH semantiğine geçer:** *gönderilmeyen anahtar korunur* (bugün
   boşalıyor, kusur #1). Sunucu-sahipli alanlar (`assigned_*`, `submitted_*`, `ready_*`,
   `go_no_go_at/by`, `result_at/by`) bugünkü gibi client'tan hiç okunmaz.

Test kancası: `test_tender_intake_items.py` desenini izleyen saf birim testi —
"yalnız `items` gönderen bir payload `go_no_go`'yu korur" ve "sözleşme dışı anahtar reddedilir".

### ADR-203 — Tek son tarih adı: `bid_deadline`

`submission_deadline` diye ikinci bir anahtar olmaz. Giriş çekmecesinin "Submission Deadline"
alanı `bid_deadline`'a yazar (etiket İngilizce kalır, anahtar tektir). Geçiş: okumada
`bid_deadline or submission_deadline` toleransı bir sürüm boyunca kalır, yazma tek anahtara
gider. Kanbandaki risk çipi ve SLA ancak bundan sonra doğru tarihi görür (kusur #4).

### ADR-204 — Kart değeri türetilir, elle girilmez

`crm_board`'un okuduğu `contract_value || budget` (kusur #5) kaldırılır; değer şu sırayla
türetilir: **(1)** deal'e bağlı Sales Order toplamı, yoksa **(2)** intake item satırları
toplamı (`items[].amount`), yoksa **(3)** `CRM Deal.deal_value`. Üçü de yoksa değer yoktur —
0 gösterilmez, "—" gösterilir. Türetme `_deal_deadlines` gibi tek bir yardımcıda toplanır.

### ADR-204b — Hazırlık yüzdesi tek yerden hesaplanır

Kusur #7'nin kaynağı, aynı sorunun iki yerde ayrı ayrı hesaplanması. Karar: `crm_board`
kendi `doc_progress` aritmetiğini yapmaz; belge merkezinin kullandığı saf fonksiyonu
(`_tender_documents.docs_summary` → `readiness_pct`) çağırır. Boş kontrol listesi için
sabit `50` kaldırılır — belge satırı yoksa yüzde **yoktur** (kartta "—"), çünkü %50 hem
yanlış hem de dolu listeden iyi görünüyor.

### ADR-205 — Belge listesi intake payload'ının parçası olmaktan çıkar

`_clean_intake` `documents`'a **dokunmaz**; prior'ı olduğu gibi taşır. Kontrol listesini
yalnız belge uçları yazar (`tender_documents.upload_/waive_/remove_tender_document`) ve
şablonu yalnız açık bir "requirement düzenle" eylemi değiştirir. Bu tek karar kusur #2'yi
kapatır ve belge merkezinin tek-kaynak iddiasını gerçekten tek kaynak yapar.

### ADR-206 — Değerlendirme formu kararın verildiği yere taşınır

GO/NO-GO, garanti tutarı + iade tarihi, ceza %/gün, sertifika gereği ve satın alma yöntemi
kanban çekmecesinin **E bölümü** olur (mockup Tab 1/Tab 2). Karar kaydedildiğinde
`go_no_go_at/by` damgası sunucuda oluşur (bugünkü davranış korunur). PO kontrol panosu
post-win ekranıdır; pre-win kararı orada durmaz.

### ADR-207 — SLA kartın üstünde görünür

`_tender_sla.py` (`DEFAULT_STAGE_SLA_DAYS`: seen 3 · go 5 · sourcing 14 · priced 3 ·
submitted 30; terminal aşamalarda eşik yok) bugün yalnız `TenderFlow.vue` /
`TenderOverview.vue`'da görünüyor. Karar: **karta aşamada geçen gün + eşik aşımı rozeti**,
şerit başlığına **eşik aşan kart sayacı**. Renk `getStatusBadgeClass` üzerinden; bileşen içi
renk haritası yazılmaz.

### ADR-208 — Tur (round) ekranda birinci sınıf olur

Veri modeli hazır (`custom_rfq`). Karar: `SourcingWorkspace` RFQ şeridi turlara göre
gruplanır (Tur 1 / Tur 2 …), her turda **cevap veren / davet edilen** oranı görünür, teklif
satırı hangi tura ait olduğunu taşır. Yeni doctype veya yeni alan **yok** — yalnız gruplama
ve etiket.

### ADR-209 — Form katmanı tek dile taşınır (`ds-*` + paylaşılan bileşenler)

Yeni bileşen açılmaz. Sıra: **(1)** giriş çekmecesi + kanban (zaten `ds-*`), **(2)** sourcing
üçlüsü (`SourcingWorkspace`, `QuotationEntryDrawer`, `rfq/*`), **(3)** belge merkezi,
**(4)** post-win panoları. Her ekranda: dense listelerde `StatusIcon`, filtrelerde
`FilterChips`, KPI şeridinde `KpiCard`, para `MoneyInput`/`ds-mono`, tarih `DateInput` +
`dd.mm.yyyy`, bölge başına tek `.btn-primary`.

### ADR-210 — Tender Master emekliliği: ERTELENDİ, ama yön sabit

16 dosya hâlâ Tender Master'a bakıyor (`api/tender_documents.py`, `sourcing.py`, `crm.py`,
`_tender_documents.py`, `tender_desk.py`, `tender_master.py`, `permissions.py`,
`_tender_master_state.py`, `composables/status.js`, `useTenderContext.js`,
`components/TenderMasterDrawer.vue`, `files/FileSlot.vue`, `TenderDocumentsPanel.vue`,
`TenderDocuments.vue`, `TenderCrm.vue`, `pages/crm/Deals.vue`) ve **belge gereksinim katalogu
tender seviyesinde orada yaşıyor** (`custom_tender_documents`, `v76_tender_master_documents.py:28`)
— yani tek-seviye mimarisiyle çelişen tek kalıntı burası. Yön: katalog şirket seviyesine
(ayarlar) taşınır, Tender Master salt-okuma arşive döner. **Bu dilimde yapılmaz.**

### ADR-211 — Garanti iadesi otomasyonu: ERTELENDİ

`guarantee_return` tarihi milestone üretiyor (`tender.py:1579`), takip elle. Bu dilimde
yalnız kart rozetine yansır; hatırlatma/otomasyon ayrı bead.

---

## 6 · Mockuplar

`docs/plans/assets/mikas-tender-workflow-mockup.html` — tek dosya, beş sekme:

| Sekme | Ne gösteriyor | Hangi ADR |
|---|---|---|
| 1 · İhale Giriş Merkezi | A müşteri / B künye / C dosyalar / D itemlar + **E değerlendirme** (yeni); altında "hangi alan nereye yazılır" sözleşme tablosu | 201, 202, 203, 206 |
| 2 · Kanban + kart çekmecesi | 13 şerit iki faz; kart anatomisi (değer, son tarih + risk, teklif sayacı 5/5, belge %, **SLA yaş rozeti**); çekmecede atama + aşama şeridi + E bölümü | 204, 206, 207 |
| 3 · Sourcing | **tur bazlı** RFQ şeridi, RFQ'dan prefill'li teklif çekmecesi, landed cost karşılaştırma + politika rozetleri, ödül paneli → PO taslağı | 208, 209 |
| 4 · Belge merkezi | lot seçici, rol kapılı yükleme satırları, hazır olma %'si, waiver; "intake kaydı bu listeyi silmez" notu | 205 |
| 5 · Kazanım sonrası | tek post-win şerit + deklarant/lojist/PO kontrol aynı verinin filtreleri; türetme kuralı tablosu | 209 |

Mockup ekran metinleri **İngilizce** (uygulama English-first), açıklama/annotasyon Türkçe.
Kırmızı `!` rozetleri bugünkü kusuru, yeşil `✓` hedefi işaretler.

---

## 7 · Uygulama dilimleri (bead önerisi)

Sıra bağlayıcı: sözleşme düzelmeden ekran taşımak, taşınan ekranın verisini de siler.

| # | Dilim | İçerik | Doğrulama |
|---|---|---|---|
| 1 | **Sözleşme** | ADR-202 + ADR-205 + ADR-203 (`_clean_intake` PATCH semantiği, bilinmeyen anahtar reddi, `documents` dokunulmaz, tek son tarih adı) | saf birim testi (`test_tender_intake_items.py` deseni) + `make check`; **DB davranışı `make test-bench`** |
| 2 | **Tek yazar** | ADR-201 + ADR-206 (çekmeceye E bölümü, `TenderIntake.vue` salt-okuma) | SPA kaynak-kontrat testi + i18n (yalnız `en.csv`) |
| 3 | **Kart doğruları** | ADR-204 + ADR-204b + ADR-207 (değer türetme, tek kaynaktan hazırlık yüzdesi, SLA rozeti/sayaç) | `test_tender_sla.py` uzatması + funnel/board kaynak testi; hazırlık için saf birim testi (aynı intake → kart % = belge merkezi %) |
| 4 | **Tur görünürlüğü** | ADR-208 (RFQ şeridi gruplama, cevap oranı) | `test_sourcing_spa.py` uzatması |
| 5 | **Form katmanı** | ADR-209 sıra (2)→(4): sourcing üçlüsü, belge merkezi, post-win panoları | ekran ekran ayrı bead; her birinde `ds-*` + paylaşılan bileşen |

Her dilim tek mikro-görev, tek atomik commit, `make check` yeşil
(`.claude/rules/00-context-budget.md`).

---

## 8 · Kapsam dışı / bilinçli ertelenen

- Tender Master backend emekliliği (ADR-210) — 16 tüketici, ayrı program.
- Tedarikçi e-posta/portalı; RFQ iletimi **bilinçli olarak insan işi** kalır
  (`mark_rfq_sent` + Communication kaydı bugünkü tasarımdır).
- Garanti iadesi otomasyonu (ADR-211).
- Teklifin UZEX'e otomatik gönderimi — E-IMZO + hukuk sınırı, `docs/plans/uzex-eimzo-feasibility.md`.
- `TenderExecutionFlow.vue`, `TenderWorkspaceTabs.vue`, `TenderDocumentChain.vue`:
  bugün API çağırmayan, tek yerden mount edilen bileşenler. Emeklilikleri form katmanı
  dilimiyle birlikte değerlendirilir, ayrı karar gerektirmez.

---

## 9 · Zafar'ın kararı gereken maddeler

1. **ADR-202/2 — bilinmeyen anahtar reddedilsin mi (`throw`), yoksa loglanıp düşülsün mü?**
   Reddetme daha dürüst; ama eski bir istemci sürümü sahadaysa kaydı bloke eder.
2. **ADR-201 — `TenderIntake.vue` salt-okumaya mı dönsün, tamamen kaldırılsın mı?**
   Salt-okuma, PO panosunda ihale künyesini görmek isteyen sourcing kullanıcısını korur.
3. **ADR-206 — E bölümü çekmecede mi, kanban kartının ayrı bir "Değerlendirme" sekmesinde mi?**
   Çekmece uzuyor; sekme bir tık ekliyor.
4. **ADR-209 sırası** — form katmanı taşıması tek büyük bead mi, ekran başına bead mi?
   (Öneri: ekran başına — 172 commit'lik bir dal istemiyoruz.)
5. **Acil yama penceresi** — sözleşme dilimi (dilim 1) beklemeden iki tek-satırlık düzeltme
   bugün merge edilsin mi? (a) çekmecenin `documents: []` göndermesini durdurmak (kusur #2),
   (b) `doc_progress`'in `"status" == "ready"` yerine `done` sayması (kusur #7). İkisi de
   davranışı yalnız düzeltme yönünde değiştirir, şema değişikliği yoktur.

---

*Kaynaklar: `docs/uat/2026-08-10-belge-merkezi/belge_merkezi_draft.html` ·
`docs/design/tender-flow-map.html` · `docs/plans/PROMPT_tender_flat_loop.md` ·
kod okuması `stabler/api/tender.py`, `sourcing.py`, `purchasing.py`, `tender_documents.py`,
`stabler/public/js/pages/tender/*`, `components/TenderMasterDrawer.vue`.*
