# Satın Alma → Ambar Zinciri — Tasarım Kurulu Kararı (2026-08-16)

Talep (Zafar): "Vendor'dan satın almadan bizim ambara girene kadar hangi aşamalar var,
biz neler yaptık, hangi aşamalar daha yapılacak? Landed cost dahil, GRN bu işin
neresinde? NetSuite, QuickBooks ya da başka en son trend ERP'ler bu işi nasıl çözüyor?
Kitabına uygun iş yapalım. Uzmanlar yetişmiyorsa gerekenleri çağıralım."

Kurul: ithalat & inbound lojistik operasyonu, **gıda güvenliği / veteriner / soğuk zincir**,
procure-to-pay & envanter muhasebesi, şüpheci/sıralamacı. Landed cost kurulunun kararı:
`docs/plans/2026-08-16-landed-cost-calculation-design-council-decision.md`.

Araştırma birincil kaynaklardan yapıldı: Oracle NetSuite Help Center, learn.microsoft.com,
help.sap.com, odoo.com/documentation, help.acumatica.com, frappe/erpnext kaynak kodu,
lex.uz ve USDA FSIS. Her iddia kaynağıyla birlikte aşağıda.

---

## KARAR: para doğruluğu önce. Uygunluk katmanı ertelendi (Zafar, 2026-08-16).

> ### ⏸️ SAHİBİN KARARI — 2026-08-16
> **Veteriner sertifikası kapısı, soğuk zincir sıcaklık kontrolü ve karantina, bu
> programın kapsamı dışındadır.** Opsiyonel adım olarak görülecek, üzerlerinde çalışma
> yapılmayacak, **gelecek özellik** olarak işaretlenmiştir → bölüm 6b.
>
> Kurulun bu konudaki bulguları dokümanda **silinmedi**, çünkü bir karar dokümanının
> işi neyin bilerek ertelendiğini kayda geçirmektir. Bulgular bölüm 6b'de duruyor;
> öncelik listesinden çıkarıldılar.

Geriye kalan zincir kusurları — ve bu program onlar üzerine kuruluyor — **paranın
doğruluğuyla** ilgili ve hepsi bugün üretimde:

1. **PO eşleşmezse Purchase Receipt satırı `rate 0.0` ile giriyor** — sadece logger
   uyarısı. Stok sıfır değerle girer, COGS kurgu olur, kanıt tek bir log satırıdır.
2. **Landed Cost Voucher'lar taslakta kalıyor** ve routed SPA sayfasında **submit butonu
   yok**. Gümrük vergisi + navlun (et ithalatında tipik olarak CIF'in **%15–30'u**)
   envantere hiç ulaşmıyor.
3. **`distribute_charges_based_on` sabit `"Qty"`** — ve stok UOM'u `Kg` olduğu için bu
   fiilen ağırlık bazlı dağıtım. Navlun için doğru, ad valorem gümrük vergisi ve sigorta
   için **yanlış**; et ithalatında birim maliyet hatası %10–20, brüt marjdan büyük.
4. **Kimseyi malı faturalamaya davet eden bir şey yok.** Sevkiyat alınıp satılabiliyor
   ve tedarikçi borcu hiç açılmıyor; `Stock Received But Not Billed` hiç kapanmıyor.
5. **Hasarlı kg deftere hiç girmiyor** — fiziksel sayım hiçbir zaman tutmaz.
6. **Gümrükten hiç GL kaydı yok.** Vergi/aksiz/KDV elle yazılan alanlar, muhasebeye
   hiç dokunmuyor; gümrük yükümlülüğü tamamen bilanço dışı.

Bunların toplam etkisi tek cümlede: **envanter ve borçlar birlikte eksik, kâr mal kabul
ayında fazla gösteriliyor.**

Ve landed cost tarafında senin istediğin şey, önümüzdeki 30 gün için dürüst cevabıyla,
**bir submit butonu ve bir dropdown'dır**. Bunu küçümsemek için değil, tam tersi için
yazıyorum: o dropdown'ın (`Qty` yerine `Amount`) et ithalatında değeri, aşağıdaki
hesapla yeni doctype'ın tamamından yüksek.

---

## 1 · Bugün zincir kodda nasıl işliyor

| # | Aşama | Doctype / ekran | Durum makinesi | GL/Stok? | Sonraki adımı ne tetikliyor |
|---|---|---|---|---|---|
| 0 | Tedarik öncesi | **yok** | — | — | — |
| 1 | Proforma Invoice | `proforma_invoice` · ProformaForm.vue | DRAFT/CONFIRMED/SUPERSEDED_BY_CI/CANCELLED — **geçiş guard'ı yok, tek doctype** | yok | hiçbir şey |
| 1b | "Import Order" | native **Purchase Order** + `custom_prepayment_type` | ERPNext | — | **%100 manuel; PI→PO kod yolu yok** |
| 2 | Commercial Invoice | `commercial_invoice` · CommercialInvoiceForm.vue (4103 satır) | BOOKED→STUFFED→GATE_IN→ON_BOARD→IN_TRANSIT→DISCHARGED→AVAILABLE→ARRIVED_AT_IRAN→DELIVERED_TO_UZBEKISTAN (guard'lı) | yok | STUFFED → taslak GRN Checklist |
| 3a | Freight Booking | `freight_booking` | Pending→Booked→In Transit→Delivered | yok | **hiçbir şey — ölü kayıt** |
| 3b | Import Container | `import_container` | CI ile aynı 10 durum | yok | ARRIVED_AT_IRAN → **taslak** %70 Payment Entry |
| 3c | Import Truck | `import_truck` | PENDING→DEPARTED_IRAN→AT_BORDER→CROSSED_BORDER→IN_TRANSIT→ARRIVED→UNLOADING→GRN_CREATED→COMPLETED | yok | CROSSED_BORDER → taslak nakliye PI |
| 3d | **Truck Receipt** | `truck_receipt` (submittable) | — | **STOK + GL BURADA** | `pr.submit()` — Purchase Receipt |
| 4 | Vet Certificate | `vet_certificate` | Pending/Approved/Rejected/Expired | yok | 2 kapı: kamyon çıkışı, GRN submit |
| 5 | Customs Declaration (GTD) | `customs_declaration` | Draft→Submitted→{Under Review, Approved, Rejected} | **GL yok** | kamyon çıkış kapısı |
| 6 | GRN Checklist | `grn_checklist` (submittable) | Pending/Receiving/Complete/Discrepancy | yok | **sadece taslak LCV** |
| 7 | Landed Cost Voucher | native ERPNext | **taslakta kalıyor** | submit edilirse GL | insan |
| 8 | Purchase Invoice | native | — | GL | **hiçbir şey tetiklemiyor** |

Kamyon çıkış kapısı (`import_truck.py:46-85`) gerçekten çalışıyor ve iyi yazılmış:
`required_for_departure` işaretli her gümrük beyannamesi **Approved** ve `cleared_date`
dolu olmalı, geçerli veteriner sertifikası olmalı, boş beyanname seti de blokaj sayılıyor.
Imports Manager gerekçe yazarak geçebiliyor. **Bu, sistemdeki en iyi kapı** — ve neyin
doğru göründüğünün örneği.

## 2 · Zincir nerede kırılıyor — 11 doğrulanmış kusur

| # | Kusur | Yer | Etkisi |
|---|---|---|---|
| 1 | ⏸️ **Stok, hiçbir uygunluk kapısı çalışmadan satılabilir oluyor** | `hooks.py:623` vs `hooks.py:736` | gıda güvenliği + regülasyon — **ertelendi, bölüm 6b** |
| 2 | ⏸️ **Yazılan herhangi bir QC notu, başarısız sıcaklık ölçümünü geçersiz kılıyor** | `truck_receipt.py:44-52` | HACCP kritik limit ihlali, kayıtlı — **ertelendi, bölüm 6b** |
| 3 | **PO eşleşmezse PR satırı rate 0.0 ile giriyor** — sadece logger uyarısı | `receipt_math.py:63-67` | stok sıfır değerle, COGS kurgu |
| 4 | **Üçlü eşleşme yok; kimse malı faturalamaya davet edilmiyor** | `api/imports.py:7067` | sevkiyat alınıp satılabilir, borç hiç açılmaz |
| 5 | **LCV taslakta kalıyor; routed sayfada submit butonu YOK** | `purchasing/LandedCostReview.vue` | gümrük+navlun envantere hiç girmiyor |
| 6 | `distribute_charges_based_on` sabit `"Qty"`; method saklanmıyor; CI'da iki çelişen sayı | `lcv.py:291`, `CommercialInvoiceForm.vue:1061` | birim maliyet hatası |
| 7 | **Batch kimliği tüm konteynerleri birleştiriyor** (`container_number` = `None`); expiry elle yazılıyor, doğrulanmıyor; `has_batch_no` yoksa batch'siz giriyor | `hooks.py:625`, `:601` | **geri çağırma imkânsız** |
| 8 | Hasarlı kg GRN varyansında sayılıyor ama **deftere hiç girmiyor** | `receipt_math.good_qty` | fiziksel sayım asla tutmaz |
| 9 | %70 avans PE taslak; `payment_70_status` elle seçilen dropdown; **%30 bacağı kodda yok**; Freight Booking ölü | `hooks.py:198` | avans maruziyeti bilinmiyor |
| 10 | Proforma'da geçiş guard'ı yok; PI ile PO bağlantısız paralel dünyalar | `proforma_invoice.py:16` | **3 numaranın kaynağı** |
| 11 | Uçtan uca sevkiyat takip ekranı yok; PR/PI/LCV'nin `/imports` altında ekranı yok | `router.js` | GL gerçeğini taşıyan belgeler görünmez |

## 3 · Dünya bunu nasıl çözüyor

### Kanonik zincir

| ERP | Zincir | Konsinye katmanı | Karantina |
|---|---|---|---|
| **NetSuite** | PO → **Inbound Shipment** → Item Receipt → Vendor Bill | ✅ tek gerçek olan | Enhanced Receipt Quarantine: Pre-Inspection Bin/Status → Pass/Fail; **Inventory Status** tahsise kapatılabilir |
| **SAP S/4HANA** | Purchase Requisition → PO → **Inbound Delivery** → Goods Receipt → **Inspection Lot + Usage Decision** → Invoice Verification | ✅ ASN katmanı | **stok tipi** olarak ("stock in quality inspection"), usage decision serbest bırakır |
| **Dynamics 365 BC** | PO → Warehouse Receipt → Put-away → Posted Receipt → Purchase Invoice | ❌ | bin/lokasyon |
| **Odoo** | RFQ → PO → Receipt → Bill (çok adımlı: Receipt → Quality → Internal Transfer → Stock) | ❌ | Quality Control Point + Input lokasyonu |
| **Acumatica** | PO → Purchase Receipt → AP Bill → Landed Costs | ❌ | ambar/lokasyon |
| **QuickBooks** | — | ❌ | ❌ |

NetSuite **Inbound Shipment**: bir kayıt **birden çok PO'nun satırlarını** taşıyabiliyor
(maks 500 satır), OneWorld'de birden çok şirket ve **para birimi** karışabiliyor. Durumlar
`In Transit → Partially Received → Complete → Closed`. Bir PO satırı bir inbound
shipment'a bağlandıysa **PO'dan doğrudan mal kabul edilemiyor**. İki opsiyonel adım:
**Transfer Ownership** (fiziksel teslimden önce mülkiyeti almak — Incoterms kancası) ve
sevkiyatı teslimden önce faturalamak.
([Inbound Shipment Management](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/chapter_1490802012.html),
[Using ISM](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_1490823161.html))

⚠️ **Ve NetSuite'in kendi tuzağı, bizim için doğrudan uyarı:** Oracle birebir yazıyor —
*"Purchase orders received through inbound shipments are not supported"* (Estimated
Landed Cost tarafından). İki maliyet motoru birbirini tanımıyor.
([ELC Considerations](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/bridgehead_4576788130.html))
Bizdeki karşılığı: **gümrük vergisinin hem GTD'de hem LCV'de sayılması.**
Kural: *GTD bir kaynak belgedir ve asla GL'e yazmaz; tek yazan LCV'dir.*

### GR/IR — mal geldi, fatura gelmedi

Beş ERP'nin beşi de bu boşluğa bir ara hesap koyuyor:

| Sistem | Hesap adı |
|---|---|
| SAP | **GR/IR clearing** |
| NetSuite | **Accrued Purchases** |
| Business Central | **Inventory Account (Interim)** + **Invt. Accrual Acc. (Interim)** |
| Odoo | **Stock Interim (Received)** |
| Acumatica | **PO accrual account** |
| **ERPNext** | **Stock Received But Not Billed** — PR: Dr Ambar / Cr SRBNB; PI: Dr SRBNB / Cr Borçlar |

**ERPNext'te bu mekanizma zaten var ve zaten çalışıyor.** Eksik olan, Acumatica'nın
ürünleştirdiği **yaşlandırma raporu** (Purchase Accrual Balance by Period, PO402000 —
Unbilled Amount / Not Received Amount / PO Accrued Amount, tedarikçi ve döneme göre,
"purchase accrual hesabını genel muhasebeyle mutabık kılmak için").
ERPNext'te `per_billed` var ama böyle bir rapor yok.
([ERPNext SRBNB](https://docs.frappe.io/erpnext/user/manual/en/stock-received-but-not-billed),
[Acumatica PO402000](https://help.acumatica.com/Wiki/ShowWiki.aspx?pageid=e67d57a0-bf6b-4656-8f21-34cffa80fa94))

**Bu bakiye, faturasız mal maruziyetinizdir.** Bugün MSA'da SRBNB her mal kabulünde
alacaklandırılıyor ve **hiç borçlandırılmıyor**, çünkü kimseyi malı faturalamaya davet
eden bir şey yok.

### Üçlü eşleşme

- **NetSuite** — 3-Way Match Vendor Bill Approval: Bill Validation → Quantity Tolerance →
  Quantity Difference → Amount Validation → Pending/Rejected/Approved. **Bill Exception**
  butonu farkları listeliyor, istisnalı faturalar **düzenlemeye kilitleniyor** ve amire
  gidiyor. Toleranslar tedarikçi/kalem/şirket seviyesinde, **23 ayrı kriter**.
- **SAP** — tolerance key aşılırsa fatura **ödemeye bloke**; serbest bırakma açık işlem.
- **Odoo** — Bill Control policy (`On ordered` vs `On received quantities`) + `Should Be
  Paid` alanı **Exception** değeriyle. **İşaretler, bloke etmez.**
- **Acumatica** — fark Purchase Price Variance hesabına.

### Gıda / bozulabilir kontroller

| Yetenek | Kim natively veriyor |
|---|---|
| Lot + expiry | hepsi. **Odoo** dört hesaplanmış tarih (Expiration/Best Before/Removal/Alert) ve **lot numarası olmadan mal kabul valide edilemiyor** |
| **FEFO** | Odoo (zorunlu removal strategy), BC (`Pick According to FEFO`) |
| **Varışta kalan raf ömrü < N gün ise reddet** | **yalnız SAP** (SLED/BBD kontrolü, mal kabulde) |
| İnceleme, stok kullanılabilirliğini kapatıyor | **SAP** (en güçlü), NetSuite (Inventory Status), Odoo (QCP) |
| **Sertifika (veteriner/helal/menşe) zorunlu kapı** | **beşinin hiçbirinde yok** — evrensel olarak özel geliştirme |
| **Soğuk zincir sıcaklık kaydı** | **beşinin hiçbirinde yok** |
| Gümrük beyannamesi birinci sınıf nesne | **yalnız SAP GTS** (ayrı ürün) |

Yani: **stabler'ın `Vet Certificate` ve soğuk zincir kontrolü yapması, dünya standardının
ötesinde bir şey denemesi demek — sadece sırası yanlış kurulmuş.** Bu kötü haber değil;
düzeltilecek olan mimari değil, bir `if` bloğu ve bir ambar.

---

## 4 · Kararlar (ADR)

### ADR-101 — Yeni "Inbound Shipment" doctype'ı AÇILMAYACAK

`Import Container` deniz bacağının konsinye kaydı, `Import Truck` kara bacağının.
MSA Bendar Abbas'ta yükü bölüyor: bir konteyner N kamyona dağılıyor, bir kamyon M
konteynerden konsolide oluyor. NetSuite'in Inbound Shipment'ı **tek** kayıt, çünkü
tedarikçiden kapıya **tek taşıma** modelliyor. MSA'nın çoktan-çoğa yapısını tek kayda
sıkıştırmak, kimsenin güvenmediği bir durum alanı ve bir torba link üretir.

Eksik olan belge değil, o katmanı işlevsel kılan **üç özellik** — ve ikisinde de yok:
(a) **satır** taşıması, sadece durum değil; (b) bir PO satırı ona bağlandıysa PO'dan
doğrudan mal kabul edilememesi; (c) teslimden önce **maliyetlenebilir ve faturalanabilir**
olması. `Commercial Invoice PO Link`, `allocated_qty`/`allocated_amount` alanları
tanımlanmış ama **hiçbir kod tarafından yazılmamış** haliyle, bu katmanın yarım bırakılmış
hali. Tamamlanacak olan o.

### ADR-102 — ⏸️ ERTELENDİ · Stok karantinaya girer; GRN Checklist "usage decision" olur

> **Zafar kararı 2026-08-16: gelecek özellik.** Aşağıdaki tasarım kayıt için korunuyor;
> uygulanmayacak, bead açılmayacak. Bkz. bölüm 6b.

**Truck Receipt stok yazan belge olarak kalır** — gerçek fiziksel olay odur. Değişen
hedef ve durum:

- PR `WH-Quarantine-<site>`'a yazar, satılabilir ambara değil. Frappe'de SAP'ın "stok
  tipi" karşılığı yok; **karantina bir ambardır** ve anlamı taşıyan şey serbest bırakmadır.
- Karantinadan çıkış, ERPNext'in kendi doğası gereği zaten korunuyor: satılabilir ambarda
  olmayan stok sevk edilemez. Ek outbound hook'a v1'de gerek yok.
- **GRN Checklist submit = usage decision.** `usage_decision`: Accept / Accept with
  deviation / Reject / Return. Submit'te **Material Transfer** Stock Entry yazar
  (karantina → ana ambar) — *mal kabul değil, transfer.* Bu ayrım kritik: transfer
  değerlemeye dokunmadığı için LCV orijinal Purchase Receipt'e bağlı kalır ve maliyet
  transfer edilen stoğa olduğu gibi akar. Landed cost iş kolu ile karantina iş kolu
  **böylece birbirinden bağımsız kalır.**
- Serbest bırakma kapıları, hepsi sert: mal kabul tarihinde geçerli veteriner sertifikası;
  UZ GTD `Approved` + `cleared_date`; `variance_category` ∈ {NORMAL, MINOR}. MAJOR →
  Imports Manager gerekçeli override (kamyon çıkışındaki mevcut desen). CRITICAL → blok.

Odoo'nun çok adımlı mal kabulü (Input lokasyonu → internal transfer) **kopyalanmayacak**:
o ambar yerleşimi modelliyor, yasal bir hold değil, ve veteriner/GTD kapısına asılacak
yer bırakmıyor.

### ADR-103 — ⏸️ ERTELENDİ · Sıcaklık: not ile bypass silinir, blokaj serbest bırakmaya taşınır

> **Zafar kararı 2026-08-16: gelecek özellik.** Kayıt için korunuyor. Bkz. bölüm 6b.

`if not qc_notes` dalı **silinir**. Sayısal bir kritik limiti serbest metinle geçersiz
kılan bir alan, kod tabanındaki en tehlikeli satırdır.

Ama blokaj **mal kabule konmaz** — kapıdaki kamyonu içeri alamamak, tam da bypass'ın
var olma sebebidir. Başarısız ölçüm **karantinadan çıkışı** bloke eder. Override:
**submitter'dan farklı** bir kişi, kapalı listeden gerekçe kodu, batch bazında.
Serbest metin, 2 numaralı kusurun ta kendisidir.

### ADR-104 — Rate 0.0 sert blok — ama manuel rate alanıyla birlikte

Truck Receipt `validate` içinde, PO satırına çözülemeyen veya rate ≤ 0 olan her satır
için `frappe.throw`. Logger uyarısı değil.

⚠️ **Tek başına gönderilirse tuzak:** PO bağı bugün zaten sık kopuyor (10 numaralı kusur),
yani bu blokaj mal kabulü kilitler. **Aynı PR'da Truck Receipt satırına manuel `rate`
alanı gelecek.** Para birimi ve UOM PO satırından okunacak — bu, sabit kodlu `"USD"` ve
`"Kg"` değerlerini de siler.

### ADR-105 — PI → PO üretir; PI, PO olmaz

Proforma `rate` vs `docs_price` ve `cash_difference` taşıyor — bu bir pazarlık artefaktı.
Onu native, GL'e komşu, ERPNext yükseltmelerine açık bir PO'nun içine itmek her stok
raporunu kirletir. Ayrı kalsınlar; PI **tek fiyatlı temiz bir PO doğursun**.

Hangi fiyat: **`rate` (agreed) PO'ya gider.** Ödenen odur, borç odur, envanterin maliyeti
odur. `docs_price` yalnız Container/GTD üzerindeki gümrük değerleme tabanını besler.

Proforma'ya eksik geçiş guard'ı eklenir: DRAFT→CONFIRMED için her satırda `item_code`
(serbest metin değil), qty, uom, `rate > 0`, para birimi, tedarikçi, Incoterm zorunlu.

### ADR-106 — Batch kimliği ve expiry (veri bütünlüğü gerekçesiyle kapsamda)

`container_number` gerçekten geçirilir. Expiry `has_batch_no` olan kalemlerde zorunlu ve
`> mal kabul tarihi` olarak doğrulanır.

**Kapsamda kalma gerekçesi uygunluk değil, veri bütünlüğü ve maliyet doğruluğu:**
birleşmiş bir batch hareket ettikten sonra geriye dönük bölünemez, yani her gecikme günü
kalıcı olarak onarılamaz kayıt üretiyor; ve ERPNext'in batch bazlı değerlemesi bu kimliğe
dayanıyor.

Üretim tarihinden hesaplanan expiry, tesis onay numarası, kesim tarihi, tür, menşe gibi
tam batch öznitelik seti **ertelendi** (bölüm 6b): 7 kiracıda item master verisi
gerektiriyor ve muhtemelen henüz yok.

### ADR-107 — GR/IR = Stock Received But Not Billed + yaşlandırma raporu

ERPNext mekanizması **zaten var, açılacak** — yeniden yazılmayacak. Kurallar: şirket
başına tek SRBNB hesabı, elle asla yazılmaz, Journal Entry ile asla kullanılmaz, her
Purchase Invoice'ta `update_stock` **kapalı** (stok PR ile zaten girdi; açık olursa çift
sayar). Tek oluşturma yolu Purchase Receipt → Purchase Invoice olur.

Yaşlandırma raporunun tutması gereken mutabakat:
`Σ Net SRBNB (rapor) = SRBNB hesabının dönem sonu GL bakiyesi`. Tutmuyorsa biri SRBNB'ye
JE yazmış ya da `update_stock` açık bir PI geçmiştir.

Bakiyenin yönü: **Unbilled** (alacak, mal geldi fatura yok) → 30 gün üstü takip, 60 gün
üstü tedarikçiden yazılı teyit, 90 gün üstü Zafar'a eskalasyon. **Not-Received** (borç,
fatura var mal yok) → **zarar maruziyeti**, 15 gün içinde takip.

### ADR-108 — Landed cost: SAP'ın blok modeli değil, fatura hep kaydedilir

Üçlü eşleşmede **SAP modeli benimsenir, NetSuite'inki değil**: fatura **her zaman
kaydedilir**. Kaydı bloke etmek (NetSuite) SRBNB'yi kirli bırakır ve borçları eksik
gösterir — MSA'da zaten var olan kusurun ta kendisi. Bunun yerine: oran/tutar ihlali →
fatura kaydolur, `on_hold = 1` + `hold_comment` = istisna gerekçesi (**ERPNext'te native,
açılacak**); miktar ihlali tolerans içindeyse kaydolur ve yalnız raporda işaretlenir.

Tolerans önerisi (dondurulmuş/soğutulmuş et — catchweight, glaze ve drip loss gerçek):

| Test | Tolerans | Taban |
|---|---|---|
| Faturalanan kg vs alınan kg | **±%2** satır bazında | veya 50 kg |
| Alınan kg vs sipariş kg | **±%5** | veya 100 kg |
| Faturalanan oran vs PO oranı | **%0** | 0,005 USD/kg yuvarlama |
| Fatura toplamı | ±%1 | 250 USD |

### ADR-109 — Landed cost iş kolu yeniden sıralanıyor

Önceki landed cost kurulu kararı (ADR-001…005) teknik olarak geçerli. Ama sırası
değişiyor ve bir maddesi güçleniyor:

**Güçlenen:** `distribute_charges_based_on` için doğru varsayılan **`Amount`**, `Qty`
değil. Et ithalatında bunun büyüklüğü ölçülebilir: karışık bir sığır konteynerinde
kemikli et ile bonfile **aynı kiloda 4 kata kadar** değer farkı taşır. `Qty` bazıyla ad
valorem her masraf ucuz-ağır kalemlere aşırı yüklenir; birim maliyet hatası kolaylıkla
**%10–20**, yani MSA'nın brüt marjından büyük. Bu, "seçenek eklemek" değil, **yanlış
sayıyı düzeltmek**.

**Ertelenen:** yeni `Landed Cost Calculation` doctype'ı + 4 child table + 6 method'lu
motor + çoklu voucher adapter + 8 patch + 7 kiracı bayrak rollout'u. Gerekçe aşağıda
(bölüm 7), ve bu **Zafar'ın kararı** — kurul öneriyor, iptal etmiyor.

### ADR-110 — Mülkiyet devri / Goods in Transit: ERTELENDİ, ama karar senin

Mal haftalarca gemide, USD/IRR/UZS dünyasında. Mülkiyet ne zaman geçtiği envanterin ne
zaman varlık olduğunu, hangi günün kurunun maliyeti dondurduğunu ve batan gemide kimin
zarar ettiğini belirler. Bugün stok Truck Receipt'te doğuyor — haftalarca geç, yanlış
kurla, ve tüm sefer boyunca bilanço envanteri eksik gösteriyor.

Doğrusu, NetSuite'in *Transfer Ownership* adımı gibi, **Import Container** üzerinde:
`incoterm`, `incoterm_place`, `title_transfer_event`, `title_transfer_date`,
**`title_transfer_exchange_rate`** (dondurulur). FOB/CIF/CFR → ON_BOARD, konşimento
tarihi. EXW → STUFFED. DAP/DDP → ARRIVED_AT_IRAN.

**Neden erteleniyor:** stoğun *ne zaman var olduğunu* değiştiriyor — 30 günlük listedeki
1–3 numaralı işlerin yeniden yazdığı tam da o yüzey. İkisi paralel yapılamaz.

⚠️ **Ama şüpheci üyenin kendi görüşüne karşı en güçlü argümanı burada, ve tutanağa
geçiyor:** *ucuz düzeltmelerin her biri, kurulun eninde sonunda değiştireceği bir model
altında stok defteri geçmişi yazıyor. Üç yıllık değerlemeyi yeniden ifade etmek, hiç
yanlış ifade etmemekten çok daha pahalıdır.* MSA 18 ay içinde dış yatırım, bağımsız
denetim veya 20 kiracıya sıçrama bekliyorsa, mülkiyet devri modelini **şimdi** kurmak
ucuz yoldur. Bu bilgi kurulda yok — sende var.

---

## 5 · Olması gereken zincir

| # | Belge | Neyi kapatır | Ne doğurur |
|---|---|---|---|
| 0 | Supplier Quotation *(opsiyonel)* | fiyat geçmişi | — |
| 1 | **Proforma Invoice** → CONFIRMED | ticari şartlar, ikili fiyat, Incoterm | **taslak Purchase Order** |
| 2 | **Purchase Order** (submitted) | **maliyet oranının var olduğu tek yer** | ödeme planı (Payment Terms Template) |
| 3 | **Commercial Invoice** | tedarikçinin sevk miktarı gerçeği; PI'ı supersede eder | konteyner satır tahsisleri |
| 4 | **Import Container** | vapur milestone'ları; *(Faz 2: mülkiyet devri)* | avans PE, navlun tahakkuku |
| 5 | **Customs Declaration** | kamyon çıkışı *(mevcut)* ⏸️ *(stok serbest bırakma ertelendi)* | LCV'ye vergi/aksiz satırları |
| 6 | **Import Truck** | İran çıkış kapısı *(mevcut, korunuyor)* | nakliye PI |
| 7 | **Truck Receipt** | fiziksel miktar; **rate 0 sert blok + manuel rate** | Purchase Receipt ⏸️ *(karantina ertelendi)* |
| 8 | **GRN Checklist** | mutabakat / varyans ⏸️ *(usage decision ertelendi)* | LCV |
| 9 | **Purchase Invoice** | üçlü eşleşme, SRBNB'yi kapatır | GL |
| 10 | **Landed Cost Voucher** | gerçekleşen maliyet — **submit edilebilir**, `Amount` bazlı | GL, değerleme |

Rol değişikliği: Freight Booking ölü kayıt olmaktan çıkıp **siliniyor** (bkz. bölüm 7).
GRN Checklist'in "usage decision"a dönüşmesi ertelendi (bölüm 6b); bugünkü mutabakat
rolünde kalıyor.

---

## 6 · 30 günlük liste — REVİZE (uygunluk katmanı çıkarıldı)

Sıra artık tamamen **para doğruluğu**. Uygunluk maddeleri bölüm 6b'ye taşındı.

| # | İş | Kapattığı kusur | Boy | Bağımsız gönderilebilir? |
|---|---|---|---|---|
| **1** | **LCV submit butonu** routed sayfaya taşınır; ölü `imports/LandedCostReview.vue` **aynı PR'da silinir**; `unitCostAnalysis` kartı kurtarılır; toast metinleri 5 dilde düzeltilir | 5 | S | Evet — Vue only |
| **2** | **`distribute_charges_based_on` açılır ve kalıcı yazılır** (`Qty` \| `Amount`), varsayılan **`Amount`**; ilk submit'ten sonra server-side **dondurulur** | 6 | S/M | Evet |
| **3** | **Rate 0 sert blok + Truck Receipt satırına manuel `rate`** — ikisi **aynı PR'da**; para birimi ve UOM PO satırından okunur (sabit `"USD"`/`"Kg"` silinir) | 3 | S/M | Evet |
| **4** | **Purchase Receipt'ten "Fatura oluştur"** — ERPNext'in kendi `make_purchase_invoice` mapper'ı (o `update_stock`'u doğru kuruyor); artı **faturalanmamış mal kabulleri listesi** | 4 | M | Evet |
| **5** | **Hasarlı kg deftere girsin** — ERPNext'in native `rejected_qty` + `rejected_warehouse` alanlarını aç. Yeni doctype yok, yeni ambar mantığı yok | 8 | S | Hayır — `test-bench` |
| **6** | **Batch = konteyner** — `batch_name`'e gerçek `container_number` geçir; `has_batch_no` olan kalemde expiry zorunlu ve `> mal kabul tarihi` | 7 | S/M | Hayır — `test-bench` |

Bir günün altındaki dolgular: %70 avans PE'yi **submit et** ve `payment_70_status`'u
salt-okunur türetilmiş yap (9) · Proforma geçiş guard'ı (10) · ölü `Freight Booking`
kaydını sil.

**⚠️ 3 numara tek başına gönderilemez.** Rate 0 blokajı yalnız başına giderse, PO bağı
kopan her sevkiyatta mal kabulü kilitler — ve PO bağı bugün zaten sık kopuyor (10 numaralı
kusur). Manuel `rate` alanı **aynı PR'da** olmak zorunda.

**6 numara neden hâlâ listede — uygunluk gerekçesiyle değil.** Batch düzeltmesi burada
**veri bütünlüğü** maddesi: birleşmiş bir batch hareket ettikten sonra geriye dönük
**bölünemez**, yani gecikilen her gün kalıcı olarak onarılamaz kayıt üretiyor. Ayrıca
ERPNext'in batch bazlı değerlemesi bu kimliğe dayanıyor, yani doğrudan maliyet doğruluğu
konusu. İzlenebilirlik faydası bonus. S/M boyutunda; yine de kesmek istersen tek maliyeti
şudur: bugünden sonra üretilen batch'ler de onarılamaz olur.

**Hasarlı kg (5 numara) — kurulda anlaşmazlık vardı, başkanın hükmü:** şüpheci "hiç alma,
`received = gross − damaged`" dedi. Ama hasarlı mal fiilen sizin zilyetliğinizde ve
defterde görünmediği sürece **fiziksel sayım hiçbir zaman tutmaz** — bu bir muhasebe
kusuru, uygunluk kusuru değil. Pahalı sürüm gerekmiyor: ERPNext'in native alanlarını
açmak yeter, S boyutunda.

**Toplam:** ~15–22 geliştirici-günü (uygunluk maddeleri çıkınca 30 günlük listeden
~8 gün düştü), kiracı başına kurulum yok, ~15 yeni çeviri satırı.

---

## 6b · GELECEK ÖZELLİKLER — ertelendi (Zafar kararı, 2026-08-16)

Bu maddeler üzerinde **çalışma yapılmayacak**, bead açılmayacak, tasarım turu
koşulmayacak. Kurulun bulguları burada kayıt altında duruyor ki, gün geldiğinde işe
sıfırdan başlanmasın.

| Madde | Kurulun bulgusu (kayıt için) | Boy |
|---|---|---|
| **Karantina ambarı + serbest bırakma** | Bugün stok, Truck Receipt submit'te doğrudan satılabilir ambara giriyor; hiçbir uygunluk kapısı öncesinde çalışmıyor. Önerilen: PR `WH-Quarantine-<site>`'a yazar, GRN Checklist submit **Material Transfer** ile serbest bırakır. Kritik tasarım notu: serbest bırakma **mal kabul değil transfer** olmalı — transfer değerlemeye dokunmadığı için LCV orijinal PR'a bağlı kalır ve landed cost iş kolu bundan **etkilenmez** | M |
| **Sıcaklık kapısı** | `truck_receipt.py:44-52` — `if not qc_notes` dalı, sayısal kritik limiti serbest metinle geçersiz kılıyor. `temperature_check_passed = 0` yazılıp bir daha hiç okunmuyor | S (silme) / M (deviation kaydıyla) |
| **Veteriner sertifikası kapısının yeri** | Kapı GRN submit'te çalışıyor, stok ise bir aşama önce giriyor. Ayrıca sertifika **yalnız Commercial Invoice'a** bağlı; konsinye konteyner ve kamyona bölündüğü için tür/tesis/kg kapsamını ifade edemiyor | M |
| **`Import Certificate` + `Certificate Coverage` modeli** | Veteriner/sağlık, helal, menşe, CoA ve **ithalat izni** ayrı sertifika tipleri; her biri farklı şeyi kapatıyor. 7 kiracıda canlı veri migrasyonu gerektiriyor | L |
| **Tam batch öznitelik seti** | Üretim/kesim tarihi, tesis onay numarası, tür, menşe, raf ömrü. Item master verisi gerektiriyor, muhtemelen henüz yok | M |
| **Varışta kalan raf ömrü eşiği** | Beş büyük ERP'den yalnız SAP'ta native. **Benimsenme uyarısı kayıtta:** sevkiyatların çoğunda tetikleneceği için iki hafta içinde bir tıklamaya dönüşür — yapılırsa waiver'sız sert blok olmalı | M |
| **Zorunlu FEFO** | Kurul zaten **kesilmesini** önermişti: depocu ekranda FEFO batch'ini seçip başka paleti sevk eder, sonuç fiziksel paletle eşleşmeyen sistem batch'leri — FEFO'suz olmaktan kötü | — |
| **`Cold Chain Deviation` doctype** | Bir QA fonksiyonu gerektiriyor; yoksa notu yazan kişi kararı da girer ve doctype fazladan satırlı tiyatro olur | M |

**Bu ertelemenin programa etkisi: yok.** Yukarıdaki maddelerin hiçbiri 30 günlük listenin
6 maddesinin önkoşulu değil, ve karantina ileride eklenirse — Material Transfer olarak
modellendiği sürece — landed cost tarafında hiçbir şeyi yeniden yazdırmıyor.

**Bu ertelemenin taşıdığı risk, kayıt için:** gıda güvenliği üyesi mevcut sırayı P0 olarak
işaretledi ve tespitini şöyle özetledi — *"bu zayıf kontrol değil, kontrol yokluğudur"*;
`temperature_check_passed = 0` kaydı, limitin aşıldığının bilindiğini gösteren saklı bir
belgedir. Bu risk **kabul edilmiş bir iş kararıdır**, çözülmüş değil.

---

## 7 · Kesilenler ve ertelenenler

| Kesilen | Neden |
|---|---|
| **`Landed Cost Calculation` doctype + 4 child table + 6 method + çoklu voucher adapter + 8 patch + 7 kiracı bayrağı** | 5 numaralı kusur *"sayfada submit butonu yok"*. O bir butondur, paralel bir değerleme modeli değil. Ayrıca ADR-110 (Goods in Transit) sonra gelirse LCC'nin girdi kümesi değişir ve **yeniden yazılması garanti** |
| **Satır bazlı 6 allocation method** | MSA'nın masrafları gümrük, navlun, komisyoncu. İki baz yeter: `Qty` ve `Amount` |
| **`Import Lane SLA` doctype** | MSA'da olmayan bir sorunu çözüyor. Kimse lane hedeflerini güncellemez; güncellenmeyen SLA yalan söyleyen bir dashboard'dur |
| **18 kolonlu / 16 düğümlü sevkiyat takip ekranı** | 18 kolon × 5 dil × 7 kiracı etiket bakımı. Altı kolonla tek ekranda listelenebilecek bir iş için |
| **Zorunlu FEFO** | Bölüm 8'e bakınız — bir ayda delinir, ve delindiğinde izlenebilirliği *aktif olarak yalancı* yapar |
| **`Vet Certificate` → `Import Certificate` + `Certificate Coverage` migrasyonu** | Et ithalatçısı için yön doğru, ama 7 kiracıda canlı veri migrasyonu ve karantina işiyle kafa kafaya çarpışıyor. **Faz 2** |
| **`Cold Chain Deviation` submittable doctype (QA-only disposition)** | Bir QA fonksiyonu gerektiriyor. QA kararını notu yazan kişi giriyorsa, doctype fazladan satırlı tiyatrodur |
| **GR/IR yaşlandırma + tolerans motoru + ay-sonu close pack** | Purchase Invoice'lar **hiç yokken** GR/IR yaşlandıramazsın. Önce 6 numara, bir çeyrek işlet, sonra raporla |
| **PO prepayment schedule doctype** | 70/30 bir ödeme vadesidir. ERPNext **Payment Terms Template** kullan |
| **`Freight Booking`'i maliyet sözleşmesine yükseltmek** | Ölü kaydı yükseltme. Sil |

**Maliyet, dürüstçe.** 30 günlük liste: ~20–30 geliştirici-günü, artı kiracı başına bir
günlük kurulum ve 15–25 yeni çeviri satırı. Tam program: 8–14 geliştirici-ayı, birkaç yüz
çeviri satırı × 5 dil, canlı kiracılarda sertifika veri migrasyonu ve tek bench'te 7
kiracıyı birden etkileyecek rollout riski — üstüne kalıcı bakım vergisi.

**Farkın satın aldığı:** denetlenebilir landed cost, yoldaki mal için tahakkuk muhasebesi,
gerçek sertifika kapsamını yansıtan uygunluk modeli, denetlenebilir üçlü eşleşme.
**Satın almadığı:** sertifikasız et satma riskinde herhangi bir azalma (onu 2 numara
yapıyor), geri çağırma hassasiyetinde iyileşme (3 numara), veya kayda değer daha iyi bir
COGS (4 ve 5 numara işin çoğunu yapıyor).

---

## 8 · Benimsenme riski — hangi kontrol bir ayda delinir

**Bir ayda delinecek olan: zorunlu FEFO.** Depocu soğuk hava deposunda önde duran paleti
alır. Sistem reddeder. Depocu ekranda FEFO batch'ini seçer ve **başka bir paleti sevk
eder.** Artık fiziksel paletle eşleşmeyen sistem batch'leriniz var — geri çağırmanın tam
ihtiyaç duyduğu anda yalan söyleyen izlenebilirlik. FEFO'suz olmaktan kötüdür.

**Her gün override talebi üretecek olan: varışta kalan raf ömrü eşiği.** Brezilya veya
Hindistan'dan dondurulmuş deniz yolu sevkiyatı raf ömrünün büyük kısmı gitmiş halde gelir.
Sevkiyatların çoğunda tetiklenen bir kapı, iki hafta içinde bir tıklamaya dönüşür.

Bundan çıkan tasarım kısıtları:

- Kiracı başına **haftada birden sık** tetiklenen bir kapı ya **sert** bloklamalı ve
  waiver'ı hiç olmamalı, ya da var olmamalı. Sık kapıda waiver ölü kontroldür.
- Gerçekle temasta ayakta kalan tek override: **submitter'dan farklı bir kişi**, kapalı
  listeden gerekçe kodu. Serbest metin, 2 numaralı kusurun ta kendisidir.
- Her override **sayılabilir** olmalı. Gerekçe dağılımı haftalık gözden geçirilir; %80'i
  "Diğer" ise kapı ölmüştür — ya sil ya eşiği düzelt.
- Tatmin edici eylemi Frappe Desk'te olan hiçbir kapı olmayacak. Repo kuralı oraya link
  vermeyi yasaklıyor; SPA'nın temizleyemediği bir kapı, insanlara SPA'yı bırakmayı öğretir.
- Her yeni blokaj mesajı = 5 dil satırı × 7 kiracı. Çevrilmemiş blokaj, yok sayılan
  blokajdır.

---

## 9 · Bir sevkiyatın yevmiye haritası

| # | Olay | Borç | Alacak | Bugün var mı? |
|---|---|---|---|---|
| 1 | %70 avans ödendi | **Verilen Sipariş Avansları** (varlık) | Banka/Kasa USD | Kısmen — *tahsis edilmemiş* avans + hayalet taslak PE |
| 2 | Mülkiyet geçti (FOB, gemide) | Yoldaki Mal (Deniz) | SRBNB | **Yok** *(ADR-110, ertelendi)* |
| 3 | Truck Receipt | Stok — **Karantina** | SRBNB | Var, ama satılabilir ambara |
| 4a | GTD — ithalat vergisi | Değerlemeye Dahil Giderler | **Gümrük Vergisi Borcu** | **Yok — gümrükten hiç GL yok** |
| 4b | GTD — aksiz | Değerlemeye Dahil Giderler | **Aksiz Borcu** | **Yok** |
| 4c | GTD — ithalat KDV'si | **İndirilecek KDV** | **Gümrük KDV Borcu** | **Yok** *(dışlama mantığı var, kayıt yok)* |
| 5 | Navlun/komisyoncu tahakkuku | Değerlemeye Dahil Giderler | **Tahakkuk Eden Landed Cost** | **Yok** |
| 6a | Tedarikçi faturası (`agreed_total`) | **SRBNB** | Ticari Borçlar USD | Yalnız `Suppliers.vue`'daki bir butonla |
| 6b | Avansın mahsubu | Ticari Borçlar USD | Verilen Avanslar | **Yok** |
| 7 | LCV submit | Stok — Karantina | Değerlemeye Dahil Giderler | **Taslakta kalıyor** |
| 8 | Hasarlı kg zararı | Hasarlı Mal Zararı | Stok — Karantina | **Yok — deftere hiç girmiyor** |
| 9 | Tedarikçi/sigorta talebi | Talep Alacakları | Hasarlı Mal Zararı | **Yok** |
| 10 | USD borç ve avansların kur değerlemesi | Kur Farkı G/Z | Ticari Borçlar USD | **Yok** |

**Bugünkü net etki:** mal stoğa yalnız PR oranıyla giriyor — gümrüksüz, navlunsuz,
KDV'siz, hasarsız ve sıklıkla **borçsuz**.

Gümrük vergisi + aksiz + navlun, Özbekistan'a et ithalatında tipik olarak **CIF'in
%15–30'u**. Bunların hiçbiri envantere ulaşmıyor ve gümrük yükümlülüğü tamamen bilanço
dışında. Envanter ve borçlar birlikte eksik, kâr mal kabul ayında fazla, sonra nakit
gider olarak çıkınca eksik gösteriliyor.

---

## 10 · İkili fiyatlandırma (agreed vs docs) — muhasebe ve denetim maddesi

Tarafsız olarak. **IAS 2.10–11** uyarınca stok maliyeti, *fiilen ödenen veya ödenecek*
alış bedeli + ithalat vergileri + iade edilemeyen vergiler + taşıma, ticari iskontolar
düşülerek. Bu **`agreed_total`**'dır — `rate`/`amount`, `docs_price` değil. **DTÖ
Gümrük Kıymeti Anlaşması md. 1** uyarınca gümrük vergisi matrahı da işlem değeri —
yine fiilen ödenen veya ödenecek bedel. **Yani aynı rakam iki sorunun da doğru cevabı**,
ve `cash_difference` bir muhasebe kategorisi değil: işletmenin ödemekle yükümlü olduğu
tutar ile beyan edilen belgelerde gösterilen tutar arasındaki fark.

Defterdeki sonuçları: envanter ve borçlar **ikisi de** `agreed_total` taşımalı. Yalnız
`docs_total` kaydedilirse envanter ve borçlar eksik, brüt marj fazla gösterilir — ta ki
nakit çıkana kadar, o an ödemenin karşılığı bir yükümlülük bulunmaz. `cash_difference`
bir GL adresine ve bir karşı tarafa sahip olmalı; yalnız arayüzde duran bir sayı olamaz.

Maruziyet: eksik beyan edilen bir kıymet, vergi, KDV, ceza ve faiz için **koşullu
yükümlülük** doğurur (IAS 37 — muhtemelse karşılık ayır, mümkünse dipnotta açıkla).
Sistemleştirilmiş bir ikili fiyat alanı, denetçi gözünde **ISA 240 kapsamında bir hile
riski faktörüdür** (yönetimin kontrolleri aşması), ve kayıt dışı nakit tasfiye
Özbekistan'da kambiyo ve AML soruları doğurur.

**Alanı silmeyin** — denetim izini yok etmek izin kendisinden kötüdür. Görünür olması
gereken yerler: PI-CI drift raporu, SRBNB yaşlandırması, ve tedarikçi/dönem bazında
`Σ agreed_total` ile `Σ docs_total`'ı mutabık kılan daimi bir çizelge.

⚠️ **Kurul, sistemde herhangi bir değişiklik yapılmadan önce, uygulamanın kendisi
hakkında profesyonel vergi ve hukuk danışmanlığı alınmasını tavsiye eder.** Bu doküman
muhasebe muamelesini ve maruziyeti tarif eder; uygulama hakkında tavsiye vermez.

---

## 11 · Zafar'ın kararı gereken maddeler

1. **`Landed Cost Calculation` doctype'ı: ertelensin mi, yapılsın mı?** Kurul erteleme
   öneriyor (bölüm 7). Karşı argüman güçlü ve senin bilgine bağlı: 18 ay içinde dış
   yatırım, bağımsız denetim veya 20 kiracıya sıçrama bekliyor musun? Evetse ADR-110
   (mülkiyet devri) ile birlikte **şimdi** yapmak ucuz yol.
2. **Kaç LCV taslakta bekliyor, tutarı ne?** (Önceki karar dokümanından devreden madde,
   hâlâ ölçülmedi. Bu sayı büyükse envanter **şu anda** eksik değerlenmiş demektir.)
3. **Ay-sonu kapanışını kim koşacak?** SRBNB yaşlandırması ve close pack, onları okuyan
   bir muhasebeci yoksa yazılmamalı — bu yüzden 30 günlük listede yok, 4 numaranın bir
   çeyrek işletilmesinden sonraya bırakıldı.
4. **`Amount` varsayılanı onaylıyor musun?** 2 numaralı iş `distribute_charges_based_on`
   varsayılanını `Qty`'den `Amount`'a çeviriyor. Bu, bugünden sonra oluşan voucher'ların
   birim maliyetini değiştirir (mockup'ta canlı görülebilir). Geçmiş voucher'lara
   dokunmaz.
5. **İkili fiyatlandırma** — bölüm 10, profesyonel danışmanlık maddesi.

*(Kapanan madde: "QA/gıda güvenliği fonksiyonu var mı?" — uygunluk katmanı ertelendiği
için konusuz.)*

---

Referanslar — kod: `stabler/stabler/imports_module/hooks.py`, `receipt_math.py`,
`departure_math.py`, `packing_math.py`, `lcv_math.py`, `stabler/api/imports.py`,
`stabler/api/lcv.py`, `doctype/{proforma_invoice,commercial_invoice,import_container,
import_truck,truck_receipt,vet_certificate,customs_declaration,grn_checklist}`.
Dış kaynaklar bölüm 3'te bağlantılı; Özbekistan mevzuatı için
[lex.uz 686904](https://lex.uz/acts/686904),
[USDA FSIS Uzbekistan](https://www.fsis.usda.gov/inspection/import-export/import-export-library/uzbekistan),
[uztradeinfo uygunluk sertifikası](https://uztradeinfo.uz/procedure/254?l=en).
Özbekistan EAEU **üyesi değil, gözlemcidir** — TR CU 034/2013 ve 021/2011'in
uygulandığı varsayılmamalıdır.
