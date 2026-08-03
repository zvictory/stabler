# Stabler ERP — Modernist Tasarım Sistemi ve Ana Dashboard / Sidebar Mimarisi

Bu doküman, **Stabler ERP** Single Page Application (Vue 3 + Tabler / Stabler Modernist CSS) mimarisi için hazırlanmış kapsamlı kod ve tasarım kılavuzudur. Claude Code ve antrenman modülleri tarafından okunabilir, doğrudan uygulanabilir teknik spesifikasyonları içerir.

---

## 1. Mimarinin Temel İlkeleri (Hard Rules)

Stabler ERP projesinde **asla çiğnenmemesi gereken zorunlu kurallar**:

1. **Hiçbir Zaman Frappe Desk Yönlendirmesi Yok (`/app/...` Yasağı)**:
   - Stabler Vue 3 SPA tamamen bağımsız bir kullanıcı deneyimidir. Kullanıcı hiçbir zaman `/app/...` Desk ekranlarına gönderilemez (`<a href="/app/...">`, `window.open('/app/...')` veya router meta ile).
   - CRUD işlemi eksikse, o ekran Stabler içinde yazılır.

2. **Varsayılan Çizgili Tablolar (`Striped Tables`)**:
   - `stabler/public/css/stabler.css` içindeki küresel kural nedeniyle her `<table>` varsayılan olarak çizgilidir.
   - Manuel `class="table-striped"` eklenmez. İptal etmek için `class="table-no-stripe"` kullanılır.

3. **Para Girişi ve Formatlama (`MoneyInput` & `formatMoney`)**:
   - Parasat tutar, oran ve bakiye içeren tüm sayısal girdiler paylaşımlı `MoneyInput` bileşenini kullanmak zorundadır. Çıplak `<input type="number">` kullanılamaz.
   - Para hücrelerinde rakam hizalaması için `font-monospace` kullanılır.

4. **Tasarım Katmanı Sınırı (`stbl-ds`)**:
   - Taşınan ve modernize edilen tüm ekranların kök elemanı `class="stbl-ds"` alır. Tüm bileşen stilleri ad-hoc sınıflar yerine `stabler-modernist.css` tasarım token'larından türetilir.

---

## 2. Kenar Çubuğu (Sidebar) Menüsü Nasıl Çalışıyor?

### 2.1. Bileşen Yeri ve State Yönetimi
- **Kaynak Dosya**: [stabler/public/js/components/Sidebar.vue](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/public/js/components/Sidebar.vue)
- **Pinia Store**: [stabler/public/js/stores/session.js](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/public/js/stores/session.js)
- **Kapsam Hizalaması**: Kenar çubuğu alt ekranları veya spesifik aksiyonları **değil, yalnızca ana modülleri** listeler.

### 2.2. Veri Akışı ve Rol/Modül Filtreleme
Kenar çubuğundaki menü öğeleri `computed(items)` üzerinden dinamik oluşturulur:
1. `session.canAccessModule(moduleKey)` çağrılarak kullanıcının aktif şirketi için o modülün açık olup olmadığı denetlenir (`stabler.api.organization.boot` verisine dayanır).
2. Şirket bazlı 15 modül (`money`, `sales`, `purchasing`, `imports`, `inventory`, `manufacturing`, `hr`, `sfa`, `marketing`, `crm`, `tender`, `service`, `bpm`, `remittance`, `installment`) filtrelenir.
3. Yöneticiler (`session.isAdmin`) ek olarak `Admin` (`/admin`) menüsünü görür.

```javascript
// Sidebar.vue içinde modüllerin gruplanması
const sections = computed(() => {
	const byName = new Map(items.value.map((item) => [item.name, item]));
	const groups = [
		{ label: "", names: ["dashboard"] },
		{ label: t("Commerce"), names: ["pos", "sales", "crm", "sfa", "marketing"] },
		{ label: t("Operations"), names: ["purchasing", "imports", "tender", "inventory", "manufacturing", "service", "bpm"] },
		{ label: t("Finance"), names: ["money", "remittance", "installment"] },
		{ label: t("Company"), names: ["hr", "reports", "admin"] },
	];
	return groups
		.map((group) => ({
			label: group.label,
			items: group.names.map((name) => byName.get(name)).filter(Boolean),
		}))
		.filter((group) => group.items.length);
});
```

### 2.3. Aktif Şirket Değişimi (`Company Context Switching`)
Kenar çubuğunun alt kısmında `Select.vue` bileşeni yer alır:
- Kullanıcı aktif şirketi değiştirdiğinde `session.setCompany(value)` tetiklenir.
- Pinia store `/api/method/stabler.api.organization.switch_company` çağrısı yaparak modül izinlerini, para birimini ve şirket verilerini yeniler.
- Tüm açık sayfalar (Dashboard, CRM, Sourcing) `watch(activeCompany, load)` ile kendilerini anında yeniler.

### 2.4. Kullanıcı Menüsü ve Güvenli Oturum Kapatma (`Logout`)
- Sol alt tarafta avatar, kullanıcı adı ve aktif şirket gösterilir.
- Tıklandığında floating `userMenuStyle` menüsü açılır (Dil değişimi: EN/RU/UZ/UZC/TR ve Çıkış yap).
- **Çıkış Butonu**: `stabler.api.organization.stabler_logout` endpoint'ine güvenli `POST` isteği gönderir ve `finally` bloğunda `hardRedirect('/login')` çalıştırarak kullanıcıyı her koşulda temiz bir şekilde login ekranına aktarır.

---

## 3. Ana Dashboard (`Dashboard.vue`) Mevcut Durumu

### 3.1. Rota Yönlendirmesi ve Kapsam
- **Kaynak Dosya**: [stabler/public/js/pages/Dashboard.vue](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/public/js/pages/Dashboard.vue)
- **Router Guard** ([router.js](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/public/js/router.js)):
  ```javascript
  if (to.path === "/dashboard" && session.canAccessModule("tender")) {
      return "/tender/portfolio";
  }
  ```
  - İhale/Tender modülü aktif olan şirketlerde `/dashboard` çağrısı otomatik olarak `/tender/portfolio` ekranına yönlendirilir.
  - İhale dışı veya genel şirketlerde ise `Dashboard.vue` Finansal Özet & İthalat Panosu olarak hizmet verir.

### 3.2. Veri Kaynakları ve API Çağrıları
`Dashboard.vue` yüklendiğinde `Promise.all` ile paralel 4 API çağrısı yapar:
1. `dashboardApi.summary(company)` (`stabler.api.dashboard.summary`): Nakit (Cash), Alacaklar (AR), Borçlar (AP) ve MTD Gelir özeti.
2. `dashboardApi.revenueTrend(company, 12)` (`stabler.api.dashboard.revenue_trend`): Son 12 ayın Gelir vs. Gider trend verisi (ApexCharts için).
3. `dashboardApi.recentActivity(company, 8)` (`stabler.api.dashboard.recent_activity`): Son 8 işlem akışı.
4. `stabler.api.inventory.low_stock_alerts` (`limit: 6`): Düşük stok kritik uyarıları.

---

## 4. Ana Dashboard'u Yeni Modernist Tasarıma (`stbl-ds`) Geçirme Planı

Mevcut `Dashboard.vue` kısmen eski Bootstrap izleri taşımaktadır (`card`, `row`, `col-md-6`). Bunu Tender / Sourcing Operations Desk (`OperationsDesk.vue` & `DirectorBoard.vue`) standartlarındaki **Modernist Tasarım Katmanına** geçirmek için aşağıdaki adımlar uygulanmalıdır:

### 4.1. Kök Yapı ve Grid Mimarisi
Sayfanın kök elemanı `<div class="dashboard-page stbl-ds">` yapılmalı ve Tabler ızgarası yerine `ds-kpis` ve `ds-panel` bileşen düzeni kullanılmalıdır:

```html
<template>
  <div class="dashboard-page stbl-ds">
    <!-- Sayfa Başlığı -->
    <header class="ds-page-head">
      <h1>{{ t("Executive Dashboard") }}</h1>
      <div class="ds-meta">
        <span>{{ activeCompany }}</span> · <span>{{ currency }}</span>
      </div>
      <div class="ds-actions">
        <button class="ds-btn" @click="load">{{ t("Refresh") }}</button>
      </div>
    </header>

    <!-- 1. KPI Şeridi (Modernist Scorecards) -->
    <div class="ds-kpis" data-cols="4">
      <div class="ds-kpi" data-sev="neutral">
        <div class="ds-label">{{ t("Cash & Bank") }}</div>
        <div><span class="ds-kpi-val">{{ formatMoney(cashTotal) }}</span></div>
        <div class="ds-kpi-note">{{ t("Available liquid balance") }}</div>
        <div class="ds-kpi-q">tabGL Entry · account_type = Bank/Cash</div>
      </div>
      <div class="ds-kpi" data-sev="ok">
        <div class="ds-label">{{ t("Receivables (AR)") }}</div>
        <div><span class="ds-kpi-val">{{ formatMoney(arTotal) }}</span></div>
        <div class="ds-kpi-note">{{ t("Outstanding customer invoices") }}</div>
        <div class="ds-kpi-q">tabSales Invoice · outstanding > 0</div>
      </div>
      <div class="ds-kpi" data-sev="soon">
        <div class="ds-label">{{ t("Payables (AP)") }}</div>
        <div><span class="ds-kpi-val">{{ formatMoney(apTotal) }}</span></div>
        <div class="ds-kpi-note">{{ t("Pending supplier payments") }}</div>
        <div class="ds-kpi-q">tabPurchase Invoice · outstanding > 0</div>
      </div>
      <div class="ds-kpi" data-sev="neutral">
        <div class="ds-label">{{ t("Revenue (MTD)") }}</div>
        <div><span class="ds-kpi-val">{{ formatMoney(revenueMtd) }}</span></div>
        <div class="ds-kpi-note">{{ trendPct ? `${trendPct}% vs last month` : t("Current month total") }}</div>
        <div class="ds-kpi-q">sum(sales_invoice.grand_total)</div>
      </div>
    </div>

    <!-- 2. Grafikler ve İşlem Akışı Panelleri -->
    <div class="dashboard-grid">
      <!-- Gelir / Gider Grafiği Paneli -->
      <section class="ds-panel">
        <div class="ds-panel-head">
          <h2>{{ t("Financial Trend (12 Months)") }}</h2>
        </div>
        <div class="ds-panel-body">
          <ApexChart type="area" height="280" :options="revenueChartOptions" :series="chartSeries" />
        </div>
      </section>

      <!-- Düşük Stok Uarıları Paneli -->
      <section class="ds-panel">
        <div class="ds-panel-head">
          <h2>{{ t("Low Stock Alerts") }}</h2>
          <span class="ds-label">{{ lowStock.length }} {{ t("items") }}</span>
        </div>
        <div class="ds-panel-body">
          <table class="table text-nowrap">
            <thead>
              <tr>
                <th>{{ t("Item") }}</th>
                <th class="text-end">{{ t("Available") }}</th>
                <th class="text-end">{{ t("Min Level") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in lowStock" :key="item.item_code">
                <td>
                  <div class="fw-semibold">{{ item.item_name || item.item_code }}</div>
                  <div class="text-muted small">{{ item.item_code }}</div>
                </td>
                <td class="text-end font-monospace text-danger fw-bold">{{ item.actual_qty }} {{ item.stock_uom }}</td>
                <td class="text-end font-monospace text-muted">{{ item.min_order_qty || 0 }} {{ item.stock_uom }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </div>
</template>
```

---

## 5. Claude Code İçin Stabler ERP Genel Tasarım Dokümanı Spesifikasyonu

Claude Code ile geliştirme yaparken referans alınacak **Stabler ERP Modernist Tasarım Sözlüğü**:

### 5.1. Sınıf ve Eleman Hiyerarşisi (`CSS Rules`)
- **Kök Eleman**: `<div class="stbl-ds">` (Sayfa bazında kapsayıcı).
- **Sayfa Başlığı**: `<header class="ds-page-head">`
  - `<h1>Title</h1>`: Sayfa ana başlığı.
  - `<div class="ds-meta">`: Alt metinler ve durum etiketleri.
  - `<div class="ds-actions">`: Sayfa seviyesi aksiyon butonları (`ds-btn`).
- **Paneller**: `<section class="ds-panel">`
  - Başlık: `<div class="ds-panel-head"><h2>...</h2></div>`
  - İçerik: `<div class="ds-panel-body">...</div>`
- **KPI Kartları**: `<div class="ds-kpis" data-cols="3|4">`
  - Severities (`data-sev`): `neutral` (gri/mavi), `ok` (yeşil), `soon` (turuncu/kahve), `crit` (kırmızı).
  - Elemanlar: `.ds-label` (etiket), `.ds-kpi-val` (büyük değer), `.ds-kpi-note` (açıklama), `.ds-kpi-q` (veritabanı kural dipnotu).

### 5.2. Tablo Standartları
- Her `<table>` otomatik olarak çizgilidir (`stabler.css`).
- Parasay değerler içeren sütun hücrelerinde: `<td class="text-end font-monospace">` kullanılır.
- Durum rozetleri için `<StatusBadge :status="row.status" />` kullanılır.

### 5.3. Buton ve Form Standartları
- Düğmeler: `<button class="ds-btn" :data-tone="primary|success|danger">`
- Metin Girdileri: `class="ds-input"`
- Sayısal / Para Girdileri: `<MoneyInput v-model="form.amount" :currency="currency" />`

---

## 6. Geliştirme Yol Haritası (Claude Code Prompt Hazırlığı)

Claude Code'a verilecek görev adımları:
1. `Dashboard.vue` bileşeninin template yapısını `stbl-ds` Modernist bileşen düzenine dönüştür.
2. Bootstrap `card`, `col-md-*` sınıflarını temizle; `ds-kpis` ve `ds-panel` yapılarını yerleştir.
3. Para birimi gösterimlerinde `font-monospace` ve `MoneyInput` uyumluluğunu sağla.
4. `npx vitest run` ve `bench build --app stabler` çalıştırarak sıfır hata ile doğrula.
