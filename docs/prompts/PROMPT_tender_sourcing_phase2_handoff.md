# Stabler · Tender Sourcing Faz 2 — devam promptu

> **Bu dosya bir devir belgesidir.** Faz 2'nin ilk üç görevi bitti ve commit'lendi;
> kalan işler burada, kabul kriterleriyle. Kod yazan ajan bu dosyayı tek başına
> okuyup devam edebilmeli — başka bir konuşmanın bağlamına ihtiyaç duymamalı.

**Repo:** `~/frappe-bench-local/apps/stabler`
**Dal:** `design/modernist-operations-desk`
**Devraldığın son commit:** `2442b9a feat(tender): the award, as a record rather than a highlighted row`

---

## 0. Önce oku, sonra yaz

Sırayla, atlamadan:

1. `CLAUDE.md` — projenin sert kuralları. Aşağıdakiler ihlal edilirse PR reddedilir.
2. `docs/superpowers/specs/2026-07-30-hierarchical-tender-crm-design.md` — onaylı tasarım (§5 sourcing zinciri, §7 bugün/hedef).
3. `docs/superpowers/plans/2026-07-30-tender-sourcing-rfq-award.md` — Faz 2 planı. **Görev 0, 1, 2 ve 3'ün 1-2. adımları BİTTİ.** Kalanı bu dosyanın §3'ünde.
4. `stabler/api/sourcing.py` — Faz 2'nin tamamının sunucu tarafı. Modülün başındaki docstring üç kapıyı anlatıyor; aynı deseni koru.

### Pazarlık edilemeyen kurallar

| Kural | Nerede kilitli |
|---|---|
| `/app/...` (Frappe Desk) linki YASAK. Eksik CRUD Stabler içinde yazılır. | `test_tender_master_spa_contract`, `test_sourcing_spa` |
| Para → `MoneyInput`, tarih → `DateInput`. Çıplak `<input type="number">` / `type="date"` yok. | `test_sourcing_spa` |
| Her yeni kullanıcı metni **beş CSV'ye** (`en,ru,uz,uzc,tr`) girer. LF satır sonu, dosyanın sonuna eklenir, mevcut satırlar yeniden yazılmaz. | `test_tender_dashboard_i18n` |
| `company` argümanı alan her `@frappe.whitelist()` fonksiyonu, **kendi gövdesinde** bir şirket kapısı çağırır (`_assert_company_scope`). Bir yardımcı fonksiyonun içine gizlenmiş kapı sayılmaz. | `test_company_scope_guard` (AST tabanlı) |
| Frappe-free testler `.github/frappe-free-tests.txt`'e kaydedilir. | `make test` / CI `lint-and-unit` |
| `ruff` **0.16.0**'a sabitli, `line-length = 110`, sekme girinti. | `.ruff-version`, `pyproject.toml` |
| `git add -A` YASAK — yollar tek tek stage'lenir. | CLAUDE.md |
| Commit trailer: `Co-Authored-By: Claude <noreply@anthropic.com>` (sürüm numarası YOK). | CLAUDE.md |
| `patches.txt` sırayla ilerler ve **numara tekrar kullanılamaz**. Şu an en yüksek: **v68**. | `test_sourcing_api.TestRfqPatch` |

### Testleri çalıştırma

```bash
cd ~/frappe-bench-local/apps/stabler
python3 -m unittest stabler.tests.test_sourcing_api -v          # tek modül
make test                                                        # frappe-free kapı
npm run test:js                                                  # vitest
make check                                                       # ruff + eslint + hepsi
```

**Mevcut borç — sana ait değil, dokunma:** `test_director_board_source`,
`test_operations_desk_source`, `test_seed_tender_demo`, `test_tender_crm_source`,
`test_tender_flow_source`. Bunlar `e5a7bfe`'de de kırmızıydı. Kendi
değişikliğinin bir testi kırıp kırmadığını anlamak için:
`git stash && make test && git stash pop` ile öncesini/sonrasını karşılaştır.

---

## 1. Şu an ne çalışıyor (BİTTİ — yeniden yazma)

### `v68` — RFQ lot'a bağlandı
`stabler/patches/v68_rfq_tender_deal.py` → `custom_crm_deal` alanı Request for
Quotation üzerinde (v30'un Supplier Quotation'da yaptığının aynısı). Çift
çalıştırma güvenli, doctype yoksa erken dönüyor.

### `stabler/api/sourcing.py` — 7 uç nokta

| Uç nokta | Kapı | Ne yapar |
|---|---|---|
| `list_rfqs(deal, company)` | tender | Lot'un iptal olmayan RFQ'ları. Migrate edilmemiş sitede boş döner. |
| `create_rfq(deal, suppliers, items, schedule_date, company)` | tender | **Taslak** RFQ üretir, lota etiketler. **E-posta göndermez.** |
| `save_supplier_quotation(deal, supplier, currency, items, valid_till, name, company)` | tender | Taslak SQ oluşturur/günceller. Düzenleme satırları **değiştirir**, eklemez. |
| `submit_supplier_quotation(name, company)` | tender + `submit` hakkı | Taslağı kesinleştirir. Ayrı çağrı, ayrı hak. |
| `get_sourcing_decision(deal, company)` | tender | Açık award + karşılaştırma, tek çağrıda. |
| `save_sourcing_decision(deal, selected_quotation, selection_reason, …)` | tender + **sourcing** görünümü | Taslak award. Snapshot'ı SUNUCU hesaplar. |
| `approve_sourcing_decision(name, company)` | tender + **director** görünümü | Onaylar, damgayı sunucu yazar. |

### `Tender Sourcing Decision` doctype
`stabler/stabler/doctype/tender_sourcing_decision/`. Üç kural **controller'da**:
onay damgasını sunucu yazar, statü tek yönlü (Draft → Approved), 5 teklif / 2
ülke kuralının altındaki ihale **yazılı istisna** ister. Sayılar (`quotation_count`,
`country_count`) belgenin üzerinde — kural kaydın kendisinden denetlenebilsin diye.

### Arayüz
- `components/QuotationEntryDrawer.vue` — `/tender/sourcing`'de "Teklif ekle" ile açılır.
- `pages/tender/TenderFunnel.vue` — chevron pipeline şeridi (`pipeline-strip` prop'u), tıklayınca `select` yayınlar.
- `pages/tender/DirectorBoard.vue` — şerit seçimiyle belge tablosunu süzer, URL anahtarı `?phase=`.

### Testler (hepsi yeşil)
`test_sourcing_api.py` (58), `test_sourcing_decision.py` (22),
`test_sourcing_spa.py` (15), `test_tender_pipeline_strip.py` (17).

---

## 2. Bu oturumda düşülen tuzaklar — tekrar düşme

1. **`_` gölgeleme.** `_, company = helper()` yazma. Modülde `from frappe import _`
   var; tuple unpacking gettext'i eziyor ve sonraki `frappe.throw(_("…"))` çağrısı
   izin hatası yerine `TypeError: '_Doc' object is not callable` atıyor —
   **sessizce yanlış istisna atan bir güvenlik kapısı.** `_lot, company = …` kullan.
2. **Yardımcı metot adı alan adıyla çakışabilir.** Controller'da `_previous()` diye
   bir metot, `_previous` diye bir alanla gölgelenir. `_committed_state()` gibi
   çakışmayacak adlar seç.
3. **Patch numarası.** Plan `v62` diyor; v62–v67 dolu. Yeni patch **v69**'dan devam.
4. **`stage` ≠ `phase`.** `tenderBoardFilters.js`'in `stage` anahtarı yaşam-döngüsü
   değerleri taşıyor (`identified/decided/…`). Huni fazları (`seen/go/sourcing/…`)
   ayrı küme, ayrı anahtar (`phase`). Karıştırmak tabloyu sessizce boşaltır.
5. **Yeni doctype `bench migrate` ister.** Test etmeden önce:
   `bench --site <site> migrate && bench build --app stabler`.

---

## 3. Sıradaki işler

### Görev A — Sourcing Workspace + award paneli *(Faz 2 · Task 3, adım 3)*

**Amaç:** `/tender/sourcing` bugün salt-okunur bir karşılaştırma tablosu.
Kazananın seçildiği, gerekçenin yazıldığı ve direktörün onayladığı ekran olsun.

**Dosyalar:**
- `stabler/public/js/pages/tender/SourcingWorkspace.vue` *(yeni — `SourcingCompare.vue`'dan evrilir)*
- `stabler/api/sourcing.py` — `get_supplier_quotation(name, company)` ekle (tek teklifi satırlarıyla okur; `QuotationEntryDrawer`'ın düzenleme yolu buna bağlı ve şu an arayüzde kapalı)
- `stabler/public/js/pages/tender/PoControlBoard.vue` — kazanan tedarikçiye rozet
- `stabler/router.js`, `TenderNav.vue` — `/tender/sourcing` yolu **aynı kalır**, bileşen değişir

**Ekranın üç bölümü:**
1. **RFQ şeridi** — `list_rfqs`; "Teklif iste" düğmesi `create_rfq` ile taslak RFQ açar (tedarikçi çoklu seçim + kalem satırları).
2. **Teklif tablosu** — bugünkü karşılaştırma + satır başına "Düzenle" (taslaksa) ve "Kesinleştir". Politika rozetleri (5/2) kalır.
3. **"Kazananı seç" paneli** — seçili teklif, gerekçe (`selection_reason`), teknik sonuç, politika istisnası + gerekçesi. Kaydet → `save_sourcing_decision`. Direktörse "Onayla" → `approve_sourcing_decision`. Onaylı award salt-okunur görünür: seçilen ↔ en ucuz, onaylayan, zaman damgası.

**Kabul kriterleri:**
- [ ] `sourcing` görünümü olmayan kullanıcı "Kazananı seç" panelini **görmez** ve uç noktadan da 403 alır (gizlemek güvenlik değil — kapı sunucuda zaten var, ön yüz onu tekrarlar).
- [ ] `director` görünümü olmayan kullanıcıda "Onayla" düğmesi yok.
- [ ] Onaylı award'da hiçbir alan düzenlenemez; ekran "yeni karar kaydet" yolunu gösterir.
- [ ] Seçilen ≠ en ucuz olduğunda ekran bunu **açıkça** söyler (fark tutarı + yüzde). Bu ekranın var olma sebebi bu.
- [ ] Politika altındayken istisna kutusu işaretlenmeden Kaydet düğmesi pasif; sebep alanı boşken de pasif.
- [ ] Doğrudan URL ile `?deal=…` açılınca ekran dolu gelir (route-param guard, `isCreate` değil).
- [ ] `test_sourcing_spa.py` genişletilir: panel `MoneyInput`/`DateInput` kullanır, `/app/` yok, `⌘K` yer tutucusu var, onay düğmesi kaydetme çağrısı yapmaz.
- [ ] Yeni metinler 5 CSV'de.

**Commit:** `feat(tender): the screen where the winner is chosen, and the reason is written`

---

### Görev B — Tedarikçi panelinde Quotations sekmesi *(Faz 2 · Task 4)*

**Dosyalar:** `stabler/api/purchasing.py`, `stabler/public/js/pages/purchasing/Suppliers.vue`

- `supplier_quotation_history(supplier, company)` — **tek sorgu**, şirket kapısı,
  izin filtresi. Satırlar: SQ no, bağlı tender/lot etiketi, base toplam, statü,
  `valid_till` ve **sonuç** (kazandı / kaybetti / açık) — onaylı award'lardan
  **türetilir, saklanmaz**.
- Ledger/Orders/Invoices'tan sonra dördüncü sekme, sayaç rozetiyle. Satıra tıklama
  → `/tender/sourcing?deal=<deal>`. Tarihler `formatDate`, para `font-monospace`.

**Kabul kriterleri:**
- [ ] Tek sorgu (N+1 yok) — test bunu kaynak düzeyinde kilitler.
- [ ] Başka şirketin teklifleri hiçbir koşulda görünmez.
- [ ] Sonuç kolonu türetilir; hiçbir yere yazılmaz.
- [ ] Tender modülü kapalı kiracıda sekme hiç çizilmez.

**Commit:** `feat(purchasing): a supplier's own record of what it bid, and how it went`

---

### Görev C — i18n, rota, kapılar, sürüm *(Faz 2 · Task 5)*

- [ ] Tüm yeni metinler 5 CSV'de; locale-key testi genişletilir.
- [ ] **Geçici dosyaları sil:** `pages/tender/FunnelCompare.vue`,
      `pages/tender/TenderFunnelLegacy.vue`, `router.js`'teki
      `/tender/funnel-compare` rotası ve o üç dosyanın CSV metinleri.
      *(Kullanıcı eski/yeni huni karşılaştırmasını yaptıktan sonra.)*
- [ ] **Ölü kod:** `pages/tender/TenderControlTower.vue` (319 satır) ve
      `TenderPortfolioPreview.vue` — hiçbir rota, hiçbir import. Sil.
- [ ] Tam kapı: `make test` + `npm run test:js` + `make check`. Mevcut borcu
      yeni bulgudan ayır, yalnız kendininkini düzelt.
- [ ] Deploy CLAUDE.md'ye göre: yedek → `rsync -rltzvn` kuru koşu gösterilir →
      build → **7 sitenin hepsinde migrate** (v68 + yeni doctype) → düşük
      trafikte restart.
- [ ] Tarayıcı dumanı (mikas): RFQ oluştur → 2 teklif gir → politika rozetlerini
      gör → istisna gerekçesiyle karar kaydet → direktör onaylasın → PO panosunda
      kazanan tedarikçi işaretli → tedarikçi panelinde ikisi de listeli.
      `msa`: `/tender/sourcing` engelli. `anjan`: tender arayüzü yok.

---

## 4. Faz 2'den sonra — sıradaki üç boşluk

Bunlar **ayrı planlar**, Faz 2 bitmeden başlama. Öncelik sırasıyla:

### 4.1 Teklif düzeyinde landed cost *(en dar acı)*
Bugün landed hesabı yalnız **Purchase Order açıldıktan sonra** çalışıyor
(`tender.po_landed_charges`). Yani "hangi teklif **teslimli** olarak en ucuz"
sorusu PO açmadan cevaplanamıyor ve iki ekran "en ucuz"u farklı tanımlıyor:
`purchasing.tender_quotations` çıplak `base_grand_total`'a bakıyor,
`tender.po_control_board` landed'a. Aynı anlaşmada iki farklı tedarikçi yeşil
işaretlenebilir.

**Yön:** teklife navlun/gümrük/nakliye tahmini iliştir (HS koduna göre
`hs_rate_lookup` zaten var), karşılaştırmayı teslimli maliyete göre sırala, iki
ekrandaki "cheapest" tanımını tek kaynağa bağla. `Tender Sourcing Decision`'ın
snapshot'ı da o zaman landed taşımalı.

### 4.2 Belge merkezi — gerçek dosyalar
Bugün `intake.documents[]` sadece bir **checklist**: `{label, required, done,
date}`. "ГТД ✓" demek "birisi kutuyu işaretledi" demek, "dosya burada" demek
değil. Tek gerçek ek `bid_package`'ın ürettiği docx.

**Yön:** spec §2 "Document scope" + Seviye 3'ün 9. sekmesi. Her checklist
satırına ek yükleme, tender-scoped ↔ lot-scoped ayrımı, izin bazlı görünürlük,
indirme/paylaşım.

### 4.3 Seviye 1 — ihale panosu *(Faz 1 · Task 3)*
`Tender Master` doctype'ı, API'si ve patch'i **hazır** (`api/tender_master.py`,
4 uç nokta, `test_tender_master_api` 27 test). Eksik olan tek şey SPA:
`list_tender_masters` hiçbir yerden çağrılmıyor. Bugün 5 lotlu bir ihale panoda
5 ayrı kart. Spec'in lane'leri: `Hazırlık → Aktif → Sonuç bekleniyor → Kısmi
sonuç → Tamamlandı`, hepsi çocuk lotlardan **türetilir**.

---

## 5. Çalışma şekli

- Görev başına **bir commit**, plandaki TDD sırası: düşen test → RED → uygula →
  GREEN → commit. Test önce yazılır; bu oturumda tam da o sayede sessizce yanlış
  istisna atan bir izin kapısı yakalandı.
- Her görev sonunda dur ve göster. Yarısı çalışan düğme koyma — koymamak yeğdir,
  sebebini kaynağa yorum olarak yaz.
- Yorumlar **neden**i anlatır, neyi değil. Bu repodaki mevcut yorumların tonunu
  taklit et: hangi hatanın yaşandığı, ölçüldüğü tarih, alternatifin neden
  reddedildiği.
- Emin olmadığın ürün kararını sorma sırası sende değil — kullanıcıya sor.
