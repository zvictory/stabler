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
satırlarına açmamalı. `use_multi_level_bom=1` tam olarak bu açmayı yapar (`work_order.py:1558-1560`
→ `bom.py:1427`, `BOM Explosion Item`).

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

- `work_order.json` varsayılan 1. `work_order.py:1558-1560`
  `get_bom_items_as_dict(..., fetch_exploded=self.use_multi_level_bom)` → `bom.py:1427`
  `if cint(fetch_exploded)` → `BOM Explosion Item` tablosu (yaprak malzemeler) yerine `BOM Item`
  (alt-montajın kendisi). Bayrak `get_items_and_operations_from_bom()` **çağrıldığı anda** okunur; `:405-406` yeni kayıtta
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

Skeptic'in "Frappe 16.17.5" ibaresi yerel bench'te doğrulandı (`bench --site stabler list-apps`);
prod sürümü ölçülmedi. Karar sürüme bağlı değil.

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
  - ~~"Sabit masraf kalemleri" (00-SETUP.md:559-562): önceden belirlenmiş liste mi, götürü tutar
    mı?~~ → **KARAR 2026-09-03 (Zafar): önceden belirlenmiş liste** (§8). Liste içeriği ve
    hesap eşlemesi hâlâ açık (§8 soru 3).
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
  - Skeptic'in "Frappe 16.17.5" sürümü: yerel bench'te `bench --site stabler list-apps` → frappe
    16.17.5, erpnext 16.17.0 (2026-09-03). Prod sürümü bu oturumda ölçülmedi.
  - Kurulun hatası (inceleyici yakaladı): ilk sürüm mekanizmayı `work_order.py:1603` diye
    alıntılıyordu; o satır `update_transferred_qty_for_required_items`. `"exploded_items" if`
    satırı `bom.py:1603`'te ve Stock Entry maliyetlemesinde (ikincil etki). Gerçek mekanizma
    `work_order.py:1558-1560` → `bom.py:1427`. Sıkıştırma öncesinden taşınan, yeniden
    ölçülmemiş bir alıntıydı — Rule 0 ihlali.
```

## 7. Uygulama durumu (2026-09-03, kurul sonrası)

Kurul kararları opus alt-ajanlarına üç paket olarak devredildi (ADR-608). Her paket kendi
worktree'sinde, dal başına test-önce, `make check` yeşil; birleştirmeden önce salt-okunur
`stabler-diff-reviewer` turu. Aşağıdaki sayılar bu oturumda çalıştırılan komutlardan.

| Paket | Dal başı → main | Kanıt |
|---|---|---|
| **P1** ADR-601 (`v102` Property Setter + `create_work_order` açık 0) | `e9a0082` → `451bea7` | bench modülü `test_work_order_multi_level_default_bench` genesis-test.local: 5 test OK; tam `make test-bench` 77/77 rc=0 (`main @ 451bea7`, sıkıştırma öncesi ölçüm) |
| **P2** ADR-604 (prompt 01 drawer) | `d6c5042` → `a79149d` | `TenderMasterDrawer.vue` tgm-* 0; `ds-drawer` + `data-size="lg"`; vitest spec 18 test; `make check` yeşil |
| **P3** ADR-605 (ön-kazanım landed) | `3081f93` → `3c50aac` | bench modülü `test_tender_prewin_landed_bench`: 10 test OK (`3081f93`; 18 landed-ilişkili bench modülü `2b2c903`'te OK); `make check` yeşil; tam `make test-bench`: 77 modül, 0 kırmızı, `Ran 0` yok, ZERO COVERAGE yok, rc=0 (`main @ 3c50aac`) |

### İnceleme turlarında verilen hükümler
- **Form sözlüğü (P2):** `ds-field` / `ds-label` / `ds-form-grid` sevk edilmiş CSS'te var (ölçüldü);
  kontroller `.form-control` / `.form-select` kalır. Altbilgi sırası Kaydet → Vazgeç.
- **Kayıt engellenmez (P3):** kuru olmayan masraf satırı toplam DIŞI ve işaretli; kaydetme
  reddedilmez (kurulun "flag, don't block" hükmü).
- **Tek kural:** `tender_landed_math.line_value(amount, amount_original, currency, fx_rate)`
  → `(company_amount, unvalued)`; istemci aynası `composables/landedLine.js`.
- **RAW / VALUED ayrımı:** kalıcı olan yalnız RAW (`_landed.raw_charge_line` /
  `sanitize_charge_lines`, `tender._raw_landed_lines`); VALUED (`parse_landed_charges`,
  `_parse_landed`) her okumada türetilir, asla yazılmaz. Üçüncü incelemede PO yolunun tek
  adımlık olduğu bulundu (`po_landed_charges` VALUED döndürüyordu, ikinci kayıt satırı
  düşürüyordu) — `d08523b` verilen tutarı `amount_given` ikinci anahtarında taşır;
  ikinci adım davranışsal testle (sakla → oku → gönderilecek → sakla, aynı sütun) kapatıldı.
- **Yüzeye çıkan çakışma:** `_parse_landed` `amount`'ı yerinde eziyordu; yedi toplama noktası
  + `stabler/api/lcv.py:274` o anahtarı topluyor. Çözüm: verilen tutar ikinci anahtarda
  taşınır, toplama noktaları ve `lcv.py` değişmez (`git diff 9e98559 d08523b -- stabler/api/lcv.py`
  boş).
- **Gerçekleşen (actual) tarafı — kurul hükmü (b):** dördüncü incelemenin P1'i: satır
  `actual`'ı gösterirken sunucu onu `line_value(actual, actual_original, …)` ile sıfırlıyordu
  (`actual_original`'ın hiç giriş kontrolü olmadı; `b9050c4`, 24.08). Ölçüm:
  `landed_actual_from_voucher` yalnız `base_grand_total` / `base_paid_amount` / `total_debit`
  döndürüyor, elle giriş kutusu şirket para biriminde → `actual` tanım gereği şirket para
  birimidir, `line_value`'dan geçmez, `actual_original` şekilden çıkar, ölü ACTUAL altbilgi
  dizesi beş katalogdan silinir (`2b2c903`; altıncı tur `3081f93`: `isSendable` üç rakamı da okur — yalnız `actual` taşıyan satır kayıtta silinmez). Prod'a salt-okunur sorgu bu oturumda
  engellendi; yerine git tarihi ölçüldü: `git log --all -S 'v-model="l.actual_original"'`
  → 0 commit, anahtar `b9050c4`'te yalnız ilklendirme/temizleme/yankı olarak girmiş — hiçbir
  saklı satır sıfır dışı `actual_original` taşıyamaz; okuma yine de anahtarı tolere eder.
- **Commit trailer:** CLAUDE.md sürümsüz `Co-Authored-By: Claude <noreply@anthropic.com>`
  ister; harness bu oturumda "Claude Fable 5.1" istedi. CLAUDE.md kazandı, çakışma burada
  kayıtlı.
- **Delta CSS:** `TenderMasterDrawer.vue` scoped stilinde `delta.css:305` (`flex-wrap: wrap`)
  ile aynı kural var; delta CSS uygulanınca (asama-a §10) tekrar silinir.

### Yan bulgu — test sitesi hijyeni (P3'ün değil)
`make test-bench` süpürmesinde üç mevcut modül genesis-test.local'da CRM Deal bırakıyor
(`bench.log` zaman damgaları + `tabCRM Deal.creation` eşlemesi, ardından modül modül
önce/sonra sayımı): `test_director_board_integration` +2, `test_tender_board_funnel_integration` +1, `test_tender_intake_master_fields_integration` +5 (modül tek başına, önce/sonra sayım); bugün 16 satır, sitede toplam 472 CRM Deal, hepsi `_Test Company`. `test_tender_prewin_landed_bench` iki yolda da temiz
ölçüldü (yeşil koşu 8 → 8; `setUpClass` çöken sürüm 8 → 8; üç kipli sonda 0). Kayıt:
`docs/backlog.md`.

### Deploy durumu
Hiçbir şey deploy edilmedi. `v102` yaması **Zafar'ın açık onayını** bekler: her stabler
sitesinde `migrate` + `bench restart`; deploy sonrası taze işçi sürecinde
`frappe.new_doc("Work Order").use_multi_level_bom == 0`; sinyal: günlük mlb=1 sayısı → 0.
`82f9001` deploy'u da hâlâ Zafar'da. Karar verilmeyenler §6'daki gibi durur (ADR-606, delta
CSS, kanvas "Новый заказ" akışı).

## 8. ADR-606 kararı ve ADR-609 önerisi (2026-09-03, akşam)

### ADR-606 — KARAR (Zafar, 2026-09-03): önceden belirlenmiş liste
Sabit masraf seti götürü tutar değil, **önceden belirlenmiş liste** olacak. Ölçülen bugünkü
durum: iki ayrı istemci listesi var ve örtüşmüyor — `PoControlBoard.vue:50` `CHARGE_TYPES`
= transport, customs, certification, insurance, storage, declarant, legal, broker, loading,
bank, other (PO/landed satırı `type`); `LandedChargesEditor.vue:46` `CHARGE_TYPES` = Freight,
Customs Duty, Handling & Terminal, Insurance, VAT, Other (teklif satırı `charge_type`).
Sunucu `_landed.py:55-57` boş tipi "General" yapar ve `:136` VAT'ı ada göre tanır. Karar
gereği tek liste sunucuda tanımlanır, iki editör de onu okur; liste içeriği Zafar'dan
(aşağıdaki soru 3). Uygulama ayrı pakette (P4), bu doküman yalnız kararı kaydeder.

### ADR-609 — KARAR (Zafar, 2026-09-03 akşam; öneri aynen kabul): tender, muhasebe boyutu olsun
Talep (Zafar, 2026-09-03): "sistemdeki aktif tender seçilebilsin, masraf ona uygulansın;
QuickBooks'taki Class gibi; tender bazlı P&L'i profesyonel görebilmek; genel giderler ayrı
P&L." ERPNext'te Class'ın karşılığı **Accounting Dimension**'dır. Ölçüldü (ERPNext 16, yerel):

- `Accounting Dimension` alanları: `label, fieldname, document_type, disabled,
  dimension_defaults`; şirket başına `Accounting Dimension Detail`: `company,
  reference_document, default_dimension, mandatory_for_bs, mandatory_for_pl,
  automatically_post_balancing_accounting_entry, offsetting_account`.
- Zorunluluk GL'de uygulanır: `erpnext/accounts/general_ledger.py:635-650`, kayıt
  `report_type == "Profit and Loss"` bir hesaba düşüyor ve `mandatory_for_pl` işaretliyse
  boyutsuz GL satırı reddedilir. **Bu, "her gider ya bir tender'a ya genel gidere yazılır"
  kuralını veritabanı seviyesinde zorlar.**
- P&L raporu boyuta göre filtrelenir: `financial_statements.py:594-640`
  `get_accounting_dimensions` → her boyut bir filtre. Tender seçilince tender P&L'i,
  "GENEL" değeri seçilince genel gider P&L'i, filtresiz konsolide.
- Boyut alanı `accounting_dimension_doctypes` kancasındaki 52 belgeye eklenir
  (`erpnext/hooks.py`): GL Entry, Payment Ledger Entry, Sales Invoice, Purchase Invoice, Payment Entry, Asset, Stock Entry, Budget, Delivery Note, Sales Invoice Item, Purchase Invoice Item, Purchase Order Item, Sales Order Item, Journal Entry Account, Journal Entry Template Account, Material Request Item, Delivery Note Item, Purchase Receipt Item, Stock Entry Detail, Payment Entry Deduction, Sales Taxes and Charges, Purchase Taxes and Charges, Shipping Rule, Landed Cost Item, Asset Value Adjustment, Asset Repair, Asset Capitalization, Loyalty Program, Stock Reconciliation, POS Profile, Opening Invoice Creation Tool, Opening Invoice Creation Tool Item, Subscription, Subscription Plan, POS Invoice, POS Invoice Item, Purchase Order, Purchase Receipt, Sales Order, Subcontracting Order, Subcontracting Order Item, Subcontracting Receipt, Subcontracting Receipt Item, Account Closing Balance, Supplier Quotation, Supplier Quotation Item, Payment Reconciliation, Payment Reconciliation Allocation, Payment Request, Asset Movement Item, Asset Depreciation Schedule, Advance Taxes and Charges.

Stabler'ın bugünkü durumu (ölçüldü): **Accounting Dimension hiç kullanılmıyor** (grep boş).
Tender bağı `custom_crm_deal` özel alanıyla belge düzeyinde: yamalarda Supplier Quotation,
Purchase Order, Sales Order, RFQ, Journal Entry; `tender.py` ayrıca Sales Invoice, Customs
Declaration, Freight Booking üzerinde okuyor. Gerçekleşen P&L (`_actual_block`,
`tender.py:1397`) üç kaynaktan derleniyor: landed satırlarının `actual`'ı, deal'e bağlı
Sales Invoice geliri (`_deal_revenue_actual`), deal'e bağlı Journal Entry gider borçları
(`_deal_kassa_actual`, `root_type = 'Expense'`, `tender.py:1305-1330`). Yani bugünkü tender
P&L'i GL'den değil belgelerden hesaplanır; Purchase Invoice ve Expense Claim üzerinden gelen
tender gideri, stok çıkışının COGS'u ve boyutsuz JE bu P&L'e girmez. Talep tam bu boşluğu
tarif ediyor.

Öneri:
1. `Tender` adlı bir Accounting Dimension (`document_type` = tender kaydının doctype'ı —
   soru 1), her şirkette `mandatory_for_pl = 1`; genel giderler için her şirkette tek bir
   "GENEL GİDER" değeri (boyut boş bırakılamaz, açıkça seçilir).
2. Stabler'ın gider yazan ekranları (Expenses/kasa, PI, Expense Claim, LCV) boyut alanını
   **aktif tender listesinden** doldurur; kapalı tender seçilemez.
3. Tender P&L ekranı GL'den okur (boyut filtresi): gelir, COGS (stok çıkışı boyutla
   damgalanır), landed, tender giderleri; `_actual_block` bununla mutabakat edilir,
   fark satır satır gösterilir (geçiş döneminde iki kaynak yan yana).
4. Kapatma: tender kapandığında boyut değeri seçilemez olur; sonrası yazımlar reddedilir
   (ERPNext'in boyutu kapatma mekanizması yok — Stabler tarafında kural, ölçülecek).
5. Veri geçişi: mevcut `custom_crm_deal` taşıyan JE/SI/PO satırlarından boyutu geriye
   dönük doldur (yama, idempotent, her sitede migrate).

Beş soru ve KARARLAR (Zafar, 2026-09-03: "5 soruya senin önerin nedir" → öneriler aynen
kabul edildi). Ölçümler: CRM Deal `title_field = organization`, `show_title_field_in_link = 1`
(`crm_deal.json`); `frappe.model.mapper.get_mapped_doc` aynı adlı, `no_copy` olmayan alanları
kopyalar, SO→DN eşlemesinde yalnız `payment_terms_template` hariç (`sales_order.py:1460`).

| # | Karar | Gerekçe |
|---|---|---|
| 1 | Boyutun `document_type` = **CRM Deal**; ayrı Tender doctype'ı yok | mevcut `custom_crm_deal` değerleri 1:1 taşınır; linklerde firma adı görünür; tender olmayan deal'ler Stabler seçicilerinde `deal_type` ile elenir; "aktif" kuralı sunucuda |
| 2 | Zorunluluk yalnız **gelir-gider** hesaplarında (`mandatory_for_pl`); bilançoda biliniyorsa damgalanır | bilançoda zorunluluk avans/banka/stok hareketini durdurur |
| 3 | **Tek sunucu listesi, birleşim, dokuz tip** + KDV bayrak: transport (Nakliye), customs (Gümrük vergisi), declarant (Gümrük müşaviri/broker; eski `broker` buraya), certification, insurance, storage (Depolama/terminal/yükleme; eski `loading`, "Handling & Terminal" buraya), bank, legal, other (etiket zorunlu). Eski değerler diskte kalır, **okumada** eşlenir. **Hesap eşlemesi (tip → gider hesabı) P5'te**: tüketicisi GL kaydı, o da P5'te | iki liste aynı masrafların iki anı; eşleşmezse plan-gerçek karşılaştırması tutmaz; tüketicisi olmayan eşleme spekülatif |
| 4 | Boyut **Sales Order**'a yazılır, DN ve SI eşlemeyle miras alır; COGS GL satırı boyutu taşır. Anjan üretim maliyeti kapsam dışı | eşleyici kopyalıyor, ek kod yok; üretim maliyeti değerlemeyle teslimatta COGS'a zaten düşüyor; tender akışı yalnız mikas'ta |
| 5 | **Tek "GENEL GİDER"** değeri; kırılım mevcut Cost Center | tender boyutuna gider kategorisi yüklemek iki kavramı karıştırır |

Giriş noktaları (Zafar, 2026-09-03): yeni ekran yok — **`/money/expenses` formu** (mevcut
Tender (Deal) seçici boyutu doldurur ve yalnız aktif tender'ları listeler; ölçüldü:
`Expenses.vue:30,475-507` seçici var, `list_deals` `status` filtresi geçmiyor, `money.py:3365`
yalnız varlık doğruluyor) ve **Purchase Invoice formu** (bugün alan yok; PO'dan gelen faturada
PO'nun tender'ı dolu ve kilitli, PO'suz faturada zorunlu ya da GENEL GİDER).

Paketler: **P4** = tek liste (bu bölüm, karar 3; DB değişikliği yok, `make check` yeter, landed
bench modülleri yine de koşturulur). **P5** = boyut + Expenses/PI seçicileri + geriye dönük
yama + hesap eşlemesi + GL'den okuyan tender P&L (DB yaması → `make test-bench`, deploy onayı).

Eski açık sorular (kayıt için, hepsi yukarıda kararlaştırıldı):
1. Boyutun `document_type`'ı: doğrudan **CRM Deal** mi (bugünkü tender kaydı), yoksa
   yalnız tender'ları taşıyan ayrı bir **Tender** doctype'ı mı? CRM Deal'de tender olmayan
   deal'ler de var; boyut listesinde onlar da görünür.
2. Hangi belgeler zorunlu: yalnız P&L hesabına düşenler (öneri) mi, bilanço kalemleri de
   (avans, stok) mi? `mandatory_for_bs` ayrı bayrak.
3. Sabit masraf listesinin içeriği (ADR-606): PO listesi mi (11 tip), teklif listesi mi
   (6 tip), birleşimi mi? Muhasebe hesabı eşlemesi de listeye girsin mi (tip → Expense
   hesabı), tender P&L'inde satır başlıkları o hesaplardan gelsin?
4. COGS: tender bazlı stok çıkışı hangi belgeyle oluyor (Delivery Note / Sales Invoice
   update_stock)? Boyut o belgeye damgalanınca `Stock Ledger`→GL COGS satırı boyutu taşır;
   üretimden (anjan) gelen maliyet bu kapsamda mı?
5. Genel gider P&L'i tek "GENEL GİDER" değeri mi, alt kırılım (idari, satış, finans) mı?

ADR-609 kesinleşti (2026-09-03 akşam); P4 aynı gün açıldı, P5 P4'ün birleşmesini bekler.

### P4 — ADR-606 tek liste (2026-09-03 akşam)

| Paket | Dal başı → main | Kanıt |
|---|---|---|
| **P4** ADR-606 (dokuz kanonik tip, tek sunucu listesi, okumada eşleme) | `aaf583e` → `04955d4` | 18 landed-ilişkili bench modülü `87945bb`'te OK (18/18, hiçbiri 0 test; `p4-bench-87945bb.log`); `make check` yeşil main'de `04955d4` (ruff 4, eslint 5, sfc 301/0, `Ran 4927`, `Test Files 124 passed`, `Tests 1616 passed`); tam `make test-bench` yeşil main'de `04955d4` (78 modül, hepsi OK, ZERO COVERAGE yok; `test-bench-main-04955d4.log`) |

Sekiz commit: `80cbc19` (liste, alias tablosu, iki editör API'den okur, +6/−10 anahtar),
`dfa774f` (karar b: lojistik panosu yalnız kanonik `transport` sayar, `_transport_figure`),
`0a7326e` (P0: editör diskteki anahtarı yalnız operatör değiştirince yazar; liste isteği
düşerse editör hata durumunda, Kaydet kapalı), `596f54e` (`import vat` alias'ı çıkarıldı;
PO yazma yolu yalnız dokuz + `broker` + `loading`; `Storage` msgid'si geri; ikon anahtar
seti pinlendi), `b35d5f5` (P1: KDV kutusunu kaldırmak diske ulaşır; tanınmayan tip metni
placeholder; yorumlar koda uyduruldu; bildirimle sağlanan assertion'lar şablona bağlandı), `e300618` (P3: düzenlemesiz kaydet
KDV bayrağını da yerinde bırakır; `is_recoverable_vat_stored`; yük anahtar seti pinlendi;
docstring'e iki türetilmiş anahtar), `87945bb` (P0: tür değişikliği de alias bilgisini
emekliye ayırır; kutu diske uyar; ekran = sonraki okuma değişmezi spec'lendi), `aaf583e`
(beşinci turun iki P3'ü, yalnız metin: beş satırlık tablonun adı "four" diyordu; guard yorumu
ölçülen gerekçeyi anlatmıyordu. Orkestratör doğrudan uyguladı, `make check` ile doğruladı,
inceleme turu açılmadı).

İnceleme turlarının hükümleri (beş tur):
- **Disk yeniden yazılmaz, editör dahil:** ilk hâlde `<select>` kanonik anahtarı satırın
  `type`'ına bağlıyordu; planı açıp kaydetmek `broker`→`declarant`, `loading`→`storage`
  yazıyor, LCV'nin metin-kimliği (`lcv.py:276-279`) kopuyor ve masraf ikinci kez vouchere
  giriyordu. Şimdi `type_canonical` gösterim anahtarı, `@change` yazar.
- **…tek istisna, operatörün düzenlemesini diskin geri alacağı yer:** sunucu saklı yazımı
  KDV alias'ı olan her satırda `is_recoverable_vat`'ı zorla açar (`_landed.py`); eski "VAT"
  satırında kutuyu kaldırıp "VAT"ı geri göndermek düzenlemeyi bir sonraki okumada siliyor,
  ekran toplamı +KDV oynarken `base_landed_total` (kazananı sıralayan rakam) yerinde
  kalıyordu. Şimdi kutu kaldırılınca `charge_type = charge_type_canonical` (`other`) yazılır;
  saklı yazımın KDV olup olmadığını sunucu `charge_type_is_vat` alanıyla söyler, istemci
  alias tablosunun kopyasını tutmaz. Kutuyu geri işaretlemek hiçbir şeyi yeniden adlandırmaz.
- **Bayrak için de aynı kural, iki disk durumunda da sabit nokta:** değerlenmiş satırdaki
  `is_recoverable_vat` birleşik bayraktır (saklı bayrak VEYA yazım KDV alias'ı); editör onu
  geri gönderince ilgisiz bir kaydet tablonun hükmünü diske yazıyordu (diskte `false` →
  `true`). Reviewer'ın tek satırlık önerisi (`&& !charge_type_is_vat`) yönü tersine
  çevirirdi (diskte `true` → `false`). Kural: yazım hâlâ alias ise diskteki bayrak geri
  gider (`is_recoverable_vat_stored`); operatör satırı düzenlediyse görünen bayrak gider.
  Dokunulmadan kaydedilen ve hiç kaydedilmeyen satır diskte aynı kalır.
- **Düzeltme (orkestratörün hatası, dördüncü tur):** kuralı "alias yazımlı satırda tek
  düzenleme kutuyu kaldırmaktır" öncülüyle dikte ettim; yanlıştı. Tür `<select>`'i ikinci
  düzenlemedir ve `onTypeChange` alias bilgisini temizlemiyordu: "VAT"→Freight yapılan
  satır diskteki `false`'u gönderirken kutu ekranda işaretli kalıyor, 300 sessizce
  `base_landed_total`'a (tedarikçi sıralaması, `comparison_snapshot`) giriyordu (reviewer,
  uçtan uca ölçüm; `e300618`'de P0). Beşinci tur: hem kutuyu kaldırmak hem tür değiştirmek
  alias bilgisini emekliye ayırır, kutu diskteki bayrağa döner, ekranda görünen = giden
  değişmezi her ulaşılabilir düzenleme dizisi için spec'lendi.
- **Alias tablosu veriyi tarif eder, genişletmez:** `import vat` main'de KDV değildi;
  eklenmesi saklı bir teklifin landed toplamını değiştirip kazananı kaydırabilirdi.
- **Bir kiracının anahtarı başka bir kiracı için silinmez:** `Storage` msgid'si imports
  ekranlarında (msa) `t(value)` ile dinamik çağrılıyordu; tender değişikliği başka kiracının
  arayüzünü İngilizceye düşürüyordu. Test artık `ImportExpenses.vue` kategorilerini okuyor.
- **Türetilmiş metin saklı alana ekilmez:** tanınmayan tip ("Local Delivery") açıklamanın
  placeholder'ı olarak gösterilir, modele yazılmaz; ilgisiz bir kaydet `description`'ı
  doldurmaz. Diskte adı olan satıra "Say what this charge is." sorulmaz (`needsChargeLabel`
  `charge_type_unmapped`'i cevap sayar).
- **Karar (b), Zafar:** lojistik panosunun nakliye rakamı yalnız kanonik `transport`;
  eski `loading` satırları rakamdan düşer.
- `landed_charge_types()` kapısız (derleme zamanı sabiti, kiracıya özgü hiçbir şey yok);
  gerekçe docstring'de. İki editörde liste ve veri tek `try` içinde ardışık okunur: liste
  düşerse editör kasıtlı olarak kapalı (seçeneksiz `<select>` kullanılamaz); yorumlar ilk
  hâlde bağımsızlık iddia ediyordu, üçüncü turda koda uyduruldu.
- Tekrarlayan desen: kaynak okuyan spec'lerde bildirim ya da yorumla sağlanan regex
  (`toMatch(/needsChargeLabel\(line\)/)` fonksiyon bildirimiyle yeşil kalıyordu). Kural:
  `<template>`'den sonra dilimle ve çizen özniteliği (`:class`, `v-if`) doğrula; reviewer'ın
  mutasyonu (şablondaki her kullanım → `false`) kırmızıya dönmeli.

Yan bulgu (P4'ün değil, önceden var): LCV satır kimliği serbest metinden türetiliyor
(`lcv.py:276`, `lcv_math.py:53`); backlog'da.
