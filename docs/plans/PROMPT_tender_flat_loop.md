# PROMPT — Tender CRM tek seviye + item döngüsü (Antigravity uygulaması)

> Hedef okur: Antigravity (`agy --print` ile verilir; bkz.
> `docs/runbooks/claude-antigravity-orchestration.md`). Talimat **karar-tamdır**:
> boşluk bırakılmaz — her boşluk uydurulmuş davranış olarak geri gelir.
> Bead: `stabler-0b2` · Dal: `feat/mikas-tender-flat-loop`
> Tasarım kaynağı: `docs/design/tender-flow-map.html` (birleşik süreç haritası)

---

## 0. Rol ve mutlak sınırlar

Sen YALNIZCA uygulayıcısın. Tasarım kararları verilmiştir; tartışmazsın, genişletmezsin.

**YASAK olanlar (hiçbir koşulda):**
- `git commit`, `git add`, `git merge`, `git push`, `git rebase`, `git reset`, dal oluşturma/silme
- `deploy_stabler.sh`, SSH, prod, `bench restart`
- İzinli dosya listesi DIŞINDA hiçbir dosyaya dokunmak
- Yeni bağımlılık, yeni stylesheet, yeni tasarım katmanı eklemek

**İzinli dosyalar (tam liste):**

```
stabler/public/js/pages/tender/TenderCrmWrapper.vue
stabler/public/js/pages/tender/TenderCrm.vue
stabler/public/js/pages/tender/TenderPage.vue
stabler/public/js/pages/tender/SourcingWorkspace.vue
stabler/public/js/pages/tender/rfq/RfqDetail.vue
stabler/public/js/components/QuotationEntryDrawer.vue
stabler/public/js/router.js                      (yalnızca import temizliği)
stabler/public/js/pages/tender/TenderMasterBoard.vue   (SİLİNİR)
stabler/public/js/composables/tenderMaster.js          (SİLİNİR)
stabler/api/crm.py
stabler/api/sourcing.py
stabler/api/purchasing.py
stabler/patches/v<next>_sq_rfq_link.py           (YENİ — numarayı patches.txt kuyruğundan al)
stabler/patches.txt                              (tek satır append)
stabler/tests/test_tender_master_board_spa.py
stabler/tests/test_tender_flow_contract.py
stabler/tests/test_sourcing_api.py
stabler/tests/test_sourcing_spa.py
stabler/tests/test_crm_company_scope.py          (yalnızca yeni kapı testi eklenirse)
stabler/tests/test_sq_rfq_link_patch.py          (YENİ)
stabler/tests/test_po_from_quotation.py          (YENİ)
.github/frappe-free-tests.txt                    (yalnızca yeni test modülleri append)
stabler/public/js/tests/rfqDetail.spec.js        (YENİ veya mevcut spec güncellemesi)
stabler/public/js/tests/quotationEntryDrawer.spec.js (YENİ)
stabler/translations/en.csv                      (YALNIZCA en — diğer dillere DOKUNMA)
```

---

## 1. Değişmezler (CLAUDE.md sert kuralları — aynen geçer)

1. **Desk linki yok.** SPA asla `/app/...`'a link vermez, `window.open` etmez.
2. **Para alanları** yalnızca `MoneyInput`; miktarlar `MoneyInput hide-currency`. Bare
   `<input type="number">` yasak. Tarihler yalnızca `DateInput` (ISO v-model), gösterim
   `formatDate`/`formatDateTime` (dd.mm.yyyy). Bare `<input type="date">` yasak.
3. **Tablolar** global striped (`stabler.css`); `class="table-striped"` ASLA elle yazılmaz.
   Para hücreleri `font-monospace`.
4. **Bölge başına tek `.btn-primary`** (kart başlığı / drawer footer / sayfa başlığı).
   İkincil eylemler `btn-outline-secondary` / `btn-ghost-secondary`.
5. **Durum renkleri** yalnızca `getStatusBadgeClass(doctype, status)` /
   `getDocstatusLabel` (`composables/status.js`) — bileşen içi renk haritesi yazılmaz.
   Dense listelerde `StatusIcon.vue` (props: `doctype`, `status`, `size`).
6. **Modül kapısı**: her yeni route `meta: { module: "tender" }` taşır (bu işte yeni route YOK).
7. **Şirket scope'u — 3 kapı sırası**: (1) modül kapısı, (2) `require_selected_company(company)`
   / `_assert_company_scope(company)` — endpoint'in KENDİ tepesinde görünür şekilde
   (`test_company_scope_guard.py` AST ile kaynak parse ediyor, guard bir çağrı derinde
   olursa test göremez), (3) kayıt başına `frappe.has_permission(..., doc=doc)`.
   Yabancı şirket kaydı "Not permitted" ile reddedilir; hata mesajı kaydın varlığını
   ele vermez.
8. **i18n**: tüm yeni kullanıcı metinleri `t("English text")` anahtarıyla, English-first.
   Yalnızca `en.csv`'ye eklenir (dosya sonuna append). `tr/ru/uz/uzc`'ye DOKUNULMAZ —
   backfill ayrı bir adımdır.
9. **Kiracı adına dallanma yasak**: `if company == "mikas"` gibi kod yazılmaz.
10. **Yorum disiplini**: yorum yalnızca kodun kendi söyleyemediği bir kısıt için;
    "burada değiştik" türü PR-notu yorumu yazılmaz.

---

## 2. Tasarım sistemi — mevcut bileşenler ve standartlar

Claude'un tasarım paketi (Imports modülü) main'de ship edilmiştir. **Yeni bileşen
açılmaz; mevcut olanlar kullanılır.** Referans uygulamalar: `pages/imports/CommercialInvoices.vue`
(en eksik örneği), `pages/imports/ImportContainers.vue`.

| Ne | Kaynak | Kural |
|---|---|---|
| Kontrol yüksekliği | grid/toolbar/kart başlığı içi | 24px: `btn-sm` / `form-control-sm` / `Select size="sm"` |
| Kontrol yüksekliği | form detay kartları | 40px: `btn` / `form-control` (üçüncü yükseklik bırakılmaz) |
| Filtre genişlikleri | `<Select style="width: …">` | yalnızca 150 / 170 / 200 px |
| Durum ikonu | `components/StatusIcon.vue` | dense liste kolonlarında; props `doctype`, `status`, `size` |
| Filtre çipleri | `components/FilterChips.vue` | filtre ref'lerinden türeyen `chips` + `@remove` |
| Seçim | `composables/useListSelection.js` | bu işte gerekmez (satır seçimi yok) |
| KPI kartı | `components/KpiCard.vue` | kanbanın kendi KPI şeridi var; kullanılmaz |
| Sayfa kabuğu | `pages/tender/TenderPage.vue` + `ds-*` sınıfları | tüm tender ekranları |

---

## 3. FAZ A — Tek seviyeli Tender CRM

### A1. `TenderCrmWrapper.vue` → doğrudan kanban

Mevcut içerik `route.query?.tender` varsa `TenderCrm`, yoksa `TenderMasterBoard`
render ediyor. Yeni içerik: `TenderCrm`'i **koşulsuz** render et. `?tender=`
query'si yok sayılır (eski URL'ler kanbana düşer; redirect yazılmaz). Route adı
(`tender-crm`) ve path (`/tender/crm`) değişmez. `TenderMasterBoard` import'u silinir.

### A2. `TenderMasterBoard.vue` ve `composables/tenderMaster.js` SİLİNİR

`router.js`'ten importları varsa temizlenir. Board'un benzersiz hiçbir işlevi kalmaz:
orphan paneli (auto-parent sayesinde orphan kalmıyor), KPI rollup'ları (kanban KPI
şeridinde karşılığı var), "Yeni İhale" butonu (A3 ile kanbana taşınıyor).

### A3. `TenderCrm.vue` — düz kanban

1. `?tender=` client-side filtresini kaldır (bugün `crm_board` tüm deal'leri döndürüyor,
   sayfa `custom_parent_tender` eşleşmesiyle filtreliyor — o filtre bloğu silinir).
2. Üstteki parent-board breadcrumb'unu ve `useEscapeBack`'in board'a dönüş hedefini kaldır.
3. **"Yeni İhale" butonu** action satırına (Ara / Kanban-Liste / Yenile'nin yanına,
   `btn-primary` — bölgedeki tek primary): `TenderMasterDrawer`'ı mount eder
   (`open` + `@saved` → `load()`; `deal` prop'u `null`). Drawer'ın edit-mode item
   yükleme davranışı zaten çalışıyor — drawer'a DOKUNMA.
4. **`?deal=` desteği**: mount'ta `route.query.deal` varsa ve kart listesinde
   eşleşen deal varsa o kartın çekmecesini aç (`selectedDeal` ata). OperationsDesk'in
   `/tender/crm?deal=X` link'i bugün anlamsız düşüyor — canlanır.

### A4. `TenderPage.vue` — breadcrumb temizliği

`parentTender` computed + breadcrumb bloğu + `buildTenderQuery` import'u (başka
kullanımı kalmadıysa) kaldırılır. `?tender=` artık hiçbir sayfa üretmiyor.

### A5. `stabler/api/crm.py` — "crm VEYA tender" kapısı

Satış-CRM modülü mikas'ta kapatılacak (`enable_crm=0` — config, deploy notu), ama
tender akışı `crm.save_deal` (ihale girişi) ve `crm.list_deals` (deal seçiciler)
üzerinden geçiyor. Kapı genişletilir:

```python
def _require_crm_or_tender(company: str | None = None) -> str:
    """Module gate for endpoints the TENDER flow shares with sales CRM.

    The tender intake drawer saves deals and both tender deal pickers search
    them through endpoints that used to sit behind the plain CRM gate; a
    tender-only tenant (enable_crm=0) would break its own intake. The gate
    accepts either module — company scoping below it is unchanged.
    """
```

- Yardımcı, mevcut `_require_crm`'in şirket-scope davranışını aynen korur; yalnızca
  modül yetkilendirmesi "crm **veya** tender" olur (`organization.module_map_for`
  / mevcut modül kontrolü desenini izle — `stabler/api/organization.py`'deki
  `_MODULE_ROLES` ve `module_map_for` mevcut kullanıma bak).
- **Yalnızca** `save_deal` ve `list_deals` bu kapıya alınır. Diğer crm uçları
  (`_require_crm`) olduğu gibi kalır — satış-CRM uçları tender tenant'ında kapalı
  kalabilmeli.
- `list_deals`'e opsiyonel `deal_type` parametresi eklenir (additive; filtre
  uygulanırsa `filters["deal_type"] = deal_type`). Tender çağrıcıları
  `deal_type: "Tender"` geçirir ki seçicide satış deal'leri görünmesin:
  - `SourcingWorkspace.vue` `searchDeals`
  - `pages/tender/rfq/RfqForm.vue` `searchDeals`
  - `TenderCrm.vue` içinde varsa benzer arama
- `test_crm_company_scope.py`'ye (veya uygun dosyaya) kapı testi: crm kapalı +
  tender açık → `save_deal`/`list_deals` çalışır; ikisi de kapalı → reddedilir;
  yabancı şirket → reddedilir.

**Deploy notu (talimata not olarak kalır, kod yok):** merge sonrası mikas Company
ayarında `enable_crm=0` kapatılacak. Sidebar'daki CRM maddesi
`session.canAccessModule("crm")`'e bağlı — kendiliğinden kaybolur.

---

## 4. FAZ B — Item döngüsünün üç halkası

### B1. RFQ → Teklif prefill

**Yeni endpoint — `stabler/api/sourcing.py`:**

```python
@frappe.whitelist()
def get_quotation_defaults(deal, rfq=None, company=None):
    """Lines to quote against: the ask, not a blank form.

    A quotation answers a request. When a specific RFQ is given its lines are
    used; otherwise the lot's LATEST open RFQ's. Rates stay empty — the rate
    is the supplier's answer, never prefilled.
    """
```

- 3 kapı (bkz. §1.7). RFQ çözümü: `rfq` verilmişse `custom_crm_deal == deal` ve
  `docstatus < 2` doğrulanır; verilmemişse aynı filtrelerle `transaction_date desc`
  ilk kayıt; hiç yoksa `items: []` döner (hata değil — elle giriş meşru).
- Dönen item satırı: `{item_code, item_name, qty, uom}`.

**`QuotationEntryDrawer.vue`:**
- Yeni prop: `rfq: { type: String, default: "" }`.
- YENİ teklif açılışında (düzenleme değil) ve `deal` doluysa:
  `get_quotation_defaults(deal, rfq, company)` çağır, satırları boş `rate` ile
  forma doldur. Düzenleme akışı (`quotationName` dolu) değişmez — mevcut
  `get_supplier_quotation` yüklemesi kalır.
- Bayat yorumu sil: "endpoint comes in Task 3" içeren blok (`onMounted` üstündeki).
- Validasyon ve kaydet/submit akışı değişmez.

**`SourcingWorkspace.vue`:** "Add quotation" akışına rfq bağlamı: mount'ta
`route.query.rfq` varsa ve `deal` varsa `openAddQuotation()` çağır ve drawer'a
`rfq` prop'u geçir; sonra `router.replace` ile query'den `rfq`'yi temizle.

**`pages/tender/rfq/RfqDetail.vue`:** suppliers tablosunun altına tek
`btn-outline-secondary btn-sm` "Record quotation" →
`router.push({ name: "tender-sourcing", query: buildTenderQuery(route.query, { deal: rfq.deal, rfq: rfq.name }) })`.

### B2. Tur-bazlı cevap takibi

**Yeni patch — `stabler/patches/v<next>_sq_rfq_link.py`**
(`v68_rfq_tender_deal.py`'yi şablon al — DocType varlık kontrolü + Custom Field
`frappe.db.exists` idempotens guard'ı + `patches.txt`'e append):
- Supplier Quotation'a `custom_rfq` (Link → Request for Quotation, label "RFQ",
  Depends on yok, Desk'te görünür).
- Numara: `patches.txt` kuyruğundaki en büyük `vNN`'in bir fazlası; mevcut numara
  TEKRAR KULLANILMAZ (test numara çakışmasını reddediyor).
- Yeni test `test_sq_rfq_link_patch.py`: patch kayıtlı + idempotent + doctype
  yokluğunda erken çıkıyor + numara çakışmıyor (`test_sourcing_api.py`'deki
  `TestRfqPatch` desenini izle). `.github/frappe-free-tests.txt`'e ekle.

**`save_supplier_quotation(..., rfq=None)`:**
- `rfq` verilmişse: RFQ aynı şirkette + `custom_crm_deal == deal` değilse
  `frappe.PermissionError`/`ValidationError` (açık mesaj: başka lotun RFQ'suna
  cevap yazılamaz).
- Yalnızca OLUŞTURMADA yazılır (`frappe.db.has_column` toleransıyla); düzenlemede
  mevcut değer korunur, retag yok.

**`get_rfq` — `responded` artık tur-bazlı:**
- Kolon varsa: SQ filtresi `{custom_rfq: name, docstatus: ["<", 2]}` (deal+supplier
  join yerine). Kolon yoksa (unmigrated) mevcut deal+supplier fallback'u korunur —
  okuma toleransı kuralı.
- `list_all_rfqs` quotation_count lot-seviyesinde kalır (değişmez).

### B3. Ödül → PO

**Yeni endpoint — `stabler/api/purchasing.py`:**

```python
@frappe.whitelist()
def create_po_from_quotation(quotation: str, company: str | None = None):
    """Raise a draft Purchase Order carrying the winning quotation's lines.

    The tender ↔ quotation ↔ PO three-way match is the audit trail: the PO
    inherits item, qty, uom and RATE from the quotation it was awarded from,
    line by line — nothing is retyped, nothing drifts.
    """
```

- Kapılar: mevcut `create_purchase_order`'ın kapı desenini aynen izle
  (şirket scope'u endpoint tepesinde görünür). Ek olarak:
  - SQ: aynı şirket, `docstatus < 2`, deal etiketi (`custom_crm_deal`) dolu olmalı.
  - **İdempotens**: aynı deal + aynı supplier için `docstatus < 2` PO zaten
    varsa YENİ oluşturma — mevcut adı döndür (`{name, existing: True}`).
- PO taslağı: `supplier`, `company`, `currency` (SQ'den), `transaction_date = today`,
  satırlar SQ satırlarından (`item_code, qty, uom, rate`; `schedule_date` satırdan
  veya `valid_till`), `custom_crm_deal = <SQ'nun deal'i>` (v34 alanı zaten var;
  `create_purchase_order`'ın zaten yaptığı yazımı izle). Item varsayılanları
  (uom/conversion) mevcut PO oluşturma yolundaki helper'dan gelir — yeniden
  icat edilmez. **Draft olarak insert edilir; submit edilmez.**

**`SourcingWorkspace.vue` — award paneli:**
- `decisionData.decision.status === "Approved"` iken ve `selected_quotation` doluysa:
  "Create purchase order" düğmesi (`btn-outline-secondary btn-sm` — primary değil,
  bölgedeki primary kaydet/onayla).
- Tık → `create_po_from_quotation` → `toast.success` →
  `router.push({ name: "purchasing-order", params: { name: res.name } })`.
- Aynı quotation için PO zaten varsa (existing) toast bilgi + yine PO'ya gider.

---

## 5. Testler

**Güncellenenler:**
- `test_tender_master_board_spa.py` → tek seviye sözleşmesi: wrapper TenderCrm'i
  koşulsuz render ediyor; TenderMasterBoard/tenderMaster.js depoda YOK; TenderCrm
  "Yeni İhale" butonu + drawer taşıyor; `?deal=` çekmece açıyor.
- `test_tender_flow_contract.py` (iki seviyeyi pinleyen blok ~:115-128) → tek
  seviyeye yeniden yazılır.
- `test_sourcing_api.py` → `get_quotation_defaults` (belirli RFQ / en son RFQ /
  RFQ yoksa boş / yabancı RFQ reddi), `save_supplier_quotation(rfq=)` yazım ve
  retag yasağı, `get_rfq` tur-bazlı responded (kolon var/yok).
- `test_sourcing_spa.py` → drawer prefill sözleşmesi (kaynak-kontrat stili:
  `get_quotation_defaults` çağrısı + rate'in prefilleNMEdiği iddiası).

**Yeni:** `test_sq_rfq_link_patch.py`, `test_po_from_quotation.py`
(kapılar + satır taşıma + idempotens + draft kalır), `test_crm_company_scope.py`
için crm-veya-tender kapı testi. Hepsi `.github/frappe-free-tests.txt`'e eklenir.

**JS spec'leri** kaynak-kontrat stili (`readFileSync` + `toContain` — repodaki
mevcut stil): rfqDetail "Record quotation" bağını, drawer prefill çağrısını,
award panel PO düğmesini iddia eder.

## 6. i18n

Yalnızca `en.csv`, dosya sonuna append. Yeni anahtarlar (tam liste):
`New tender`, `Record quotation`, `Create purchase order`,
`Purchase order created from the quotation.`, `This quotation has no lines.`
Kullanılmayan anahtar eklenmez. Diğer dillere DOKUNMA.

## 7. Doğrulama (sırayla)

```bash
cd <worktree-kökü>
python3 -m py_compile stabler/api/crm.py stabler/api/sourcing.py stabler/api/purchasing.py stabler/patches/v*_sq_rfq_link.py
grep -v -e '^#' -e '^$' .github/frappe-free-tests.txt | xargs -P8 -n1 python3 -m unittest
node_modules/.bin/eslint --config eslint.config.mjs <değişen .js/.vue dosyaları>
make check
```

`make check` blok eden kapıdır: ruff check + ruff format --check + eslint + guards
+ frappe-free suite + vitest. Kırmızıysa düzelt; düzeltemediğin varsa
`deviations`'a yaz, asla geçiştirme.

## 8. Rapor

Bitince rapor şu alanları taşır: `changed_files`, `behavior_implemented`,
`tests_added`, `commands_run` (komut + exit_code), `deviations`. Rapor bir
iddiadır — Claude bağımsız tam-diff incelemesi yapacak.

---

## Launch (Claude tarafı — agy çalıştırılmadan önce)

```bash
# 1. Bu prompt dalda commit'te
# 2. zcode worktree'ini kaldır (dal commit'lerle yerinde kalır), agy worktree'i aç:
git worktree remove .worktrees/zcode-tender-flat-loop
git worktree add .worktrees/agy-stabler-0b2 feat/mikas-tender-flat-loop
# 3. Rapor şemasını yaz (runbook §3) ve agy'yi worktree içinden çalıştır:
cd .worktrees/agy-stabler-0b2
agy --model gemini-3.1-pro-high --effort high --mode accept-edits --sandbox \
  --dangerously-skip-permissions --output-format json \
  --json-schema .worktrees/agy-report.schema.json --print-timeout 60m \
  --print "$(cat ../../docs/plans/PROMPT_tender_flat_loop.md)" > /tmp/agy-stabler-0b2.json
# 4. conversation_id'yi hemen bd'ye yaz:
bd update stabler-0b2 --append-notes "agy conversation_id: <cid> (tur 1)" --json
```

Risk seviyesi ORTA-YÜKSEK (çok dosyalı iş mantığı + patch + kapı değişikliği):
`gemini-3.1-pro-high` uygundur; çok-kiracılık semantiği değişmez (kapı genişletmesi
mevcut deseni izler), migration yalnızca additive Custom Field'dır.
