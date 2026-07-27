# MSAERP → Stabler Migration Planı

**Tarih:** 2026-07-09 · **Sürüm:** v3 (critique + sahip kararları işlendi — bkz. `2026-07-09-msaerp-migration-critique.md`)
**Sahip kararları (v3):** msa.erpstable.com mevcut ve satışlar orada → restore YOK, stabler o site'a kurulur · PI = native Purchase Order (ayrı proforma doctype'ı yok) · Müşteri hiyerarşisi QuickBooks modeli (işlemler child'da, parent kümülatif) · Dual pricing: veri ERPNext'te, görünürlük imports-UI + rol kilitli
**Kaynak:** `/Users/zafar/Downloads/msaerp` — Django 4.2, 57 model, ~320 view, 304 template, 197 migration, django-q, 4 dil (en/ru/tr/uz), ERPNext'e API ile bağlı
**Hedef:** `stabler` Frappe app'i (Frappe/ERPNext v16, MariaDB, Vue 3 SPA, py≥3.14) — ortak bench 22 kiracı

---

## 0. Yönetici Özeti

MSAERP, et ithalatı operasyonunu (PI → avans → CI → konteyner → tır → GRN → landed cost → satış) Django'da yönetip muhasebeyi ERPNext'e yazan bir orkestrasyon UI'sı. Migration stratejisi **yeniden yazım değil, yeniden konumlandırma**: modellerin ~%40'ı ERPNext core doctype'larına erir, ~%30'u stabler'da yeni custom DocType olur, ~%30'u düşer (karşılığı hazır). En büyük mimari kazanç: **çift-veritabanı senkron katmanı (SyncLog/retry/webhook) komple ölür.**

Critique sonrası en önemli düzeltmeler: müşteri geçmişi **parent ledger'da** kalıyor (split-brain riski — K2 yeniden yazıldı), agreed fiyat ERPNext'in *native* alanı olduğundan Accounts rollerinden gizlenemez (K3 kapsamı daraltıldı), ETL hook-guard'sız çalıştırılamaz, Django'da read-only modu yok (freeze mekanizması inşa edilecek), takvim 18-22 hafta.

---

## 0.5 FAZ 0 BULGULARI (2026-07-09, canlı site API envanteri — `faz0-msa-site-inventory.md`)

1. ✅ **Sürüm uyumlu:** Frappe 16.18.2 / ERPNext 16.18.3 (v16) — stabler gereksinimiyle eş; site upgrade gerekmiyor.
2. ❌ **"PO/PI'lar zaten site'ta" varsayımı GEÇERSİZ:** msa'da satın alma tarafı BOŞ (PO/PINV/PR/LCV/Stock Entry/Batch = 0). Django'nun purchase sync'i prod'a hiç yazmamış. → ETL satın alma zincirini **sıfırdan üretir** (migration flag altında); Ref-bağlama yalnız SI/PE için geçerli.
3. ⚠️ **Custom field şeması kod ile ters:** canlı site `custom_agreed_rate/amount/total` taşıyor (native=docs şeması); koddaki `custom_docs_*` + `backfill_erpnext_native_agreed.py` (native=agreed) hiç deploy edilmemiş. K3'ten önce hangi şemanın gerçek olduğu netleşmeli — **satın alma tarafı boş olduğundan flip maliyetsiz**: yeni kayıtlar doğrudan native=agreed + `custom_docs_*` ile başlar; `custom_agreed_*` alanları kaldırılır. `custom_ikpu_code` Item'da YOK (stabler kurulumu ekleyecek; 27 Item'a IKPU backfill görevi).
4. ✅ **K2 legacy köprüsü beklenenden ÇOK küçük:** 4.149 submitted SI'ın **sıfırı** parent'a kesilmiş / child_reference'lı. Hiyerarşi (170 müşteri: MSA→65 child, Ravshan aka→97 child) SI tarafında hiç kullanılmamış → QB modeli neredeyse temiz başlar; UNION formülü büyük ölçüde gereksizleşir. Tek legacy: **14 aktif PE, parent "Ravshan aka" üzerinde, ~4,57 milyar UZS (2026-06-02/03)** — go-live kapsamına alınıp child'lara manuel yeniden tahsis edilir (PE'de child alanı yok).
5. **Kurulum riskleri (runbook'ta):** (a) `desk_gate` kurulumla tüm non-System-Manager kullanıcıları /app'ten atar — kurulum ÖNCESİ karar şart; (b) `uzex_poll` + `one_c` hourly job'ları msa'da durdurulur (Scheduled Job Type `stopped=1`, scheduler kapatılmaz!); (c) Stabler Company Modules default'ları çoğunlukla AÇIK gelir — MSA satırı tüm toggle'lar KAPALI oluşturulur; (d) Django custom field'larıyla stabler patch'leri arasında çakışma YOK (16 alan tek tek doğrulandı).

## 1. Mevcut Durum Envanteri

### 1.1 Veri hacmi (db_production.sqlite3 — 7 Haziran snapshot, **BAYAT**)

| Tablo | Satır | Tablo | Satır |
|---|---|---|---|
| Container | 732 | Customer | 181 |
| CommercialInvoice | 243 | ProformaInvoice | 36 |
| CILineItem | 4.194 | PIGroup | 19 |
| ContainerLineItem | 4.193 | GRN | 3 |
| LineItem (PI) | 523 | Batch | 6 |
| StockLedgerEntry | 408 | AdvancePayment/Allocation | 3/8 |
| JournalEntry(+Line) | 2.394/4.788 (legacy, taşınmaz) | CustomsDeclaration | 0 |

⚠️ **P0:** Her iki lokal SQLite'ta `CustomerInvoice/CustomerPayment/SalesOrder/VendorBill/TruckReceipt` **boş** — canlı DB sunucuda. Gerçek AR/AP/stok bakiyeleri ERPNext (MSA company) tarafında. **İki kaynak birden taşınacak.** GRN yalnız 3 kayıt → GRN/PR/LCV zinciri doğrulaması satır sayımıyla değil senaryo bazlı yapılır.

### 1.2 Stabler'da hazır / eksik

| Hazır (yeniden kullan) | Yok (bu migration inşa edecek) |
|---|---|
| Company izolasyonu, territory/owner scoping, modül toggle | Batch/expiry takibi (roadmap FAZ 2 "kırmızı çizgi") |
| Approval tiers, SoD, period close, desk_write_guard | Landed Cost Voucher akışı (şu an sadece PO JSON alanı) |
| CBU kur scheduler'ı, bank import, Didox/EHF/factura | Konteyner/tır/gümrük/GRN doctype'ları |
| Tender→PO→PR hattı, 3-way match, Xarid mapping dokümanı | Müşteri parent/child hiyerarşisi |
| 5 dil (en/ru/uz/uzc/tr), Telegram | Dual-pricing alanları + maskeleme |
| `custom_ikpu_code` Item'da mevcut (hooks.py) — sadece backfill | SO-bazlı rezervasyonun imports akışına bağlanması |

---

## 2. Kritik Kararlar

### K1 — KARAR VERİLDİ: `msa.erpstable.com` zaten canlı — restore yok, in-place kurulum
Satışlar dahil tüm ERPNext verisi msa.erpstable.com'da. Cutover dramatik sadeleşir (critique B5 büyük ölçüde düşer): **`bench --site msa.erpstable.com install-app stabler` → patch'ler → ETL (yalnız Django-özel veriler)**. Restore/tam-kopya yok; ERPNext'teki PO/PI/PE/SI'lara dokunulmaz, sadece Ref ile bağlanır.
Kalan denetimler: (a) msa site'ının bench/sürüm uyumu (aynı bench'te v16 mi? değilse önce site upgrade); (b) Django'nun yarattığı mevcut custom field'lara (`custom_docs_*`, `custom_parent_customer`, `custom_child_reference`, `custom_payment_stream`) karşı stabler patch'leri **idempotent**; (c) stabler kurulumu + `bench migrate`'in canlı satış operasyonuna etkisi → düşük trafik penceresi; (d) `enable_imports` dışındaki stabler modülleri msa'da kapalı başlar (Stabler Company Modules default'ları).

### K2 — KARAR VERİLDİ: QuickBooks modeli — işlemler CHILD'da, parent kümülatif
**Hedef davranış (sahip):** Customer Center'da hiyerarşi modu; tüm yeni işlemler child'a özel (QB sub-customer/job), parent hiç işlem taşımaz, kümülatif rollup gösterir.
**Uygulama:**
- Her child = gerçek ERPNext **Customer** (`custom_parent_customer` self-Link + `custom_is_location`, `custom_job_status/start/end/description`). Yeni SI/DN/PE/SO **her zaman child party'ye** kesilir; SPA'da parent'a doğrudan işlem kesme UI'dan engellenir (parent = konsolidasyon düğümü).
- **Legacy köprüsü (critique B1):** tarihsel SI'lar parent üzerinde `custom_child_reference` etiketli, ödemeler parent'ta — **yerinden oynatılmaz**. Kümülatif/per-child formül kalıcı UNION: `(customer = child) OR (customer = parent AND custom_child_reference = child_code)`; tek helper `api/imports.py`/customer rapor katmanında. Zamanla legacy payı doğal erir. Faz 0 envanteri: kaç SI etiketli, hangi child'ların party kaydı var, canlı-CRUD'un local-only bıraktığı child'lar ETL'de party'leştirilir.
- **Customer Center hierarchy mode (SPA):** ağaç liste — parent satırı genişler, child'lar girintili; kolonlar: child kendi bakiyesi, parent satırında kümülatif (UNION helper'dan); child'a tıklayınca QB tarzı yalnız o child'ın transaction listesi.
- **Parent'tan toplu tahsilat:** PE tek party'ye bağlanabildiğinden, "Ödeme Al" ekranı parent seçtirir → tüm child'ların açık faturaları listelenir → arka planda **child başına PE bölünür** (tek makbuz görünümü SPA'da birleşik).
- **Kredi kontrolü:** limit parent'ta; SI submit hook'u zincir toplam outstanding'i (UNION) parent limitine karşı denetler; UZS/USD çevrimi işlem günü CBU kuru; override → Stabler Approval Tier; ERPNext native credit-limit kontrolü kapatılır.
- İsteğe bağlı temizlik (go-live kapsamı DIŞI): açık legacy kalemler muhasebeci onayıyla credit/debit note çiftleriyle child'lara taşınıp UNION sadeleştirilebilir.

### K3 — KARAR VERİLDİ: dual pricing verisi ERPNext'te, görünürlüğü imports-UI'a kilitli
"Sadece UI" saklama olamaz — docs fiyatının kalıcı bir evi olmalı ve tek source of truth ERPNext. Katmanlama:
- **Veri:** `custom_docs_rate/amount/total`, `cash_difference` → PO/PO Item + Purchase Invoice custom field'ları (çoğu zaten mevcut), **perm_level 1**.
- **Görünürlük:** yalnız imports SPA sayfalarında ve rol bazlı (Imports Manager/Director + `Stabler Settings.cost_visible_roles`); `api/imports.py` her endpoint'te `apply_cost_mask`; desk zaten kapalı (desk_gate); print formatları kilitli; standart raporlarda custom alanlar görünmez.
- **Dürüst sınır (critique B2, sahip kabulü):** native `rate` = **agreed** (gerçek) fiyat → GL/party ledger/stok değerlemesi gerçek ekonomiyi taşır ve Accounts rolleri agreed toplamları defterde görür. Tersi (native=docs) reddedildi: defter gerçek yükümlülüğü göstermez, cash-difference ödemelerinin GL karşılığı kalmaz, marj/değerleme bozulur.

### K4 — Kesişme: paralel çalışma yok
3 dry-run + kısa freeze + cutover (bkz. §8). Django için **gerçek freeze mekanizması inşa edilir** (critique B4): DB kullanıcısı SELECT-only'ye indirilir, django-q cluster durdurulur, eski ERPNext'te Django API token'ı iptal + webhook'lar kapatılır. (Django'da hazır read-only middleware YOK — bu bir Faz 5 görev kalemi.)

---

## 3. DocType Eşleme Tablosu

Adlandırma: iş dokümanları öneksiz, altyapı `stabler_` önekli (eşleme doctype'ı: `stabler_msaerp_ref`). Şema **idempotent patch** ile. **Submittable olanlar yalnız finansal bağlayıcılar** (critique M5): Import Proforma (onayda), GRN Checklist (tamamlanınca), Truck Receipt (onayda). Container/CI/Truck = **non-submittable operasyonel doc** + statü alanı + merkezi geçiş guard'ı (stabler status pattern'i).

### 3.1 Tedarik zinciri (yeni custom DocType'lar)

| Django modeli | Hedef | Not |
|---|---|---|
| **PIGroup** | `Import PI Group` (custom master) + PO'da `custom_pi_group` Link | code/name/vendor/notes |
| **ProformaInvoice** | **native Purchase Order** — ayrı doctype YOK (sahip kararı) | PO custom field'ları: `custom_advance_percentage`, `custom_prepayment_type`, `custom_pi_group`, `custom_docs_total`, `custom_cash_difference` (K3 maskeli), incoterm native. **İş yaşam döngüsü TÜRETİLİR, saklanmaz:** ADVANCE_PAID=`advance_paid>0`, SHIPPING=bağlı CI statülerinden, COMPLETED=`per_received=100`; SPA rozet olarak hesaplar. Türetilemeyen aşama için tek `custom_stage` Select. Finansal gerçek native alanlarda (docstatus, advance_paid, per_received/billed) |
| **LineItem** | **Purchase Order Item** + `custom_docs_rate/amount`, `custom_boxes`, `custom_box_weight_kg` | boxes×box_weight=qty otomatiği SPA formunda + `validate` hook'ta |
| **AdvancePayment** | **2× Payment Entry** (Bank/Cash) PO-referanslı, `custom_payment_stream` | "Avans Öde" aksiyonu `api/imports.py`'da; eşit-split kuralı hem aksiyonda hem **PE-level hook'ta** (custom_payment_stream'li PE'lerde, `enable_imports` gate'li) |
| **AdvanceAllocation** | PE→PI allocation (native advances) + `Import Advance Allocation` (standalone log/denetim doctype'ı) | |
| **CommercialInvoice** | `Commercial Invoice` (non-submittable, 9-statü) | PO bağlantısı child table `Commercial Invoice PO Link` (M2M: bir CI birden çok PO'yu kapsayabilir). БРВ gümrük ücreti alanları, uzb_vat_usd. **PI üretmez** — bkz. satın alma döngüsü kararı (M2): İran varışında yalnız %70 **avans PE** (PO'ya karşı); **Purchase Invoice, Purchase Receipt'ten SONRA** kesilir (billing follows receipt — native 3-way match) |
| **CILineItem** | `Commercial Invoice Item` (child) | |
| **CILineItemAllocation** | `Import Allocation` (**standalone** doctype — critique M3: Link'ler child-row hedefleyemez) | parent Link'ler (**Purchase Order**, Commercial Invoice) + satır adları Data alanında, `validate`'te satır varlığı re-check; deposit/balance alanları |
| **CIExpense** | `Import Expense` | **düz Link'ler**: `commercial_invoice` (zorunlu) + `container` + `truck` (opsiyonel) — Dynamic Link değil (m1). Onayda service Purchase Invoice üretir |
| **FreightBooking** | `Freight Booking` | XOR validate |
| **Container** | `Import Container` (non-submittable) | **naming series** (`IMP-CNT-.YYYY.-`) — container_number unique DEĞİL (732 satırda tekrar var, m2), düz alan olarak kalır. 12 maliyet kolonu → child `Container Cost Line` (component/currency/amount/amount_uzs). ARRIVED_AT_IRAN statü hook'u → %70 avans PE enqueue |
| **ContainerLineItem** | `Import Container Item` (child) | |
| **ContainerLocalCharge** | `Container Cost Line`'a erir | |
| **Truck** | `Import Truck` (non-submittable) | CROSSED_BORDER hook → transport PI (3-tier lookup portu) |
| **CustomsDeclaration** | `Customs Declaration` (ГТД) | duty/vat/excise **LCV'nin kaynağı**; child satırlar **snapshot** alanlı |
| **VetCertificate** | `Vet Certificate` | Geçerlilik kontrolü Purchase Receipt `before_submit`'te |
| **GRN + GRNLineItem** | `GRN Checklist` (+child) — progresif kabul, varyans ±2/5/10 | **Umbrella/ilerleme dokümanı.** Stok girişi GRN'de değil — bkz. TruckReceipt |
| **TruckReceipt(+Item)** | `Truck Receipt` (submittable) | QC alanları. **Onayda PR-per-truck: native partial Purchase Receipt** (PO'ya karşı, batch+expiry'li) — bozulabilir mal tır tır stoğa girer, satış beklemez (critique M7). GRN Checklist satırları otomatik güncellenir |
| **VendorBill(+Item)** | ERPNext **Purchase Invoice** + `custom_docs_total/diff_total` | 2× PE dual-stream |
| **LandedCostAllocation** | ERPNext **Landed Cost Voucher** | Dağıtım "Qty" (kg). **Kapsam dışı: product_cost + tedarikçi PI'ındaki CIF navlun** (çift kapitalizasyon — critique M8). ГТД geç gelirse ek LCV; LCV cut-off vs period close kuralı tanımlı; **tek close rejimi: stabler period_close** (native Accounting Period kullanılmaz) |

### 3.2 ERPNext core'a eriyen modeller

| Django | Native | Not |
|---|---|---|
| Batch | **Batch** (expiry) | FEFO picking `expiry_date asc` |
| StockEntry/SLE | Stock Entry / SLE | `allow_negative_stock` kapalı; cutover öncesi negatif temizliği |
| StockReservation | **Stock Reservation Entry — Sales Order'a karşı** (critique M1: draft-SI voucher tipi yok; stabler SRE altyapısı SO-merkezli) | Satış akışı SO-first olur; SO'suz hızlı satış gerekiyorsa arka planda otomatik SO |
| SalesOrder(+Item) | Sales Order | |
| CustomerInvoice(+Item) | Sales Invoice + `custom_child_reference` (mevcut desen) | FIFO JSON → batch_no/SRE |
| CustomerPayment(+Alloc) | Payment Entry | |
| DeliveryNote | Delivery Note (Legacy arşiv) | |
| SalesReturn/CreditNote | SI `is_return=1` | |
| BankStatement(+Txn) | Stabler Bank Import + Bank Transaction | MSAERP format parser'ı eklenir |
| BankAccount / Mint | ERPNext Bank Account; Mint → `integrations/mint/` | |
| ExchangeRate | Currency Exchange | Tarihsel kurlar taşınır; aynı tarihte CBU kaydı varsa **CBU önceliklidir**, Django kuru yalnız boş tarihlere yazılır (m9) |
| FiscalYear/AccountingPeriod | Fiscal Year + stabler period_close (**tek rejim**) | |
| Product/Vendor/Kategoriler | Item (+IKPU **backfill** — alan zaten var) / Supplier / Supplier Group | |
| PriceList/Version | Price List + Item Price | ETL Faz 1'e eklendi |

### 3.3 Düşen katmanlar
RBAC→Frappe Role+stabler modül izinleri; UserProfile→Frappe User (**ETL'de User yaratma + rol atama + parola sıfırlama iletişimi adımı var**, critique M4); ActivityLog→Version/audit_seal; Notification→Telegram; Sidebar→SPA router; JournalEntry legacy→arşiv; SyncLog/FXPaymentPair/PaymentSettings→ölür.

---

## 4. Otomasyon Portu

**Zorunlu kural (critique M6 — 22 kiracı):** her imports hook'unun ilk satırı `if not company_module_enabled(doc.company, "imports"): return` + ETL guard'ı `if frappe.flags.in_msaerp_migration: return`. `desk_write_guard`/`approvals`/`sod_enforce` her yeni doctype'a **tek tek açıkça** bağlanır (otomatik değil).

| Django sinyali | Frappe karşılığı |
|---|---|
| create_grn_for_ci (CI→STUFFED) | CI statü hook → GRN Checklist üret |
| Container→ARRIVED_AT_IRAN | statü hook → deposit allocation + %70 **avans PE** enqueue (PI değil — M2) |
| Truck→CROSSED_BORDER | hook → transport PI |
| GRN→COMPLETE stok girişi | **Truck Receipt on_submit → partial Purchase Receipt** (M7) |
| GRN→APPROVED LCV | GRN Checklist on_submit (tüm PR'lar kesildikten sonra) → LCV (ГТД + Cost Line'lardan, product/CIF hariç) |
| auto_reserve_stock | **Sales Order** submit → SRE (M1) |
| advance push | api/imports.py aksiyonu + PE hook denetimi |
| django-q görevleri | scheduler: batch expiry+Telegram (daily), ETA−7g ödeme uyarısı (daily), mint (hourly) — hepsi `enable_imports` gate'li |

## 5. SPA "imports" Modülü

`enable_imports` toggle + `_MODULE_FIELDS/_MODULE_ROLES` + router `meta.module`. ~18 sayfa: ImportOrderList/Form (PO tabanlı — türetilmiş yaşam döngüsü rozetleri, avans progress, dual-pricing maskeli; stabler'ın mevcut PurchaseOrderForm'u genişletilebilir), AdvancePayDialog, CIBoard/CIForm, ContainerTracker/Form, TruckBoard, **TruckReceiptForm (tablet-first, Faz 2'nin İLK sayfası — saha pilotu)**, GRNChecklist, CustomsQueue*, VetCertQueue*, LandedCostReview, ImportExpenseList, ImportsDashboard. (*v1'de list-view-only — kapsam emniyeti, critique M10.)
**Desk fallback YOK** (desk_gate) — gözden kaçan her ekran elle Vue yazılır; bu yüzden **URL→sayfa eşleme tablosu ve kullanıcı anketi Faz 0'da** yapılır (m8). Satış/stok/finans ekranları stabler'ın mevcut modüllerinden; Customer formuna parent/child alanları + konsolide ekstre (K2 UNION helper) eklenir.

## 6. Yetki Eşlemesi
Roller: Imports User / Imports Manager (cash_difference görünürlüğü) / Warehouse User / Declarant / Logist / Accounts / Director. Django `approve_*` → Stabler Approval Tier (GRN onayı, credit override, SalesReturn). Maliyet maskesi perm_level 1 seti = {custom_docs_*, cash_difference, valuation, margin} — agreed native alanı GL üzerinden Accounts'a görünür (K3 kabulü).

## 7. Veri Migration (ETL)

**Araç:** `stabler/migration/msaerp/` — SQLite'ı stdlib `sqlite3` ile okuyan idempotent bench komutları. **`stabler_msaerp_ref`** eşleme doctype'ı (source_table, source_pk, target_doctype, target_name, **target_row_name** — child satırlar dahil, critique M3; 4.194 CILineItem + 523 LineItem satır-eşlemesi zorunlu). **Tüm ETL `frappe.flags.in_msaerp_migration = True` altında koşar; hook'lar no-op** (B3). ERPNext'te zaten var olan PO/PI/PE/SI'lar **regenerate edilmez**, Ref ile bağlanır.

**Sıra:**
1. **Masters:** **Warehouse'lar** (M4), Vendor→Supplier, Product→Item (IKPU backfill), Customer (**topolojik: önce parent** — 181 kayıt; K2 envanterine göre party/etiket kararı kayıt bazında), BankAccount, ExchangeRate (CBU çakışma kuralı m9), BRV/CustomsFeeTier, **Price List + Item Price**, **Frappe User'lar + rol atamaları**.
2. **Tedarik zinciri (Faz 0 bulgusu #2: sıfırdan üretim):** PIGroup → **PO'lar Django ProformaInvoice verisinden ÜRETİLİR** (36 PI + 523 satır; migration flag altında, native=agreed + custom_docs_* şemasıyla) → advance PE'ler: mevcutlar Ref'le bağlanır, eksikler üretilir → CI(+Items) → Import Allocation → Import Expense → Container(+cost lines) → Truck → GRN Checklist/Truck Receipt → **2. geçiş: Container.goods_receipt_note dairesel FK'sı** (M4) → CustomsDeclaration → VetCertificate → **dosya ekleri: BL/packing list/sertifika/fotoğraflar → Frappe File** (M4 — gümrük denetim evrakı, atlanamaz).
3. **Stok:** Batch → native Batch; açılış tek Stock Reconciliation (batch+valuation_rate).
4. **AR/AP:** K1=A'da ERPNext'te zaten var — dokunulmaz.
5. **Arşiv:** JournalEntry, Historical*, Legacy DN → taşınmaz; SQLite read-only + kritik rapor dökümleri.

**Doğrulama:** müşteri sayısı + parent-child kenarları; **bakiye doğrulaması ERPNext party outstanding'e karşı** (Django property'si değil — m4) + K2 UNION formülü child bazında; açık PI avans bakiyeleri; konteyner başına Σ Cost Line (product hariç) ; stok ürün×depo×batch eşitliği; AR/AP yaşlandırma eski-yeni ERPNext eşitliği; GRN/PR/LCV zinciri **senaryo bazlı** test (prod'da yalnız 3 GRN var).

## 8. Kesişme & Cutover

1. 3 dry-run (staging, taze dump'larla) — **dry-run #2/#3 tam cutover provası**: taze restore → bench migrate → stabler install/patch → tam ETL → doğrulama, **süre ölçümüyle** (B5). Dry-run #1 go/no-go kapısı: takvime faz ekleyebilir.
2. **Freeze runbook** (B4): Django DB kullanıcısı SELECT-only → django-q cluster stop → eski ERPNext'te Django token iptal + webhook kapama → son dump → cutover zinciri → doğrulama → kullanıcı yönlendirme.
3. **Rollback:** cutover öncesi site tar'ı; **point-of-no-return = ilk canlı Sales Invoice** — ondan sonra tar-restore yok, düzeltmeler ileri yönlü (m10). Django 30 gün read-only referans (yalnız SELECT).
4. Eğitim: depo (TruckReceipt tablet) + Declarant ayrı oturum; ru/uz kılavuzlar.

## 9. Fazlı Yol Haritası (1 kıdemli Frappe dev + 1 Vue dev + sen) — **re-baseline: 18-22 hafta** (critique M10)

| Faz | İçerik | Süre |
|---|---|---|
| 0 | K1-K4 kararları + **sahip imzaları** (K2/K3), taze dump, **ERPNext MSA envanteri (sürüm! custom field'lar! child SI sayımı!)**, kullanıcı-ekran anketi, staging bench | 2 hafta |
| 1 | DocType'lar + idempotent patch'ler + workflow + hook iskeleti (guard'larıyla); Customer alanları + UNION helper | 3 hafta |
| 2 | api/imports.py + SPA (TruckReceipt önce, saha pilotu); 5 dil (uzc net-yeni çeviri) | 5 hafta |
| 3 | ETL paketi + stabler_msaerp_ref (child-row'lu) + dosya migration + dry-run #1 (go/no-go) | 3 hafta |
| 4 | Uçtan uca senaryolar (konteyner→LCV, kredi kontrolü, iade), approval/SoD, Playwright smoke | 2-3 hafta |
| 5 | Freeze mekanizması inşası + dry-run #2-#3 (tam prova) + eğitim + cutover + hypercare | 3-4 hafta |
| | **Toplam** | **18-22 hafta** |

## 10. Risk Kaydı (güncellenmiş)

| # | Risk | Önlem |
|---|---|---|
| R1 | Lokal SQLite bayat; satış verisi görünmüyor | Faz 0 taze dump + ERPNext envanteri |
| R2 | Müşteri split-brain (B1) | K2 UNION formülü; geçmiş taşınmaz; envanter Faz 0 |
| R3 | Agreed fiyat GL'de görünür (B2) | K3 dürüst kapsam + sahip imzası; docs/cash_difference maskesi |
| R4 | ETL hook tetiklemesi (B3) | migration flag guard, regenerate yasağı |
| R5 | Freeze mekanizması yok (B4) | Faz 5'te inşa: DB SELECT-only + q-cluster stop + token iptal |
| R6 | Çift-kaynak cutover (B5) | Dry-run #2/#3 tam prova, süre ölçümü, MSA ERPNext sürüm envanteri |
| R7 | 22 kiracı blast radius (M6) | enable_imports gate her hook'ta; staging ayrı bench; düşük trafik deploy + tar rollback |
| R8 | Negatif stok yasağı çelişkisi | Cutover öncesi temizlik; PR-per-truck stok gecikmesini zaten çözer |
| R9 | LCV çift kapitalizasyon / geç ГТД (M8) | product+CIF hariç; ek-LCV akışı; tek period-close rejimi; muhasebeci onayı |
| R10 | UI kapsam kaçağı — desk fallback yok (m8) | Faz 0 URL→sayfa tablosu + kullanıcı anketi; v1'de 2 sayfa list-only |
| R11 | Depo adaptasyonu | TruckReceipt ilk yazılır, saha pilotu |
| R12 | Bus factor | Bu doküman + critique canlı tutulur; PR'lar review'dan geçer |

---
*v2 — critique raporundaki 5 BLOCKER, 10 MAJOR, 10 MINOR maddenin tamamı işlendi. Kaynaklar: msaerp model envanteri, stabler mimari raporu, db_production.sqlite3 sayımları, 2026-07-03 GRN gap analizi, critique raporu.*
