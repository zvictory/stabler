# MSAERP → Stabler Özellik Paritesi — Bölüm 3: Lojistik, GRN, Landed Cost, Gümrük/Veteriner/Navlun

**Tarih:** 2026-07-10
**Kapsam:** Container, Truck + Truck Receipt, GRN (Goods Receipt Note), Landed Cost, Customs Declaration (ГТД), Vet Certificate, Freight Booking.
**Yöntem:** MSAERP tarafı gerçek şablonlar (`templates/`), `models.py`, `views.py`, `urls.py`, `signals.py`, `services/`, `erpnext_integration/sync.py` okunarak; Stabler tarafı WP2-3 kapsamındaki (henüz commit edilmemiş, working tree'de duran) doctype'lar ve `imports_module/` iş mantığı okunarak çıkarılmıştır. Tahmin/varsayım yapılmamış, sadece kodda görülenler yazılmıştır. Bilinmeyen/doğrulanamayan noktalar açıkça "doğrulanamadı" olarak işaretlenmiştir.

**Zamanlama notu (önemli düzeltme):** Görev tanımında "Faz 2 SPA ≈ Ağustos 2026", "WP4 ≈ yakın", "ETL ≈ Eylül 2026", "cutover ≈ Ekim-Kasım 2026" şeklinde bir çerçeve verilmişti. Gerçek plan dosyası (`docs/plans/2026-07-09-msaerp-to-stabler-migration-plan.md`, v3) **"WP" (work package) numaralandırması kullanmıyor** — bunun yerine **Faz 0-5** kullanıyor ve süreleri takvim ayı değil, doküman tarihinden (2026-07-09) itibaren **hafta** cinsinden veriyor. Bu belgede WP4 diye bir şey yok; Customs Declaration + Import Expense + Freight Booking, **Faz 1**'de (DocType+patch+hook iskeleti) inşa ediliyor, **Faz 2**'de (SPA) kullanıcıya açılıyor, **Faz 3**'te (ETL) veri taşınıyor. Aşağıdaki tablo plandan birebir alınmıştır, ay eşlemesi ise doküman tarihinden itibaren kümülatif hesaplanmış bir **çıkarımdır** (plan dosyasında birebir yazmıyor):

| Faz | İçerik | Süre | Yaklaşık takvim (çıkarım) |
|---|---|---|---|
| 0 | Kararlar + sahip onayları, taze dump, ERPNext MSA envanteri, staging bench | 2 hafta | ~9-23 Tem 2026 |
| 1 | DocType'lar + idempotent patch'ler + workflow + hook iskeleti | 3 hafta | ~23 Tem - 13 Ağu 2026 |
| **2** | **api/imports.py + SPA (TruckReceipt önce, saha pilotu); 5 dil** | **5 hafta** | **~13 Ağu - 17 Eyl 2026** |
| 3 | ETL paketi + stabler_msaerp_ref + dosya taşıma + dry-run #1 | 3 hafta | ~17 Eyl - 8 Eki 2026 |
| 4 | Uçtan-uca senaryolar, onay/SoD, Playwright smoke | 2-3 hafta | ~8-29 Eki 2026 |
| 5 | Freeze mekanizması + dry-run #2-3 + eğitim + cutover + hypercare | 3-4 hafta | ~29 Eki - 26 Kas/3 Ara 2026 |
| **Toplam** | | **18-22 hafta** (kritik eleştiri M10 sonrası yeniden baseline'landı — orijinal tahmin %30-40 iyimserdi) | |

Yani "Ağustos 2026" Faz 2'nin **başlangıcına** denk geliyor ama Faz 2 orta Eylül'e kadar sürüyor; ETL (Faz 3) Eylül'ün ortasından Ekim başına kadar; cutover (Faz 5) Ekim sonu - Kasım sonu/Aralık başı bandında. Bu belgede "Faz 2 / Faz 3 / Faz 5" ifadeleri kullanılacak, "WP" değil.

Bu belgede ayrıca sürekli referans verilen iki kaynak belge var:
- `docs/audit/GRN_AUTOMATION_GAP_ANALYSIS_2026-07-03.md` (MSAERP repo) — MSAERP'in GRN→Purchase Receipt→LCV zincirinin neden çalışmadığını satır satır belgeleyen denetim raporu.
- `docs/plans/2026-07-09-msaerp-migration-critique.md` ve `docs/plans/2026-07-09-faz0-msa-site-inventory.md` (Stabler repo) — plan v1'in eleştirisi ve prod ERPNext envanteri (satın alma tarafında **0 kayıt** bulundu — yani MSAERP'in GRN→PR→LCV zinciri pratikte hiçbir zaman prod'a tek bir ERPNext belgesi bile yazmamış).

---

## 1. Container (Konteyner)

### MSAERP'de bugün

**Liste görünümü** — `templates/container/container_list.html`, `ContainerListView` (`proforma_app/views.py:3124`)

- Başlık: "Container Tracking", rozet: `{{ total_containers }} containers`. Butonlar: **New Container**, **Bulk Import**, **CI**.
- 4 metrik kartı: FCL (toplam konteyner), Boxes, Weight (kg), **Delivered** — `status="DELIVERED"` sayıyor ama bu değer `Container.STATUS_CHOICES` içinde **yok**, dolayısıyla bu sayaç her zaman 0 (bug).
- Filtreler (server-side GET, arama 500ms debounce): Arama (konteyner no, CI no, BL no, vessel, shipping line, port), Status (sadece kullanımda olan değerler), BL Type, Shipping, Vendor (sadece SUPPLIER tipli, konteyneri olan vendor'lar). `?ci=` ile CI filtre pili.
- Tablo kolonları: Container (no + boyut/tip), CI/Vendor, BL (no + tip rozeti), Vessel (vessel, shipping line, DIRECT/INDIRECT rozeti, ETD/ETA/Cut Off/Gate Open/Gate Close mini-grid), Status (renkli rozet), Route (loading→discharge, transshipment varsa "via ..."), Weight & Boxes, Carrier (taşıyıcı firma çipleri, CI'ye bağlı truck'lardan türetilmiş), Actions (View/Edit/Delete).
- **Bug:** rozet renk mantığı `BOOKED/IN_TRANSIT/DELIVERED` kontrol ediyor ama gerçek `STATUS_CHOICES` = `BOOKED, STUFFED, GATE_IN, ON_BOARD, IN_TRANSIT, DISCHARGED, AVAILABLE, ARRIVED_AT_IRAN, DELIVERED_TO_UZBEKISTAN` — `DELIVERED`/`ARRIVED` yok, gerçek terminal durumdaki her konteyner gri "diğer" dalına düşüyor.
- **Mobile varyant** (`templates/mobile/container_list.html`) — Alpine.js kart görünümü, ayrı bir filtre mantığı kullanıyor: konteynerin değil **CI'nin** status'üne göre filtreliyor (All/In Transit/At Port/Arrived). Kartta **"70% Payment"** rozeti var (`payment_70_status`: COMPLETED=yeşil "Paid", PARTIAL=amber "Partial", diğer=kırmızı "Pending") — masaüstü detay sayfasında bu bilgi **yok**, sadece mobilde var.

**Form** — `templates/container/container_form.html`, `ContainerForm` (`forms.py:1107`)

Bölümler: (1) Basic Information — Container Number*, Commercial Invoice, Date*, Status*; (2) Container Details — Container Type* (readonly, hep "RF" — tüm konteynerler reefer), Container Size*; (3) Shipping Information — Shipping Type*, Shipping Line*, BL Number, BL Type*, Seal Number, Vessel, Voyage (not: vessel/voyage/bl_number/port'lar/ETD-ETA-ATD-ATA modelde gerçek kolon değil, CI'den okunan `@property` — form alanları görünse de bazıları `ContainerForm.Meta.fields` içinde bile değil, yani no-op); (4) **Freight Costs (Shipping Expenses)** — Shipping Company, Freight Cost, Currency, Payment Status, Payment Date, Payment Reference; (5) Ports and Route — Port of Loading*, Port of Discharge*, Transshipment Port; (6) Schedule and Dates — ETD/ETA/ATD/ATA, Cut Off, Gate Open, Gate Close, Gate In, Customs Clearance, Telex Release; (7) **Packing List** editable tablo — "Load from CI" (AJAX), "Add Item", kolonlar Code/Product Name/Category (sadece "BUFFALO COMPENSATED"/"HQ CUTS" hardcoded)/Boxes/Box Weight/Total Weight (client-side otomatik)/Action.

`ContainerUpdateView.form_valid` içinde: eski status `"ARRIVED"` değilken yeni status `"ARRIVED"` olursa otomatik GRN oluşturma dener — ama `"ARRIVED"` geçerli bir `STATUS_CHOICES` değeri değil (`ARRIVED_AT_IRAN` var), yani bu **dead code**, hiç tetiklenmiyor.

**Detay** — `templates/container/container_detail.html`, `ContainerDetailView`

- Hero header, Shipping Information, Ports/Route, Schedule/Dates.
- Cargo Information (4 kart): Total Boxes, Net Weight, Gross Weight, VGM.
- Financial Information (3 kart): Product Value, Bank (Invoice), Cash (Invoice).
- **En önemli boşluk:** Model üzerinde **12 alanlık landed-cost alanları** (`product_cost_usd`, `shipping_cost_usd`, `iran_customs_duty_usd`, `iran_port_thc_usd`, `iran_storage_fee_usd`, `iran_demurrage_usd`, `iran_inspection_fee_usd`, `cross_border_transport_usd`, `uzb_customs_duty_usd/uzs`, `uzb_port_handling_usd/uzs`, `certificate_cost_usd`, `insurance_cost_usd`, `total_landed_cost_usd` property) ve **70% avans/depozito alanları** (`payment_70_status/date/amount/reference`, `allocated_deposit_amount`, `balance_due_amount`) modelde tam dolu, ERPNext'e Purchase Invoice/LCV oluşturmayı tetikliyor — ama **container_detail.html'de bu alanlar için hiçbir UI yok**. Sadece inline-edit AJAX endpoint'i (`LandedCostUpdateView`) var, kendi görünür UI'ı yok bu sayfada.
- Documents (BL, Packing List, Invoice, Certificate of Origin) — AJAX upload/delete; `other_documents` alanı var ama upload UI'ı yok.
- GRN bölümü: GRN varsa link/warehouse/received kg/progress; yoksa *"GRN will be created automatically when the container status changes to ARRIVED"* mesajı — bu **yanlış**: gerçek otomatik GRN tetikleyicisi Container değil **CI status**'üne bağlı (`create_grn_for_ci` sinyali).
- "Confirm Status Change" modalı JS'i `#statusSelect` elementine referans veriyor ama bu element şablonda **yok** — dead/orphaned JS; sunucu tarafındaki `container_update_status` endpoint'i bu sayfadan hiç çağrılmıyor.

**Toplu içe aktarma** — `container_bulk_import.html`: 13 kolonlu Excel (Container Number*, CI Number, Date, Status, Shipping Line, BL Number, Port of Loading, Port of Discharge, ETD, ETA, Container Size, Total Boxes, Total KG), `container_number` ile get_or_create, hatalar ilk 10 + "...N more" olarak gösterilir.

**Model — `Container`** (`proforma_app/models.py:2668`)

- `STATUS_CHOICES`: BOOKED, STUFFED, GATE_IN, ON_BOARD, IN_TRANSIT, DISCHARGED, AVAILABLE, ARRIVED_AT_IRAN ("Arrived at Iran Port (Pay Balance)"), DELIVERED_TO_UZBEKISTAN.
- **%70 depozito alanları:** `payment_70_status` (PENDING/COMPLETED), `payment_70_date`, `payment_70_amount`, `payment_70_reference`.
- **Depozito tahsis takibi ("30/70 payment split"):** `allocated_deposit_amount`, `balance_due_amount`.
- **Uluslararası ithalat maliyet takibi** (yorum: `===== INTERNATIONAL IMPORT COST TRACKING =====`): 12 alan (yukarıda listelendi), `total_landed_cost_usd` property, `calculate_cost_per_kg()`.
- `goods_receipt_note` FK → GoodsReceiptNote.
- Belgeler: `bl_document`, `packing_list`, `invoice_document`, `certificate_origin`, `other_documents`.

**Otomasyonlar/sinyaller (`signals.py`) — %70 depozito zinciri (bu bölümün kalbi)**

`trigger_70_percent_bill_on_iran_arrival` (pre_save, Container, satır 581) — **sadece** `ARRIVED_AT_IRAN`'a geçişte tetiklenir:
1. `DepositAllocationService.allocate_line_items(ci)` — CI kalemlerine avans payını dağıtır (`line.agreed_amount / total_PI_value × total_advance_paid`, birden fazla PI'ye bağlıysa toplanır).
2. `DepositAllocationService.allocate_and_compute_balance(container)` — `deposit_share`/`balance_due = product_cost_usd - deposit_share` hesaplar, `allocated_deposit_amount`/`balance_due_amount`/`payment_70_amount` set eder.
3. `balance_due <= 0` ise (avans tamamen karşılıyorsa) işlem biter.
4. `ERPNEXT_ENABLED=True` ise instance'ı işaretler (`_create_erpnext_pi=True`) → post_save sinyali `create_erpnext_purchase_invoice_on_iran_arrival` ERPNext Purchase Invoice oluşturma görevini `django_q` ile kuyruğa alır (`erpnext_integration.tasks.submit_purchase_invoice_for_container`).
5. ERPNext kapalıysa yerel `VendorBill` (`bill_type="PRODUCT"`, `reference_number="70PCT-{container_number}"`) oluşturur, kalemleri "docs vs diff/agreed dual-pricing" oranıyla böler.

Not: `deposit_allocation_service.py`'nin docstring'i "30/70 Payment Split" diyor ama formülde sabit %30/%70 **yok** — pay, gerçek ödenen avansa orantılı hesaplanıyor.

**`docs/container-cost-workflow.md` notu:** Bu doküman ismine rağmen aslında **CI-seviyesi `CIExpense`** hakkında (konteyner-seviyesi değil), "Future Enhancements" bölümünde açıkça "Container-Specific Costs — Cost allocation per container" **henüz yapılmamış** olarak listeli. Yani doküman, kod tabanındaki 30/70 depozito mekanizmasının (`signals.py`/`deposit_allocation_service.py`) gerisinde kalmış — bu mekanizma hiçbir dokümanda ayrıntılı anlatılmıyor, sadece kod yorumlarında var.

**ERPNext sync:** Container alanları `create_landed_cost_for_grn(grn)` (`erpnext_integration/sync.py:617`) içinde toplanıp LCV'ye giriyor (bkz. Bölüm 4) — ama bu fonksiyon pratikte hep no-op (bkz. Bölüm 3/4, PR asla oluşmuyor).

**Diğer bilinen buglar:** `quick_add_container` API'si `port_of_loading`/`port_of_discharge`'ı `Container.objects.create()`'a kwarg olarak geçiyor — bunlar salt-okunur `@property`, setter yok → çalışma zamanında `AttributeError` (kırık endpoint). Ayrıca `status="PACKED"` de geçerli bir choice değil.

### Stabler'da bugün (WP2-3, working tree'de, commit edilmemiş)

**Import Container** doctype (`stabler/stabler/doctype/import_container/`) — submit edilemez, `autoname: IMP-CNT-{YYYY}-{#####}`.

- Alanlar: `container_number`, `commercial_invoice`, `supplier`, `company`*, `currency` (default USD), `container_type` (DC/RF/OT/FR/TK, default RF), `container_size` (20/40/40HC), `bl_type`, `seal_number`, `gross_weight`, `vgm`, `status`* (aşağıdaki state machine), `status_correction_reason`, `total_boxes`/`total_kg`, `total_amount` (permlevel 1), **`advance_70_payment_entry`** (Link→Payment Entry, salt-okunur — "DRAFT 70% advance PE auto-created on ARRIVED_AT_IRAN"), tarihler (cut_off, gate_open, gate_close, gate_in_date, customs_clearance_date, telex_release_date), ödeme bölümü (`allocated_deposit_amount`, `balance_due_amount` permlevel 1, `payment_70_status`, `payment_70_date`, `payment_70_amount`), `items` (child table), `cost_lines` (child table → **Container Cost Line**).
- Roller: System Manager / Imports Manager tam CRUD; Imports User oluştur/oku/yaz (silme yok).

**Durum makinesi** (`_ALLOWED_TRANSITIONS`, `import_container.py`):
```
BOOKED → STUFFED | Cancelled
STUFFED → GATE_IN | Cancelled
GATE_IN → ON_BOARD | Cancelled
ON_BOARD → IN_TRANSIT | Cancelled
IN_TRANSIT → DISCHARGED | Cancelled
DISCHARGED → AVAILABLE | Cancelled
AVAILABLE → ARRIVED_AT_IRAN | Cancelled
ARRIVED_AT_IRAN → DELIVERED_TO_UZBEKISTAN   (SADECE — Cancelled çıkışı yok; mal fiziken geldiyse geri alınamaz)
```
Geriye tek adımlık düzeltme sadece Imports Manager/System Manager rolüyle ve `status_correction_reason` doldurularak yapılabilir; `Cancelled`'dan hiçbir yöne çıkış yok. Guard, ETL migrasyonu sırasında (`frappe.flags.in_msaerp_migration`) veya şirket bazında `enable_imports=0` iken no-op olur (varsayılan **kapalı**, diğer tenant'lar etkilenmesin diye).

**%70 avans otomasyonu:** `ARRIVED_AT_IRAN`'a geçişte `hooks.on_container_update` → `create_advance_pe` arka plan görevini kuyruğa alır. `payment_math.py`: `ADVANCE_PCT = 0.70` (yorum: "Iran-arrival advance is 70% of the container's goods value (the 30% deposit was paid up front at PO stage). See Django signals.py:581" — MSAERP'teki orijinal mantığa doğrudan izlenebilirlik). **Önemli mimari düzeltme:** bu artık bir **Purchase Invoice değil**, doğrudan bir **DRAFT Payment Entry** (`paid_amount = total_amount * 0.70`, bağlı PO'lara `grand_total`'a orantılı dağıtılır, `reference_no = "70PCT-{container_name}"` idempotency anahtarı). PE hiç submit edilmez, muhasebeci gözden geçirir. Bu, göç planının **M2 kararı**: "CI Iran'a varışta artık Purchase Invoice üretmiyor, sadece PO'ya karşı %70 avans Payment Entry" — MSAERP'in mevcut (ve gap-analizinde P0-3/P0-4 olarak işaretlenen çifte stok girişi sorununa yol açan) davranışının doğrudan düzeltmesi.

**Container Cost Line** (child, controller yok — bilinçli olarak frappe-bağımsız): `cost_component` (Freight, Iran Customs Duty, Iran Port & THC, Iran Storage, Iran Demurrage, Iran Inspection, Cross-Border Transport, Insurance, Certificate, Uzbekistan Customs Duty, Uzbekistan Port Handling, Customs Clearance Fee, Other), `description`, `currency`, `amount`, `amount_uzs`, `include_in_landed_cost` (default 1), `lcv_ref` (salt-okunur — boşsa satır henüz bir LCV'ye tüketilmemiş demek). Alan açıklaması: mal bedeli/CIF navlun **bilinçli olarak** bir maliyet bileşeni değil — "çifte kapitalizasyonu önlemek için."

**SPA (Faz 2 için):** Şu an sadece `stabler/public/js/pages/imports/ImportsDashboard.vue` var, içeriği tamamen placeholder: *"The Imports workspace will be built out in the next work package."* `router.js`'de tek route `/imports`. **ContainerTracker/Form dahil hiçbir Vue bileşeni henüz yok** — WP2-3 şu an tamamen backend (doctype + `imports_module` iş mantığı + unit testler), SPA yüzeyi Faz 2'de inşa edilecek.

### Boşluk tablosu

| Özellik | MSAERP | Stabler | Durum | Plan | Tahmini zaman |
|---|---|---|---|---|---|
| Konteyner listesi (filtre/arama/rozet) | Var, ama status-değer sürüklenmesi nedeniyle "Delivered" sayacı hep 0, rozet renkleri kısmen kırık | Doctype hazır, liste ekranı yok | 🔜 | Faz 2 SPA — ContainerTracker | Faz 2 (~Ağu-Eyl 2026) |
| Konteyner formu (navlun, rota, tarihler, packing list) | Var (Bootstrap form) | Doctype alanları hazır (items child table) | 🔜 | Faz 2 SPA — ContainerTracker Form | Faz 2 |
| %70 avans/depozito | Modelde tam ama UI'da hiç görünmüyor (sadece mobilde rozet); yerel VendorBill veya ERPNext PI (Iran varışında) | **Mimari olarak düzeltildi**: PI değil, doğrudan DRAFT Payment Entry (M2 kararı); alan + hook + arka plan görev tamam | ✅ (backend) / 🔜 (UI) | Faz 2 SPA'da görünür kılınacak | Faz 2 |
| Landed-cost 12 alan / maliyet bileşenleri | Modelde var, **hiçbir detay sayfasında UI yok** | Container Cost Line child table — component bazlı, çoklu LCV'ye uygun tasarım | 🔜 | Faz 2 SPA — LandedCostReview | Faz 2 |
| Belge ekleri (BL, packing list, invoice, cert. of origin) | Var, AJAX upload/delete; `other_documents` için UI yok | Doctype'ta henüz attach alanı yok (doğrulanamadı — dosya modeli Faz 3 ETL'de "file migration" kapsamında) | 🔜 | Faz 2/3 | Faz 2-3 |
| Toplu Excel içe aktarma | Var (13 kolon) | Yok, planlanmadı (doğrulanamadı) | ❌/🔜 | Plan dosyasında ayrı madde yok — netleştirilmeli | Belirsiz |
| Durum makinesi tutarlılığı | Şablon/view'larda `DELIVERED`/`ARRIVED`/`PACKED` gibi **geçersiz** status string'leri kullanılıyor, gerçek bug'lara yol açıyor | Net, kod-seviyesinde zorunlu kılınan tek yönlü state machine (`assert_transition`) + backward-correction guard | ✅ (Stabler net üstün) | — | Tamam |
| Otomatik GRN oluşturma tetikleyicisi | CI status'üne bağlı (Container status'üne değil) — detay sayfasındaki mesaj yanlış yönlendiriyor | Container ayrı, GRN Checklist ayrı doctype; tetikleyici ilişkisi Faz 1'de netleşecek | 🔜 | Faz 1/2 | Faz 1-2 |

### Notlar/kararlar

- Stabler'ın **Import Container** doctype'ı, MSAERP'in dağınık/tutarsız status değerlerini (`DELIVERED`, `ARRIVED`, `PACKED` gibi kodda hiç var olmayan string'ler) ortadan kaldırıyor; `_ALLOWED_TRANSITIONS` + `assert_transition` guard'ı migration planının M6 maddesiyle örtüşüyor (ETL sırasında ve modül kapalıyken no-op).
- %70 avans mekanizmasının **Purchase Invoice yerine Payment Entry** olarak yeniden tasarlanması (M2 kararı), MSAERP'in gap-analiz raporunda P0-3/P0-4 olarak işaretlenen "çifte stok girişi" ve "beklenen miktar üzerinden borç" sorunlarını kökünden çözüyor — bu, Stabler'ın kasıtlı bir mimari düzeltmesi olarak belgelenmeli.
- Container-seviyesi maliyet kırılımı UI'ı MSAERP'te **hiç yoktu** (sadece model + arka plan mantığı) — Stabler'da da henüz SPA'da yok, ama en azından veri modeli (`Container Cost Line`, bileşen bazlı) LCV'ye temiz şekilde bağlanacak şekilde tasarlanmış; bu MSAERP'in 12 hardcoded alanına göre daha esnek.

---

## 2. Truck + Truck Receipt (QC / Sıcaklık / Fotoğraf)

### MSAERP'de bugün

**Truck listesi** — `templates/truck/truck_list.html`, `TruckListView` (`views.py:5328`)

- Başlık "Trucks", alt başlık "{{count}} trucks • Transport Iran → Uzbekistan", "New Truck" butonu.
- Metrik kartları: Total, In Transit (DEPARTED_IRAN/AT_BORDER/CROSSED_BORDER/IN_TRANSIT), Arrived, Completed (GRN_CREATED/COMPLETED).
- Filtreler: Search (truck#, driver, CI#), Status, Allocation, **Warehouse** (`destination_warehouse` distinct string listesi — **bug:** bu alan düz `CharField`, FK değil, ama `truck_detail.html` bazı yerlerde `truck.destination_warehouse.name` render ediyor — string'in `.name` özelliği yok, her zaman boş basılıyor), Vendor.
- Kolonlar: Truck #, CI/Vendor, Carrier, Border Crossing (tarih), Driver (isim+telefon), Transport Cost ($ + ödeme rozeti), Status (9 değer, ikonlu), Allocation (AVAILABLE/ALLOCATED/IN_USE/COMPLETED), Actions.
- Satır aksiyonları: View, **Generate CI** (sadece `not truck.commercial_invoice and truck.vendor` iken görünür — truck'tan CI üretir), Edit, Delete.

**Model — `Truck`** (`models.py:3484`)

- `STATUS_CHOICES`: PENDING, DEPARTED_IRAN, AT_BORDER, CROSSED_BORDER, IN_TRANSIT, ARRIVED, UNLOADING, GRN_CREATED, COMPLETED.
- `ALLOCATION_STATUS_CHOICES`: AVAILABLE, ALLOCATED, IN_USE, COMPLETED — `save()` içinde **her save'de** otomatik yeniden hesaplanıyor (manuel değişiklik üzerine yazılıyor).
- `destination_warehouse` — CharField(140), **FK değil** (yukarıdaki bug'ın kaynağı).
- Sıcaklık: `temperature_logger`, `target_temp_min` (default **-22.00°C**), `target_temp_max` (default **-18.00°C**).
- `transport_cost`, `transport_currency`, `transport_payment_status` (UNPAID/PARTIALLY_PAID/PAID/OVERDUE).

**Form** — `truck_form.html`, `TruckForm` (`forms.py:1426`): Truck Identification (Truck Number* — otomatik önerilen, "Generate New Number" butonu; Destination Warehouse* — canlı AJAX dropdown; Status*), Driver Information, Timeline, **Temperature Monitoring** (Logger ID, Min/Max °C, default -22/-18), Cargo Details, Transport Cost, Notes.

**Detay** — `truck_detail.html`: Basic Info, Driver Info, Cargo Details, Timeline, Temperature Monitoring (Logger ID + "{min}°C to {max}°C"), Notes, **Truck Receipts** listesi (receipt no linki `grn_detail`'e gidiyor, kendi detay sayfası yok; status/arrival/received_by/boxes/kg). Boşsa: **"Create GRN" butonu `proforma:grn_create`'e link veriyor ama bu URL kayıtlı değil** (`GRNCreateView` sınıfı yorum satırında/devre dışı) — tıklanırsa `NoReverseMatch` hatası verir (kırık buton).

**Truck Receipt formu — ÖNEMLİ BULGU: erişilemiyor (dead template)**

`templates/grn/truck_receipt_form.html` — Truck Arrival Details, **Photo Documentation (4 fotoğraf alanı: Truck Arrival, Cargo, Damaged Items, Quality Check)**, **QC checkbox'ları (Temperature OK, Packaging OK, Seal Intact)**, Item Checklist (per-satır condition GOOD/DAMAGED/REJECTED + damaged_boxes + verified) — bu form MSAERP'te QC/sıcaklık/fotoğraf iş akışının **tek tasarlanmış UI yüzeyi**. Ancak **hiçbir URL/view bu şablonu render etmiyor** — `views.py`'de bu forma render eden hiçbir çağrı yok, `urls.py`'de sadece `truck-receipt/<pk>/approve/` var (o da doğrudan `truck_detail`'e redirect ediyor, formu hiç göstermiyor). **Yani MSAERP'te tasarlanmış ama hiç çalışmayan/erişilemeyen bir özellik.**

**Gerçekte kullanılan (erişilebilir) akış:** GRN detay sayfasındaki "spreadsheet" — `GRNDetailView` her CI'ye bağlı truck için otomatik `TruckReceipt` (status DRAFT, `received_by="Warehouse Staff"` hardcoded) + boş `TruckReceiptLineItem`'lar oluşturuyor (**GET isteğinde DB satırı yaratan side-effect** — dikkat edilmesi gereken bir nokta). `grn_update_spreadsheet` view'ı sadece **boxes/kg/fact_count** post ediyor — **sıcaklık, ambalaj/mühür kontrolü, condition, hasarlı/reddedilen kutu, fotoğraf hiçbirini kaydetmiyor**. Bu alanlar sadece model default değerleriyle kalıyor (`temperature_check_passed=True`, `packaging_check_passed=True`, `seal_intact=True`, `condition="GOOD"`) — yani **gerçek denetim verisi hiç girilmiyor.**

**Model — `TruckReceipt`** (`models.py:4074`): `STATUS_CHOICES` = DRAFT/VERIFIED/APPROVED. `photos_uploaded` bool — otomatik türetilmiyor, hiçbir erişilebilir kod yolunda True set edilmiyor. `photo_1..4` (ImageField). `approve()` metodu: status→APPROVED, GRN line item ve GRN toplamlarını günceller, `truck.status = "GRN_CREATED"`. `TruckReceiptLineItem`: `box_weights` (JSONField, tek tek kutu ağırlığı — erişilebilir hiçbir UI'da kullanılmıyor), `condition`, `damaged_boxes`, `rejected_boxes`.

**Sinyal — sınır geçişi navlun faturası:** `trigger_transport_bill_on_border_crossing` (pre_save, Truck) — sadece `CROSSED_BORDER`'a geçişte tetiklenir, 3 katmanlı maliyet bulma (linked CIExpense → unlinked CIExpense eşleşmesi → `truck.transport_cost` fallback), `VendorBill` (`bill_type="TRANSPORT"`, `reference_number="XBORDER-..."`, 15 gün vade) oluşturur.

### Stabler'da bugün

**Import Truck** doctype — submit edilemez, `autoname: IMP-TRK-{YYYY}-{#####}`. Alanlar MSAERP'e büyük ölçüde paralel: `truck_number`, `commercial_invoice`, `trucking_company` (Link→Supplier), `destination_warehouse` (**Link→Warehouse — MSAERP'in CharField bug'ı burada çözülmüş**), `status`*, cold-chain (`target_temp_min` -22, `target_temp_max` -18), transport bölümü (`transport_cost` permlevel 1, `transport_purchase_invoice` — Link→Purchase Invoice, salt-okunur, "DRAFT cross-border transport PI auto-created on CROSSED_BORDER").

**Durum makinesi:**
```
PENDING → DEPARTED_IRAN → AT_BORDER → CROSSED_BORDER → IN_TRANSIT → ARRIVED → UNLOADING → GRN_CREATED → COMPLETED
```
her adımdan `Cancelled`'a çıkış var (COMPLETED hariç), geri dönüş yok. `CROSSED_BORDER`'a geçiş **senkron** olarak (arka plan görevi değil) DRAFT bir cross-border transport Purchase Invoice oluşturuyor (`payment_math.build_transport_pi_payload`, tek "Cross-Border Transport" servis kalemi, `bill_no = "XBORDER-{truck_name}"` idempotency).

**Truck Receipt** doctype — **submit edilebilir**, `autoname: TRK-RCV-{YYYY}-{#####}`. Alanlar: `grn_checklist`*, `truck`*, `arrival_date`/`arrival_time`, `received_by`, **QC bölümü: `temperature_at_arrival`, `temperature_check_passed`, `packaging_check_passed`, `seal_intact`, `seal_number`, `qc_notes`**, `items` (child), `purchase_receipt` (salt-okunur — "Partial Purchase Receipt auto-created and submitted on Truck Receipt submit").

**Sıcaklık kontrolü kod-seviyesinde zorunlu kılınıyor** (`truck_receipt.py::_check_temperature`): `temperature_at_arrival`, bağlı Import Truck'ın `target_temp_min/max` aralığı dışındaysa ve `qc_notes` boşsa → **`frappe.throw` ile submit engellenir**; not girilmişse geçişe izin verilir ama `temperature_check_passed = 0` olarak işaretlenir. **Bu, MSAERP'te hiç çalışmayan QC kontrolünün Stabler'da gerçek bir zorunlu kural haline getirilmesi.**

**Truck Receipt Item:** `condition` (Good/Damaged/Rejected, default Good) — açıklama: **"Only Good-condition weight enters the Purchase Receipt; Damaged/Rejected is kept for the claim trail"** — yani condition artık sadece görsel değil, gerçekten hangi miktarın stoğa gireceğini belirliyor. `expiry_date` alanı — otomatik oluşturulan Batch'e expiry taşıyor (FEFO için).

**PR-per-truck (kasıtlı düzeltme, "critique M7"):** `Truck Receipt` **submit edildiğinde**, `hooks.py::_create_pr_for_truck_receipt` senkron olarak (submit transaction'ı içinde) **kısmi bir Purchase Receipt oluşturup submit ediyor** — `receipt_math.py`: sadece `condition == "Good"` ağırlık PR'a giriyor (`good_qty`), batch adı `"{container_number}-{item_code}-{arrival_date}"` formatında otomatik oluşuyor (expiry varsa set ediliyor), PO satırlarıyla `resolve_po_rate` üzerinden rate/PO bağlantısı kuruluyor (tek eşleşme→bağlan, eşleşme yok→rate 0+uyarı, çoklu eşleşme farklı rate→rate 0+"manuel doğrula" uyarısı). PR başarısız olursa **Truck Receipt submit işlemi de geri alınıyor** (atomiklik).

**Fotoğraf alanları:** Doğrulanamadı — okunan `truck_receipt.json`'da fotoğraf/attach alanı için ayrı bir alan grubu bulunamadı; muhtemelen Frappe'nin standart dosya eki mekanizması (herhangi bir doctype'a "Attach" ekleme) kullanılacak, ama MSAERP'teki gibi 4 ayrı etiketli (Arrival/Cargo/Damage/Quality) foto alanı doğrulanmadı — bu netleştirilmesi gereken bir nokta.

### Boşluk tablosu

| Özellik | MSAERP | Stabler | Durum | Plan | Tahmini zaman |
|---|---|---|---|---|---|
| Truck listesi/filtreleri | Var, ama `destination_warehouse.name` bug'ı (CharField'a `.name` erişimi) | Doctype hazır, `destination_warehouse` artık gerçek Link→Warehouse (bug çözülmüş) | 🔜 | Faz 2 SPA — TruckBoard | Faz 2 |
| Truck formu (sürücü, sıcaklık hedefleri, taşıma maliyeti) | Var | Doctype alanları paralel/eksiksiz | 🔜 | Faz 2 SPA — TruckBoard/Form | Faz 2 |
| **Truck Receipt QC formu (sıcaklık/ambalaj/mühür checkbox, 4 fotoğraf, per-kutu condition)** | **Tasarlanmış ama hiç erişilemiyor** (dead template, hiçbir URL render etmiyor) | Doctype + **kod-seviyesinde zorunlu sıcaklık kontrolü** (`frappe.throw` submit'te) var; SPA formu henüz yok | 🔜 (backend ✅) | **Faz 2'nin İLK sayfası** — TruckReceiptForm, tablet-first, "saha pilotu" olarak planlanmış | Faz 2, öncelikli (~Ağu 2026 başı) |
| Fotoğraf ekleri (4 ayrı etiketli foto) | Model var, UI hiç erişilemiyor | Doğrulanamadı — attach mekanizması netleşmedi | 🔜 | Faz 2 SPA tasarımında netleştirilmeli | Faz 2 |
| Truck→GRN otomatik ilişki, "Create GRN" butonu | Kırık (`NoReverseMatch`, kayıtlı olmayan URL) | GRN Checklist ayrı doctype, Truck Receipt submit sonrası `advance_truck_after_receipt` otomatik truck'ı GRN_CREATED'a taşıyor | ✅ (Stabler net üstün) | — | Tamam |
| Sınır geçişinde taşıma faturası otomasyonu | Var (sinyal, 3 katmanlı maliyet bulma, yerel VendorBill) | Var (senkron hook, DRAFT Purchase Invoice, idempotent `XBORDER-` referansı) | ✅ | — | Tamam |
| **PR-per-truck (kısmi Purchase Receipt, batch+expiry ile)** | **Yok** — hiçbir kod yolu GRN/truck seviyesinde gerçek bir Purchase Receipt oluşturmuyor | **Var** — Truck Receipt submit → senkron kısmi PR + batch + expiry + PO bağlantısı | ✅ (Stabler'ın kasıtlı düzeltmesi) | — | Tamam (backend) |
| Sadece "Good" condition stoğa girer, Damaged/Rejected claim trail'de kalır | Model alanı var ama hiçbir gerçek akışta ayrım yapılmıyor (hepsi tek toplam kg) | Kod-seviyesinde uygulanıyor (`good_qty` fonksiyonu) | ✅ | — | Tamam (backend) |

### Notlar/kararlar

- Bu bölümdeki en çarpıcı bulgu: MSAERP'te QC/sıcaklık/fotoğraf iş akışı **tasarlanmış ama üretimde hiç kullanılamıyor** — sahadaki gerçek veri girişi (`grn_update_spreadsheet`) sadece kutu/kg sayıyor, hiçbir denetim verisi kaydetmiyor. Stabler bunu hem doctype hem de **kod-seviyesinde zorunlu kural** (sıcaklık aralığı dışıysa not zorunlu, yoksa submit engellenir) olarak yeniden kuruyor — bu MSAERP'te asla var olmamış yeni bir kontrol katmanı, "parite" değil gerçek bir iyileştirme.
- TruckReceiptForm'un Faz 2'nin **ilk** sayfası ve "saha pilotu" olarak seçilmesi (`docs/plans/2026-07-09-msaerp-to-stabler-migration-plan.md`, R11: "Warehouse-staff adaptation" riskine karşı mitigasyon) bilinçli bir sıralama kararı — tablet-first UI, depo personelinin adaptasyonunu erken test etmek için.
- Fotoğraf eki mekanizmasının tam olarak nasıl tasarlandığı (MSAERP'teki 4 ayrı etiketli alan mı, yoksa Frappe'nin genel "Attach" çoklu-dosya mekanizması mı) Faz 2 SPA tasarımı sırasında netleştirilmeli.

---

## 3. GRN (Goods Receipt Note / Mal Kabul Fişi)

### MSAERP'de bugün

**ÖNEMLİ ALTYAPI BULGUSU — iki farklı `grn_detail.html` var, biri "gölgede":** `templates/grn/grn_detail.html` (proje kökü) Django'nun `TEMPLATES[0]["DIRS"]` ayarı nedeniyle **her zaman** `proforma_app/templates/grn/grn_detail.html`'in önüne geçiyor (dosya-sistemi loader, app-dizini loader'ından önce kontrol ediliyor). Yani **gerçekte render edilen** dosya kök `templates/` altındaki "spreadsheet" arayüzü; **`proforma_app/templates/grn/grn_detail.html`** (Approve GRN butonu, Variance Analysis paneli, satır-bazlı status rozetleri, vet-sertifika uyarısı içeren, daha zengin sürüm) **hiçbir zaman kullanıcıya gösterilmiyor** — kod tabanında var ama erişilemez.

**Liste görünümü** — `templates/grn/grn_list.html`

- Başlık "Goods Receipt Notes", alt başlık "One checklist per commercial invoice - tracking truck arrivals". **"Create GRN" butonu yok** — boş durum mesajı: *"GRNs are automatically created when a commercial invoice is created."*
- 4 istatistik kartı: Total, Pending, Receiving, Completed.
- Filtreler: Search (GRN#, CI#, vendor), Status, Warehouse, Vendor.
- Kolonlar: GRN #, CI & Vendor, **Expected/Received** (çift ilerleme çubuğu: Boxes ve Weight, >%100 ise ⚠ öneki), Trucks (sayı rozeti), Status, Actions (sadece "View").

**Detay (gerçekte render edilen "spreadsheet" arayüzü)** — `templates/grn/grn_detail.html`

- Başlık "GRN {no} - Data Entry"; ilerleme özet kartları (Expected/Received/Pending/Status); `grn.erpnext_purchase_receipt` set edilmişse yeşil "Synced: {pr_name}" — **tek senkron göstergesi bu, ama pratikte bu alan hiç dolmuyor** (bkz. aşağı).
- Linked Trucks çipleri + "Add Truck" modalı.
- Photo Documentation bölümü — sadece herhangi bir truck'ın fotoğrafı varsa gösteriliyor (ama Bölüm 2'de görüldüğü gibi erişilebilir akışta foto hiç yükleniyor).
- **Spreadsheet tablosu**: sabit kolonlar (Item Code, Product Name, Expected kg) + **her truck için** 3 kolonluk grup (Boxes/Box KG/Total KG, daraltılabilir), trailing Total Received/Pending kolonları.
- Kaydet butonları: "Export to Excel", "Debug", "Save Data", **"Complete GRN"** (finalize).
- **Bu sayfada YOK:** Approve GRN butonu, Variance Analysis paneli, vet-sertifika gate uyarısı, satır-status rozetleri — hepsi sadece gölgedeki (erişilemez) şablonda var.

**Model — `GoodsReceiptNote`** (`models.py:3669`)

- `STATUS_CHOICES` (`GRN_STATUS_CHOICES`): **PENDING, RECEIVING, PARTIAL, COMPLETE, DISCREPANCY** — dikkat: `APPROVED` bu listede **yok**.
- `VARIANCE_CATEGORY_CHOICES`: NORMAL (±2%), MINOR (±5%), MAJOR (±5-10%), CRITICAL (>±10%).
- `update_totals()` — received/pending/tamamlanma%/varyans% hesaplar, `claim_required=True` eğer |varyans%|>2, status'ü PENDING/RECEIVING/COMPLETE/DISCREPANCY olarak set eder — **hiçbir zaman `APPROVED` set etmez.**
- `save()` — yorum "GL journal entry oluşturmak için override" diyor ama gövde artık boş (no-op), `_post_grn_journal_entry`/`_try_ias21_posting`/`_fallback_usd_posting` hepsi stub ("GL posting removed — ERPNext handles accounting").
- `erpnext_purchase_receipt`, `erpnext_stock_entry`, `erpnext_lcv` — üç ayrı CharField, hepsi varsayılan boş.

**ÜÇ FARKLI, BİRBİRİNDEN BAĞIMSIZ TAMAMLAMA/ONAY YOLU (kritik bulgu):**

1. **`grn_update_spreadsheet`, `action=finalize`** — **canlı UI'dan erişilebilen tek yol** ("Complete GRN" butonu). `grn.status = "COMPLETE"` set eder (vet-sertifika kontrolü **atlanarak**), `GRNCompletionService.complete_grn()` çağırır — bu servis **yerel** `Batch`/`StockEntry`/`StockLedgerEntry` ve **isteğe bağlı yerel GL `JournalEntry`** oluşturuyor. **Bu, CLAUDE.md kuralı #2'yi ("ERPNEXT_ENABLED=True iken asla yerel GL kaydı oluşturma") doğrudan ihlal ediyor.** Bu yolda **hiçbir ERPNext Purchase Receipt veya LCV oluşmuyor.**
2. **`grn_approve` view'ı** (`views.py:6058`, `proforma_app.approve_goodsreceiptnote` izni) — `GRNApprovalService.approve_grn()` çağırıyor, **vet-sertifika gate'ini uyguluyor**, ERPNext Stock Entry (Material Receipt) oluşturuyor. **Ama canlı `grn_detail.html`'de bu view'a giden hiçbir buton yok** — sadece gölgedeki (erişilemez) şablonda referans var.
3. **`GRNCompletionService.complete_grn()`** — kendi `'COMPLETED'` status string'ini kullanıyor (modelin `COMPLETE`'inden bile farklı yazım) — üçüncü, bağımsız bir status sözlüğü.

**Vet-sertifika gate'i** (`GRNApprovalService.approve_grn`, `grn_services.py:352`): `grn.status` DRAFT/PENDING olmalı → CI'nin `vet_certificates.filter(status='APPROVED', expiry_date__gte=today)` boş değilse geç, boşsa **`VetCertificateRequiredError`** fırlat: *"Cannot approve GRN {no}: CI {no} has no valid vet certificate. Upload and approve a vet certificate first."* — **ama bu kontrol sadece `grn_approve` yolunda çalışıyor, günlük kullanılan "Complete GRN" butonunda hiç çalışmıyor.**

**Otomasyonlar/sinyaller:**
- `create_grn_for_ci` (post_save, CommercialInvoice) — CI status'ü STUFFED/GATE_IN/SAILED/AT_PORT/CUSTOMS_CLEARANCE/DELIVERED_TO_UZBEKISTAN/CUSTOMS_CLEARED'a ulaştığında, o CI için henüz GRN yoksa otomatik oluşturur (`warehouse="Main Warehouse"` hardcoded, `created_by=vendor.name` — gerçek kullanıcı değil).
- `create_lcv_on_grn_approval` (pre_save, GRN) — `status == "APPROVED"` VE `erpnext_purchase_receipt` doluysa LCV oluşturmayı tetikler. **`erpnext_purchase_receipt` hiçbir zaman dolmadığı için bu sinyal pratikte hiç ateşlenmiyor** (bkz. Bölüm 4).

**Bead takip notu:** `.beads/issues.jsonl`'de "Feature 4: Automated LCV on GRN Approval" issue'su `status: closed`, `close_reason: "All 7 features implemented"` olarak kapatılmış — ama zincir kanıtlanabilir şekilde çalışmıyor (PR hiç oluşmuyor).

### Stabler'da bugün

**GRN Checklist** doctype — **submit edilebilir**, `autoname: GRN-{YYYY}-{#####}`, her Commercial Invoice için tek (`commercial_invoice` unique). Alanlar: `receipt_status` (Pending/Receiving/Complete/Discrepancy, salt-okunur), toplamlar (salt-okunur, hesaplanmış), varyans bölümü (`variance_boxes/kg/percentage`, `variance_category`, `claim_required`, `claim_reference`), **`vet_cert_override`** (Check, default 0 — "Imports Manager only: bypass the veterinary certificate requirement at submit"), `landed_cost_vouchers` (child table → **GRN LCV Ref**, `allow_on_submit: 1` — "Auto-appended DRAFT Landed Cost Vouchers (initial on submit, plus any additional for late costs)").

**Mimari düzeltme:** GRN Checklist docstring'i açıkça: **"umbrella/progress document — stock entry does NOT happen in GRN, see TruckReceipt"** diyor. Yani MSAERP'teki "GRN onayı stok girişini tetikliyor" tasarımı (P0-2 bug'ının kaynağı) tamamen terk edilmiş; stok girişi artık **her Truck Receipt submit'inde** (Bölüm 2) gerçekleşiyor, GRN sadece toplayıcı/ilerleme dokümanı.

**Varyans motoru** (`grn_math.py`) — MSAERP'in `GoodsReceiptNote.update_totals`/`GRNLineItem.update_totals` mantığından **birebir taşınmış** eşikler: ≤%2 NORMAL, ≤%5 MINOR, ≤%10 MAJOR, >%10 CRITICAL, claim_required her zaman >%2'de. Fark: GRN artık **fiziksel alınan miktarı** (hasarlı dahil, claim trail için) kaydediyor; **satılabilir stok** (sadece Good condition) Purchase Receipt'e giriyor — bu ayrım MSAERP'te yoktu.

**Submit-zamanı gate'ler** (`hooks.grn_before_submit`): `received_total_kg <= 0` ise throw; **geçerli bir Vet Certificate yoksa VE `vet_cert_override` set edilmemişse throw** (override sadece Imports Manager/System Manager rolüyle mümkün) — **MSAERP'teki gate'in aksine, bu artık submit'i gerçekten engelleyen, atlanamayan bir kural** (MSAERP'te sadece `grn_approve` gibi kullanılmayan bir yolda vardı).

**Çoklu-LCV desteği:** `GRN LCV Ref` child (lcv, posted_on, note) — GRN submit'inde ilk LCV otomatik oluşuyor (`grn_on_submit` → `create_landed_cost_voucher`), sonradan gelen maliyetler için `create_additional_lcv` whitelisted API'siyle **ikinci/üçüncü LCV** eklenebiliyor (sadece henüz `lcv_ref`'i boş olan `Container Cost Line` satırları — yani "delta" — toplanıyor). **MSAERP'in "tek LCV, force-clear-and-repost" hack'inin doğrudan düzeltmesi** (bkz. Bölüm 4).

**Truck Receipt → GRN senkronizasyonu:** her Truck Receipt submit/cancel sonrası `hooks.recompute_grn_from_receipts` GRN Checklist Item'ları **tüm submit edilmiş** (docstatus=1) Truck Receipt'lerden yeniden toplar, `first_receipt_date`/`trucks_received_count` günceller, sonra `validate()`→`update_totals()` tetiklenir.

**SPA:** Henüz yok (ImportsDashboard placeholder), Faz 2'de GRNChecklist sayfası olarak planlı.

### Boşluk tablosu

| Özellik | MSAERP | Stabler | Durum | Plan | Tahmini zaman |
|---|---|---|---|---|---|
| GRN listesi | Var (istatistik kartları + filtre) | Doctype hazır, liste ekranı yok | 🔜 | Faz 2 SPA — GRNChecklist | Faz 2 |
| GRN spreadsheet veri girişi (truck×item matrisi) | Var, tek erişilebilir akış, sadece boxes/kg | Backend hazır (grn_math), SPA yok | 🔜 | Faz 2 SPA — GRNChecklist | Faz 2 |
| **Vet-sertifika onay gate'i** | **Tasarlanmış ama günlük akışta hiç uygulanmıyor** (yalnızca kullanılmayan `grn_approve` yolunda çalışıyor) | **Submit'i gerçekten engelleyen zorunlu kural** (`grn_before_submit`), sadece yetkili rol override edebilir | ✅ (Stabler net üstün, gerçek bir düzeltme) | Backend tamam | Tamam |
| Varyans hesaplama/kategori (%2/%5/%10 eşikleri) | Var, çalışıyor | MSAERP'ten birebir taşındı (`grn_math.py`) | ✅ | Backend tamam, SPA görünümü Faz 2'de | Faz 2 (UI) |
| **Onay/tamamlama akışı tutarlılığı** | **3 farklı, birbirini bilmeyen yol** (spreadsheet finalize / grn_approve / GRNCompletionService), status sözlükleri bile tutarsız | **Tek submit akışı**, doctype workflow'una entegre, gate'ler `before_submit` hook'unda merkezi | ✅ (Stabler net üstün) | — | Tamam |
| GRN onayında yerel GL kaydı oluşturma | **Var — CLAUDE.md kural #2'yi ihlal ediyor** (GRNCompletionService) | Yok — LCV/PR akışı tamamen ERPNext-native | ✅ | — | Tamam |
| Çoklu/gecikmeli LCV (geç gelen maliyetler) | Yok — tek LCV, force-clear-and-repost hack'i, tüm maliyetleri yeniden postalıyor | Var — `GRN LCV Ref` child + `create_additional_lcv`, sadece delta'yı postalıyor | ✅ (Stabler'ın kasıtlı düzeltmesi) | — | Tamam (backend) |
| GRN detay sayfasında ERPNext senkron göstergesi | Var ama pratikte hep boş (PR asla oluşmuyor) | Doğal olarak dolu olacak (PR artık gerçekten oluşuyor — Bölüm 2) | ✅ | Faz 2 SPA'da gösterilecek | Faz 2 |

### Notlar/kararlar

- Bu bölümdeki en kritik mimari karar, GRN'in **"stok girişi yapmayan, sadece toplayıcı/ilerleme dokümanı"** olarak yeniden tanımlanması. MSAERP'te GRN onayı hem stok girişini hem de (teorik olarak) LCV'yi tetikliyordu ama gerçekte hiçbiri düzgün çalışmıyordu; Stabler'da stok girişi Truck Receipt seviyesine indirilmiş, GRN sadece checklist+varyans+LCV orkestrasyon katmanı.
- Vet-sertifika gate'inin gerçekten zorunlu kılınması, MSAERP'te veri kalitesi açısından ciddi bir risk kapatıyor: MSAERP'te teorik olarak "sertifikasız GRN onaylanamaz" kuralı vardı ama günlük kullanılan buton bunu tamamen atlıyordu — yani gerçekte hiçbir zaman uygulanmıyordu.
- Cutover (Faz 5) öncesi ETL'de MSAERP'teki GRN verisi taşınırken, `APPROVED`/`VERIFIED`/`COMPLETED` gibi modelin kendi choice listesinde bile olmayan status değerlerinin normalize edilmesi gerekecek — bu ETL adımı için ayrı bir mapping tablosu hazırlanmalı.

---

## 4. Landed Cost (Konteyner Maliyeti / LCV)

### MSAERP'de bugün

**Dashboard** — `templates/commercial_invoice/landed_cost_dashboard.html`, `LandedCostDashboardView`

- Başlık "Landed Cost Overview" — "Monitor import costs and accounting sync status".
- 4 özet kartı: Total CIs, Total Landed Cost ($), Avg Cost/kg, **Sync Rate** ("PR + LCV submitted" — GRN'si olan CI'ların yüzde kaçında hem `grn.erpnext_purchase_receipt` hem `grn.erpnext_lcv` dolu — **bu metrik PR hiç dolmadığı için yapısal olarak her zaman %0**).
- Filtreler: arama, Status, Vendor.
- Tablo: CI Number, Vendor, Containers, Product Cost, Extra Costs, Cost/kg, Expenses (rozet), **PR** rozeti (yeşil "Synced"/kırmızı "Failed"/gri "—"), **LCV** rozeti (aynı desen).

**Detay** — `templates/commercial_invoice/landed_cost_detail.html`, `LandedCostDetailView`

- Sync Status kartı: GRN (no+status), Purchase Receipt (varsa isim+"Submitted", yoksa "—"), **Landed Cost Voucher** — Alpine.js 3 durum: (a) LCV varsa isim + "Re-post" butonu; (b) PR var ama LCV yoksa "Pending" + "Post" butonu; (c) **PR yoksa (yaygın durum) hiçbir buton yok** — yani "Post" butonu pratikte neredeyse hiçbir gerçek GRN için görünmüyor.
- **Cost Breakdown kartı** — `CIExpense` modeline dayalı, kategori grupları: TRANSPORT, BORDER_CROSSING, HANDLING, STORAGE, INSURANCE, DOCUMENTATION, CUSTOMS, OTHER. Product Cost, CI-seviyesi VAT, Customs Clearance Fee satırları, Grand Total, Cost/kg footer.
- "Cost/kg Analysis by Product" — ürün bazlı, ama **düz bir markup oranı** uyguluyor (`landed_price_per_kg = product_price_per_kg * (grand_total/product_cost)`), gerçek ağırlık/değer bazlı tahsis değil — bu, aşağıdaki `LandedCostAllocation` mekanizmasından **tamamen ayrı, basitleştirilmiş** bir gösterge.

**İKİ AYRI, PARALEL LANDED-COST MOTORU (kritik bulgu):**

1. **`LandedCostAllocation` modeli + `LandedCostService`** (`services/landed_cost_service.py`) — `VendorBillItem`/`Batch` üzerinde çalışır, WEIGHT/VALUE bazlı tahsis yapar, `Batch.valuation_rate`'i günceller, **yerel bir GL journal entry postalıyor** (`_create_gl_entry`, DR Inventory 1300 / CR expense account, `auto_post=True`). **Bu, CLAUDE.md kural #2'yi ihlal ediyor** ve hiçbir çağıran kod bulunamadı (views.py/signals.py'de ad hoc/bağlantısız görünüyor).
2. **ERPNext LCV builder — `create_landed_cost_for_grn(grn)`** (`erpnext_integration/sync.py:617`) — GRN/Purchase Receipt üzerinde çalışır (bkz. aşağı).

Gap-analiz raporu bunu doğrudan §6'da "dual valuation engine" olarak işaretliyor: iki motor paralel çalışıp COGS'ta birbirinden **sapacak**.

**ERPNext LCV builder mantığı (`create_landed_cost_for_grn`):**
- **Çağrı noktaları (3):** `grn_approve` view, `ManualLCVPostView`, `create_lcv_on_grn_approval` sinyali — **her üçü de aynı guard'a çarpıyor**: `if not grn.erpnext_purchase_receipt: return ""` — bu alan **hiçbir zaman dolmadığı için her zaman no-op.**
- Kod çalışsaydı: 9 USD konteyner alanını toplar (freight, iran_customs_duty, cross_border_transport, insurance, certificate, iran_port_thc, iran_storage_fee, iran_demurrage, iran_inspection), + 2 UZS alan direkt (uzb_customs_duty_uzs, uzb_port_handling_uzs), + CI-seviyesi `uzb_vat_usd` + `effective_customs_fee_uzs` (konteyner sayısına **bölünerek** — bug!). **13 maliyet bileşeni**, hepsi tek hardcoded hesap **"Stock Adjustment - MSA"**'ya gidiyor. `distribute_charges_based_on: "Amount"` (dondurulmuş et için ağırlık-bazlı olması gerekirken).

**Gap-analiz raporundaki tüm bilinen buglar (§3, doğrulanmış):**
1. **Customs Clearance Fee eksik sayılıyor** — CI-seviyesi ücret konteyner sayısına bölünüp sadece bir payı ekleniyor; 4-konteynerli CI'da ücretin %75'i kayboluyor.
2. Tüm bileşenler hardcoded `"Stock Adjustment - MSA"` hesabına gidiyor.
3. **Import VAT stoğa kapitalize ediliyor** ("Uzbekistan VAT 12%") — geri kazanılabilir bir girdi kredisiyse IAS 2'yi ihlal ediyor olabilir.
4. **CustomsDeclaration (ГТД) tamamen görmezden geliniyor** — LCV, manuel girilen `container.uzb_customs_duty_uzs`'yi okuyor, gerçek tahakkuk edilmiş `duty_amount`/`vat_amount`/`excise_amount`'ı değil.
5. `"Amount"` bazlı dağıtım kullanılıyor, ağırlık-bazlı (`"Qty"`) olması gerekirken.
6. Tek-LCV-per-GRN idempotency, geç gelen maliyetleri (demuraj, soğuk depo, muayene faturaları) engelliyor — `ManualLCVPostView`'in "force" modu **tüm** maliyetleri yeniden postalıyor, sadece delta'yı değil.
7. Tek FX kuru (onay tarihinde) kullanılıyor — IAS 21 işlem-tarihi kurlarını tercih eder.
8. LCV submit, PR'nin posting tarihinden itibaren GL/Stok Defterini yeniden postalıyor — mal zaten satılmışsa COGS geriye dönük olarak yeniden yazılır.

**Eksik maliyet bileşenleri (§5):** UZ-tarafı veteriner muayene/SES/lab ücretleri (VetCertificate modeli var ama maliyet alanı yok), cutover öncesi UZ soğuk depolama, UZ-tarafı demuraj (sadece Iran tarafı var), gümrük komisyoncusu ücreti ayrı kalem, Excise (`CustomsDeclaration.excise_amount` var ama hiç okunmuyor).

**Manuel maliyet girişi:** `LandedCostUpdateView` — Container üzerinde 13 alanlık whitelist ile AJAX inline-edit. **Manuel LCV post/re-post:** `ManualLCVPostView` — force modunda LCV'yi **temizleyip yeniden oluşturuyor** ("clear-and-repost hack").

### Stabler'da bugün

**`lcv_math.py`** — MSAERP'in gap-analiz raporundaki tespit edilen buglarını **doğrudan referans alarak** tasarlanmış (dosya başlığında: "critique M8 + audit §3", "fixing the known bugs in the Django `create_landed_cost_for_grn` that must NOT be replicated"):

- **Customs Clearance Fee — tam tutar, konteyner sayısına bölünmüyor.** Maliyet satırları olduğu gibi toplanıyor.
- **VAT kapitalize edilmiyor** — bileşen adı "VAT" içeriyorsa `aggregate_components()` tamamen atlıyor (`is_vat_component`).
- **Ürün bedeli / CIF navlun çifte kapitalizasyonu yok** — Container Cost Line doctype'ında böyle bir bileşen tasarım gereği yok.
- **Ağırlık (Qty) bazlı dağıtım** — `distribute_charges_based_on="Qty"`, dondurulmuş et için doğru yaklaşım.
- **Tek, yapılandırılabilir gider hesabı** (`Stabler Settings.imports_lcv_expense_account`) — hardcoded "Stock Adjustment - MSA" yerine; hesap ayarlanmamışsa throw (asla sessizce yanlış hesaba yazmıyor).

**Çoklu-LCV / geç maliyet desteği:** `unconsumed(cost_lines)` — bir maliyet satırı bir LCV tarafından tüketildiyse (`lcv_ref` dolu) sonraki LCV'ler onu atlıyor; `create_additional_lcv` API'si sadece **delta**'yı toplayıp yeni bir DRAFT LCV oluşturuyor — MSAERP'in "force-clear-and-repost" hack'inin tam tersi, doğru bir çözüm.

**Orkestrasyon (`hooks.py`):** GRN submit → `grn_on_submit` → ilk LCV kuyruğa alınır (`note="initial"`). `_build_and_save_lcv`: gider hesabını `Stabler Settings`'ten çözer (yoksa throw), submit edilmiş PR'ları toplar (`_submitted_prs_for_grn`), maliyet satırlarını toplar (`_collect_cost_lines` — CI'ye bağlı tüm Import Container'ları dolaşır, `include_in_landed_cost=1` + boş `lcv_ref` filtreler), USD kurunu tamamlanma tarihinde çözer (`erpnext.setup.utils.get_exchange_rate`, hata durumunda 1.0 fallback), DRAFT LCV'yi oluşturur, `get_items_from_purchase_receipts()` ile dağıtım satırlarını otomatik doldurur, GRN'e bir `GRN LCV Ref` satırı ekler, tüketilen her `Container Cost Line`'ı yeni LCV adıyla damgalar.

**CustomsDeclaration (ГТД) entegrasyonu:** Henüz doctype yok (bkz. Bölüm 5) — plan §4'te "GRN→APPROVED → LCV built from ГТД + Cost Lines, excluding product/CIF" diye belirtilmiş, yani **Faz 1'de ГТД doctype'ı geldiğinde LCV'nin onu okuyacağı tasarım niyeti var** — MSAERP'in "ГТД tamamen görmezden geliniyor" bug'ının önceden planlanmış düzeltmesi.

**Batch değerleme:** Truck Receipt seviyesinde otomatik Batch oluşturuluyor (`_ensure_batch`, idempotent, expiry set edilebiliyor) — MSAERP'in `stock_check_service.py`'deki `batch_no: ''` ("Batch tracking handled separately" yorumuyla boş bırakılan) sorununun düzeltmesi.

### Boşluk tablosu

| Özellik | MSAERP | Stabler | Durum | Plan | Tahmini zaman |
|---|---|---|---|---|---|
| Landed cost dashboard/detay UI | Var (Bootstrap+Alpine, kapsamlı) | Doctype/backend hazır, SPA yok | 🔜 | Faz 2 SPA — LandedCostReview | Faz 2 |
| **LCV otomasyonu (GRN onayından tetikleme)** | **Tasarlanmış ama hiç çalışmıyor** — 3 çağrı noktası da `erpnext_purchase_receipt` boş olduğu için no-op | **Çalışıyor** — Truck Receipt submit → gerçek PR → GRN submit → gerçek LCV zinciri eksiksiz | ✅ (Stabler'ın kritik düzeltmesi) | Backend tamam | Tamam |
| Customs Clearance Fee tam/doğru toplanması | **Bug: konteyner sayısına bölünüyor**, %75'e kadar kayıp | **Düzeltildi** — tam tutar, bölünmeden | ✅ | — | Tamam |
| **VAT hariç tutma (kapitalize edilmemesi)** | **Bug: VAT stoğa kapitalize ediliyor** | **Düzeltildi** — bileşen adı "VAT" içeriyorsa otomatik hariç | ✅ | — | Tamam |
| Ağırlık (Qty) bazlı dağıtım | Bug: `"Amount"` bazlı kullanılıyor | Düzeltildi — `"Qty"` bazlı | ✅ | — | Tamam |
| Yapılandırılabilir gider hesabı | Bug: hardcoded "Stock Adjustment - MSA" | Düzeltildi — `Stabler Settings`'ten, yoksa throw | ✅ | — | Tamam |
| Çoklu/gecikmeli LCV, sadece delta postalama | Yok — force-clear-and-repost tüm maliyetleri tekrar postalıyor | Var — `unconsumed()` ile sadece delta | ✅ | — | Tamam |
| ГТД (CustomsDeclaration) verisinin LCV'ye girmesi | Yok — LCV manuel konteyner alanlarını okuyor, ГТД'yi hiç görmüyor | **Planlanmış** (plan §4) ama ГТД doctype'ı henüz yok | 🔜 | Faz 1 (ГТД doctype) + LCV entegrasyonu | Faz 1 |
| Batch değerleme / expiry (FEFO) | `batch_no: ''` — batch takibi "ayrıca ele alınacak" denip hiç yapılmamış | Otomatik Batch + expiry, Truck Receipt seviyesinde | ✅ | — | Tamam (backend) |
| İki paralel maliyet motoru (LandedCostAllocation + ERPNext LCV) sorunu | **Var — CLAUDE.md kural #2 ihlali**, COGS sapma riski | Tek motor (ERPNext LCV), yerel GL kaydı yok | ✅ | — | Tamam |
| Eksik maliyet bileşenleri (UZ veteriner/lab, UZ demuraj, komisyoncu ücreti, excise) | Eksik — 13 hardcoded alan yeterli değil | Container Cost Line açık uçlu (`Other` dahil serbest bileşen listesi) — genişletilebilir ama şu an aynı 13 bileşen + Other | 🔜 (kısmi) | Faz 1/2'de bileşen listesi genişletilebilir | Faz 1-2 |

### Notlar/kararlar

- Landed Cost, bu beş bölüm arasında Stabler'ın MSAERP'e göre **en fazla sayıda kasıtlı, belgelenmiş bug düzeltmesi** yaptığı alan — `lcv_math.py`'nin dosya başlığı bu düzeltmeleri açıkça MSAERP gap-analiz raporuna (2026-07-03) atıfla listeliyor. Bu, göç sunumunda/karar toplantılarında öne çıkarılmaya değer somut bir kazanım.
- ГТД (CustomsDeclaration) entegrasyonu henüz **planlanmış ama inşa edilmemiş** — bu, Bölüm 5'teki en büyük boşlukla doğrudan bağlantılı; ГТД doctype'ı Faz 1'de gelmeden LCV'nin gümrük vergisi/KDV/ÖTV rakamlarını gerçek beyannameden değil, hâlâ manuel girilen alanlardan okuması riski var.
- Cutover öncesi, MSAERP'teki iki paralel maliyet motorunun (`LandedCostAllocation`/`LandedCostService` ile ERPNext LCV) hangi verilerinin (varsa) taşınacağı netleştirilmeli — muhtemelen sadece ERPNext LCV verisi taşınacak, yerel `LandedCostAllocation` kayıtları geçmiş kayıt olarak arşivlenip taşınmayacak (ETL kapsamı planında netleştirilmeli).

---

## 5. Customs Declaration (ГТД) + Vet Certificate + Freight Booking

### MSAERP'de bugün

#### 5.1 Customs Declaration (ГТД)

**Model — `CustomsDeclaration`** (`models.py:3252`)

- `STATUS_CHOICES`: DRAFT, SUBMITTED, UNDER_REVIEW, APPROVED ("Cleared"), REJECTED.
- `commercial_invoice` VE `container` — her ikisi de opsiyonel FK (CI-anchored veya container-anchored olabilir).
- `gtd_number` (unique, format `XXXXX/DDMMYY/NNNNNNN`), `declaration_date`, `customs_office`, `customs_value_usd`/`uzs`, **`duty_amount`, `vat_amount`, `excise_amount`** (UZS, otomatik hesaplanan), `document` (dosya), `cleared_date` (**sadece admin panelinden düzenlenebilir**, formda yok), `history` (django-simple-history).

**Alt model — `CustomsDeclarationLineItem`** — kod yorumunda açıkça: *"Field names map to standard ГТД boxes (lex.uz/docs/7357270). Spec excerpt was missing at design time; rename freely once the regulation columns are confirmed."* — yani **gerçek ГТД kutu numaralarına eşleme tasarım anında doğrulanamamış**, geçici olarak işaretlenmiş. Kalem verileri (açıklama, miktar, değer) CI'den **canlı okunuyor, hiç snapshot alınmıyor** — bilinçli tasarım kararı.

**Liste/form/detay:** Konteyner-bazlı liste (`customs/<container_id>/`), global bir liste/arama **yok**. Form: Declaration Information, Customs Valuation, Clearance Status, Supporting Documents. Ayrıca **CI-anchored oluşturma formu** (`customs_declaration_from_ci_form.html`) — CI satırlarından checklist ile seçim yapılıp declaration oluşturuluyor.

**Silme onay ekranında bug:** CI-anchored (container=None) declaration'lar için iptal linki hâlâ container-scoped listeye gitmeye çalışıyor → `AttributeError`/`NoReverseMatch` riski.

**İKİ AYRI ÜCRET HESAPLAMA MEKANİZMASI (kritik bulgu):**

1. **`CustomsFeeService`** (CI-seviyesi "customs clearance fee", БРВ-tier bazlı komisyoncu/idari ücret) — `BRVSetting` (devlet tarafından belirlenen taban değer, UZS, tarihli) × `CustomsFeeTier` (USD aralığına göre çarpan) + %25 mesai-dışı sürşarj (varsa). **Tier/БРВ verisi migration'larda seed edilmemiş — Django admin'den elle girilmesi gerekiyor.**
2. **`CustomsDeclarationForm.clean()`** — declaration'ın `duty_amount`'ını **aynı БРВ-tier formülünü** kullanarak dolduruyor (yani "Import Duty" aslında gümrük komisyoncusu ücretiyle aynı formülden geliyor, HS-koduna dayalı gerçek ad-valorem bir vergi hesaplaması **hiçbir yerde yok**). `vat_amount = (customs_value_uzs + duty_amount) * 0.12`. `excise_amount` her zaman hardcoded 0. **Hesaplama try/except içinde sessizce yutuluyor** — БРВ/tier verisi eksikse form kullanıcıya hata göstermeden eski/varsayılan değerle kaydediyor.

**Test/factory sürüklenmesi:** Test dosyaları modelde olmayan `duties_paid`, `PENDING_CLEARANCE`/`CLEARED` status'leri, `clearance_date` (gerçek alan adı `cleared_date`) referans veriyor — bu test paketi çalıştırılırsa muhtemelen `TypeError` ile patlayacak, yani zaten güncel değil/çalışmıyor.

**Yetkilendirme:** Tüm customs declaration view'ları sadece `LoginRequiredMixin` — hiçbir izin kontrolü (permission check) yok, vet-sertifika onayının aksine.

**Sinyal:** Hiç yok — declaration kayıt/silme hiçbir otomasyonu tetiklemiyor (vendor bill, GL, bildirim vs. yok).

#### 5.2 Vet Certificate

**Model — `VetCertificate`** (`models.py:6304`) — docstring: *"Regulatory requirement blocking GRN approval until: (1) valid approved cert attached to CI, (2) reviewed/approved by manager, (3) not expired."*

- `STATUS_CHOICES`: PENDING, APPROVED, REJECTED, EXPIRED (ama hiçbir kod otomatik EXPIRED'a geçirmiyor — geçerlilik her zaman `is_valid()` ile dinamik hesaplanıyor: `status == 'APPROVED' and expiry_date >= today`).
- Upload → Review/Approve akışı: `VetCertificateUploadView` (CI'ye bağlı, cert numarası/otorite/tarihler/dosya), `VetCertificateApproveView` (**tek izin-korumalı view bu üç özellik arasında**, `proforma_app.change_vetcertificate` gerektiriyor) — Decision select (APPROVED/REJECTED/...), REJECTED seçilince JS ile Rejection Reason zorunlu görünür.
- Detay sayfasında açık gösterge: "Certificate Valid: ✓/✗" ve **"Can Approve GRN: ✓/✗"** — aynı boolean'dan (`is_valid`) türetiliyor, GRN ilişkisini kullanıcıya doğrudan gösteriyor.
- Silme/düzenleme endpoint'i yok — reddedilen bir sertifika yerinde düzeltilemez, yeni bir kayıt yüklenmesi gerekiyor.
- **GRN gate'i** — Bölüm 3'te detaylandırıldı: `GRNApprovalService.approve_grn` içinde uygulanıyor ama günlük kullanılan "Complete GRN" butonu bu servisi hiç çağırmadığı için **gate pratikte işlemiyor.**

#### 5.3 Freight Booking

**Model — `FreightBooking`** (`models.py:2416`) — docstring: *"Land Freight Booking for cross-border trucking. Exactly one of (CI, container) must be set. Posts to GL account 7400. Dual-track with CIExpense.TRANSPORT during Q2-Q3 2026 migration."*

- Tam alanlı, doğrulamalı bir model: booking_date/reference, pickup/delivery tarih+lokasyon (varsayılan "Bandar Abbas, Iran" → "Tashkent, Uzbekistan"), route, araç/sürücü bilgisi, amount+currency, bank_payment/cash_payment (soft-check, sadece uyarı loglar, engellemez).
- **HİÇBİR KULLANICI ARAYÜZÜ YOK** — `templates/` içinde `*freight*` araması **sıfır sonuç** veriyor, `urls.py`'de "freight" içeren hiçbir route yok, `views.py`'de `FreightBooking*View` sınıfı yok. **Tek erişim yolu Django Admin** (`FreightBookingAdmin` + CI admin sayfasına gömülü `FreightBookingInline`).
- Otomasyon var (sinyal seviyesinde çalışıyor): save'de `vendor` VE `commercial_invoice` ikisi de doluysa otomatik `VendorBill` (bill_type=TRANSPORT) oluşturuyor/güncelliyor; delete'de siliyor. **Container-anchored booking'ler (CI yok) hiçbir zaman vendor bill tetiklemiyor** — model `clean()`'i container-only'e izin verse de sinyal bunu atlıyor.
- Model docstring'inin "GL 7400'e postalıyor" iddiası kodda **uygulanmamış** (`get_default_gl_account()` her zaman `None` döndürüyor, yorum: "GL system removed").

**Sonuç:** Freight Booking, diğer iki özelliğe göre **belirgin şekilde daha az geliştirilmiş** — güçlü bir model + otomasyon var ama sıfır operasyonel UI.

### Stabler'da bugün

**Customs Declaration:** **Henüz hiç doctype yok.** Kodda sadece ileriye dönük referanslar var: `commercial_invoice.py` docstring'i "Customs-clearance statuses ... belong to the separate Customs Declaration doctype, not here" diyor (henüz var olmayan bir doctype'a atıf), `stabler_company_modules.json`'daki `enable_imports` alan açıklaması "Import/customs declaration pipeline" diye genel geçer bahsediyor. Migration planı (§3.1 DocType tablosu) ГТД'yi **Faz 1**'de inşa edilecek yeni custom doctype olarak listeliyor: *"duty/vat/excise are the source of LCV; child rows carry **snapshot** fields"* — yani MSAERP'in "canlı okuma, snapshot yok" tasarımının **tam tersi** bir karar önceden alınmış (ГТД verisi zamanla değişebileceği/resmi belge olduğu için snapshot mantıklı).

**Vet Certificate:** Doctype **var** (`stabler/stabler/doctype/vet_certificate/`), MSAERP'e paralel alanlar: `certificate_number` (unique), `commercial_invoice`, `issuing_authority`, `issue_date`/`expiry_date`, `status` (Pending/Approved/Rejected/Expired), `reviewed_by`, `rejection_reason`, `document` (Attach), `notes`. **Fark:** `validate()` içinde **otomatik expiry kontrolü var** — status Approved ama `expiry_date < today` ise otomatik olarak Expired'a çeviriyor (MSAERP'te bu hiç otomatik değildi, sadece `is_valid()` dinamik kontrol ediyordu, status hiç değişmiyordu). `has_valid_vet_cert(commercial_invoice)` modül fonksiyonu, GRN submit gate'inin (Bölüm 3) tek doğruluk kaynağı.

**Freight Booking:** **Henüz hiç doctype yok** — grep sonucu sıfır. Plan §3.1'de "FreightBooking → Freight Booking ('XOR validate')" olarak Faz 1'de inşa edilecek doctype listesinde var, ayrıntı yok.

**Import Expense** (MSAERP'in `CIExpense`'inin karşılığı, ilgili çünkü landed cost'a besleniyor): Plan §3.1'de "CIExpense → Import Expense: **plain Links** — `commercial_invoice` (zorunlu) + `container` + `truck` (opsiyonel) — Dynamic Link **değil** (madde m1). Onaylanınca servis Purchase Invoice'u üretir." diye tanımlı — henüz kod tabanında doctype yok, sadece planda.

**SPA:** CustomsQueue ve VetCertQueue, Faz 2'de **"v1 sadece liste görünümü"** olarak planlanmış (bilinçli kapsam sınırlaması, kritik eleştiri M10/R10: "no Desk fallback" riskine karşı — Stabler SPA hiçbir zaman Frappe Desk'e yönlendirmiyor, o yüzden her ekranın elle Vue'da yazılması gerekiyor, kapsam patlamasını önlemek için v1 bilinçli olarak dar tutulmuş).

### Boşluk tablosu

| Özellik | MSAERP | Stabler | Durum | Plan | Tahmini zaman |
|---|---|---|---|---|---|
| Customs Declaration (ГТД) doctype/model | Var, çalışıyor ama ГТД kutu-numarası eşlemesi doğrulanmamış, iki farklı ücret formülü çakışıyor | **Yok** — henüz inşa edilmedi | ❌ | Faz 1 (doctype+patch+hook), Faz 2 (CustomsQueue liste-only v1) | Faz 1-2 |
| ГТД liste/form/detay UI | Konteyner-bazlı liste, global arama yok; CI-anchored oluşturma formu var | Yok | ❌ | Faz 2 SPA — CustomsQueue (**v1 sadece liste**, detay formu daha sonra) | Faz 2 (liste), sonrası (form) |
| Gümrük vergisi/KDV/ÖTV hesaplama tutarlılığı | **Bug: "Import Duty" aslında komisyoncu ücret formülünden geliyor, gerçek HS-kod bazlı vergi hesabı yok**, БРВ/tier verisi seed edilmemiş | Plan: "duty/vat/excise LCV'nin kaynağı" — ГТД'den gerçek tahakkuk okunacak (Faz 1 tasarımı) | 🔜 | Faz 1 | Faz 1 |
| Vet Certificate doctype | Var, çalışıyor | **Var**, ek olarak otomatik expiry-durum geçişi eklenmiş | ✅ | Backend tamam | Tamam |
| Vet Certificate upload/review UI | Var (Bootstrap) | Doctype hazır, SPA yok | 🔜 | Faz 2 SPA — VetCertQueue (**v1 sadece liste**) | Faz 2 |
| Vet-sertifika → GRN gate | Tasarlanmış ama günlük akışta uygulanmıyor (bkz. Bölüm 3) | **Gerçekten uygulanıyor** (`grn_before_submit`), yetkiliyle override edilebilir | ✅ (Stabler net üstün) | — | Tamam |
| Freight Booking doctype | Var, güçlü model + otomasyon, ama **sıfır UI** (sadece admin) | **Yok** — henüz inşa edilmedi | ❌ | Faz 1 (doctype, "XOR validate"), sonrasında UI | Faz 1+ |
| Freight Booking UI | Yok (admin-only) | Yok | ❌/❌ | Plan detayı belirsiz — Faz 2 sayfa listesinde ayrı bir "FreightBooking" ekranı adı geçmiyor, netleştirilmeli | Belirsiz |
| Import Expense (CIExpense karşılığı) | Var (`CIExpense`, CI-seviyesi, kategori bazlı) | **Yok** — Faz 1'de "plain Links (Dynamic Link değil)" olarak planlı, onaylanınca servis PI üretecek | ❌ | Faz 1 (doctype), Faz 2 SPA (ImportExpenseList) | Faz 1-2 |

### Notlar/kararlar

- Bu üç özellik arasında en dengesiz durum Freight Booking: MSAERP'te güçlü bir model var ama sıfır UI; Stabler'da henüz doctype bile yok. Cutover öncesi bu üçünün (Customs Declaration, Freight Booking, Import Expense) **Faz 1'de** gerçekten teslim edilip edilmediği yakından takip edilmeli, çünkü hepsi LCV zincirine (Bölüm 4) veri besliyor ve Faz 1 gecikirse Faz 2 SPA ve Faz 3 ETL de gecikir.
- ГТД'nin Stabler tasarımında **snapshot** alanlarla tutulması (MSAERP'in "canlı okuma" tasarımının tersi) kasıtlı ve doğru bir karar: resmi bir gümrük beyannamesinin, beyan anındaki CI verisini donuk şekilde koruması gerekir; CI sonradan değişirse (fiyat revizyonu, satır düzeltmesi gibi) MSAERP'teki mevcut ГТД kayıtları sessizce değişebiliyor — bu bir veri bütünlüğü riski, Stabler'ın snapshot kararıyla ortadan kalkıyor.
- CustomsQueue/VetCertQueue'nun Faz 2'de **"v1 sadece liste"** olarak sınırlanması bilinçli bir kapsam kararı (kritik eleştiri M10) — detay/form ekranları büyük olasılıkla Faz 2 sonrası ayrı bir iterasyonda gelecek; bu, kullanıcı beklentisi yönetimi açısından paydaşlara net anlatılmalı.
- ETL sırasında (Faz 3) ГТД verisi MSAERP'ten taşınacaksa, `CustomsDeclarationLineItem`'ın kod yorumunda itiraf edilen "spec excerpt was missing at design time" belirsizliği netleştirilmeden taşıma yapılmamalı — yanlış kutu-numarası eşlemesiyle resmi bir gümrük belgesi taşınması ciddi bir uyum riski oluşturur.

---

## Genel Özet — En Büyük Boşluklar

1. **GRN → Purchase Receipt → LCV zinciri**: MSAERP'te tasarlanmış ama tamamen kırık (PR hiç oluşmuyor, LCV hep no-op, prod ERPNext'te satın alma tarafı sıfır kayıt). Stabler bunu PR-per-Truck-Receipt + submit-tetiklemeli LCV ile **baştan doğru** kuruyor — bu, en yüksek değerli düzeltme.
2. **QC/sıcaklık/fotoğraf iş akışı**: MSAERP'te tasarlanmış ama hiç erişilemeyen bir form (dead template); Stabler'da kod-seviyesinde zorunlu kılınan gerçek bir kontrol haline geliyor.
3. **Vet-sertifika → GRN gate'i**: MSAERP'te var ama günlük akışta atlanıyor; Stabler'da submit'i gerçekten engelleyen bir kural.
4. **Customs Declaration + Freight Booking + Import Expense**: Üçü de Stabler'da henüz **hiç yok**, Faz 1'e bağımlı; MSAERP'te ГТД ve Vet Certificate var ama Freight Booking'in hiç UI'ı yok. Bu üçlü, Faz 1'in en kritik teslimat riski.
5. **Container-seviyesi maliyet/70% depozito UI'ı**: MSAERP'te hiç yoktu (sadece model+arka plan); Stabler'da da henüz SPA'da yok ama veri modeli (Container Cost Line, DRAFT Payment Entry) MSAERP'e göre daha temiz — Faz 2'de LandedCostReview/ContainerTracker ile ilk kez gerçek bir UI kazanacak.
