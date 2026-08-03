# Stabler ERP — Sales & Customer Center Tasarım ve Kod Briefi

Bu doküman, **Stabler ERP** projesinin **Sales (Satış)** modülü, **Customer Center (Müşteri Merkezi)** ve **Header / Subnav Menü** mimarisi için hazırlanmış detaylı kod ve tasarım brief'idir. **Claude Design** ve ön yüz ekibiyle yeni tasarımı görüşmek ve geliştirmek üzere teknik spesifikasyonları içerir.

---

## 1. Genel Modül Mimarisi ve Rota Yapısı

Sales (Satış) modülü, Stabler SPA'nın ana modüllerinden biridir.

### 1.1. Ana Kapsayıcı ve Header Menüsü
- **Kaynak Dosya**: [stabler/public/js/pages/sales/SalesHome.vue](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/public/js/pages/sales/SalesHome.vue)
- **Header Sekme Bileşeni**: [stabler/public/js/components/ModuleHeader.vue](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/public/js/components/ModuleHeader.vue)

Header menüsü, Satış modülü altındaki 7 alt rotayı yatay sekme çubuğu olarak sunar:

| # | Sekme Etiketi | Rota İzi | İkon | Açıklama |
| :-: | :--- | :--- | :--- | :--- |
| **1** | **Customers** | `/sales/customers` | `ti-users` | Müşteri Merkezi, 360° Müşteri Ekstresi ve Alacak Kule |
| **2** | **Quotations** | `/sales/quotations` | `ti-file-description` | Müşteri Satış Teklifleri |
| **3** | **Sales Orders** | `/sales/orders` | `ti-clipboard-check` | Müşteri Siparişleri ve Sipariş Kanban Panosu |
| **4** | **Invoices** | `/sales/invoices` | `ti-file-invoice` | Müşteri Satış Faturaları ve İadeler |
| **5** | **AR Aging** | `/sales/aging` | `ti-clock-hour-4` | Alacak Yaşlandırma Raporu (Aging) |
| **6** | **Reserved Stock** | `/sales/reserved-stock` | `ti-lock` | Müşterilere Rezerve Edilmiş Stok Takibi |
| **7** | **Reports** | `/reports` | `ti-chart-bar` | Satış ve Müşteri Raporları |

---

## 2. Customer Center (Müşteri Merkezi) Kod ve Tasarım Yapısı

### 2.1. Temel Dosya ve Bileşenler
- **Ana Ekran Dosyası**: [stabler/public/js/pages/sales/Customers.vue](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/public/js/pages/sales/Customers.vue) (~1,700 satır Vue 3 Composition API).
- **Yardımcı Bileşenler**:
  - `BalanceChip.vue`: Bakiye ve para birimi rozeti.
  - `PartyAvatar.vue`: Müşteri baş harfleri veya logosu.
  - `PartyPaymentModal.vue`: Müşteriden ödeme alma diyalogu.
  - `ParentBulkPaymentDialog.vue`: Holding/Ana müşteri toplu ödeme diyalogu.
  - `ParentReallocateDialog.vue`: Ödemeleri alt müşteriler arası yeniden tahsis etme.
  - `NewDirectInvoiceModal.vue`: Doğrudan siparişsiz fatura kesme diyalogu.

---

### 2.2. Görünüm Modları: Cockpit (Genel Özet) vs. Customer 360 Workspace

`Customers.vue` ekranı çift modlu bir görünüm mimarisine sahiptir:

#### Mod A: Müşteri Seçilmemişken (`Cockpit View`)
1. **Receivables Cockpit (Alacak Kütüğü & KPI'lar)**:
   - **Toplam Alacak (Total Receivables)**: Aktif şirketin müşterilerden toplam alacak tutarı.
   - **Gecikmiş Alacak (Overdue Balance)**: Vadesi geçmiş alacak tutarı.
   - **8 Haftalık Alacak Trendi**: `ApexChart` sparkline grafiği.
2. **Müşteri Ana Listesi (Master Customer Table)**:
   - **Hiyerarşik Ağaç Modu (Tree View)**: Holding / Ana Müşteri (`parent_customer`) ve alt bayi/şubeler (`level 0` ve `level 1` girintili).
   - **Düz Liste Modu (Flat View)**: Tüm müşteriler düz liste.
   - **Filtre ve Arama**: Arama çubuğu (`search`), Müşteri Grubu (`filterGroup`), Bölge (`filterTerritory`), Sadece Bakiyeliler (`onlyWithBalance`).
   - **URL İletişimi**: `useListViewState` ile arama ve filtre durumları URL query parparametrelerine (`?c=CUSTOMER_NAME&search=...`) eşitlenir.

#### Mod B: Müşteri Seçildiğinde (`Customer 360 Workspace`)
Ekran 2 kolonlu Split Pane / Detay çalışma alanına dönüşür:
- **Sol Kolon (Müşteri Kimlik & Bakiye Özeti)**:
  - Müşteri Adı, Vergi No (`tax_id`), Ülke/Bölge, İletişim e-postası/telefonu.
  - Cari Bakiye Rozeti (`BalanceChip`), Özel Fiyat Listesi, Varsayılan Para Birimi.
- **Aksiyon Çubuğu (Action Bar)**:
  - `+ New Invoice` (Yeni Fatura Kes)
  - `+ Record Payment` (Ödeme Tahsil Et)
  - `Reallocate` (Tahsisat Düzenle)
  - `Export XLSX` (Profesyonel Müşteri Ekstresi İndir)
  - `Edit Customer` (Müşteri Kartını Düzenle)
- **Sağ Sağ Sekme Paneli (Detail Tabs)**:
  - **Ledger (Cari Ekstre)**: Tarih aralığı sorgulu borç/alacak/bakiye hareket listesi.
  - **Invoices (Faturalar)**: Müşterinin faturaları ve ödeme durumları.
  - **Orders (Siparişler)**: Müşterinin aktif ve tamamlanmış siparişleri.
  - **Quotations (Teklifler)**: Müşteriye verilen teklifler.
  - **Analytics (Analitik)**: Müşteri bazlı aylık ciro ve alacak grafiği.

---

## 3. Yeni Modernist Tasarım (`stbl-ds`) Geçiş ve İyileştirme Fırsatları

Claude Design ile yapılacak yeni tasarım görüşmesinde hedeflenen iyileştirmeler:

### 3.1. Header & Subnav Modernizasyonu (`ModuleHeader.vue`)
- Mevcut `ModuleHeader.vue` Bootstrap `nav-bordered` kullanmaktadır.
- **Tasarım Hedefi**: Tender modülündeki `TenderNav.vue` gibi Modernist Tabler çubuğuna (`stbl-ds` tasarım token'ları, `--ds-bg`, `--ds-card-bg`, `--ds-primary`) kavuşturulması.
- Sekme geçişlerinin yumuşak CSS geçişleri (`micro-animations`) ve yüksek kontrastlı aktif çizgi ile vurgulanması.

### 3.2. Customer 360 Split Workspace Tasarımı
- Sol müşteri profil kartı ve sağ ekstre/fatura sekme panellerinin `ds-panel` ve `ds-kpi` yapısına dönüştürülmesi.
- Cari ekstre tablosundaki borç (`Debit`), alacak (`Credit`) ve bakiye (`Balance`) sütunlarının `font-monospace` ve renkli borç/alacak rozetleriyle hizalanması.

### 3.3. Mobil ve Dar Ekran (Responsive Split View) Uyumluğu
- Dar ekranlarda sol müşteri listesi ve sağ detay alanının akıcı geçişi (`drawer` veya tam sayfa split toggle).
- ESC tuşu ile müşteri seçiminden listeye dönme mekanizmasının (`useEscapeBack`) korunması.

---

## 4. Claude Design İçin Kod Kılavuzu Özet Tablosu

| Bileşen / Sayfa | Dosya Yolu | Mevcut Tasarım Katmanı | Hedef Tasarım Katmanı |
| :--- | :--- | :--- | :--- |
| **Sales Parent Shell** | [SalesHome.vue](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/public/js/pages/sales/SalesHome.vue) | Bootstrap Container | `stbl-ds` Modernist Layout |
| **Sales Module Header** | [ModuleHeader.vue](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/public/js/components/ModuleHeader.vue) | Bootstrap Nav Bordered | Modernist Tab Subnav |
| **Customer Center** | [Customers.vue](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/public/js/pages/sales/Customers.vue) | Mixed Bootstrap / Custom | Split 360 Workspace (`ds-panel` + `ds-kpis`) |
| **Sales Order Board** | [SalesOrderBoard.vue](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/public/js/pages/sales/SalesOrderBoard.vue) | Kanban Columns | Modernist Operations Kanban |
