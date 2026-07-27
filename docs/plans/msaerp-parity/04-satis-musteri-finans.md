# 04 — Satış, Müşteri ve Finans Modülleri: MSAERP → Stabler Özellik Paritesi Denetimi

**Tarih:** 2026-07-10
**Kapsam:** (1) Müşteriler / Customer Center / hiyerarşi / kredi limiti / ekstre, (2) Satış (SalesOrder, CustomerInvoice, DeliveryNote/toplama, SalesReturn/CreditNote, POS, Excel'den satış içe aktarma), (3) Giderler, Tedarikçi Faturaları (VendorBill), Fon Transferi, Banka (ekstre, mutabakat, nakit yönetimi, ödeme içe aktarma), (4) Raporlar (mali, satış, stok, dışa aktarma), (5) Hesap Planı ve mali dönemler.
**Kaynaklar:** MSAERP kod tabanı `/Users/zafar/Downloads/msaerp` (Django, doğrudan `models.py`, `views*.py`, `services/*.py`, `templates/**` okundu); Stabler kod tabanı `/Users/zafar/frappe-bench-local/apps/stabler` (`public/js/pages/**`, `api/*.py`, `router.js`, `organization.py` okundu); `docs/plans/2026-07-09-msaerp-to-stabler-migration-plan.md` (v3, sahip kararları K1-K4, DocType eşleme §3, Faz planı §9).

---

## ⚠️ Metodolojik uyarı — MSAERP tarafında "model var" ≠ "canlı özellik var"

MSAERP kod tabanının doğrudan okunmasıyla ortaya çıkan **en kritik ve bu denetimin tamamını etkileyen bulgu**: MSAERP'de birçok modül **modelde/serviste tam olarak var ama URL yönlendirmesi (`RedirectView`) veya kaldırılmış view'lar (`_RemovedView` → 404, `raise Http404(...)`) yüzünden kullanıcı tarafından erişilemez durumda.** Bu denetim, her özellik için **"canlı/erişilebilir mi?"** sorusunu ayrıca işaretler; yoksa Stabler karşılaştırması yanıltıcı olur (MSAERP'in aslında kullanılmayan bir özelliğini "kayıp" gibi göstermek gibi).

Doğrulanmış canlı/ölü durum özeti:
- **Canlı (gerçekten kullanılıyor):** `proforma/customer-center/` (Alpine.js, ERPNext Sales Invoice/Payment Entry'ye doğrudan bağlı — SalesOrder/CustomerInvoice/CustomerPayment'in Django-model CRUD ekranlarının yerini almış), `sales/import/` (Excel'den satış faturası içe aktarma → doğrudan ERPNext Sales Invoice üretir), `pos/terminal/` + `pos/open-shift/` (ERPNext `/accounting/api/pos/*` uçlarına bağlı), `erpnext_integration` altındaki Hesap Planı / Fon Transferi / Quick Expense / Journal Entry / Payment Entry CRUD ekranları, `payments/import/` (müşteri tahsilat Excel içe aktarma), banka ekstresi CSV içe aktarma + otomatik/manuel eşleştirme (AJAX uçları).
- **Ölü/erişilemez (kod var, route yok veya 404):** `sales/orders/*` (SalesOrder CRUD — detay/form şablonları diskte bile yok), `sales/deliveries/*` (legacy DeliveryNote), `wms/deliveries/*` (WMS DeliveryNote/toplama/FIFO-FEFO), `invoices/*` (Django-model CustomerInvoice CRUD + onay/FIFO ekranı), `payments/*` (CustomerPayment CRUD), `customers/` liste ve detay sayfaları (Customer Center'a yönlendiriliyor), tüm `banking/reconciliation_*` liste/detay sayfaları (silinmiş veri modeline göre yazılmış — her zaman boş/yanlış gösterir, aksiyon butonları 404), `finance/expenses/*` ve `Mark Ready for Payment`/`Cashier Payment` (deprecated stub, `Http404`), Cash Management servisi (import edilemez — `ImportError`), SalesReturn/CreditNote (**hiç view/URL/template yok — hiçbir zaman inşa edilmemiş**).
- **Kısmen çalışıyor / bug'lı:** VendorBill "Post" butonu ERPNext'e hiçbir belge yazmıyor (kozmetik); VendorBill detay sayfası `payment_allocations` satırında sunucu hatası veriyor (silinmiş model); birkaç raporda UI verisi ile export verisi farklı kaynaklardan geliyor (Monthly Sales, Stock Movements).

Bu belgede her bölümün "MSAERP'de bugün" kısmı önce **canlı/erişilebilir özellikleri**, sonra **var olan ama erişilemeyen kod/model katmanını** (gelecekteki ETL ve iş mantığı kaynağı olarak hâlâ değerli) ayrı ayrı ele alır.

---

## Bölüm 1 — Müşteriler: Customer Center, Ebeveyn/Alt Hiyerarşi, Kredi Limiti, Ekstre

### MSAERP'de bugün

**Not:** İki paralel uygulama var — biri **ölü** (`customer_list.html`, `customer_detail.html`; `CustomerDetailView.get()` doğrudan Customer Center'a yönlendiriyor), biri **canlı** (`proforma_app/templates/proforma/customer_center.html`, 2744 satır, Alpine.js, çift panelli QuickBooks-tarzı ekran). `customer_form.html` (oluştur/düzenle tam form) hâlâ canlı ama Customer Center'dan **ayrı bir akış**.

#### `Customer` modeli (`models.py:4274-4489`)

| Alan | Tip | Not |
|---|---|---|
| `company_name` | CharField(200) | zorunlu |
| `customer_code` | CharField(20), unique | otomatik `CUST-####` |
| `customer_type` | choices | `RESTAURANT/RETAILER/DISTRIBUTOR/HOTEL/OTHER`, varsayılan `RESTAURANT` |
| `parent_customer` | self-FK, `SET_NULL`, `related_name="child_customers"` | hiyerarşi — "Ravshan aka gibi bir ebeveynin birden çok lokasyonu" |
| `contact_person`, `email`, `phone`, `address` | | zorunlu (email hariç) |
| `business_registration` | CharField(100) | opsiyonel |
| `credit_limit` | Decimal(12,2), varsayılan 0 | 0 = sınırsız kredi |
| `credit_limit_currency` | CharField(3), varsayılan `UZS` | |
| `payment_terms` | choices | `NET_30/NET_60/NET_90/COD/ADVANCE` |
| `sales_representative` | FK User | |
| `is_active` | bool | soft-delete |
| `current_balance` | Decimal(15,2) | yerel önbelleklenmiş AR bakiyesi |
| `job_status/start_date/end_date/job_description` | | yalnızca `parent_customer` doluysa anlamlı ("job/lokasyon" modeli) |
| `erpnext_name` | CharField(140), unique, indexed | muhasebe sistemi belge adı |
| `erpnext_child_reference` | CharField(20), indexed | Sales Invoice'larda referans olarak kullanılan müşteri kodu |
| `history` | django-simple-history | tam denetim izi |

Yöntemler: `balance`, `available_credit`, `payment_terms_days`, `get_children()`, `get_all_invoices_with_children()`, `get_total_balance_with_children()`, `get_children_balances()`, `recalculate_balance()`.

**Tutarsızlık bulgusu:** Customer Center'ın oluştur/düzenle modalı `customer_type` için `COMPANY/INDIVIDUAL/RESTAURANT/RETAILER/DISTRIBUTOR/WHOLESALER` seçenekleri sunuyor — bunlar modelin gerçek `CUSTOMER_TYPE_CHOICES` ile **eşleşmiyor** (`COMPANY/INDIVIDUAL/WHOLESALER` model için geçersiz; `HOTEL/OTHER` modalde yok).

#### Customer Center ekranı (canlı, `proforma/customer-center/`)

**Sol panel (350px)** — hiyerarşik ağaç: başlık + sıralama düğmesi + "Yeni Müşteri" (+); **"Satışları İçe Aktar"** ve **"Ödemeleri İçe Aktar"** giriş noktaları (ayrı sayfalara link); arama kutusu; ebeveyn satırları genişler/daralır, alt satırlar girintili; her satırda bakiye rozeti (turuncu "Balance Due" / yeşil "Overpaid (Credit)", sıfırsa gösterilmez); alt panelde WebSocket canlı-güncelleme göstergesi (yeşil nokta = bağlı) + "Refresh balances" butonu.

**Sağ panel (detay):**
- Başlık: müşteri adı, tip rozeti, ebeveynliyse "Child of {parent}" (mor, link ikonu) rozeti, satış temsilcisi/telefon/e-posta ikonları.
- Panel aksiyonları (yalnızca `erpnext_name` doluysa): **"New Invoice"** (teal), **"Receive Payment"** (emerald), her zaman **"Edit"**, **"Delete"**.
- **KPI şeridi (4 kart):** Open Balance (kırmızı/yeşil "Overpaid"), AR Aging (4 dilimli mini bar: emerald=Current, amber=1–30, orange=31–60, red=61-90+90), Lifetime Sales, Avg Order.
- **"Statement" (Ekstre) paneli** — asıl canlı ekstre özelliği: `GET /erpnext/api/customer-ledger/`. Başlık + Export butonu (Excel) + büyük Open Balance rakamı. Filtre çubuğu: Type (All/Invoices/Payments), Date From/To. Tablo kolonları: Date, Type (renkli nokta: mavi=fatura, yeşil=ödeme, amber=iade), Customer (yalnız ebeveyn rollup'ında), Reference (+ "FX" rozeti varsa), Debit, Credit, koşan **Balance**. Satıra tıklayınca fatura/ödeme slide-over panel açılır.
- Ayrıca AJAX sekmeler: `invoices`, `payments`, `ar_aging` (VALID_TABS). **AR Aging sekmesi** tam sunucu-render: 4 renkli yaşlandırma kartı + segment bar + "Outstanding Invoices by Age" tablosu + "Collection Summary".
- Fatura slide-over: Customer (salt-okunur), Date, Due Date, **"Whom"** = `custom_child_reference` (serbest metin), kalem tablosu (Item Code select, Boxes, Box Kg, Total Kg hesaplı, Rate, Amount hesaplı), toplam kartı; docstatus'a göre rozet (0=Draft turuncu, 1=Submitted emerald, 2=Cancelled gri) + "Outstanding: X сўм".
- Ödeme slide-over ("Receive Payment"): Date, Account select (Bank/Cash), Amount (`autoAllocate()` ile otomatik dağıtım), açık faturalar listesi (checkbox + düzenlenebilir tahsis tutarı), yabancı para desteği (exchange rate, UZS karşılığı), Notes.
- Oluştur/düzenle modalı (yalnızca): Company Name*, Type, Contact Person, Phone, Email, Address — **kredi limiti alanı modalde YOK**.
- Deaktive modalı: engelleyicileri (blockers) listeler (ERPNext'te aktif fatura/ödeme sayısı, aktif alt müşteri/job sayısı) — varsa buton devre dışı; her zaman **soft delete** (`is_active=False`).

#### Kredi limiti — enforcement var, canlı UI YOK

`InvoicePostingService._check_customer_credit_limit()` faturayı post ederken kontrol eder: `outstanding + invoice_amount > credit_limit` → `CreditLimitExceededError`. Override: `CustomerInvoice.credit_limit_override` (bool) + `credit_limit_override_by/at`; override=True ise kontrol tamamen atlanır (post anında yeniden doğrulama yok). Override checkbox'ı yalnızca **legacy `CustomerInvoiceForm`**'da (`approve_customerinvoice` izniyle gated) var — Customer Center'ın canlı fatura panelinde override kontrolü **bulunamadı**. **Kredi limiti alanının kendisini düzenleyecek canlı bir ekran yok** — yalnızca ölü `customer_form.html`/`customer_detail.html` üzerinden erişilebiliyordu.

#### Ebeveyn/alt hiyerarşi mekaniği

- Rollup: `customer_rollup_names()` — ebeveyn için kendi + tüm **aktif** alt müşterilerin `erpnext_name`'leri; alt/bağımsız için yalnız kendisi. Ekstre, KPI, sekmeler hep bunu kullanır.
- **Ebeveyn değişince taşıma:** legacy `CustomerUpdateView.form_valid()` — ebeveyn değişince o müşterinin tüm fatura/ödemeleri + varsa kendi alt kayıtlarınınkiler + sales order/delivery note'ları **toplu olarak yeni ebeveyne taşınır** (`transaction.atomic()`, tam sayı raporlanır). **Bu taşıma mantığı yalnızca ölü legacy formda var** — Customer Center'ın düzenleme modalında ebeveyn alanı yok.
- `customer_batch_balances_api` — tek ERPNext çağrısıyla tüm bakiyeleri ebeveyn-altına gruplayarak çeker (60sn cache); eski `custom_child_reference` tabanlı gruplamayı da destekler (gerçek hiyerarşiye bağlı olmayan eski SI'lar için).
- Sadece **ebeveyn** ERPNext'e Customer olarak push edilir; **alt müşteriler hiç ERPNext Customer belgesi olarak push edilmez** — yalnız yerel DB'de var, `erpnext_child_reference` üzerinden SI'lara referans veriliyor.

#### ERPNext senkronu

Push (yalnız ebeveyn): create/update → ERPNext `Customer` (`customer_type` eşlemesi: `COMPANY/DISTRIBUTOR/RESTAURANT/OTHER→Company`, `RETAILER→Individual`; `HOTEL` eşlenmemiş, varsayılana düşer). Pull: `sync_customers_from_erpnext` (manuel tetiklenen POST) — ERPNext müşterilerini isimle eşleştirir veya yerel oluşturur; `custom_parent_customer` alanından hiyerarşi bağlantısını okur; ebeveyn-yalnız yerel kayıtları (max 20/çalıştırma) geri push eder. Webhook tabanlı ERPNext→Django push **yok**; gerçek zamanlı bakiye güncellemesi Django Channels WebSocket (`CustomerBalanceConsumer`) ile.

#### Müşteri Excel içe aktarma

**Ayrı bir toplu müşteri içe aktarma özelliği yok.** Sadece Sales Import akışı içinde, satırdaki müşteri ERPNext'te bulunamazsa satır içi "eksik müşteriyi ekle" (`sales_import_add_customer_view`) yardımcı uç noktası var (yeni ERPNext Customer, `customer_type="Company"`, opsiyonel `custom_parent_customer`).

### Stabler'da bugün

`stabler/public/js/pages/sales/Customers.vue` (route `/sales/customers`) — liste + detay birleşik "Customer Center" tarzı sayfa, **ancak hiyerarşik ağaç değil, düz liste.**

- **Sol panel:** aranabilir müşteri listesi, Customer Group / Territory filtreleri, "Only with balance" anahtarı, isim/bakiyeye göre sıralama, toplam alacak footer'ı.
- **Sağ panel (müşteri seçilmemiş):** **alacaklar kokpiti** — Toplam alacak, bugünkü tahsilatlar, 8 haftalık alacak trendi (ApexChart sparkline), **Top 10 Borçlu** listesi (`stabler.api.sales.receivables_cockpit`).
- **Sağ panel (müşteri seçili):** başlıkta Edit/Payment/"New SO" aksiyonları; KPI şeridi (Balance, Overdue, Lifetime Sales, Last Payment date); 3 sekme — **Ledger** (tip/tarih filtreli tam GL-tarzı ekstre + arama/sıralama + "Excel" export → `stabler.api.export.export_report_xlsx?report_key=customer_ledger`), **Orders**, **Invoices**.
- Oluştur/düzenle modalı: Customer name, Type (Company/Individual/Partnership), Tax ID, Customer Group, Territory, Email, Mobile, varsayılan fiyat listesi, varsayılan para birimi. Silme aksiyonu düzenleme modunda mevcut.

**API** (`stabler/api/sales.py`): `list_customers`, `get_customer_defaults`, `list_customers_with_balances`, `customer_ledger`, `customer_detail`, `create_customer`, `get_customer`, `update_customer`, `delete_customer`, `list_customer_groups`, `receivables_cockpit`, `ar_aging`.

**Kredi limiti:** Repo genelinde `credit_limit` alanı hiçbir Stabler API'sinde veya Vue sayfasında okunmuyor/yazılmıyor/uygulanmıyor — **doğrulanmış: hiç uygulanmamış**, ERPNext Customer doctype'ının native `credit_limit` alanı boşta duruyor.

**Hiyerarşi (ebeveyn/alt):** Repo genelinde `custom_parent_customer`, `custom_child`, `custom_is_location`, `parent_customer`, `customer_hierarchy`, `hierarchy` terimleri **yalnızca migration plan dokümanlarında** geçiyor — hiçbir `.py`/`.vue`/DocType JSON'da yok. Canlı `msa.erpstable.com` sitesindeki `custom_parent_customer` vb. alanlar **legacy Django MSAERP'in kendisinin yarattığı** alanlar, Stabler'ın değil. Plan §K2 bunu "karar verildi ama henüz inşa edilmedi" olarak işaretliyor.

**Ekstre/export:** `customer_ledger` Excel export (yalnız .xlsx) var; ayrıca `customer_balance_summary` ve `customer_balance_detail` raporları (`reports.py`). **PDF ekstre yok.**

### Boşluk tablosu

| Özellik | MSAERP | Stabler | Durum | Plan (WP/Faz) | Tahmini zaman |
|---|---|---|---|---|---|
| Müşteri CRUD, arama, tip/grup filtre | ✅ Customer Center'da canlı | ✅ Customers.vue'da canlı | ✅ Yapıldı | — | — |
| Bakiye/AR ekstresi (debit/credit/running balance) | ✅ canlı, ERPNext SI+PE'den | ✅ canlı, Ledger sekmesi | ✅ Yapıldı | — | — |
| Alacaklar kokpiti (top borçlu, trend, günlük tahsilat) | ❌ yok (yalnız KPI kartları var, trend/top-debtor yok) | ✅ canlı, `receivables_cockpit` | ✅ Stabler MSAERP'i geçiyor | — | — |
| AR Aging (yaşlandırma) | ✅ canlı sekme, 4 dilim | ✅ canlı, `/sales/aging` | ✅ Yapıldı | — | — |
| Ebeveyn/alt hiyerarşi (ağaç, konsolide bakiye) | ✅ canlı (sol panel ağacı + rollup) | ❌ yok — düz liste, hiyerarşi kodu sıfır | ❌ Yok — karar gerekli değil, **karar zaten K2'de verildi** | Faz 1 (§9: "DocType'lar + idempotent patch'ler... Customer alanları + UNION helper") | 3 hafta (Faz 1) |
| Ebeveyne toplu tahsilat → child'lara otomatik bölünme | ⚠️ MSAERP'de de yok (yalnız ebeveyn tek işlem alır, gerçek "split" yok) | ❌ yok | 🔜 Planda (K2: "Parent'tan toplu tahsilat... arka planda child başına PE bölünür") | Faz 1-2 | Faz 1-2 içinde |
| Kredi limiti alanı + zorlaması (submit-time check) | ⚠️ model+enforcement var ama **canlı UI'da alanı düzenlemek mümkün değil** | ❌ hiç uygulanmamış | ❌ Yok — karar gerekli | K2: "Kredi kontrolü: limit parent'ta; SI submit hook'u... parent limitine karşı denetler... ERPNext native credit-limit kontrolü kapatılır" | Faz 1 (alan+hook), Faz 2 (SPA) |
| Kredi limiti override (onaylı aşım) | ⚠️ yalnız legacy formda, Customer Center panelinde yok | ❌ yok | ❌ Yok — karar gerekli | K2 + Approval Tier altyapısı (zaten Stabler'da hazır) | Faz 1-2 |
| Ebeveyn değişince fatura/ödeme/SO/DN toplu taşıma | ⚠️ yalnız ölü legacy formda çalışıyordu | ❌ yok (hiyerarşi olmadığı için anlamsız) | 🔜 Planda (dolaylı, hiyerarşi ile birlikte) | Faz 1 | Faz 1 |
| ERPNext müşteri senkronu (push/pull) | ✅ canlı, manuel pull + create/update push | N/A (Stabler zaten ERPNext native, ayrı senkron katmanı yok) | ✅ Mimari olarak gereksizleşiyor | — | — |
| Gerçek zamanlı bakiye WebSocket bildirimi | ✅ canlı (Django Channels) | ❌ yok (sayfa yenileme/manuel refresh) | ❌ Yok — düşük öncelik, karar gerekli değil | Kapsam dışı (nice-to-have) | — |
| Müşteri Excel toplu içe aktarma | ❌ MSAERP'de de yok (yalnız satır-içi tekli ekleme) | ❌ yok | — (her iki tarafta da yok) | — | — |
| Ekstre PDF export | ⚠️ MSAERP: sadece Excel export var | ❌ yalnız Excel (.xlsx) | — (her iki tarafta da yok) | — | — |

### Notlar/kararlar

1. **Hiyerarşi UI'ı Faz 2'ye kadar yok** — plan zaten "hierarchy-mode Customer Center UI planned Faz 2 ≈ Ağustos 2026" diyor; bu denetim bunu doğruluyor: Stabler'da bugün sıfır kod var. Faz 0 bulgusu #4 (170 müşteri, 4.149 SI'ın sıfırı hiyerarşiyle etiketli) sayesinde inşa maliyeti düşük — MSAERP'in kendi hiyerarşi UI'ı da aslında zaten çürümüş durumda (yalnız ölü legacy formda taşıma mantığı vardı), yani "MSAERP'deki her şeyi birebir kopyala" yerine **K2 UNION modelini temiz sıfırdan inşa etmek** daha isabetli.
2. **Kredi limiti — MSAERP'in kendi uygulaması da yarım**: alan var, submit-time kontrol var, ama düzenlenecek canlı UI yok. Stabler'da sıfırdan, K2'nin öngördüğü "limit ebeveyn'de, zincir toplamına karşı kontrol" modeliyle inşa edilmeli — MSAERP'in kırık UI'ını kopyalamaya gerek yok.
3. Stabler'ın **alacaklar kokpiti** (top borçlu, trend sparkline) MSAERP'de hiç yok — bu net bir Stabler avantajı, dokümante edilmeli ama "gap" değil.
4. MSAERP'in Customer Center'ındaki **`customer_type` seçenek tutarsızlığı** (modal vs model) — Stabler'a taşınacak referans değil, düzeltilecek bir hata örneği olarak not edildi.

---

## Bölüm 2 — Satış: SalesOrder, CustomerInvoice, DeliveryNote/Toplama, SalesReturn/CreditNote, POS, Excel'den Satış İçe Aktarma

### MSAERP'de bugün

**Kritik mimari not:** `proforma_app/urls.py`'deki **tüm** klasik SalesOrder/DeliveryNote/CustomerInvoice/CustomerPayment URL'leri `RedirectView` ile `customer_center_entry`'ye yönlendiriliyor (`invoices/`, `payments/`, `sales/orders/`, `sales/deliveries/`, `wms/deliveries/`). Karşılık gelen view/template'ler kodda duruyor ama **hiçbir kullanıcı bunlara erişemiyor**. Gerçek canlı satış arayüzü tek başına **Customer Center**'dır (ERPNext Sales Invoice'a doğrudan bağlı).

#### SalesOrder — ölü/erişilemez ama model+servis tam

`models.py:5416` — `order_number` (`SO-YYYY-XXXX`), `customer`, `customer_po_number`, `payment_terms` (`CASH/NET_15/NET_30/NET_60/PREPAID/CUSTOM`), `subtotal/discount/total_amount`, `total_ordered_qty/total_delivered_qty`, `status` (`DRAFT/CONFIRMED/PARTIALLY_DELIVERED/DELIVERED/PARTIALLY_INVOICED/INVOICED/CANCELLED`). `SalesOrderItem`: `product`, `quantity`(kg), `unit_price`, `delivered_quantity`, `invoiced_quantity`.

Liste şablonu (`sales_order_list.html`) **sabit kodlanmış Rusça**, i18n kuralını ihlal ediyor (`{% trans %}` yok): "Заказы на продажу", kolonlar `Заказ #/Дата/Клиент/Общая сумма/Статус/Действия`; rozetler DRAFT-sarı/CONFIRMED-mavi/DELIVERED-yeşil. **`sales_order_detail.html` ve `sales_order_form.html` diskte hiç yok** — yönlendirme olmasa bile `TemplateDoesNotExist` verirdi; bu gerçekten tamamlanmamış bir özellik. Toplama listesi (`picking_list.html`) ve PDF'i (WeasyPrint) mevcut ama gönderime bağlı değil, sadece baskı hazırlığı.

#### CustomerInvoice — ölü/erişilemez Django-CRUD, canlı olan yalnız Customer Center'daki ERPNext SI paneli

`models.py:4954` — durum: `DRAFT/PENDING_APPROVAL/APPROVED/POSTED/POSTING_FAILED/PAID/VOIDED`; `credit_limit_override(+by/+at)`; `erpnext_sales_invoice`, `erpnext_stock_entry`, `erpnext_status`. `CustomerInvoiceItem`: `quantity`(kutu), `box_kg`(varsayılan 20.00), `total_kg`, `unit_price`, `line_total`, **`allocated_batches` (JSONField — FIFO parti tahsisi)**, `cost_of_goods_sold`.

**Onay/gönderim akışı** (`InvoicePostingService.post_invoice()`, ölü UI ama servis mantığı canlı — Sales Import ve Customer Center bu servisin bazı parçalarını dolaylı kullanabilir):
- Ön koşullar: `DRAFT`/`PENDING_APPROVAL`, kalem var, `total_amount>0`, kredi limiti kontrolü (override yoksa).
- İki dal (`USE_WMS_WORKFLOW`'a göre): **WMS modu** — stok müsaitlik kontrolü → fiyat anlık görüntüsü → 2 satırlı JE (DR AR / CR Sales Revenue, ama `ERPNEXT_ENABLED=True` iken bu **no-op**, "ERPNext GL'yi yönetiyor") → opsiyonel ERPNext Stock Entry → `POSTED`. **Legacy mod** — yerel FIFO stok çıkışı → 4 satırlı JE (no-op) → opsiyonel Stock Entry → `POSTED`.
- `erpnext_sales_invoice` **senkron değil** — `transaction.on_commit` ile ertelenmiş `create_sales_invoice()` çağrısı; hata sadece loglanır, kullanıcıya gösterilmez. Yani `status=POSTED` iken `erpnext_sales_invoice` hâlâ boş olabilir.
- Ölü ama tam UI (`invoice_approve.html`): **onay/FIFO ekranı** — stok müsaitlik kartı (yeşil "FIFO için yeterli stok" / kırmızı liste), "Approve & Post Invoice" (JS confirm: "FIFO ile stok tahsisi yapılacak"), "Reject Invoice" (Bootstrap modal, zorunlu `reject_reason` textarea, DRAFT'a geri döner), workflow stepper DRAFT→PENDING→POSTED→PAID.
- Ölü liste (`invoice_list.html`): 4 KPI kartı (Total/Total Amount/Amount Paid/Balance Due), filtre çubuğu (Search/Status/Customer-Job/Date), kolonlar `Invoice #/Customer/Invoice Date/Due Date(+OVERDUE)/Status/Amount/Paid/Balance/Actions`; rozet mantığı `status`+`erpnext_status` çaprazlamasıyla (Draft/Pending/Paid/Overdue/Unpaid/Cancelled/Posted).

**Canlı olan** — Customer Center'ın fatura slide-over paneli §1'de anlatıldı (Customer, Date, Due Date, Whom=`custom_child_reference`, kalem grid, toplam kartı, docstatus rozetleri).

#### DeliveryNote / Toplama — iki paralel model, ikisi de ölü/erişilemez

- **Legacy** (`models.py:5583`): `delivery_note_number`, `sales_order`, teslimat/şoför bilgileri, `customer_signature`/`proof_of_delivery` (resim), `status` (`DRAFT/SUBMITTED/COMPLETED/CANCELLED`). Liste şablonu yine sabit Rusça.
- **WMS DeliveryNote** (`models.py:5720`): `invoice` FK (CustomerInvoice), `warehouse`, `status` (`PICKING/PACKED/SHIPPED/DELIVERED/RETURNED/CANCELLED`). `DeliveryNoteItem`: **`batch` FK zorunlu** (parti bazlı sevkiyat).
- **Toplama/FIFO algoritması** (`services/picking_service.py`): rezervasyonlar `batch__location__zone/row/shelf, batch__manufacturing_date` sırasına göre — yani **fiziksel depo-yürüyüş sırası birincil, FIFO (üretim tarihi) yalnız aynı rafta eşitlik bozucu**.
- **Rezervasyon FIFO'su** (`services/stock_reservation_service.py`): `ACTIVE` partiler `manufacturing_date, created_at` sırasına göre, `atp = quantity_available - quantity_reserved` üzerinden açgözlü tahsis.
- **Ayrı bir yerel FIFO yolu** (`InventoryService.create_stock_issue_for_invoice`, legacy-mod fatura gönderiminde kullanılır): aynı sıralama, ama doğrudan `batch.quantity_available` düşürür, yerel `StockEntry`/`StockLedgerEntry` oluşturur, COGS'u `CustomerInvoiceItem.cost_of_goods_sold`'a yazar.
- **ERPNext tarafında üçüncü, bağımsız ve FIFO değil FEFO olan bir seçim** (`StockCheckService._select_batches_fefo`): `expiry_date asc, name asc`; süresi geçmiş parti varsa **postu tamamen engeller** (`ExpiredBatchError`). Çoklu parti gerektiğinde yalnız ilk seçilen partinin `batch_no`'su ERPNext Stock Entry satırına yazılıyor — tam liste yalnız log'a düşüyor. **Bu üç ayrı FIFO/FEFO mantığı iki farklı veri kaynağına (yerel `Batch` modeli vs ERPNext `Batch` doctype) karşı bağımsız çalışıyor ve aynı fatura için farklı fiziksel partiler seçebilir** — denetim açısından kritik bir tutarsızlık bulgusu.
- `Batch` modeli: `batch_number`, `manufacturing_date`, `expiry_date`, `quantity_available/reserved`, `valuation_rate`, `status` (`ACTIVE/EXPIRED/QUARANTINE/EXHAUSTED`).

#### SalesReturn / CreditNote — **hiç UI/URL/template yok, hiçbir zaman inşa edilmemiş**

`SalesReturn` (`models.py:6760`): `customer_invoice`, `return_number`, `reason` (`DAMAGED/WRONG_ITEM/QUALITY/CUSTOMER_REQUEST/OTHER`), `status` (`DRAFT/APPROVED/CANCELLED`). `CreditNote` (`models.py:7000`): `sales_return` OneToOne, `credit_note_number`, `amount`, `status` (`DRAFT/POSTED/CANCELLED`).

`ReturnsService`: `create_return()`/`approve_return()` çalışıyor (durum geçişleri), ama **`approve_return()` hiçbir stok işlemi yapmıyor**; `post_credit_note()` — dokümante edilen niyete (ERPNext `is_return=1` Sales Invoice oluşturmak) rağmen **hiçbir ERPNext API'sini çağırmadan yalnızca yerel durumu POSTED'e çeviriyor**; `reverse_stock_issue()` açıkça yer tutucu (`# Placeholder: actual implementation in T03`). **Hiç view, URL veya template yok** (grep ile doğrulandı). İlginç not: `is_return=1` Sales Invoice oluşturmanın **tek gerçek uygulaması** Sales Import servisinde (negatif miktarlı satırlar için) — SalesReturn akışıyla hiç ilgisi yok.

#### POS — tam canlı, amaca özel tek ekranlardan biri

`CustomerInvoice.source_type` (`STANDARD`/`POS`) dışında model yok; `POSSession`/`POSPayment` modelleri var ama **hiçbir view/API bunları kullanmıyor** — POS vardiya durumu tamamen ERPNext `/accounting/api/pos/*` uçlarına bağlı.

- `pos/open-shift/` — vardiya zaten açıksa yönlendirir; POS profili seçer; "Opening Cash Amount" (UZS) → `POST /accounting/api/pos/open-shift/`.
- `pos/terminal/` — üst bilgi (profil, "Shift Open" rozeti, kasiyer, "Close Shift"); sol panel ürün arama + kart grid; sağ panel sepet (adet stepper, alt toplam); ödeme modu ("All Cash"/"All Card"/"Split"); "Complete Sale" → `POST /accounting/api/pos/invoice/create/`; başarı modalı (fatura adı, toplam, para üstü); "Close Shift" modalı (Closing Cash Amount).

Yerel Django kalıcılığı yok — her şey ERPNext üzerinden.

#### Sales Excel İçe Aktarma — canlı, yerel modelleri tamamen atlıyor

Doğrudan **ERPNext Sales Invoice** üretir (Django `CustomerInvoice`/`SalesOrder` satırı oluşturmaz).

- **Beklenen format:** zorunlu kolonlar `date, customer, item, box, box kg, rate`; opsiyonel `total kg, amount, parent`. `'whom'` kolonu = gerçek alıcı (fatura gruplaması bunu kullanır); `'customer'` = ebeveyn/hiyerarşi yedeği.
- **Otomatik düzeltme:** `total_kg` ve `boxes` tutarsızsa (±0.5 tolerans) yeniden hesaplanır ve `*_corrected` bayrağı konur.
- **Gruplama:** `(date, effective_customer)` başına bir ERPNext Sales Invoice. Doğrulama: `customer_missing/item_missing/customer_blank/item_blank/rate_invalid/qty_zero` (engelleyici), `rate_zero/total_kg_corrected/boxes_corrected` (uyarı).
- **Payload:** `{customer, company, posting_date, currency:"UZS", update_stock:0}`; pozitif/negatif satırlar ayrılır — **negatif satırlar `is_return=1` ayrı bir Sales Invoice olarak** gönderilir (aynı tarih+müşteri grubu için 2 fatura üretebilir).
- **İdempotency:** SHA-1 tabanlı import referansı, `po_no` alanına yazılır; mevcut SI durumu kontrol edilip (submitted→atla, draft→submit et, cancelled→yeniden oluştur) tekrar çalıştırma güvenli.
- **Yürütme:** Server-Sent Events akışı (`text/event-stream`), satır satır başarı/hata bildirimi, kısmi import mümkün (`selected_indices`).
- İçe aktarma sırasında eksik müşteri/ürün için satır-içi ekleme uçları (`sales_import_customers_view`, `sales_import_add_customer_view`) var. Her çalıştırma `SalesImportSession` olarak denetlenir (COMPLETED/PARTIAL), geçmiş listesi ve detay sayfası mevcut.

### Stabler'da bugün

**Sayfalar** (`stabler/public/js/pages/sales/` + `pos.vue`):

| Sayfa | Rota | Özet |
|---|---|---|
| `SalesOrders.vue` | `/sales/orders` | Liste: tarih aralığı, durum filtresi (Draft/To Deliver and Bill/To Bill/To Deliver/Completed/Cancelled/Closed/On Hold), arama; kolonlar #, Date, Customer, Total, Delivered %, Billed %, Status, koşullu Reserved. |
| `SalesOrderForm.vue` | `/sales/orders/new`, `/:name` | Tam SO oluştur/düzenle/görüntüle (~1270 satır). Satır bazlı canlı stok kontrolü; pipeline stepper (Quotation→SO→Deliver→Invoice); Save draft / Submit & rezerve et / admin "force submit"; "Create Invoice"; "Close & release reserved stock"; teslim/faturalama ilerleme paneli. |
| `SalesInvoices.vue` | `/sales/invoices` | Liste, para birimi bazlı toplam footer'ı; durum filtresi (Return/Credit Note Issued dahil); "New Return" butonu. |
| `SalesInvoiceForm.vue` | `/sales/invoices/:name` | Kalemler salt-okunur (satırlar SO'dan gelir — tasarım gereği); aksiyonlar: Submit, Receive payment, Issue credit note (modal), Print, "Yuk xati" (irsaliye/waybill) baskısı, Didox EDO gönder/durum, Cancel, Amend, Delete. |
| `Quotations.vue`/`QuotationForm.vue` | `/sales/quotations*` | Teklif CRUD. **"Convert to Sales Order" butonu yok** — hem UI'da hem backend'de doğrulandı, yok. |
| `SalesReturnForm.vue` | `/sales/returns/new` | Bağımsız iade/alacak dekontu — `create_direct_sales_return`. |
| `pos.vue` | `/pos` | Tam POS kasası (aşağıda). |
| `Waybill.vue` | `/sales/invoices/:name/waybill` | SI için yazdırılabilir irsaliye — gerçek bir Delivery Note belgesi değil, SI'nin baskı görünümü. |
| `Aging.vue` | `/sales/aging` | AR yaşlandırma tablosu. |
| `ReservedStock.vue` | `/sales/reserved-stock` | Stok rezervasyon analizörü, **tek depoya sabitlenmiş** (`"Tayyor Mahsulot - A"`). |
| `SalesOrderBoard.vue` | `/tender/board` | Tender'a bağlı SO'lar için kanban. |

**API** (`stabler/api/sales.py`, 2903 satır, 45 fonksiyon; `stabler/api/pos.py`, 7 fonksiyon).

**Mimari kararlar (kasıtlı):**
- SI oluşturma **yalnız SO'dan** — `create_sales_order` yoksa/submit edilmemişse hata verir. Genel "yeni Sales Invoice" yolu yok (yalnız 2 iade rotası + POS istisna).
- **Ayrı bir Delivery Note özelliği yok** — kod içi yorum: *"Stabler sells directly from the warehouse (no separate Delivery Note), so the SI ALWAYS carries `update_stock=1`"*; `RelatedDocuments.vue`'da literal `"Delivery Note": null, // not yet in SPA`; hiçbir `Delivery*.vue` yok. Yalnız eski SO'lar için tek seferlik onarım scripti (`backfill_so_delivery.py`) var.
- Stok rezervasyonu SO submit'te ERPNext native Stock Reservation Entry ile; SI submit'te serbest bırakılır+düşülür.
- İade/alacak dekontu iki yol: (1) faturaya bağlı (`create_sales_return`, ERPNext `make_return_doc`), (2) bağımsız (`create_direct_sales_return`, submitted `is_return=1` SI, otomatik ödeme uygulamaz).
- **POS:** barkod/isim arama, stok-farkında ürün grid'i, sepet, UZS-küsürat yuvarlamalı nakit hızlı tuşlar, online gateway (Payme/Click/Uzum Bank QR + polling), Satış/İade mod anahtarı. "Shift"/"Cashier Lock" UI öğeleri **kozmetik, backend'e bağlı değil**.

**Doğrulanmış boşluklar:**
- **Excel/CSV toplu içe aktarma yok** (Sales Order, Sales Invoice, Quotation, Customer için) — yalnız export var, import yok.
- Quotation→Sales Order dönüşümü yok.
- SO/SI'ye özel biçimsel çok-kademeli onay akışı yok (indirim onayı, kredi-limit-aşımı onayı) — yalnız genel "force submit" checkbox'ı.
- Alacak dekontları açık faturalara otomatik uygulanmıyor.

### Boşluk tablosu

| Özellik | MSAERP | Stabler | Durum | Plan (WP/Faz) | Tahmini zaman |
|---|---|---|---|---|---|
| Sales Order liste+form+onay | ⚠️ model+servis tam ama **erişilemez** (redirect); detay/form şablonu diskte bile yok | ✅ tam canlı, pipeline stepper + stok kontrollü | ✅ Stabler zaten üstün | — | — |
| Customer Invoice liste+form+onay+FIFO | ⚠️ model+servis tam (FIFO onay ekranı dahil) ama **erişilemez**; canlı olan yalnız Customer Center'ın basit paneli | ✅ SO'dan türetilen SI, submit/payment/credit-note aksiyonlu | ✅ Stabler MSAERP'in *erişilebilir* halinden üstün; MSAERP'in *ölü* FIFO onay UI'ı zaten kullanılmıyor | — | — |
| Delivery Note / toplama (WMS, parti bazlı) | ⚠️ model+FIFO/FEFO servisleri tam (3 farklı, tutarsız algoritma) ama **erişilemez** | ❌ kasıtlı olarak yok (SI doğrudan stok düşer) | ❌ Yok — mimari karar farkı, netleştirilmeli | K2 dışı; sahip kararı gerekli: "Delivery Note ayrı adım mı, yoksa Stabler'ın SI=stok-hareketi modeli mi devam edecek?" — plan §3.2 "DeliveryNote → Delivery Note (Legacy arşiv)" diyor, yani **aktif kullanılmayacak, sadece arşiv** | Faz 1 (arşiv kararı) |
| FIFO/FEFO parti tahsisi (satış anında) | ⚠️ üç bağımsız, birbirinden farklı sonuç verebilen algoritma (yerel FIFO, ERPNext FEFO, toplama-sırası) — hiçbiri canlı UI'da yok | ✅ ERPNext native Stock Reservation Entry + Batch (FEFO tek, tutarlı) | ✅ Stabler daha tutarlı — MSAERP'in 3'lü çelişkisi taşınmamalı | Plan §3.2: "Batch→Batch (expiry), FEFO picking `expiry_date asc`" — zaten karar verilmiş | Faz 1 |
| Sales Return / Credit Note | ❌ hiçbir zaman UI/URL inşa edilmemiş (yalnız yarım servis) | ✅ 2 yol (faturaya bağlı + bağımsız), canlı | ✅ Stabler MSAERP'i geçiyor | — | — |
| POS | ✅ canlı, sepet+ödeme+vardiya (ERPNext API'lerine bağlı) | ✅ canlı, ayrıca online ödeme gateway (Payme/Click/Uzum) desteği | ✅ Stabler MSAERP'i geçiyor | — | — |
| Sales Excel içe aktarma | ✅ canlı — SSE akışlı, otomatik düzeltme, idempotent, iade satırı desteği | ❌ yok (yalnız export var) | ❌ Yok — karar gerekli | Belirlenmemiş — ETL kapsamında tek seferlik geçiş var (Faz 3) ama **kalıcı/tekrar kullanılabilir Excel-satış-içe-aktarma özelliği** plan'da yok | Kapsam kararı gerekli; muhtemelen Faz 2 SPA veya "kapsam dışı" |
| Sales Order'dan bağımsız hızlı satış (SO'suz SI) | ⚠️ MSAERP'de de dolaylı — Customer Center doğrudan SI açar (SO'yu atlar) | ❌ yok (SI her zaman SO gerektirir, POS hariç) | 🔜 Planda (M1 notu: "SO'suz hızlı satış gerekiyorsa arka planda otomatik SO") | Faz 1-2 | — |
| Waybill/irsaliye baskısı | ⚠️ toplama listesi PDF'i var (WMS, ölü UI) | ✅ canlı "Yuk xati" (Waybill.vue) | ✅ Stabler'da var, farklı biçimde | — | — |

### Notlar/kararlar

1. **En büyük yanlış-alarm riski:** Bu bölümü MSAERP'in *modellerine* göre değerlendirmek, Stabler'ın aslında MSAERP'in **kullanıcı tarafından hiç görülmeyen** bir SalesOrder/DeliveryNote/CustomerInvoice CRUD yığınına "eksik" gözüyle bakmasına yol açar. Gerçek karşılaştırma noktası MSAERP'in **canlı** yüzeyidir: Customer Center (basit SI paneli) + POS + Sales Import. Bu üçü karşısında Stabler zaten **daha zengin** (tam SO pipeline'ı, stok kontrolü, iade akışı, Waybill baskısı, çok kanallı POS ödeme).
2. **FIFO/FEFO tutarsızlığı MSAERP'in gerçek bir tasarım borcu** — üç bağımsız algoritma iki ayrı veri kaynağına (yerel `Batch` vs ERPNext `Batch`) karşı çalışıyor, aynı fatura için farklı fiziksel parti seçebiliyor. Stabler'ın tek, ERPNext-native FEFO mekanizması bu riski ortadan kaldırıyor — **taşınacak bir "özellik" değil, kaçınılacak bir hata**.
3. **Delivery Note kararı netleştirilmeli:** Plan §3.2 "Legacy arşiv" diyor ama sahip onayı gerektirir — depo/lojistik ekibi fiziksel sevkiyat belgesi (imza, fotoğraf, araç plakası) istiyorsa Stabler'ın "SI=stok hareketi" modeli bunu karşılamıyor; Waybill.vue kısmen bunu telafi ediyor (baskı görünümü var) ama imza/fotoğraf/QC alanları yok.
4. **Sales Excel içe aktarma** — MSAERP'de canlı ve aktif kullanılan (muhtemelen toplu tarihsel veri girişi veya toplu satış işlemleri için) bir özellik; Stabler'da hiç yok. Bunun yalnızca ETL'de tek seferlik mi kalacağı yoksa kalıcı bir SPA özelliği mi olacağı (örn. aylık toplu satış girişi ihtiyacı sürüyorsa) **sahip kararı gerektirir** — plan bunu açıkça ele almıyor.
5. SalesReturn/CreditNote'un MSAERP'de **hiç inşa edilmemiş** olması, Stabler'ın zaten var olan iade akışının bu alanda ekstra bir gap taşımadığı anlamına gelir — sadece iş kurallarının (sebep kodları `DAMAGED/WRONG_ITEM/QUALITY/CUSTOMER_REQUEST/OTHER` gibi) Stabler'a taşınıp taşınmayacağı kontrol edilmeli.

---

## Bölüm 3 — Giderler, Tedarikçi Faturaları (VendorBill), Fon Transferi, Banka

### MSAERP'de bugün

Bu alan **iki paralel katmana** bölünmüş: eski yerel-GL katmanı (`proforma_app`, `VendorBill`/`BankStatement`/`BankAccount` modelleri — GL kaldırılırken kısmen çürütülmüş) ve gerçekten çalışan ERPNext-passthrough katmanı (`erpnext_integration`).

#### VendorBill / VendorBillItem (`models.py:5846`, `:6138`)

Alanlar: `bill_number` (`BILL-YYYY-XXXX`), `vendor`, `bill_date`/`due_date` (vendor ödeme koşullarından otomatik), kaynak belge bağlantıları (`commercial_invoice`, `container`, `truck`, `truck_receipt`, `goods_receipt_note` — 3 yönlü eşleşme), `status` (`DRAFT→POSTED→READY_FOR_PAYMENT→PAID`), `bill_type` (`PRODUCT/TRANSPORT/CUSTOMS/SERVICE/OTHER`), çift-akış fiyatlama: `docs_total_amount`/`diff_total_amount`/`docs_amount_paid`/`diff_amount_paid` ("docs" = resmi/banka ödemesi, "diff" = nakit farkı), `currency`, `exchange_rate`, `erpnext_purchase_invoice` (**ölü alan — hiç yazılmıyor**).

**Kritik bulgular:**
1. **"Post" butonu ERPNext'e hiçbir belge yazmıyor** — yalnız `DRAFT→POSTED` durum değişimi yapıyor; kod yorumunda "GL posting will be handled by signal" yazıyor ama böyle bir signal yok. Gerçek ERPNext Purchase Invoice oluşturma tamamen ayrı bir mekanizmadan geliyor (`Container` → `ARRIVED_AT_IRAN` sinyali → `submit_purchase_invoice_for_container` task'i).
2. **VendorBill detay sayfası sunucu hatası veriyor** — `payment_allocations` context satırı silinmiş `VendorBillPayment` modeline erişmeye çalışıyor (migration `0174_remove_gl_fk_fields.py` ile silindi).
3. **"Mark Ready for Payment" ve "Cashier Payment" 404 stub'ları** — `views_finance.py` açıkça `"""DEPRECATED"""`, tüm metot gövdeleri `raise Http404(...)`.
4. **Form'daki "GL Account" kolonu hayalet** — `VendorBillItemForm`'da böyle bir alan yok, template boş render ediyor.
5. VendorBill'ler manuel değil, **otomatik DRAFT olarak üretiliyor** (`CIVendorBillService`): ana tedarikçi faturası (CI toplamı − PI avansları), gider bazlı faturalar (her `CIExpense` için biri, vendor atanmışsa), navlun rezervasyonu faturaları, sınır geçişi ulaşım faturası.

**Liste/detay/form ekranları var** (`vendor_bills/bill_list.html` vb.) ama yukarıdaki hatalar yüzünden **kısmen çalışmıyor**.

#### BankStatement / BankStatementTransaction — Banka Mutabakatı

Alanlar: `bank_account_name` (serbest metin), `status` (`NEW→PARTIAL→RECONCILED`/`CANCELLED`), `opening_balance`/`closing_balance`; `BankStatementTransaction`: `debit`/`credit`, `match_status` (`UNMATCHED/MATCHED(auto)/MANUAL`), `matched_payment_entry_name`.

**İçe aktarma:** CSV, kolonlar `Date`(DD/MM/YYYY)/`Debit`/`Credit`/`Description`(zorunlu)/`Reference`(opsiyonel); satır hataları toplu import'u durdurmaz.

**Otomatik eşleştirme algoritması:** ERPNext'ten tüm Submitted Payment Entry'leri çeker (max 500); ±2 gün tarih penceresi, **tam tutar eşleşmesi**, referans bulanık eşleşme (alt-dize) veya (referans boşsa) ±1 gün tek kriter. **Tam olarak 1 aday eşleşirse otomatik MATCHED; 0 veya >1 ise manuel incelemeye bırakılır** (en iyi eşleşmeyi otomatik seçmiyor).

**Kritik bulgu — Mutabakat listesi/detay UI'sı tamamen bozuk:** `reconciliation_list.html`/`reconciliation_detail.html`/`banktransaction_list.html` şablonları **silinmiş bir veri modeline göre yazılmış** — var olmayan alanlara (`reconciliation.reconciliation_number`, `transaction.bank_account.account_name` vb.) erişiyorlar, view'lar bu context'i hiç sağlamıyor. Sonuç: sayfalar her zaman "bulunamadı" gösteriyor, her aksiyon butonu (`reconciliation_create/complete/approve`, `transaction_reconcile/unreconcile`) 404. **Yalnız CSV içe aktarma ve iki AJAX uç noktası (`auto_match_statement`, `manual_match_transaction`) canlı veriye dokunuyor** ve bunlara çalışan bir navigasyon yolundan erişilemiyor.

#### BankAccount — fiilen ölü

Tüm `banking/accounts/*` rotaları ya ERPNext Hesap Planı'na (`?account_subtype=BANK`) yönlendiriliyor ya da 404. Yerel model yalnız `MintBankConfig` (ayrı bir Mint-API banka senkronu) tarafından referans alınıyor.

#### Gider ("Expense") kavramı — bağımsız model yok

- **(a) `CIExpense`** — tek hayatta kalan "gider" modeli, bir `CommercialInvoice`'a bağlı: kategori, `bank_payment`/`cash_payment` bölünmesi, `status` (`PENDING→PARTIAL→PAID`, otomatik hesaplı). `CIVendorBillService._create_expense_vendor_bills` üzerinden otomatik `VendorBill`'e dönüşüyor.
- **(b) Eski genel onay akışlı "Expense" özelliği — tamamen kaldırılmış.** URL'ler hâlâ kayıtlı ama hepsi `_RemovedView`/`Http404`.
- **(c) Gerçek canlı gider özelliği "Quick Expense"** (`erpnext_integration/views_journal.py`) — tek seferlik, **her zaman otomatik-submit edilen** çok satırlı Journal Entry (Gider hesabı borç / Ödeme hesabı alacak); taslak/onay adımı yok. Yabancı para desteği, bakiye koruması (`check_sufficient_balance`).

#### Fon Transferi (`erpnext_integration/views_coa.py`) — canlı, yalnız Hesap Planı ekranı içinde

Kaynak/hedef hesap (yalnız yaprak Bank/Cash hesapları), tutar, tarih, opsiyonel not; çapraz para birimi bölümü (kur + hedef tutar, `finance.ExchangeRate`'ten canlı otomatik kur, iki yönlü canlı hesaplama); **bakiye koruması** (yetersiz bakiye + overdraft politikasına göre engelleme); onay modalı; arka planda hesap tiplerine göre otomatik `entry_type` seçimiyle (Contra/Bank/Cash/Inter Company) **otomatik submit edilen** Journal Entry.

#### Nakit Yönetimi (Cash Management) — **tamamen ölü kod**

`CashManagementService`, artık var olmayan modelleri (`BankAccount`, `BankTransaction`, `JournalEntry`, `CashVoucher`, `GLAccount` — hiçbiri `finance/models.py`'de yok) import ediyor; **import edilemez bile** (`ImportError`). Hiçbir view/URL/template bunu çağırmıyor. Petty cash/nakit pozisyonu/kasa mutabakatı diye bir özellik **yok** — fiilen yerini Fon Transferi + Quick Expense alıyor.

#### Ödeme İçe Aktarma (Payment Import) — **müşteri tahsilatı (AR), tedarikçi değil**

`.xlsx`, kolonlar `Date/Amount/Customer/Deposit` (zorunlu) + `Remark/Exchange rate/USD amount/Child customer` (opsiyonel). Negatif tutar = iade (child customer'a veya kendi müşterisine bağlı `Pay`-tipi PE); pozitif tutar = tahsilat → **FIFO çoklu-tahsis** (`simulate_fifo_multi`, açık faturalar en eskiden başlayarak, ebeveyn+alt müşteriler tek kuyrukta birleştirilerek). Kalan tutar "fazla ödeme" avansı olur. İdempotency: SHA-256 tabanlı `reference_no`. UI: Alpine.js 4 adımlı akış (yükle→doğrula, sorun tablosu, özet+önizleme, SSE ile yürütme, ilerleme çubuğu, geçmiş listesi `PaymentImportSession`).

**Not: Tedarikçi faturaları için eşdeğer bir toplu ödeme içe aktarma aracı yok** — AP tarafı Payment Import kapsamı dışında.

#### İlgili canlı ekranlar (`erpnext_integration`, tam çalışıyor)

- **Hesap Planı** (Chart of Accounts): genişleyebilir ağaç, Root Type/arama filtreleri, bakiye (AJAX, 50'lik gruplar halinde yükleniyor), sağ-tık menüsü (Ledger görüntüle/Düzenle/Alt hesap ekle/Sil).
- **Hesap Defteri (Register):** tarih aralığı, çift para birimi (yabancı hesap için UZS eşdeğeri), belgeye tıklayınca kaynak JE/SI/PE'ye gider.
- **Journal Entry CRUD:** tam manuel JE oluşturucu, debit=credit doğrulaması, çoklu para birimi otomatik algılama, submit/cancel/delete/amend.
- **Payment Entry CRUD:** genel PE yönetimi (müşteri+tedarikçi), FX Journal Entry bağlantısı (`FXPaymentPair`).

### Stabler'da bugün

**Sayfalar:** `money/MoneyHome.vue`, `Accounts.vue`, `AccountLedger.vue`, `JournalEntries.vue`, `PaymentEntries.vue`, `PaymentEntryForm.vue`, `Expenses.vue`, `Transfers.vue`, `Approvals.vue`, `Reconcile.vue`, `FxRevaluation.vue`, `Budgets.vue`, `BudgetVsActual.vue`; `purchasing/PurchasingHome.vue`, `Suppliers.vue`, `PurchaseInvoices.vue`, `PurchaseInvoiceForm.vue`, `PurchaseOrders.vue`, `PurchaseOrderForm.vue`, `PurchaseReceipts.vue`, `Aging.vue`.

**Expenses (`money/Expenses.vue`):** çalışan-gider-mutalebe modülü **değil** — doğrudan "çek yaz" tarzı GL kaydı (`voucher_type="Bank Entry"` Journal Entry). İki mod: "Expense" (Gider hesabı borç) / "Asset Purchase" (Sabit Kıymet hesabı borç); çok satırlı, CBU kur ipucu + override, Save & Close/New/Clear. Tedarikçi/PO bağlantısı, makbuz eki, per-claimant onay **yok** (ayrı bir HR-avans alt sistemi var ama kapsam dışı).

**Fund Transfer (`money/Transfers.vue`):** gerçek hesaplar arası transfer, aynı şekilde `Bank Entry` JE'ye dönüşüyor (`entry_type="Transfer"`). Görsel Kaynak/Hedef kartları + takas, tam çapraz-para desteği (karşılıklı tutar/kur/tutar bağlama, CBU otomatik kur, manuel override "AUTO" rozetiyle izlenir).

**Payment Entries:** Receive/Pay, taraf varsayılanları + açık faturalar otomatik yüklenir (FIFO otomatik tahsis, gönderimden önce düzenlenebilir), çapraz-para banka tutarı alanı (CBU'ya göre >%5 sapma uyarısı).

**Purchase Invoices ("Vendor Bills"):** Liste — tarih aralığı, durum (Paid/Unpaid/Overdue/Partly Paid/Return/Debit Note Issued/Draft), arama, para birimi bazlı toplamlar. Form: Supplier, Warehouse, tarihler, Bill No/Date, para birimi+dönüşüm kuru (öneri ipucu), vergi şablonu, indirim, boyut alanları. Aksiyonlar: Save/Submit/Make payment/Issue debit note/Print/Cancel/Amend/Delete.

**Üç yönlü eşleşme** (`_three_way_match.py`) — **opsiyonel** (`Stabler Settings.enable_three_way_match`): oran sapması PO'ya karşı (engelleyici), faturalanan miktar > alınan miktar toleransın üstünde (engelleyici), faturalanan > sipariş edilen (yalnız uyarı).

**Purchase Order / Purchase Receipt:** PO listesi/formu, kısmi teslim alma modalı, doğrudan-PO'suz teslim alma da destekleniyor. Landed cost voucher bağlantı banner'ı var ama **bu dosyalarda oluşturma UI'ı yok** (otomasyon imports_module'de).

**Banka mutabakatı/ekstre içe aktarma — inşa edilmiş ve işlevsel tamamlanmış** (`stabler/integrations/bank_statement/` + `Stabler Bank Import` doctype + `money/Reconcile.vue`):
- Format: **"1C ClientBank Exchange"** — BDT/Özbekistan'da yaygın metin formatı (Kiril anahtar=değer, kodlama otomatik algılama cp1251/cp866/UTF-8). **MT940/SWIFT/OFX/genel CSV desteği yok.**
- İçe aktarma: önizleme → tekilleştirme (`dedupe_key`) → her satır için bir `Bank Transaction` oluşturup submit eder → `Stabler Bank Import` denetim kaydı.
- Eşleştirme: `suggest_matches` — Payment Entry ve Journal Entry satırlarına karşı tutar/tarih/referans/karşı-taraf INN ağırlıklı skorlama (CIS isim-transliterasyon gürültüsüne göre ayarlı); mutabakatın kendisi **tek tıkla manuel onay** (tam otomatik değil), kısmi bölme desteği (`reconcile_partial`), `unreconcile`.

**FX Revaluation:** ERPNext'in native "Exchange Rate Revaluation" doctype'ının ince sarmalayıcısı — kendi GL kaydını üretmiyor, native belgeyi oluşturup submit ediyor.

**Çok para birimi (USD/UZS):** CBU günlük kur entegrasyonu Journal Entry, Payment, Transfer, Expense, Purchase Invoice, FX Revaluation ve Hesap Defteri'nin USD-eşdeğeri katmanında geniş şekilde işleniyor. Sabit taban: USD→UZS kuru 1000'in üstünde olmalı; ±%20 CBU-tolerans bandı.

**Konteyner/landed-cost alt sistemi:** `stabler/stabler/imports_module/` — Container/Truck/GRN/Vet Certificate/Landed Cost otomasyonu **ayrı bir denetim konusu** (bu belgenin kapsamı dışı, ama plan §3.1'in doğrudan hedefi).

**Doğrulanmış boşluklar:**
- Money modülünde çalışan-gideri/mutalebe akışı yok (Expenses = doğrudan GL kaydı, personel talebi değil).
- Banka mutabakatı tek CIS formatına sınırlı.
- Üç yönlü eşleşme varsayılan olarak kapalı.
- İncelenen Purchasing sayfalarında landed-cost oluşturma UI'ı yok (imports pipeline'ında otomatik).

### Boşluk tablosu

| Özellik | MSAERP | Stabler | Durum | Plan (WP/Faz) | Tahmini zaman |
|---|---|---|---|---|---|
| Vendor Bill (Purchase Invoice) liste+form | ⚠️ liste/form var ama **detay sayfası sunucu hatası veriyor**, "Post" kozmetik | ✅ tam çalışan liste+form+submit+payment+debit-note+3-way-match | ✅ Stabler MSAERP'in bozuk halinden üstün | — | — |
| Otomatik VendorBill üretimi (CI/gider/navlun/sınır-geçişi tetikli) | ✅ canlı, `CIVendorBillService` | 🔜 planda — imports_module otomasyonu (Container/Truck/GRN hook'ları, plan §4) | 🔜 Planda | Faz 1-2 (imports otomasyon portu) | Faz 1-2 |
| Çift-akış (docs/diff) fiyatlama | ✅ canlı, VendorBill+Item seviyesinde | 🔜 planda, K3 kararına göre `custom_docs_*`/`cash_difference`, perm_level 1, maskeleme | 🔜 Planda | K3 kapsamında | Faz 1-2 |
| Banka ekstresi CSV içe aktarma + eşleştirme | ✅ içe aktarma canlı; **liste/detay UI'sı tamamen bozuk**, aksiyon butonları 404 | ✅ 1C format, tam işlevsel (önizleme+dedup+skor+manuel onay+kısmi bölme) | ✅ Stabler MSAERP'in bozuk halinden çok üstün | — | — (MSAERP formatı da eklenmeli mi karar gerekli) |
| MSAERP formatı banka ekstresi (CSV, Date/Debit/Credit/Description/Reference) desteği | ✅ | ❌ yalnız 1C format destekleniyor | ❌ Yok — karar gerekli | "MSAERP format parser'ı eklenir" (plan §3.2, BankStatement satırı) | Belirlenmemiş, muhtemelen Faz 3 (ETL) |
| Fon Transferi | ✅ canlı, çapraz para, bakiye koruması | ✅ canlı, çapraz para, CBU otomatik kur, bakiye koruması | ✅ Yapıldı (paritede) | — | — |
| Quick Expense / gider kaydı | ✅ canlı, tek-adım otomatik-submit JE | ✅ canlı, benzer model (Expense/Asset Purchase modu) | ✅ Yapıldı (paritede) | — | — |
| Çalışan gideri/mutalebe (reimbursement) onay akışı | ❌ MSAERP'de de yok (yalnız CI-bazlı `CIExpense`, genel onaylı akış kaldırılmış) | ❌ Money modülünde yok (ayrı HR-avans alt sistemi var, kapsam dışı) | — (her iki tarafta da resmi olarak yok) | — | — |
| Nakit Yönetimi (petty cash, kasa mutabakatı) | ❌ MSAERP'de tamamen ölü kod (import edilemez) | ❌ yok, Fon Transferi+Quick Expense ile telafi ediliyor | — (her iki tarafta da yok — MSAERP'in "özelliği" zaten çalışmıyordu) | — | — |
| Müşteri tahsilat Excel içe aktarma (Payment Import) | ✅ canlı, FIFO çoklu-tahsis, SSE, idempotent | ❌ yok | ❌ Yok — karar gerekli | ETL'de tek seferlik geçiş var ama kalıcı özellik olarak plan'da yok | Kapsam kararı gerekli |
| Tedarikçi ödeme toplu içe aktarma | ❌ MSAERP'de de yok | ❌ yok | — (her iki tarafta da yok) | — | — |
| Hesap Planı (CoA) — ağaç, bakiye, Ledger, Fund Transfer | ✅ canlı, tam işlevsel | ✅ ERPNext native passthrough (§4/5'te detay) | ✅ Yapıldı | — | — |
| Journal Entry CRUD | ✅ canlı, tam manuel JE oluşturucu | ✅ `JournalEntries.vue` (Money modülü) | ✅ Yapıldı | — | — |
| Onay kademeleri (Approval Tier) — PI/PE/JE/PO | ❌ MSAERP'de yok | ✅ canlı, çok-kademeli eşik bazlı onay (`Stabler Approval Request`) | ✅ Stabler MSAERP'i geçiyor | — | — |
| FX Revaluation | ❌ MSAERP'de yok (yalnız kur senkronu var, revalüasyon JE'si yok) | ✅ canlı, ERPNext native Exchange Rate Revaluation sarmalayıcısı | ✅ Stabler MSAERP'i geçiyor | — | — |
| Üç yönlü eşleşme (3-way match) | ⚠️ VendorBill'de kaynak bağlantıları var ama otomatik doğrulama/blokaj yok | ✅ canlı, opsiyonel (`enable_three_way_match`) | ✅ Stabler MSAERP'i geçiyor (etkinleştirilmeli) | — | Hedef tenant için toggle kontrolü |

### Notlar/kararlar

1. **MSAERP'in Banka/Finans katmanı, Sales katmanından bile daha çürümüş durumda** — GL kaldırılırken VendorBill/BankReconciliation UI'ları güncellenmeden bırakılmış; şablonlar silinmiş modellere referans veriyor. Bu bölümde "MSAERP'de var, Stabler'da yok" diye görünen çoğu şey aslında **MSAERP'de de fiilen çalışmıyor** — parite karşılaştırması MSAERP'in *kod varlığına* değil *gerçekten çalışan* davranışına göre yapılmalı.
2. **Karar gerektiren gerçek boşluk: MSAERP-format banka ekstresi (CSV) desteği.** Stabler'ın mutabakat modülü yalnız 1C formatını destekliyor; plan zaten "MSAERP format parser'ı eklenir" diyor (§3.2) ama bunun ETL'de tek seferlik mi yoksa kalıcı bir ikinci format seçeneği mi olacağı netleştirilmeli — muhtemelen bankalar MSA'da zaten 1C formatını kullanıyorsa (Özbekistan bankacılık sektöründe yaygın) bu sorun kendiliğinden çözülür; doğrulanmalı.
3. **Payment Import (müşteri tahsilat Excel'i) — Sales Excel içe aktarma ile aynı kategoride kalıcılık kararı gerektiriyor.** Her ikisi de MSAERP'de aktif kullanılan, FIFO/idempotent, SSE-akışlı, olgun özellikler; Stabler'da hiçbiri yok. Bunların günlük/aylık operasyonel ihtiyaç mı yoksa yalnızca geçmiş veri girişi ihtiyacı mı olduğu (yani ETL sonrası hâlâ gerekecek mi) sahip ile netleştirilmeli.
4. **Nakit Yönetimi ve çalışan-gideri mutalebesi her iki tarafta da yok** — bunlar gerçek bir gap değil, iki sistemin de bu işi kapsam dışı bıraktığı alanlar; migration planında da hiç geçmiyor, bilinçli bir kapsam dışı bırakma olarak dokümante edilmeli.
5. Stabler'ın **Onay Kademeleri + FX Revaluation + 3-way-match** özellikleri MSAERP'de hiç yok — bunlar net kazanımlar, migration'ın "yeniden konumlandırma" tezini destekliyor (plan §0: "en büyük mimari kazanç: çift-veritabanı senkron katmanı komple ölür").

---

## Bölüm 4 — Raporlar (Mali, Satış, Stok, Dışa Aktarma)

### MSAERP'de bugün

**Yapısal bulgular:**
- **Çift kayıtlı/ölü rotalar:** `reports/ar-aging/` ve `reports/ap-aging/` iki kez kayıtlı (`views.py` ve `views_financial_reports.py`); Django'da ilk eşleşen kazanır → `views_financial_reports.py`'deki AR/AP Aging sınıfları **erişilemez ölü kod**.
- **Şablon dizini gölgelemesi:** `settings.py`'de `TEMPLATES[0]["DIRS"]` kök `templates/` dizinini `APP_DIRS`'den önce kontrol ediyor — bazı raporlarda (`report_pl.html`, `report_bs.html`, `report_tb.html` vb.) kök dizindeki şablon, uygulama içindeki (anlamlı farklarla) farklı kopyayı gölgeliyor. Ölü ağırlık.
- **GL raporları sert şekilde kaldırılmış:** `ProfitLossReportView`, `TrialBalanceReportView`, `BalanceSheetReportView`, tüm Journal Entry görünümleri `Http404("... removed — use ERPNext.")` veriyor.
- **Hiçbir raporda grafik/chart yok** — tüm "raporlar" HTML tablo + renkli KPI kartı.
- **Export kütüphanesi:** yalnız `openpyxl` (Excel); PDF/`reportlab`/`weasyprint`(rapor için) yok. CSV export'lar stdlib `csv.writer` ile (yalnız 2 rapor).

#### Raporlar Paneli (hub)

`reports/` → statik kart-grid: **Mali Raporlar** (AR Aging, AP Aging, Payments Register, Deposit Summary, Bank/Cash Balances, Advance Summary, CI Financial Summary, Vendor AP, PI Progress, PI Group Container Status), **Satış Analitiği** (Sales by Customer, Sales by Item, Trending Items, ABC/XYZ Analysis, Sales Detail, Monthly Sales), **Stok Raporları** (Stock by Warehouse, Stock Movements). Kart adları sabit Rusça, `{% trans %}` kullanılmıyor (i18n kuralı ihlali).

#### Mali raporlar (özet)

| Rapor | Veri kaynağı | Filtreler | Export |
|---|---|---|---|
| AR Aging | ERPNext "Accounts Receivable Summary" (5dk cache) | yok (yalnız `?force=1`) | ✅ Excel |
| AP Aging | ERPNext "Accounts Payable Summary" | yok | ❌ yok (asimetri) |
| Payments Register | ERPNext Payment Entry (doğrudan MariaDB hızlı yol + HTTP yedek) | tarih ön ayarları, karşı taraf, hesap | ✅ Excel |
| Deposit Summary | ERPNext + yerel `DepositSummaryService` | tarih aralığı | ✅ Excel |
| Bank/Cash Balances | ERPNext Trial Balance motoru (Bank/Cash filtreli) | yok | ❌ yok |
| Advance Payment Summary | yalnız yerel `AdvancePayment` | yok | ❌ yok |
| CI Financial Summary | yalnız yerel `CommercialInvoice`+`CIExpense` | yok | ❌ yok |
| Vendor AP Report | yalnız yerel | yok | ❌ yok |
| PI Progress Report | yalnız yerel | arama, vendor, PI Group, status | ❌ yok |
| PI Group Container Status | yalnız yerel | PI Group, vendor, tarih, status | ✅ **CSV** (tek CSV export) |
| Payment Preparation | yalnız yerel `CommercialInvoice` | days ahead, supplier | ❌ yok |
| P&L / Balance Sheet / Trial Balance | ERPNext rapor motoru RPC (`erpnext.accounts.report...execute`, 1sa cache+2sa bayat-fallback) | dönem başı/sonu veya tarih | ✅ Excel |

#### Satış analitiği (özet)

Sales by Customer (yerel, ebeveyn/alt hiyerarşik satırlar), Sales by Item (ERPNext), Trending Items (ERPNext, iki dönem karşılaştırma, **çevrilmemiş**), ABC/XYZ Analysis (yerel, 9 segment, **çevrilmemiş**), Sales Detail Report (ERPNext, sayfalama 100/sayfa, fatura detay linki ERPNext-yalnız satırlarda muhtemelen kırık), Monthly Sales Report (**UI verisi ERPNext'ten, export verisi farklı bir yerel model `CustomerInvoiceItem`'dan — kaynak uyuşmazlığı bug'ı**).

#### Stok raporları (tümü yerel DB tabanlı)

Stock by Warehouse (yerel `StockLedgerEntry`), Stock Movements (**"Balance" kolonu hiç uygulanmamış stub, her zaman em-dash; export UI'dan farklı bir model sorguluyor — uyuşmazlık**), Item Transactions/Product Ledger (GRN+CustomerInvoiceItem+StockEntryItem birleşimi, koşan bakiye + FIFO parti kenar çubuğu), Stock Ledger/Cardex (`stock_ledger_service.py`, ağırlıklı ortalama değerleme kardex'i — stok rapor setindeki **tek Excel export**, 13 kolon), Warehouse Stock Dashboard (parti sona erme durumu — good/upcoming/critical/expired).

### Stabler'da bugün

**Mimari:** `ReportsHub.vue` (`/reports`) — kategorize dizin (Financial/Sales/Purchasing/Inventory/Warehouse/People/Field Sales/Trade Marketing/Installment), kategori bazlı modül erişimiyle korunuyor. Mali tablolar bağlantısı açıkça "ERPNext" rozeti taşıyor çünkü bunlar ERPNext'in native Query Report'larının ince sarmalayıcısı (`stabler.api.money.run_report`, yalnız P&L/Balance Sheet/Trial Balance/Cash Flow'a izin verilmiş) — Sales/Purchasing/Inventory raporlarının aksine **özel Stabler raporu değil**.

Çoğu özel rapor **genel, yapılandırma-güdümlü bir motor** üzerinden çalışıyor: `DrillReport.vue`, tamamen `router.js`'deki `meta.report`'tan parametrelenir (özet API, detay API, drill anahtarı, export adı, filtreler) — `customer-abc`, `purchases-by-supplier`, `supplier-abc`, `inventory-aging`, `margin-by-item`, `margin-by-customer`, `sales-by-salesperson`, `sales-orders`'ı besliyor.

**Tam rapor envanteri** (`stabler/api/reports.py`, 1701 satır):
- **Satış:** `sales_by_customer(_detail)`, `customer_balance_summary/_detail`, `sales_by_item(_detail)`, `item_abc`, `customer_abc`, `gross_margin_by_item`, `gross_margin_by_customer`, `sales_by_salesperson`, `sales_orders`, `sales_trend`.
- **Satın alma:** `purchases_by_supplier(_detail)`, `supplier_abc`.
- **Stok:** `inventory_aging`, `inventory_expiry` (parti sona erme ufku), `stock_movement_summary`, `stock_daily_kpi`, `stock_ledger_detail`.

Tümü şirket-kapsamlı, yalnız submit edilmiş belgeler, para birimleri hiç toplanmıyor (UZS+USD karıştırılmıyor).

**Export** (`stabler/api/export.py`): merkezi `export_report_xlsx(report_key, filters)` — **yalnız XLSX**, sunucu tarafında raporu yeniden çalıştırır (istemci satırlarına güvenmez), 30 raporluk kayıt, hassas raporlar için (marj, mali tablolar, GL) rol koruması + Activity Log denetimi. Mali tablolar için ayrı, eski bir export yolu daha var (`stabler.api.money.export_report`, "Excel — basic" veya "CSV"). **Hiçbir yerde PDF export yok.**

**Doğrulanmış boşluklar:**
- Sales/Purchasing raporlarındaki drill/filtre/ABC cilası, mali tablolarda (P&L/BS/TB/Cash Flow) **yok** — bu 4 tablo için tek genel tablo görüntüleyici (`money/Reports.vue`).
- Hiçbir yerde PDF export yok.
- `sales_by_salesperson` ve `sales_orders` raporlarının detay drill'i yok (yalnız özet).

### Boşluk tablosu

| Özellik | MSAERP | Stabler | Durum | Plan (WP/Faz) | Tahmini zaman |
|---|---|---|---|---|---|
| AR/AP Aging raporu | ✅ canlı (AR export'lu, AP export'suz) | ✅ canlı, drill destekli | ✅ Yapıldı | — | — |
| P&L / Balance Sheet / Trial Balance | ✅ canlı, ERPNext rapor motoru RPC + cache | ✅ canlı, ERPNext native Query Report passthrough | ✅ Yapıldı (temelde eşdeğer mimari) | — | — |
| Cash Flow raporu | ❌ MSAERP'de yok | ✅ canlı (`run_report` izin listesinde) | ✅ Stabler MSAERP'i geçiyor | — | — |
| Sales by Customer/Item, ABC/XYZ, marj raporları | ✅ canlı (yerel+ERPNext karışık, bazı kaynak uyuşmazlığı bug'ları var) | ✅ canlı, tutarlı tek motor (`DrillReport.vue`), drill destekli | ✅ Stabler daha tutarlı | — | — |
| Stok yaşlandırma/sona erme raporu | ⚠️ Warehouse Stock Dashboard (parti sona erme) var ama export/drill yok | ✅ `inventory_aging`, `inventory_expiry`, drill+export | ✅ Stabler MSAERP'i geçiyor | — | — |
| Stok kardex/hareket raporu | ✅ canlı (`stock_ledger_service`, ağırlıklı ortalama, 13 kolon export) | ✅ `stock_movement_summary`, `stock_ledger_detail` | ✅ Yapıldı (doğrulama gerekir — kg-bazlı & parti-bazlı MSAERP mantığının Stabler'a taşınması) | Faz 1-3 (imports/stok altyapısı ile birlikte) | — |
| PI/CI/Vendor ilerleme raporları (Advance Summary, CI Financial Summary, Vendor AP, PI Progress, PI Group Container Status) | ✅ canlı, tamamen yerel (ithalat zincirine özel) | ❌ yok (henüz ithalat modülü Stabler'da inşa edilmedi) | 🔜 Planda — imports_module raporlaması (plan §3.1 DocType eşlemesi ile birlikte) | Faz 2 (SPA "imports" modülü, `ImportsDashboard`) | Faz 2, 5 hafta |
| PDF rapor/export | ❌ MSAERP'de de yok (yalnız Excel/CSV) | ❌ yok (yalnız XLSX) | — (her iki tarafta da yok) | — | — |
| Mali tablolarda drill-down/grafik | ❌ MSAERP'de yok (tablo+KPI kart) | ⚠️ Sales/Purchasing raporlarında var, mali tablolarda yok | 🔜 İyileştirme fırsatı, gap değil | Kapsam dışı / nice-to-have | — |
| Rapor veri kaynağı tutarlılığı (UI vs export aynı kaynak) | ❌ MSAERP'de en az 2 rapor bu hatayı taşıyor (Monthly Sales, Stock Movements) | ✅ export her zaman raporu sunucuda yeniden çalıştırıyor (`export_report_xlsx`) | ✅ Stabler'ın mimarisi bu hatayı yapısal olarak engelliyor | — | — |

### Notlar/kararlar

1. **MSAERP'in rapor setinin büyük kısmı ithalat zincirine özel** (PI Progress, CI Financial Summary, Vendor AP, PI Group Container Status, Deposit Summary, Advance Summary) — bunlar Stabler'ın henüz inşa edilmemiş `imports_module`'üne bağlı; bu bölümdeki asıl "boşluk" aslında Bölüm 3 dışında kalan, ayrı denetlenmesi gereken ithalat-zinciri raporlama alanıdır (plan §5, `ImportsDashboard`).
2. **Genel satış/finans/stok raporlarında Stabler zaten mimari olarak MSAERP'den daha sağlam** — tek motor (`DrillReport.vue` + `reports.py`), tutarlı export (sunucu-taraflı yeniden hesaplama), rol bazlı hassas veri koruması. MSAERP'in raporlarındaki UI/export kaynak-uyuşmazlığı hataları (Monthly Sales, Stock Movements) taşınmamalı, bilinçli olarak terk edilmeli.
3. Her iki tarafta da **PDF export yok** — bu ortak bir boşluk, ancak muhasebe/denetim ekibi PDF mali tablo talep ediyorsa (Özbekistan'da resmi teftiş için gerekebilir) ayrıca değerlendirilmeli.

---

## Bölüm 5 — Hesap Planı ve Mali Dönemler

### MSAERP'de bugün

#### Hesap Planı — %100 ERPNext passthrough, yerel model/önbellek yok

Hiçbir yerel Django modeli hesap, GL kaydı veya CoA hiyerarşisini desteklemiyor. `erpnext_integration/views_coa.py`/`forms_coa.py` doğrudan ERPNext `Account` doctype'ı üzerinde çalışıyor. Eski `chart-of-accounts/<pk>/` rotası artık 404; `GLAccount` modeline referans veren iki yetim şablon (`glaccount_detail.html`, `glaccount_list.html`) diskte duruyor ama erişilemez.

Canlı ekran: `erpnext/chart_of_accounts.html` — Root Type filtresi, arama, girintili ağaç (Account Name, Type rozeti, Currency, async yüklenen Balance), sağ-tık menüsü (Ledger görüntüle/Düzenle/Alt hesap ekle/Sil). Hesap oluşturma formu: account_name, parent_account, root_type, account_type (24 ERPNext seçeneği), account_currency (varsayılan UZS), is_group, opening_balance (sıfır olmayan → otomatik "Opening Entry" JE'si oluşturup submit ediyor).

#### Mali Yıl / Muhasebe Dönemi

**Modeller** (`finance/models.py`): `FiscalYear` (year_code, start/end date, status DRAFT/ACTIVE/CLOSED, `generate_periods()` 12 aylık dönem üretir, `close_year()` tüm dönemler CLOSED/LOCKED olmadan çalışmaz), `AccountingPeriod` (period_number 1-12, status OPEN/CLOSING/CLOSED/LOCKED, `close_period()`/`reopen_period()`/`lock_period()`).

**Zorlayıcı — canlı ama kısıtlı:** `PeriodService.validate_transaction_date()` — gerçek kapı bekçisi, `views_finance.py`'ye bağlı.

**`PeriodClosingService` — doğrulanmış ölü/kırık kod:** `services/__init__.py`'den export edilmiyor, sıfır çağıran var, `GLAccount`/`JournalEntry`/`JournalEntryLine`/`Expense` gibi **artık hiç var olmayan** sınıfları import etmeden kullanmaya çalışıyor — çağrılsa `NameError` verir. İlişkili `gl_services.py` de aynı şekilde bozuk ama hâlâ üç serviste (`expense_service.py`, `invoice_posting_service.py`, `shipment_service.py`) import ediliyor — kırılganlık riski. **Gerçek dönem kapama yeteneği** yalnız düz model metotlarından ibaret (durum bayrağı çevirme) — **hiç kapanış kaydı / gelir-gider hesaplarının bilanço hesabına aktarımı yok**; gerçek kapanış kayıtları gerekiyorsa ERPNext'te yapılmalı.

**Kullanıcı arayüzü yok** — `FiscalYear`/`AccountingPeriod` hiçbir view/url/template'te geçmiyor; yönetim **yalnız Django admin** üzerinden (üretimde bir olayda ham Django-shell ORM çağrılarıyla dönem oluşturulduğu belgelenmiş — kendiliğinden yıl-sonu devri akışı yok).

#### Döviz Kuru Yönetimi

**Model:** `ExchangeRate` (currency, rate_to_usd, rate_to_uzs, effective_date, is_active — para birimi başına tek aktif satır). **Gerçek iş mantığı:** `ExchangeRateService` — yedekleme zinciri (DB tam eşleşme → en yakın önceki → hesaplanan çapraz kur → sabit kodlu varsayılanlar: USD 12.755, EUR 13.839, IRR 0.3030, RUB 127.0, TRY 352.0).

**Kırık paralel uç nokta:** `finance/views.py::get_exchange_rate` var olmayan model alanlarını sorguluyor, sessiz `except: pass` ile her zaman `{"exchange_rate": 1.0}` döndürüyor — hiçbir şablon kullanmıyor, ölü kod.

**Senkron mekanizması — CBU (Özbekistan Merkez Bankası), manuel giriş UI'ı yok.** İki yönetim komutu `cbu.uz` JSON API'sinden çekiyor: `sync_exchange_rates.py` (geri dolgu aracı, USD/EUR/RUB/TRY varsayılan; `--local-only` yoksa ERPNext `Currency Exchange` belgeleri de oluşturur), `fetch_daily_rates.py` (günlük, USD/EUR/RUB/TRY sabit kodlu, cron önerilir ama **repo içinde hiçbir zamanlayıcı bağlantısı yok** — yenileme tamamen repo dışı/manuel).

**Override:** özel bir "kuru geçersiz kıl" UI'ı yok; yalnız senkron komutunu yeniden çalıştırmak (upsert) veya doğrudan Django-admin düzenlemesi. Fon Transferi formunda işlem bazlı manuel kur override'ı var ama bu, saklanan `ExchangeRate` tablosunu etkilemiyor.

**Desteklenen para birimleri:** `CURRENCY_CHOICES` — UZS (сўм), USD, RUB, EUR, IRR, TRY.

### Stabler'da bugün

**Hesap Planı / Mali Yıl — saf ERPNext passthrough.** `stabler/api/onboarding.py::provision()` içinde Company `chart_of_accounts: "Standard"` ile oluşturuluyor, ERPNext'in kendi `Company.on_update()` mekanizması CoA'yı otomatik kuruyor. **Stabler'da Fiscal Year oluşturma kodu hiç yok** — grep yalnız *tüketicileri* buluyor (`money.py::_resolve_fiscal_year()`, `budget.py` doğrulaması), hiçbir *oluşturucu* yok. **İlk kurulum riski olarak işaretlendi:** yeni kurulan bir şirkette ERPNext'in tembel otomatik-oluşturması tetiklenene veya bir admin Desk üzerinden elle oluşturana kadar sıfır Fiscal Year kaydı olabilir.

**Onay Kademeleri** (`stabler/api/approvals.py` + `_approval_rules.py`): `Payment Entry`, `Journal Entry`, `Purchase Order`, `Purchase Invoice` için; her biri kendi etkinleştirme anahtarı + taban-para-birimi eşiğine sahip; Purchase Invoice ayrıca **çok kademeli** eşik listesi destekliyor. Onay gereken belge Draft'ta kalır, `Stabler Approval Request` oluşur; onaylayan (`Accounts Manager`/`System Manager`/`Stabler Admin`, kendi-kendini-onaylama engellenir) `money/Approvals.vue`'dan onaylar. `before_submit` hook'larıyla **her yoldan** (SPA, Desk, script) zorlanıyor — yalnız SPA'ya özgü değil.

**Görevler Ayrılığı (SoD)** (`_sod_rules.py`, `sod_enforce.py`): (1) **Danışma niteliğinde** rol-çatışması matrisi (4 zehirli rol-çifti), `admin/AccessReview.vue`'da salt-okunur gösterilir, hiçbir şeyi engellemez. (2) **Aktör-çatışması zorlaması** — aynı kullanıcının aynı belgeyi oluşturup onaylamasını vb. engeller; **varsayılan olarak kapalı** (`Stabler Settings.enable_sod_enforcement`).

**`desk_write_guard.py`:** yalnız Sales Invoice ve Sales Order için REST-API sertleştirmesi (Desk-dışı yazma yollarını engeller). Genel Desk-UI engeli ayrı bir dosyada (`desk_gate.py`, `/app`/`/desk`'i admin-olmayanlara tamamen kapatıyor).

**Dönem Kapama — iki bağımsız, entegre olmayan mekanizma:**
1. Stabler'ın kendi `period_close.py`/`_period_close.py` — tek admin-ayarlanabilir kapama tarihi + geçersiz kılma rol listesi, SI/PI/PE/JE/Stock Entry'de `validate` hook'larıyla zorlanıyor. **Varsayılan kapalı, ve hiçbir SPA UI'ı yok** — hiçbir Vue sayfası `get_period_status`/`set_close_date` çağırmıyor. Backend tamamen hazır, admin için görünmez.
2. `/admin/posting-window` (`PostingWindow.vue`) — ERPNext'in native geriye-tarihleme dondurma penceresi (`Stock Settings.stock_frozen_upto_days`, `Accounts Settings.acc_frozen_upto`) — kayan pencere, sabit kapama tarihinden **farklı, daha kaba** bir mekanizma.

**Döviz kuru:** CBU entegrasyonu tüm para-birimi işlemlerine (JE, Payment, Transfer, Expense, PI, FX Revaluation, Hesap Defteri) yayılmış; sabit taban USD→UZS>1000, ±%20 tolerans bandı ve tazelik penceresi.

### Boşluk tablosu

| Özellik | MSAERP | Stabler | Durum | Plan (WP/Faz) | Tahmini zaman |
|---|---|---|---|---|---|
| Hesap Planı (CoA) yönetimi | ✅ canlı, tam ERPNext passthrough (ağaç, düzenle, sil, defter) | ✅ ERPNext native, Company oluştururken otomatik "Standard" CoA | ✅ Yapıldı | — | — |
| Fiscal Year / Accounting Period oluşturma | ⚠️ model var ama **UI yok**, yalnız Django-admin/shell ile (belgelenmiş prod olayı) | ❌ oluşturma kodu hiç yok — ERPNext'in tembel otomatiğine bağımlı | ❌ Yok — karar gerekli, **risk: ilk kurulumda sıfır Fiscal Year** | Faz 0/1'de netleştirilmeli — plan §3.2 "FiscalYear/AccountingPeriod → Fiscal Year + stabler period_close (tek rejim)" diyor ama oluşturma akışı belirtilmemiş | Faz 1 (kurulum kontrol listesine eklenmeli) |
| Dönem kapama zorlaması | ⚠️ model+servis var (`PeriodService.validate_transaction_date` canlı) ama **`PeriodClosingService` tamamen kırık/ölü**, gerçek kapanış kaydı hiç yok | ✅ backend tam (`period_close.py`) ama **varsayılan kapalı, SPA UI yok** | ⚠️ Kısmen — Stabler'ın backend'i MSAERP'in kırık servisinden daha sağlam ama kullanılabilir değil | Plan §3.2: "tek close rejimi: stabler period_close (native Accounting Period kullanılmaz)" — karar zaten verilmiş, **yalnız SPA UI ve varsayılan-açık kararı eksik** | Faz 1-2 (UI eklenmesi) |
| Döviz kuru — CBU senkronu | ✅ canlı, 2 yönetim komutu (backfill+günlük), ama **repo içinde zamanlayıcı yok** (cron dışarıda) | ✅ canlı, CBU scheduler zaten Stabler'da var ("hazır/yeniden kullan" listesinde, plan §1.2) | ✅ Stabler zaten üstün (gerçek scheduler var) | — | — |
| Döviz kuru manuel override | ⚠️ yok (yalnız işlem-bazlı override, kalıcı tabloyu etkilemiyor) | ⚠️ benzer düzeyde (per-transaction override, "AUTO" rozetiyle işaretli) | ✅ Paritede (ikisi de aynı sınırlamayı taşıyor) | — | — |
| Desteklenen para birimleri | UZS/USD/RUB/EUR/IRR/TRY | Stabler geneli çok-para-birimi altyapısı var (agent bulgusunda spesifik liste doğrulanmadı — ek kontrol gerekir) | 🔍 Doğrulama gerekli | — | Faz 0/1 kontrol listesi |
| Onay kademeleri (finansal belgeler) | ❌ MSAERP'de yok | ✅ canlı, çok kademeli | ✅ Stabler MSAERP'i geçiyor | — | — |
| Görevler Ayrılığı (SoD) | ❌ MSAERP'de yok | ✅ backend var (2 katman), varsayılan kapalı | ✅ Stabler MSAERP'i geçiyor (etkinleştirilmesi kararı gerekli) | Faz 4 ("approval/SoD... Playwright smoke") | Faz 4 |

### Notlar/kararlar

1. **En kritik netleştirme: Fiscal Year/Accounting Period oluşturma akışı.** MSAERP'in kendi deneyimi ("prod olayı: dönem bulunamadı, shell ile manuel oluşturuldu") Stabler'a aynen taşınabilir bir risk — plan tek-rejim kararını (`stabler period_close`) veriyor ama *ERPNext Fiscal Year kayıtlarının kim/ne zaman oluşturacağı* belirtilmemiş. Bu, kurulum runbook'una (Faz 0/1) somut bir adım olarak eklenmeli: "Company provisioning sırasında N yıl ileri/geri Fiscal Year otomatik oluştur" gibi.
2. **`stabler period_close` özelliği "var ama kullanılamaz" durumda** — backend tamamen yazılmış (hook'lar, ayarlar, rol listesi) ama SPA'da hiçbir ekran çağırmıyor ve varsayılan kapalı. Bu, MSAERP'in kendi `PeriodClosingService`'inin tam tersi bir problem: MSAERP'te *kod kırık*, Stabler'da *kod sağlam ama erişilemez*. Faz 1-2'de küçük bir SPA ekranı (`admin/PeriodClose.vue` gibi) eklemek görece düşük efor, yüksek değer bir iş kalemi.
3. Hesap Planı ve döviz kuru altyapısında Stabler zaten MSAERP'i geçiyor (gerçek CBU scheduler'ı var, MSAERP'de yalnız repo-dışı cron öneriliyor) — bu alanda ek iş gerekmiyor, yalnızca hedef tenant'ta (`msa.erpstable.com`) doğrulama gerekiyor.

---

## Genel Özet — Bu Dört Bölümdeki En Büyük Boşluklar (Öncelik Sırasıyla)

1. **Müşteri ebeveyn/alt hiyerarşisi (Customer Center hierarchy mode)** — Stabler'da sıfır kod, MSAERP'de kısmen çalışan (ama kırık taşıma mantığıyla) bir örnek var. Plan zaten Faz 2'ye (Ağustos 2026) koymuş — bu denetim bu zamanlamayı doğruluyor ve MSAERP'in "temiz başlangıç" fırsatını (Faz 0 bulgusu: SI'larda hiyerarşi hiç kullanılmamış) teyit ediyor.
2. **Kredi limiti alanı + zorlaması + override** — Stabler'da hiç yok; MSAERP'de de yarım (UI'sız). K2 kararına göre sıfırdan, ebeveyn-seviyesinde inşa edilmeli.
3. **Sales/Payment Excel toplu içe aktarma** — MSAERP'de olgun, aktif kullanılan iki özellik (satış + tahsilat); Stabler'da hiçbiri yok. Kalıcı ihtiyaç mı yoksa yalnız ETL-dönemi ihtiyacı mı olduğu sahip kararı gerektiriyor.
4. **MSAERP-formatı banka ekstresi (CSV) desteği** — Stabler yalnız 1C formatını destekliyor; plan bunu zaten iş kalemi olarak işaretlemiş, doğrulama gerekiyor.
5. **Fiscal Year/Accounting Period ilk-kurulum oluşturma akışı** — her iki tarafta da net bir "kim oluşturacak" cevabı yok; MSAERP'in prod olayı ders niteliğinde, Stabler runbook'una eklenmeli.
6. **`stabler period_close` için SPA ekranı** — backend hazır, arayüz yok; düşük efor/yüksek değer hızlı kazanım.
7. **Delivery Note / fiziksel sevkiyat belgesi kararı** — Stabler'ın "SI = stok hareketi" modeli MSAERP'in imza/fotoğraf/parti-bazlı WMS akışını karşılamıyor; depo ekibinin gerçek ihtiyacı netleştirilmeli (Waybill.vue kısmi çözüm sağlıyor).

Öte yandan bu denetim, migration planının "yeniden konumlandırma, yeniden yazım değil" tezini güçlü şekilde doğruluyor: MSAERP'in Sales/Finans/Banka katmanlarının önemli bir kısmı (SalesOrder CRUD, DeliveryNote, VendorBill detay sayfası, Bank Reconciliation UI, Cash Management, Expense onay akışı) **zaten canlı olarak çalışmıyor** — Stabler bunların çoğunu daha tutarlı, daha modern bir mimariyle (tek FEFO motoru, sunucu-taraflı export yeniden hesaplama, çok kademeli onay, SoD, 1C banka mutabakatı, FX revalüasyon) **zaten karşılıyor veya geçiyor**. Gerçek iş, MSAERP'in kod tabanını birebir kopyalamak değil, yukarıdaki 7 maddedeki **bilinçli tasarım kararlarını** tamamlamaktır.
