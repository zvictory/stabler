# Party Center — QuickBooks tarzı 2-pane yeniden tasarımı

**Tarih:** 2026-08-05
**Kapsam:** Hedefli iyileştirme (tam QB paritesi değil) + `Customers.vue` ve
`Suppliers.vue`'nin ortak `PartyCenter` bileşenine çıkarılması.
**Görsel referans:** `Customer Center - Modernist Tabler.dc.html` (Claude Design
component). Bu doküman = **Vue uygulama planı**; DC dosyası = **görsel spesifikasyon**.
Kaynak spec: `HANDOFF-CustomerCenter.md` + `stabler_modernist_design_guide.md`.
**Etkilenen tenant'lar:** hepsi (sales = anjan/dts/horeca, purchasing = msa/mikas).
Shared-core UI değişikliği → modül gate'i gerekmiyor, ama davranış her tenant'ta
aynı kalmalı.

---

## 1. Mevcut durum (baseline)

| | `sales/Customers.vue` | `purchasing/Suppliers.vue` |
|---|---|---|
| Satır | 1715 | 1748 |
| Layout | `col-md-5 col-lg-4` / `col-md-7 col-lg-8` | aynı |
| CSS sınıfları | `cust-merged-list` / `cust-merged-pane` | **aynı sınıf adları** (kopya) |
| Cockpit | `receivables_cockpit` | `payables_cockpit` |
| Hiyerarşi | var (parent_customer + job_status) | yok |
| Tab'lar | Children / Ledger / Orders / Invoices | Ledger / Orders / Invoices |

İki dosya ~%80 aynı. Ledger bloğu, cockpit bloğu, liste bloğu, create/edit modal
iskeleti, `useListViewState` kullanımı, ESC davranışı — hepsi kopyalanmış.

### Mevcut güçlü yanlar (korunacak)

- **Customer:Job hiyerarşisi** — tree/flat toggle, chevron expand, kümülatif
  parent bakiyesi (`customer_children_balance_map`), `include_children`
  konsolide görünüm switch'i. QB'nin Customer:Job modeliyle birebir.
- **Ledger** — opening balance satırı, running balance kolonu, çoklu para birimi
  tespiti + uyarı, saf FX-revaluation satırlarının filtrelenmesi, voucher tipi /
  tarih / metin filtreleri, `export_report_xlsx` ile profesyonel Excel export.
- **Cockpit** — seçim yokken toplam alacak, bugünkü tahsilat, 8 haftalık trend,
  Top 10 borçlu. QuickBooks'ta karşılığı yok, kaybetmeyelim.
- **URL/localStorage state** — `useListViewState` ile `?c=<name>` senkronu,
  refresh sonrası aynı müşteri açık kalıyor.

### Kapatılacak açıklar

| # | Açık | Etki |
|---|---|---|
| A1 | `email_id` / `mobile_no` / `tax_id` sağ pane'de **hiç gösterilmiyor** — sadece edit modalında | Kullanıcı müşteriyi aramak için modal açmak zorunda |
| A2 | Adres / contact hiç yok (Frappe `Address` / `Contact` link'leri kullanılmıyor) | Fatura adresi ERP dışında tutuluyor |
| A3 | `ListToolbar.vue` kullanılmıyor (35 sayfa kullanıyor) | CLAUDE.md ihlali, görsel tutarsızlık |
| A4 | `SkeletonRows.vue` yok, 4 yerde boşlukta `spinner-border` | CLAUDE.md ihlali ("Never show a spinner in a void") |
| A5 | Ledger / Orders / Invoices 3 ayrı tab | QB tek "Transactions" listesi + filtre kullanır; 3 tab gezinme maliyeti |
| A6 | Sabit `calc(100vh - 12rem)` / `calc(100vh - 20rem)` yükseklikler, sürüklenemez splitter | Zoom / küçük ekranda bozuluyor |
| A7 | ~3400 satır kopya kod | Her düzeltme iki yerde yapılıyor, drift riski |

---

## 2. Hedef tasarım

### 2.1 Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│  ModuleHeader                                                            │
├───────────────────────────┬──────────────────────────────────────────────┤
│ ListToolbar               │  ┌── IDENTITY CARD ─────────────────────┐    │
│  [🔍 Search…      ⌘K]     │  │ (AV)  ACME TRADING LLC     [Parent]  │    │
│  [Status ▾] [Group ▾] [⇄] │  │       CUST-0042                      │    │
│  Count: 128   [+ New]     │  │  ✉ info@acme.uz   ☎ +998 90 123 45 67│    │
├───────────────────────────┤  │  # TAX 302 456 789   Grup: Toptan    │    │
│ ▾ ACME TRADING     [3]    │  │                    [Edit] [Payment]  │    │
│   ├ Chilonzor      12.4M  │  │                    [+ New Invoice]   │    │
│   ├ Yunusobod       0.0   │  └──────────────────────────────────────┘    │
│   └ Sergeli         3.1M  │  ┌── KPI ───────────────────────────────┐    │
│ ▾ BETA SAVDO       [0]    │  │ Bakiye │ Vadesi Geçen │ Ciro │ Son Ö.│    │
│   ...                     │  └──────────────────────────────────────┘    │
│                           │  [☑ Alt müşteriler dahil]      (parent ise)  │
│                           │  ┌──────────────────────────────────────┐    │
│                           │  │ Hareketler │ Alt Müşteriler │ Bilgi  │    │
│                           │  ├──────────────────────────────────────┤    │
│                           │  │ Göster: [Tümü ▾] [01.01▾-05.08▾]     │    │
│                           │  │         [🔍 Belge no…]      [Excel]  │    │
│                           │  ├──────────────────────────────────────┤    │
│                           │  │ Tarih│Tip│Belge│Borç│Alacak│Bakiye   │    │
│ ─────────────────────     │  │ ...                                  │    │
│ Toplam alacak   47.2M     │  └──────────────────────────────────────┘    │
└───────────────────────────┴──────────────────────────────────────────────┘
                            ▲
                       sürüklenebilir splitter
```

### 2.2 Değişiklikler (madde madde)

**S1 — Sol pane: `ListToolbar.vue`'ye geçiş**
`#filters` slot'una Status / Group / Territory Select'leri, `#summary` slot'una
"Toplam alacak" konur, `primaryLabel` = "Yeni". Kendi arama input'u + kbd
kaldırılır (ListToolbar zaten 300ms debounce + ⌘K veriyor). Tree/flat toggle
`#filters` slot'una ghost-secondary ikon buton olarak taşınır.

`onlyWithBalance` checkbox'ı → **tek Status dropdown**'a dönüşür (QB deseni):
`Tümü` / `Bakiyesi olanlar` / `Vadesi geçenler`. Üçüncü seçenek yeni; backend
`list_customers_with_balances`'e `only_overdue` parametresi eklenir.

**S2 — Sol pane: `SkeletonRows` + boş durum**
`spinner-border` → `<SkeletonRows :rows="8" :cols="2" />` `<tbody>` içine.
Aynısı ledger (`:cols="5"`), orders (`:cols="4"`), invoices (`:cols="5"`) için.
Cockpit'teki spinner de skeleton kartlara döner.

**S3 — Sağ pane: Identity Card (A1 + A2)**
Header bloğu iki satıra çıkar:
- 1. satır: avatar, isim, parent breadcrumb, ID, aksiyon butonları (mevcut)
- 2. satır (**yeni**): `✉ email_id` (mailto link), `☎ mobile_no` (tel link),
  `# tax_id`, `customer_group`, `territory`, `default_currency` — hepsi
  `small text-secondary`, boş olanlar hiç render edilmez.

Adres (A2) bu fazda **kapsam dışı** — Frappe `Address`/`Contact` link'leri ayrı
bir iş kalemi. Identity Card'da yer ayrılır, veri sonra bağlanır.

`customer_detail` / `supplier_detail` endpoint'lerine bu alanlar eklenir (şu an
dönmüyor).

**S4 — Tab'lar: Ekstre / Faturalar / Siparişler / Teklifler / Analitik**
HANDOFF'un 5 sekmeli düzeni esas alındı (Customer:Job hiyerarşisi varsa başa
**Alt müşteriler** eklenir). Birleşik tek liste fikri kapsam dışına alındı —
ekstre GL tabanlı running-balance semantiğini korumalı, sipariş/teklif ise
belge listesi; tek tabloda ikisi tutarsız kolonlar üretiyor.

**Ekstre** tab'ında üst filtre çubuğu: tarih aralığı · "Yalnız açık kalemler"
toggle · belge/açıklama arama · sağda **Devreden** bakiyesi. Tablo kolonları
`Tarih · Belge/açıklama · Borç · Alacak · Bakiye` — belge no ve açıklama tek
hücrede iki satır (dar ekranda kolon sıkışmasını önler), tip rozeti
(`FATURA` / `TAHSILAT`) belge no'nun solunda.

USD hareketlerinin altında koşullu kur satırı: `#eef4fb` zemin +
`border-left:3px solid #206bc4` → `1 USD = 12 101,85 UZS · 5 363,64 USD`.
Yerli para satırlarında hiç çizilmez. Tablo altında toplam şeridi:
hareket sayısı · borç toplamı (`#b32424`) · alacak toplamı (`#1c7a3a`) · bakiye.

**S5 — Splitter (A6)**
Bootstrap `col-*` sabit gridi → CSS Grid + sürüklenebilir ayraç:
```css
.party-center { display: grid; grid-template-columns: var(--pc-left, 22rem) 4px 1fr; }
```
Genişlik `localStorage["stabler.partyCenter.leftWidth"]`'te tutulur, min 18rem /
max 40rem clamp'lenir. `<md` breakpoint'te tek kolona düşer (liste → seçince
detay full-screen, geri butonu ile listeye dönüş).

Sabit `calc(100vh - Xrem)` yükseklikler kaldırılır; her iki pane
`height: 100%; min-height: 0; overflow-y: auto` ile flex/grid'den yükseklik alır.

**S6 — `PartyCenter.vue` ortak bileşeni (A7)**
`components/party/` altına:

```
components/party/
  PartyCenter.vue        ← layout + splitter + state orkestrasyonu
  PartyList.vue          ← sol pane (toolbar + tree/flat tablo + footer)
  PartyIdentityCard.vue  ← sağ pane header + iletişim satırı
  PartyKpiStrip.vue      ← 4 KPI kartı
  PartyTransactions.vue  ← birleşik hareketler tab'ı (ledger + orders)
  PartyChildren.vue      ← alt müşteri tablosu (opsiyonel, prop ile açılır)
```

`PartyCenter.vue` prop sözleşmesi:

```js
defineProps({
  partyType:   { type: String, required: true },   // "Customer" | "Supplier"
  api: {                                           // endpoint adları
    type: Object, required: true,
    // { list, detail, ledger, orders, cockpit, childrenBalanceMap?,
    //   get, create, update, remove }
  },
  labels:      { type: Object, default: () => ({}) }, // i18n override'ları
  hierarchy:   { type: Boolean, default: false },  // Customer'da true
  cockpit:     { type: Boolean, default: true },
  stateKey:    { type: String, required: true },   // useListViewState anahtarı
  routes: {                                        // voucher → route eşlemesi
    type: Object, required: true,
    // { invoice: "/sales/invoices/:name", order: "/sales/orders/:name", ... }
  },
});
```

Slot'lar: `#actions` (header butonları — Payment/Reallocate/New Invoice tenant'a
göre değişiyor), `#form-fields` (create/edit modal alanları), `#extra-tabs`.

`Customers.vue` ve `Suppliers.vue` bu bileşeni saran ~150 satırlık ince
wrapper'lara iner. Hedef: 3463 satır → ~1400 satır (ortak) + 2×150 (wrapper).

**S6b — Modernist token'ları (`stbl-ds`)**
Kök eleman `class="stbl-ds"`. Bootstrap `card` / `col-md-*` kalkar, yerine
`ds-panel` / `ds-kpis` / `ds-btn` / `ds-input` gelir. Sabit palet:
`bg #f6f8fb · panel #fff · primary #206bc4 · ink #1d273b · mut #667382 ·
faint #9099a6 · çizgi #e3e5e8 · ok #2fb344/#1c7a3a · warn #f76707/#9a4d06 ·
danger #d63939/#b32424`. Köşe yarıçapı **0**. Bölüm başlıkları
`border-bottom:2px solid rgba(29,39,59,.32)`. Başlıklar Archivo 800.
Tüm sayılar mono + sağa hizalı. Hit target ≥ 44px. Aktif sekme
`border-bottom:3px solid #206bc4` + `margin-bottom:-2px`.

**S7 — Button hierarchy uyumu**
CLAUDE.md: bölge başına tek `.btn-primary`. Sol toolbar'da `Yeni` primary,
sağ header'da `Yeni Fatura` primary — ayrı bölgeler, uygun. Diğer tüm aksiyonlar
`btn-outline-secondary` kalır. Yeni eklenen hiçbir buton primary olmayacak.

---

## 3. Backend değişiklikleri

| Endpoint | Değişiklik |
|---|---|
| `stabler.api.sales.list_customers_with_balances` | `only_overdue` parametresi (Status dropdown'ın 3. seçeneği) |
| `stabler.api.sales.customer_detail` | dönen payload'a `email_id`, `mobile_no`, `tax_id`, `customer_group`, `territory`, `default_currency` |
| `stabler.api.purchasing.list_suppliers_with_balances` | aynı `only_overdue` |
| `stabler.api.purchasing.supplier_detail` | aynı iletişim alanları (`email_id`, `mobile_no`, `tax_id`, `supplier_group`) |

Yeni doctype / yeni alan **yok** — hepsi mevcut Frappe standart alanları.
Migration / patch gerekmiyor.

---

## 4. i18n

Yeni string'ler (5 dil: en/ru/uz/uzc/tr):

```
Transactions, Show, All (ledger), Orders, Returns, Journal,
Customers with open balances, Overdue customers,
Contact, Tax ID, Group, Territory,
Back to list
```

`bench --site <site> execute stabler.translations.harvest.run` ile harvest,
ru/uz/uzc elle doldurulur.

---

## 5. Uygulama sırası

1. **Backend** — 4 endpoint güncellemesi + testleri. Tek başına deploy edilebilir,
   frontend'i bozmaz (yeni alanlar additive).
2. **`components/party/*`** — yeni bileşenler, henüz kimse kullanmıyor.
3. **`Customers.vue` → wrapper.** Tek sayfa, tek tenant grubunda (anjan) smoke.
4. **`Suppliers.vue` → wrapper.** msa/mikas'ta smoke.
5. **Eski `cust-merged-*` CSS'lerinin silinmesi.**
6. i18n harvest + çeviri.

Her adım ayrı commit (CLAUDE.md: `git add -A` yok, explicit path).

---

## 6. Kabul kriterleri

- [ ] `?c=<name>` URL'i ile direkt açılış ve refresh çalışıyor (her iki sayfada)
- [ ] ESC → seçim temizleniyor, ikinci ESC → modül ana sayfasına
- [ ] Parent müşteride kümülatif bakiye ve "Own" kırılımı aynı değerleri veriyor
      (regresyon: `customer_children_balance_map` çıktısıyla karşılaştır)
- [ ] Ledger opening + running balance, mevcut sürümle **birebir aynı** sayılar
- [ ] Excel export aynı dosyayı üretiyor
- [ ] Çoklu para birimi uyarısı hâlâ çıkıyor; FX-revaluation satırları hâlâ gizli
- [ ] Hiçbir yerde boşlukta spinner yok — hepsi `SkeletonRows`
- [ ] Hiçbir yerde bare `<input type="date">` veya ham ISO tarih yok
- [ ] Her bölgede en fazla 1 `.btn-primary`
- [ ] Splitter genişliği refresh sonrası korunuyor; `<md`'de tek kolon + geri butonu
- [ ] `/app/...` Desk linki yok
- [ ] 5 dilde yeni string eksiği yok
- [ ] `bench build --app stabler` temiz

---

## 7. Kapsam dışı (bilinçli)

QuickBooks'ta olup bu fazda **yapılmayacaklar** — ayrı iş kalemi:

- Sol pane'de "Transactions" tab'ı (tüm partiler genelinde işlem listesi)
- Contacts / To Do's / Notes / Sent Email tab'ları (yeni doctype gerekir)
- Dosya eki (Attach) kolonu
- "Reports for this Party" hızlı rapor bloğu
- Üst toolbar (New ▾ / Print ▾ / Excel ▾ / Word ▾)
- Adres (Bill-to / Ship-to) — Identity Card'da yer ayrıldı, veri sonra bağlanacak
