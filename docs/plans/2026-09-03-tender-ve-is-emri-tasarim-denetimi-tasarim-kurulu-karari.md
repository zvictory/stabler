# Tasarım Kurulu Kararı — mikas tender akışı ve anjan iş emri tasarımlarının denetimi

**Tarih:** 2026-09-03 · **Kurul:** Claude Fable 5.1 (mercekler) + Skeptic alt-ajanı (ayrı bağlam) ·
**Talep eden:** Zafar
**Önceki kararlar:** `2026-09-01-mikas-tender-tasarim-dili-tasarim-kurulu-karari.md` (ADR-301..307),
`2026-09-02-taraf-paneli-sekme-yerlesimi-tasarim-kurulu-karari.md`,
`2026-08-28-manufacturing-is-emirleri-durum.md` (envanter; §3'te düzeltiliyor).

## Talep

Zafar, 2026-09-03: *"mikas yeni tasarımını ve anjan için de yapılan manufacturing çalışmalarını
kurul denetlesin … manufacturing'de WO oluştururken bu use multilevel BOM işaretinin kaldırılması
lazım, o zaman smes içindekileri de göstermez!!! buna da dikkat edelim yeni UI tasarımlarında. ve
bu tasarımların güncellenip hayata geçirilmesini kontrol etsin kurul!!! mikas tender akışı, pre
win/post win ve anjan manufacturing WO yeni tasarımları denetlemesi."* Ek: ERPNext Desk
"Work Order" diyaloğunun ekran görüntüsü — *Qty To Manufacture 1.000*, **Use Multi-Level BOM
işaretli**, *Create*. Süreç talimatı: denetimi Fable 5.1 yapar; iş denetimden sonra opus
alt-ajanlarına devredilir.

Alan okuması: "smes" = **смесь** (karışım). Dondurma karışımı kendi iş emriyle üretilen bir
alt-montajdır; bitmiş ürünün iş emri karışımı **tek satır** olarak istemeli, içindeki süt/şeker
satırlarına açmamalı. `use_multi_level_bom=1` tam olarak bu açmayı yapar (`work_order.py:1603`).

## Kanıt rejimi

- Her sayı bu oturumda çalıştırılan bir komuttan: anjan prod salt-okunur
  (`ssh ice-production … bench --site anjan.erpstable.com mariadb`), yerel repo (`grep`, `git log`),
  ERPNext v16.17.0 ve Frappe kaynak dosyaları. Ölçülemeyen → **(unverified)**.
- Skeptic ayrı alt-ajan olarak koştu; itirazları §5'te, kazandığı yerlerde karar değişti.
- Yönlendirme sapması: Skeptic `fable` modelinde koştu (model-routing kuralı doğrulama katmanı
  için `opus` der). Gerekçe Zafar'ın talimatı: "Fable 5.1 gücünü denetimde kullan".

## KARAR ÖZETİ

| # | Karar | Paket |
|---|---|---|
| ADR-601 | `use_multi_level_bom` varsayılanı kayıt düzeyinde 0: Property Setter (`Work Order` · `use_multi_level_bom` · `default` = `"0"`, `property_type` **Text**) idempotent yama `v102` + `create_work_order`'da BOM okunmadan **önce** açık `doc.use_multi_level_bom = 0` + `frappe.clear_cache(doctype="Work Order")` | P1 |
| ADR-602 | Stabler'ın "New Work Order" modalına çok-seviyeli kutusu **eklenmez**; Desk diyaloğundaki kutu kalır, yalnız varsayılanı değişir | P1 |
| ADR-603 | Yeni üretim UI tasarımlarında oluşturma akışı çok-seviyeli kontrolü **göstermez**; ihtiyaç doğarsa ürün başına değil BOM başına ve ayrı bir karardır | tasarım kuralı |
| ADR-604 | Tender prompt 01 (intake drawer) göçü, 2026-09-01 ACCEPTANCE #1/#6/#7/#9 **harfiyen**; #8 delta CSS kapısına bağlı, paketin dışında | P2 |
| ADR-605 | Ön-kazanım maliyeti: teklif masraf satırları PO satırlarının şeklini alır (`currency`, `fx_rate`, `rate_date` → `converted_amount`); `base_landed_total` yalnız dönüştürülebilen satırlardan; BidPricing PO yokken lotun **kaynak kararındaki** teklifin toplamını ön-doldurur, "en ucuz" tahmini yapmaz | P3 |
| ADR-606 | "Sabit masraf kalemleri" (şirket başına set / kopyalama jesti) **karar verilmedi** — ölçüm yok (mikas 0/3), Zafar'a tek soru | — |
| ADR-607 | 2026-08-28 durum dokümanının 1b satırları düzeltilir; `907caf7`'nin yeniden ölçümü alıntılanır, tarih silinmez | bu commit |
| ADR-608 | Devir: opus alt-ajanları, paket başına ayrı worktree/branch, test-önce, `make check`; P1 ayrıca `make test-bench`; deploy Zafar onayı, her stabler sitesinde migrate | — |

## 1. Üretim — çok seviyeli BOM bayrağı

### 1.1 Ölçüm — anjan, salt-okunur, 2026-09-03

| docstatus | mlb=0 | mlb=1 |
|---|---|---|
| 0 taslak | 5 | 4 |
| 1 onaylı | 3 656 | 167 |
| 2 iptal | 413 | 26 |
| **toplam** | **4 074** | **197** |

- Son mlb=1 onaylı kayıt 2026-09-02 09:31 → sorun bugün canlı.
- 2026-08-20'den bu yana **her gün** iki değer birlikte (20.08: 17 / 14 · 01.09: 3 / 9 ·
  02.09: 16 / 3). Kişi ayrımı yok: aynı vardiya, aynı gün, bazen kutu kalıyor.
- `operator` alanını oluşturma anında yalnız Stabler API'si yazar (Desk diyaloğunda alan yok):
  mlb=0 → 14 / 4 074; mlb=1 → 8 / 197. 02.09'daki üç mlb=1 kaydın üçünde `operator` dolu →
  Stabler modalından çıktılar; modal bayrağı yazmıyor, `new_doc` varsayılanı 1 veriyor.
- Bu oturumun 2026-09-02 ölçümleri: aynı ürün **34** kez iki ayarla da üretilmiş, **7** ürün
  yalnız mlb=1; 167 mlb=1 onaylının **130**'unun BOM'unda alt-montaj var (bayrak sonucu
  değiştirdi; 37'sinde etkisiz); 562 BOM'un 346'sında alt-montaj satırı; mlb=0 iş emirlerinde
  2 862 gerekli-malzeme satırı alt-montajın kendisi; sekiz kiracının hiçbirinde bu alan için
  Property Setter yok.
- Varsayılanı atlayan yollar (Skeptic §5): Production Plan (`production_plan.py:730`,
  `include_exploded_items`) ve Sales Order'dan üretim. anjan: Production Plan **0**, plandan
  gelen WO **0**, Sales Order'dan gelen WO **0** → bugün iki oluşturma yolu var: Desk diyaloğu
  ve Stabler API'si. İkisini de tek anahtar kapatır.

### 1.2 Mekanizma (ERPNext v16.17.0 / Frappe)

- `work_order.json` varsayılan 1. `work_order.py:1603` `table = "exploded_items" if
  use_multi_level_bom else "items"`; `:1559` `fetch_exploded=self.use_multi_level_bom` —
  `get_items_and_operations_from_bom()` **çağrıldığı anda** okunur; `:405-406` yeni kayıtta
  `reset_use_multi_level_bom` erken döner, `insert()` yeniden türetmez. Atama bu yüzden
  BOM okunmadan önce durmalı.
- Desk diyaloğu `bom.py:232-241`: `Property Setter {doc_type: Work Order, field_name:
  use_multi_level_bom, property: default}` → yoksa 1, `cint()` ile.
- `frappe.new_doc` meta varsayılanını okur. Aynı Property Setter **ayrı bench süreçlerinde**
  ölçüldü: `new_doc → 0`, `get_meta().get_field(...).default → "0"`, setter silinince yeniden
  1. Tek anahtar iki yolu da kapatır.
- `default` özelliğinin tipi **"Text"** (`customize_form.py:800`). `v20_cost_field_perm_level.py`
  içindeki `_upsert_property_setter` "Int" yazar ve güncellemede `frappe.db.set_value` kullanır —
  kopyalanmaz: `PropertySetter.validate` (`property_setter.py:39-45`) yeni kayıtta aynı
  anahtardaki eskiyi siler ve `frappe.clear_cache(doctype)` çağırır; `db.set_value` bu
  temizliği atlar.
- Stabler: `stabler/api/manufacturing.py:1947 create_work_order` bayrağa dokunmaz
  (`grep -rn use_multi_level_bom stabler/` → 0 satır). Sıra `:2000-2002`:
  `set_work_order_operations()` → `get_items_and_operations_from_bom()` → `insert()`.
  `WorkOrders.vue:1014` modalında kontrol yok. `hooks.py:427` Work Order için yalnız
  `on_submit` → malzeme talebi.

### 1.3 Tasarım kanvası

- Zafar'ın bağlantısı "Work Orders redesign" sayfası. Kanvasta dört sayfa: *Work Orders -
  Stabler (standalone)*, *Work Orders - Stabler*, *Work Orders redesign*, *Work Orders current*.
  Kanvasın sohbet günlüğü "Save as standalone HTML: Work Orders redesign.dc.html" diyor →
  standalone, redesign'ın dışa aktarımı; iki sayfa aynı içerik.
- Görülen: **0** yol haritası (Faza 1 → 1a · Faza 2 → 1d · Faza 3 → 1c/1b/1e); **1** "beş yön";
  **1a** üst bölümü — sekmeler *BOMs · Производственные заказы · Планирование · Смена*,
  "+ Новый заказ", KPI şeridi, filtre çipleri (*Сегодня · Моя смена · Готовы к запуску ·
  Дефицит сырья · Просрочены*), toplu işlem çubuğu (*Провести и выпустить · Назначить
  оператора · Передать материалы · Этикетки партий*).
- **Görülemeyen (unverified):** kanvas bu oturumdan kaydırılamadı — çapraz-kaynak iframe;
  tekerlek, PageDown, kaydırma çubuğu sürükleme ve Present kipinde ok tuşları etkisiz.
  "Новый заказ" akışının çok-seviyeli bir kontrol içerip içermediği doğrulanmadı. **Karar
  buna bağlı değil:** bayrak kayıt varsayılanında ve API'de 0'a çekildiği için yeni UI ne
  gösterirse göstersin kayıt 0 alır. ADR-603 yeni tasarımlar için kuralı koyar.
- Uygulama (git, `WorkOrders.vue`): 1a `a0b42ba` (28.08), `e7698d3` (29.08); 1b `907caf7`,
  `c27e643` (29.08); 1c engel paneli `ebd3562` (29.08). 2026-08-28 durum dokümanı 1b'yi "YOK"
  (:18) ve "ÖLÜ" (:223) yazıyor → §3.

### 1.4 Mercekler

- **Architect:** Property Setter, ERPNext'in bu iş için **kendi okuduğu** anahtar (`bom.py:232`);
  dördüncü desen icat edilmiyor. API'deki açık atama varsayılana güveni kaldırır. Yama tek
  yönlü değil: setter silinirse eski davranış geri gelir (§5, reset deliği).
- **Dev Team:** Desk'te kutu kalır, alışkanlık değişmez; "unutmak" zararsız olur. Stabler modalı
  sessizce 1 üretmeyi bırakır. Sinyal basit: mlb=1 günlük yeni kayıt sayısı.
- **DevOps:** yama her stabler sitesinde `migrate` ister (deploy skill adım 5; site sayısını
  yeniden ölç); `bench restart` süreçlerdeki meta önbelleğini kesin tazeler; yama ayrıca
  `frappe.clear_cache(doctype="Work Order")` çağırır. Yalnız anjan'da üretim açık; diğer
  sitelerde setter zararsız (iş emri yok).
- **Operator:** Desk diyaloğu kutuyu işaretsiz açar; iş emrinde "смесь" tek satır. Mesaj yok,
  değişen tek şey varsayılan.

## 2. Tender (mikas)

### 2.1 Envanter — repo, 2026-09-03

| Prompt | Durum | Ölçüm |
|---|---|---|
| 01 intake drawer | uygulanmadı | `TenderMasterDrawer.vue`: `tgm-*` 15 benzersiz sınıf, `ds-*` 0 |
| 02 kanban | kapı PASSED 2026-09-01 | `TenderCrm.vue` `ds-*` 52 benzersiz |
| 03 sourcing | uygulanmadı | `SourcingWorkspace.vue` 1 047 satır, `ds-*` 0 |
| 04–12 | uygulanmadı | `PoControlBoard.vue` 800 satır / 0 · `DeclarantQueue` 361 / 0 · `LogistBoard` 346 / 0 · `TenderDocuments` 603 / 0 |
| 13–17 | main'de | `DirectorBoard` 28 · `OperationsDesk` 36 · `TenderOverview` 18 · `TenderFlow` 23 · `MyTenders` 8; birleşmeler `4b63ba5`, `14a21ce` |
| 18 contract board | kısmi | `SalesOrderBoard.vue` `ds-*` 2; C7/C8/C15–C19 düzeltmeleri commit'lendi |

- Prompt dosyaları (`docs/design/prompts/01..18`) 2026-09-01/02'de yazıldı → "01–12
  uygulanmadı" gecikme bulgusu değil, durumdur.
- `ds-*` sayısı **stil değil sınıf benimsenmesi** ölçer: katman `.stbl-ds` altında kapsamlı
  (`test_design_layer_contract.py:65`). Kabul ölçütleri bu yüzden 2026-09-01 ACCEPTANCE'tan
  harfiyen devralınır; sayı tek başına geçmez.
- Delta CSS `docs/design/2026-09-01-asama-a-delta.css` **HENÜZ UYGULANMADI** (başlığı öyle
  diyor); `:disabled` kuralı sevk edilmiş `stabler-modernist.css`'te 2, deltada 15 → 2026-09-01
  ACCEPTANCE #8 bu kapıya bağlı; kapı `2026-09-01-asama-a-tender-bilesen-dili.md §10`'daki
  Zafar kararları. P2 bu kapıya dokunmaz.
- Sevk edilmiş katmanda `ds-drawer` 14, `ds-form-section` 2 kural var → drawer göçü deltayı
  beklemez.

### 2.2 Ön-kazanım / kazanım sonrası

Kural (`00-SETUP.md:557-591`): ön-kazanım = tekliflere işlenen maliyet **tahmini**; kazanım
sonrası = PO/gümrük/nakliyeden **operasyonel kayıt**. Bugün iki bağımsız ön-kazanım sayısı var
ve birbirini görmez:

- **(a)** Teklif başına masraf satırları — `Supplier Quotation.custom_landed_charges` (JSON;
  `sourcing.py:1284`), satır şekli `{charge_type, description, amount, is_recoverable_vat}`
  (`LandedChargesEditor.vue:107-112`). `_landed.py:41` tutarları **para birimi ve kur olmadan**
  toplar; `get_quotation_landed` (`sourcing.py:1272`) bunu şirket para birimindeki
  `base_grand_total`'a ekleyip `base_landed_total` üretir. Editör aynı satırı **teklif** para
  birimiyle etiketler (`SourcingWorkspace.vue:1034` `landedRow?.currency || 'USD'`), tablo
  şirket para birimiyle. Tek sayı, iki etiket. PO satırları WP-T3 ile `currency / fx_rate /
  rate_date → converted_amount` aldı (`tender_landed_math.py:21`, boş `currency` = şirket
  para birimi); teklif satırları almadı.
- **(b)** `CRM Deal.custom_bid_pricing.landed_goods` — şirket para birimi (`tender.py:1046-1099`),
  `BidPricing.vue:161`; PO yoksa boş; `useLandedFromPOs` (:113) yalnız kazanım sonrası dolar.
  BidPricing `PoControlBoard.vue:402`'de `:currency="ccy"` ile monte; `ccy`
  `workspace.overview.currency` (:113) — şirket para birimi olduğu **varsayıldı**, P3 doğrular.
- mikas: 3 teklifin **0**'ında masraf satırı (2026-09-02). (a)'daki birim hatasının canlı
  verisi henüz yok; düzeltme önleyici ve ucuz — teklif fiyatı yanlış etiketli bir para
  biriminden hesaplanmamalı.
- "Kazanan teklif" ön-kazanımda tanımsız: `Tender Sourcing Decision.status == "Approved"`
  (`sourcing.py:1089-1094`) PO rotasını açan şeydir (`purchasing.py:3454-3460`); ön-kazanımda
  en fazla taslak karar vardır. ADR-605 kaynağı **kaynak kararındaki teklif** olarak adlandırır
  (taslak ya da onaylı); karar yoksa alan boş kalır ve boş durum eylemi söyler.

## 3. 2026-08-28 durum dokümanı düzeltmesi (ADR-607)

`:18` "1b Kanban panosu | YOK" ve `:223` "1b kanban | ÖLÜ — ölçümle iptal" bayat. `907caf7`
(2026-08-29) gövdesi: 08-28 kararı ERPNext `status` alanına karşı ölçülmüştü (onaydan sonra
salt-okunur, anjan'ın %99,1'i tek değerde); tasarımın kolonları ise türetilmiş durumlar —
yanlış eksen. 2026-08-29 yeniden ölçüm: Completed/Closed 3 757 · Draft 8 · hiç transfer yok 33 ·
tam transfer 2 · kısmi 0 · üretildi-bitmedi 0 · Line Stop 0 · saat içinde tamamlanan
3 631 / 3 755. Üç kolon bugün boş — türetilemediği için değil, adımlar kaydedilmediği için.
Düzeltme dokümana **ek** olarak yazılır (tarih ve commit ile); 28.08 satırı silinmez,
üstü çizilir.

## 4. Devir planı (ADR-608)

| Paket | Kapsam | Model · tetik | Kapı |
|---|---|---|---|
| P1 | `v102` Property Setter yaması + `create_work_order`'da BOM okunmadan önce açık 0 + `clear_cache` + frappe-free sıra testi + bench idempotens ve `required_items` testi | opus · DB yaması, geri alınması zor; Zafar talimatı | `make check` **ve** `make test-bench`; deploy Zafar onayı, her sitede migrate |
| P2 | Prompt 01 drawer göçü (ADR-301); 2026-09-01 ACCEPTANCE #1, #6, #7, #9 | opus · Zafar talimatı ("opus alt-ajanları"); rubrikte sonnet-varsayılan, sapma kayıtlı | `make check` |
| P3 | Teklif masraf satırlarına PO şekli + `converted_amount`; `base_landed_total` yalnız dönüştürülebilen satırlardan; BidPricing ön-dolum kaynak kararından; boş durum eylemi söyler | opus · para matematiği | `make check`; JSON alanı → şema ve migrate yok |
| — | 08-28 dokümanı düzeltmesi | kurul, bu commit | — |

P2 ve P3 dosya kesişmez: P2 `TenderMasterDrawer.vue` + testleri; P3 `_landed.py`,
`sourcing.py`, `LandedChargesEditor.vue`, `SourcingWorkspace.vue`, `BidPricing.vue`,
`tender.py` + testleri. `stabler-modernist.css`'e yalnız P2 dokunabilir.

## 5. Skeptic — itirazlar ve sonuç

| İtiraz | Doğrulama | Sonuç |
|---|---|---|
| D3(a): masraf tutarları kur/para birimi olmadan toplanıyor; editör ve tablo farklı etiketliyor; "kazanan teklif" ön-kazanımda tanımsız | `_landed.py:41`, `SourcingWorkspace.vue:1034`, `sourcing.py:1089-1094` okundu — doğru | **Kazandı.** D3(a) → ADR-605: satırlara PO şekli, kaynak = kaynak kararındaki teklif |
| D3(b): "sabit" tek çeviri kelimesine dayanıyor; tekrar yazma ölçülmedi; yüzde şemada yok | `00-SETUP.md:559-575`; mikas 0/3 | **Kazandı.** Karar verilmedi (ADR-606), Zafar'a soru |
| D1(a): atama `get_items_and_operations_from_bom()`'dan sonra konursa test geçer, malzeme yine patlamış olur | `work_order.py:1559`, `:405-406`, `manufacturing.py:2000-2002` | **Kazandı.** Sıra kabul ölçütüne girdi; bench testi `required_items` içeriğini kontrol eder |
| D1(b): meta önbelleği süreç içi; `db.set_value` temizlemez | `property_setter.py:39-45` | **Kazandı.** `frappe.clear_cache(doctype="Work Order")` yamada |
| D1(c): property_type "Text" olmalı | `customize_form.py:800` | **Kazandı** (kurul da aynı satırı bulmuştu) |
| D1(d): Production Plan yolu varsayılanı atlar | `production_plan.py:730`; anjan'da plan 0, plandan WO 0 | Doğru ama bugün boş; dokümante edildi |
| D1(e): Customize Form "Reset" setter'ı siler, yama geri gelmez | mekanizma doğru | Kabul edilen delik; WOULD CHANGE MY MIND'da sinyal |
| D2: 167 / 197 farklı kümeler | yeniden ölçüldü: 197 = tüm docstatus, 167 = onaylı | İkisi de doğru; CORRECTIONS |
| D4: `ds-*` sayısı stil değil; 09-01 ölçütleri bileşik; #8 delta CSS'e bağlı; 1b düzeltmesi yeniden ölçümü alıntılamalı | `test_design_layer_contract.py:65`; delta başlığı; `907caf7` gövdesi | **Kazandı.** ADR-604 ölçütleri harfiyen devralır; #8 kapsam dışı; §3 alıntı |
| D5: paket başına yönlendirme tetiği adlandırılmalı | rubrik | Kabul: tabloda tetik sütunu; opus seçimi Zafar talimatı |

Skeptic'in kendi hatası: "Frappe 16.17.5" sürüm ibaresi bu oturumda ölçülmedi (unverified —
Skeptic raporu); karar sürüme bağlı değil.

## 6. Çıktı sözleşmesi

```
DECISIONS
  1. ADR-601 — Property Setter default "0" (Text) + create_work_order'da BOM okunmadan önce açık 0 +
     clear_cache. Çünkü: bom.py:232-241 setter'ı okuyor; ayrı süreçte new_doc → 0 ölçüldü;
     work_order.py:1559 bayrağı get_items_and_operations_from_bom anında okuyor; anjan'da
     197 mlb=1 kayıt, son onaylı 2026-09-02 09:31; mlb=1 kayıtların 130/167'sinde bayrak
     sonucu değiştirdi (mariadb sorguları, bu oturum).
  2. ADR-602 — Stabler modalına kutu yok; Desk kutusu kalır. Çünkü: grep → Stabler bayrağı hiç
     yazmıyor; Desk kutusunu kaldırmak ERPNext çekirdeğini forklar; yalnız mlb=1 ile üretilen
     7 ürün var (yetenek Desk'te kalır).
  3. ADR-603 — yeni üretim tasarımlarında oluşturma akışında çok-seviyeli kontrol yok.
     Çünkü: Zafar'ın talimatı; 1.3'te kanvasın ilgili bölümü görülemedi, kural ileriye dönük.
  4. ADR-604 — P2 = prompt 01 drawer, 2026-09-01 ACCEPTANCE #1/#6/#7/#9 harfiyen.
     Çünkü: TenderMasterDrawer.vue tgm-* 15 sınıf / ds-* 0 (grep); sevk edilmiş CSS'te
     ds-drawer 14 kural var; delta CSS uygulanmamış (dosya başlığı).
  5. ADR-605 — teklif masraf satırlarına PO şekli; ön-dolum kaynak kararındaki teklifden.
     Çünkü: _landed.py:41 kur olmadan toplar; SourcingWorkspace.vue:1034 teklif para birimiyle
     etiketler; converted_amount (tender_landed_math.py:21) hazır; mikas 0/3 teklif masraflı.
  6. ADR-606 — sabit masraf seti karar verilmedi. Çünkü: ölçüm yok; 00-SETUP.md:559-575 tek
     kelimeye dayanıyor.
  7. ADR-607 — 08-28 dokümanı 1b düzeltmesi 907caf7 yeniden ölçümüyle. Çünkü: git log
     WorkOrders.vue → 907caf7, c27e643 (29.08); doküman :18 "YOK", :223 "ÖLÜ".
  8. ADR-608 — devir opus alt-ajanlarına, paket başına worktree, test-önce. Çünkü: Zafar'ın
     talimatı; P1 DB yaması → make test-bench zorunlu (CLAUDE.md).

ACCEPTANCE
  P1
   - anjan'da migrate sonrası TAZE bench sürecinde frappe.new_doc("Work Order").use_multi_level_bom
     == 0 (bugün 1) VE Property Setter value == "0", property_type == "Text" (bugün None).
   - Yama iki kez koşar → tek Property Setter satırı, değer "0" (bench test).
   - Frappe-free test: create_work_order gövdesinde `use_multi_level_bom = 0` ataması
     get_items_and_operations_from_bom() çağrısından ÖNCE; atama silinirse VEYA sonrasına
     taşınırsa kırmızı (iki mutasyon, commit mesajında).
   - Bench test: alt-montajlı BOM ile create_work_order → required_items alt-montajı tek satır
     içerir, alt-montajın yaprak malzemelerini içermez.
   - Sinyal: mlb=1 günlük yeni kayıt (bugün 3–14) → 0; deploy'dan bir hafta sonra yeniden ölç.
  P2
   - 2026-09-01 ACCEPTANCE #1 harfiyen: tgm- 46 → 0 VE ds-drawer + ds-form-section > 0 VE
     data-size="lg"; #6 kaynaktan yürüten test; #7 stabler/ dışında dosya yok; #9 sahte veri yok.
   - Drawer .stbl-ds altında monte — sınıf sayısı tek başına geçmez.
   - make check yeşil; test-js yürütülen test sayısı artar.
  P3
   - currency'li teklif masraf satırı converted_amount ile dönüştürülür; kur yoksa satır toplam
     dışı ve UI'da işaretli (bugün ham tutar toplanıyor); currency'siz eski satır aynen geçer
     (frappe-free test, _landed.py).
   - Editör ve tablo aynı para birimini etiketler (kaynak okuyan test).
   - BidPricing PO yokken kaynak kararı teklifi varsa landed_goods ön-dolu VE kaynak etiketi
     görünür; yoksa boş durum "Sourcing'de bu lot için teklif seçin" der; "en ucuz" hiçbir
     zaman kaynak değil (test: iki teklif, karar yok → boş).
   - make check yeşil; doctype JSON ve patches.txt değişmez (JSON alanı).

NOT DECIDED
  - "Sabit masraf kalemleri" (00-SETUP.md:559-562): önceden belirlenmiş liste mi, götürü tutar
    mı? Zafar tek satırla. Ölçüm tetiği: ≥20 teklif masraf taşıdığında lot içinde aynı set
    kaç kez yazılmış.
  - Yalnız mlb=1 ile üretilen 7 ürün gerçekten çok seviyeli mi? Desk kutusu kaldığı için
    yetenek kaybolmaz; Stabler modalı 1 üretemez (Zafar'ın talimatı).
  - Delta CSS'in uygulanması (ACCEPTANCE #8) — asama-a §10 Zafar kararları.
  - Kanvasta "Новый заказ" akışının içeriği (görülemedi).
  - 82f9001 (?c= düzeltmesi) deploy'u hâlâ Zafar'da.

WOULD CHANGE MY MIND
  - migrate sonrası taze süreçte new_doc hâlâ 1 → Property Setter yolu yanlış; before_insert
    hook'una geçilir.
  - mlb=1 günlük sayı bir hafta sonra sıfıra inmiyorsa → üçüncü bir oluşturma yolu var;
    yeniden ölç (Production Plan / SO / import).
  - Bir operatör 7 üründen biri için kutuyu bilerek işaretliyorsa → ADR-602: modala BOM-bazlı
    görünür bir seçenek.
  - mikas'ta ≥20 masraflı teklifte aynı set tekrarı ≥%50 → ADR-606 kopyalama jesti.
  - Property Setter bir kiracıda silinmiş bulunursa → yama yeniden koşturulur (idempotent),
    deploy skill'e kontrol satırı eklenir.

CORRECTIONS
  - Kurulun hatası: Property Setter denemesi aynı süreçte after=1 verdi (meta önbelleği).
    Ayrı süreçlerde yeniden ölçüldü → 0. İlk okuma yanlıştı.
  - Skeptic'e verilen özette "167", kararda "197": iki farklı küme (onaylı / tüm docstatus);
    ikisi de doğru, etiketsiz yazılmıştı.
  - D3(a) ilk hâli (base_landed_total → landed_goods) yanlıştı: birim tutarsız, kaynak
    tanımsız → ADR-605.
  - D3(b) ilk hâli (sabit set / kopyalama jesti) ölçümsüzdü → ADR-606, karar yok.
  - D1'e üç düzeltme: atama sırası, cache temizliği, property_type "Text".
  - Zafar'ın "işaretin kaldırılması" talebi: Desk'te kutu kaldırılmıyor, varsayılanı değişiyor
    (kaldırmak çekirdeği forklar); Stabler tarafında kutu hiç yoktu — sorun kontrolsüz 1'di.
  - 2026-08-28 dokümanının "1b ÖLÜ" satırı yanlış eksende ölçülmüştü (§3).
  - Skeptic'in "Frappe 16.17.5" sürümü ölçülmedi (unverified).
```
