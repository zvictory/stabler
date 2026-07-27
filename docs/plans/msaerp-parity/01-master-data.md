# MSAERP → Stabler İnce Taneli Özellik Paritesi Denetimi — Bölüm 1: Ana Veri (Master Data)

**Tarih:** 2026-07-10
**Kapsam:** Dashboard(lar), Vendor + Vendor Kategorileri, Ürünler (Product/Item), Depolar & Stok Transferi.
**Yöntem:** Her iki kod tabanı (`/Users/zafar/Downloads/msaerp` — Django, ve `/Users/zafar/frappe-bench-local/apps/stabler` — Frappe/Vue) doğrudan dosya okunarak incelendi; Stabler tarafında commit edilmemiş WP1-3 (imports) çalışması da working tree üzerinden dahil edildi. Referans: `docs/plans/2026-07-09-msaerp-to-stabler-migration-plan.md` (§3.1 eşleme tablosu, §9 faz takvimi: Faz 0 tamam, Faz 1 doctype'lar WP1-3 ile ~%60, Faz 2 SPA ≈ 5 hafta / Ağustos 2026, Faz 3 ETL ≈ Eylül, Faz 4-5 test+cutover ≈ Ekim-Kasım 2026).
**Durum kodları:** ✅ Yapıldı · 🔜 Planda (plan dokümanında karşılığı var, henüz inşa edilmedi) · ❌ Yok — karar gerekli (planda da yok, sahip kararı lazım).

---

## 1. Dashboard(lar)

### 1.1 MSAERP'de bugün

MSAERP'te tek bir "dashboard" değil, **rol bazlı yönlendirilen 8 ayrı dashboard/rapor-hub ekranı** var. Hepsi sunucu tarafında render ediliyor (Django template), grafikler **ApexCharts 3.49.0** (CDN) ile çiziliyor — view'lardaki "Chart.js" yorum satırları yanıltıcı, gerçekte Chart.js hiç yüklenmiyor.

**Şablon çözümleme tuzağı:** `templates/proforma/dashboard.html.shadowed` ve `.original_broken_bak` gibi dosyalar devre dışı bırakılmış eski sürümler; Django `TEMPLATES.DIRS` önce `templates/` dizinine bakıp orada bulamayınca `APP_DIRS` ile `proforma_app/templates/proforma/*.html` altındaki gerçek aktif dosyalara düşüyor. `templates/proforma/dashboard_overview.html` hiçbir yerden referans edilmiyor — ölü kod.

**a) Ana Dashboard — `dashboard_view` (`/`, route adı `dashboard`)**
Kullanıcının `userprofile.role.department.code` alanına göre 3 farklı şablona yönlendiriyor:
- **`SALES` departmanı → `dashboard_sales.html`** (Satış Dashboard'u): 6 KPI kartı (Ciro, Tahsil Edilen/Toplam Ödenen, Alacak, Bugünkü satış, Dönem fatura sayısı+ortalama, Aktif müşteri sayısı) — hepsi **UZS** (`сўм`) formatında; Ciro Dinamiği alan grafiği; En Çok Satan Müşteriler + Ürünler yatay çubuk grafikleri; Son Faturalar listesi + Alacak Yaşlandırması (5 kova özet + müşteri bazlı tablo); Vadesi Geçmiş Faturalar ızgarası; Hızlı Aksiyonlar çubuğu (Yeni Fatura, Ödeme Al, Satış Merkezi, Raporlar); sayfada gizli bir AI-chat context JSON bloğu (KPI/top-customer/top-product verisini AI asistanına besliyor).
- **`PROC` (satın alma) departmanı → `dashboard_procurement.html`** (Satın Alma Dashboard'u): Hızlı Aksiyonlar (Yeni PI, Yeni CI, Yeni Konteyner, Yeni Tır, Vendorlar, Ürünler); 3 metrik kart (Varış sayısı, Vadesi gelen ödeme $, Banka ödemeleri $); "7 gün içinde İran'a varacaklar" tablosu (CI#, Vendor, Konteynerler, ETA, Kalan gün, Tutar); "Tüm gelen sevkiyatlar" tablosu; Ödeme Hatırlatmaları (koşullu); Parti Son Kullanma özet kartları. **Bilinen buglar:** Ödeme Hatırlatmaları bloğu context'te olmayan alan adları (`reminder.ci_number` vs gerçek key `ci`) okuduğu için sessizce boş render ediyor; "Tüm gelen sevkiyatlar" tablosu da benzer şekilde `item.agreed_total` yerine gerçek key `agreed_value` olduğu için boş kalıyor.
- **Diğer tüm roller (Muhasebe, Yönetim, Depo, profilsiz) → `dashboard.html`** (Yönetici Dashboard'u): 7 KPI kartı (Toplam Gelir, Toplam Gider, Net Kâr [işarete göre kırmızı/yeşil], Alacak, Borç, Banka Bakiyesi USD, Aktif Müşteri, Bekleyen Onaylar); 3 ApexCharts grafiği (Gelir Trendi 12 ay alan grafiği, Kategoriye Göre Giderler donut, İlk 5 Müşteri yatay çubuk); Para Birimine Göre Banka Bakiyeleri tablosu; "Yakında Varacaklar — Ödeme Planlaması" bölümü (7 gün içinde ödeme varsa uyarı banner'ı, 3-4 istatistik kartı, tam tablo: CI#, Konteynerler, Vendor, ETD/ETA aciliyet renklendirmeli, Değer, %70 Ödeme durumu, Nakit farkı, Durum rozeti, toplam satırı); Ödeme Uyarıları (kritik + yaklaşan ödemeler partial'ları); Bekleyen Onaylarım / Ödenmemiş Giderler iki sütun; Son Aktivite (Son Müşteri Faturaları, Son Giderler, Vadesi Geçmiş Faturalar); Parti Son Kullanma Uyarıları (4 sayaç kartı + Bootstrap sekmeler — 90-gün sekmesi eksik, sayaç kartı var ama panel yok).

Periyot filtresi (`?period=`): `this_month/last_3_months/this_year/last_12_months(varsayılan)/custom`; `dashboard.html`'in açılır menüsünde sadece ilk 3 seçenek var, `last_12_months`/`custom` yalnız URL parametresiyle erişilebiliyor (UI'da eksik). "Yenile" butonu = tam sayfa `location.reload()`, otomatik AJAX yenileme yok.

**b) Raporlar Merkezi — `reports_dashboard` (`/reports/`)**
Filtre/grafik yok — 3 kategoriye (Finansal Raporlar 10 link, Satış Analitiği 6 link, Envanter Raporları 2 link) ayrılmış statik kart ızgarası + 3 "Hızlı İstatistik" kartı. **i18n hatası:** rapor adları/açıklamaları view'da sadece İngilizce + `_ru` suffix olarak var; şablon `{{ report.name_ru }}` hardcoded çağırdığı için **uz/tr/en dillerinde de her zaman Rusça metin görünüyor** — projenin kendi i18n kuralını ihlal ediyor.

**c) Operasyon Dashboard'u — `operations_dashboard` (`/dashboard/operations/`)**
Sidebar'da linklenmiyor, sadece URL'i bilenler erişebiliyor. 4 pipeline kartı (Aktif PI sayısı+toplam, Yolda CI, Limandaki Konteynerler, Varan Konteynerler); 3 ödeme-sağlığı kartı (7 gün içinde vade, Gecikmiş, Bu ay ödenen); 2 ApexCharts grafiği (İthalat Hattı huni grafiği, Aylık Ödeme Trendi); Uyarılar tablosu (Tip rozeti: Gecikmiş/Yakında/Sync Hatası, detay, vade, tutar); Hızlı Aksiyonlar (Yeni PI, Yeni CI, Sync Çalıştır).

**d) Ayarlar Dashboard'u — `settings_dashboard` (`/settings/`, `@management_required`)**
Salt link hub'ı: 8 kart (Sidebar Menü Düzenleyici, Kullanıcı Yönetimi, Rol & Yetkiler, Aktivite Logları, Sync Monitörü, Veri Uzlaştırma, Ödeme Hesapları, Muhasebe Sync'i); alt kısımda statik RBAC bilgi paneli (Departman=5, Modül=15, Aksiyon=5 hardcoded + dinamik Rol/Kullanıcı sayıları) ve VCEDA (View/Create/Edit/Delete/Approve) legend.

**e) ERPNext Sync Dashboard'u — `erpnext_sync_dashboard` (`/settings/sync/`, `@management_required`)**
4 özet sayaç kartı; 4 aksiyon kartı — her biri açıklama + canlı bekleyen-sayı satırı + "Çalıştır"/"Kuru Çalıştır" butonları, AJAX `fetch()` ile POST (`{action, dry_run}`): **Custom Field Kurulumu** (bootstrap), **Proforma Faturaları Taşı** (migrate-pis), **Ticari Faturaları Taşı** (migrate-cis, varan CI'lar için PI'ları otomatik onaylıyor), **Avansları Uzlaştır** (reconcile). Sonuçlar inline spinner→check/x ikonuyla, güvenli DOM API'leriyle render ediliyor (XSS riski yok).

**f) Uzlaştırma Dashboard'u — `reconciliation_dashboard` (`/settings/reconciliation/`)**
İlk yüklemede boş; 3 sekme (Vendorlar / Avans Ödemeleri / Satın Alma Faturaları), her birinde "Şimdi Doğrula" butonu → AJAX ile `erpnext_integration.reconciliation` modülünü çağırıp `{entity, local_value, erpnext_value, difference, status}` satırları döndürüyor (`status ∈ MATCH/MISMATCH/MISSING_LOCAL/MISSING_ERPNEXT`, renk kodlu rozetler). Sonuç çıkınca "CSV Dışa Aktar" butonu beliriyor.

**g) Lojistik Dashboard'u — `LogisticsDashboardView` (`/ci/logistics/`)**
`CommercialInvoice` üzerinde `ListView`, `paginate_by=20`. Filtreler: durum, vendor (yalnız SUPPLIER tipi), arama (CI#/konteyner#/tır# icontains). Tablo: CI Numarası+tarih, Vendor, Konteynerler (rozet sayısı + ilk 3 numara + "daha fazla"), Tırlar (rozet sayısı + Bekleyen/Yolda/Varan dökümü), GRN Durumu (rozet), Aksiyonlar. Klasik sayfalama.

**h) Landed Cost Dashboard'u — `LandedCostDashboardView` (`/ci/landed-costs/`)**
`CommercialInvoice` üzerinde `ListView`, `paginate_by=20`. CI başına `total_landed_cost = docs_total + Σexpenses + uzb_vat_usd` hesaplanıyor. Özet kartlar (tüm filtrelenmiş sorgu üzerinden, sadece sayfa değil): Toplam CI, Toplam Landed Cost, kg başı ortalama maliyet, Sync Oranı %. Tablo: CI Numarası, Vendor, Konteyner sayısı, Ürün Maliyeti, Ekstra Maliyetler, kg başı maliyet, Giderler (rozet sayısı), PR Durumu rozeti, LCV Durumu rozeti.

**Gerçek zamanlılık:** Hiçbir dashboard otomatik yenilenmiyor (Vendor Center hariç — 30sn polling, bkz. Bölüm 2). "Yenile" = tam sayfa reload. Yalnız Sync ve Uzlaştırma dashboard'larının Run/Verify butonları kullanıcı tetiklemeli AJAX.

### 1.2 Stabler'da bugün

**a) Ana `/dashboard` — `Dashboard.vue` (commit edilmiş)**
Sanal modül (`_VIRTUAL_MODULE_KEYS = ("dashboard",)`), şirket bazlı toggle yok, `_MODULE_ROLES["dashboard"] = ["All"]` — her giriş yapan kullanıcı görüyor; SPA'nın varsayılan iniş sayfası. İçerik: 4 KPI kartı (Kasa, Alacak, Borç, Aylık Ciro + trend %); "Gelir vs Gider (12 ay)" alan grafiği + "Nakit akışı" çubuk grafiği (`ApexChart.vue`); "Son aktivite" akışı (son SI/PI/Payment Entry/Journal Entry — durum rozeti **inline renk sınıfıyla**, `getStatusBadgeClass` KULLANMIYOR, merkezi-durum kuralına aykırı); "Düşük stok" listesi (`low_stock_alerts` API'si); ilk-kullanım boş durumu (Müşteri ekle / Satış kaydet / Açılış bakiyesi gir hızlı linkleri — Desk'e yönlendirme yok, uyumlu); çoklu para birimi duyarlı (dönüştürme yok, uyumlu). Para/tarih formatlaması (`formatMoney`, `formatDateTime`) kurallara uygun. Yükleme durumunda `SkeletonRows.vue` DEĞİL, Tabler `placeholder-glow` kullanılıyor.

Backend `api/dashboard.py`: `summary`, `revenue_trend`, `recent_activity` — hepsi şirket-izole (`_assert_company_scope`), 300sn Redis cache, para birimi bazlı (baz para birimine çevrim yok — uyumlu).

**b) Modül-bazlı mini-dashboard'lar (ana dashboard değil):**
- Service modülü kendi `Dashboard.vue`'suna sahip (bilet sayıları, kendi `STATUS_COLORS` map'i — yine merkezi-durum kuralına aykırı).
- `api/purchasing.py::payables_cockpit` — Suppliers sayfasının "cockpit" görünümü (toplam borç, bugün ödenen, 8 haftalık trend sparkline, ilk 10 alacaklı) — bağımsız route değil, Suppliers sayfasına gömülü bir AP mini-dashboard'u.
- `hr_overview.py` + çeşitli `*Home.vue` modül-giriş kabukları (PurchasingHome, InventoryHome, MoneyHome, SFAHome, CrmHome) — sekme konteynerleri, KPI dashboard'u değil.

**c) ERPNext native Desk dashboard'ları**
Frappe/ERPNext'in yerleşik Desk çalışma alanları (Accounting/Stock/Selling dashboard'ları, `/app/...`) fiziksel olarak hâlâ mevcut ama CLAUDE.md'nin "Desk'e asla yönlendirme yok" kuralı gereği Stabler bunlara asla link vermiyor. **Sonuç: Desk'in yerleşik KPI kartları/heatmap/Chart-of-Accounts treemap'leri gibi özellikler kullanıcıya tamamen kapalı** — sadece gizli değil, gerçekten erişilemez. Stabler'ın kendi Dashboard.vue + modül cockpit'leri bunların yerini tam dolduramıyor.

**d) İthalat (Imports) Dashboard'u — sadece iskelet**
`stabler/public/js/pages/imports/ImportsDashboard.vue` zaten commit edilmiş (WP1-3'ün parçası değil), route `/imports`, modül erişimi `_MODULE_ROLES["imports"]` ile rol-kilitli ve `enable_imports` şirket toggle'ıyla kapılı. **İçerik: tamamen placeholder** — tek bir `EmptyState` kartı: *"The Imports workspace will be built out in the next work package."* KPI kartı, grafik, veri çağrısı YOK. WP1-3'ün commit edilmemiş çalışması (yeni doctype'lar + `imports_module/*`) yalnız backend'e dokunuyor — Vue sayfasına veya yeni API endpoint'ine hiç dokunmamış.

### 1.3 Boşluk tablosu

| Özellik | MSAERP | Stabler | Durum | Plan (WP/Faz) | Tahmini zaman |
|---|---|---|---|---|---|
| Ana KPI dashboard'u (Ciro/Gider/Kâr/Alacak/Borç/Banka) | Var, rol bazlı 3 varyant (Sales/Procurement/Executive) | Var, tek varyant, herkese açık | ✅ Yapıldı (temel), 🔜 rol-özel varyantlar planda değil | Faz 2 SPA'da genişletilebilir | — |
| Satış Dashboard'u (ciro dinamiği, top müşteri/ürün, AR yaşlandırma) | Var (`dashboard_sales.html`) | Kısmen — CRM/Sales modülünde ayrı sayfalarda dağınık (Aging.vue vb.) var ama tek ekran değil | 🔜 Planda değil, ayrı analiz gerekir | Faz 2 sonrası, kapsam dışı | Belirsiz |
| Satın Alma / İthalat Dashboard'u (varış takvimi, ödeme vade uyarıları, konteyner/tır özet) | Var (`dashboard_procurement.html`, buglu ama işlevsel) | Placeholder (EmptyState) | ❌ Yok — inşa edilecek | Faz 2, ImportsDashboard.vue | Faz 2 içinde ~1 hafta (5 haftalık SPA bütçesinin parçası) |
| Lojistik Dashboard'u (CI listesi + konteyner/tır/GRN durumu) | Var, filtre+arama+sayfalama | Yok (WP1-3 doctype'ları var ama SPA yok) | ❌ Yok | Faz 2, imports SPA'nın parçası olmalı | Faz 2 içinde |
| Landed Cost Dashboard'u (CI başına maliyet özeti, sync oranı) | Var | Yok (LCV backend akışı WP1-3'te var — draft LCV üretimi — ama izleme ekranı yok) | ❌ Yok | Faz 2, "LandedCostReview" sayfası planda (§5) | Faz 2 içinde |
| Raporlar Merkezi (statik link hub) | Var (i18n buglu) | Dağınık — her modülün kendi Reports sekmesi var, tek hub yok | 🔜 Kısmi eşdeğer var, merkezi hub yok | Değerlendirilmeli | — |
| ERPNext Sync Dashboard'u (bootstrap/migrate/reconcile butonları) | Var | Gereksiz — Stabler'da çift-veritabanı senkron katmanı yok (mimari kazanç, plan §0) | ✅ Mimari olarak gereksizleşiyor | — | — |
| Uzlaştırma (Reconciliation) Dashboard'u | Var (local vs ERPNext karşılaştırma) | Gereksiz — tek kaynak (ERPNext) olduğundan uzlaştırılacak ikinci sistem yok | ✅ Mimari olarak gereksizleşiyor | — | — |
| Operasyon Dashboard'u (pipeline+ödeme sağlığı, sidebar'da linksiz) | Var ama kullanılmıyor (orphan) | Yok | ❌ Değerlendirilmeli — muhtemelen ImportsDashboard'a birleşecek | Faz 2 | — |
| AI-chat context entegrasyonu (dashboard_sales.html gizli JSON bloğu) | Var (deneysel görünüyor) | Yok | ❌ Kapsam dışı — MSAERP'e özgü deneysel özellik | Kapsam dışı kabul | — |
| Düşük stok uyarısı widget'ı | Yok (dashboard'da yok, ayrı raporlarda var) | Var, ana dashboard'da widget olarak | ✅ Stabler MSAERP'i aşıyor | — | — |

### 1.4 Notlar/kararlar

1. MSAERP'nin rol-bazlı 3-varyant dashboard mimarisi Stabler'a taşınmayacaksa (tek ortak dashboard + modül-bazlı cockpit'ler yaklaşımı benimsenmişse) bu **bilinçli bir sadeleştirme** olarak dokümante edilmeli — sahip onayı gerekir, çünkü Procurement/Sales kullanıcıları MSAERP'te departmanlarına özel bir "giriş ekranı" alışkanlığı edinmiş olabilir.
2. Satın Alma/İthalat Dashboard'u en kritik boşluk: MSAERP'in en aktif kullanılan operasyonel ekranlarından biri (varış takvimi + ödeme vade uyarıları), Stabler'da salt placeholder. Faz 2'nin ilk haftalarında önceliklendirilmeli.
3. `dashboard_procurement.html`'deki iki bug (Ödeme Hatırlatmaları ve "Tüm gelen sevkiyatlar" tablosunun context key uyuşmazlığı nedeniyle boş render etmesi) ETL/parity analizine dahil edilmemeli — bunlar MSAERP'in kendi hataları, "parity" hedefi bu bug'ları da taşımak değil, düzeltilmiş halini üretmek olmalı.
4. Stabler'ın merkezi durum-rozet kuralı (`getStatusBadgeClass`) Dashboard.vue ve Service Dashboard'ta ihlal ediliyor — bu Faz 2 kapsamı dışında bile küçük bir refactor borcu, ayrıca not edilmeli.
5. ERPNext Sync ve Uzlaştırma dashboard'larının "gereksizleşmesi" migration planının ana tezi (§0: "çift-veritabanı senkron katmanı komple ölür") — bu iki ekranın parity listesinde "yapılacak" değil "artık gerek yok" olarak işaretlenmesi kritik, aksi halde yanlışlıkla backlog'a girebilir.

---

## 2. Vendor + Vendor Kategorileri

### 2.1 MSAERP'de bugün

**Kritik başlangıç notu — MSAERP'te bugün İKİ PARALEL ve eşzamanlı çalışan Vendor arayüzü var**, ikisi de sidebar'da: eski `/vendors/` CRUD ekranları (yerel model üzerinde, sert silme, engelsiz) ve yeni `/vendor-center/` (Alpine.js SPA, ERPNext `Supplier` + yerel `Vendor`'u birleştiren, yumuşak silme + engelleyici kontroller, senkron ERPNext push). Bu ikilik parity denetiminde önemli — Stabler'a taşınacak "gerçek" davranış muhtemelen Vendor Center'ınki.

**a) `Vendor` modeli** (`proforma_app/models.py`) alanları: `name`* (200), `code`* (10, unique, uppercase), `vendor_type` (SUPPLIER/SHIPPING/TRANSPORTER/CUSTOMS_BROKER/WAREHOUSE/OTHER, varsayılan SUPPLIER), `contact_person`, `email`, `phone`, `address` (metin), `country` (varsayılan "India"), banka bilgileri (`bank_name`, `bank_account_number`, `bank_swift_code`, `bank_iban`, `bank_address`, `beneficiary_name`), `payment_terms` (NET_15/30/60/90/COD/PREPAID), `credit_limit` (Decimal), `discount_percentage` (0-100), `vendor_group` (serbest metin), `currency` (USD/UZS/EUR/IRR/INR/TRY, varsayılan USD), `is_active`, `website`, `tax_id`, `notes`, `erpnext_name` (sync anahtarı, unique). Hesaplanan: `total_balance_due`, `total_pending_amount`, `get_aging_analysis()` (30/60/90+ kova).

**b) `VendorCategory` / `VendorCategoryItem`** — Bu "Vendor Kategorileri" bir **ürün kategorisi DEĞİL**, belirli bir vendor'a özel satın alma şablonu: "Bu tedarikçiden hangi ürünler, konteyner başına kaç kutu geliyor" tanımı. `VendorCategory`: `vendor` FK (CASCADE), `name`, `display_name`, `description`, `is_active`; `unique_together=(vendor,name)`. `VendorCategoryItem`: `category` FK, `product` FK, `boxes_per_container`; `unique_together=(category,product)`. PI oluştururken "kategori doldur" özelliği için kullanılıyor (`api/vendor-categories/` PI satır formunu otomatik dolduruyor).

**c) Vendor Listesi — `VendorListView` (`/vendors/`)**
Filtreler: `vendor_type` sekmeleri (ALL/SUPPLIER/SHIPPING/TRANSPORTER/CUSTOMS_BROKER/WAREHOUSE — Rusça-only etiketli, i18n ihlali), arama (kod|isim|iletişim kişisi icontains), sıralama (tip, isim), `paginate_by=20`. Sütunlar: #, Kod, Vendor (isim/link/Senkron rozeti/ülke/iletişim/tip istatistikleri), Tip rozeti, İşlemler (sayı+bekleyen), Bakiye Borcu (veya "Ödendi" rozeti), Aksiyonlar (görüntüle/düzenle ikonları). **Bilinen kritik bug: bu sayfa şu anda kırık** — `get_context_data` silinmiş `VendorTransaction` modelini import ediyor, her istek `ImportError` veriyor, ama sidebar'da hâlâ linkli.

**d) Vendor Oluştur/Düzenle — `VendorForm`**
Bölümler: **Temel Bilgiler** (Kod*, İsim*, Tip, Ülke, Aktif; senkronsa salt-okunur ERPNext-sync banner'ı) · **Finansal Kontroller** (Ödeme Vadesi, Para Birimi, Kredi Limiti USD, İndirim %, Vendor Grubu, Vergi No) · **İletişim Bilgileri** (İletişim Kişisi, E-posta, Telefon, Website, Adres) · **Banka Bilgileri** (Alıcı Adı, Banka Adı, Hesap No, SWIFT/BIC, IBAN, Banka Şube Adresi) · **Ek Bilgiler** (Vergi No — mükerrer alan, + Dahili Notlar). Yalnız kod/isim zorunlu. Dosya eki yok. Kayıt sonrası listeye dönüyor (detay sayfasına değil).

**e) Vendor Detay — `VendorDetailView`**
Sekmeler `vendor_type`'a göre değişiyor: SUPPLIER için PI/CI/Konteyner listeleri+istatistikler; SHIPPING için sevk edilen konteyner istatistikleri; TRANSPORTER için tır/konteyner-navlun istatistikleri (`VendorBill.filter(bill_type="TRANSPORT")` toplamları). Ortak sekmeler: Genel Bakış, Proforma Faturalar, Ticari Faturalar, Konteynerler, Vendor Faturaları, Yaşlandırma Analizi (transporter için: Tırlar, Konteyner Navlunu, İşlemler, Vendor Faturaları, Yaşlandırma). Header aksiyonları: Geri, **Fatura Oluştur**, **Vendor Düzenle**. Silme yok burada.

**f) Vendor Merkezi — `VendorCenterView` (`/vendor-center/`)** — Alpine.js SPA, tüm veri AJAX ile, eski CRUD view'ları tamamen bypass ediyor:
- Liste: ERPNext `Supplier` + yerel `Vendor` birleşimi (ERPNext erişilemezse yerel-only fallback); arama/sıralama; tip pilleri (Tümü/Tedarikçiler/Nakliye/Nakliyeciler/Aracılar); **30 saniyede bir otomatik yenileme (polling)**.
- Sağ panel: header + ERPNext-türevli 4 istatistik kartı + sekme şeridi (`vendor_center_tab_partial` ile parçalı yükleniyor): **Genel Bakış** (son yerel PI/CI'lar, son 5 ERPNext PI, son 5 ERPNext Payment Entry, Vendor Bilgisi kartı), **Satın Alma Faturaları** (4 istatistik kartı + tam ERPNext PI tablosu, 200 satıra kadar, Taslak/Ödendi/Ödenmedi/Gecikmiş/İptal rozetleri, ERPNext-only fallback'siz), **Avans Ödemeleri** (yerel `AdvancePayment`/`AdvanceAllocation`, 4 istatistik kartı, durum filtresi, genişletilebilir satırlar), **İthalat Belgeleri** (yerel PI+CI tam listesi).
- Oluşturma: kod otomatik üretimi `VND-NNNN`, yerel kayıt + ERPNext `Supplier` push (409 çakışmasında isimle eşleştirme kurtarma).
- Silme: **yumuşak silme** (`is_active=False`), ERPNext'te açık PI/Payment Entry veya yerelde aktif PI/CI varsa **engelleniyor** (HTTP 409 + engel listesi) — legacy `/vendors/`'daki sert silmenin aksine.

**g) Vendor Kategorisi ekranları**
`vendor_category_list.html`: vendor başına kart, her kartta tablo (Ad, Görünen Ad, Ürün Sayısı, Aktif/Pasif rozeti, Düzenle/Sil). `vendor_category_form.html`: Kategori Detayları + dinamik Ürün formset (JS satır klonlama).

**h) Vendor AP Raporu — `VendorAPReportView`**
Sadece SUPPLIER tipi, iptal olmayan PI'lar. Sütunlar: Tedarikçi (genişletilebilir), PI Toplamı, CI Toplamı, Avans Ödenen, %70 Ödenen, Toplam Ödenen, Kalan (+ilerleme çubuğu). Genişletince PI/CI/avans satır detayı. 6 özet kart + toplam satırı + yazdır butonu.

**i) Otomasyonlar / ERPNext sync**
`post_save` sinyali (`auto_push_vendor_to_erpnext`): her `Vendor.save()`'de (aktifse) `django_q` async görevi (`push_vendor`) kuyruğa alınıyor — yani **legacy `/vendors/` formları da ERPNext'e push ediyor**, ama asenkron ve kullanıcıya geri bildirimsiz; Vendor Center kendi endpoint'leri ise **senkron** push yapıyor. Alan haritası: `VENDOR_TO_SUPPLIER_MAP` (name→supplier_name, vendor_group→supplier_group, currency→default_currency, tax_id, email→email_id, phone→mobile_no, country, website; varsayılan supplier_group="Meat Suppliers", supplier_type her zaman "Company" — **`vendor_type` ayrımı ERPNext tarafında kayboluyor**). Yerel GL kaydı yok (kural uyumlu) — bakiyeler yerel `VendorBill` veya canlı ERPNext PI verisinden.

**j) Bilinen hata/ölü kod listesi (denetim için önemli — bunlar "parity hedefi" değil):**
1. `/vendors/` bugün kırık (`ImportError`).
2. `vendor.transactions` ölü ilişki, sessizce boş render ediyor.
3. Vendor Payment akışı tamamen ölü (`_RemovedView` → 404), 6 orphan template hâlâ diskte.
4. Legacy listede `'TRUCKING'` kontrolü var ama model choice'ı `TRANSPORTER` — nakliyeci rozetleri hiç render olmuyor.
5. `vendor_create_bill`'in `pk` parametresi kullanılmıyor — "Fatura Oluştur" butonundan vendor otomatik doldurulmuyor.
6. İki bağımsız, eşzamanlı canlı Vendor UI'ı (yukarıda not edildi).
7. `vendor_confirm_delete.html` tamamen çevrilmemiş (i18n ihlali).

### 2.2 Stabler'da bugün

**a) SPA sayfası — `Suppliers.vue`** (`/purchasing/suppliers`, commit edilmiş, WP1-3 dışı), master-detail split layout.

**Liste (sol panel):** Elle yazılmış arama kutusu, `⌘K` suffix'i doğru (satır 606) — **ancak `ListToolbar.vue` KULLANMIYOR** (PurchaseOrders/Invoices/Receipts sayfalarının aksine) — CLAUDE.md ihlali. Filtreler: Tedarikçi Grubu (client-side, yüklenen tedarikçilerden türetilmiş, ayrı bir "grup listesi" fetch'i değil), "Sadece bakiyesi olanlar" checkbox (sunucu taraflı). Sıralama: İsim/Bakiye, tıklanabilir kolon başlıkları. Tablo `table-no-stripe` (bilinçli, "customers-redesign" deseniyle tutarlı). **Yükleme durumu düz spinner — `SkeletonRows.vue` YOK**, "boşlukta spinner gösterme" kuralını ihlal ediyor. Satır: avatar, isim+ID, bakiye (kırmızı/yeşil/gri inline mantık — kabul edilebilir çünkü durum rozeti değil bakiye rengi). Alt bilgi: toplam borç. Toplu aksiyon yok.

**Cockpit görünümü (tedarikçi seçili değilken)** — `payables_cockpit`: Toplam Borç kartı, Bugün Ödenen kartı, "8 Haftalık Borç Trendi" sparkline, "İlk 10 Alacaklı" listesi (tıklanınca o tedarikçiyi seçiyor).

**Detay görünümü (tedarikçi seçiliyken):**
Header: avatar, isim+ID, **Düzenle** ve **Ödeme** butonları (ikisi de `btn-outline-secondary` — bu bölgede `.btn-primary` yok, kurala uygun). KPI şeridi: Bakiye (`BalanceChip`), Gecikmiş tutar, Yaşam Boyu Alışveriş, Son Ödeme. Sekmeler: **Defter** (varsayılan), **Siparişler** (rozet=sayı), **Faturalar** (rozet=sayı).
- Defter sekmesi: fiş tipi filtresi, `DateInput` başlangıç/bitiş (kurallara uygun), serbest metin fiş/not arama, sıralama, **Excel dışa aktar** butonu (`export_report_xlsx?report_key=supplier_ledger`). Tablo: Tarih (`formatDateTime`), Fiş (tıklanabilir → fiş çekmecesi), Borç, Alacak, koşan Bakiye — açılış/kapanış satırları dahil.
- Siparişler sekmesi: Satın Alma Siparişleri tablosu, Durum `getStatusBadgeClass` ile (kurala uygun).
- Faturalar sekmesi: Satın Alma Faturaları tablosu, Durum `getStatusBadgeClass` ile (kurala uygun).
- Fiş çekmecesi (offcanvas): PI/PO/Payment Entry/Journal Entry tipine özel detay, para `formatMoney`, tarih `formatDate`, durum `getStatusBadgeClass` — tam uyumlu.
- Ödeme modalı: `PartyPaymentModal` (Supplier parti tipi).

**Oluştur/Düzenle modalı:** Tedarikçi adı* (zorunlu), Tip (Şirket/Birey/Ortaklık), Vergi No, **Tedarikçi grubu** (`list_supplier_groups`'tan), Ülke, E-posta, Mobil, Varsayılan fiyat listesi (yalnız alım listeleri), Varsayılan para birimi. Para/tarih alanı yok (kredi limiti/açılış bakiyesi form'da yok — MoneyInput/DateInput kuralı bu formda uygulanamıyor). Footer: İptal (`btn-link`), Sil (`btn-outline-danger`, düzenleme modunda), Kaydet (`btn-primary`) — tam olarak bir primary, kurala uygun. Silme `useConfirm()` üzerinden geçiyor.

**b) Tedarikçi Grubu (kategori) yönetimi — KRİTİK BOŞLUK**
Kodda **hiçbir Tedarikçi Grubu SPA sayfası yok**. Yalnızca ERPNext native `Supplier Group` doctype'ı (`is_group=0` yaprak düğümler) düz bir seçim listesi olarak (`list_supplier_groups`, max 200) Suppliers formunda kullanılıyor. Grup oluşturma/yeniden adlandırma/hiyerarşi düzenleme **hiçbir yerden yapılamıyor** — "Desk'e yönlendirme yok" kuralı gereği Desk'e de gidilemiyor, yani bu **gerçek bir işlevsel boşluk**, sadece UX eksikliği değil.

**c) `api/purchasing.py` tedarikçi endpoint'leri (tam liste):** `list_suppliers`, `list_suppliers_with_balances` (GL-türevli canlı bakiye), `supplier_ledger`, `supplier_detail` (cockpit KPI'ları), `create_supplier`, `get_supplier`, `update_supplier`, `delete_supplier` (**sert silme** — MSAERP Vendor Center'ın yumuşak silme + engelleme mantığı burada YOK), `list_supplier_groups`, `ap_aging`, `payables_cockpit`, artı tüm PO/PI/PR yaşam döngüsü fonksiyonları (tedarikçi bazlı filtrelenmiş) ve `tender_quotations` (2-ülke kaynak politikası kontrolü ile tedarikçi karşılaştırma — MSAERP'te karşılığı yok, Stabler'ın fazlası).

**d) Native ERPNext `Supplier` alanları kullanımda:** `supplier_name`, `supplier_type`, `supplier_group`, `country`, `email_id`, `mobile_no`, `tax_id`, `default_currency`, `default_price_list`, `website`, `supplier_details`. Supplier üzerinde Stabler custom field'ı yok — WP1-3 patch'leri (v41/v42/v43) yalnız Purchase Order/Purchase Order Item'a ve bir Item kaydına dokunuyor, Supplier'a değil.

**e) WP1-3'ün Vendor/Supplier bağlantısı:** `Import Container`, `Import Truck` ("Trucking Company" alanı — Link→Supplier, yani **yurt dışı et tedarikçileri VE yerel nakliye firmaları aynı Supplier master'ında** tutuluyor, ayrı bir Vendor/Carrier doctype'ı yok), `GRN Checklist` — hepsi `supplier` Link alanı taşıyor. `Import PI Group`'ta ise supplier bağlantısı YOK (yalnız title/company/status/remarks) — vendor bağlantısı bir alt seviyede (Commercial Invoice, Purchase Order) yapılıyor.

**f) Vendor'a bağlı raporlar (SPA'dan, Desk'siz erişilebilir):** AP Aging (`/purchasing/aging`), Tedarikçi Defteri Excel export'u (Suppliers detay panelinden). Genel Finansal Raporlar sayfasında (Money modülü) kasıtlı olarak yer almıyor — Purchasing altında yaşıyorlar.

### 2.3 Boşluk tablosu

| Özellik | MSAERP | Stabler | Durum | Plan (WP/Faz) | Tahmini zaman |
|---|---|---|---|---|---|
| Tedarikçi ana kaydı (isim, tip, ülke, vergi no, para birimi) | Var (Vendor modeli, 20+ alan) | Var (Supplier native + Stabler formu) | ✅ Yapıldı | Faz 1 ETL: Vendor→Supplier | ETL'de |
| Tedarikçi tipi ayrımı (SUPPLIER/SHIPPING/TRANSPORTER/CUSTOMS_BROKER/WAREHOUSE) | Var, ama ERPNext push'ta kaybolan alan | Kısmen — `supplier_type` var ama Şirket/Birey/Ortaklık (farklı taksonomi) | ⚠️ Karar gerekli — taksonomi eşlemesi net değil | Faz 1/ETL kararı | Küçük — 1-2 gün analiz |
| Banka bilgileri (SWIFT/IBAN/beneficiary) | Var, Vendor formunda ayrı bölüm | ERPNext native `Bank Account` doctype üzerinden (Suppliers formunda görülmedi) | 🔜 Muhtemelen native karşılığı var, doğrulama gerekli | Faz 1 ETL | — |
| Ödeme vadesi (NET_15/30/60/90/COD/PREPAID) | Var | ERPNext native `Payment Terms Template` mevcut (standart özellik) | ✅ Native karşılık var | Faz 1 ETL alan eşleme | — |
| Kredi limiti + indirim % | Var | Suppliers formunda görünmedi (native `Supplier` alanı olarak var olabilir ama SPA'da yok) | ❌ Doğrulanmalı/eklenmeli | Faz 2 form genişletmesi | 1-2 gün |
| Vendor Kategorileri (vendor-özel ürün/kutu şablonu, PI'a otomatik doldurma) | Var, tam CRUD + PI formuna entegre | **Yok** — hiçbir karşılığı yok | ❌ Yok — karar gerekli | Plan §3.1'de bahsi yok; yeni custom doctype gerekebilir | Faz 1'e eklenmeli, ~3-5 gün (doctype+hook) + Faz 2 SPA entegrasyonu ~2-3 gün |
| Tedarikçi Grubu (Supplier Group) CRUD | Yok (MSAERP'te `vendor_group` serbest metin) | Var native ama **SPA'da yönetim ekranı yok**, sadece düz seçim listesi | ❌ Yok — SPA'da eksik | Faz 2, küçük bir SupplierGroups.vue sayfası | 1-2 gün |
| Vendor listesi — arama/filtre/sıralama/sayfalama | Var (legacy kırık, Vendor Center çalışıyor) | Var, ama `ListToolbar.vue` kullanmıyor + `SkeletonRows` yok | ⚠️ Küçük uyum borcu | Faz 2 içinde küçük düzeltme | <1 gün |
| Vendor Merkezi — Genel Bakış/PI/Avans/İthalat Belgeleri sekmeleri | Var (Vendor Center) | Var (Ledger/Orders/Invoices sekmeleri) — kavramsal eşdeğer ama "Avans Ödemeleri" ve "İthalat Belgeleri" sekmeleri MSAERP'e özel | 🔜 Kısmen — imports'a özel sekmeler Faz 2 imports SPA'sında olmalı | Faz 2 | Faz 2 içinde |
| Soft-delete + engelleme kontrolü (açık PI/PE varsa silme engeli) | Var (Vendor Center'da) | **Yok — Stabler `delete_supplier` sert silme, engel kontrolü yok** | ❌ Yok — karar gerekli, veri kaybı riski | Faz 2, `delete_supplier`'a engel kontrolü eklenmeli | 1-2 gün |
| ERPNext senkron push (create/update, 409 kurtarma) | Var (asenkron legacy + senkron Vendor Center) | N/A — Stabler zaten ERPNext üzerinde çalışıyor, sync katmanı gereksiz | ✅ Mimari olarak gereksizleşiyor | — | — |
| Vendor AP Raporu (PI/CI/avans/%70/kalan bakiye, genişletilebilir) | Var, detaylı | AP Aging var ama PI/CI/avans/%70 kırılımı imports'a özel — yok | ❌ Yok — imports-özel rapor gerekiyor | Faz 2/3, imports raporlama | 2-3 gün |
| Tedarikçi defteri Excel export | Yok (MSAERP'te yok, sadece Vendor AP raporunda yazdır var) | Var (`supplier_ledger` export) | ✅ Stabler MSAERP'i aşıyor | — | — |
| Tedarikçi karşılaştırma / tender (2-ülke kaynak politikası) | Yok | Var (`tender_quotations`) | ✅ Stabler MSAERP'i aşıyor | — | — |

### 2.4 Notlar/kararlar

1. **En kritik parity boşluğu bu bölümde: Vendor Kategorileri.** MSAERP'te PI oluştururken vendor'a özel "kaç kutu × hangi ürün" şablonunu tek tıkla dolduran bu özelliğin Stabler'da hiçbir karşılığı yok ve migrasyon planında (§3.1) da bahsi geçmiyor. Sahip ile netleştirilmeli: (a) bu özellik gerçekten kullanılıyor mu (envanterde kaç `VendorCategory` kaydı var?), (b) taşınacaksa yeni bir custom doctype + Purchase Order form entegrasyonu gerekir.
2. Stabler `delete_supplier`'ın sert silme olması ve MSAERP Vendor Center'ın engelli yumuşak silmesi arasındaki fark üretimde veri bütünlüğü riski — Faz 2'de düzeltilmeli, aksi halde açık borcu olan bir tedarikçi yanlışlıkla silinebilir.
3. MSAERP'teki "iki paralel Vendor UI" durumu bir migration fırsatı: Stabler'a taşınacak olan yalnızca Vendor Center'ın davranış modeli olmalı (soft-delete+engel, senkron sync, ERPNext-öncelikli veri) — legacy `/vendors/` ekranının kırık/tutarsız davranışları taşınmamalı.
4. `vendor_type` → ERPNext `supplier_type` eşlemesinin bugün MSAERP'te kaybolması (hepsi "Company" oluyor) migrasyon ETL'inde düzeltilecek bir fırsat: Stabler'da `Trucking Company` gibi ayrı Link alanlarıyla (WP1-3'te görüldüğü gibi) tip ayrımı korunabiliyor — ETL bu alanı MSAERP `vendor_type`'tan doğru şekilde türetmeli.

---

## 3. Ürünler (Product / Item)

### 3.1 MSAERP'de bugün

**Kritik başlangıç notu:** Products özelliği de Vendor gibi geçiş halinde — ama burada geçiş **tamamlanmış**: `products/` route'u (`product_list_dispatch`) hiçbir dallanma mantığı olmadan doğrudan ERPNext Item listesine yönlendiriyor (`from erpnext_integration.views_items import erpnext_item_list; return erpnext_item_list(request)`). Eski yerel `ProductListView` sınıfı ve `product_list.html` hâlâ kodda duruyor ama **hiçbir URL'e bağlı değil — tamamen ölü kod.**

**a) Canlı Ürün ekranı — ERPNext Item listesi** (`erpnext_integration/views_items.py`, şablon `erpnext/item_list.html`, başlık "Product Catalog")
Sunucu taraflı sayfalama (20/sayfa), sıralanabilir alanlar: `item_code, item_name, item_group, stock_uom, modified`. Filtreler: `item_group` (ERPNext `Item Group`'tan canlı çekiliyor), `status` (aktif/pasif → `disabled=0/1`), serbest metin arama (kod/isim OR). Her satır yerel `Product` ile (erpnext_name üzerinden) zenginleştiriliyor: `is_synced` rozeti, `name_uzbek` (Özbekçe isim — **yalnız yerelde**, ERPNext'te `custom_name_uzbek` custom field olarak push/pull ediliyor). Sütunlar: #, Kod (sıralanabilir), İsim (sıralanabilir), Özbekçe, Grup (rozet — "Meat Products" ise kırmızı özel rozet 🍗), UOM (sıralanabilir), Durum (Açık/Kapalı rozeti), Aksiyonlar (Düzenle/Sil/Senkronize-değilse-Senkronize-Et). Header: toplam sayaç + senkron/senkron-değil rozetleri (yeşil/amber). "Yeni Ürün" → ERPNext Item oluşturma formu.

**b) Oluştur/Düzenle formu** — `ERPNextItemForm`, düz Django Form (ModelForm DEĞİL — veri tamamen ERPNext'te yaşıyor). Alanlar: `item_code`* (düzenlemede disabled), `item_name`*, `item_group`* (ERPNext'ten canlı), `stock_uom`* (ERPNext'ten canlı), `custom_name_uzbek` (opsiyonel — Özbekçe isim), `standard_rate` (satış fiyatı), `valuation_rate` (maliyet fiyatı), `is_stock_item` (checkbox, varsayılan True), `has_serial_no` (checkbox), `disabled` (checkbox). Kaydet: `client.create_doc("Item", ...)` veya `update_doc`, sonra yerel `Product`'a senkronize ediliyor.

**c) Silme** — Confirm sayfası → ERPNext Item silme + yerel `Product` soft-delete.

**d) Tek-tek Senkronize Et butonu** — Salt POST, henüz yerelde karşılığı olmayan bir ERPNext Item'ı yerel `Product` tablosuna çekiyor.

**e) IKPU / Özbekistan vergi sınıflandırma kodu — HİÇ YOK.** Kod tabanında `ikpu`/`IKPU` için sıfır eşleşme. Ne yerel `Product` modelinde, ne `ITEM_FIELD_MAP`'te, ne `ERPNextItemForm`'da böyle bir alan var.

**f) Yerel `Product` modeli** (`proforma_app/models.py`) — sadece 7 alan: `item_code` (unique), `name_english`, `name_uzbek`, `erpnext_name` (sync anahtarı, unique), `is_active`, `deleted_at`, `deleted_by`. **Kategori, birim, fiyat, resim, açıklama YOK** — hepsi ERPNext tarafında canlı okunuyor. `delete()` soft-delete olarak override edilmiş. Hesaplanan: `total_atp` (ACTIVE partiler üzerinden `available-reserved` toplamı), `total_reserved`.

`ITEM_FIELD_MAP` senkron sözleşmesi: yalnız `item_code`, İngilizce isim, Özbekçe isim yereldeki `Product`'a çekiliyor — fiyat/UOM/grup/disabled durumu **yerelde tutulmuyor**, her seferinde ERPNext'ten canlı okunuyor.

**g) Yerel Product CRUD — orphan (erişilemiyor)**
`ProductCreateView`/`UpdateView` hâlâ route'lu ve çalışıyor (`ProductForm` — yalnız 3 alan: item_code, name_english, name_uzbek) ama `product_list` artık ERPNext ekranına gittiğinden **bu ekranlara giden hiçbir canlı link kalmamış** — navigasyon açısından tamamen kopuk. `ProductDetailView` de aynı durumda: header + 4 özet kart (Kod, Mevcut/ATP, Rezerve, Aktif Parti) + Ürün Detayları paneli + Vendor Kategorileri tablosu + Aktif Partiler tablosu (Parti#, Konteyner, Vendor, Depo, İlk Miktar, ATP, Rezerve, Durum) + Son Satışlar tablosu (son 10 satır) + Stok Raporu/Düzenle/Sil/Geri butonları — **erişilemez durumda, ama içerik zengin**, parity denetimi için referans alınmalı.

**h) `products_api` (`/api/products/`)** — ERPNext'ten canlı `Item` listesi + POS fiyat listesinden `rate` + yerel `Batch`'ten ATP hesaplayıp `{item_code, item_name, name_english, name_uzbek, id, stock_atp, actual_qty, rate}` döndürüyor. PI/CI satır girişlerinde ürün otomatik-tamamlama/seçim için kullanılıyor. ERPNext erişilemezse yerel-only fallback var.

**i) Fiyat Listeleri** — Yerel `PriceList` modeli YOK; tamamen ERPNext native `Price List`/`Item Price` üzerinden (`erpnext_integration/views_price_lists.py`: liste/detay/oluştur/düzenle/aç-kapa/sil, + `Item Price` satır CRUD'u, `/accounting/price-lists/...` altında).

**j) Ürüne bağlı raporlar** — `report_stock_movements` (ürün filtresiyle), `item_stock_report`, `stock_ledger_detail`/`export` (Bölüm 4'te detaylı).

**k) Bilinen hata/ölü kod:** `product_list_dispatch` adı yanıltıcı (dallanma yok); yerel Product CRUD tamamen navigasyondan kopuk; `product_confirm_delete.html` çevrilmemiş (i18n ihlali).

### 3.2 Stabler'da bugün

**a) SPA sayfası — `Items.vue`** (`/inventory/items`, InventoryHome sekme şeridinde: Items, Warehouses, Stock Status, Material Staging, Stock Entries, Stock Ledger, Reconcile, Low Stock).

**Liste:** Sütunlar: Kod (monospace), İsim, Grup, UOM, Tip (Stok/Alım/Satış rozetleri — `is_stock_item`/`is_purchase_item`/`is_sales_item`'dan), Standart fiyat (sağa yaslı, `formatMoney`). Filtre: tek bir çıplak `<input type="search">`, 250ms debounce — **`ListToolbar.vue` DEĞİL**, `⌘K` suffix'i yok, filtre slot'u yok — kural ihlali. Sıralama kontrolü yok, sayfalama UI'ı yok (sunucu 100 kayıtla sınırlı, "ilk N gösteriliyor" banner'ı yok), toplu aksiyon yok. Satır tıklama → sağ offcanvas detay çekmecesi (tam sayfa değil). "Yeni ürün" → modal. **Yükleme durumu spinner, `SkeletonRows.vue` DEĞİL** — kural ihlali.

**Detay (offcanvas, 640px):** Resim thumbnail veya ikon avatar, isim, kod. 2 istatistik kartı: Eldeki miktar, Stok değeri. Veri ızgarası: Grup, Stok UOM, Standart fiyat, Değerleme fiyatı (`formatMoney`), Ağırlık (koşullu). "Depo bakiyeleri" tablosu: Depo, Eldeki, Rezerve, Projekte, Değer (client-side `actual_qty × valuation_rate`). **Sekme yok, tek kaydırma görünümü. Düzenleme YOK — sadece oluşturma + okuma var, SPA'da hiç Item düzenleme formu yok.**

**Oluştur modalı:** İsim* (zorunlu), Kod (opsiyonel, isimden otomatik), Grup (`Select`), Stok UOM (`Select`), Standart fiyat (`MoneyInput` — kurala uygun), 3 checkbox (Stok/Satış/Alım kalemi), Açıklama. Tek `.btn-primary` — kurala uygun.

**b) `custom_ikpu_code` — backend'de var, SPA'da hiç görünmüyor.** `stabler/hooks.py`'de fixture olarak tanımlı custom field (Item, `item_group`'tan sonra) — plan dokümanının "alan zaten var, sadece backfill lazım" iddiasıyla örtüşüyor, WP1-3 tarafından değiştirilmemiş. **Ancak Items.vue formunda bu alan hiç sunulmuyor** — backend hazır, UI eksik.

**c) `api/inventory.py` — ürün endpoint'leri:** `list_items`, `item_detail`, `list_item_groups`, `list_uoms`, `create_item` (**tek yazma endpoint'i — `update_item`/`delete_item`/`disable_item` YOK**), `item_availability`, `item_valuation_history`. **Boşluk: Item güncelleme/pasife alma/silme endpoint'i yok; Fiyat Listesi/Item Price yönetim ekranı yok; parti/seri numarası yönetim endpoint'i yok.**

**d) WP1-3'ün Item'a dokunuşu — dolaylı:** `custom_ikpu_code` değişmemiş. `custom_boxes`/`custom_box_weight_kg` **Item'da değil, Purchase Order Item'da** (patch `v42`). Yeni patch `v43_cross_border_transport_item.py` tek bir sentetik "Cross-Border Transport" servis kalemi (Item) oluşturuyor — otomatik sınır-ötesi nakliye faturalarında satır olarak kullanılıyor; bu bir Item şema değişikliği değil, kullanım. `Container Cost Line`'ın ürün maliyetini LCV'ye dahil ETMEME kararı (çift kapitalizasyon önleme, plan §3.1 R9 ile tutarlı) burada da teyit edildi.

### 3.3 Boşluk tablosu

| Özellik | MSAERP | Stabler | Durum | Plan (WP/Faz) | Tahmini zaman |
|---|---|---|---|---|---|
| Ürün listesi (ERPNext Item'dan canlı, kod/isim/grup/UOM/durum) | Var, filtre+arama+sıralama+sayfalama | Var, ama filtre/sıralama/sayfalama eksik (ListToolbar yok) | ✅ Temel Yapıldı, ⚠️ UI zenginliği eksik | Faz 2 küçük iyileştirme | 1-2 gün |
| Özbekçe isim alanı (`name_uzbek`/`custom_name_uzbek`) | Var, listede sütun + formda alan | Belirsiz — Items.vue'de görülmedi | ❌ Doğrulanmalı/eklenmeli | Faz 1/2 | 1 gün |
| IKPU vergi kodu | **Yok** (MSAERP'te hiç yok) | Backend'de var (`custom_ikpu_code`), UI'da yok | 🔜 Planda ("backfill" — plan §1.2), sadece UI eksik | Faz 2 form alanı ekleme + Faz 3 27 kayıt backfill | UI: <1 gün, backfill: plan'da zaten görev kalemi |
| Ürün oluşturma/düzenleme (fiyat/UOM/grup/stok ayarları) | Var (ERPNext Item formu tam) | Yalnız **oluşturma** var, **düzenleme yok** | ❌ Yok — kritik boşluk | Faz 2 | 2-3 gün (Edit formu) |
| Ürün silme/pasife alma | Var (ERPNext Item sil + yerel soft-delete) | **Yok** — `delete_item`/`disable_item` endpoint'i yok | ❌ Yok | Faz 2 | 1-2 gün |
| Senkronizasyon durumu göstergesi + tek-tık senkron | Var (rozet + buton) | N/A — Stabler zaten ERPNext üzerinde, senkron kavramı yok | ✅ Mimari olarak gereksiz | — | — |
| Ürün detay — parti/stok/son satış özeti | Var (yerelde zengin, ama navigasyondan kopuk) | Var (offcanvas: depo bakiyeleri) — parti/son-satış detayı yok | ⚠️ Kısmi — parti düzeyinde detay eksik | Faz 2, batch/expiry roadmap'e bağlı (plan §1.2: "kırmızı çizgi") | Faz 2 sonrası |
| Fiyat Listesi / Item Price yönetimi | Var (ERPNext native CRUD, ayrı ekranlar) | **Yok** — SPA'da hiç yok | ❌ Yok — kritik boşluk | Plan §3.1: "PriceList/Version → Price List + Item Price, ETL Faz 1'e eklendi" — ama SPA sayfası planda değil | Faz 2'ye eklenmeli, 2-3 gün |
| Vendor Kategorisi ↔ Ürün ilişkisi (kutu/konteyner şablonu) | Var (bkz. Bölüm 2) | Yok | ❌ Yok — Bölüm 2'deki karara bağlı | Bkz. Bölüm 2 | Bkz. Bölüm 2 |
| Ürün API'si (otomatik-tamamlama, fiyat+stok birlikte) | Var (`products_api`) | Var (`list_items`, `item_availability`) — kavramsal eşdeğer | ✅ Yapıldı | — | — |

### 3.4 Notlar/kararlar

1. **Item düzenleme formunun SPA'da hiç olmaması** ("sadece oluştur", var olanı düzenleyemiyorsunuz) — bugün Stabler'da ürün fiyatını/grubunu değiştirmenin tek yolu Desk, bu doğrudan "Desk'e yönlendirme yok" kuralının ruhuna aykırı (link vermiyor ama işlevi de sağlamıyor). Faz 2'de yüksek öncelik olmalı.
2. Fiyat Listesi/Item Price yönetim ekranının SPA'da tamamen eksik olması, MSAERP'in günlük kullanılan bir özelliğinin (ayrı price-list CRUD ekranları) karşılıksız kalması demek — migration planında ETL için bahsi var ama SPA sayfası için §5'teki ~18 sayfa listesinde yok, eklenmesi gerekebilir.
3. IKPU alanının UI'da eksik olması düşük efor/yüksek görünürlük bir düzeltme — Faz 2'nin erken bir sprintine alınabilir, backend zaten hazır.
4. MSAERP'te "yerel Product CRUD'un navigasyondan kopuk ama zengin" durumu — bu ekranlardaki Vendor Kategorileri, Aktif Partiler, Son Satışlar panelleri Stabler'ın Item detay tasarımı için iyi bir referans olabilir (özellikle batch/expiry Faz 2 sonrası roadmap'e girdiğinde).

---

## 4. Depolar & Stok Transferi

### 4.1 MSAERP'de bugün

**Kritik başlangıç notu — bu bölüm en karmaşık ve mimari açıdan en riskli alan.** Kod tabanında **iki paralel stok sistemi** var: (1) tamamen yerel, eski `StockEntry/StockEntryItem/StockLedgerEntry/Batch` defter sistemi (`stock/*`, `reports/stock-*`, `inventory/stock-adjustment/*`), ve (2) yeni ERPNext-native `warehouse-center/` + `stock-transfer-center/` iki-panelli SPA-tarzı ekranlar (ERPNext `Warehouse`/`Stock Entry` doctype'larını doğrudan API ile kullanıyor, yerel yansıma yok). Bu iki sistem yalnızca **depo-adı string eşleşmesiyle** (`Batch.warehouse` CharField ↔ ERPNext `Warehouse.name`) köprüleniyor — başka hiçbir uzlaştırma yok.

**Ayrıca bugün yerelde bir `Warehouse` Django modeli YOK** — geçmiş migrationlar (`0131` vd.) bir FK modeli eklemiş ama kod bugün `Batch.warehouse` gibi alanları düz `CharField(140, help_text="Warehouse name in accounting system")` olarak tutuyor — yani depo, ERPNext `Warehouse.name`'iyle eşleşmesi gereken serbest metin.

**a) Depo Merkezi — `WarehouseCenterView` (`/warehouse-center/`)** — iki panelli, ERPNext-native master + yerel stok
Sol panel ("Depo Defteri"): `warehouse_list_api`'den (60sn cache) depo listesi. Filtreler: arama (isim/kod/şehir), Ana Depo dropdown, tip pilleri (Tümü/Yaprak/Grup/Aktif/Pasif). Sıralama: A-Z veya Tipe göre. Satır: klasör/bina ikonu, isim, ana depo alt metni, "Pasif" rozeti. "Yeni Depo" (+) butonu modal açıyor.

Sağ panel (depo detayı, sekmeli): Header (isim, tip rozeti, Grup/Yaprak rozeti, şehir/ülke) + Düzenle/Sil. 4 istatistik kartı: Durum, Depo Tipi, Benzersiz Ürün Sayısı, Mevcut Miktar (kg). Sekmeler: **Genel Bakış** (alt depolar ızgarası, grup depoysa), **Stok** (yerel `Batch` verisi, depo-adı eşleşmesiyle — Ürün Kodu, Ürün, Mevcut kg, Rezerve kg [rezerve varsa amber], ATP kg [≤0 ise kırmızı], Parti sayısı [genişletilebilir], En Erken S.K.T.; genişletince parti alt-satırları: parti no, vendor, miktar, değerleme fiyatı, S.K.T.), **Stok Girişleri/Transferler** (ERPNext'ten canlı `Stock Entry`, from/to filtreli, Ad/Tip/Kaynak/Hedef/Tarih/Durum rozeti), **GRN'ler** (**placeholder: "GRN data will be available after migration" — açıkça uygulanmamış**).

Oluştur/Düzenle modalı: `warehouse_name`*, `parent_warehouse`, `warehouse_type` (serbest metin), `is_group`, `city`, `country` (varsayılan Özbekistan), `disabled` (düzenlemede). Silme modalı: ERPNext'e doğrulama ("stok varsa silinemez" uyarısı).

**b) Stok Transfer Merkezi — `StockTransferCenterView` (`/stock-transfer-center/`)** — %100 ERPNext-native
Sol panel: `purpose=Material Transfer` filtreli ERPNext Stock Entry listesi, durum pilleri (Tümü/Taslak/Onaylı/İptal, docstatus'a göre), arama. Sağ panel (detay): header + **Onayla** (taslaksa) veya **İptal Et** (onaylıysa) butonu; 4 bilgi kartı (Kaynak Depo, Hedef Depo, Toplam Miktar, Toplam Tutar); satır tablosu (Kod, İsim, Miktar, UOM, Fiyat, Tutar) — hepsi canlı ERPNext'ten.

Oluştur modalı: Kaynak Depo*/Hedef Depo* (yaprak depolardan), Kayıt Tarihi, tekrarlanabilir satır listesi (item_code serbest metin + miktar). `POST /accounting/api/stock-entry/create/` ile taslak ERPNext Stock Entry oluşturuluyor. **Parti/değerleme fiyatı seçimi UI'da yok** — bu akışın **yerel veritabanında hiç izi yok.**

**c) Legacy yerel Stok Girişi sistemi** (`stock/*`)
`StockEntry` modeli: `entry_number` (oto SE-YYYYMMDD-####), `entry_type` (RECEIPT/ISSUE/TRANSFER/ADJUSTMENT), `status` (DRAFT/SUBMITTED/IN_TRANSIT/RECEIVED/CANCELLED), kaynak belge linkleri (grn/container/customer_invoice), `location_from`/`location_to` (serbest metin). `StockEntryItem`: `product`, `batch` (opsiyonel), `quantity` (>0 constraint), `uom`, `valuation_rate`, `amount` (oto-hesap). `StockLedgerEntry`: **append-only** (save/delete güncellemede ValidationError fırlatıyor) — ama `balance_quantity` her zaman `Decimal('0')` olarak sabitleniyor, "sinyal/trigger ile güncellenecek" yorumu var ama böyle bir sinyal **yok** — yarım kalmış/bozuk özellik.

**Bilinen kritik bug:** `StockEntryCreateView.form_valid`, `StockEntryItem.objects.create()`'e `unit_cost=` parametresi geçiyor ama modelde böyle bir alan yok (gerçek alan adı `valuation_rate`) — legacy `stock/create/` formu her kullanımda muhtemelen `TypeError` veriyor.

`stock_entry_post`: yalnız DRAFT girişleri onaylıyor, ISSUE/TRANSFER için FIFO parti tahsisi uyguluyor, TRANSFER için 2 `StockLedgerEntry` (kaynak OUT + hedef IN) oluşturuyor. **Ama gerçek `Batch.quantity_available` mutasyonunu buradan yapmıyor** — asıl ATP güncellemesi ayrı olarak GRN onayı (`grn_services.py`) ve fatura postalama (`inventory_services.py`, `shipment_service.py`) sinyalleriyle yapılıyor. Yani **legacy StockEntry→StockLedgerEntry hattı, uygulamanın geri kalanında gösterilen gerçek ATP rakamlarından büyük ölçüde kopuk.**

**d) Stok Ayarlaması (Stock Adjustment)** — ayrı model YOK, `StockEntry.filter(entry_type='ADJUSTMENT')` üzerinden. Form alanları: Konum*, Ürün*, Parti (opsiyonel), Sistemdeki Mevcut Miktar (salt-okunur), Fiziksel Sayım*, Ayarlama Nedeni* (Sayım farkı/Hasar-Kayıp/Numune-Test/Satıştan iade/Diğer), Kayıt Tarihi, Notlar.

**e) `Batch` modeli — gerçek envanter defteri**
`batch_number` (unique), `product`, `container` (opsiyonel), `vendor` (opsiyonel), `warehouse` (serbest metin), `manufacturing_date`, `expiry_date`, `quantity_received`, `quantity_available`, `quantity_reserved`, `valuation_rate`, `original_valuation_rate` + `landed_cost_added` (IAS 2 landed-cost uyumu takibi), `status` (ACTIVE/EXPIRED/QUARANTINE/EXHAUSTED). DB constraint'leri negatif miktarı engelliyor. Hesaplanan: `is_expired`, `days_until_expiry`, `consumption_percentage`, `quantity_atp`.

`StockReservation` modeli: DRAFT/ISSUED müşteri faturalarına ayrılan stoğu takip ediyor (RESERVED/FULFILLED/RELEASED).

**f) Depo Stok Raporu — `WarehouseStockView` (`/warehouse/stock/`)**
`Batch` satırları (ACTIVE, mevcut>0), S.K.T.'ye göre sıralı. Filtreler: depo (distinct `Batch.warehouse` string listesi), arama, S.K.T. durumu (tümü/iyi >30g/yaklaşan 7-30g/kritik <7g/süresi geçmiş). Sütunlar: Parti No, Ürün (isim+kod), Depo (rozet), Mevcut Miktar kg, S.K.T., Kalan Gün, Durum rozeti (yeşil "İyi stok >30g", amber "Yakında kontrol 7-30g", kırmızı "Yakında bitecek <7g veya Süresi geçmiş"), Vendor. Alt kısımda 4-renk açıklama kartı. 50/sayfa sayfalama.

**g) Stok Seviyesi Raporu — `StockLevelReportView` (`/reports/stock-levels/`)**
`StockLedgerEntry`'yi ürün+konum bazında topluyor (`total_quantity`, ağırlıklı `avg_cost`), `total_quantity>0` filtreli. Filtreler: ürün, konum.

**h) Stok Hareket Raporu — `StockMovementReportView` (`/reports/stock-movements/`)**
Kendini hem `StockLedgerEntry` hem `StockEntryItem` kapsayan "QB Desktop tarzı" bir rapor olarak tanımlıyor ama **gerçekte yalnız `StockEntryItem` sorguluyor**. Sütunlar: Tarih, Tip (renkli rozet), Belge, Ürün, Konum, Giren Miktar, Çıkan Miktar, Bakiye (**her zaman "—", hiç hesaplanmıyor — ölü sütun**), Fiyat, Değer. **Bilinen bug:** şablon `movement.stock_entry.location_from.location_name` gibi ilişkisel bir nesne bekliyor ama `location_from` düz `CharField` — Django template'te sessizce boş render ediyor, yani **Konum sütunu her zaman boş.** Aynı sorun konum filtresi dropdown'ında da var — filtre işlevsiz.

**i) Stok Hareket Excel Export'u (`stock_movement_export`)** — Rapor ekranından FARKLI olarak `StockLedgerEntry`'yi sorguluyor (yani **ekran ve export aynı rapor için farklı veri kaynağı kullanıyor, rakamlar örtüşmeyebilir**). `openpyxl` ile: başlık, filtre özeti, sütunlar (Tarih, Tip, Belge, Fiş Tipi, Ürün Kodu, Ürün Adı, Konum, Giren, Çıkan, Bakiye, Fiyat $, Değer $), renk kodlu satırlar (yeşil=giriş, kırmızı=çıkış). **Aynı `.location_name` bug'ı burada Python seviyesinde — muhtemelen `AttributeError` ile export çöküyor.** USD formatında (`$#,##0.00`) — CLAUDE.md'nin UZS-öncelikli format kuralına aykırı.

**j) Ürün Hızlı Raporu (QuickBooks-tarzı) — `item_stock_movement_report` (`/reports/item/<id>/transactions/`)**
Üç bağımsız kaynağı birleştiriyor: (1) `GRNLineItem` (Stok GİRİŞ, APPROVED GRN'ler), (2) `CustomerInvoiceItem` (Stok ÇIKIŞ, POSTED/PAID faturalar), (3) `StockEntryItem` (RECEIPT/ISSUE/ADJUSTMENT/TRANSFER, SUBMITTED, GRN/fatura ile ilişkili olanlar hariç — çifte sayımı önlemek için). Tarih aralığı filtresi (varsayılan son 90 gün). Açılış bakiyesi + koşan bakiye hesaplıyor. FIFO parti katmanları da gösteriliyor (aktif partiler, üretim tarihine göre sıralı, toplam değerleme+ortalama maliyet).

**k) Stok Defteri (Cardex) Raporu — `stock_ledger_detail`/`export` (`/reports/stock-ledger/<id>/`)**
Ağırlıklı ortalama maliyet koşan defteri (`stock_ledger_service.get_stock_ledger`). Açılış/kapanış miktar+değer, satır bazında giriş/çıkış/bakiye/gelen fiyat/değerleme fiyatı/bakiye değeri/fiş tipi/fiş no. Varsayılan dönem: cari ay. Excel export: başlık "Stock Ledger (Cardex)", açılış/kapanış satırları görsel vurgulu (gri/amber, kalın), normal satırlar yeşil(giriş)/kırmızı(çıkış), USD formatı.

**l) ERPNext senkronizasyonu — "sistem kaydı" bulgusu (proje kuralı açısından kritik)**
- Yerel `StockEntry`/`StockLedgerEntry`/`Batch`'i ERPNext `Stock Entry`/`Bin`'e push eden HİÇBİR kod yok; ERPNext `Bin` miktarlarını yerel `Batch`'e çeken kod da yok.
- `CustomerInvoice.erpnext_stock_entry` — fatura postalanınca ERPNext'te "Stock Entry (Material Issue)" oluşturulup adı bu alana yazılıyor — tek yönlü, geri okunmayan bir referans, ayrı bir akış.
- **Net sonuç: uygulamanın her yerinde gösterilen gerçek zamanlı ATP (Product detay, `products_api`, Depo Merkezi Stok sekmesi, POS) tamamen yerel `Batch` tablosundan geliyor** — GRN onayı ile artıyor, fatura postalama/rezervasyon sinyalleriyle azalıyor; **ERPNext'in native stok defteri sadece Depo master verisi ve Material Transfer akışı için kullanılıyor.** Bu, CLAUDE.md Kural 2'nin ("ERPNext sistem kaydıdır... gerçek zamanlı bakiyeler için ERPNext'i sorgula") ruhuyla doğrudan gerilimde — pratikte fiziksel envanter miktarı **yerel sistem kaydı**, yalnızca depo-transfer/master katmanı ERPNext-native. Bu, Türkçe denetim dokümanında açıkça bir uyum/parity riski olarak işaretlenmeli.

**m) Somut hata listesi (bilinen sorunlar — parity hedefine dahil edilmemeli, ama ETL/test senaryosu tasarımı için önemli):**
1. `product_list_dispatch` tarzı: `StockEntryCreateView.form_valid`, model alanıyla uyuşmayan `unit_cost=` kwarg'ı geçiyor — legacy oluşturma formu muhtemelen çöküyor.
2. `StockLedgerEntry.balance_quantity` hep 0 — "sinyal ile güncellenecek" ama sinyal yok.
3. Stok Hareket Raporu + export'unda `.location_name` bug'ı — Konum sütunu/filtresi işlevsiz (raporda sessiz, export'ta muhtemelen hard crash).
4. Rapor ekranı (`StockEntryItem`) ile export'u (`StockLedgerEntry`) farklı tablo sorguluyor — rakamlar tutarsız olabilir.
5. Fiziksel envanter (Batch, yerel) ile Depo master/Transfer (ERPNext) arasında yalnız depo-adı string eşleşmesi var, gerçek bir foreign-key/senkron yok.
6. `templates/inventory/`'de hem üst düzey hem `proforma_app/templates/inventory/` altında aynı isimli dosyalar var (`warehouse_stock.html`, `stock_movement_report.html`) — Django `DIRS`-önce-`APP_DIRS` sırası nedeniyle üst düzeydekiler aktif, `proforma_app/` altındakiler bayat kopya.

### 4.2 Stabler'da bugün

**a) SPA sayfaları — Inventory sekme şeridi altında** (`InventoryHome.vue`: Items, Warehouses, Stock Status, Material Staging, Stock Entries, Stock Ledger, Reconcile, Low Stock)

**1. `/inventory/warehouses` — `Warehouses.vue`**
Genişle/daralt ağaç listesi (client-side, `parent_warehouse`'tan kurulu), derinlik girintili satırlar, arama filtresi (çıplak input — **`ListToolbar` yok**, Items.vue ile aynı ihlal sınıfı). Sütunlar: Depo (isim+klasör/bina ikonu), Tip (rozet), Stok Değeri (`formatMoney`). Yaprak depoya tıklama → o depoya filtrelenmiş Stock Status'a yönlendiriyor; grup satırına tıklama genişletiyor. "Yeni Depo" / satır-üstü hover "+" ile alt depo ekleme — modal: Depo adı, Ana Depo, Tip, "Grup depo" checkbox. Para/tarih alanı yok. Tek `.btn-primary` Kaydet — kurala uygun. **Yükleme spinner, `SkeletonRows` yok — ihlal.** **Depo düzenleme/pasife alma/silme endpoint'i veya UI'ı yok — sadece oluşturma.**

**2. `/inventory/stock-status` — `StockStatus.vue`**
Depo seçici (URL query param'a senkron, paylaşılabilir link), ürün arama filtresi (çıplak input). 4 KPI kartı: Ürün sayısı, Eldeki, Serbest, Stok Değeri. Ürün tablosu: Ürün, Grup, Fiili, Rezerve, Serbest, Fiyat, Değer — tıklama → `ItemValuationDrawer.vue` (fiyat geçmişi grafiği + kronolojik SLE tablosu).

**3. `/inventory/entries` — `StockEntries.vue`** — MSAERP'in Stok Transfer Merkezi'nin gerçek eşdeğeri, ama **birleşik Giriş/Çıkış/Transfer** ekranı
**Bu sayfa `ListToolbar.vue`'yu TAM olarak kullanıyor** (kaynak/hedef depo filtreleri, durum, `DateInput` başlangıç/bitiş, `⌘K` dahil) — **kurala tam uyumlu.** Amaç pilleri (Tümü/Girişler/Çıkışlar/Transferler) + mobilde Select fallback. İstemci tarafı sıralanabilir sütunlar (Referans, Tarih, Amaç, Kaynak→Hedef, Ürünler, Değer, Durum). **`SkeletonRows` doğru kullanılmış — kurala uyumlu** (Items/Warehouses'ın aksine). Durum rozeti: **elle yazılmış `docstatusBadge()` fonksiyonu, `getStatusBadgeClass` KULLANMIYOR** — merkezi-durum kuralı ihlali (oysa `composables/status.js`'te tam bu durumu (docstatus 0/1/2) kapsayan genel bir dal zaten var). Detay çekmecesi (720px): amaç ikonu, ad, amaç+tarih, docstatus rozeti, Onayla/İptal butonları (rol/duruma göre kilitli), Kaynak/Hedef özet kartı, satır tablosu. Oluşturma modalı (geniş): amaç radio grubu, `DateInput` kayıt tarihi (uyumlu), canlı "Tahmini değer" toplamı, amaca göre koşullu Kaynak/Hedef `Select`'leri, satır ızgarası (debounce'lu ürün arama, `MoneyInput` fiyat için — uyumlu, miktar çıplak number input — kural kapsamı dışı ama not edilmeye değer), "Taslak Kaydet" (outline-primary) + "Kaydet ve Onayla" (primary) — aynı footer'da iki güçlü-vurgulu buton, harfi harfine kural ihlali sayılmayabilir (biri outline) ama sınırda.

**4. `/inventory/ledger` — `StockLedger.vue`**
Filtre satırı `ListToolbar` DEĞİL, özel bir header filtre çubuğu: `DateInput` başlangıç/bitiş (uyumlu), ürün Typeahead, depo Select, **elle "Uygula" butonu** — **"filtre değişince otomatik uygula, Uygula/Yenile butonu yok" kuralını açıkça ihlal ediyor.** Tablo: Tarih (`formatDateTime`, uyumlu), Fiş (tip rozeti + JE/PE için detay çekmecesi; Stock Entry/Purchase Receipt fişleri için tıklanabilirlik yok — UX boşluğu), Ürün, Depo, Hareket (işaretli miktar, renkli), Bakiye, Değer Δ. Sabit `limit=200`, "ilk N gösteriliyor" banner'ı yok.

**5. `/inventory/reconcile` — `StockReconciliation.vue`**
Depo Select + canlı "Değişen"/"Değer farkı" özeti + "Uzlaştırmayı Kaydet" (rol-kilitli: Stock Manager/System Manager/Stabler Admin). Ürün arama/sayım satırında **`ListToolbar` kullanılmış (`⌘K` dahil) — uyumlu.** Sayılan miktar sütunu `MoneyInput` (para değil ama sayısal format için makul kullanım). **`SkeletonRows` doğru — uyumlu.** Kaydetmeden önce `useConfirm()` onay diyaloğu — iyi pratik. "Son uzlaştırmalar" alt tablosu `formatDate`/`formatDateTime` doğru kullanıyor.

**6. `/inventory/alerts` — `LowStockAlerts.vue`**
Filtre/arama UI'ı hiç yok. Şiddet rozeti elle hesaplanıyor (Tükendi/Kritik/Düşük, kırmızı/turuncu/sarı) — yine **merkezi-olmayan durum haritası, aynı ihlal sınıfı.** Sütunlar: Durum, Ürün, Depo, Eldeki, Projekte, Yeniden sipariş noktası, Yeniden sipariş miktarı.

**7. `/inventory/staging` — `MaterialStaging.vue`**
Bu aslında bir **Üretim/İş Emri malzeme-transfer ekranı** (`manufacturing.py` API'lerini kullanıyor) — genel depo-arası transfer aracı değil, üretime hammadde hazırlama amaçlı. Inventory sekme şeridinde olduğu için burada anıldı.

**Modül erişimi:** `_MODULE_ROLES["inventory"] = ["Stock User", "Stock Manager"]`, `enable_inventory` şirket toggle'ı, `/inventory` ana route'unda `meta: { module: "inventory" }` — kurala uyumlu.

**"Desk'e yönlendirme yok" kontrolü:** Tüm inventory sayfalarında Desk linki/yönlendirmesi bulunamadı — **bu alanda ihlal yok**, Stabler'ın kendi tam işlevsel depo/stok yönetim yüzeyi var (MSAERP'in "warehouse-center"/"stock-transfer-center" gibi, ama daha eksiksiz filtre/skeleton uyumu ile).

**Para birimi gösterimi:** Tüm sayfalarda `formatMoney(value, currency, ...)` şirketin kendi para biriminde — baz-para/USD alt satırı yok, kurala uyumlu.

**b) `api/inventory.py` — depo/stok endpoint'leri:** `list_warehouses` (her düğüm için hesaplanmış `stock_value`), `list_stock_warehouses`, `list_parent_warehouses`, `list_warehouse_types`, `create_warehouse` (**tek yazma endpoint'i — güncelleme/pasife alma/silme YOK**), `warehouse_stock`, `item_availability`, `list_stock_entries`, `stock_entry_detail`, `create_stock_entry` (amaç doğrulaması `{Material Receipt, Material Issue, Material Transfer}`, `set_missing_values()`+`insert()`+opsiyonel `submit()`), `submit_stock_entry`/`cancel_stock_entry`, `stock_ledger`, `item_valuation_history`, `low_stock_alerts`, `warehouse_stock_balance`, `preview_reconciliation`/`create_stock_reconciliation` (rol-kilitli), `list_stock_reconciliations`. Her şirket-kapsamlı endpoint `_assert_company_scope` çağırıyor (kiracı izolasyonu).

**Boşluklar:** Depo güncelleme/pasife alma/silme yok; **parti/seri numarası takibi Stock Entry oluşturmada desteklenmiyor** — `create_stock_entry` hiçbir zaman `batch_no`/`serial_no` set etmiyor, yani parti-takipli ürünler bu ekrandan doğru transfer edilemiyor (işlevsel boşluk, sadece UI değil); Stock Entry Type yönetimi yok.

**c) WP1-3'ün Depo/Stok'a dokunuşu — asıl önemli bulgu: bu iskelet DEĞİL, gerçek çalışan bir zincir.**
`Truck Receipt.on_submit` → `imports_module/hooks.py::truck_receipt_on_submit` (aynı transaction içinde, senkron — PR başarısız olursa Truck Receipt onayı da geri alınıyor): tedarikçiyi GRN/CI'dan çözüyor, hedef depoyu `Import Truck.destination_warehouse` (yoksa `GRN Checklist.warehouse`) üzerinden çözüyor, her satır için "İyi" miktarı `receipt_math.good_qty()` ile hesaplıyor, PO fiyatını `receipt_math.resolve_po_rate()` ile çözüyor, parti-takipli ürünse ihtiyaç halinde ERPNext **Batch** kaydı oluşturuyor, gerçek bir **`Purchase Receipt`** ekliyor+onaylıyor (`pr.submit()` — bu asıl stok-defteri postalama olayı), sonra `recompute_grn_from_receipts()` (GRN Checklist satırlarını yeniden hesaplıyor) ve `advance_truck_after_receipt()` (Import Truck durumunu otomatik ilerletiyor) çağırıyor. İptalde bağlı Purchase Receipt hâlâ onaylıysa iptal engelleniyor.
`GRN Checklist` submittable; satır/header beklenen/alınan/bekleyen/varyans/durum alanlarını `grn_math` ile yeniden hesaplıyor; onay öncesi geçerli bir Veteriner Sertifikası şartı (Imports Manager override edebilir); onayda arka plan işiyle **taslak** Landed Cost Voucher üretiliyor (`Container Cost Line`'lardan, ürün maliyeti+CIF hariç — çift kapitalizasyon önleniyor, ERPNext native LCV `get_items_from_purchase_receipts()` ile otomatik dağıtım) — **hiçbir zaman otomatik onaylanmıyor**, muhasebeci draft'ı elle onaylıyor.
`Import Container`/`Import Truck` submittable-olmayan, tek yönlü durum-pipeline belgeleri, paylaşılan `assert_transition()` helper'ıyla doğrulanıyor. Durum geçişlerinde yan etkiler: `Import Container→ARRIVED_AT_IRAN` arka planda **taslak** %70 avans Payment Entry oluşturuyor; `Import Truck→CROSSED_BORDER` senkron olarak sentetik "Cross-Border Transport" Item'a karşı **taslak** sınır-ötesi nakliye Purchase Invoice'ı oluşturuyor. Hepsi `_should_run()` ile (migration flag DEĞİL VE `enable_imports` şirket toggle'ı AÇIK) kapılı — diğer 5 kiracıda inert.

**Ama bu zincirin hiçbir SPA/UX yüzeyi yok** — bugün bu akışı tetiklemenin tek yolu Frappe Desk veya doğrudan API; Faz 2 SPA çalışması başladığında bu, "Stabler kendi kendine yeten bir UX" ilkesiyle (henüz ihlal değil çünkü SPA'da Desk'e link de yok — özellik basitçe SPA'dan yok) uyumlu hale getirilmeli.

### 4.3 Boşluk tablosu

| Özellik | MSAERP | Stabler | Durum | Plan (WP/Faz) | Tahmini zaman |
|---|---|---|---|---|---|
| Depo master listesi (ağaç, tip, aktif/pasif) | Var (Depo Merkezi sol panel) | Var (`Warehouses.vue`) | ✅ Yapıldı (temel) | Faz 1 ETL: Warehouse'lar (plan §7.1'de ilk sırada) | ETL'de |
| Depo oluştur/düzenle/sil | Var (3'ü de) | Yalnız **oluşturma** var | ❌ Düzenleme/silme yok | Faz 2 | 1-2 gün |
| Depo başına stok görünümü (parti kırılımlı ATP) | Var (Depo Merkezi Stok sekmesi, parti genişletme) | Var (`Stock Status`), parti detayı `ItemValuationDrawer` üzerinden dolaylı | ⚠️ Kısmi — parti-özel görünüm farklı UX | Faz 2 iyileştirme | 1-2 gün |
| Stok Transferi (depo-depo, Material Transfer) | Var (Stok Transfer Merkezi, ERPNext-native) | Var (`Stock Entries` — Girişler/Çıkışlar/Transferler birleşik) | ✅ Yapıldı, Stabler daha kapsamlı (3 amaç tek ekranda) | — | — |
| Stok Girişi (Material Receipt) — manuel | Var (legacy `stock/`, **buglu/çöküyor**) | Var (`Stock Entries`, çalışıyor) | ✅ Stabler MSAERP'in kırık halini aşıyor | — | — |
| Stok Ayarlaması (fiziksel sayım farkı) | Var (`inventory/stock-adjustment/`) | Var (`Stock Reconciliation`, ERPNext-native, rol-kilitli) | ✅ Yapıldı | — | — |
| Parti/S.K.T. takibi (Batch expiry) | Var (Batch modeli, S.K.T. renk kodlu rapor) | ERPNext native Batch var ama **Stock Entry oluşturmada parti seçimi desteklenmiyor**, expiry-öncelikli picking planlanmamış | ❌ Yok — plan §1.2'de açıkça "kırmızı çizgi" (Faz 2 sonrası roadmap) olarak işaretli | Kapsam dışı (Faz 2), ayrı roadmap kalemi | Büyük — ayrı proje kapsamı |
| Depo Stok Raporu (S.K.T. renk kodlu, filtreli) | Var (`warehouse_stock.html`) | Var (`Stock Status`) — S.K.T. renk kodlaması/vurgu yok | ⚠️ Kısmi | Faz 2 küçük iyileştirme | 1 gün |
| Stok Seviyesi Raporu | Var | Kısmen `Stock Status`'a gömülü | 🔜 Kısmi eşdeğer | — | — |
| Stok Hareket Raporu (ekran+Excel export) | Var, **ama ekran/export farklı veri kaynağı kullanıyor — buglu** | `Stock Ledger` sayfası var ama Excel export yok bu sayfada (Supplier Ledger'da var, Stock Ledger'da doğrulanmadı) | ⚠️ Doğrulanmalı — export eksikse eklenmeli | Faz 2/3 | 1-2 gün |
| Ürün Hızlı Raporu (3 kaynaklı — GRN+Fatura+StockEntry birleşik) | Var, zengin (FIFO parti katmanları dahil) | `ItemValuationDrawer` kısmi eşdeğer, GRN/İthalat kaynaklarını henüz kapsamıyor (WP1-3 SPA'sız) | ❌ Yok — imports SPA'sına bağlı | Faz 2, imports sonrası | Faz 2 içinde |
| Stok Defteri (Cardex, ağırlıklı ortalama) | Var (ekran+Excel export) | `Stock Ledger.vue` var ama filtre "Uygula" butonlu (kural ihlali) ve export doğrulanmadı | ⚠️ Kısmi, küçük UX borcu | Faz 2 küçük düzeltme | <1 gün (auto-apply) |
| Truck Receipt onayında otomatik kısmi Purchase Receipt (stoğa giriş) | Yok (MSAERP'te GRN onayı stok girişini tetikliyor ama tır-bazlı kısmi kabul yok) | **Var, WP1-3'te tam çalışır durumda** (backend) | ✅ Stabler MSAERP'i aşıyor (backend), ❌ SPA'sı yok | Faz 2 TruckReceiptForm (plan §5: "saha pilotu, Faz 2'nin İLK sayfası") | Faz 2'nin ilk haftaları |
| Landed Cost Voucher taslağı otomatik üretimi | Var (LandedCostAllocation manuel akış, dashboard'da izlenebiliyor) | **Var, WP1-3'te tam çalışır durumda** (backend, GRN onayında taslak LCV) | ✅ Stabler MSAERP'i aşıyor (backend), ❌ SPA izleme ekranı yok | Faz 2 "LandedCostReview" sayfası (plan §5) | Faz 2 içinde |
| Fiziksel envanterin sistem kaydı sorunu | MSAERP'te ATP yerelde (Batch), ERPNext sadece depo master+transfer | Stabler'da ATP tamamen ERPNext native (`Bin`) — **gerçek sistem kaydı ilkesine tam uyumlu** | ✅ Stabler mimari olarak MSAERP'in ihlalini düzeltiyor | Faz 3 ETL: açılış Stock Reconciliation ile tek seferlik geçiş | Plan §7.3'te zaten görev kalemi |

### 4.4 Notlar/kararlar

1. **En önemli mimari bulgu bu bölümde:** MSAERP'te "ERPNext sistem kaydıdır" kuralı depo/stok alanında bugün fiilen **ihlal ediliyor** — gerçek zamanlı ürün mevcudiyeti (ATP) tamamen yerel `Batch` tablosundan geliyor, ERPNext yalnız depo master'ı ve transfer akışı için kullanılıyor. Stabler'ın ERPNext-native `Bin`/`Stock Entry` tabanlı mimarisi bu sorunu **kökten çözüyor** — bu, migration'ın en net "iyileşme" hikayelerinden biri ve dokümanda böyle çerçevelenmeli, sadece "parity" değil "düzeltme" olarak.
2. Parti/S.K.T. (batch/expiry) takibinin Stok Girişi ekranında desteklenmemesi plan dokümanında zaten bilinen bir boşluk ("kırmızı çizgi" — Faz 2 sonrası ayrı roadmap) — bu denetimde de teyit edildi, kapsam netliği açısından önemli: go-live için bloklayıcı DEĞİL, ama et ithalatı işinde parti/S.K.T. kritik olduğundan sahip ile net bir tarih taahhüdü konuşulmalı.
3. WP1-3'ün Truck Receipt→Purchase Receipt ve GRN→LCV zincirinin **arka planda tam çalışır durumda olması ama hiç SPA yüzeyinin olmaması**, Faz 2'nin en yüksek iş değerli ilk teslimi — plan zaten bunu "TruckReceiptForm, Faz 2'nin İLK sayfası, saha pilotu" olarak önceliklendirmiş, bu denetim bu önceliklendirmeyi doğruluyor.
4. Legacy `stock/create/` formunun muhtemelen her zaman çökmesi (`unit_cost` bug'ı) ve Stok Hareket Raporu'nun ekran/export tutarsızlığı gibi MSAERP hataları **ETL doğrulama senaryolarına dahil edilmemeli** — bunlar zaten kırık, "aynısını üretmek" hedef değil.
5. Depo düzenleme/silme endpoint'lerinin Stabler'da eksik olması (yalnız oluşturma var) hem Item hem Warehouse için tekrarlanan bir desen — muhtemelen bilinçli bir "v1 minimal API" kararı, ama parity denetimi açısından Faz 2'de birlikte ele alınabilecek düşük-riskli, düşük-efor bir iyileştirme grubu.
6. CLAUDE.md kural ihlalleri (ListToolbar eksikliği: Items/Warehouses/StockStatus/StockLedger/MaterialStaging/LowStockAlerts; SkeletonRows eksikliği: Items/Warehouses/StockStatus; merkezi olmayan durum rozeti: StockEntries/LowStockAlerts/Dashboard/ServiceDashboard; StockLedger'da auto-apply yerine "Uygula" butonu) bu denetimin dört bölümünde de tekrar eden bir desen — bunları tek bir "UI tutarlılık temizliği" iş paketi olarak Faz 2'nin başında toplu ele almak, her sayfayı ayrı ayrı düzeltmekten daha verimli olabilir.

---

## Genel Özet — En Büyük Boşluklar (4 bölüm toplamı)

1. **Satın Alma/İthalat Dashboard'u** — MSAERP'te günlük kullanılan operasyonel ekran, Stabler'da salt placeholder (`ImportsDashboard.vue`). Faz 2'nin erken bir teslimi olmalı.
2. **Vendor Kategorileri** (vendor-özel ürün/kutu şablonu, PI'a otomatik doldurma) — Stabler'da hiç karşılığı yok, migration planında da bahsi geçmiyor. Sahip kararı gerekiyor: taşınacak mı, taşınacaksa yeni bir custom doctype mı gerekiyor.
3. **Tedarikçi Grubu (Supplier Group) yönetim ekranının SPA'da hiç olmaması** — "Desk'e yönlendirme yok" kuralı gereği gerçek bir işlevsel boşluk (grup oluşturma/düzenleme hiçbir yerden yapılamıyor).
4. **Item düzenleme formunun SPA'da hiç olmaması** (yalnız oluşturma var) — ürün fiyatı/grubu/UOM değiştirmenin bugün SPA'dan yolu yok.
5. **Fiyat Listesi / Item Price yönetim ekranının SPA'da tamamen eksik olması** — MSAERP'te ayrı, işlevsel bir CRUD var; Stabler'da ne var ne planlı (§5'teki 18 sayfa listesinde yok).
6. **Parti/S.K.T. (batch/expiry) takibinin Stok Girişi'nde desteklenmemesi** — bilinen roadmap boşluğu, et ithalatı işi için kritik, go-live tarihinden ayrı netleştirilmeli.
7. **WP1-3'ün güçlü backend zincirinin (Truck Receipt→Purchase Receipt, GRN→taslak LCV) hiç SPA yüzeyi olmaması** — teknik borç değil, planlı sıradaki iş (Faz 2 ilk sayfa = TruckReceiptForm); en yüksek iş değeri burada.
8. **Mimari iyileşme (olumlu bulgu):** MSAERP'te fiziksel envanter (ATP) aslında yerel sistemde tutuluyor, "ERPNext sistem kaydı" ilkesini ihlal ediyor; Stabler'ın ERPNext-native `Bin` mimarisi bunu köklü şekilde düzeltiyor — bu migration yalnız "parity" değil, gerçek bir mimari borç ödemesi.
