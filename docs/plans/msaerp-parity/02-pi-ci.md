# 02 — PI ve CI Paritesi: Proforma Invoice ↔ Purchase Order, Commercial Invoice

**Tarih:** 2026-07-10
**Kapsam:** MSAERP `ProformaInvoice` + `LineItem` + `PIGroup` + `AdvancePayment` + `AdvanceAllocation` ↔ Stabler native **Purchase Order** + WP1/WP2 custom field ve doctype'ları; MSAERP `CommercialInvoice` + `CILineItem` + `CIExpense` + `CILineItemAllocation` ↔ Stabler **Commercial Invoice** doctype'ı (WP1.1/WP2, working-tree'de committed+uncommitted karışık).
**Kaynaklar:** MSAERP — `proforma_app/models.py`, `forms.py`, `views.py`, `urls.py`, `signals.py`, `services/financial_ops.py`, `services/advance_allocation.py`, `services/customs_fee_service.py`, `erpnext_integration/purchase_orders.py`, `erpnext_integration/invoicing.py`, `templates/proforma/*`, `templates/commercial_invoice/*`. Stabler — `stabler/patches/v40-v43_*.py`, `stabler/stabler/doctype/commercial_invoice*`, `stabler/stabler/doctype/import_pi_group/`, `stabler/stabler/imports_module/*`, `stabler/api/purchasing.py`, `stabler/public/js/pages/purchasing/*`, `stabler/public/js/pages/imports/ImportsDashboard.vue`, `stabler/public/js/router.js`. Plan: `docs/plans/2026-07-09-msaerp-to-stabler-migration-plan.md` (K1-K4, §3 DocType eşleme, §9 fazlı yol haritası).
**Not:** Stabler tarafında incelenen kod tabanının önemli bir kısmı **git working tree'de committed değil** (bkz. §1.2 ve §2.2 dipnotları) — bu, "bugün var" ifadesinin "prod'da deploy edilmiş" anlamına gelmediği, "yerel repo'da yazılmış ve okunabilir" anlamına geldiği şeklinde okunmalı.

---

## 1. PI — Proforma Invoice (→ native Purchase Order)

### 1.1 MSAERP'de bugün

#### 1.1.1 PI Listesi
`templates/proforma/pi_list.html`, `ProformaInvoiceListView` (`views.py:240-340`), URL `/pi/`, `paginate_by=20`.

- **Kolonlar:** PI & İhracatçı (PI numarası linki, tedarikçi linki, opsiyonel PI Group rozeti) · Tarih (g/a/Y) · Ürünler (satır sayısı) · Fiziksel (boxes, kg, FCL) · Fiyatlandırma (Agreed $, Docs $, cash-difference rozeti) · Faturalanma % (CI listesine link, renkli rozet + progress bar) · Ödeme Durumu (FULLY PAID yeşil / PARTIAL mavi / NOT PAID turuncu, progress bar + %) · Statü (7 durumlu rozet) · Aksiyonlar.
- **Filtre/arama:** debounce'lu (500ms) serbest metin arama (PI no, tedarikçi ad/kod, grup kod/ad — `Q` OR); Tedarikçi seçici (`vendor__code` exact); Statü seçici (exact). Kullanıcı tarafından değiştirilebilir sıralama **yok** — sabit `-date, -pi_number`.
- **Satır aksiyonları:** Görüntüle (göz), Düzenle (kalem), Sil (çöp kutusu). Toplu aksiyon/checkbox yok.
- **Statü rozet renkleri:** DRAFT=gri, CONFIRMED=mavi, ADVANCE_PAID=mor, INVOICED=sarı, SHIPPING=indigo, COMPLETED=yeşil, CANCELLED=kırmızı.
- **Özet şeridi:** Agreed toplam $ / Docs toplam $ / Fark (amber, koşullu); fiziksel toplamlar (boxes/kg/FCL); fatura sayaçları (toplam/bekleyen/tamam) — hepsi filtrelenmiş queryset üzerinde `.aggregate()` ile (6 ayrı DB round-trip — verimsizlik notu).
- **Bilinen kusur:** tedarikçi dropdown'ı için context'te önce distinct-vendor-id listesi hesaplanıyor, sonra kullanılmadan tüm `vendor_type="SUPPLIER"` tedarikçilerle eziliyor (ölü kod, views.py:282-284 vs 338).

#### 1.1.2 PI Grubu (`PIGroup`)
- **Liste** (`pi_group_list.html`, `paginate_by=30`): # · Kod (sıralanabilir, link) · Ad (sıralanabilir + notlar) · Tedarikçi (sıralanabilir, "{atanan}/{tedarikçinin_toplam_PI} PI" sayacı) · Bağlı PI'lar (chip'ler) · Aksiyonlar. Sıralama beyaz listesi: `code/-code, name/-name, vendor/-vendor, pi_count/-pi_count, created_at/-created_at`. Statü alanı/rozeti **yok** (gruplar durum taşımaz).
- **Form** (`pi_group_form.html`): Kod* (zorunlu), Ad, Tedarikçi, Notlar — sadece Kod zorunlu.
- **Detay** (`pi_group_detail.html`): Kod, Tedarikçi Kısıtlaması, Oluşturulma, Son Güncelleme kartları; Notlar kartı (varsa); Bağlı PI'lar tablosu (PI No, Tarih, Tedarikçi, 7 durumlu statü rozeti, Agreed Total, Görüntüle). Butonlar: Geri, PI Ata, Düzenle, Sil.
- **PI Atama ekranı** (`pi_group_assign_pis.html`): **tek checkbox çoklu-seçim tablosu** (iki panelli değil). Aday kümesi = gruptaki mevcut PI'lar VEYA atanmamış PI'lar (`pi_group__isnull=True`), grubun tedarikçisi varsa ona kısıtlı. "Tümünü Seç"/"Tümünü Temizle" JS butonları. POST `transaction.atomic()` içinde: seçimden çıkarılanların bağını koparır, yeni seçilenleri bağlar (server-side yeniden doğrulama var).
- **Silme onayı:** bağlı PI sayısını gösterir, "Bu PI'lar silinmeyecek — sadece grup referansları temizlenecek" uyarısı. Engelleme mantığı yok — silme her zaman mümkün (`PI.pi_group` = `SET_NULL`).

#### 1.1.3 PI Formu (`pi_form.html`, `pi_create_view`/`pi_update_view`)

Gruplar halinde alanlar:
- **Temel Bilgiler:** PI Numarası* · PI Grubu (opsiyonel referans) · Tedarikçi* · Tarih* (GG/AA/YYYY) · Statü*.
- **Sevkiyat Detayları:** Para birimi, Incoterms (11 değerli dropdown: EXW/FCA/FAS/FOB/CFR/CIF/CPT/CIP/DAP/DPU/DDP), Adlandırılmış Yer, Yükleme Limanı (özel giriş destekli seçici), Boşaltma Limanı — hiçbiri zorunlu değil.
- **Ödeme Koşulları:** Prepayment Base seçeneği (radyo kartlar: "Docs only prepayment" / "Agreed Total Prepayment") · Avans Yüzdesi (preset pill'ler 20/80, 30/70, 50/50, 100/0 veya Custom 0-100 sayı alanı, hidden input ile sürülür) · canlı split çubuğu.
- **Satır Kalemleri (inline formset):** Kategori (tedarikçiye özel seçici) · Ürün (auto-fill açıklama) · FCL · Boxes · Box (kg) (datalist: 10/15/18/20/25/30/50) · Qty (kg) — **salt okunur, otomatik hesaplanır** (`boxes × box_weight_kg`, hem JS'te hem model `save()`'de duplike edilmiş) · Agreed Price · Docs Price · Sil. "Kategoriden Doldur" modalı (Kategori, Konteyner Sayısı 1-50, Box Ağırlığı kg varsayılan 20, Agreed/Docs Price $/kg — FCL'yi box sayısına göre orantılı böler) ve "Kalem Ekle" butonu.
- **Toplamlar şeridi (JS canlı):** Agreed Total, Documents Total, Cash Difference.
- **Doğrulama:** yalnız server-side (Django form/formset `clean()`); HTML5 `required` yok — zorunluluk görsel bir kırmızı yıldız kuralı. Formset en az bir satır (product_code + quantity_kg dolu) ister.
- **Kaydetme akışı:** `transaction.atomic()`; kayıttan sonra `invoice.recalculate_totals()` çağrılır, ardından (ERPNEXT_ENABLED ise) senkron olarak `sync_pi_to_purchase_order()` inline çağrılır — try/except sadece log'lar, **kullanıcıya senkron başarısız olsa da her zaman başarı mesajı gösterilir.**

#### 1.1.4 PI Detay Sayfası
Başlık: statü renkli sol kenarlık, PI-{numara}, statü rozeti, tedarikçi adı. Butonlar: Düzenle, Geri. **Bu sayfada sil/senkron/yazdır/PDF butonu yok** (silme sadece liste sayfasından).

Alan ızgarası: Tedarikçi, PI Grubu, Tarih, Şartlar (para birimi/incoterm/yer), Rota (yükleme→boşaltma limanı), Ödeme (avans/bakiye % + prepayment tipi).

Metrik şeridi: FCL, Boxes (+tahsis edilen/kalan), Ağırlık kg (+tahsis), CI Durumu (%tamamlanan/kısmi/bekleyen).

Satır Kalemleri tablosu: Ürün, Açıklama, FCL, Boxes, Box(kg), Qty(kg), Agreed Price, Agreed Total, Docs Price, Docs Total, Durum (satır bazlı faturalanma-% rozeti: complete ≥%99.9 yeşil / partial >%0 sarı / none kırmızı — **bu üç etiket `_()` ile sarılmamış, hardcode İngilizce**, views.py:552,556,560).

Toplamlar çubuğu: Agreed / Docs / Fark ($).

**Avans Ödemeleri bölümü:** özet Ödenen/Tahsis/Tahsis-edilmemiş $ + avans %. "Avans Kaydet" butonu. Tablo: Ödeme #, Tarih, Tutar, Bank, Cash, Statü, Payment Entry (senkron göstergesi — yeşil nokta "muhasebe sistemine senkronize" / amber "senkron bekliyor"), Aksiyonlar (Düzenle, İptal — CANCELLED olunca gizlenir).

#### 1.1.5 Avans Ödemeleri + Allocation

**AdvancePayment modeli:** `proforma_invoice` FK, `payment_date`, `bank_amount`, `cash_amount`, `remaining_to_allocate`, `created_by`, `erpnext_payment_bank`, `erpnext_payment_cash`, `status` (ACTIVE/CANCELLED), `cancelled_at`, `cancelled_by`. **`payment_method` alanı model'de yok** — form topluyor ama hiçbir yere yazılmıyor; edit-advance prefill "WIRE_TRANSFER" hardcode ediyor (workaround).

**"Avans Kaydet" ekranı** (`pi_record_advance.html`): PI özet kartı, mevcut avanslar tablosu, form alanları: Ödeme Tarihi* (flatpickr), Para Birimi, Ödeme Yöntemi, Bank Amount (USD)* + Cash Amount (USD) canlı toplamla, Bank/Cash Hesabı seçicileri (canlı bakiye kontrolü + "Yetersiz bakiye" JS guard'ı), Referans No, Açıklama.

**"Eşit bölüşüm" kuralı YOKTUR** — "önerilen split" sadece bir UI-prefill'dir: `bank = docs_total × (advance_pct/100)`, `cash = cash_difference × (advance_pct/100)` (AGREED_TOTAL için; DOCS_ONLY'de cash her zaman 0), server-side hiçbir yerde zorlanmaz.

**AdvanceAllocation modeli:** `advance_payment` FK, `commercial_invoice` FK, `allocated_bank`, `allocated_cash`, `allocated_at`, `created_by`; `unique_together=(advance_payment, commercial_invoice)`. Otomatik pro-rata allocation `advance_allocation.py`'de: `ci_fraction = ci.docs_total / pi.agreed_total` (kodun kendi yorumuna göre bu, DOCS_ONLY PI'lar için muhtemel bir hata — `prepayment_base` yerine tam `agreed_total`'a göre boyutlandırılmış). Her ACTIVE avans için `share = min(remaining_to_allocate, total_amount × ci_fraction)`, avansın kendi bank/cash oranını koruyarak bölünür. Aşırı-tahsis koruması `select_for_update()` ile.

Hem `pi_record_advance_view` hem `pi_edit_advance_view` başarı sonrası, `pi.commercial_invoices.all()` üzerinde döngüye girip her bağlı CI için `allocate_advance_to_ci()`'yi yeniden çalıştırır (CI başına hatalar sadece log'lanır, kullanıcıya gösterilmez).

#### 1.1.6 Otomasyonlar/Sinyaller

**Bulgular: PI alanında (ProformaInvoice, LineItem, AdvancePayment, AdvanceAllocation, PIGroup) SIFIR sinyal handler'ı vardır** — `signals.py` (1184 satır) bu sınıf adları için grep'lendi, sıfır eşleşme. Her yan etki (totals recalc, ERPNext PO senkronu) view fonksiyonları içinde açık çağrılarla bağlanmış, `post_save`/`pre_save` değil. Bu, sistemin diğer neredeyse tüm alanlarıyla (`CommercialInvoice`, `Container`, `Truck`, master data) tam tersi — onlar sinyal güdümlü + async task deferral kullanıyor.

#### 1.1.7 ERPNext Senkron (PI → Purchase Order)

Modül: `erpnext_integration/purchase_orders.py`, `sync_pi_to_purchase_order()`. Oluşturulan doctype: ERPNext **Purchase Order**. Senkron durumu yalnız `ProformaInvoice.erpnext_purchase_order` (unique CharField) ile takip ediliyor — boolean flag/timestamp yok.

**Tetikleme noktaları (hepsi senkron, sinyal değil):** PI oluşturma, PI güncelleme (inline, try/except log-only), toplu geri-dolgu (`_sync_migrate_pis`), CLI komutu (`migrate_pis_to_purchase_orders`).

**Alan eşlemesi (özet):** `LineItem.agreed_price → items[].rate` (ERPNext'in gerçek yükümlülük olarak kaydettiği alan), `docs_price → items[].custom_docs_rate`, `docs_line_total → custom_docs_amount`, `boxes/box_weight_kg → custom_boxes/custom_box_weight_kg`; `Vendor.erpnext_name → supplier` (zorunlu, boşsa abort); `date + 30 gün → schedule_date` (hardcode); `pi_number → custom_pi_number`; `docs_total/cash_difference/advance_percentage → custom_docs_total/custom_cash_difference/custom_advance_percentage`.

**Statü → docstatus:** DRAFT→taslak; CONFIRMED/ADVANCE_PAID/INVOICED/SHIPPING/COMPLETED→submitted; CANCELLED→iptal/silme. **Submit edilmiş PO'larda sonraki PI düzenlemeleri sadece 3 custom alanı günceller — satır fiyat düzeltmeleri ERPNext'e yayılmaz.**

**Hata yönetimi:** sadece `ERPNextAPIError` yakalanıyor; kullanıcı her zaman başarı mesajı görüyor senkron başarısız olsa bile; **PI→PO senkronu için hiçbir `SyncLog` satırı yazılmıyor** (framework mevcut ve başka yerlerde kullanılıyor olmasına rağmen) — başarısız senkronlar izleme panelinde görünmez, sadece uygulama loglarında.

#### 1.1.8 Raporlar
- **AdvancePaymentSummaryView** (`/reports/advance-summary/`) — tüm ACTIVE avanslar, "Fully/Partially/Unallocated" (hardcode İngilizce) rozetleri, banka/nakit toplamları.
- **PIProgressReportView** (`/reports/pi-progress/`) — filtrelenebilir yaşam döngüsü raporu; kompozit `overall_pct = advance_pct×0.4 + allocation_pct×0.3 + min(pct_70,100)×0.3`.
- **PIGroupContainerStatusReportView** + CSV export (`/reports/pi-group-container-status/`) — PI'ları gruplara göre kümeleyip konteynerleri 4 lifecycle bucket'ına (ORIGIN/TRANSIT/DESTINATION/DELIVERED) ayırır; CRO takibi stub (hardcode 0).

PI/PI Grubu için PDF/print export **yok**.

---

### 1.2 Stabler'da bugün

> **Not:** Aşağıdaki maddelerin büyük kısmı `git status` incelendiğinde **commit edilmemiş working-tree değişiklikleri**. HEAD `a75a62e` (WP1: imports pipeline — CI logistics statüleri + PO/PO Item costing alanları), altında `9e7be69` (WP1 imports modül iskeleti). Uncommitted: `stabler/hooks.py`, `patches.txt`, `v42_po_imports_costing_fields.py`, CI doctype dosyaları, ve tamamen yeni `imports_module/` paketi + testler. v43 patch dosyası da uncommitted/untracked.

**Sahip kararı (plan §K1/§3.1):** ProformaInvoice için **ayrı doctype yok** — native **Purchase Order** kullanılıyor, PI'nin iş yaşam döngüsü türetilir (saklanmaz).

**Native PO alanları (zaten var, `api/purchasing.py`'de kullanılıyor):** `supplier`, `supplier_name`, `company`, `set_warehouse`, `currency`, `conversion_rate`, `transaction_date`, `schedule_date`, `net_total`, `grand_total`, `per_received`, `per_billed`, `status`, `docstatus`, `amended_from`, `terms`; satır: `item_code`, `item_name`, `warehouse`, `qty`, `received_qty`, `billed_amt`, `uom`, `rate`, `price_list_rate`, `discount_percentage/amount`, `amount`. **`advance_paid` native alanı hiçbir yerde referans edilmiyor** — Stabler'ın yeni `custom_advance_percentage`/`custom_prepayment_type` mekanizması ERPNext'in kendi PO-avans akışından bağımsız, paralel bir mekanizma.

**Patch v40 (`v40_imports_roles.py`):** `Imports User`, `Imports Manager` rollerini oluşturur (`desk_access=0`).

**Patch v41 (`v41_po_imports_fields.py`):** `custom_import_pi_group` (Link→Import PI Group) hem Purchase Order hem Purchase Order Item'a ekler, permlevel 0.

**Patch v42 (`v42_po_imports_costing_fields.py`) — permlevel 1 (K3 maskeleme kararına uygun):**
- PO: `custom_advance_percentage` (Percent), `custom_prepayment_type` (Select: boş/"Docs Total"/"Agreed Total" — Django'nun `prepayment_base`'ini yansıtır), `custom_docs_total` (Currency), `custom_cash_difference` (Currency), `custom_stage` (Data — türetilemeyen aşama için tek Select/serbest alan).
- PO Item: `custom_docs_rate`, `custom_docs_amount` (Currency), `custom_boxes` (Int), `custom_box_weight_kg` (Float).

**Patch v43 (`v43_cross_border_transport_item.py`):** "Cross-Border Transport" adında stoksuz, sadece-satın-alma hizmet Item'ı oluşturur (tır sınır-geçiş PI'sinin tek satırı için).

Hepsi `patches.txt`'de `[post_model_sync]` altında — CLAUDE.md kuralına (yeni kolon okuyan/yazan patch'ler `has_column` guard'lı olmalı veya post_model_sync'te olmalı) uygun.

**Import PI Group doctype'ı:** `title`, `company`, `status` (Open/Closed), `remarks`. Controller **boş `pass`** — hiçbir iş mantığı yok, "gruptaki PO'lar" rollup/raporu yok.

**imports_module/payment_math.py:** `ADVANCE_PCT = 0.70` sabiti, açık yorumla: *"Iran-arrival advance is 70% of the container's goods value (the 30% deposit was paid up front at PO stage). See Django signals.py:581."* — Stabler tasarımının MSAERP'in 30%-PO-avansı / 70%-Iran-varışı-avansı modelini bilinçli olarak izlediğinin kanıtı. `build_advance_pe_payload()` DRAFT (asla otomatik submit edilmeyen) bir Payment Entry inşa eder, referanslar PO'lara `grand_total`'a göre orantılı dağıtılır.

**SPA/API durumu — kritik boşluk:**
- `PurchaseOrderForm.vue` mevcut, ama v41/v42'nin 10 yeni custom alanından (**hiçbiri**: `custom_import_pi_group`, `custom_advance_percentage`, `custom_prepayment_type`, `custom_docs_total`, `custom_cash_difference`, `custom_stage`, `custom_docs_rate`, `custom_docs_amount`, `custom_boxes`, `custom_box_weight_kg`) `blankLine()`/`blankForm()`/`fromDetail()`/`toPayload()` içinde görünmüyor.
- `api/purchasing.py`'deki `purchase_order_detail()` bu alanların **hiçbirini** dönmüyor (repo çapında grep doğrulandı — sadece patch dosyaları ve dokümanlarda geçiyor).
- `stabler/api/imports.py` **yok**. Import PI Group / Import Container / Import Truck / GRN Checklist / Truck Receipt / Commercial Invoice için **hiçbir whitelisted RPC endpoint'i yok**.
- `public/js/pages/imports/ImportsDashboard.vue` — tek dosya, placeholder boş-durum ekranı ("Imports workspace will be built out in the next work package"). Router'da tek `/imports` route'u, alt route yok.
- `PurchasingHome.vue`'da "Commercial Invoice" veya "Imports" sekmesi yok.

**Özet:** PI'nin Stabler karşılığı olan şema (custom field'lar) ve arka plan otomasyonu (70% avans PE üretimi) **var**, ama bunu görebilecek/düzenleyebilecek hiçbir kullanıcı arayüzü veya API katmanı yok — sadece Desk üzerinden erişilebilir, ki Stabler'ın "Desk fallback yok" kuralı bunu SPA kullanıcıları için kapatıyor.

---

### 1.3 Boşluk tablosu

| Özellik | MSAERP | Stabler | Durum | Plan (WP/Faz) | Tahmini zaman |
|---|---|---|---|---|---|
| PI temel kayıt (numara, tedarikçi, tarih, incoterm) | ProformaInvoice modeli, tam form | Native PO alanları zaten var | ✅ | — | — |
| PI Grubu (PIGroup) — kod/ad/tedarikçi/not | Tam CRUD + assign-PIs ekranı | Import PI Group doctype var (alan seti eş), ama controller boş, rollup/rapor yok, SPA yok | 🔜 | WP2 (SPA+API) | Faz 2, ~Ağustos 2026 |
| Avans %, prepayment base (Docs/Agreed) | `advance_percentage`, `prepayment_type` alanları + form UI | `custom_advance_percentage`, `custom_prepayment_type` (permlevel 1) — şema hazır, SPA'da yok | 🔜 | WP2 (SPA alan bağlama) | Faz 2, ~Ağustos 2026 |
| Dual pricing (agreed vs docs fiyat/tutar) satır bazında | `LineItem.agreed_price/docs_price` | `custom_docs_rate/custom_docs_amount` (PO Item, permlevel 1); native `rate`=agreed (K3 kararı) | 🔜 | WP2 (SPA maskeleme + görünürlük) | Faz 2, ~Ağustos 2026 |
| Boxes × Box Weight → Qty otomatiği | `LineItem.save()` override + form JS | `custom_boxes`, `custom_box_weight_kg` alanları var; otomatik hesap SPA/`validate` hook'ta yok | 🔜 | WP2 | Faz 2, ~Ağustos 2026 |
| PI listesi (kolonlar, filtre, özet şerit, rozetler) | Tam (§1.1.1) | Yok — PurchasingHome'da CI/Imports sekmesi yok | ❌ | WP2 SPA | Faz 2, ~Ağustos 2026 |
| PI türetilmiş yaşam döngüsü rozetleri (ADVANCE_PAID/SHIPPING/COMPLETED) | Gerçek `status` alanı (7 durum) | Plan kararı: **saklanmaz, türetilir** (`advance_paid>0`, CI statülerinden, `per_received=100`) — henüz SPA'da hesaplanmıyor | ❌ | WP2 SPA rozet mantığı | Faz 2, ~Ağustos 2026 |
| Avans ödeme kaydı (Bank+Cash iki akış) | AdvancePayment modeli + record-advance ekranı | Native PO + 2× Payment Entry planı (§3.1); hazır script yok, "Avans Öde" aksiyonu api/imports.py'de tanımlı değil | ❌ | WP2 | Faz 2, ~Ağustos 2026 |
| Avans → CI/PI Invoice allocation | AdvanceAllocation modeli + pro-rata + manuel override ekranı | Plan: native advances + `Import Advance Allocation` standalone log doctype'ı — henüz oluşturulmamış | ❌ | WP2/WP3 | Faz 2-3 |
| 70% Iran-varış avansı otomasyonu | `Container` pre_save sinyali, gate_in_date+7g VendorBill/ERPNext PI | `imports_module/hooks.py::on_container_update` → `create_advance_pe` (DRAFT PE, ARRIVED_AT_IRAN tetikli) — **arka planda hazır, MSAERP'in 30/70 mantığına bilinçli paralel** | ✅ (backend) / ❌ (UI) | WP2 SPA + doğrulama | Faz 2, ~Ağustos 2026 |
| PI→ERPNext PO senkronu | `sync_pi_to_purchase_order`, senkron inline, SyncLog yok, sessiz hata yutma | N/A — Stabler'da zaten native PO, ayrı senkron katmanı **komple ölüyor** (plan §0 "en büyük mimari kazanç") | ✅ (mimari olarak gereksizleşti) | — | — |
| ERPNext PO senkron hata izlenebilirliği | Yok (flag yok, SyncLog yazılmıyor) | N/A (senkron katmanı yok) | ✅ | — | — |
| Avans "eşit bölüşüm" kuralı | Yok — sadece orantılı UI-prefill, server-side zorlanmıyor | Henüz tasarlanmadı | 🔜 | WP2 tasarım kararı | Faz 2 |
| PI raporları (Advance Summary, Progress, Group-Container-Status) | 3 rapor + 1 CSV export | Yok | ❌ | Faz 2/4 (kapsam netleştirilmeli) | Faz 2-4 |
| PI silme koruması (bağlı CI/VendorTransaction kontrolü) | Var, ama AdvancePayment kontrolü **eksik** (MSAERP bug) | N/A (native PO silme kuralları farklı) | ⚠️ | Faz 4 senaryo testinde doğrulanmalı | Faz 4 |

---

### 1.4 Notlar/kararlar

1. **PI domaininde sinyal otomasyonu yok** (MSAERP tarafı) — bu aslında Stabler'a taşımayı kolaylaştırıyor: port edilecek "sinyal davranışı" yok, sadece view-seviyesi iş kuralları (totals recalc, senkron tetikleme) var ve bunlar zaten SPA/API katmanında yeniden yazılacak.
2. **K3 kararı** (native `rate`=agreed, `custom_docs_*`=docs, permlevel 1 maskeleme) MSAERP'in `agreed_price`/`docs_price` ikili modelini birebir karşılıyor; Stabler şeması bunu doğru yansıtıyor (v42 patch).
3. **MSAERP'in "avans_paid_percentage" (prepayment_base bazlı) ile "payment_percentage" (her zaman agreed_total bazlı) arasındaki tutarsızlık** Stabler tasarımına taşınmamalı — SPA'da tek, net tanımlı bir "avans ilerleme %" metriği kullanılmalı (WP2 tasarım notu).
4. **Advance-allocation pro-rata formülünün `agreed_total` yerine `prepayment_base` kullanması gerektiği** (MSAERP'in kendi kod yorumunda flag'lenmiş bir olası hata) — Stabler'ın `Import Advance Allocation` mantığı tasarlanırken bu hata tekrarlanmamalı.
5. **`AdvancePayment.payment_method` alanının MSAERP model'inde eksik olması** (form topluyor, model saklamıyor) — Stabler'ın Payment Entry tabanlı modeli zaten native `mode_of_payment` alanına sahip, bu sorun kendiliğinden çözülüyor.
6. **PI silme guard'ının avans ödemelerini kontrol etmemesi** MSAERP'te bir veri bütünlüğü riski; Stabler'da native PO silme/iptal kuralları zaten daha sıkı (submitted doc'lar silinemez) — ama ETL/parite testinde bu senaryo (avansı olan PI'nin durumu) özellikle test edilmeli (Faz 4).
7. **Stabler'ın `custom_advance_percentage`/`custom_prepayment_type` mekanizması ERPNext'in native `advance_paid`/PO-avans akışından bağımsız** — bu, MSAERP'in kendi paralel avans modelini birebir kopyalıyor (iyi bir parite kararı), ama native ERPNext avans raporlarıyla çakışma riski taşıyor; Faz 4 senaryo testlerinde native vs custom avans görünümü karşılaştırılmalı.
8. Import PI Group'un Stabler'daki controller'ı şu an tamamen boş (`pass`) — MSAERP'in "assign PIs" tek-checkbox-tablo UX'i ve "gruptaki PI sayacı" bilgisi WP2 SPA tasarımında yeniden üretilmeli.

---

## 2. CI — Commercial Invoice

### 2.1 MSAERP'de bugün

#### 2.1.1 CI Listesi
`templates/commercial_invoice/ci_list.html`, `CommercialInvoiceListView` (`views.py:1858-2000`), `paginate_by=20`.

- **Kolonlar:** CI Numarası · PI Referansı (link + tedarikçi kod/ad) · Tarih/Kalemler · Ağırlık (+ konteynerlere paketlenme % progress bar) · Finans (Docs, Agreed, Trans(port), Add(itional)) · Sevkiyatlar (konteyner/tır rozet+sayı, ilk 2 konteyner no/gemi) · Ödeme (FULLY_PAID/PARTIALLY_PAID/PENDING rozeti + coverage %) · Statü (renkli pill) · Aksiyonlar (Görüntüle/Düzenle/Sil).
- **Filtre/arama:** serbest metin (CI no/PI/tedarikçi), Tedarikçi dropdown, Statü dropdown.
- **Bilinen kusurlar (önemli — parite tasarımında tekrarlanmamalı):**
  - Özet şeridindeki `draft_cis`/`pending_cis`/`completed_cis` sayaçları model'in gerçek `STATUS_CHOICES`'ında olmayan değerlerle (`"DRAFT"`, `"PENDING"`, `"COMPLETED"`) filtreleniyor — **her zaman 0 gösteriyor.**
  - Liste ve detay sayfalarındaki statü rozeti CSS'i (DRAFT/CONFIRMED/ADVANCE_PAID/INVOICED/SHIPPING/COMPLETED/CANCELLED) gerçek model statüleriyle (BOOKED/STUFFED/GATE_IN/ON_BOARD/IN_TRANSIT/DISCHARGED/AVAILABLE/ARRIVED_AT_IRAN/DELIVERED_TO_UZBEKISTAN) **eşleşmiyor** — tüm satırlar varsayılan (boş) stile düşüyor.
  - Sayfalama sadece `status` query param'ını koruyor, `search`/`vendor` filtrelerini kaybediyor.

#### 2.1.2 CI Formu
`CommercialInvoiceForm` (`forms.py:358-421`), model `CommercialInvoice` (`models.py:1523-2149`).

- **Kimlik/tedarikçi:** `ci_number` (otomatik `PRO/ALS/NNNN/FY-FY` formatı, Nisan-Mart mali yıl), `pi_reference` (otomatik virgüllü liste, salt okunur), `proforma_invoices` M2M, `vendor`, `date`.
- **Statü — ÖNEMLİ BUG:** model'in 9 gerçek değeri var (BOOKED…DELIVERED_TO_UZBEKISTAN), ama form widget'ı **hardcode yanlış bir liste** gösteriyor: DRAFT/CONFIRMED/SHIPPED/DELIVERED — model'de bunların hiçbiri yok. Yeni CI'larda form `initial["status"]="CONFIRMED"` set ediyor — geçersiz bir değer önceden seçili geliyor.
- **Incoterms:** 11 ICC 2020 terimi, varsayılan CIF; bağlı PI'lardan otomatik doldurma (hepsi aynı incoterm'e sahipse).
- **Sevkiyat lojistiği:** vessel, voyage, port_of_loading, port_of_discharge, transshipment_port, shipping_type (DIRECT/TRANSSHIPMENT), shipping_company, bl_number.
- **Sevkiyat tarihleri:** etd, eta, atd, ata — hepsi formda var. **`eta_transit_port` ("İran ETA — Bandar Abbas", 7-günlük ödeme kuralı için kritik) formda ve `ci_form.html`'de HİÇ YOK** — bu alanı CI oluşturma/düzenleme UI'ından set etmenin **hiçbir yolu bulunamadı** (Django admin veya doğrudan DB/API dışında).
- **Otomatik hesaplanan/salt okunur toplamlar:** `total_boxes`, `total_kg`, `agreed_total`, `docs_total`, `cash_difference` — satır kalemlerinden `calculate_totals()` ile her kayıtta yeniden hesaplanır.
- **VAT:** `uzb_vat_usd` ("Özbekistan KDV %12, USD") — sadece alan boşsa otomatik doldurulur (`calculate_vat()`); bir kez değer girildikten sonra bir daha otomatik yeniden hesaplanmaz; formda "Otomatik Hesapla" butonu var. Formül: `(docs_total + toplam_konteyner_transport_usd) × 0.12`.
- **Gümrük:** `off_hours_clearance` (checkbox, "+%25 БРВ" ek ücreti), `customs_fee_override` (manuel UZS override) formda var; `customs_clearance_fee_uzs`, `customs_fee_brv_used`, `customs_fee_multiplier` formda YOK — sadece detay sayfasındaki ayrı "Hesapla" aksiyonuyla hesaplanıyor.
- **Deprecated alanlar** (`transport_vendor`, `transport_total`, `additional_costs_*`) hâlâ formda, model'de açıkça "DEPRECATED: Use CIExpense model" yorumuyla işaretli.
- **Satır kalemleri inline formset:** Kategori (6 hardcode seçenek), Ürün, PI # (salt okunur), Box Qty, Box Weight, Total Kg (JS hesaplı), Agreed/Docs fiyat+tutar (JS hesaplı). "PI'lardan Akıllı Doldur" 2 adımlı sihirbaz modalı.
- **Konteyner inline formset:** kaydedilmiş konteynerler için başlık + paketleme listesi tablosu; birçok alan (ağırlık, tarihler, %70 ödeme, navlun, İran/Özbekistan maliyet alanları, belgeler) yalnızca gizli input olarak POST-koruması için var, bu formdan düzenlenmiyor. "Konteyner Üret" sihirbazı (satır satır yapıştırma).
- **Tır inline formset:** Tır No, Nakliye Şirketi, Şoför Ad/Tel, Toplam Boxes/KG, Nakliye Maliyeti, Sil.
- **CI Giderleri inline formset:** sadece **Güncelleme'de var, Oluşturma'da yok** (Create view context'i `expense_formset` hiç kurmuyor).
- **Doğrulama:** transport bank+cash = transport_total (1 cent tolerans, sadece transport_total doluysa); ETD ≤ ETA; ATD ≤ ATA; TRANSSHIPMENT ise transshipment_port zorunlu.

#### 2.1.3 CI Detay Sayfası
Tek uzun sayfa (tab yok):
1. Başlık: CI no, statü rozeti (ölü CSS dalları), tedarikçi, özet şerit. Butonlar: **Landed Costs**, **GTD Oluştur** (gümrük beyannamesi), **CI Düzenle**.
2. Satır Kalemleri tablosu + **Paketlenme %** (satır bazlı, konteyner satırlarıyla kod+kategori eşleşmesiyle hesaplanıyor).
3. Sevkiyat & Lojistik kartı (vessel/voyage/liman/ETD-ETA, ATD/ATA varsa yeşille override, BL no, **İran ETA pill'i — sadece `eta_transit_port` set edilmişse görünür**, ama UI'dan set edilemez).
4. "Konteyner Üret" sihirbazı.
5. Konteyner kartları (her biri: başlık, paketleme tablosu, Zaman Çizelgesi & Tarihler, Belgeler, GRN özeti).
6. **CI Giderleri tablosu** (§2.1.5) + kategori özet şeridi.
7. Tırlar tablosu + "Tır Üret" satır formu.
8. **Gümrük Temizleme Ücreti kartı:** CI Değeri, Tier (×БРВ çarpanı), Kullanılan БРВ, Ücret (manuel override notu), off-hours ek ücret notu, son hesaplanma zamanı. "Hesapla/Yeniden Hesapla" butonu (GET, onay istemeden anında hesaplar).
9. **Finansal Özet şeridi:** Agreed, Docs, Cash Difference, VAT %12.
10. **"UZS'de Fiili Ödemeler" tablosu** — sadece dolu ise gösterilir. `AdvanceAllocation` + konteyner navlun + `CIExpense` ödemeleri + `FreightBooking` ödemelerini, ödeme tarihindeki kur ile UZS'ye çevirerek birleştirir.
11. **Avans Tahsis bölümü** (§2.1.4).
12. **Ödeme Özeti:** Agreed Total / Tahsis Edilen Avans / Kalan Bakiye kartları, Bank(docs)/Cash(diff) akış kırılımı, konteyner bazlı %70-ödeme statü pill'leri. "Nihai Ödeme Kaydet" butonu (sadece `payment_70_status=='PENDING'` iken).
13. **Purchase Invoice bölümü** (ERPNext_ENABLED ise) — ERPNext PI rozeti veya "konteyner İran limanına varınca oluşturulacak" notu.

CI seviyesinde print/export/PDF butonu **yok**.

#### 2.1.4 PI Allocation (Avans Tahsisi)
`ci_allocate_advances.html`, `ci_allocate_advances_view`.

- Arka planda `AdvancePayment` + `AdvanceAllocation` (junction, `unique_together`); `CILineItemAllocation` (satır seviyesi 30/70 deposit/balance split, `DepositAllocationService` tarafından ayrıca yönetilir) — **iki farklı allocation mekanizması aynı domainde var, karıştırılmamalı.**
- **Otomatik Tahsis (pro-rata) butonu:** `ci_fraction = ci.docs_total / pi.agreed_total`; her ACTIVE avans için `share = min(remaining_to_allocate, total_amount × ci_fraction)`.
- **Manuel mod:** her avans için bank/cash input, Alpine.js canlı toplam; server-side aşırı-tahsis guard'ı (`remaining_to_allocate + zaten_tahsis_edilmiş + 1 cent` toleransı).
- Tahsis sonrası CI'nin `allocated_advance_bank`/`allocated_advance_cash` denormalize alanları yeniden hesaplanıp kaydedilir.

#### 2.1.5 CI Giderleri (`CIExpense`)
- **Alanlar:** `commercial_invoice`, `vendor` (opsiyonel), `truck` (opsiyonel), `expense_date`, `category`, `description`, `invoice_reference`, `amount`, `currency` (USD/EUR/UZS), `bank_payment`, `cash_payment`, `status`, `erpnext_name`.
- **Kategori seçenekleri:** BORDER_CROSSING, TRANSPORT, HANDLING, STORAGE, INSURANCE, DOCUMENTATION, CUSTOMS, OTHER.
- **Statü:** PENDING/PAID/CANCELLED — ama `clean()` kullanıcının seçtiği statüyü **her zaman ezip** ödeme tutarına göre yeniden hesaplıyor: `bank+cash>=amount`→PAID, `>0`→"PARTIAL" (**bu değer choices listesinde yok — geçersiz enum DB'ye yazılabiliyor**, veri bütünlüğü hatası), yoksa PENDING.
- **Onay iş akışı yok** — doğrudan tutar bazlı statü geçişi, rol gate'i yok.
- **Standalone form/URL yok** — sadece `ci_form.html` içine gömülü inline formset (yalnız Update'te), **belirtilen `expense_form.html` yolu repo'da mevcut değil.**
- **Landed cost'a besleme:** `CommercialInvoice` üzerinde kategori bazlı toplama property'leri (`transport_expenses_total`, `border_expenses_total`, `handling_expenses_total`, vb.).
- **Sinyaller:** `CIExpense` post_save/post_delete → yerel `VendorBill` oluşturur/günceller/siler (due_date = expense_date+15 gün); tır bağlı TRANSPORT giderleri atlanır (tır sınır-geçiş sinyaliyle işlenir). **Not:** dedike `erpnext_integration/expense_sync.py::sync_expense_to_erpnext()` fonksiyonu tanımlı ama **kod tabanında hiç çağrılmıyor** — ölü kod; gerçek yol yerel `VendorBill`, ki bu CLAUDE.md Kural #2'yle ("ERPNEXT_ENABLED=True iken yerel GL kaydı oluşturulmaz") çelişiyor gibi görünüyor.

#### 2.1.6 Gümrük Ücreti / БРВ / VAT
`services/customs_fee_service.py`:
```python
base_fee = tier.multiplier * brv.value_uzs
surcharge = (Decimal("0.25") * brv.value_uzs) if off_hours else Decimal("0")
fee_uzs = base_fee + surcharge
```
- `BRVSetting` (`core/models.py:354-391`): devlet belirli БРВ taban değeri (UZS), `effective_date` ile versiyonlanır.
- `CustomsFeeTier` (`core/models.py:394-433`): `min/max_value_usd` + `multiplier` — **migration planındaki `CustomsFeeTier` referansı gerçek, kullanımda bir model** (vestigial değil).
- Hesaplama `ci.docs_total` ve `ci.off_hours_clearance` üzerinden; **otomatik değil**, sadece kullanıcı aksiyonuyla (`ci_calculate_customs_fee`, GET, onaysız).
- `effective_customs_fee_uzs` = `customs_fee_override or customs_clearance_fee_uzs` (manuel override her zaman kazanır).

**VAT:** `calculate_vat()` = `(docs_total + Σ konteyner cross_border_transport_usd) × 0.12`, sabit %12, geri alınamaz, "landed cost'a eklenir".

#### 2.1.7 Sevkiyat/Tarihler & 7-Gün Ödeme Kuralı

**Kanonik iş kuralı** — `CommercialInvoice.payment_due_date` property'si:
```python
if self.eta_transit_port:
    return self.eta_transit_port - timedelta(days=7)
elif self.eta:
    return self.eta - timedelta(days=7)
return None
```
Docstring: *"%70 ödeme, İran'a (Bandar Abbas) varıştan 7 gün önce yapılmalı."*

**Üç ayrı, birbirinden bağımsız "7 gün" implementasyonu var — parite tasarımında birleştirilmeli:**
1. Model property'si (yukarıda) — `eta_transit_port` yoksa `eta`'ya düşer.
2. **Payment Preparation Report kendi mantığını duplike ediyor** — model property'sini çağırmıyor, bağımsız olarak `eta_transit_port - 7 gün` hesaplıyor ve `eta_transit_port__range` filtresi kullanıyor — **`eta_transit_port` boş, `eta` dolu CI'lar bu rapordan sessizce dışlanıyor**, oysa model property hâlâ bir tarih dönerdi. Gerçek fonksiyonel sapma.
3. **İlgisiz "7 gün" örüntüleri** — ERPNext Purchase Invoice `due_date = ci_date + 7 gün` (genel net-7 vade, İran-ETA kuralıyla karıştırılmamalı) ve `VendorBill.due_date = bill_date + 7 gün` (konteyner ARRIVED_AT_IRAN fallback yolu).

**En kritik bulgu: `eta_transit_port` alanı UI'dan tamamen erişilemez** — 7-gün kuralının ve Payment Preparation Report'un dayandığı tek alan, CI oluşturma/düzenleme formunda yok.

#### 2.1.8 Landed Cost
- **Dashboard:** toplam CI, toplam landed cost, ort. maliyet/kg, senkron oranı; `total_landed_cost = docs_total + Σexpenses + uzb_vat_usd` (**gümrük ücreti dashboard toplamına dahil değil** — detay sayfasıyla tutarsız).
- **Detay:** Senkron Durumu (GRN, Purchase Receipt, Landed Cost Voucher, Döviz Kuru); Maliyet Kırılımı (Ürün Maliyeti → 8 gider kategorisi → VAT → Gümrük Ücreti → Genel Toplam); tahsis yöntemi: **düz CI-seviyesi maliyet/kg** (`grand_total_usd / grand_total_weight`) — konteyner/ürün bazlı orantılı dağıtım yok; ayrı "Ürün Bazlı Maliyet/kg Analizi" tablosu tek tip bir markup oranı uyguluyor.

#### 2.1.9 Otomasyonlar/Sinyaller
- `create_grn_for_ci` (post_save) — CI statüsü belirli değerlere girince (ama bunların bir kısmı **geçersiz/ölü statü dalları**: SAILED/AT_PORT/CUSTOMS_CLEARANCE/CUSTOMS_CLEARED — sadece STUFFED/GATE_IN/DELIVERED_TO_UZBEKISTAN fiilen tetikleyebiliyor) GRN + GRNLineItem'lar oluşturur.
- `sync_shipping_company_to_containers` (post_save, update'te) — CI'nin shipping_company'sini bağlı konteynerlere yayar.
- `auto_generate_vendor_bill_on_expense_save`/`_freight_booking_save` (§2.1.5) — yerel VendorBill.
- `trigger_70_percent_bill_on_iran_arrival` (Container pre_save, ARRIVED_AT_IRAN'a geçişte) — `CILineItemAllocation` oluşturur, deposit/balance hesaplar, ERPNEXT_ENABLED ise ERPNext Purchase Invoice için flag koyar (post_save'de async `django_q` task ile submit), değilse yerel VendorBill (`due_date = gate_in_date+7 gün`).

#### 2.1.10 ERPNext Senkron
- `create_purchase_invoice_from_ci` — idempotent, `balance_due = agreed_total − Σkonteyner.allocated_deposit − Σ(AdvanceAllocation)`; `balance_due<=0` ise atlanır. Satır bazında dual-pricing custom alanları (`custom_docs_rate/amount/boxes/box_weight_kg`). Draft olarak oluşturulur.
- `sync_ci_to_purchase_invoice` — her CI kaydında (Create+Update, ERPNEXT_ENABLED ise) otomatik çağrılır; submit edilmiş ERPNext PI'lara dokunmuyor (no-op+warning).
- Nihai ödeme: `record_ci_final_payment` — bank/cash akış başına 1'er ERPNext Payment Entry, bakiye guard'ı transaction içinde, **hiçbir yerel GL kaydı oluşturmuyor** (CLAUDE.md kuralına uygun — CIExpense yolunun aksine).
- `CIExpense` sync fonksiyonu (`expense_sync.py`) ölü kod (§2.1.5).

#### 2.1.11 Raporlar
- **Payment Preparation Report** — `eta_transit_port` penceresi içindeki bekleyen %70 bakiyeli CI'lar; Overdue/Urgent/Upcoming pill'leri, "Öde" aksiyonu.
- **Logistics Dashboard** — CI→Konteyner/Tır→GRN operasyonel genel bakış.

---

### 2.2 Stabler'da bugün

> **Not:** CI doctype'ının hem committed (HEAD `a75a62e`) hem uncommitted (working-tree'deki `commercial_invoice.json`/`.py` değişiklikleri) katmanları var; aşağıdaki alan listesi güncel working-tree durumunu yansıtır.

**Commercial Invoice doctype** (`stabler/stabler/doctype/commercial_invoice/`): non-submittable, `autoname: CI-{YYYY}-{#####}`, `track_changes=1`.

`field_order`: `import_pi_group, company, supplier, ci_number, ci_date, currency, status, status_correction_reason, [section] incoterm, incoterm_location, vessel, voyage, bl_number, port_of_loading, port_of_discharge, eta_transit_port, etd, eta, atd, ata, [section] total_boxes, total_kg, agreed_total, docs_total, cash_difference, customs_fee, [section] items`.

Önemli gözlemler:
- **`eta_transit_port` doctype'ta ZATEN VAR** — MSAERP'in en büyük boşluğu (UI'dan erişilemez alan) burada şema seviyesinde çözülmüş durumda; kalan iş sadece SPA formuna bu alanı koymak.
- **`status`** — 9 gerçek lojistik durum + Cancelled: `BOOKED\nSTUFFED\nGATE_IN\nON_BOARD\nIN_TRANSIT\nDISCHARGED\nAVAILABLE\nARRIVED_AT_IRAN\nDELIVERED_TO_UZBEKISTAN\nCancelled` — **MSAERP'in model'indeki gerçek 9 değerle birebir eşleşiyor** ve MSAERP'in kendi UI'ındaki (form widget hardcode 4 değer, dead CSS dalları, dead sayaç filtreleri) tutarsızlıklarını miras almıyor. Bu, Stabler tarafının MSAERP'in bug'lı implementasyonunu değil, MSAERP'in *niyet edilen* modelini doğru kopyaladığının kanıtı.
- **`status_correction_reason`** — MSAERP'te karşılığı olmayan yeni bir özellik: rol kısıtlı (Imports Manager/System Manager), tek adımlık geri alma + zorunlu gerekçe metni.
- **`docs_total`, `cash_difference`** — permlevel 1 (K3 maskeleme).
- **`agreed_total`, `customs_fee`** — permlevel 0, henüz hesaplama mantığı yok.
- **Controller** (`commercial_invoice.py`): sadece statü-geçiş guard'ı (`_ALLOWED_TRANSITIONS`, `imports_module/status_pipeline.py::assert_transition()` üzerinden) — **VAT hesabı, gümrük ücreti hesabı, totals recalculation gibi hiçbir iş mantığı yok.** `on_submit`/`on_update` hook'u yok; yan etkiler Import Container/Truck/GRN Checklist/Truck Receipt doctype'larına bağlı, CI'nin kendisine değil.

**Commercial Invoice Item (child):** `item` (Link→Item, reqd), `description`, `hs_code` ("HS/IKPU Code"), `qty`, `uom`, `rate`, `amount` (read_only). MSAERP'in dual-pricing satır alanları (`docs_price`, `agreed_price` ayrımı) burada **yok** — tek `rate` alanı var, ayrı `custom_docs_rate` yok.

**Commercial Invoice PO Link:** standalone doctype, `commercial_invoice`, `company`, `purchase_order`, `purchase_order_item` (satır adı), `item`, `allocated_qty`, `allocated_amount` — MSAERP'in `pi_reference` string-eşleşmesi yerine **gerçek PO-satır referanslı, çok-PO'ya-bir-CI (M2M) tahsis tablosu.** Bu, plan §3.1'de belirtilen "critique M3: Link'ler child-row hedefleyemez" çözümü.

**İmports_module otomasyonu — CI'ye özel değil, Import Container'a bağlı:**
- `on_container_update` → ARRIVED_AT_IRAN'a geçişte `create_advance_pe` (DRAFT PE, %70, Commercial Invoice PO Link üzerinden bağlı PO'lara `grand_total`'a orantılı) — **MSAERP'in `trigger_70_percent_bill_on_iran_arrival` sinyalinin doğrudan karşılığı**, ama Purchase Invoice değil Payment Entry üretiyor (plan §3.1 M2 kararı: "CI PI üretmez — İran varışında yalnız %70 avans PE; Purchase Invoice, Purchase Receipt'ten SONRA kesilir").
- Tır tarafı simetriği: `on_truck_update` → `create_transport_pi` (CROSSED_BORDER'a geçişte, DRAFT PI, "Cross-Border Transport" item'ıyla). Kod içinde açık **genişletme noktası** yorumu: MSAERP'in 3-katmanlı lookup'ı (Import Expense linked → Import Expense trucking company eşleşmesi → tır'ın kendi transport_cost'u) yalnız 3. katman implement edilmiş — "Import Expense doctype'ı sonraki bir WP'de gelecek."

**Eksik/yok olan kısımlar (doğrudan doğrulandı, tahmin değil):**
- **VAT hesaplama mantığı yok** — CI'de `%12` formülü, konteyner cross-border transport toplamı gibi hiçbir hesap kodu bulunamadı.
- **Gümrük ücreti (БРВ/CustomsFeeTier) mantığı yok** — MSAERP'in `customs_fee_service.py`'sine denk bir servis yok; `customs_fee` alanı şemada var ama hesaplanmıyor.
- **CIExpense/Import Expense doctype'ı henüz yok** — hooks.py'de açıkça "later WP" olarak işaretli.
- **Landed cost hesaplama/dashboard yok.**
- **7-gün ödeme kuralı henüz implement edilmemiş** — `payment_math.py`'de `ADVANCE_PCT=0.70` var ama `eta_transit_port - 7 gün` hesaplayan bir fonksiyon/rapor yok.
- **`stabler/api/imports.py` yok** — CI için hiçbir whitelisted RPC endpoint'i yok (liste, oluştur, güncelle, statü geçir — hiçbiri).
- **SPA'da hiçbir CI sayfası yok** — sadece placeholder `ImportsDashboard.vue`.
- **Avans allocation (AdvanceAllocation/CILineItemAllocation karşılığı) henüz yok** — plan §3.1'de "native advances + Import Advance Allocation standalone log doctype" olarak tasarlanmış ama oluşturulmamış.

---

### 2.3 Boşluk tablosu

| Özellik | MSAERP | Stabler | Durum | Plan (WP/Faz) | Tahmini zaman |
|---|---|---|---|---|---|
| CI temel kayıt + 9 lojistik statü | Model'de doğru, ama form/liste/rapor UI'ları statüyle tutarsız (bug'lar) | Doctype + controller'da **doğru ve tutarlı** 9 statü + Cancelled + geri-alma mekanizması | ✅ (şema) / 🔜 (SPA) | WP2 SPA | Faz 2, ~Ağustos 2026 |
| `eta_transit_port` alanı | Model'de var, **UI'dan erişilemez** (bug) | Doctype'ta var, SPA henüz yok | 🔜 | WP2 SPA (kritik — bug'ı düzeltir) | Faz 2, ~Ağustos 2026 |
| PI→CI çoklu bağlantı (M2M, satır referanslı) | `pi_reference` string-eşleşme (kırılgan) + M2M `proforma_invoices` — iki paralel mekanizma | **Commercial Invoice PO Link** — gerçek satır-referanslı M2M | ✅ (şema, MSAERP'ten daha sağlam) | WP2 SPA + API | Faz 2, ~Ağustos 2026 |
| Satır kalemi dual pricing (agreed/docs) | `CILineItem.agreed_price/docs_price` | Commercial Invoice Item'da yalnız tek `rate` — `custom_docs_rate` YOK | ❌ | WP1.2/WP2 (yeni custom field + SPA) | Faz 2 öncesi ek WP + Faz 2 |
| VAT %12 hesaplama | `calculate_vat()` servis fonksiyonu | Hiç yok | ❌ | WP2/WP3 (backend hesap fonksiyonu + SPA) | Faz 2-3 |
| Gümrük ücreti / БРВ / CustomsFeeTier | `customs_fee_service.py` + `BRVSetting`/`CustomsFeeTier` modelleri | `customs_fee` alanı şemada var, hesap mantığı yok; BRV/Tier doctype'ları yok | ❌ | WP2/WP3 (yeni doctype + servis + SPA) | Faz 2-3 |
| CI Giderleri (CIExpense — kategori, ödeme akışı, statü) | Tam model + inline formset (Update-only) | Import Expense doctype'ı **yok**, hooks.py'de "later WP" notu var | ❌ | Ayrı WP (Faz 2/3 sınırında, plan §3.1'de "Import Expense" olarak listeli) | Faz 2-3 |
| 7-gün ödeme kuralı (İran ETA − 7g) | 3 farklı (tutarsız) implementasyon, model'de kanonik property var | Hiç implement edilmemiş | ❌ | WP2/WP3 — tek, birleşik hesap fonksiyonu (MSAERP'in 3 implementasyon hatasını tekrarlamadan) | Faz 2-3 |
| Payment Preparation Report | Var, ama model'in `payment_due_date` property'sini kullanmıyor (bug) | Yok | ❌ | Faz 2/4 | Faz 2-4 |
| Landed Cost dashboard/detay | Var (2 sayfa), ama dashboard/detay arası tutarsız toplam (gümrük ücreti dahil/hariç) | Yok | ❌ | Plan §3.1 (Landed Cost Voucher — native), SPA "LandedCostReview" sayfası listeli | Faz 2, ~Ağustos 2026 |
| 70% İran-varış avansı → ödeme belgesi | `Container` sinyali → VendorBill veya ERPNext Purchase Invoice (async) | `on_container_update` → DRAFT Payment Entry (M2 kararınca PI değil PE) — **backend hazır** | ✅ (backend) / ❌ (UI) | WP2 SPA + doğrulama | Faz 2, ~Ağustos 2026 |
| Avans tahsisi (AdvanceAllocation + CILineItemAllocation) | İki paralel mekanizma, otomatik pro-rata + manuel override ekranı | Yok — plan'da "Import Advance Allocation standalone doctype" tasarlanmış, oluşturulmamış | ❌ | WP2/WP3 | Faz 2-3 |
| CI→GRN otomatik oluşturma | `create_grn_for_ci` sinyali (kısmen ölü statü dalları) | GRN Checklist doctype + Truck Receipt→PR akışı var, ama CI'den değil Container/Truck'tan tetikleniyor | 🔜 (mimari farklı ama kapsıyor) | WP2/Faz 4 doğrulama | Faz 2-4 |
| CI→ERPNext Purchase Invoice senkronu | Her kayıtta otomatik Draft PI + custom alanlar | Plan M2 kararı: **CI PI üretmez**, Purchase Receipt'ten sonra native 3-way match ile kesilir — mimari olarak farklı ve daha doğru | ✅ (kasıtlı mimari iyileştirme) | WP2/Faz 4 | Faz 2-4 |
| CI Listesi (kolonlar, filtre, özet, rozetler) | Tam (bug'lı sayaçlarla) | Yok | ❌ | WP2 SPA | Faz 2, ~Ağustos 2026 |
| CI için API endpoint'leri | N/A (Django view'ları) | `stabler/api/imports.py` **yok**, hiçbir whitelisted method yok | ❌ | WP2 | Faz 2, ~Ağustos 2026 |

---

### 2.4 Notlar/kararlar

1. **Stabler'ın CI statü enum'u, MSAERP'in model'inde tanımlı olan ama UI'da asla doğru şekilde kullanılmayan "niyet edilen" 9 statüyü doğru yakalamış** — bu bir parite kazanımı: MSAERP'teki dört farklı statü tutarsızlığı (form widget, liste/detay CSS, sayaç filtreleri, GRN sinyali) Stabler'a taşınmamalı ve taşınmamış.
2. **`eta_transit_port`'un doctype'ta zaten var olması** MSAERP'in en ciddi kullanılabilirlik bug'ını (7-gün kuralının dayandığı alanın UI'dan erişilemez olması) kökten çözüyor — WP2 SPA formunda bu alanın **mutlaka** görünür ve düzenlenebilir olması gerekiyor (aksi halde aynı hata tekrarlanır).
3. **7-gün ödeme kuralı Stabler'da henüz implement edilmemiş** — tasarlanırken MSAERP'in 3 farklı (ve birbiriyle çelişen) implementasyonu tek, kanonik bir fonksiyona indirgenmeli; Payment Preparation Report'un ayrı bir kopya mantık yazmaması (MSAERP'in yaptığı hata) özellikle dikkat edilmeli.
4. **M2 kararı** (CI doğrudan Purchase Invoice üretmez, sadece %70 avans Payment Entry; asıl fatura Purchase Receipt'ten sonra native 3-way match ile kesilir) MSAERP'in mevcut mimarisinden **kasıtlı bir sapma ve iyileştirme** — MSAERP'te CI her kayıtta otomatik Draft PI üretiyor (idempotent ama gereksiz senkron yükü + billing-before-receipt riski taşıyor); Stabler'ın "billing follows receipt" yaklaşımı ERPNext native akışına daha uygun. Bu fark parite denetiminde "eksik" değil, "bilinçli mimari farklılık" olarak işaretlenmeli.
5. **VAT, gümrük ücreti/БРВ, landed cost, CIExpense/Import Expense — dördü de Stabler'da tamamen eksik** ve MSAERP'in finansal olarak en kritik parçalarından (İthalat maliyetinin nihai müşteri fiyatına yansıması). Bunlar WP2/WP3 sınırında, ayrı doctype + servis + SPA gerektiren en büyük iş kalemleri.
6. **`CIExpense.status="PARTIAL"` geçersiz enum bug'ı** ve **`expense_sync.py`'nin ölü kod olması / yerel VendorBill'in CLAUDE.md Kural #2'yle çelişmesi** — Stabler'ın Import Expense tasarımı bu iki hatayı miras almamalı: (a) status enum'u PARTIAL'ı içermeli veya kullanılmamalı, (b) ERPNEXT_ENABLED mantığı olmadığından (Stabler zaten ERPNext-native), yerel GL kaydı riski yapısal olarak yok — ama tasarım gene de "expense → hangi native doctype (Purchase Invoice / Journal Entry)" kararını netleştirmeli.
7. **Landed cost dashboard/detay tutarsızlığı** (gümrük ücretinin dashboard toplamına dahil olmaması) MSAERP'te veri güvenilirliği sorunu yaratıyor; Stabler'ın native Landed Cost Voucher'ı (plan §3.1) tek bir hesaplama kaynağı olacağından bu sınıf hata yapısal olarak ortadan kalkıyor — ama LCV'nin "product+CIF hariç" kapsam kararı (plan R9) ile MSAERP'in "ürün maliyeti dahil" landed cost tanımı arasındaki fark, kullanıcı eğitiminde açıkça belirtilmeli (aynı terim, farklı kapsam).
8. **Avans tahsisi (Advance Allocation) hâlâ tasarım aşamasında** — MSAERP'in iki paralel mekanizması (CI-seviyesi `AdvanceAllocation` + satır-seviyesi `CILineItemAllocation`) Stabler'da tek, standalone `Import Advance Allocation` doctype'ına sadeleştirilmesi planlanıyor (plan §3.1); bu sadeleştirme parite denetiminde olumlu bir konsolidasyon olarak değerlendirilmeli, ama pro-rata formülünün `prepayment_base` mi `agreed_total` mi kullanacağı WP2'de netleştirilmeli (MSAERP'in kendi kod-içi hata notunu tekrarlamamak için, bkz. §1.4 madde 4).
