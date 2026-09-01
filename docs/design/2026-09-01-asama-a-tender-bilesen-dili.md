# Aşama A · Mikas Tender — **Bileşen Dili**

**Tarih:** 2026-09-01 · **Depo:** `/Users/zafar/frappe-bench-local/apps/stabler` @ **`7dfb381`**
**Girdi:** beş alan şartnamesi (`cekmece`, `form`, `durum`, `aksiyon`, `bosluk`) + dört
uzlaştırma dosyası + **üç bağımsız çürütme raporu**.
**Çıktı:** brief §7.1'in altı maddesini karşılayan **tek** belge.

> **Sürüm 2 (düzeltilmiş).** Üç çürütme raporu 46 itiraz getirdi; 41'i işlendi, 5'i
> gerekçesiyle reddedildi. Ne değiştiği madde madde **§12 DÜZELTMELER**'de. Künye
> `0240c16` idi ve **yanlıştı** — `HEAD` ölçüm anında `7dfb381`; aradaki 7 tender
> `.vue` değişikliği CSS'e dokunmuyor, yani satır atıfları geçerli, künye değildi.

Denetçinin hükmü — *"Aşama A beş güçlü tek-alan belgesi üretti ve BİR bileşen dili
üretmedi"* — bu belgenin varlık sebebi. Burada **yeni tasarım yok**: dokuz belgenin
kararları birleştirildi, birbiriyle çelişen yerleri karara bağlandı, ve **her sayı bu
oturumda yeniden ölçüldü**.

Bir uygulayıcı bu belgeyi okuyup kod yazabilmelidir. "İyi tasarlanmış olsun" cümlesi
hiçbir yerde geçmiyor.

---

## 0 · Kanıt rejimi ve öncelik sırası

### 0.1 · Hiçbir sayı devralınmadı

Çürütme turu beş şartnamede **49 ölçülmemiş iddia** buldu. Bu belgedeki her rakam bir
komutun çıktısıdır.

**Ve bu iddia sürüm 1'de kendisi de delindi:** üç çürütme raporu §0.1'in tablosunu tek
tek yeniden çalıştırdı, çoğunu doğruladı, ve **on bir sayıyı yanlış buldu**. Aşağıdaki
tablo düzeltilmiş hâlidir; değişen her satır **↺** ile işaretli ve eski değeri yazılı.
Bir ölçümün "doğrulandı" olması onu doğru yapmaz — **kapsamı** yanlışsa sayı da yanlış
olur, ve buradaki on bir hatanın altısı tam olarak kapsam hatasıydı.

| Ölçüm | Komut | Sonuç |
|---|---|---|
| Katman boyu | `wc -l stabler/public/css/stabler-modernist.css` | **1037** (brief "1038" diyor) |
| `ds-*` envanteri | `grep -oE '\.ds-[a-zA-Z0-9_-]+' …css \| sort -u \| wc -l` | **149** |
| `--ds-*` token | `grep -oE '(--ds-[a-z0-9-]+)\s*:' …css \| sort -u \| wc -l` | **28** |
| `disabled` geçişi | `grep -n disabled …css` | **2** — `930`, `931`, ikisi de köprüde |
| `ds-btn` kuralı | `grep -n 'ds-btn' …css` | **5** — `421, 427, 428, 429, 430` |
| `tgm-*` (drawer) | `grep -o 'tgm-[a-z0-9-]*' TenderMasterDrawer.vue` | **46 kullanım / 15 sınıf** |
| aynı dosyada `ds-` | `grep -c 'ds-' TenderMasterDrawer.vue` | **0** |
| Tender'ın bugün kullandığı `ds-*` | python, `class=` jetonlarını ayrıştırıp envanterle kesişim | **96 / 149** |
| Sıfır `ds-*` tender dosyası | `pages/tender/**` (27 dosya) | **17**, dördü `.vue`/`.js`'ten çağrılmıyor → **13 canlı** |
| ↺ Ölü dört dosya | `grep -rn <ad> --include='*.py'` — **kapsam düzeltildi** | `.vue`/`.js` referansı **0** ✔ ama **Python testlerinde 10 referans / 3 modül**: `test_tender_dashboard_i18n.py` (11,18,19,57), `test_tender_dashboard_spa.py` (17,18,19), `test_tender_master_board_spa.py` (4,20,37). **Üçü de `.github/frappe-free-tests.txt`'te** (117, 118, 122) → `make test` → `make check` → **push kapısı**. Ve `test_tender_master_board_spa.py:37` dosyanın **var olduğunu** iddia ediyor. "Ölü" nitelemesi `.vue` grafiğinde doğru, **depoda değil** |
| ↺ `SkeletonRows` (uygulama) | `grep -rn '<SkeletonRows' --include='*.vue'` | **79 dosya / 96 site** (eski: 80/97 — 97.'si `vehicleFinanceAgreements.spec.js:167`'deki bir **test dizesi**, çağrı yeri değil) |
| ↺ `SkeletonRows` yerleşimi (uygulama) | kaynak ayrıştırma, en yakın açık ata etiketi | **71 doğru (`<table>`) · 16 iç içe `<tbody>` · 9 öksüz** — sürüm 1 *"doğru kalıp hiçbir yerde uygulanmıyor"* diyordu, **yanlıştı** |
| `SkeletonRows` (tender) | aynı ayrıştırma, tender alt kümesi | **16 site, 0'ı doğru** (8 iç içe `<tbody>`, 8 öksüz) — doğrulandı, on altı dosya:satırın on altısı da |
| Hazır guard (K4+K5'in emsali) | `stabler/tests/test_ci_bill_link_panel_source.py:90-96` | `test_skeleton_is_a_direct_thead_sibling_not_nested_in_a_tbody` **zaten var** |
| `spinner-border` (tender) | `grep -rn` | **18** — 5'i boşlukta, 13'ü düğme içinde |
| ↺ `ds-btn` taşıyan `<button>` | python, etiket taraması | **36**; **12'si** devre dışı bağlamalı (10 dosya); gerekçe taşıyan **3** (eski: 4 — `PartyTransactions.vue:325`'in `:title`'ı koşulsuz bir açıklama, *"Professional Excel export of this ledger"*, devre dışılık gerekçesi değil) |
| ↺ Devre dışı bloğunun yayılma yarıçapı | aynı tarama, dosya bazında | tender kapsamı **7 düğme** (5'i `pages/tender`, 2'si `QuotationEntryDrawer`) · tender **dışı 5 dosya / 5 düğme** (`Login:262`, `Suppliers:594`, `Customers:391`, `PartyTransactions:325`, `SalesOrderFormModern:1245`). Sürüm 1 *"üç dosya"* diyip **beş** ad sayıyordu |
| **YENİ** `<button>` olmayan `ds-btn` taşıyıcısı | aynı tarama | **18 site** — `router-link`, `span`, `a`. Devre dışılığı `:disabled` ile değil `.disabled` **sınıfı** ile yazan canlı kalıp: `Customers.vue:401-407` |
| `ds-btn--primary` | `grep -rn` | **7 site / 6 dosya** (5 `<button>`, 1 `<router-link>`, 1 `<span>`) |
| `table-responsive` | `grep -rl` (uygulama) / tender | **148 dosya** / **7 site, 6 dosya**; `SourcingWorkspace` **0** |
| `EmptyState` | `<EmptyState>` etiketleri | **159 kullanım**, `compact` **16'sında** (ölü değil) |
| `STATUS_MAP` | `grep -cE '^\t"[^"]+":' composables/status.js` | **49 anahtar**; aranan 5'i **0** |
| Elle `badge bg-*` (tender) | `grep -rn 'class="[^"]*badge[^"]*bg-'` | **45 site / 10 dosya** |
| **YENİ** `class="badge"` + ayrı `:class` (tender) | `grep -rn 'class="badge"'` | **19 site** — 15'i yukarıdaki grep'in **dışında**, ve dördü sayfa-yerel rozet fabrikası (`TenderIntake:135`, `TenderIntake:177`, `MyTenders:90`, `PoControlBoard:132`) |
| ↺ `headerClass\|badgeClass\|stBadge` | `grep -rno`, jeton bazında | **26 site** (eski: 30 — `badgeClass` paylaşılan `getStatusBadgeClass`'ın **içinde** de eşleşiyordu, 4 kez çift sayılmış) |
| `<StatusBadge` (tender) | `grep -rn` | **0** |
| Mount altyapısı | `grep -n 'test-utils\|jsdom\|happy-dom' package.json` | **0 eşleşme** |
| `mount(` çağrısı | `grep -rn '\bmount(' tests/` | **0** (76 spec'in **17'si** adını **anıyor**) |
| `vitest` ortamı | `sed -n '15p' vitest.config.mjs` | `environment: "node"`, gerekçesi yazılı |
| `ds-cut*` canlı tüketici | `grep -rn 'ds-cut' --include='*.vue'` | **0** |
| `btn-xs` | kod / CSS | **14 kullanım / 5 dosya** ↔ **0 tanım** |
| `--ds-ok-t` | `grep -c` | **0** (crit-t, today-t, soon-t, info-t var) |
| `--ds-font-body` | `grep -n` | **2 kullanım** (921, 951), **0 tanım** |
| Tender'da tanımsız `ds-*` sınıfı | python, `class=` jetonları ↔ envanter | **0** (bosluk §1.4 `btn-xs`/`shadow-xs` hakkında; `ds-*` tarafı temiz) |

**Sürüm 2'de eklenen on iki ölçüm** — hepsi bir çürütme itirazının konusu:

| Ölçüm | Komut | Sonuç |
|---|---|---|
| `form-check-input` **tender kapsamında** | `grep -rn` (`pages/tender/**` + iki çekmece) | **4 site** — `SourcingWorkspace:932`, `TenderDocuments:70`, `PoControlBoard:709`, `TenderMasterDrawer:630`. Sürüm 1 **"0"** diyordu |
| `.stbl-ds` altındaki **tüm** `form-check-input` | aynı + `LandedChargesEditor:217` + `SalesOrderFormModern:1560` | **6 canlı kontrol** |
| `form-switch` **kodda** | `grep -rn 'form-switch' pages/tender` | **3** — `SourcingWorkspace:928`, `TenderDocuments:70`, `PoControlBoard:708`. Sürüm 1 yalnız **katmanı** ölçüp "0" yazmıştı |
| `ds-form-section-head` canlı tüketici | `grep -rn 'ds-form-section'` | **2** (`SalesOrderFormModern:1108`, `:1241`). Sürüm 1 **"0"** diyordu |
| `.ds-kpi[data-sev]` değerleri | `sed -n '250,257p'` | **crit, today, soon, ok** — **`info` YOK**. Blok I'in beşinci kuralı kopya değil **icat**tı |
| `ds-empty` yerel ezme | `grep -rn 'ds-empty' --include='*.vue'` | **1 dosya / 2 site** (`PartyTransactions:340`, `:584`). `TenderCrm.vue:789` `crm-col-empty ds-mono` — `ds-empty` **taşımıyor**, ezme değil |
| `ds-col-head` canlı | `grep -rn` | **1 site**, `TenderCrm.vue:**454**` (455 değil), satır-içi `:style`. `DeclarantQueue.vue:210` bir **`card-header`**, `ds-col-head` değil |
| `class="badge"` ile `<tr role="button">` | `grep -rn 'role="button"' pages/tender` | `TenderDocuments.vue:**257**` bir `<tr>` üzerinde — sürüm 1 *"tender'da 0 emsal"* diyordu |
| `nav-link` köprüde | `grep -n 'nav-link' …css` | **css:137**, kare-köşe sıfırlama listesinde. Sürüm 1 **"0"** diyordu |
| `a4-print` | `grep -rl` | **1 dosya** (`RfqPrint.vue`). Sürüm 1 **"4 dosya"** diyordu; `@media print` 5 dosyada, ama ortak bir `a4-print` **deseni yok** |
| `ds-field-req` **tender'da** | `grep -rn` | **0** (uygulama geneli 2, ikisi de `Login.vue`) — K11'i boşta doğru yapan sayı |
| Şeritli tablo (tender) | `class="table…"` jetonları, eksi `table-no-stripe` | **14** — `ds-table` göçünün şerit kaybı bu kadar tabloyu etkiliyor |
| `ListToolbar` (tender) | `grep -rln` | **1 dosya** (`rfq/RfqList.vue`) |
| `placeholder-glow` kuralı depoda | `grep -rn 'placeholder-glow' public/css/` | **0** → Tabler CDN'den geliyor, katman onu yeniden giydirmiyor. `ds-skel` ise katmanın kendi `ds-shimmer`'ı (css:446-448) → **aynı ekranda iki yükleme animasyonu** |
| `en.csv` girdi / belgenin yeni dizesi | `csv` ayrıştırma, 31 aday | katalogda **7000** girdi · belgenin yazdığı **15 dize katalogda YOK** (§4.3) |

**Kontrast — sürüm 1'de hiç ölçülmemişti** (§11 bunu itiraf ediyordu). WCAG 2.x göreli
parlaklık, token değerleri css:68-119'dan, **fallback** değerleriyle:

| Çift | Oran | Nerede kullanılıyor |
|---|---:|---|
| `--ds-ln` #e3e5e8 ↔ `--ds-bg` #f6f8fb | **1.19:1** | sürüm 1'in devre dışı **kesikli kenarı** — görünmüyor |
| `--ds-ln2` #c7ccd4 ↔ `--ds-bg` | 1.52:1 | etkin `ds-btn` kenarı |
| `--ds-tx3` #9099a6 ↔ `--ds-bg` | **2.71:1** | sürüm 2'nin kesikli kenarı **ve** devre dışı metni |
| `--ds-tx2` #667382 ↔ `--ds-bg` | 4.55:1 | (3:1'i geçen tek aday — §3.2-B'de neden seçilmediği yazılı) |
| `ds-chip[data-tone="crit"]` | 5.54:1 | ✔ |
| `ds-chip[data-tone="today"]` | 5.46:1 | ✔ |
| `ds-chip[data-tone="soon"]` | 4.72:1 | ✔ kontrast, ✘ token kuralı (metinde **dolgu** token'ı) |
| **`ds-chip[data-tone="ok"]`** | **2.47:1** | ✘ — 10.5px metin için eşik 4.5:1. §5.5(a) yeni işaretlemeyi **buraya** yönlendiriyordu |
| **`ds-sev[data-sev="info"] span`** | **3.03:1** | ✘ — 10px metin |
| `ds-sev[data-sev="soon"] span` | 5.30:1 | ✔ kontrast, ✘ token kuralı |
| `--ds-soon-t` #eef2f7 ↔ `--ds-info-t` #eef0f3 | **1.02:1** | blok H'nin dört ton zemini görsel olarak **üç** |
| `--ds-ok-tx` adayı #1c7430 ↔ #e8f7ea | 5.27:1 | §3.2-L'de yazıldı |
| `--ds-info-tx` adayı #5b6675 ↔ beyaz | 5.83:1 | §3.2-L'de yazıldı |
| `ds-label` (10px, `--ds-tx3` / #fbfcfd) | 2.80:1 | Ç30'un ölçülmemiş bedeli — §2 sıra 8'e yazıldı |

`--ds-*-tx` ailesinin tamamı: `grep -oE '\-\-ds-[a-z0-9-]*-tx'` → **yalnız `--ds-crit-tx`
ve `--ds-today-tx`**. Dört severity tonunun **ikisinde metin token'ı hiç üretilmemiş** —
brief §5.2'nin *"metin rengi ile dolgu/kenar rengi ayrı token'lardır"* kısıtının
ölçülmüş ihlali, ve sürüm 1 §0.1'de `--ds-ok-t`'nin yokluğunu **ölçüp** aynı ailedeki
bu deliği görmemişti.

Ölçemediklerim §11'de, adıyla.

### 0.2 · Çelişki çözüldüğünde hangi belge kazanır

1. **Beş şartname birbiriyle çelişiyorsa** → `UZLASTIRMA-celiskiler.md` (34 çelişki,
   hepsi karara bağlı). Görevin verdiği sıra budur.
2. **İki uzlaştırma dosyası birbiriyle çelişiyorsa** → §0.3'te tek tek karara bağlandı.
3. **Bir uzlaştırma dosyası ölçülmüş bir kusur üretiyorsa** → düzeltilir, ve düzeltme
   "kararın yeniden açılması" değil "aritmetiğin düzeltilmesi" olarak işaretlenir.
4. **Bir depo kuralı ile bir şartname çelişiyorsa** → depo kuralı kazanır ve değişikliği
   **Zafar'ın onayına** gider (§10). Bir şartname `CLAUDE.md`'yi ezemez.

### 0.3 · Dört uzlaştırma dosyası kendi arasında da çelişiyordu — 7 madde, karara bağlandı

Bu, bu turun kendi bulgusu. `UZLASTIRMA-celiskiler.md` (03:15) ve `UZLASTIRMA-delta.md`
(02:41) **aynı yedi soruya iki farklı cevap** veriyor ve toplamları uyuşmuyor
(149→151 ↔ 149→155).

| # | Konu | `celiskiler.md` | `delta.md` | **KARAR** ve gerekçe |
|---|---|---|---|---|
| **D1** | `ds-file-list/-chip/-name` | **EKLENMEZ** (Ç1: `form` kazanır; `ds-table` satırı + `ds-cut-del` + `FileSlot`) | **EKLENİR** (Ç3: `S1` kazanır) | **`celiskiler`.** Görevin verdiği öncelik + daha yeni. ADR-303'ün ispat yükü: gerekçe *"`ds-table` şunu yapamıyor"* olmalı; `cekmece` bu cümleyi yalnız `ds-chip` için kurdu, `ds-table` bileşimini hiç denemedi. **Bedeli adıyla:** 34px dokunma hedefi → `ds-table td` 11px dolgu + 30px `ds-cut-del`; mobilde daha küçük hedef, ve bu bir gerileme. |
| **D2** | Devre dışılığın "sebep" kabı | `ds-field-hint` (tekil sebep) + `ds-empty[data-tone="crit"]` (form özeti) | **yeni `.ds-blockers`** | **`celiskiler`.** İki yuva zaten var ve ikisi farklı işi yapıyor; üçüncü ad ADR-303'ün ispat yükünü karşılamıyor. `ds-field-hint`'in "sessiz gri" olduğu itirazı ölçülü ama hedefi ıskalıyor: **devre dışılığın sebebi bir hata değil bir kural ifadesidir** — katmanın kendi yorumu (css:578-580) ipucu satırını *"alanın hangi kuralı taşıdığını söyler"* diye tanımlıyor, ve deponun canlı kalıbı (`SourcingWorkspace.vue:995-1000`, `<span class="text-secondary small">` + `ti-lock`) tam da sessiz gri. |
| **D3** | `ds-empty[data-tone="crit"]` | **EKLENİR** (form gönderim özeti) | DÜŞER | **`celiskiler`.** D2'nin devamı; `[data-tone="ok"]` (css:445) ailesine ikinci üye, yeni ad değil. |
| **D4** | Tablo satırı vurgusu özniteliği | `data-sev` tek | `data-state="lead"` + `data-sev` | **`celiskiler`.** `data-state` **zaten dolu**: `ds-sla[data-state="in\|edge\|out\|unknown\|empty"]` (css:867-875). Aynı adı ikinci anlamla kullanmak, bu turun kapattığı belirsizliğin ta kendisi. Ayrıca `[data-sev]` ataya konunca satırdaki `.ds-sev` çocukları **kendiliğinden** renkleniyor (css:307-314) — bedava kazanç. |
| **D5** | `ds-btn:disabled` gövdesi | 4 bildirim: `color` · `border-color` · `background` · `cursor` | + `border-style: dashed` ve iki `:not(:disabled)` koruması | **`celiskiler`'in kararı + `delta`'nın iki ölçülmüş eklentisi.** `celiskiler` kendi ölçümüyle *"dördü de aynı kod (renk)"* diyor ve ikinci kodu **etikete** yüklüyor; `delta`'nın `dashed`'i **üçüncü** kodu (biçim) getiriyor. Bu bir kararın geri alınması değil, aynı kararın güçlendirilmesi — kurul ACCEPTANCE #8 "en az ikisi" istiyor, üçü de yazılıyor. Koruma ise **ölçülmüş bir kaskad kusuru**: `.stbl-ds .ds-btn--primary:hover` ve `.stbl-ds .ds-btn:disabled` **aynı özgüllükte (0-3-0)** — koruma olmadan doğruluk kural sırasına kalır, ve katmanın kendi yazılı ilkesi bunu yasaklıyor (css:160: *"doğruluğu kural SIRASINA bağlayan örtük bir bağımlılık olurdu"*). Deponun kendi kalıbı da bu: `TenderCrm.vue:900` `.crm-dw-del:hover:not(:disabled)`. |
| **D6** | `ds-btn[data-icon="1"]` geometrisi | `width: 34px` tek kural | `[data-icon="1"]` 40px + `[data-size="sm"][data-icon="1"]` 34px | **`delta`.** `celiskiler`'in tek kuralı `.ds-btn`'in kendi `min-height: 40px`'ini (css:424) yürürlükte bırakıyor → **34×40 dikdörtgen** ikon kutusu. Bu bir tasarım tercihi değil, bir aritmetik kusuru. İki değer de ölçülü: 40px `.ds-btn`'den, 34px köprünün `.btn-sm`/`.btn-icon`'undan (css:956, 961). |
| **D7** | `tr[data-sev]:hover` | `background: inherit` — ve §8'de *"denenmedi"* diye işaretli | ton başına ayrı `:hover` | **`delta`'nın biçimi.** `celiskiler` bu maddeyi açıkça açık bıraktı (*"uygulayıcı bunu ilk işi olarak denemeli"*). `inherit` `<tbody>`'nin arka planını alır ve o genelde `transparent`'tır — yani `tr`'nin kendi tonunu geri getirmeyebilir. **Tarayıcı olmadan doğruluğu kanıtlanabilir tek biçim ton başına açık kuraldır**; 1 kural yerine 4 kural, sıfır varsayım. |

**Sonuç:** `ds-*` envanteri **149 → 151**. Yazılmayan altı ad §3.4'te.

### 0.4 · Çürütmenin zorladığı altı ek karar (D8–D13)

Bunlar sürüm 1'de **karar bile değildi** — ölçülmemiş varsayımlardı. Üç rapor onları
ölçtü ve karar gerektirdiğini gösterdi.

| # | Soru | **KARAR** ve gerekçe |
|---|---|---|
| **D8** | Blok D (`ds-btn--commit[data-sev]`, 0-3-0) blok B'yi (`ds-btn:disabled`, 0-3-0) **sıra ile** eziyordu → silahlanmamış `Approve decision` kırmızı metin + kırmızı kesikli kenar çiziyordu, yani **etkin hâlinden daha alarmlı**. | **Blok D'nin dört kuralına da `:not(:disabled):not([aria-disabled="true"])` konur.** Belgenin blok A için yazdığı ilkenin (css:160, *"doğruluğu kural SIRASINA bağlayan örtük bir bağımlılık"*) kendi deltasına uygulanması. Sıraya değil **seçiciye** yazılır: bloklar sonra yeniden sıralansa bile doğru kalır |
| **D9** | Kesikli kenar `--ds-ln` ile **1.19:1** — görünmeyen bir çizginin kesikliliği bir kod değil. | **Kenar `--ds-tx3`'e taşınır (2.71:1)** *ve* "üç kod" iddiası **"iki taşıyıcı + bir destekleyici"** olarak düzeltilir. `--ds-tx2` (4.55:1) reddedildi: devre dışı bir düğmenin kenarını **etkin** düğmeninkinden (1.52:1) üç kat koyu yapardı — "devre dışı geri çekilir" ilkesinin tersi. `--ds-tx3` metinle aynı token, düğme tek bir gri birim olarak okunur, ve etkin kenara göre 1.78× kontrast adımı var. **2.71:1 hâlâ 1.4.11'in 3:1'ini geçmiyor ve bu yazılı** — kod destekleyicidir, taşıyıcı değil |
| **D10** | `ds-chip[data-tone="ok"]` metin rengi için **dolgu** token'ı kullanıyor: **2.47:1**, 10.5px. Brief §5.2'nin "pazarlık dışı" kısıtı. Ve §5.5(a) yeni işaretlemeyi tam oraya yönlendiriyordu. | **`--ds-ok-tx: #1c7430` ve `--ds-info-tx: #5b6675` eklenir** (blok L), üç bildirim yeniden yazılır. **`--ds-soon-tx` eklenmez:** `soon` kontrastı geçiyor (4.72 / 5.30), yalnız token ayrımı kuralını çiğniyor — görsel değişiklik üretmeyen bir yeniden adlandırma bu deltanın işi değil, **B-18**'e gider |
| **D11** | Blok J'nin `border-radius: 0`'ı üç canlı `form-switch`'i kareleştiriyordu; ve özgüllük Bootstrap'la **berabere** (0-2-0), doğruluk yükleme sırasına kalıyordu. | **Seçici `.ds-form-check .form-check-input` değil, `.form-check:not(.form-switch) .form-check-input` olur**, ve yarıçap sıfırlaması katmanın **kendi** `!important`'lı listesine (css:136-138) eklenir. Yani: onay kutuları kareleşir, **switch'ler bugünkü hâllerinde kalır**. `form-switch` yasağı yürürlükte, ama **göçü Aşama B'ye adıyla yazılı** (B-16, üç site). Bir kontrolü yasaklayıp aynı anda kimse taşımadan bozmak kabul edilemez |
| **D12** | B13 (`ds-form-section`) ile B5 (`ds-drawer-foot`) **iç içe**; tanım "en küçük eleman" diyor, tablo ikisini birden sayıyor, K8 üçüncü bir cevap veriyor. | **R9 yazılır** (§5.2): iç içe bölgelerde kota **en dış bölge kökünde** toplanır, iç kökler onun **yuvası**dır. `ds-form-section` bir **bölge**, `ds-form-section-head` ve `ds-drawer-foot` onun **iki yuvası** — ikisi birlikte ≤1 primary. B4 ve B5 bağımsız birer bölge olarak yalnız **B13'ün dışında** (panel başlığı, çekmece altbilgisi) geçerlidir. Tanım cümlesi *"en küçük eleman"*dan *"kendi kenarı/zemini ile ayrılan **en dış** eleman"*a düzeltilir |
| **D13** | `EmptyState.vue` **dördüncü lehçe**: 8 sınıflık `stabler-empty-*`, `<style scoped>` içinde, katmanda 0 kural, ve **iki `border-radius: 50%`** (`:81`, `:111`) — `--ds-radius: 0` ilan eden bir sistemin içinde iki tam daire. `tgm-*`'e sorulan uzlaştırma sorusu buna hiç sorulmadı. | **Bu turda uzlaştırılmaz, ve bu bir karar.** Gerekçe: `EmptyState` **159 kullanım / uygulama geneli** — `tgm-*`'in (1 dosya) aksine bir tender sorunu değil, bir **uygulama** sorunu, ve bu turun kapsamı tender'dı. Ama sürüm 1'in *"üç lehçe"* sayımı **yanlıştı**: dört. Adıyla **B-17**'ye yazılır ve §1.2'de `EmptyState` satırına *"kendi lehçesini taşır, katman ona ulaşmaz"* notu düşülür |

---

## 1 · SÖZLÜK — tender'ın kullanacağı `ds-*` alt kümesi

### 1.1 · Önce mevcut: tender **bugün** 149 sınıfın 96'sını zaten kullanıyor

Bu, ADR-303'ün *"sorun kelime dağarcığı değil benimseme"* hükmünün ölçülmüş hâli.
Ölçüm (python, `class=` jetonlarını ayrıştırıp `stabler-modernist.css`'in `.ds-*`
envanteriyle kesişim, kapsam `pages/tender/**` + `TenderMasterDrawer` + `QuotationEntryDrawer`):

```
katman envanteri            149
tender bugün kullanıyor      96
kullanılmayan                53
tender'da tanımsız ds-* sınıfı  0
```

Kullanılan 96'nın çoğu **hiçbir şartnamede belgelenmemiş** ama kod onlara bağımlı:
`ds-funnel-*` (7 sınıf, `TenderFunnel.vue`), `ds-stage-*` (6, `DirectorBoard`/`TenderFlow`),
`ds-row-*` (8, `OperationsDesk`), `ds-load-*` (4), `ds-week-*` (3), `ds-loss-*` (5),
`ds-kpi-*` (5), `ds-band-*` (3), `ds-modnav*` (2), `ds-meter*` (3).

> **Kural:** bunlar **icat değil, kayıt.** Aşama B'nin ekran şartnameleri bu 96'yı
> yeniden tasarlamaz; belgeler. Bir ekran onlardan birini değiştirecekse gerekçesi
> ekran şartnamesinde yazılı olur.

### 1.2 · Dağarcık — tender'ın **yeni yazacağı** işaretlemenin tamamı

> **Sürüm 1 bu listeyi "kapalı" ilan ediyordu ve bu ölçülerek çürütüldü.** Tender'ın
> bugün kullandığı 96 sınıfın **55'i** bu tabloda yok (`ds-row-*` 10, `ds-funnel-*` 7,
> `ds-stage-*` 7, `ds-kpi-*` 5, `ds-loss-*` 5, `ds-load-*` 4, `ds-band-*` 3,
> `ds-week-*` 3, `ds-meter` çocukları 2, `ds-modnav*` 2, ve 7 tekil). Aynı belge §1.1'de
> onları **korumayı emrediyordu**. İki kural aynı anda uygulanamaz: `TenderFunnel`'a
> dokunan biri `ds-funnel-t`'yi ne yazabilir ne silebilirdi. Üstelik bu deltanın kendi
> gerekçeleri o 55'in üçüne dayanıyor (`ds-row--lead` → blok H, `ds-kpi[data-sev]` →
> blok I, `ds-step[aria-current]` → blok B).

**Düzeltilmiş kural — iki küme, iki rejim:**

| Küme | Ne | Rejim |
|---|---|---|
| **Kayıtlı 96** (§1.1) | tender'ın bugün kullandığı, katmanda tanımlı `ds-*` | **Korunur.** Kullanılabilir, değiştirilemez. Bir ekran birini değiştirecekse gerekçesi o ekranın Aşama B şartnamesinde yazılı olur |
| **Aşağıdaki tablo** | tender'ın **yeni işaretlemede** yazacağı dağarcık | **Kapalı.** Bir tender dosyası, kayıtlı 96'nın dışında ve bu tabloda olmayan bir `ds-*` veya köprü sınıfı yazacaksa, önce bu belge değişir |

Yani kapalılık **yeni yazıma** bağlanır, mevcut kullanıma değil. 55 sınıfın
belgelenmesi kayıt işidir ve **B-6**'dadır.

| Rol | Sınıf / bileşen | Tanım | Beş hâl | Kaynak karar |
|---|---|---|---|---|
| **— Aksiyon —** | | | | |
| Nötr aksiyon | `ds-btn` | css:421 | §7 | Ç16 |
| Bölgenin beklenen aksiyonu | `ds-btn--primary` — **bölge başına ≤1** | css:428 | §7 | Ç21, R1 |
| Geri alınamaz aksiyon | `ds-btn--commit` + silahlama kutusu | **YENİ** | §7 | Ç2, A6 |
| Küçük düğme | `ds-btn[data-size="sm"]` (34px) | **YENİ varyant** | §7 | Ç19 / D-Ç1 |
| İkon düğmesi | `ds-btn[data-icon="1"]` (40px kare) · sm ile 34px kare | **YENİ varyant** | §7 | D6 |
| Devre dışı | `:disabled` **+ yanında sebep** (`ds-field-hint` veya `:title`) | **YENİ** | §7 | Ç20, D2, D5 |
| Bekleme | **etiket takası** + `aria-busy="true"` + `:disabled` — spinner elemanı yok | — | §7 | Ç9 |
| Seçim durumu (aksiyon değil) | `ds-seg` + `aria-pressed` | css:431 | §7 | R4 |
| Aksiyon çubuğu | `ds-drawer-foot` — **seçici serbest** (css:669, `.ds-drawer` atası şart değil) | css:669 | §7 | Ç24 |
| Sayfa başlığı şeridi | `ds-actions` — **yalnız `.ds-page-head` altında biçimlenir** (css:203) | css:203 | §7 | R8 |
| **— Kap —** | | | | |
| Çekmece | `ds-drawer[data-size="lg"]` (760px) + `-backdrop` `-head` `-title` `-kicker` `-close` `-body` `-foot` | css:644-672 | §7 | Ç-S1 |
| Panel | `ds-panel` + `-head` | css:260-264 | §7 | — |
| Kaynak beyanı | `ds-panel-foot` — **hiçbir hâl taşımaz** | css:549 | — | Ç24, Ç6 |
| Form bölümü | `ds-form-section` + `-head` + `ds-form-body` | css:568-573 | §7 | Ç-S1 §2.6 |
| Commit bölgesi | `ds-form-section[data-commit="1"]` | **YENİ varyant** | §7 | Ç2, Ç21 |
| Kanban | `ds-kanban` > `ds-col` > `ds-col-head`(`-n`/`-t`) / `ds-col-rule` / `ds-card`(`-t`/`-id`/`-org`/`-foot`) | css:369-384 | §7 | bosluk §4.7 |
| Kulvar aciliyeti | `ds-col-head[data-sev]` | **YENİ varyant** | §7 | Ç22 |
| Dolu-renk cevap kutusu | `ds-fill` + `ds-fill-n` | css:345-349 | §7 | aksiyon §7.2 |
| Salt-okuma özet | `ds-deflist` | css:675-684 | §7 | bosluk §3.6 |
| **— Form —** (tam gramer §4) | | | | |
| Bölüm başlığı metni | `<span class="ds-label">A · {{ t("…") }}</span>` | css:181 | §7 | Ç30 |
| Izgara | `ds-form-grid[data-cols="2"]` — **`"3"` tender'da yasak** | css:574-576 | §7 | Ç11 |
| Alan | `<label class="ds-field">` (çok kontrollüde `<div role="group">`) | css:582 | §7 | Ç12, Ç13 |
| Etiket | `ds-field-label` | css:583 | §7 | — |
| Zorunluluk | `ds-field-req` + `aria-hidden="true"` **ve** kontrolde `aria-required`/`required` | css:588 | §7 | Ç14 |
| İpucu / kural bildirimi | `ds-field-hint` — **asla boş hâl taşımaz** | css:589 | §7 | Ç7, D2 |
| Alan hatası | `ds-field-err` + kontrolde `aria-invalid="true"` | css:590 | §7 | Ç6 |
| Metin girdisi | `ds-input` · çok satırlı `textarea.ds-input` (`rows` yazılmaz) | css:437, 592 | §7 | form §3.6 |
| Onay kutusu ← **12. madde** | `form-check` + `form-check-input` (köprü) — **`form-switch` yasak** | **YENİ köprü** | §7 | Ç15, Ç27 |
| Para | `MoneyInput` + `formatMoney`/`moneyFractionDigits` | `components/MoneyInput.vue` | §7 | manda 3 |
| Yüzde ← **10.4(a)** | `.input-group` + `.form-control` + `<span class="input-group-text">%</span>` — **`ds-input` YASAK** (esneklik sözleşmesi dışı, `%` alt satıra düşer) | `BidPricing.vue:170-173` | §7 | manda 3 ✔ |
| Tarih | `DateInput` + `formatDate` | `components/DateInput.vue` | §7 | manda 4 |
| Tipeahead | `Typeahead` + **sarmalayan** `<label class="ds-field">` | `components/Typeahead.vue` | §7 | Ç13 |
| Çoklu seçim **ve** dosya eki | **tek jeton listesi**: `ds-table` + `ds-cut-del` + `ds-cut-add` + ekleyici (`Typeahead` / `FileSlot`) | css:389, 785, 790 | §7 | Ç1, D1 |
| Köprülenmiş kontrolde geçersizlik | `.form-control[aria-invalid="true"]` — `MoneyInput`/`DateInput`'a **artık ulaşıyor** (`f267e6d`); `Typeahead`/`MultiSelectPicker`'a hâlâ ulaşmıyor, §4.1(a) | **YENİ köprü** | §7 | form delta-2, §10.9 ✔ |
| **— Veri —** | | | | |
| Tablo | `ds-table`, **`table-responsive` sarmalayıcı zorunlu** | css:389 | §7 | Ç3 |
| Şeritli tablo ← **varsayılan** | `class="ds-table table"` — göç eden her tablo bunu yazar; şerit korunur (14 tablo) | `stabler.css:145` | §7 | §10.8(b) ✔ |
| Liste ekranı araç çubuğu ← **bu turda eklendi** | `ListToolbar` — **manda 8 ile zorunlu**, filtre/arama elle kurulmaz | `components/ListToolbar.vue` | §7 | manda 8, K17 |
| Sayısal hücre/başlık | `ds-td-num` — **`ds-col-n` DEĞİL** | css:399 | §7 | Ç26 |
| Satır vurgusu | `tr[data-sev]` + satırda `ds-chip[data-tone]` | **YENİ varyant** | §7 | Ç34, D4 |
| Durum rozeti | `<StatusBadge>` — elle `class="badge bg-*"` **yasak** | `composables/status.js` | §7 | manda 7, Ç22 |
| Sıralama / aciliyet | `ds-chip[data-tone]` · `ds-sev` (bir `[data-sev]` **atası** ister) | css:406, 304 | §7 | Ç22 |
| Politika sayacı | `ds-meter` (rozet değil, ölçer) | css:337 | §7 | aksiyon G6 |
| Kimlik / mono metin | `ds-mono` · sayı `ds-num` | css:188, 189 | — | — |
| **— Hâl —** (tam gramer §6) | | | | |
| Yükleniyor · tablo | `SkeletonRows` — **`<table>`'ın doğrudan çocuğu** | `components/SkeletonRows.vue` | §6 | Ç4, A5 |
| Yükleniyor · tablo dışı | `ds-skel-stack` > `ds-skel` ×3 | **YENİ** | §6 | Ç4 |
| Yükleniyor · alan içi | `.ds-field .ds-skel` (44px) | **YENİ varyant** | §6 | form delta-3 |
| Boş · birincil | `<EmptyState>` (çekmece/kulvar içinde `compact`) — **kendi `stabler-empty-*` lehçesini taşır, katman ona ulaşmaz** (D13, B-17) | `components/EmptyState.vue` | §6 | Ç7 |
| Boş · ikincil | `ds-empty[data-size="sm"]` | **YENİ varyant** | §6 | Ç7 |
| Hata · bölge | `alert alert-danger` + `role="alert"` + `ds-mono` ham metin + "Try again" | css:1013 (köprü) | §6 | Ç6 |
| Hata · form gönderim özeti | `ds-empty[data-tone="crit"]` + `role="alert"` + `tabindex="-1"` | **YENİ varyant** | §6 | Ç6, D3 |
| Yetkisiz | `alert alert-warning` + `role="alert"` + `ti-lock` + rota düğmesi | css:1013 (köprü) | §6 | durum §5 |
| Ölçülemiyor (5. hâl) | `ds-sla[data-state="unknown"]` | css:874 | §6 | durum §6 |
| Test kancası | `data-region-state="loading\|empty\|error\|forbidden"` — **hiçbir CSS ona bağlanmaz** | — | §6 | Ç10 |

### 1.3 · Yasak liste — tender dosyalarında **yazılmayacak** olanlar

| Yasak | Yerine | Ölçülen bugünkü durum | Gerekçe |
|---|---|---|---|
| Elle `class="badge bg-*"` | `<StatusBadge>` | **45 site / 10 dosya** | manda 7 |
| ↺ Elle `class="badge"` + ayrı `:class` bağlaması | `<StatusBadge>` | **19 site**, 15'i yukarıdaki grep'in dışında | manda 7 — **sürüm 1 bu kalıbı hiç görmemişti**, K10 onunla oynanabiliyordu |
| ↺ Sayfa-yerel rozet fabrikası (`headerClass` / `badgeClass` / `stBadge` / `riskBadge` / `fxBadge` / `badgeMeta`) | `STATUS_MAP` + `data-sev` | **26 site** + **4 fabrika** (`TenderIntake:135`, `TenderIntake:177`, `MyTenders:90`, `PoControlBoard:132`) | manda 7, Ç22 |
| Boşlukta `spinner-border` | `SkeletonRows` / `ds-skel-stack` | **5 site** (adlarıyla §8-K5) | manda 9 |
| Düğme içi `spinner-border` | etiket takası + `aria-busy` | **13 site** | Ç9 |
| `ds-form-grid[data-cols="3"]` | `data-cols="2"` | tender'da **0** (mevcut tek `data-cols="3"` `ds-kpis` üzerinde — meşru) | Ç11 |
| ↺ `<tr role="button">` | satırda gerçek `<button>` + fare için `@click`+`cursor:pointer` | tender'da **1 canlı ihlal**: `TenderDocuments.vue:257` — ve o dosya §5.5(d)'de yeniden tasarlanıyor. Sürüm 1 üç öznitelikli birebir dizeyi arayıp *"0 emsal"* demişti | Ç18 |
| `ds-col-n` bir `<th>` üzerinde | `ds-td-num` | seçici `.ds-col-head .ds-col-n` (css:375) → `<th>`'de **etkisiz** | Ç26 |
| ↺ `form-switch` (**yeni işaretlemede**) | `form-check` | **kodda 3 canlı site**: `SourcingWorkspace:928`, `TenderDocuments:70`, `PoControlBoard:708`. Sürüm 1 *"katmanda 0"* diyordu — **yasağın konusunu hiç saymamıştı.** Üçünün göçü **B-16**; delta onları bozmuyor (D11) | Ç15 |
| `btn-xs`, `shadow-xs` | `ds-btn[data-size="sm"]` | **14 kullanım / 5 dosya**, **0 tanım** — "çok küçük" yazıp 44px alıyor | bosluk §1.4 |
| `useConfirm()` ile ikinci diyalog (ödül onayında) | DOM'da duran silahlama kutusu | `useConfirm` 59 dosyada canlı, ödül panelinde **0** | Ç2 |
| `ds-panel-foot` bir hâl taşıyıcısı olarak | `alert` / `ds-empty` / `ds-skel-stack` | `OperationsDesk.vue:64-76` **dört hâli** aynı sınıfla çiziyor | Ç6, Ç24 |
| `ds-table-wrap` | `table-responsive` (**148 dosya**) | katmanda **0** | Ç3 |
| Köprü `.btn-*` ailesi | `ds-btn` ailesi | — | Ç16 — **ama Aşama B'de yürürlüğe girer, §10.2** |

### 1.4 · Sözlüğün **kapatmadığı** beş yer (ölçüldü, Aşama B'ye)

| Boşluk | Mevcut `ds-*` yeter mi | Ölçüm | Gereken |
|---|---|---|---|
| (a) Filtre / araç çubuğu | **Evet** — `ListToolbar` köprüye (`form-control`, `btn`) zaten bağlı | tender'da `ListToolbar` **1 dosyada** (`rfq/RfqList.vue`); sekiz ekran kendi filtresini elle kurmuş | CSS değil **göç**: 8 ekran `ListToolbar`'a |
| (b) Bağlantı / gezinme | **Hayır** | `ds-link` katmanda **0**; `TenderOverview.vue:243` kendi yorumunda *"`ds-link` diye bir sınıf yok"* diyor ve `.ov-link`'i elle yazmış | 1 yeni sınıf `ds-link` — Aşama B'nin ilk delta maddesi |
| ↺ (c) Sekme | **Hayır**, ama gerekçe zayıfladı | `ds-tabs`/`ds-tab` envanterde **0** ✔; `nav-tabs` köprüde **0** ✔; **ama `nav-link` köprüde VAR — css:137**, kare-köşe sıfırlama listesinde, `!important` ile. Yani köprü sekmelere **zaten dokunuyor**. `TenderWorkspaceTabs.vue:**33-43**` (34-44 değil) çıplak Bootstrap, dosya **canlı** (`PoControlBoard.vue:365`) | yeni çift `ds-tabs`/`ds-tab`. *"Beşin içindeki tek gerçek yeni bileşen"* hükmü **ölçülmemiş bir sıfıra** dayanıyordu; hüküm ayakta ama artık "köprünün kapsamadığı tek bileşen" değil, "köprünün yalnız köşesini kapattığı bileşen" |
| (d) Grafik / SVG | **Hayır**, ve `ds-flow-*`'u genişletmek **yanlış** | `ds-flow*` ailesi tamamen ölü; jeneratörü (`tools/build_flow_svg.py`) **depoda yok** | Yalnız `TenderTrendChart` canlanırsa. **Zafar'a soru** (§10.5) |
| ↺ (e) Print | **Soru yanlış** — `stbl-ds`'in bunu karşılaması gerekmiyor | katmanda `@media print` **0** ✔. Ama *"`a4-print` deseni 4 dosyada"* **yanlıştı**: `a4-print` **1 dosyada** (`RfqPrint.vue`, kendi scoped style'ında). `@media print` 5 dosyada, ve üç ayrı yerel yakınsama kullanıyorlar (`a4-print` ×1, `print-wrapper` ×2, hiçbiri ×2). **Ortak bir print deseni yok** | **Sürüm 1'in talimatı (*"`RfqPrint`'i `a4-print`'e uydur"*) hiçbir şey yapmayan bir no-op'tu — `RfqPrint` zaten `a4-print`'in tek dosyası.** Düzeltilmiş hüküm: print **tender tasarım dilinin kapsamı dışıdır**, hiçbir iş yok. Beş print ekranının ortak bir dile taşınması ayrı bir iş ve bu belgenin konusu değil |
| (f) Salt-okuma **form** dili | **Kısmen** — `.form-control:disabled` (css:930) hazır | `TenderMasterDrawer`'da yazma-yetkisi kavramı **0** | `ds-btn:disabled` bu deltada kapanıyor; form-içi "salt-okuma görüyorsun" bildirimi Aşama B'de, `durum`'un sayfa-düzeyi yetkisiz deseninin küçük varyantı olarak |

---

## 2 · UZLAŞTIRMA TABLOSU — 15 `tgm-*` sınıfının **15'i** karara bağlı

Kapsam: `components/TenderMasterDrawer.vue` (777 satır, `<style scoped>` :658, `tgm-*`
46 kullanım / 15 sınıf, `ds-*` **0**). Göçün ön koşulu doğrulandı: dosya tek yerden
mount ediliyor (`TenderCrm.vue:753`) ve `<TenderPage>` sarmalayıcısının içinde — yani
`.stbl-ds` atası **var**, `ds-*` kuralları çekmeceye ulaşacak.

Karşılaştırma noktası: `ds-drawer`'ın repodaki **iki** canlı örneği —
`TenderCrm.vue:579` (varsayılan 542px) ve `QuotationEntryDrawer.vue:225` (`data-size="lg"`,
760px).

| # | `tgm-*` | Hedef | Ölçülen çakışma | **KARAR** | Diğer ekranlara etkisi |
|---|---|---|---|---|---|
| 1 | `tgm-drawer` | `ds-drawer[data-size="lg"]` (css:648, 655) | `width` 720↔**760** · `z-index` 1050↔**41** · `border-left` yok↔2px `--ds-ink` · `box-shadow` -4/24↔**-12/32** · `overflow` yok↔hidden | **Katman kazanır.** `data-size="lg"`. z-index §10.3'te **çözülmemiş mimari soru**. | Yok — `lg` zaten var, CSS değişmiyor |
| 2 | `tgm-drawer-body` | `ds-drawer-body` (css:668) | fark yok | Katman kazanır | Yok |
| 3 | `tgm-drawer-header` | `ds-drawer-head` (css:657) | `padding` 16/24↔18/16/16 · `align-items` center↔flex-start · **`justify-content` space-between ↔ TANIMSIZ** | **Katman kazanır, tek istisnayla:** `justify-content: space-between` **tgm'den katmana taşınır** (§3.2-blok E). Ölçüldü: katmanda gerçekten yok, ve iki tüketici ona iki farklı yerel cevap vermiş | **`QuotationEntryDrawer` değişir** — kapat düğmesi sağ kenara gider. Bu görünür bir değişikliktir ve adlandırılmıştır |
| 4 | `tgm-drawer-title` | `ds-drawer-title` (css:662) | 18px↔**22px**, `font-family` yok↔`--ds-font-head` | Katman kazanır | Yok |
| 5 | `tgm-drawer-footer` | `ds-drawer-foot` (css:669) | `padding` 12/24↔14/16 · `background` #fbfcfe↔yok · **`justify-content` flex-end↔tanımsız** · `flex-wrap` yok↔**wrap** | **Katman kazanır**, düğme **sırası** şablonda ters çevrilir (primary öne) | Yok — CSS değişmiyor |
| 6 | `tgm-kicker` | `ds-drawer-kicker` (css:661) | 10.5↔11px · uppercase var↔yok · `color` gri↔**mavi `--ds-acc`** · weight 700↔yok | Katman kazanır; kicker **içeriği** de sözleşmeye uyar | Yok |
| 7 | `tgm-section` | `ds-form-section` (css:568) | `border` yalnız-alt↔**dört kenar** · `background` miras↔`--ds-surface` · `margin-bottom` yok↔14px | **Katman kazanır** — bitişik yığın → ayrık kartlar. ADR-302 bunun bir **tasarım kararı** olduğunu söylüyor; onaylandı | Yok |
| 8 | `tgm-sec-head` | `ds-form-section-head` (css:569) | `padding` 10/24↔11/16 · `gap` 8↔12 · **`font-size:13px`/`weight:700` katmanda YOK** | Katman kazanır; **tipografi çocuğa iner:** `<span class="ds-label">`. **↺ Bedeli ölçüldü ve sürüm 1'de yazılmamıştı:** bölüm başlığı 13px koyu (miras, ≈14.9:1) iken **10px uppercase `--ds-tx3`, 2.80:1** oluyor. Bu bir **gerileme** ve kabul ediliyor — çünkü `ds-label` sistemin **her** bölüm başlığında kullandığı ortak dil (emsal `SalesOrderFormModern` ×3) ve tek bir çekmece için ondan sapmak dördüncü bir lehçe üretirdi. Bir başlığın 2.80:1'de olması Aşama B'nin **katman-düzeyi** sorusudur, tender'ın değil | Yok |
| 9 | `tgm-sec-body` | `ds-form-body` (css:573) | `padding` 16px **24px** ↔ 16px | Katman kazanır | Yok |
| 10 | `tgm-sec-num` | **karşılığı gerekmiyor** | 22×22 rozet, `border-radius:6px`, mavi zemin — `--ds-radius: 0` ile doğrudan çelişiyor | **Boşluk DEĞİL.** Metin öneki: `<span class="ds-label">A · {{ t("…") }}</span>`. Ç30 bu soruyu **kapattı**; emsal `SalesOrderFormModern.vue:1109/1242/1350`, üç kez | Yok |
| 11 | `tgm-file-list` | **`ds-table`** (jeton listesi) | katmanda `ds-file-list` **0** | **Yeni sınıf YAZILMAZ** (D1). Jeton listesi: `ds-table` gövdesi | Yok |
| 12 | `tgm-file-chip` | **`ds-table` satırı** + kaldır düğmesi `ds-cut-del` | katmanda **0**; `border-radius:7px` `--ds-radius:0`'a aykırı | **Yeni sınıf YAZILMAZ** (D1). `FileSlot` (zaten import: `:29`, kullanım `:470`) dropzone'u sağlar. **Bedeli:** 34px hedef → 30px `ds-cut-del`; gerileme, gizlenmiyor | `ds-cut-del`/`ds-cut-add` bugün **0 canlı tüketici** → sıfır regresyon riski |
| 13 | `tgm-file-name` | `ds-mono` + `ds-table td` | katmanda **0** | **Yeni sınıf YAZILMAZ** (D1) | Yok |
| 14 | `tgm-drawer-dialog` | **karşılığı olmamalı** | `height:100%;display:flex;flex-direction:column` | **SİLİNİR** — `ds-drawer` tek flex `<aside>` getiriyor (ADR-302 lafzı) | Yok |
| 15 | `tgm-drawer-content` | **karşılığı olmamalı** | `tgm-drawer-dialog` ile **birebir aynı kural gövdesi** | **SİLİNİR** | Yok |

**Toplam:** 15 sınıfın **9'u** katmandaki adaşına eriyor · **2'si** siliniyor ·
**3'ü** (`file-*`) mevcut parçalara dağıtılıyor · **1'i** (`sec-num`) metin önekine
dönüşüyor. **Katmana `tgm-*` kaynaklı tek dokunuş:** `ds-drawer-head`'e
`justify-content: space-between` (1 bildirim).

**Ve çekmecenin kendisinde iki ek düzeltme** (ölçüldü, hiçbir şartname birleştirmemişti):
`TenderMasterDrawer.vue:517` ve `:606` çıplak `<input type="number">` taşıyor — manda 3'ün
kapsamına giriyorsa `MoneyInput`, girmiyorsa §10.4'ün cevabını bekliyor.

---

## 3 · TEK CSS DELTASI

### 3.1 · Landing sırası ve nedeni

| Sıra | Blok | Neden bu sırada |
|---|---|---|
| 1 | A · Mevcut iki `:hover` seçicisinin değişmesi | Devre dışı bloğu **onlardan sonra** gelirse aynı özgüllükte (0-3-0) çakışır. Korumalar **önce** lander |
| 2 | B · Devre dışı ekseni | **Göçten ÖNCE** lander. Yoksa `btn btn-primary` → `ds-btn--primary` göçü, bugün GÖRÜNEN bir devre dışı hâli GÖRÜNMEZ yapar (kurul ACCEPTANCE #8) |
| 3 | C–L · Kalan bloklar | Sırası serbest — **çünkü D8'den sonra öyle.** Sürüm 1 bunu *"hiçbiri diğerine bağlı değil"* diye yazıyordu ve **yanlıştı**: blok D, blok B ile aynı özgüllükteydi (0-3-0) ve sonra indiği için onu eziyordu. Artık bağımlılık **sıraya değil seçiciye** yazılı (`:not(:disabled)`), yani sıra gerçekten serbest |
| 4 | Mevcut kurallara birer bildirim | Yayılma yarıçapı **yeniden** ölçüldü — biri sıfır değil, aşağıda |

### 3.1b · İnişin gerçek yayılma yarıçapı — sürüm 1'in en ağır hatası

Sürüm 1 kalın harflerle *"**Bu delta tek başına hiçbir ekranı değiştirmez**"* diyordu.
**Üç çürütme raporunun üçü de bunu bağımsız olarak çürüttü.** Ölçülmüş doğru hâli:

| Blok | Bugünkü tüketici | İniş anındaki etki |
|---|---|---|
| **B · devre dışı** | 12 düğme / 10 dosya | **Değişir** — istenen etki. Tender kapsamı 7 düğme, tender **dışı 5 dosya / 5 düğme** (sürüm 1 *"üç dosya"* deyip beş ad sayıyordu) |
| **J · `form-check-input`** | **6 canlı kontrol**, sürüm 1 *"tender'da 0"* diyordu | **Değişir** — onay kutuları kareleşir ve işaret rengi Tabler mavisinden `--ds-acc`'a kayar. Üç `form-switch` **D11 ile kapsam dışında bırakıldı**, yani hap biçimini korurlar |
| **K · `ds-drawer-head`** | 2 çekmece | **Değişir** — `QuotationEntryDrawer`'da kapat düğmesi sağ kenara gider. §2 sıra 3 bunu zaten adıyla yazıyordu; §3.1'in *"sıfır regresyon"* cümlesi **kendi belgesiyle çelişiyordu** |
| **K · `ds-form-section-head`** | **2 tüketici** (`SalesOrderFormModern:1108`, `:1241`), sürüm 1 *"0"* diyordu | **Değişir** (düşük şiddet) — `space-between` + `flex-wrap` dar ekranda sağ yuvayı ikinci satıra indirir |
| **L · `ds-chip[ok]` / `ds-sev[info]`** | 3 çip sitesi + `ds-sev` taşıyan 7 dosya | **Değişir** — 2.47:1 ve 3.03:1'lik iki metin okunur hâle gelir. Görsel değişikliktir ve istenen etkidir |
| **K · `.ds-field { display: block }`** | 3 site / 2 dosya | **Sıfır regresyon** — bu iddia doğrulandı (`Login:176,198` zaten `<div>`, `TenderCrm:390` bir flex item) |
| C, D, E, F, G, H, I | `data-size` 0 · `ds-btn--commit` 0 · `data-commit` 0 · `ds-empty[data-size]` 0 · `ds-skel-stack` 0 · `tr[data-sev]` 0 · `ds-col-head[data-sev]` 0 | **Sıfır** — doğrulandı |

**Yani delta beş ayrı bloktan ekran değiştirir, sürüm 1 birini söylüyordu.**
Ve blok I'in ayrı bir kusuru var: tek canlı `ds-col-head` tüketicisi
(`TenderCrm.vue:454`) **satır-içi `:style`** taşıyor, o her seçiciyi yener — yani blok I,
o satır-içi stil kaldırılana kadar **hiçbir şey yapmaz**. Kaldırma işi §3.5-T7'ye
yazıldı; sürüm 1 bunu geçmiş zamanla (*"eziyordu"*) yazıp hiçbir listeye koymamıştı.

### 3.2 · Kopyalanıp eklenecek CSS

```css
/* ══ A · MEVCUT İKİ SEÇİCİ DEĞİŞİR — css:427 ve css:429 YERİNE ═══════════════
 * `:hover` devre dışı bir <button>'da da eşleşiyor, ve aşağıdaki
 * `.ds-btn:disabled` bu iki kuralla AYNI özgüllükte (0-3-0). Koruma olmadan
 * doğruluk kural sırasına kalır — katmanın kendi yazılı ilkesi bunu yasaklıyor
 * (css:160: "doğruluğu kural SIRASINA bağlayan örtük bir bağımlılık olurdu").
 * Deponun kendi kalıbı: TenderCrm.vue:900 `.crm-dw-del:hover:not(:disabled)`.
 * Değerler DEĞİŞMİYOR — yalnız koruma ekleniyor.
 * ------------------------------------------------------------------------- */
.stbl-ds .ds-btn:hover:not(:disabled):not([aria-disabled="true"])          { background: #f4f6f9; }
.stbl-ds .ds-btn--primary:hover:not(:disabled):not([aria-disabled="true"]) { background: #1b5ca8; }
/* ↺ `[aria-disabled]` sürüm 1'de KORUMASIZDI: blok B iki seçici yazıyor
 * (`:disabled` VE `[aria-disabled="true"]`), koruma yalnız birine konmuştu.
 * `:not(:disabled)` bir aria-disabled düğmeyi dışlamaz — o gerçekten
 * `:disabled` değildir. Bugün kullanım 0 (ölçüldü), yani gizli bir kusurdu;
 * ama sözlüğü bu belge yazdı, kusuru da bu belge kapatır. */

/* ══ B · DEVRE DIŞI EKSENİ · kurul ACCEPTANCE #8 ════════ ekleme yeri: css:430 sonrası
 * Ölçüldü: katmanda `disabled` İKİ kez geçiyor, ikisi de köprüde (css:930-931,
 * .form-control/.form-select). `.ds-btn` arka planını (#fff) ve rengini
 * (var(--ds-tx)) AÇIKÇA yazdığı için tarayıcının kendi grileştirmesi de
 * devreye giremez: `.ds-btn--primary[disabled]` bugün etkin hâliyle piksel
 * piksel aynı. Bugünkü `btn btn-primary`'de Tabler'ın opaklığı hayattaydı —
 * yani göç bunu kapatmazsa GERİLEME getirir.
 *
 * Katmanın kendi kuralı (css:83-84): renk tek başına bilgi taşımaz.
 *
 * ↺ SÜRÜM 1 "ÜÇ KOD, ÜÇÜ DE YAZILIYOR" DİYORDU. ÖLÇÜLDÜ, İKİSİ TAŞIYOR:
 *   RENK  (taşıyıcı)      → metin --ds-tx3'e iner: 14.9:1 → 2.71:1, büyük bir
 *                           parlaklık sıçraması. --primary'de mavi dolgu KALKAR
 *                           (gerçek bir sıçrama). Dolgunun kaybı bu sistemde
 *                           anlamlıdır: css:80 `--ds-ink: sidebar / dolu alan`;
 *                           ds-fill, ds-seg[aria-pressed], ds-step[aria-current]
 *                           hep dolguyla konuşuyor.
 *   ETİKET (taşıyıcı)     → SEBEP yazılır: yanında `.ds-field-hint`, veya düğmede
 *                           `:title` / `aria-describedby`. Ölçüldü: 12 devre dışı
 *                           ds-btn'in 9'unda bugün YOK (gerekçeli 3, sürüm 1 "4"
 *                           diyordu — PartyTransactions:325'in :title'ı koşulsuz
 *                           bir açıklama). K7 bunu zorunlu kılıyor.
 *                           Canlı emsal: SourcingWorkspace.vue:995-1000 (ti-lock),
 *                           QuotationEntryDrawer.vue:332 (:title).
 *   BİÇİM (DESTEKLEYİCİ)  → kenar KESİKLİ. Sürüm 1 bunu `--ds-ln` ile yazıyordu:
 *                           ÖLÇÜLDÜ, kendi dolgusuna karşı 1.19:1 — görünmeyen bir
 *                           çizginin kesikliliği bir kod DEĞİLDİR. Kenar --ds-tx3'e
 *                           taşındı: 2.71:1, etkin kenarın (--ds-ln2, 1.52:1)
 *                           1.78 katı. HÂLÂ 1.4.11'in 3:1'ini GEÇMİYOR ve bu
 *                           bilerek yazılı — bu kod DESTEKLEYİCİDİR, taşıyıcı
 *                           değil. Kurul ACCEPTANCE #8 "en az ikisi" istiyor;
 *                           RENK + ETİKET onu karşılıyor. 3:1'i geçen tek aday
 *                           --ds-tx2 (4.55:1) REDDEDİLDİ: devre dışı bir düğmenin
 *                           kenarını etkin düğmeninkinden üç kat koyu yapardı,
 *                           yani "devre dışı geri çekilir" ilkesinin tersi. (D9)
 * ------------------------------------------------------------------------- */
.stbl-ds .ds-btn:disabled,
.stbl-ds .ds-btn[aria-disabled="true"] {
  background: var(--ds-bg); color: var(--ds-tx3);
  border-color: var(--ds-tx3); border-style: dashed;
  cursor: not-allowed;
}
/* Köprüdeki .form-control:disabled'ın (css:930-931) AYNASI — kesikli kenar
 * eklenmiyor: bir girdi zaten kenarını taşıyor, ve iki bildirim köprüyle
 * birebir aynı kalırsa iki katman aynı satırda yan yana ayırt edilemez. */
.stbl-ds .ds-input:disabled { background: var(--ds-bg); color: var(--ds-tx3); }

/* ══ C · KONTROL BOYUTU ═════════════════════════════════ ekleme yeri: css:430 sonrası
 * 34px köprünün .btn-sm/.btn-icon uzlaşısı (css:956, 961) — iki katman aynı
 * satırda yan yana durursa yükseklikleri tutsun diye. 40px `.ds-btn`'in kendi
 * min-height'ı (css:424). `gap: 5px` icat DEĞİL, SAYILDI: beş yerel yeniden
 * icadın üçü aynı değere varmış (PartyTransactions.vue:733, PartyList.vue:399,
 * PartyCenter.vue:1314). `.ds-btn`'in 7px'i 40px'lik düğme için.
 * İki ayrı ikon kuralı, çünkü tek kural min-height:40px'i yürürlükte bırakıp
 * 34×40 DİKDÖRTGEN üretiyordu.
 * ------------------------------------------------------------------------- */
.stbl-ds .ds-btn[data-size="sm"]                { min-height: 34px; padding: 6px 12px; font-size: 12.5px; gap: 5px; }
.stbl-ds .ds-btn[data-icon="1"]                 { width: 40px; padding: 6px; gap: 0; justify-content: center; }
.stbl-ds .ds-btn[data-size="sm"][data-icon="1"] { width: 34px; }

/* ══ D · GERİ ALINAMAZ AKSİYON ══════════════════════════ ekleme yeri: css:430 sonrası
 * TenderCrm.vue:895-901'deki yerel `.crm-dw-del`'in genelleştirilmiş hâli;
 * o iki bildirim oradan SİLİNİR. Ağırlık RENKTEN değil KENARDAN ve BÖLGEDEN
 * gelir: dolgu --ds-acc'a ayrılmış (tek primary kuralı), ve kırmızı dolgu bir
 * onayı "hata" gibi gösterirdi. Üçüncü kod için ayrı kural YOK — düğmenin
 * içindeki `.ds-sev` [data-sev] atası üzerinden zaten renklenip kareleniyor
 * (css:307-314).
 *
 * ↺ D8 — SÜRÜM 1'İN EN AĞIR KUSURU BURADAYDI. Bu dört kural (0-3-0) blok B ile
 * (0-3-0) AYNI özgüllükteydi ve ondan SONRA iniyordu → silahlanmamış
 * "Approve decision" (varsayılan hâli DEVRE DIŞI, §5.4 parça 4) kırmızı metin +
 * kırmızı kesikli kenar çiziyordu: etkin hâlinden DAHA alarmlı. Yani sistemin
 * en görünür devre dışı düğmesi, deltanın devre dışı eksenini geçemiyordu.
 * Belge tam bu kaskad kusuru için blok A'yı yazıp, aynı korumaya muhtaç dört
 * kuralı korumasız bırakmıştı. `:not()` argümanı özgüllüğe sayıldığı için
 * korunmuş kurallar 0-5-0 olur ve blok B'yi (0-3-0) sırasından bağımsız yener.
 * ------------------------------------------------------------------------- */
.stbl-ds .ds-btn--commit:not(:disabled):not([aria-disabled="true"])                   { border-width: 2px; border-color: var(--ds-ink); color: var(--ds-tx); }
.stbl-ds .ds-btn--commit[data-sev="crit"]:not(:disabled):not([aria-disabled="true"])  { border-color: var(--ds-crit);  color: var(--ds-crit-tx); }
.stbl-ds .ds-btn--commit[data-sev="today"]:not(:disabled):not([aria-disabled="true"]) { border-color: var(--ds-today); color: var(--ds-today-tx); }
/* Kenar KALINLIĞI devre dışıyken de korunur — 2px commit'in kimliği, ve blok B
 * border-width yazmıyor. Yani silahlanmamış commit düğmesi: 2px KESİKLİ gri
 * kenar + gri metin. Etkin hâlinden hem sessiz hem hâlâ "ağır". */
.stbl-ds .ds-btn--commit:disabled,
.stbl-ds .ds-btn--commit[aria-disabled="true"] { border-width: 2px; }
.stbl-ds .ds-btn--commit[data-armed="1"]:hover:not(:disabled) { background: var(--ds-acc-tint); }

/* ══ E · COMMIT BÖLGESİ ═════════════════════════════════ ekleme yeri: css:576 sonrası
 * Yeni kutu değil: `.ds-form-section`'ın (css:568) varyantı. Commit bloğu bir
 * form bölümüdür — içinde bir silahlama kutusu ve bir sonuç özeti var.
 * ------------------------------------------------------------------------- */
.stbl-ds .ds-form-section[data-commit="1"] { border: 2px solid var(--ds-ink); }
.stbl-ds .ds-form-section[data-commit="1"] .ds-form-section-head { background: var(--ds-acc-tint); }

/* ══ F · BOŞ HÂLİN İKİNCİ DÜZEYİ ve FORM HATA ÖZETİ ═════ ekleme yeri: css:445 sonrası
 * `.ds-empty` 42px dikey dolgu (css:444); `.ds-col` 268px (css:370) ve kart
 * 13px dolgu (css:378) — kulvarda karttan uzun bir boşluk kutusu çıkıyor.
 * ↺ SÜRÜM 1 "İKİ bağımsız dosya bu değeri zaten ezmiş" diyordu; ÖLÇÜLDÜ, BİR:
 * PartyTransactions.vue (`ds-empty pc-empty`, :340 ve :584). TenderCrm.vue:789
 * `class="crm-col-empty ds-mono"` taşıyor — `ds-empty` YOK, yani bir ezme değil.
 * Karar ayakta (268px kulvarda 42+42px dolgu ölçülü bir kusur), ama gerekçe
 * "iki bağımsız emsal" değil, TEK emsal + kulvar geometrisinin kendisi.
 *
 * ↺ [data-tone="crit"] — SÜRÜM 1 BUNU YALNIZ RENKLE YAZIYORDU. Kullanıcı için
 * boş kutu ile hata kutusu arasındaki tek fark metin rengi (gri → koyu kırmızı)
 * ve hizalamaydı. Brief §5.2: "Yalnız renkle ayırt edilen HER durum blocker'dır."
 * `role="alert"` ekran okuyucuyu kurtarır, GÖZÜ kurtarmaz. Katmanın kendi hata
 * dili aynı dosyada tanımlı ve bu belge onu §6.5'te "sıfır yeni CSS" diye
 * övüyordu: css:1013 `.alert { border: 1px solid; border-left-width: 3px }`.
 * Aynı 3px sol çizgi buraya da yazılır — bir bildirim, ikinci kod. (İ7)
 * ------------------------------------------------------------------------- */
.stbl-ds .ds-empty[data-size="sm"]   { padding: 16px var(--ds-pad); font-size: 12.5px; }
.stbl-ds .ds-empty[data-tone="crit"] { color: var(--ds-crit-tx); text-align: left;
                                       border-left: 3px solid var(--ds-crit); }

/* ══ G · TABLO DIŞI ve ALAN İÇİ YÜKLEME ═════════════════ ekleme yeri: css:449 sonrası
 * `SkeletonRows`'un kökü <tbody> (SkeletonRows.vue:10) → <table> dışında
 * ÖKSÜZ kalıyor. Ölçüldü: tender'ın 16 kullanımının 8'i öksüz, 8'i iç içe,
 * 0'ı doğru. `.ds-skel` (css:446) background/animation/height:13px veriyor;
 * margin, gap, width YOK — art arda konan N çubuk tek bir 13N piksellik blok
 * gibi okunur. Tek canlı tüketicisi bu yüzden kendi yerel sınıfını yazmak
 * zorunda kalmış: PartyCenter.vue:916 `class="ds-skel pc-chart-skel"`.
 * Alan içi: 13px'lik iskelet 44px'lik `.ds-input`'un (css:438) yerine konunca
 * yükleme bitince sayfa alan başına 31px zıplıyor.
 * ------------------------------------------------------------------------- */
.stbl-ds .ds-skel-stack { display: flex; flex-direction: column; gap: 10px; padding: var(--ds-pad); }
.stbl-ds .ds-skel-stack .ds-skel:nth-child(2n) { width: 78%; }
.stbl-ds .ds-skel-stack .ds-skel:nth-child(3n) { width: 61%; }
.stbl-ds .ds-field .ds-skel { height: 44px; }

/* ══ H · TABLO SATIR VURGUSU ════════════════════════════ ekleme yeri: css:403 sonrası
 * Bootstrap'ın .table-success/.table-primary'si `.table` sınıfına bağlı ve
 * `.ds-table`'da ÇALIŞMIYOR (ölçüldü: ds-table `.table` taşımıyor). Değerler
 * `.ds-row--lead`'den (css:327-332).
 * Öznitelik `data-sev`, `data-state` DEĞİL: ikincisi `ds-sla`'da (css:867-875)
 * beş değerle DOLU. Ve [data-sev] ataya konunca satırdaki `.ds-sev` çocukları
 * kendiliğinden renkleniyor (css:307-314) — bedava kazanç.
 * `ok` tonu YAZILMIYOR: `--ds-ok-t` token'ı yok (ölçüldü: 0).
 * `tbody tr:hover` (css:396) ile aynı özgüllükte → ONDAN SONRA gelmeli.
 * :hover ton başına AÇIK yazılıyor; `background: inherit` <tbody>'nin
 * (genelde transparent) zeminini alır ve satırın kendi tonunu geri
 * getirmeyebilir — tarayıcı olmadan doğrulanamaz bir varsayım.
 * Renk TEK BAŞINA bilgi taşımaz: satırdaki `ds-chip[data-tone]` kelimeyi ve
 * şekli taşır; bu kural yalnız gözü satırda tutar.
 * ------------------------------------------------------------------------- */
.stbl-ds .ds-table tbody tr[data-sev="crit"]  { box-shadow: inset 3px 0 0 0 var(--ds-crit);  background: var(--ds-crit-t); }
.stbl-ds .ds-table tbody tr[data-sev="today"] { box-shadow: inset 3px 0 0 0 var(--ds-today); background: var(--ds-today-t); }
.stbl-ds .ds-table tbody tr[data-sev="soon"]  { box-shadow: inset 3px 0 0 0 var(--ds-soon);  background: var(--ds-soon-t); }
/* ↺ `info` satırı ZEMİN ALMAZ. Ölçüldü: --ds-soon-t (#eef2f7) ile --ds-info-t
 * (#eef0f3) arasındaki kontrast 1.02:1 — dört ton zemini görsel olarak ÜÇ.
 * Ayrımı taşıyan şey sol çubuğun rengi (#8b95a5 ↔ #206bc4), zemin değil; o
 * yüzden yalan söyleyen bildirimi yazmıyoruz. */
.stbl-ds .ds-table tbody tr[data-sev="info"]  { box-shadow: inset 3px 0 0 0 var(--ds-info); }
.stbl-ds .ds-table tbody tr[data-sev="crit"]:hover  { background: var(--ds-crit-t); }
.stbl-ds .ds-table tbody tr[data-sev="today"]:hover { background: var(--ds-today-t); }
.stbl-ds .ds-table tbody tr[data-sev="soon"]:hover  { background: var(--ds-soon-t); }

/* ══ I · KANBAN KULVAR BAŞLIĞI · ACİLİYET ÇUBUĞU ════════ ekleme yeri: css:377 sonrası
 * `.ds-col-head` üst kenarı sabit gri (css:373, `border-top: 3px solid
 * var(--ds-ln2)`); TenderCrm.vue:**454** (455 DEĞİL — 455 `ds-col-n` span'i) onu
 * satır-içi :style ile eziyor. ↺ SÜRÜM 1 ikinci bir emsal sayıyordu
 * (DeclarantQueue.vue:210) — ÖLÇÜLDÜ, o bir Bootstrap `card-header`, dosyada
 * `ds-col-head` HİÇ YOK ve dosya zaten sıfır-`ds-*` on yediden biri. Emsal BİR.
 *
 * ↺ Değerler `.ds-kpi[data-sev]`den (css:250-257). SÜRÜM 1 "BİREBİR" diyordu ve
 * BEŞ kural yazıyordu; ölçüldü, `.ds-kpi[data-sev]` DÖRT değer taşıyor:
 * crit, today, soon, ok. `info` YOK. Beşinci kural kopya değil İCATtı, ve
 * ADR-303'ün ispat yükünü karşılamıyordu → SİLİNDİ. Bir kulvar başlığı
 * "bilgilendirme" aciliyeti taşımaz; taşıması gerekirse gerekçesi ekran
 * şartnamesinde yazılır.
 *
 * Bu ACİLİYET taşır (bu aşamada ne kadar acil iş var), DURUM değil;
 * kaydın durumu StatusBadge + STATUS_MAP'ten gelir. İkisi farklı nesne.
 * UYARI: tek canlı tüketici satır-içi `:style` taşıdığı için bu blok, o stil
 * kaldırılana kadar (§3.5-T7) HİÇBİR ŞEY YAPMAZ.
 * ------------------------------------------------------------------------- */
.stbl-ds .ds-col-head[data-sev="crit"]  { border-top-color: var(--ds-crit); }
.stbl-ds .ds-col-head[data-sev="today"] { border-top-color: var(--ds-today); }
.stbl-ds .ds-col-head[data-sev="soon"]  { border-top-color: var(--ds-soon); }
.stbl-ds .ds-col-head[data-sev="ok"]    { border-top-color: var(--ds-ok); }

/* ══ J · KÖPRÜ · ONAY KUTUSU ve GEÇERSİZLİK ═════════════ ekleme yeri: css:944 sonrası
 * Kare-köşe sıfırlaması (css:136-138) `.form-check-input`'u LİSTELEMİYOR →
 * --ds-radius:0 geometrisi içindeki tek yuvarlak kontrol o kalıyor. Mekanizma
 * .form-control/.badge/.alert ile AYNI (css:894-908): bileşene dokunulmuyor,
 * yalnız .stbl-ds altında yeniden giydiriliyor. Yeni sınıf adı: 0.
 * `form-switch` YENİ İŞARETLEMEDE KULLANILMAZ — switch "anında etkili ayar" der;
 * politika istisnası formla gönderilen bir alandır. Ayrıca border-radius: 2rem
 * --ds-radius: 0 ile doğrudan çelişir.
 *
 * ↺ D11 — SÜRÜM 1 SEÇİCİYİ ÇIPLAK YAZIYORDU ve iki kusuru vardı:
 *  (1) Tender'da 3 CANLI `form-switch` var (SourcingWorkspace:928,
 *      TenderDocuments:70, PoControlBoard:708 — sürüm 1 katmanı ölçüp "0"
 *      demişti). `border-radius: 0` üçünü de "kayan kare"ye çevirirdi:
 *      tasarlanmamış bir kontrol, ve göç maddesi hiçbir listede yoktu.
 *      Bir kontrolü yasaklayıp aynı anda kimse taşımadan bozmak kabul edilemez.
 *  (2) Bootstrap'ın `.form-switch .form-check-input { border-radius: 2em }`
 *      özgüllüğü (0-2-0) ile çıplak seçicininki (0-2-0) BERABERE; doğruluk
 *      yükleme sırasına kalıyordu — blok A'da alıntılanan css:160 ilkesinin
 *      tam ihlali. Katmanın kendi köşe sıfırlaması bu yüzden `!important`
 *      kullanıyor (css:138).
 * Çözüm ikisini birden kapatıyor: switch seçiciden AÇIKÇA dışlanıyor, ve
 * yarıçap sıfırlaması katmanın kendi !important'lı listesine ekleniyor.
 * Üç switch'in `form-check`'e göçü B-16.
 *
 * aria-invalid köprüsü: `.ds-input[aria-invalid]` VAR (css:591) ama
 * MoneyInput (inputClass = "form-control text-end font-monospace", :157-161) ve
 * DateInput (textClass = "form-control", :92-96) `form-control` üretiyor ve
 * onlara `ds-input` eklenemiyor. Köprüde `.is-invalid` kuralı da 0 (ölçüldü).
 * ------------------------------------------------------------------------- */
/* Yarıçap: katmanın mevcut kare-köşe listesine (css:136-138, !important'lı)
 * `.form-check:not(.form-switch) .form-check-input` eklenir. Ayrı bir kural
 * değil, mevcut seçici listesine bir üye. */
.stbl-ds .form-check:not(.form-switch) .form-check-input { border-color: var(--ds-ln2); box-shadow: none; }
.stbl-ds .form-check-input:checked { background-color: var(--ds-acc); border-color: var(--ds-acc); }
.stbl-ds .form-check-input:focus   { border-color: var(--ds-acc); box-shadow: none;
                                     outline: 2px solid var(--ds-acc); outline-offset: 1px; }
.stbl-ds .form-control[aria-invalid="true"],
.stbl-ds .form-select[aria-invalid="true"]  { border-color: var(--ds-crit); }

/* ══ L · METİN TOKEN'I OLMAYAN İKİ SEVERITY TONU ════════ ekleme yeri: css:79 ve css:417
 * ↺ Bu blok sürüm 1'de YOKTU ve brief §5.2'nin "pazarlık dışı" ikinci kısıtının
 * ölçülmüş ihlaliydi: "metin rengi ile dolgu/kenar rengi AYRI token'lardır…
 * parlak severity rengini gövde metnine uygulama."
 * Ölçüldü: `--ds-*-tx` ailesinin TAMAMI iki üye — `--ds-crit-tx`, `--ds-today-tx`.
 * `ok` ve `soon` metinlerinde DOLGU token'ı kullanılıyor:
 *     ds-chip[data-tone="ok"]   color: var(--ds-ok)   / #e8f7ea  →  2.47:1  ✘
 *     ds-sev[data-sev="info"]   color: var(--ds-info) / beyaz    →  3.03:1  ✘
 *     ds-chip[data-tone="soon"] color: var(--ds-soon) / #eef2f7  →  4.72:1  ✔ kontrast
 * İlk ikisi 10–10.5px metin için 4.5:1 eşiğinin ALTINDA. Ve bu kusur sürüm 1'in
 * kendi işine yansıyordu: §5.5(a) bugün `badge bg-green` olan "Cheapest
 * Delivered"ı ds-chip[data-tone="ok"] yapıyordu — yani göç, uyumlu bir Tabler
 * rozetini alıp 2.47:1'lik bir çipe taşıyordu.
 * `--ds-soon-tx` YAZILMIYOR (D10): kontrastı geçiyor, yalnız token ayrımı
 * kuralını çiğniyor; görsel değişiklik üretmeyen bir yeniden adlandırma bu
 * deltanın işi değil → B-18.
 * Yayılma yarıçapı ölçüldü: ds-chip[data-tone="ok"] 3 canlı site
 * (TenderCrm:691, Suppliers:646, Suppliers:702), ds-sev 7 dosya. Değişiklik
 * GÖRÜNÜRDÜR ve istenen etkidir.
 * ------------------------------------------------------------------------- */
/* token tanımları — .stbl-ds bloğuna, --ds-ok'un yanına */
/*   --ds-ok-tx:   #1c7430;   ← #e8f7ea üstünde 5.27:1 (ölçüldü)              */
/*   --ds-info-tx: #5b6675;   ← beyaz üstünde 5.83:1 (ölçüldü)                */
.stbl-ds .ds-chip[data-tone="ok"]      { color: var(--ds-ok-tx); }   /* border/background DEĞİŞMİYOR */
.stbl-ds [data-sev="info"] .ds-sev span { color: var(--ds-info-tx); } /* noktalı kare --ds-info kalıyor */

/* ══ K · MEVCUT ÜÇ KURALA BİRER BİLDİRİM ════════════════════════════════════
 * Üçünün de yayılma yarıçapı ölçüldü; üçü de sıfır regresyon.
 * ------------------------------------------------------------------------- */

/* css:582 — `.ds-field`'in TEK özelliği `min-width: 0` idi; `display` yok.
 * Bir <label> varsayılan `inline` olduğu için ds-field normal akışta
 * ÇALIŞMIYOR. Yayılma ölçüldü: 3 site / 2 dosya — Login.vue:176,198 zaten
 * <div> (blok), TenderCrm.vue:390 bir `ds-actions` flex item'ı (flex item'da
 * display:block düzeni değiştirmez). Bir kural yerine kuralı GEREKSİZ kılan
 * bir bildirim (form §2.1'in vaat edip §6'da teslim etmediği satır). */
.stbl-ds .ds-field { display: block; min-width: 0; }

/* css:657 — `.ds-drawer-head` `justify-content` TAŞIMIYOR (ölçüldü). İki canlı
 * tüketici ona iki farklı yerel cevap vermiş: TenderCrm `.crm-dw-head{flex:1}`,
 * QuotationEntryDrawer çıplak <div>. Üçüncü tüketiciyi (çekmece) aynı deliğe
 * göndermek, aynı hatayı üçüncü kez yazdırmaktır. `tgm-*`'in katmana taşınan
 * TEK değeri budur. */
.stbl-ds .ds-drawer-head { /* mevcut bildirimler + */ justify-content: space-between; }

/* css:569 — `justify-content: space-between` zaten VAR; eksik olan yalnız
 * `flex-wrap`. 3.75× çeviri uzamasında başlık + sağ yuva sıkışıyor.
 * `ds-drawer-foot` (css:671) ve `ds-cut-add` (css:792) aynı sorunu zaten
 * `flex-wrap: wrap` ile çözmüş.
 * ↺ SÜRÜM 1 "Mevcut tüketici 0 → sıfır regresyon" diyordu. ÖLÇÜLDÜ: İKİ
 * tüketici — SalesOrderFormModern.vue:1108 ve :1241. Üstelik belge o dosyanın
 * BİR SATIR AŞAĞISINI (§2 sıra 10) bölüm numarası emsali diye alıntılıyordu,
 * yani satırları okumuş, `-head`'i saymamıştı. Etki: dar ekranda sağ yuva
 * ikinci satıra iner. Şiddet düşük, ama "sıfır regresyon" YANLIŞ. */
.stbl-ds .ds-form-section-head { /* mevcut bildirimler + */ flex-wrap: wrap; }
```

### 3.3 · Deltanın ölçülmüş toplamı

Aşağıdaki sayılar **yazılan CSS'in kendisinden** üretildi (blokları bir dosyaya yazıp
python ile ayrıştırarak), beyandan değil:

| Ölçü | Sürüm 1 | **Sürüm 2** |
|---|---:|---:|
| Ham ayrıştırma: kural bloğu / seçici / bildirim | 39 / 41 / 70 | **40 / 43 / 70** |
| Yeni kural bloğu | 34 | **33** |
| Yeniden yazılan mevcut seçici | 2 | **4** — blok A ×2 (`:not()` koruması) + blok L ×2 (`ds-chip[ok]`, `ds-sev[info] span`) |
| Yeni seçici | 36 | **36** |
| Yeni bloklardaki bildirim | 64 | **62** |
| Mevcut kurala eklenen bildirim | 3 | **5** — `display` · `justify-content` · `flex-wrap` · **`--ds-ok-tx`** · **`--ds-info-tx`** |
| Mevcut kural listesine eklenen seçici | 0 | **1** — kare-köşe listesine (css:136-138) `.form-check:not(.form-switch) .form-check-input` |
| **Dokunulan bildirim toplamı** | 67 | **67** |
| **Yeni `ds-*` sınıf adı** | 2 | **2** — `ds-btn--commit`, `ds-skel-stack` |
| **Yeni `--ds-*` token** | 0 | **2** — `--ds-ok-tx`, `--ds-info-tx` (D10) |
| Yeni öznitelik varyantı | 7 | **7** — `ds-btn[data-size]` · `ds-btn[data-icon]` · `ds-form-section[data-commit]` · `ds-empty[data-size]` · `ds-empty[data-tone="crit"]` · `ds-table tr[data-sev]` · `ds-col-head[data-sev]` |
| Yeni köprü ailesi | 2 | **2** — `.form-check-input` (3 kural) · `[aria-invalid="true"]` (1 kural) |
| **`ds-*` envanteri** | 149 → 151 | **149 → 151** |
| **`--ds-*` token sayısı** | 28 | **28 → 30** |
| Kullanılan `--ds-*` token | 20 / tanımsız 0 | **20 / tanımsız 0** — ikisi (`--ds-ok-tx`, `--ds-info-tx`) **bu delta tarafından tanımlanıyor**, yani blok L'nin token satırları atlanırsa tanımsız **2** olur |
| `.stbl-ds` dışına kaçan seçici | 0 | **0** (yeniden ayrıştırıldı) |

**↺ Kapsam kontrolünün doğru çalıştırma biçimi.** Sürüm 1 bunu
`test_design_layer_contract.py::test_every_rule_lives_under_the_stbl_ds_wrapper` diye
yazıyordu ve **bu node id çalışmaz**: test bir `unittest.TestCase` **metodu**
(`TestScopeIsolation`, `:64-65`), ve `make test` süiti `python3 -m unittest` ile koşuyor
(`Makefile:181`), pytest node id sözdizimi hiç geçerli değil. Doğrusu:

```
python3 -m unittest stabler.tests.test_design_layer_contract.TestScopeIsolation
```

> **Sayımı yeniden üretmek isteyen için:** ham ayrıştırma "mevcut kurala eklenen bildirim"i
> 4 gösterir, 5 değil — çünkü blok L'nin iki token satırı **yorum içinde** yazıldı
> (mevcut `.stbl-ds` bloğuna girecekleri için), ve `.ds-field` tam hâliyle yazıldığı
> hâlde `min-width: 0` **zaten vardı** (css:582), yeni olan tek bildirim `display`.

### 3.4 · Önerilip **yazılmayan** altı ad, ve ret gerekçesi

| Ad | Öneren | Ret gerekçesi (ölçülmüş) |
|---|---|---|
| `ds-file-list` · `ds-file-chip` · `ds-file-name` | `cekmece` §3.3 | ADR-303'ün ispat yükü karşılanmadı: gerekçe *"`ds-table` şunu yapamıyor"* olmalıydı, `ds-chip` üzerinden kuruldu. `ds-table` + `ds-cut-del` + `FileSlot` bileşimi hiç denenmedi. `FileSlot` zaten import edilmiş (`TenderMasterDrawer.vue:29`), `ds-cut-del`/`ds-cut-add` zaten yazılmış (css:785-795) ve **0 canlı tüketicisi** var |
| `ds-table-wrap` | `bosluk` §2.3 | `table-responsive` **148 dosyada** benimsenmiş; katmanda hiç kural gerektirmiyor. ADR-303 *"sorun benimseme"* diyor. `bosluk`'un *"dört ekran kendi sarmalayıcısını icat etti"* iddiası ölçüldü ve **abartılı**: yalnız **bir** yerel icat var (`DirectorBoard.vue:327 .board-scroll`) |
| `ds-field--check` | `cekmece` §4:715 | Katmanda **0**, depoda **0**, `cekmece`'nin **kendi delta bölümünde 0** — beyan edilmeden bir iskelete girmiş 16. sınıf. Uygulayıcı bunu yazarsa stilsiz bir onay kutusu alır. Yerine köprünün `form-check` ailesi |
| `ds-blockers` | `UZLASTIRMA-delta.md` Ç5 | Yuva zaten iki parçalı ve dolu: tekil sebep → `ds-field-hint` (css:589), form-düzeyi liste → `ds-empty[data-tone="crit"]`. Üçüncü ad ADR-303'ü karşılamıyor (§0.3-D2) |

### 3.5 · Ayrı temizlik commit'i — tasarım kararı değil, düzeltme

| # | Ne | Nerede | Ölçüm |
|---|---|---|---|
| T1 | `var(--ds-font-body)` → `var(--ds-font)` | css:921, 951 | tanım **0**, kullanım **2**. Bugün kazara mirasa düşüyor; başlık yazı tipi taşıyan bir ata altındaki düğme Display ile çıkar |
| T2 | *"Tablo dar ekranda kendi içinde yatay kayar"* yorumu düzeltilir | css:397-398 | `.ds-table`'da `overflow-x` **yok**; `grep -n overflow` → 212, 369, 653, 668, 692, 836, hiçbiri `.ds-table` değil. Yorum olmayan bir davranışı vaat ediyor |
| T3 | `.btn-primary:hover` `#1b5aa6` → `#1b5ca8` | css:960 | `.ds-btn--primary:hover` **#1b5ca8** (css:429). Göç hover rengini sessizce kaydırıyor. Katmanın kendi kuralı kazanır |
| T4 | `ds-label` *"ÇEVRİLMEZ — kaynak kimliği"* yorumu güncellenir | css:178-179 | Ç30 bölüm başlığını `ds-label` içine koyuyor ve o başlık **çevrilir**; yorum eskimiş |
| T5 | `.crm-dw-del` iki bildirimi silinir | `TenderCrm.vue:895-901` | `ds-btn--commit`'in genelleştirdiği yerel icat |
| T6 | `.board-scroll` → `table-responsive` | `DirectorBoard.vue:327` | tek yerel kaydırma icadı |
| **T7** ← YENİ | `:style="{ borderTopColor: l.color }"` **kaldırılır**, yerine `:data-sev` | `TenderCrm.vue:454` | Satır-içi stil her seçiciyi yener → **blok I bu satır kalkmadan hiçbir şey yapmaz.** Sürüm 1 ezmeyi geçmiş zamanla anlatıp kaldırma işini hiçbir listeye koymamıştı |
| **T8** ← YENİ | `<tr … role="button">` kaldırılır, satıra gerçek bir `<button>` konur | `TenderDocuments.vue:257` | §1.3'ün kendi yasağının tek canlı ihlali, ve §5.5(d)'de yeniden tasarlanan ekranda |
| **T9** ← YENİ | `test_design_layer_contract` node id'si düzeltilir (`unittest` biçimine) | bu belge, K14 | Sürüm 1'in yazdığı pytest node id'si çalışmıyor (§3.3) |

---

## 4 · FORM GRAMERİ — **12 madde** (11 + onay kutusu)

`form` şartnamesi 11 madde yazdı; Ç15 onay kutusunu 12. madde olarak ekledi (gramerde
delik olduğu ölçüldü: `ds-field--check`, `form-check`, `ds-check`, `ds-switch` — dördü
de katmanda **0**).

### 4.1 · Üç çapraz mekanizma

**(a) Etiket-kontrol bağı — tek varsayılan, iki adlandırılmış istisna.**

> **Varsayılan: sarmalayan `<label class="ds-field">`.** Katman iki kalıbı da destekliyor
> (css:583-587: `.ds-field > label, .ds-field-label`), ama `for=`/`id=` kalıbı iki
> kontrolde **var olmayan bir id'yi işaret eder** — sessiz bir erişilebilirlik hatası.

Ölçüldü, kontrol kontrol:

| Kontrol | `id` dışarıdan ulaşıyor mu | Kanıt |
|---|---|---|
| `MoneyInput` | **Evet** | `id` prop'u `:26`, `:id="id \|\| undefined"` |
| `DateInput` | **Evet** | `id` prop'u `:28`, `:id="id \|\| undefined"` |
| `Select` | **Evet** | `defineOptions({ inheritAttrs: false })` + `v-bind="$attrs"` tetikleyici `<button role="combobox">` üzerinde (`:321-330`) |
| çıplak `<input>/<select>/<textarea>` | Evet | — |
| `Typeahead` | **Hayır** | kök `<div class="typeahead">` (`:254`), `inheritAttrs` beyanı **0** → `id` `<div>`'e düşer |
| `MultiSelectPicker` | **Hayır** | kök `<div class="ms-picker">` (`:119`), `inheritAttrs` beyanı **0** |

- **İstisna 1 — alan birden çok kontrol taşıyorsa** (jeton listesi, onay kutusu grubu):
  `<div class="ds-field" role="group" aria-labelledby="…">` + `<span id="…" class="ds-field-label">`.
- **İstisna 2 — kontrol `id` kabul ediyorsa:** sarmalamaya **ek olarak** `for`/`id` de
  yazılır; `aria-describedby`'nin hedefi ondan doğar.

**(b) Hata durum makinesi — beş kural.**

1. Alan hatası **yalnız** o alanın altında: `ds-field-err` + kontrolde `aria-invalid="true"`
   + `aria-describedby` hata elemanının `id`'sini işaret eder.
2. Form-düzeyi özet gönderimde çizilir, yazarken değil:
   `<div class="ds-empty" data-tone="crit" role="alert" tabindex="-1">` — ve **odak oraya
   taşınır**. Başlığı bir **yönerge**dir, bir olgu değil (§4.3-i18n).
3. Özetin her satırı ilgili alana **tıklanabilir** bağlantıdır.
4. Alan hatası temizlenince `aria-invalid` **kalkar** — bayat `true` bırakılmaz.
5. **Devre dışı bir gönder düğmesinin sebebi görünür olur** (§5.6). Ölçülmüş kalıp:
   `QuotationEntryDrawer.vue:315-317` (`<ul class="qed-problems" role="alert">`) +
   `:174` (`save()` engel varken sessizce döner — devre dışılık gerçek bir kapı) +
   `:404-410` (stilin kendi yorumu bu kuralı yazıyor).

**(c) `id` sözleşmesi.** `<bölüm-kısaltması>-<alan-adı>` — örn. `award-winner`,
`intake-deadline`. Hata elemanının id'si `<aynı>-err`, ipucununki `<aynı>-hint`.
Bir sayfada iki kez mount edilen bileşen (çekmece) kendi kök `id` önekini alır.

### 4.2 · On iki madde

| # | Madde | Ne kullanılır | Tanım | Kritik kural |
|---|---|---|---|---|
| 1 | **Bölüm başlığı** | `ds-form-section` + `-head` + `ds-form-body` + `<span class="ds-label">A · …</span>` | css:568, 569, 573, 181 | Numaralandırma **rozet değil metin öneki** (Ç30). Bir formda **ikiden fazla** alan varsa bölüm açılır. `-head`'e `flex-wrap: wrap` eklenir |
| 2 | **Alan** | `ds-form-grid[data-cols="2"]` > `<label class="ds-field">` > `ds-field-label` + kontrol | css:574-575, 582-587 | **`data-cols="3"` tender'da yasak** (Ç11): 641–992px arasında üç kolon ~220px eder; 3.75× uzayan bir etiket 2-3 satıra sarar ve kolonların kontrolleri **farklı y'de** hizalanır. Katmanda 992px'te ara kırılma **yok** (media yalnız 640px'te, css:702-703) |
| 3 | **Zorunluluk işareti** | `<span class="ds-field-req" aria-hidden="true">*</span>` **+ kontrolde `aria-required="true"`** (veya native `required`) | css:588 | `.ds-field-req` **yalnız renk** taşıyor — yıldız tek kod. İki parça da zorunlu (Ç14) |
| 4 | **İpucu** | `ds-field-hint` | css:589 | Alanın hangi **kuralı** taşıdığını söyler ("limit 400 000 000 · vade 30 gün"). **Asla boş hâl taşımaz** (Ç7). Devre dışı bir düğmenin sebebi de buraya yazılır (§5.6) |
| 5 | **Hata** | `ds-field-err` + `aria-invalid` + `aria-describedby`; form özeti `ds-empty[data-tone="crit"]` | css:590, 591 + **YENİ** | §4.1(b)'nin beş kuralı. Bölge yükleme hatası **buraya girmez** — o `alert alert-danger` (§6.4). **↺ KAPSAM SINIRI:** `aria-invalid`'in görsel karşılığı `MoneyInput` (para birimi dalı) ve `DateInput`'ta **ULAŞMIYOR** — ikisi de kök `<div>` + `inheritAttrs` beyanı 0, öznitelik sarmalayıcıya düşüyor. Ölçüldü, **§10.9'un cevabını bekliyor.** O ikisinde bugün geçerli olan tek yol `ds-field-err` + `aria-describedby` |
| 6 | **Çok satırlı metin** | `<textarea class="ds-input">` | css:592 (`min-height: 80px; resize: vertical`) | `rows` **yazılmaz** — katman yüksekliği veriyor, `rows` onu ezer |
| 7 | **Para** | `MoneyInput` + `formatMoney` / `moneyFractionDigits(currency)` | `components/MoneyInput.vue` | Manda 3. Ölçüldü: tender'da **10 çıplak `<input type="number">`** var, ikisi `TenderMasterDrawer`'da (`:517`, `:606`). Yüzde alanları §10.4'ün cevabını bekliyor |
| 8 | **Tarih** | `DateInput` + `formatDate` | `components/DateInput.vue` | Manda 4. Ölçüldü: tender'da çıplak `type="date"` **0** — modülün en sağlam yeri |
| 9 | **Tipeahead** | `Typeahead` + **sarmalayan** `<label class="ds-field">` | `components/Typeahead.vue` | `for=` **kullanılmaz** (§4.1a). `Typeahead` yükleme sırasında kendi içinde `spinner-border` çiziyor (`:270`) — o bileşenin içi, dokunulmaz |
| 10 | **Çoklu seçim** | **jeton listesi**: `ds-table` gövdesi + satır sonu `ds-cut-del` + `ds-cut-add` ekleyici şeridi + `Typeahead` | css:389-403, 785-789, 790-795 | Kap `<div class="ds-field" role="group" aria-labelledby>` (İstisna 1) |
| 11 | **Dosya eki** | **aynı jeton listesi** + `FileSlot` (dropzone) | aynı + `components/files/FileSlot.vue` | 10 ve 11 **aynı gramer maddesidir**: "silinebilir şeylerin listesi + bir ekleyici". Ayrı çizmek üçüncü bir lehçe üretirdi. `ds-cut-del` 30px — 34px'lik hedeften küçük, **kabul edilmiş gerileme** (§0.3-D1) |
| 12 | **Onay kutusu** ← YENİ | `<label class="form-check">` + `<input class="form-check-input" type="checkbox">` (köprü, §3.2-J) | **YENİ köprü** | `form-switch` **yasak**. Kare-köşe sıfırlaması (css:136-138) `.form-check-input`'u listelemiyor → `--ds-radius: 0` içindeki tek yuvarlak kontrol o. Silahlama kutusu (§5.4) bu maddeyi kullanır |

### 4.3 · Gramerin 3.75×'e cevabı

Ölçülen en kötü uzama: `RFQs` (4) → uz `Narx so'rovlari` (15) = **3.75×** (kurul §1.4).

| Kural | Nasıl | Ölçülmüş dayanak |
|---|---|---|
| Hiçbir alan, etiket veya düğme **sabit genişlik** almaz | `ds-form-grid` `minmax(0, 1fr)` (css:575) zaten böyle | brief §5.4 |
| Bölüm başlığı sarabilir | `ds-form-section-head`'e `flex-wrap: wrap` (§3.2-K) | `ds-drawer-foot` (css:671) ve `ds-cut-add` (css:792) aynı sorunu zaten böyle çözmüş |
| Üç kolonlu ızgara yasak | §4.2 madde 2 | 641–992px'te ara kırılma yok |
| **`ds-chip` içine uzun metin girmez** | Çip metinleri **tek kelime**: `Winner`, `Lead`, `Cheapest` | `ds-chip` `white-space: nowrap` (css:412) ve kendi yorumu uyarıyor: *"Çip asla sarmaz"*. `bosluk`'un önerdiği `Winning quotation` (18 kr) / `Cheapest delivered` (18 kr) 3.75×'te ~68 karaktere çıkar ve 9 sütunlu tabloda hücreyi taşırır. **Uzun ifade `ds-field-hint` satırına (sarabilen) taşınır** |
| Kısaltma kullanan `ds-sev` etiketleri | `FAIL` / `FINAL` kalır ama izlenir | `.ds-sev span` genişlik sınırı taşımıyor; sistemin alışkanlığı üç harf, bunlar 4-5. Kırılma riski düşük, işaretli |
| Arama yer tutucusu | `⌘K` ile biter (manda 8); kırpılması düzeni bozmaz | `<input>` içinde, `nowrap` kısıtı yok |

**İki dize düzeltmesi (ölçüldü, ikisi de doğru):**
- `t("Save tender")` → **`t("Save Tender")`** — katalogda **tam bu yazımla** var; küçük
  "t" ikinci bir satır açar ve beş dilde ayrıca çevrilir.
- `t("Retry")` → **`t("Try again")`** — `Retry` katalogda **yok**, `Try again` var ve
  beş dilde çevrili. Aynı ekranda iki farklı "yeniden dene" kelimesi olmaz.

### 4.3b · ↺ i18n borcu — sürüm 1 iki dizede sayıp on beşinde susuyordu

Sürüm 1 bu bölümü *"i18n katalog borcunu önlemek için"* diye başlatıyordu; **borcun
kendisi ölçülmemişti.** Ölçtüm — belgenin kendi metninde harfiyen geçen kullanıcı
dizeleri, 7000 girdilik `en.csv`'ye karşı:

```
kontrol edilen aday        31
katalogda VAR              14   (Save Tender, Try again, Winner, Cheapest, Not measurable,
                                 Saving…, Loading…, Supplier, Total, Create purchase order,
                                 Approve decision, Confirm waiver, Re-award this lot,
                                 Save draft decision)
katalogda YOK              15   ← borç
reddedilen yazım            2   (Save tender, Retry — zaten yukarıda düşürüldü)
```

**Katalogda olmayan on beş:**

| # | Dize | Nerede |
|---|---|---|
| 1 | `Lead` | §7 `tr[data-sev]` / çip metni |
| 2 | `Delete tender` | §5.4, §5.5(c) |
| 3 | `no approval stamp` | §6.7 beşinci hâl |
| 4 | `Go to the operations desk` | §6.6 |
| 5 | `Loading the quotation comparison…` | §6.3 Şekil A |
| 6 | `Loading the award decision…` | §6.3 Şekil B |
| 7 | `Fix these to save` | §4.3 metin tablosu |
| 8 | `Enter a rate greater than 0.` | §4.3 metin tablosu |
| 9 | `Write a reason for the exception.` | §4.3 metin tablosu |
| 10 | `Try again — the attached files did not load.` | §4.3 metin tablosu |
| 11 | `Try again — the quotation table did not load.` | §6.5 |
| 12 | `Clear the supplier or status filter, or widen the date range.` | §6.4 |
| 13 | `Raise one to start collecting supplier prices.` | §6.4 |
| 14 | `Bid pricing is the sourcing role's screen. Your work for today is on the operations desk.` | §6.6 |
| 15 | `Approving writes the server-side stamp and closes this lot to further quotations.` | §5.4 parça 2 |

**15 anahtar × 5 katalog (`en/ru/uz/uzc/tr`) = 75 çeviri satırı.** Bu bir Aşama B
kalemidir ve **B-19**'a yazıldı. `CLAUDE.md` dize taşıyan bir değişikliği kapı sayıyor
(`stabler-i18n` skill'i) — yani bu 75 satır **iniş öncesi** borçtur, sonrası değil.

**Ve 3.75× testi bu dizelerde yapılmadı.** Sürüm 1 uzamayı yalnız `RFQs → Narx
so'rovlari` üzerinde ölçtü. Yukarıdaki 14 numaralı dize **89 karakter**; 3.75×'te
~334 karaktere çıkıyor ve bir `alert alert-warning` kutusunda hiç görülmedi (§11).

**Dört hata metni operatör kuralına göre yeniden yazıldı** (manşet = **eylem**, olgu değil):

| Bugün önerilen | Yerine |
|---|---|
| `Could not load attached files` | **`Try again — the attached files did not load.`** |
| `Rate must be greater than 0.` | **`Enter a rate greater than 0.`** |
| `A written reason is required.` | **`Write a reason for the exception.`** |
| `Cannot save` | **`Fix these to save`** |

---

## 5 · AKSİYON HİYERARŞİSİ

### 5.1 · **Bölge** — kapalı liste

Manda 5 (*"görsel bölge başına tek `.btn-primary`"*) bugün hiçbir şeyi engellemiyor,
çünkü "bölge" tanımsız. Tanım:

> **↺ Bölge, aksiyon taşıyan ve kendi kenarı/zemini ile kardeşlerinden ayrılan en DIŞ
> elemandır.** İçindeki aksiyon şeritleri (`-head`, `-foot`) onun **yuvalarıdır**,
> ayrı bölgeler değil.

**Neden "en küçük" değil (D12).** Sürüm 1 *"en küçük"* yazıyordu ve bu, kendi bölge
listesini iç tutarsız yapıyordu: `ds-drawer-foot`'un **kendi kenarı var** (css:669,
`border-top: 1px solid var(--ds-ln)`) ve `ds-form-section`'ın **içinde** — yani "en
küçük" şartına göre bölge B5'ti, B13 değil. Sonuç: aynı DOM düğümü için iki kota
yürürlükteydi (B9 → primary 0, içindeki B5 → primary ≤1), R1/R2 hangisinin
uygulanacağını söylemiyordu, ve **K8 üçüncü bir cevap veriyordu** (`ds-form-section`
başına ≤1). Tek bir bileşen dili üretmesi beklenen turda üç ayrı cevap. Tanım
düzeltildi ve **R9** eklendi (§5.2).

Bölge kökleri **tam olarak** şunlardır. Liste kapalıdır; yeni bir kök ancak bu belge
değiştirilerek eklenir.

| # | Bölge kökü | Nerede | İzinli primary |
|---|---|---|---:|
| B1 | `.ds-page-head .ds-actions` | sayfa başlığı eylem şeridi (`TenderPage.vue:18`) | ≤1 |
| B2 | `.ds-panel-head` / `.card-header` | panel/kart başlığı | ≤1 |
| B3 | `.ds-panel-foot` / `.card-footer` | panel/kart altbilgisi | ≤1 |
| B4 | `.ds-form-section-head` | form bölümü başlığı | ≤1 |
| B5 | `.ds-drawer-foot` | **aksiyon çubuğu** — çekmecede, panelde, `ds-form-section` altında (seçici serbest, css:669) | ≤1 |
| B6 | `.modal-footer` | modal altbilgisi | ≤1 |
| B7 | `EmptyState` `#actions` slotu | boş durum | ≤1 |
| B8 | `ListToolbar` kökü (`primaryLabel` primary üretir) | liste araç çubuğu | ≤1 |
| **B13** | **`.ds-form-section`** ← **bu turda eklendi** | ödül panelinin üç bölümü (§5.5) | ≤1 |
| B9 | `.ds-form-section[data-commit="1"]` | geri alınamaz aksiyon bloğu | **0** |
| B10 | bir `<tr>` | tablo satırı aksiyon hücresi | **0** |
| B11 | `.ds-card` / `.ds-row` | kart / iş satırı | **0** |
| B12 | hata bloğu (`.alert` + yeniden dene) | §6.4 | **0** |

> **↺ B13 neden eklendi — gerekçe düzeltildi.** Sürüm 1 şöyle diyordu: *"Bu eksiklik
> yüzünden ödül paneli **aynı bölgede iki primary üretiyordu**."* **Bu ölçüm yanlıştı,
> ve iki çürütme raporu onu bağımsız olarak çürüttü.** Ödül panelinin tamamında
> (`SourcingWorkspace.vue:780-1010`) bugün **tek** `btn-primary` var:
>
> ```
> :842  btn btn-outline-secondary btn-sm   Create purchase order
> :854  btn btn-link btn-sm text-secondary Re-award this lot
> :972  btn btn-primary                    Save draft decision   ← TEK primary
> :987  btn btn-success                    Approve decision      ← primary DEĞİL
> ```
> Dosyadaki ikinci `btn-primary` (`:455`) teklif tablosunun başlığında, ödül panelinin
> **dışında** — ve belgenin kendi R3'ü bunu doğru yazıyordu (*"455 ve 972 … hepsi
> meşru"*). İki bölüm birbirini yalanlıyordu; ölçüm R3'ü doğruluyor.
>
> **Bugün R1 ihlali YOK. İki primary durumunu bu belgenin kendi tasarımı üretiyor:**
> `Create purchase order`'ı `btn-outline-secondary`'den `ds-btn--primary`'ye
> yükselttiği an (§5.5b bölge 1) bölge 1 ve bölge 2 birer primary taşır. **B13'ün
> meşru gerekçesi budur** — bugünkü bir ihlal değil, tasarımın kendi ürettiği ihtiyaç.
> Kapalı bir listeye var olmayan bir ihlal göstererek 13. maddeyi eklemek, kanıt
> rejiminin ihlaliydi.
>
> **Bugün gerçek olan kusur R5'in ölçtüğüdür:** `Save draft decision` (primary) ile
> `Approve decision` (`btn-success`) aynı `d-flex align-items-center gap-2` içinde
> (`:969`), 8px arayla, ikisi de `btn-sm` taşımadan. R5 doğru, sürüm 1'in §5.5(b)
> ve K8 formülasyonu değildi.

### 5.2 · Bölge kuralları R1–R8

| # | Kural | Ölçülmüş dayanak |
|---|---|---|
| **R1** | Bir bölge **en çok bir** `ds-btn--primary` taşır. "En çok" — sıfır meşru ve sık doğru cevaptır | `DirectorBoard` ve `TenderOverview` bugün 0 primary taşıyor, ikisi de salt-okuma |
| **R2** | **B9, B10, B11, B12 SIFIR primary taşır.** Bir tablo satırı bir bölge değil, bir bölgenin **tekrarıdır** | 20 satırda 20 primary, primary kavramını yok eder |
| **R3** | Modal/çekmece açıkken **arkasındaki bölgeler askıya alınır**. Kural "dosyada tek primary" değil, **"aynı anda ekranda, aynı bölgede tek primary"**dir | `SourcingWorkspace` (455 ve 972), `TenderCrm` (385 ve 722), `TenderDocuments` (49 ve 196) — üçü de dosyada 2 primary taşıyor ve **hepsi meşru** |
| **R4** | **Renk seçim durumu taşımaz.** `:class="cond ? 'btn-primary' : 'btn-outline-secondary'"` **yasak**; karşılığı `ds-seg` + `aria-pressed` | Dört dosya aynı deseni yazmış: `DeclarantQueue.vue:168-183`, `LogistBoard.vue`, `TenderDocumentsPanel.vue:117-118`, `BidPricing.vue:155-156`. `ds-seg`'de primary yoktur: seçili düğme `--ds-ink` alır |
| **R5** | Bir bölgede **primary VE commit birlikte duramaz** | Bugün ihlal: `SourcingWorkspace.vue:969-993`, `Save draft decision` (primary) ile `Approve decision` aynı `d-flex gap-2` içinde, **8px arayla, aynı boyutta** |
| **R6** | Primary, bölgenin **beklenen** aksiyonudur; en görünür olan değil | Karşı örnek: `rfq/RfqDetail.vue` — `Print` (:123) primary, zincirin gerçek olayı `Mark as sent` (:115-121) `btn-outline-secondary`. Tasarım bunu ters çevirir |
| **R7** | Bir aksiyon **iki bölgede birden tekrarlanmaz** — aynı verinin iki görünümü (kart ↔ satır) tekrar sayılmaz | `DeclarantQueue` `Doc Center` (274-281 ve 333-339) meşru |
| **R8** | `ds-actions` **yalnız `.ds-page-head` altında** biçimlenir (seçici `.stbl-ds .ds-page-head .ds-actions`, css:203). Başka yerde `class="ds-actions"` yazmak **hiçbir stil vermez** | Panel/çekmece şeridi için `ds-drawer-foot` (B5) |
| **R9** ← **bu turda eklendi** | **İç içe bölgelerde kota EN DIŞ bölge kökünde toplanır.** Bir `ds-form-section` (B13) içindeki `ds-form-section-head` (B4) ve `ds-drawer-foot` (B5) o bölgenin **iki yuvasıdır**; ikisi **birlikte** en çok bir `ds-btn--primary` taşır. B4 ve B5 **bağımsız bölge** olarak yalnız bir B13'ün dışında sayılır (panel başlığı, çekmecenin kendi altbilgisi). Sayma birimi budur; K8 de bunu ölçer | Ölçülmüş çelişki: `ds-drawer-foot` **kendi kenarını taşıyor** (css:669) ve `ds-form-section`'ın (css:568) **içinde** — sürüm 1'in *"en küçük eleman"* tanımıyla aynı düğüme iki kota çıkıyordu. `-head`'inde 1 + footer'ında 1 primary olan bir bölüm eski kurala göre **B4 ve B5'e uyar, B13'ü ve K8'i ihlal ederdi** ve uygulayıcı hangisine uyacağını okuyamazdı |

### 5.3 · Buton dağarcığı

| Sınıf | Rol | Ne zaman |
|---|---|---|
| `ds-btn` | nötr | **varsayılan.** İkincil, geri alınabilir her aksiyon |
| `ds-btn--primary` | bölgenin beklenen aksiyonu | bölge başına ≤1, ve R6'ya göre seçilir |
| `ds-btn--commit` | **geri alınamaz** aksiyon | §5.4'ün beş parçası eksiksiz kurulduğunda |
| `ds-btn[data-size="sm"]` | küçük kontrol (34px) | satır içi, kart içi, panel başlığı |
| `ds-btn[data-size="sm"][data-icon="1"]` | satır-içi ikon (34px kare) | **`aria-label` zorunlu** |
| `ds-seg` + `aria-pressed` | **seçim durumu, aksiyon değil** | filtre/görünüm anahtarları |

### 5.4 · Geri alınamaz aksiyonların dili — commit grameri

**Hangi aksiyonlar commit'tir** (ölçüldü, üç tane):

| Aksiyon | Nerede | `data-sev` | Neden commit |
|---|---|---|---|
| `Approve decision` | `SourcingWorkspace.vue:980-993` | `crit` | Sunucu onay damgasını yazar, durum tek yönlüdür (Taslak→Onaylı) — brief §2 |
| `Confirm waiver` | `TenderDocuments.vue:228-230` | `today` | Bir belge gereksinimini kalıcı olarak muaf tutar; yazılı gerekçe zorunlu |
| `Delete tender` | `TenderCrm.vue` çekmece footer'ı | `crit` | Kayıt siliniyor |

**Beş zorunlu parça** — beşi de eksiksiz kurulmadan `ds-btn--commit` yazılmaz:

1. **Kendi bölgesi.** `<section class="ds-form-section" data-commit="1">` (B9).
   Bu bölgede `ds-btn--primary` **sayısı sıfırdır** (R5).
2. **Sonuç cümlesi.** Ne olacağını **fiil** ile yazan bir metin — "Bu karar geri
   alınamaz" değil, *"Approving writes the server-side stamp and closes this lot to
   further quotations."* Emsal: `TenderDocuments.vue:212-215` `alert alert-warning`.
3. **Sonuç özeti.** Neyin onaylandığı okunabilir olmalı: `ds-deflist` (css:675) veya
   `ds-fill` (css:345) ile kazanan + tutar + gerekçe.
4. **Silahlama kutusu.** DOM'da **duran** bir `<input type="checkbox" class="form-check-input">`
   (§4.2 madde 12), `v-model` ile bir ref'e bağlı; düğme
   `:disabled="!awardAck || approvingDecision"` ve `data-armed="0|1"`.
   **`useConfirm()` KULLANILMAZ** (Ç2) — iki sebeple: (a) bir handler içindeki modal
   çağrısı deponun tek kanıt yolundan (kaynaktan ifade çıkarıp çalıştırma) **görülemez**;
   (b) `ds-drawer` (z-41) içinden açılan bir Bootstrap `.modal` (z-1040+) z-index
   sorusunu (§10.3) tetikler.
5. **Sebep görünür.** Düğme devre dışıysa nedeni yanında `ds-field-hint` ile yazılı
   (§5.6). Emsal: `SourcingWorkspace.vue:995-1000` `ti-lock` + *"Approval requires
   Director view"*.
6. **↺ Silahlama kutusu komşu onay kutularından ayırt edilir.** ← **bu turda eklendi.**
   Ölçüldü: ödül panelinde **zaten bir `form-check-input` var** —
   `SourcingWorkspace.vue:932`, *"Policy exception required"*, bir **veri alanı**.
   Sürüm 1 silahlama kutusunu aynı sınıfla, aynı görünümle, aynı bölgeye koyuyordu:
   biri bir formun alanı, öteki geri alınamaz bir kararın kilidi, ve ikisi piksel
   piksel aynı. **Ayrım üç yolla kurulur:** (a) silahlama kutusu `data-commit="1"`
   bölgesinin **içinde**, veri alanı **dışında** — bölge sınırı ilk koddur;
   (b) silahlama kutusunun etiketi bir **taahhüt cümlesidir** (*"I have reviewed the
   winner and the amount"*), bir alan adı değil; (c) silahlama kutusu **doğrudan
   düğmenin üstünde**, `ds-drawer-foot`'un hemen öncesinde durur. Bu üçü olmadan
   `ds-btn--commit` yazılmaz.

**Neden `ds-btn--primary` değil:** dolgu (`--ds-acc`) bu sistemde **tek beklenen-aksiyon
kodudur**; onu bir commit'e vermek "beklenen" ile "geri alınamaz"ı aynı görsel ağırlığa
indirir. **Neden kırmızı dolgu değil:** kırmızı dolgu bir onayı **hata** gibi gösterir.
Ağırlık **kenardan** (2px) ve **bölgeden** (kendi çerçeveli kutusu) gelir. Boşluğun
ölçülmüş kanıtı: `TenderCrm.vue:895-901` — modülün `ds-*`'ı en iyi konuşan dosyası
sistemde arayıp bulamayınca kendi kırmızı düğmesini yazmış. **Yerel bir yeniden-icat,
boşluğun kanıtıdır.**

### 5.5 · Gerçek aksiyon kümeleri — beş ekran

#### (a) Sourcing karşılaştırma tablosu (`SourcingWorkspace.vue`)

| Bugün | Sınıf | Bölge | Tasarım | Kural |
|---|---|---|---|---|
| `Request for quotation` 449-454 | `btn-outline-secondary btn-sm` | B2 | `ds-btn[data-size="sm"]` | R1 |
| `Add quotation` 455 | `btn-primary btn-sm` | B2 | **`ds-btn--primary[data-size="sm"]`** — bölgenin beklenen aksiyonu | R1, R6 |
| `Landed cost` 628-635 | `btn-ghost-secondary btn-sm` | B10 | **KALIR** — `ds-btn[data-size="sm"][data-icon="1"]`, `ti-truck-delivery`, `aria-label` | T4 |
| `Edit` 637-642 | `btn-ghost-primary btn-sm` | B10 | **satırdan çıkar** → satır tıklaması çekmeceyi açar | T4 |
| `Submit` 644-649 | `btn-outline-success btn-sm` | B10 | **satırdan çıkar** → `QuotationEntryDrawer.vue:330-337`'de zaten var | T4 |
| `Detach` 651-657 | `btn-ghost-danger btn-sm` | B10 | **satırdan çıkar** → çekmece gövdesinde nötr `ds-btn` (commit **değil**: `Attach to this lot` geri alıyor) | T4 |
| `Attach to this lot` 735-740 | `btn-outline-primary btn-sm` | B10 (2. tablo) | `ds-btn[data-size="sm"]`, primary **değil** | R2 |
| Durum sütunu 625 | `<span class="text-secondary small">{{ r.status }}</span>` — **rozet bile değil, `t()`'den geçmemiş ham sunucu dizesi** | — | `<StatusBadge doctype="Supplier Quotation" …>` | manda 7 |
| `Cheapest Delivered` 592 / `Sticker Leader` 599 / `Winner` 604 | `badge bg-green` / `bg-warning-lt` / `bg-blue` | rozet | `ds-chip[data-tone="ok"/"today"/"soon"]` — **sıralama**, durum değil. **↺ `ok` tonu ancak blok L indikten sonra:** bugünkü `ds-chip[data-tone="ok"]` **2.47:1** ve bu göç, uyumlu bir Tabler rozetini eşiğin yarısına taşırdı. `--ds-ok-tx` (5.27:1) ön koşuldur | G1, D10 |

**Satırda kalan tek aksiyon: `Landed cost`.** Testi: *"aksiyon bu tablonun sayılarını
değiştiriyor mu?"* — `Landed cost` değiştiriyor, üçü değiştirmiyor.
`bosluk`'un `Open`'ı **reddedildi**: satır tıklamasının kopyası.
Ve `bosluk`'un bağlayıcı erişilebilirlik hükmü (*"`ds-table` satırı asla tek erişim yolu
olamaz; her satırda odaklanabilir en az bir gerçek `<button>` bulunur"*) `Landed cost`
ile **karşılanıyor** — iki taraf da yaşıyor.

**`<tr role="button" tabindex="0">` YAZILMAZ** (Ç18). `<tr>`'nin örtük rolü `row`'dur;
`role="button"` onu ezer ve ekran okuyucu **9 sütunlu satırın hücre yapısını kaybeder** —
bu erişilebilirliği düzeltmek değil yok etmektir. Satır tıklaması bir **fare kolaylığı**
olarak kalır (`@click` + `cursor: pointer`); klavye yolu satırdaki gerçek `<button>`'dır.
`ds-card` tarafında `role="button"` **kalır** — orada kök bir `<div>`, çakışma yok
(emsal: `TenderCrm.vue:467-476`, doğru kurulmuş).

#### (b) Ödül paneli (`SourcingWorkspace.vue:780-1005`) — **üç bölge**

Ölçüldü: `panelMode === 'both'` (`:862`) onaylı özeti (`:788`) **ve** taslak formunu
(`:865`) **aynı anda** çiziyor. Yani bugün iki primary aynı anda ekranda.

| # | Bölge kökü | İçerik | Primary |
|---|---|---|---|
| 1 | `ds-form-section` "Awarded" (B13) | `ds-fill` (kazanan + tutar) + `ds-deflist` + `ds-drawer-foot` | **`Create purchase order` = `ds-btn--primary`** |
| 2 | `ds-form-section` "Draft decision" (B13) | form alanları + `ds-drawer-foot` | **`Save draft decision` = `ds-btn--primary`** |
| 3 | `ds-form-section[data-commit="1"]` "Irreversible" (B9) | sonuç cümlesi + özet + silahlama kutusu + `ds-drawer-foot` | **`Approve decision` = `ds-btn--commit[data-sev="crit"]`** · primary **0** |

`Re-award this lot` (`:850-859`, bugün `btn-link btn-sm`) → bölge 1'de nötr `ds-btn`.

> **`Create purchase order` GERİ GETİRİLDİ.** `bosluk`'un iskeletinde **0 kez** geçiyordu
> (ölçüldü). O düğme (`SourcingWorkspace.vue:839-849`) `sourcingAwardPanel.spec.js`'in
> **var olma sebebidir** — spec'in kendi yorumu: *"Reload the page and an already-awarded
> lot rendered the NEW-award form instead, **with no way to reach the PO route at all**."*
> Bir tasarım turu, bir hatanın düzeltilmesi için yazılmış tek yolu düşüremez.

**`awardPanelMode` kuralı korunur** (brief §5.2): fonksiyon `:52-71`, `computed` `:320`,
şablon dört yerde (788, 852, 862, 865) yalnız onu okuyor. Commit bloğu kendi `v-if`'inde
`panelMode`'u değil, bugün `Approve` düğmesinin okuduğu ifadelerin **aynısını** okur
(`:981-985`).

#### (c) İhale girişi çekmecesi (`TenderMasterDrawer.vue`)

| Bugün | Tasarım |
|---|---|
| `<div class="tgm-drawer" role="dialog">` (:340) — `aria-modal` **yok**, `aria-labelledby` **yok** | `<aside class="ds-drawer" data-size="lg" role="dialog" aria-modal="true" aria-labelledby="tgm-title">` — emsal aynı ekranın komşusu: `QuotationEntryDrawer.vue:225` |
| `tgm-drawer-dialog` / `-content` (:341, :342) | **silinir** |
| `tgm-drawer-footer` (:644) | `ds-drawer-foot` (B5) |
| `Cancel` `btn btn-ghost-secondary` (:645) | `ds-btn` |
| `Save Tender` `btn btn-primary` (:648) | `ds-btn--primary` — bu bölgedeki tek primary |
| `spinner-border` (:649) | **etiket takası:** `{{ saving ? t("Saving…") : t("Save Tender") }}` + `aria-busy="true"` |
| `<input type="number">` (:517, :606) | §10.4'ün cevabına göre `MoneyInput` veya `ds-input` + `input-group-text` |
| — | **YENİ:** `Delete tender` `TenderCrm.vue` footer'ından **kendi commit bloğuna** (§5.4) |

#### (d) Belge merkezi (`TenderDocuments.vue`)

| Bugün | Bölge | Tasarım |
|---|---|---|
| `Edit checklist` 44-46 / `Cancel` 48 | B2 | `ds-btn[data-size="sm"]` |
| `Save checklist` 49-51 | B2 | `ds-btn--primary[data-size="sm"]` — bölgenin tek primary'si |
| `Remove requirement` 85 | B10 | `ds-btn[data-size="sm"][data-icon="1"]` |
| `Add requirement` 91-93 / `Add standard set` 94-96 | B3 | `ds-btn[data-size="sm"]` |
| `Upload file` 158-160 / `Waive` 161-163 | B10 | ikon + `aria-label`; **komşusuyla aynı ağırlık**. `btn-ghost-warning` köprünün ghost listesinde **yok** → bugün kenarlı beyaz kutu |
| upload modal `Save document` 196-198 | B6 | `ds-btn--primary` |
| **waive modal `Confirm waiver`** 228-230 | B6 | **`ds-btn--commit[data-sev="today"]`**; mevcut `:disabled="waiveSaving \|\| !waiveForm.reason.trim()"` silahlama görevini görür; footer'da primary yok → R5 ✔ |
| waive modal uyarısı 212-215 | B6 | **kalır** — commit grameri parça 2'nin (sonuç cümlesi) hazır örneği |
| 10 literal `badge bg-*` | — | durum olanlar `<StatusBadge>`; `Tender Master`/`Lot Specific` **kapsam** rozetleri durum değil → `ds-chip` |
| **↺ `<tr … role="button">` 257** | B10 | **SİLİNİR** (T8). §1.3'ün yasağının tek canlı ihlali burada, ve sürüm 1'in bu tablosunda **hiç geçmiyordu** — yasak kendi ekranındaki tek ihlali görmüyordu. Yerine: satırda gerçek bir `<button>` (lot seç), fare için `@click` + `cursor: pointer` (Ç18) |
| **↺ `form-switch` 70** | — | **KALIR** bu turda; `form-check`'e göçü B-16. Delta onu bozmuyor (D11) |

**Tek yazar kuralı korunur** (brief §5.2): `TenderIntake.vue:287` `Open Document Center`
**kalır** (bir kapıdır); `TenderDocumentsPanel.vue`'a düzenleme aksiyonu **eklenmez**.

#### (e) RFQ listesi (`rfq/RfqList.vue`, 146 satır)

| Bugün | Bölge | Tasarım |
|---|---|---|
| `New request` (`ListToolbar` `primaryLabel`) | B8 | **kalır, primary.** Sınıf `ListToolbar`'ın **içinde**, dokunulmaz |
| `Clear lot filter` 73-75 | B1 | `ds-btn` — zaten doğru |
| satır tıklaması 104-108 (`style="cursor: pointer"` 106, başka hiçbir şey yok) | B10 | fare kolaylığı **kalır**; klavye yolu **satırdaki gerçek `<button>`** (Ç18) |
| lot linki 111-114 | B10 içi | `router-link` + `@click.stop` — `openLot` (57-60) zaten `stopPropagation` yapıyor |
| teklif sayısı rozeti 118-128 (yerel `tenderPolicy.minQuotations` ternary'si) | rozet | `ds-meter` (css:337) — **rozet değil ölçer**; politika sayısı sunucudan gelir, ekrana yazılmaz (brief §5.3) |
| durum rozeti 130-133 | rozet | `<StatusBadge doctype="Request for Quotation" :docstatus="r.docstatus" />` — çıktı bugünküyle birebir aynı; kazanç guard'ın uygulanabilir olması |
| `catch` 41-44 (`toast.error` + `rows.value = []`), sonra `EmptyState` 139-143 | B12 | **hata ≠ boş** → §6.4. **B12'de primary yoktur** (R2): `Try again` bir kurtarma, ekranın beklenen aksiyonu değil |

### 5.6 · Devre dışı ekseni — bir görünüm değil, bir **cümle**

Ölçüldü (python, `<button>` etiket taraması, uygulama geneli):

```
ds-btn taşıyan <button>            36
  devre dışı bağlaması olan        12   (10 dosya)
    …düğmede GERÇEK gerekçe taşıyan 3   ↺ (sürüm 1: 4 — PartyTransactions:325'in
                                          :title'ı koşulsuz bir açıklama,
                                          "Professional Excel export of this ledger",
                                          devre dışılık gerekçesi DEĞİL)
    …gerekçesiz                     9
  tender kapsamındakiler            7   (pages/tender ×5: OperationsDesk:27, TenderCrm:407,
                                         TenderCrm:741, TenderFlow:105, TenderOverview:107
                                         + QuotationEntryDrawer:321, :329)
  tender DIŞI                       5 dosya / 5 düğme   ↺ (sürüm 1 "üç dosya" deyip
                                         beş ad sayıyordu; ölçüm: Login:262,
                                         Suppliers:594, Customers:391,
                                         PartyTransactions:325, SalesOrderFormModern:1245)
ds-btn--primary olan                 3   (QuotationEntryDrawer:321, Login:262, Customers:391)

↺ <button> OLMAYAN ds-btn taşıyıcısı  18 site  ← sürüm 1 bunu hiç saymamıştı, §5.6b
```

**↺ İKİ taşıyıcı kod + bir destekleyici — "üçü de yazılıyor" iddiası ölçülünce düştü:**

| Kod | Nasıl | Ölçülen kontrast | Hüküm |
|---|---|---:|---|
| **RENK** (taşıyıcı) | `color: var(--ds-tx3)`, `background: var(--ds-bg)`; `--primary`'de mavi dolgu **kalkar** | metin 14.9:1 → **2.71:1** | **Taşıyor** — parlaklık sıçraması büyük ve gri tonlamada okunur |
| **ETİKET** (taşıyıcı) | **Sebep yazılır:** yanında `ds-field-hint`, veya düğmede `:title` / `aria-describedby`. K7 zorunlu kılıyor | metin | **Taşıyor** |
| **BİÇİM** (**destekleyici**) | `border-style: dashed`, `border-color: var(--ds-tx3)`; `--primary`'de **dolgunun kaybı** | sürüm 1'in `--ds-ln`'si: **1.19:1** → sürüm 2'nin `--ds-tx3`'ü: **2.71:1** | **Destekliyor, taşımıyor.** 1.4.11'in 3:1'ini geçmiyor ve bu yazılı (D9). `--primary`'de dolgunun kaybı (mavi→gri) ayrı ve **gerçek** bir sıçrama; nötr `ds-btn`'de zemin farkı yalnız 1.06:1 |

> **Kurul ACCEPTANCE #8 "en az ikisi" istiyor ve RENK + ETİKET onu karşılıyor.**
> Sürüm 1'in §11'de yazdığı sigorta — *"kontrast yetersiz çıkarsa biçim kodu tek
> başına ayakta kalır"* — ölçülünce **iki ucundan da kopuktu**: kontrast da yetersizdi
> (2.71:1), biçim de ayakta değildi (1.19:1). Sürüm 2 ikinci ucu 1.19 → 2.71'e
> çekiyor ve sigortayı **kaldırıyor**: taşıyıcı kod ETİKET'tir, ve K7 onu her düğmede
> zorunlu kılar.

### 5.6b · ↺ `<button>` olmayan devre dışı taşıyıcılar — sürüm 1'in adlandırmadığı boşluk

`ds-btn` taşıyan 18 eleman bir `<button>` değil (`router-link`, `span`, `a`). Deponun
**canlı** devre-dışı kalıbı onlar için `:disabled` değil, `.disabled` **sınıfı**:

```
Customers.vue:401-407   <router-link class="ds-btn ds-btn--primary"
                                     :class="{ disabled: isParent }"
                                     :title="isParent ? t('Transactions are …') : ''">
OperationsDesk.vue:100  <span class="ds-btn ds-btn--primary desk-lead-cta">
TenderCrm.vue:726/731/736  <router-link class="ds-btn" …>
```

Delta `.disabled` sınıfına **hiçbir kural yazmıyor**, ve köprüde de yok (Bootstrap'ınki
`.btn.disabled`'a bağlı, bu eleman `.btn` taşımıyor) → bugün **üç kodun sıfırı** görünüyor
ve bağlantı hâlâ tıklanabilir. K7 de kapatmıyor: ölçütü `<button>` geziyor.

**Karar:** delta bu turda `.disabled` kuralı **yazmıyor**, ve gerekçesi şu — bir bağlantının
devre dışı edilmesi bir CSS sorunu değil bir **işaretleme** sorunudur (`router-link`
tıklanabilirliğini CSS durduramaz; `pointer-events: none` klavye erişimini de öldürür,
`aria-disabled` ise ekran okuyucuya "burada" der). Doğru cevap bağlantıyı **çizmemek**
veya bir `<button>`'a çevirmektir, ve o bir ekran kararıdır. **B-20**'ye yazıldı, ve
K7'nin kapsamı bu turda `<button>` ile **sınırlı olduğu açıkça yazılıyor.**

**Kapsam sınırı, bilerek dışarıda ve işaretli:** `.ds-seg button`, `.ds-stepper button`,
`.ds-drawer-close`, `.ds-cut-del` de `<button>` ve hiçbirinin `:disabled` kuralı yok.
Dördü de bugün devre dışı bağlaması **taşımıyor** (ölçüldü) → **B-10**.

**Ders `QuotationEntryDrawer`'dan alındı:** `:174` — `save()` engel varken **sessizce
döner**, yani devre dışılık gerçek bir kapı; `:315-317` — engeller düğmenin yanı başında,
`role="alert"` ile; `:404-410` — stilin kendi yorumu kuralı yazıyor: *"kaydet düğmesi
devre dışıysa SEBEBİ görünür olmalı, yoksa kullanıcı tıklamayan bir düğmeye bakıp
kalıyor."*

---

## 6 · DURUM GRAMERİ — dördü ayrı, artı beşinci hâl

### 6.1 · Kural

> **yükleniyor ≠ boş ≠ hata ≠ yetkisiz.** Bu dördü *"istek bana ulaştı mı"* sorusunun
> cevabıdır. **"ölçülemiyor" bu eksende değil** — o, isteğin başarıyla döndüğü bir
> ekranda *elimdeki sayının ne anlama geldiğini* söyler.

- **Bölge = tek bir sunucu çağrısının beslediği görsel alan.** `SourcingWorkspace`'in
  bugünkü dört çağrısı (`loadQuotations`, `loadRfqs`, `loadDecision`, `loadUnassigned`)
  **dört bölgedir**; her biri kendi hâlini kendi taşır, ve birinin hatası komşusunu
  karartmaz.
- Her bölge her an **tek** bir hâlde olur ve o hâli **tek** bir eleman taşır.
  Bir hâl hem toast hem eleman ile anlatılmaz (ADR-305: *"toast bu ölçütü geçmez"*).
- **Ayırt edici kanıt üç koddur, renk değil:** dört hâl farklı **eleman**, farklı
  **kelime kalıbı** ve farklı **eylem** taşır.

**Test kancası:** `data-region-state="loading|empty|error|forbidden"`. Ölçüldü: depoda
**0 çakışma**. **Hiçbir CSS kuralı buna bağlanmaz** — `ds-sla[data-state]` (beşinci hâl)
ile karıştırılmasın diye ayrı ad (Ç10). Ve mount olmadığı için bu kanca **zorunludur**:
"bölge hangi hâlde" sorusunun kaynaktan cevaplanabilir tek yolu, şablonda duran tek ve
benzersiz bir dizedir.

**↺ Kancanın üç eksik tanımı kapatıldı** (sürüm 1'de §6.2 *"hepsinde"* diyordu, §1.2 ve
§6.1'in enum'u ise dört değerdi, ve şablon sırası **beş** hâl sayıyordu — beşincisi
içerik):

1. **Enum dörttür ve içerik hâli kanca TAŞIMAZ.** Öznitelik `null` olur, elemandan
   düşer. Gerekçe: kanca *"bu bölge şu anda bir HÂL çiziyor"* demek için var; içerik
   hâlin yokluğudur. Sürüm 1'in *"hepsinde"* cümlesi §6.3'ün koşulsuz özniteliğini
   üretmişti — aynı hatanın iki yüzü.
2. **Kanca hâl elemanının kendisinde değil, BÖLGE KÖKÜNDE durur** ve koşulludur:
   `:data-region-state="loading ? 'loading' : error ? 'error' : …"`. Yoksa "bölge
   hangi hâlde" sorusu iki eleman arasında bölünür.
3. **`empty` değerinin örneği** (sürüm 1'de üç iskelette de yoktu):
   ```html
   <div class="table-responsive" data-region-state="empty">
     <table class="ds-table"><thead>…</thead></table>
     <EmptyState :title="t('No quotations yet')"
                 :subtitle="t('Raise one to start collecting supplier prices.')" />
   </div>
   ```
   `<EmptyState>` **`<table>`'ın DIŞINDA** — §7'nin düzeltmesi, aşağıda.

### 6.2 · Şablon sırası — istisnasız

```
catch (err) {
  data = boş                                    // bayat veri hatanın altında kalmaz
  if (err?.status === 403 || /role|permission/i.test(err?.message)) forbidden = true
  else error = err?.message || ""               // SESSİZ CATCH YASAK
}
  ← err.status api/client.js:73 ve :110'da zaten set ediliyor (ölçüldü) → 0 sunucu değişikliği

1. forbidden  → alert alert-warning + ti-lock + rota düğmesi        (yeniden dene YOK)
2. error      → alert alert-danger  + ds-mono ham metin + "Try again"
3. loading    → tablo ise   <table><thead/><SkeletonRows v-if/></table>   (DOĞRUDAN çocuk)
                değilse     .ds-skel-stack > .ds-skel × 3
                alan ise    .ds-field .ds-skel  (44px)
                METİN YOK — kelime yalnız aria-label'a gider
4. empty      → birincil    <EmptyState>  (filtreli / gerçekten yok, iki dal)
                ikincil     .ds-empty[data-size="sm"]
5. içerik

hepsinde:          data-region-state="…"
hata + yetkisiz:   role="alert"
yükleniyor:        role="status" aria-live="polite" aria-label="…"

Metin kuralı: manşet = EYLEM. "X yüklenemedi" bir olgudur, manşet olamaz.
```

### 6.3 · YÜKLENİYOR

**İki şekil, biri tablo biri değil.** `SkeletonRows.vue` **değiştirilmez** — ↺ ölçüldü:
uygulama genelinde **79 dosya / 96 site** kullanıyor (sürüm 1 "80/97" diyordu; 97.'si
`vehicleFinanceAgreements.spec.js:167`'deki bir **test dizesi**, çağrı yeri değil), ve
kök elemanını değiştirmek **96 çağrı yerini** aynı anda değiştirirdi. Kökü
`<tbody class="placeholder-glow">` (`SkeletonRows.vue:10`).

**Şekil A — tablo bölgesi.** `SkeletonRows` `<table>`'ın **doğrudan çocuğu**; gerçek
`<tbody>`'ye `v-else`. `<table>` birden fazla `<tbody>` alabildiği için bu geçerli
HTML'dir ve `<thead>` monte kalır (sütun başlıkları yükleme sırasında kaybolmaz).

**↺ Sürüm 1'in iskeleti dört özniteliği `<table>` üzerine KOŞULSUZ koyuyordu** ve dört
ayrı kuralı birden bozuyordu: (1) yükleme bittikten sonra tablo kalıcı olarak
`data-region-state="loading"` taşıyordu — §6.1 bu kancayı *"tek yol"* ve **zorunlu**
ilan ediyor, yalan söyleyen bir kanca yok demektir; (2) §6.1'in *"her bölge her an tek
bir hâlde"* kuralı, dolu tablo aynı anda hem içerik hem "loading" oluyordu; (3) ekran
okuyucu veri geldikten sonra da *"Loading…"* duyuruyordu; (4) `role="status"` bir
`<table>`'ın **örtük `table` rolünü eziyordu** → 9 sütunlu satırın hücre yapısı ekran
okuyucudan kalıcı olarak kayboluyordu — **bu, belgenin Ç18'de `<tr role="button">`'a
karşı yazdığı itirazın kelimesi kelimesine aynısı.**

**Düzeltilmiş kalıp: hâl öznitelikleri koşulsuz `<table>`'a değil, sarmalayıcıya ve
koşullu olarak yazılır.**

```html
<div class="table-responsive" :data-region-state="loading ? 'loading' : null">
  <!-- role/aria-live/aria-label YALNIZCA yükleme sürerken var: durum duyurusu
       bir kere yapılır ve veri gelince ORTADAN KALKAR. <table> kendi örtük
       `table` rolünü korur — 9 sütunun hücre yapısı ekran okuyucuda yaşar. -->
  <div v-if="loading" role="status" aria-live="polite"
       :aria-label="t('Loading the quotation comparison…')" class="visually-hidden"></div>
  <table class="ds-table">
    <thead><tr><th>{{ t("Supplier") }}</th>… <th class="ds-td-num">{{ t("Total") }}</th></tr></thead>
    <SkeletonRows v-if="loading" :cols="9" :rows="4" />
    <tbody v-else>
      <tr v-for="row in rows" :key="row.name" :data-sev="row.sev || null">
        <td>{{ row.supplier }}</td>
        <td><span class="ds-chip" :data-tone="row.tone">{{ t(row.rank) }}</span></td>
        <td><StatusBadge doctype="Supplier Quotation" :docstatus="row.docstatus" /></td>
        <td class="ds-td-num ds-num">{{ formatMoney(row.total, row.currency) }}</td>
        <td>
          <!-- Ç18: satırda ODAKLANABİLİR gerçek bir <button>. Satır tıklaması
               yalnız bir FARE kolaylığıdır; klavye yolu budur. -->
          <button type="button" class="ds-btn" data-size="sm" data-icon="1"
                  :aria-label="t('Landed cost') + ' — ' + row.supplier"
                  @click.stop="openLanded(row)">
            <i class="ti ti-truck-delivery"></i>
          </button>
        </td>
      </tr>
    </tbody>
  </table>
</div>
```

`visually-hidden` köprüden gelir (Bootstrap/Tabler) ve katman ona dokunmuyor —
`role="status"` bir görsel eleman gerektirmez, iskeletin kendisi görsel kodu taşır.

**Bugünkü durum, ölçüldü (kaynak ayrıştırma, her `<SkeletonRows>`'un en yakın açık ata
etiketi):** tender'da **16 site, 0'ı doğru** — **8'i iç içe `<tbody>`** (DirectorBoard:228,
MyTenders:112, SourcingWorkspace:576, SourcingWorkspace:714, TenderDocuments:115,
RfqDetail:131, RfqForm:316, RfqList:102) ve **8'i öksüz** (DeclarantQueue:192,
LogistBoard:195, OperationsDesk:64, OperationsDesk:161, TenderCrm:432, TenderCrm:673,
TenderDocuments:244, TenderFlow:128).

**↺ Ama "doğru kalıp bugün hiçbir yerde uygulanmıyor" hükmü YANLIŞTI** — ve bu sürüm
1'in en ağır kanıt hatasıydı, çünkü ondan bir **talimat** çıkarıyordu (*"Aşama B onu
sıfırdan kurar, mevcut bir örneğe bakarak değil"*). Uygulama geneli ölçüm (96 site,
her `<SkeletonRows>`'un kaynaktaki en yakın açık ata etiketi):

```
toplam                                96
ata = <table>   (DOĞRU kalıp)         71   ← sürüm 1: "0"
ata = <tbody>   (iç içe)              16
başka ata       (öksüz)                9
```

**71 site zaten doğru.** Emsaller: `components/party/PartyList.vue:254-256`
(`<table class="ds-table pc-table"><SkeletonRows :rows="8" :cols="2" /></table>`),
`PartyTransactions.vue:337/497/548`, `admin/AccessReview.vue:140/175`,
`hr/Attendance.vue:390`, `hr/PayrollPreview.vue:305`.

**Ve depo bu kalıbı zaten guard'lıyor** — `stabler/tests/test_ci_bill_link_panel_source.py`:

```python
:94  def test_skeleton_is_a_direct_thead_sibling_not_nested_in_a_tbody(self):
:95      self.assertRegex(self.block, r"</thead>\s*<SkeletonRows")   ← K4'ün birebir emsali
:96      self.assertNotIn("<tbody", self.block)
:90  def test_skeleton_used_not_a_bare_spinner(self):
:91      self.assertIn("<SkeletonRows", self.block)
:92      self.assertNotIn("spinner-border", self.block)              ← K5'in yarısı, hazır
```

§8.1 *"deponun kendi kanıt yolu iki biçimde var"* diyor ve `sourcingAwardPanel.spec.js`
+ `test_design_layer_contract.py` sayıyor; K4 ve K5'in **birebir emsali olan bu üçüncü
dosya listede yoktu.** Düzeltildi (§8.1).

> **Düzeltilmiş talimat:** tender'ın 16 sitesi **kopyalanacak bir emsale sahiptir** —
> `PartyList.vue:254-256`. Aşama B onu **taklit eder**, sıfırdan kurmaz; ve guard'ı
> yazarken `test_ci_bill_link_panel_source.py:94-96`'yı **genelleştirir**, yenisini
> icat etmez. Bu, ADR-303'ün *"sorun kelime dağarcığı değil benimseme"* hükmünün
> tam da bu belgeye uygulanmış hâli.

**İki bağlayıcı değişmez:**
1. `:cols` = o tablonun `<thead>`'indeki `<th>` sayısı.
2. `hide-first-on-mobile` **ancak** ilk `<th>` de `d-none d-md-table-cell` taşıyorsa
   verilir. Bugün `DirectorBoard.vue:228` prop'u veriyor ama ilk `<th>` (`:216`) o sınıfı
   taşımıyor → dar ekranda iskelet 8, gerçek tablo 9 sütun çiziyor. Uyarı: prop'un
   kırılma noktası `d-md-*` = **768px**, tasarım sisteminin kendi kırılması **992px**
   (css:452). İkisi aynı değil; sütun gizlemede prop'un kullandığı 768 geçerlidir.

**Şekil B — tablo olmayan bölge** (panel gövdesi, KPI şeridi, kanban kulvarı, ödül
paneli, çekmece bölümü):

```html
<div class="ds-skel-stack" data-region-state="loading" role="status" aria-live="polite"
     :aria-label="t('Loading the award decision…')">
  <div class="ds-skel"></div><div class="ds-skel"></div><div class="ds-skel"></div>
</div>
```

**Şekil C — alan içi:** kontrolün yerine `<div class="ds-skel"></div>`, `.ds-field .ds-skel`
kuralı onu 44px yapar.

**Metin:** yükleniyor hâli **metin taşımaz**. Bugün 4 sitede taşıyor
(`SourcingWorkspace.vue:472`, `TenderFunnel.vue:374`, `TenderOverview.vue:136`,
`PoControlBoard.vue:537`) — hepsi kalkar. Gerekçe ölçüldü: `OperationsDesk.vue:64-76`
**dört ayrı hâli** (yetkisiz, hata, boş, şirket seç) **aynı** `ds-panel-foot desk-state`
sınıfıyla çiziyor — piksel piksel aynı, tek fark kelime. Hareket zaten "bekliyor" diyor;
kelime yalnız ekran okuyucuya `aria-label` olarak gider.
**`<EmptyState icon="ti-loader" :title="t('Loading…')" />` yasaklanır**
(`PoControlBoard.vue:537`): boş durumun bileşeni yükleme durumunu anlatamaz.

**↺ İki şekil, ama ölçüldü: İKİ ANİMASYON — ve bu kabul edilmiş bir tutarsızlıktır.**
`SkeletonRows.vue:10`'un kökü `<tbody class="placeholder-glow">` ve `placeholder-glow`
için **depo CSS'inde 0 kural** (`grep -rn 'placeholder-glow' public/css/` → boş) →
Bootstrap/Tabler CDN'inden geliyor, bir **opaklık nabzı**, ve `.stbl-ds` onu yeniden
giydirmiyor. `ds-skel` ise katmanın kendi **kayan gradyanı** (css:446-448, 1.3s
`ds-shimmer`). Yani Şekil A ile Şekil B aynı ekranda **iki farklı yükleme dili**
konuşuyor. Sürüm 1 ikisini "iki şekil" diye anlatıp bu farkı hiç görmemişti.

**Karar: bu turda birleştirilmez, ve gerekçesi yazılı.** `SkeletonRows` **79 dosya /
96 site** — kökünü ya da sınıfını değiştirmek uygulamanın en çok kullanılan bileşenini
tek commit'te değiştirmek olur, ve bu turun kapsamı tender'dı. Birleştirme **B-21**'e
yazıldı; doğru yön `placeholder-glow`'u köprüde `ds-shimmer`'a bağlamaktır (bileşene
dokunmadan, `.stbl-ds .placeholder-glow .placeholder` üzerinden) — mekanizma
`.form-control`/`.badge`/`.alert` ile aynı.

**Yeniden deneme:** yok — zaten deniyor. Yükleme hâlinde hiçbir düğme çizilmez.

**Dar ekran:** Şekil A `table-responsive` içinde olduğu için gerçek tabloyla aynı kayar.
Şekil B `ds-skel` blok elemandır, %100 genişlik. `ds-skel-stack` `padding: var(--ds-pad)`
taşır, ek kural gerekmez.

### 6.4 · BOŞ

**İki eksen, ikisi de karıştırılmaz.**

**Eksen 1 — düzey:**

| Düzey | Bileşen | Nerede |
|---|---|---|
| Birincil | `<EmptyState>` (159 kullanım, `compact` prop'u **16'sında canlı**) | sayfanın/panelin ana listesi; çekmece ve kulvar içinde `compact` |
| İkincil | `ds-empty[data-size="sm"]` | form bölümü, kanban kulvarı, alt tablo |

`ds-field-hint` **asla** boş hâl taşımaz (Ç7). Tam boy `ds-empty` bir 268px'lik kulvara
konmaz: 42+42px dikey dolgu, karttan (13px, css:378) uzun bir boşluk kutusu üretir — ve
**iki bağımsız dosya** bu değeri zaten ezmiş.

**Eksen 2 — sebep:** filtre yüzünden mi boş, gerçekten yok mu? İki farklı metin, iki
farklı eylem:

| Sebep | Metin kalıbı (eylem!) |
|---|---|
| Filtre | *"Clear the supplier or status filter, or widen the date range."* |
| Gerçekten yok | *"Raise one to start collecting supplier prices."* |

**Yeniden deneme:** yok — boş bir cevap başarılı bir cevaptır.
**Dar ekran:** `EmptyState` kendi içinde akışkan; `ds-empty[data-size="sm"]` 16px dolgu.
**Erişilebilirlik:** `role` **yok** — boş bir liste bir uyarı değil, bir bilgidir.

### 6.5 · HATA

**Sert kural:** bir hata **asla** boş hâlle aynı elemanı çizmez, ve **asla** yalnız toast
ile anlatılmaz (kurul ACCEPTANCE #5). **Sessiz `catch` yasak.**

**Tek kural, üç kapsam — kapsam sınırı bağlayıcıdır:**

| Kapsam | Eleman | Neden |
|---|---|---|
| **Bölge yükleme hatası** (çağrı düştü, içerik çizilmez) | `<div class="alert alert-danger" role="alert" data-region-state="error">` + `<p class="ds-mono">{{ error }}</p>` + `<button class="ds-btn" data-size="sm">{{ t("Try again") }}</button>` | Köprü `.alert`'i zaten giydiriyor (css:1013: kare köşe, 1px kenar, **soldan 3px**, gölge yok) → **sıfır yeni CSS**. ADR-305'in referansı `RfqDetail.vue`/`RfqPrint.vue` ve ikisi de `alert alert-danger` kullanıyor — *"yenisi icat edilmez"* |
| **Form gönderim özeti** (doğrulama düştü, içerik yerinde) | `<div class="ds-empty" data-tone="crit" role="alert" tabindex="-1">` + odak taşınır | §4.1(b) |
| **Alan hatası** | `ds-field-err` + `aria-invalid="true"` | §4.2 madde 5 |

**Reddedilenler ve nedeni:**
- `aksiyon` §7.5'in `ds-panel` + `ds-sev` + `data-sev` kurgusu → dördüncü bir lehçe,
  ölçülmüş kazancı yok, ve `data-sev`'i bölge köküne taşımayı gerektiriyor.
- `bosluk`'un `ds-panel-foot[data-state="error"]`'ı → 10.5px mono bir dipnot (css:549-553)
  hata manşeti olamaz, ve `OperationsDesk`'in ölçülmüş kusurunu **tekrarlıyor**.
- `cekmece`'nin bölüm düzeyi `ds-field-err`'ü → bir bölümün tamamı sunucudan gelemediyse
  bu bir **alan** hatası değil, bir **bölge** hatasıdır.

**Yeniden deneme: evet, ve bu ölçülmüş bir boşluk.** `grep -rn "Retry|Try again"` →
uygulamanın **hiçbir** yükleme-hatası dalında yeniden deneme düğmesi yok. Anahtar
`Try again` (katalogda var); `Retry` açılmaz.

**Metin:** manşet eylemi adlandırır. *"Try again — the quotation table did not load."*
Ham sunucu mesajı **`ds-mono` ile ayrı satırda** durur, manşetin yerine geçmez.
**Dar ekran:** `alert` blok elemandır; düğme `flex-wrap` ile alt satıra iner.

### 6.6 · YETKİSİZ

**Sert kural:** yetkisiz **hata değildir**. Kullanıcı yanlış bir şey yapmadı; yanlış
ekrandadır. Bu yüzden **yeniden deneme düğmesi YOKTUR** — aynı istek aynı cevabı verir.

```html
<div class="alert alert-warning" role="alert" data-region-state="forbidden">
  <i class="ti ti-lock"></i>
  <p>{{ t("Bid pricing is the sourcing role's screen. Your work for today is on the operations desk.") }}</p>
  <router-link class="ds-btn" data-size="sm" :to="{ name: 'tender-operations' }">
    {{ t("Go to the operations desk") }}
  </router-link>
</div>
```

**Ayırt etme sunucu değişikliği gerektirmiyor:** `err.status === 403` istemcide zaten
set ediliyor (`api/client.js:73`, `:110` — ölçüldü), ve `client.js:40/106` 403'te bir
`stabler:forbidden` olayı da yayınlıyor. Kapı **uçta** durur, navigasyonda değil
(brief §5.2).

**Üç kod:** farklı ikon (`ti-lock` ↔ hatada ikon yok) + farklı ton (warning ↔ danger) +
farklı **eylem** (rota ↔ yeniden dene). Renk tek başına ayırt etmiyor.

**Metin kuralı burada en sert:** kullanıcıya *ne yapamadığını* değil, **nereye gitmesi
gerektiğini** söyler. Rol adı geçebilir, ama suçlayıcı değil bilgilendirici olarak.

### 6.7 · BEŞİNCİ HÂL — "ölçülemiyor"

Sayfanın değil **hücrenin** hâli, ve dik bir eksende. Sentetik kümede kaynağı belli:
**2 damgasız lot** (4312, 4313) süreç akışında bu satırı üretiyor.

**Üç yuva, üçü de zorunlu:**
1. **Değer** `—` (tire). **`0` yazılmaz** — 0 bir ölçümdür, bu bir ölçüm yokluğudur.
2. **Durum** `<span class="ds-sla" data-state="unknown">{{ t("Not measurable") }}</span>`
3. **Kapsam notu** `<span class="ds-mono">{{ t("no approval stamp") }}</span>` — neyin
   eksik olduğunu söyler.

**Renk verilmez.** Katmanın kendi gerekçesi (css:870-873): *"İki dürüstlük durumu.
Renkleri aynı ve sessiz — ayrımı KELİME taşıyor… uyarı rengi vermek gözü sorunu olmayan
satıra çekerdi."* `ds-sla[data-state="unknown"]` ve `["empty"]` ikisi de `--ds-tx3`.

---

## 7 · BEŞ HÂL — her bileşen için

Dar ekran sütunu iki kırılmayı ayırır: **992px** (katmanın kendi kırılması, css:452) ve
**640px** (çekmece ve ızgara, css:698).

| Bileşen | Dolu | Boş | Hata | Yetkisiz | Dar ekran |
|---|---|---|---|---|---|
| `ds-table` | satırlar; sayısal hücre `ds-td-num` | ↺ `<EmptyState>` **`<table>`'ın DIŞINDA**, `table-responsive`'in kardeşi olarak (`<tbody>` *yerine* **DEĞİL**) | tablo **çizilmez**; yerine `alert alert-danger` (B12) | `alert alert-warning` + rota | **`table-responsive` zorunlu** — `.ds-table`'da `overflow-x` yok (ölçüldü) |
| `ds-table` satırı | `tr[data-sev]` vurgusu + satırda `ds-chip[data-tone]` | — | — | — | `ds-td-num` `white-space: nowrap` (css:401) → sayılar sarmaz, tablo kayar |
| `SkeletonRows` | — | — | — | — | `<thead>` monte kalır; `hide-first-on-mobile` yalnız ilk `<th>` de gizleniyorsa |
| `ds-panel` | `-head` + gövde + `ds-panel-foot` (kaynak beyanı) | gövdede `EmptyState` | gövdede `alert alert-danger` | gövdede `alert alert-warning` | tam genişlik; `-head` `flex-wrap` |
| `ds-form-section` | `-head` (`ds-label`) + `ds-form-body` | bölüm gövdesinde `ds-empty[data-size="sm"]` | bölüm bir bölge ise `alert alert-danger`; alan hatası ise `ds-field-err` | bölüm salt-okuma: kontroller `disabled` + form-içi yetki notu (Aşama B) | `-head`'e `flex-wrap: wrap` (§3.2-K) |
| `ds-form-section[data-commit="1"]` | sonuç cümlesi + özet + silahlama + `ds-drawer-foot` | — (özet yoksa blok **çizilmez**) | commit düğmesi `disabled` + sebep `ds-field-hint` | blok **çizilmez** (yetkisi yoksa onay bloğu görünmez) | 2px kenar korunur, dolgu değişmez |
| `ds-field` | `ds-field-label` + kontrol + `ds-field-hint` | kontrol boş; **placeholder boş hâl sayılmaz** | `ds-field-err` + `aria-invalid` | kontrol `disabled` (köprü css:930 giydiriyor) | `ds-form-grid` 640px'te tek kolona iner (css:702-703) |
| `ds-field` yükleniyor | — | — | — | — | `.ds-field .ds-skel` 44px — yükleme bitince zıplama yok |
| `ds-btn` | etiket + isteğe bağlı ikon | — | — | `:disabled` + sebep | metin sarmaz; bölge `flex-wrap` ile alt satıra iner (`ds-drawer-foot` css:671 zaten wrap) |
| `ds-btn--primary` | dolu `--ds-acc` | — | — | `:disabled` → **dolgu kalkar** (biçim kodu) | aynı |
| `ds-btn--commit` | 2px kenar + `ds-sev` | — | — | silahlanmamış: `disabled` + `data-armed="0"` | aynı |
| `ds-drawer[data-size="lg"]` | 760px, `-head`/`-body`/`-foot` | gövdede `EmptyState compact` | gövdede `alert alert-danger` | çekmece **açılmaz**; sayfa düzeyi yetkisiz | **640px'te `width: 100vw`, `border-left: 0`** (css:699-701) |
| `ds-kanban` / `ds-col` | 268px kulvarlar, `ds-col-head[data-sev]` | kulvarda `ds-empty[data-size="sm"]` | pano düzeyi `alert alert-danger` | `alert alert-warning` + rota | `ds-kanban` `overflow-x: auto` (css:369) — kendi içinde kayar |
| `ds-card` | `-t` `-id` `-org` `-foot`; `role="button"` **meşru** (kök `<div>`) | — | — | — | kulvar genişliği sabit 268px; kart akışkan |
| ↺ `ds-chip[data-tone]` | **İKİ kod: renk + kelime.** 7×7 kare `background: currentColor` — dört tonda **birebir aynı**, yani bir **sabit**, ayırt edici kod değil (B-14). Gri tonlamada ayrımı **yalnız kelime** taşır | — | — | — | `white-space: nowrap` — **metin tek kelime olmak zorunda** (§4.3) |
| ↺ `ds-sev[data-sev]` | **ÜÇ kod:** renk + biçim (`soon` 1.5px çerçeve, `info` **noktalı** çerçeve, css:311/313) + üç harf. **İstisna:** `crit` ve `today` ikisi de **dolu kare** → o çiftte iki kod (B-14) | — | — | — | `display: flex`, sarmaz |
| `ds-sev` yerleşimi | 11×11 kare + üç harf; bir `[data-sev]` **atası** ister. `info` metni blok L ile `--ds-info-tx`'e taşındı (3.03 → 5.83:1) | — | — | — | `display: flex`, sarmaz |
| `StatusBadge` | `STATUS_MAP`'ten sınıf | — | — | — | köprü `.badge` kare köşe (css:136-138) |
| `ds-meter` | dolu/boş segment + `ds-meter-txt` | 0 segment dolu | — | — | `display: flex`, akışkan |
| `EmptyState` | — | ikon + başlık + alt başlık + `#actions` (B7, ≤1 primary) | — | — | `compact` prop'u çekmece/kulvar için |
| `alert alert-danger/-warning` | — | — | manşet + `ds-mono` ham metin + eylem | ikon `ti-lock` + rota | blok; düğme alt satıra iner |
| `ds-sla[data-state]` | `in`/`edge`/`out` | `empty` | — | — | mono 10.5px, sarmaz |
| `ds-empty` | — | `[data-size="sm"]` ikincil · `[data-tone="crit"]` form hata özeti | — | — | dolgu `var(--ds-pad)` |
| `form-check` (onay kutusu) | kare kutu, `--ds-acc` işaretli | — | — | `disabled` (köprü) | etiket sarar |
| Jeton listesi (çoklu seçim / dosya) | `ds-table` satırları + `ds-cut-del` + `ds-cut-add` | `ds-empty[data-size="sm"]` | `ds-field-err` (alan) veya `alert` (bölge) | `ds-cut-del` gizlenir, ekleyici şerit çizilmez | `ds-cut-add` `flex-wrap: wrap` (css:790-792) |

---

## 7b · ↺ İSKELETLER — sürüm 1'in en büyük eksiği

**Çürütmenin hükmü:** *"Belge denetçinin şikâyetini kapatmıyor… Bir uygulayıcı bu
belgeyi açıp ÜÇ şeyi kodlayabilir. Geri kalan her şey için düzyazıdan işaretleme icat
etmesi gerekir — ve belgenin kendi reddettiği altı adın ret gerekçesi 'bileşim hiç
denenmedi' iken, belge o bileşimi de denemiyor."*

Ölçüm: sürüm 1'de ` ```html ` bloğu **3**. §5.4'ün beş parçası, §4.1'in `id`
sözleşmesi, Ç18'in klavye kuralı — üçü de yalnız düzyazıydı. **İki uygulayıcı
bunlardan iki farklı DOM üretir, ve bu tam olarak denetçinin şikâyet ettiği durumdur.**

Aşağıdaki beş iskelet yazıldı (§6.3'ün tablosu ve §6.6'nın yetkisiz kutusuyla birlikte
toplam **7**). Kalan on bileşen §12c'de adıyla, **açık borç olarak** işaretli.

### 7b.1 · Jeton listesi — **D1'in ret gerekçesi buna dayanıyordu**

`ds-file-list`/`-chip`/`-name` üç adı, *"`ds-table` + `ds-cut-del` + `FileSlot`
bileşimi hiç denenmedi"* gerekçesiyle reddedildi (§3.4). **Sürüm 1 o bileşimi de
denemiyordu** — yani bir ret, denenmemiş bir alternatife dayanıyordu. Deneniyor:

```html
<!-- §4.2 madde 10 ve 11 AYNI gramer maddesidir: silinebilir şeylerin listesi
     + bir ekleyici. Kap: İstisna 1 (alan birden çok kontrol taşıyor). -->
<div class="ds-field" role="group" aria-labelledby="award-files-lbl"
     :data-region-state="filesLoading ? 'loading' : (!files.length ? 'empty' : null)">
  <span id="award-files-lbl" class="ds-field-label">
    {{ t("Attachments") }}<span class="ds-field-req" aria-hidden="true">*</span>
  </span>

  <div class="table-responsive">
    <table class="ds-table">
      <tbody v-if="files.length">
        <tr v-for="f in files" :key="f.name">
          <td><span class="ds-mono">{{ f.file_name }}</span></td>
          <td class="ds-td-num ds-num">{{ formatBytes(f.file_size) }}</td>
          <td>
            <!-- ds-cut-del: 30px GENİŞLİK, katmanda height YOK (css:785-788).
                 Gerçek dokunma hedefi ~30×17px — WCAG 2.5.8'in 24×24'ünün
                 ALTINDA. §0.3-D1 bedeli "34px → 30px" diye yazmıştı; ölçülen
                 gerileme YÜKSEKLİKTE ve daha ağır. Uygulayıcı bunu bilerek
                 yazar; düzeltmesi ds-cut-del'e min-height ve o AŞAMA B (B-23). -->
            <button type="button" class="ds-cut-del"
                    :aria-label="t('Remove') + ' ' + f.file_name"
                    @click="removeFile(f)">&times;</button>
          </td>
        </tr>
      </tbody>
      <SkeletonRows v-else-if="filesLoading" :cols="3" :rows="2" />
    </table>
  </div>

  <!-- Boş hâl tablonun DIŞINDA (§7): <div> bir <table>'ın geçerli çocuğu değil,
       ayrıştırıcı onu foster-parenting ile dışarı taşır. -->
  <div v-if="!filesLoading && !files.length" class="ds-empty" data-size="sm">
    {{ t("Attach the signed offer and the price list.") }}
  </div>

  <!-- Ekleyici şerit: ds-cut-add zaten flex-wrap:wrap (css:790-792) -->
  <div class="ds-cut-add">
    <FileSlot :doctype="doctype" :docname="docname" @uploaded="onUploaded" />
    <span class="ds-field-hint">{{ t("PDF or XLSX · up to 10 MB") }}</span>
  </div>
</div>
```

**Çoklu seçim** aynı iskelettir; `FileSlot` yerine `<Typeahead>` girer ve satırlar
dosya değil jeton taşır. Ayrı çizmek üçüncü bir lehçe üretirdi.

### 7b.2 · Form bölümü montajı — §4'ün on iki maddesinin hepsi bunu varsayıyordu

```html
<section class="ds-form-section">
  <div class="ds-form-section-head">   <!-- flex-wrap: wrap, §3.2-K -->
    <span class="ds-label">A · {{ t("Lot and deadline") }}</span>
    <!-- B4 yuvası. R9: bu yuva ile aşağıdaki ds-drawer-foot BİRLİKTE ≤1 primary -->
  </div>

  <div class="ds-form-body">
    <div class="ds-form-grid" data-cols="2">   <!-- data-cols="3" YASAK, Ç11 -->

      <!-- Varsayılan: SARMALAYAN <label class="ds-field">. §4.1(a) -->
      <label class="ds-field">
        <span class="ds-field-label">
          {{ t("Deadline") }}<span class="ds-field-req" aria-hidden="true">*</span>
        </span>
        <!-- DateInput id KABUL EDİYOR (:28) → sarmalamaya EK OLARAK for/id de
             yazılır, çünkü aria-describedby'nin hedefi ondan doğar (İstisna 2) -->
        <DateInput id="intake-deadline" v-model="form.deadline" required
                   aria-required="true"
                   :aria-invalid="errors.deadline ? 'true' : null"
                   aria-describedby="intake-deadline-hint intake-deadline-err" />
        <span id="intake-deadline-hint" class="ds-field-hint">
          {{ t("Working days only · supplier gets 3 days to respond") }}
        </span>
        <span v-if="errors.deadline" id="intake-deadline-err" class="ds-field-err">
          {{ errors.deadline }}
        </span>
      </label>

      <!-- Typeahead id KABUL ETMİYOR (kök <div>, inheritAttrs beyanı 0) →
           for= KULLANILMAZ, yalnız sarmalama. §4.1(a) tablosu -->
      <label class="ds-field">
        <span class="ds-field-label">{{ t("Supplier") }}</span>
        <Typeahead v-model="form.supplier" doctype="Supplier" />
        <span class="ds-field-hint">{{ t("Only approved suppliers are listed.") }}</span>
      </label>

      <!-- Onay kutusu — 12. madde. form-switch DEĞİL (§1.3). Köprü, §3.2-J -->
      <div class="ds-field">
        <label class="form-check">
          <input v-model="form.vatRecoverable" class="form-check-input" type="checkbox">
          <span>{{ t("VAT is recoverable on this lot") }}</span>
        </label>
      </div>

    </div>
  </div>

  <!-- B5 yuvası. R9 ile B4 ile birlikte tek kotayı paylaşır -->
  <div class="ds-drawer-foot">
    <button type="button" class="ds-btn--primary ds-btn" data-size="sm"
            :disabled="!canSaveSection">
      {{ t("Save draft decision") }}
    </button>
    <span v-if="!canSaveSection" class="ds-field-hint">
      {{ t("Enter a deadline and a supplier first.") }}   <!-- §5.6 ETİKET kodu -->
    </span>
  </div>
</section>
```

### 7b.3 · Commit bloğu — modülün en yüksek bahisli bileşeni

Sürüm 1'de 14 kez anılıyor, **0 kez kuruluyordu.** §5.4'ün **altı** parçası burada:

```html
<!-- Parça 1: KENDİ BÖLGESİ. B9 → primary sayısı SIFIR (R5) -->
<section class="ds-form-section" data-commit="1"
         v-if="canApprove && decision.winner">   <!-- yetkisizde blok ÇİZİLMEZ, §7 -->
  <div class="ds-form-section-head">
    <span class="ds-label">C · {{ t("Irreversible") }}</span>
  </div>

  <div class="ds-form-body">
    <!-- Parça 2: SONUÇ CÜMLESİ — fiil, "geri alınamaz" değil -->
    <p>{{ t("Approving writes the server-side stamp and closes this lot to further quotations.") }}</p>

    <!-- Parça 3: SONUÇ ÖZETİ — neyin onaylandığı okunabilir -->
    <dl class="ds-deflist">
      <dt>{{ t("Winner") }}</dt><dd>{{ decision.winner }}</dd>
      <dt>{{ t("Total") }}</dt>
      <dd class="ds-num">{{ formatMoney(decision.total, decision.currency) }}</dd>
      <dt>{{ t("Reason") }}</dt><dd>{{ decision.reason }}</dd>
    </dl>

    <!-- Parça 4 + 6: SİLAHLAMA KUTUSU, DOM'da DURAN, ve komşusundan AYIRT EDİLİR.
         Ölçüldü: aynı panelde :932'de bir "Policy exception required" onay kutusu
         VAR ve o bir VERİ ALANI. Ayrım üç kodla: (a) bu kutu data-commit="1"
         bölgesinin İÇİNDE, o dışında; (b) etiketi bir TAAHHÜT CÜMLESİ, alan adı
         değil; (c) doğrudan düğmenin üstünde, ds-drawer-foot'un hemen öncesinde.
         useConfirm() KULLANILMAZ (Ç2). -->
    <label class="form-check">
      <input v-model="awardAck" class="form-check-input" type="checkbox">
      <span>{{ t("I have reviewed the winner and the amount above.") }}</span>
    </label>
  </div>

  <div class="ds-drawer-foot">
    <button type="button"
            class="ds-btn ds-btn--commit" data-sev="crit"
            :data-armed="awardAck ? '1' : '0'"
            :disabled="!awardAck || approvingDecision"
            aria-describedby="award-commit-why"
            @click="approveDecision">
      <span class="ds-sev"><i></i><span>FINAL</span></span>
      {{ approvingDecision ? t("Saving…") : t("Approve decision") }}
    </button>
    <!-- Parça 5: SEBEP GÖRÜNÜR. §5.6'nın ETİKET kodu — devre dışılığın taşıyıcı kodu -->
    <span id="award-commit-why" v-if="!awardAck" class="ds-field-hint">
      {{ t("Tick the box above to enable approval.") }}
    </span>
  </div>
</section>
```

> **`aria-busy` nerede:** bekleme hâli **etiket takasıyla** anlatılır (Ç9) —
> `{{ approvingDecision ? t("Saving…") : t("Approve decision") }}` — ve düğmeye
> `:aria-busy="approvingDecision"` eklenir. **Spinner elemanı yoktur** (§1.2).

### 7b.4 · `ds-seg` — R4'ün dört ölçülmüş ihlalinin yerine geçen kalıp

```html
<!-- R4: RENK SEÇİM DURUMU TAŞIMAZ.
     :class="cond ? 'btn-primary' : 'btn-outline-secondary'" YASAK.
     ds-seg'de primary YOKTUR: seçili düğme --ds-ink alır (css:436). -->
<div class="ds-seg" role="group" :aria-label="t('Lane filter')">
  <button v-for="opt in lanes" :key="opt.id" type="button"
          :aria-pressed="lane === opt.id ? 'true' : 'false'"
          @click="lane = opt.id">
    {{ t(opt.label) }}
  </button>
</div>
```

### 7b.5 · Hata bölgesi — kardeşi (yetkisiz) tam blok almıştı, bu almamıştı

```html
<div class="alert alert-danger" role="alert" data-region-state="error">
  <!-- Manşet = EYLEM. "X yüklenemedi" bir olgudur, manşet olamaz. -->
  <p>{{ t("Try again — the quotation table did not load.") }}</p>
  <!-- Ham sunucu mesajı AYRI SATIRDA, manşetin yerine geçmez -->
  <p class="ds-mono">{{ error }}</p>
  <!-- B12'de primary YOKTUR (R2): Try again bir kurtarma, beklenen aksiyon değil -->
  <button type="button" class="ds-btn" data-size="sm" @click="load()">
    {{ t("Try again") }}
  </button>
</div>
```

---

## 8 · KABUL ÖLÇÜTLERİ — **mount testine dayanmadan**

### 8.1 · Neden ve nasıl

Beş şartnamenin 57 ölçütünün **30'u** mount testi istiyordu. Ölçtüm:

```
grep -n 'test-utils|jsdom|happy-dom' package.json   → 0 eşleşme
grep -rn '\bmount(' stabler/public/js/tests/        → 0
grep -rl '@vue/test-utils' …/tests/                 → 17 dosya (ADINI anıyor, kullanmıyor)
sed -n '15p' vitest.config.mjs                      → environment: "node",
```

`vitest.config.mjs:1-10` gerekçesini **yazılı** veriyor: *"No DOM, no component mounting,
no jsdom dependency… `environment: "node"` on purpose."* Ve iki bağımlılık da depo
kökünde olurdu — kurul ACCEPTANCE #7'nin (*"`stabler/` dışı 0"*) yasakladığı yerde.

**↺ Deponun kendi kanıt yolu ÜÇ biçimde var** (sürüm 1 üçüncüsünü atlamıştı, ve o
tam olarak K4 ile K5'in emsali):
- **Kaynak-yürütme** — `sourcingAwardPanel.spec.js` (182 satır): dosyayı `readFileSync`
  ile okur, `extractFunction()` / `vIfAt()` ile fonksiyonları ve `v-if` ifadelerini
  **çıkarıp çalıştırır**. Dosyanın kendi yorumu neden `toContain`'in yetmediğini yazıyor:
  *"A `toContain` assertion passes just as happily on a branch wired backwards."*
- **CSS sözleşmesi** — `stabler/tests/test_design_layer_contract.py` (13 test) katmanı
  okuyup seçici yürüyüşü yapıyor; `TestScopeIsolation.test_every_rule_lives_under_the_stbl_ds_wrapper`
  (`:64-65`) bu deltanın kapsamını doğrulayan hazır test.
  **Çalıştırma biçimi `python3 -m unittest stabler.tests.test_design_layer_contract.TestScopeIsolation`** —
  sürüm 1'in yazdığı pytest node id'si çalışmıyor (§3.3).
- **↺ Yapısal kaynak guard'ı** — `stabler/tests/test_ci_bill_link_panel_source.py:90-96`:
  `test_skeleton_is_a_direct_thead_sibling_not_nested_in_a_tbody` ve
  `test_skeleton_used_not_a_bare_spinner`. **K4 ve K5 bunun genelleştirilmesidir**,
  yeni bir kalıp değil.

Aşağıdaki ölçütlerin hepsi bu üç yolla (veya düz `grep` ile) bugün yazılabilir.
Hiçbiri `@vue/test-utils` istemiyor.

### 8.1b · ↺ Hangi ölçüt hangi kapıyı bekliyor — sürüm 1'de yalnız K16'da yazılıydı

Sürüm 1 §8.1'de *"16 ölçütün hepsi bugün yazılabilir"* diyordu. **Doğru, ama
"yazılabilir" ile "geçilebilir" aynı şey değil** ve belge ikisini ayırmıyordu. Sonuç:
deltayı indiren uygulayıcı K1–K16'yı çalıştırır, çoğunu kırmızı görür ve neyden
sorumlu olduğunu belgeden okuyamaz. Üstelik §9-B8 K5'in istediği işi **açıkça Aşama
B'ye devrediyordu** — yani belge kendi devrettiği işi kendi teslimatının kabul ölçütü
sayıyordu.

| Kapı | Ölçütler | Ne zaman yeşil olmalı |
|---|---|---|
| **KAPI 1 — CSS deltası** (bu belgenin teslimatı) | **K13, K14, K15, K18** · K7'nin 1. koşulu · K12'nin 1. koşulu · K3'ün 1. koşulu | Delta commit'i `make check` yeşilken |
| **KAPI 2 — Aşama B ekran göçü** | K1, K2, K4, K5, K6, K8, K9, K10, K11, K16, K17 · K3'ün 2. koşulu · K7'nin 2. koşulu · K11'in 2-3. koşulu · K12'nin 2. koşulu | Ekran dilimi bittiğinde, ekran ekran |

**Bu ayrım bağlayıcıdır.** Kapı 1'in ölçütü kırmızıysa delta inmez. Kapı 2'nin ölçütü
kırmızıysa bu bir eksik değil, **henüz yapılmamış iş**tir.

### 8.2 · Ölçütler

| # | Ölçüt | Bugün (ölçüldü) | Kanıt yolu |
|---|---|---|---|
| **K1** | `grep -o 'tgm-' TenderMasterDrawer.vue \| wc -l` = **0** **VE** aynı dosyada `ds-drawer` ≥1 **VE** `ds-form-section` ≥1 **VE** `data-size="lg"` ≥1 | 46 / 0 / 0 / 0 | grep (kurul #1) |
| ↺ **K2** (Kapı 2) | Sıfır `ds-*` taşıyan **canlı** tender dosyası = **0** (kapsam `pages/tender/**`, 27 dosya; `.vue`/`.js`'ten çağrılmayan 4 hariç) **VE** `RfqPrint.vue` ile `BidPricing.vue`'da `TenderPage\|stbl-ds` ≥1 **VE** `TenderMasterDrawer.vue`'da `ds-` ≥1 **VE** **her canlı dosyada `ds-` sayısı ≥3** | 13 / 0 / 0 | grep (kurul #2). **↺ İki düzeltme:** (a) "ölü dört"ün `.vue` grafiğinde 0 çağrısı var ama **Python testlerinde 10 referansı** — nitelemesi §0.1'de düzeltildi; (b) sürüm 1'de kalan 11 dosya tek bir `class="ds-mono"` ile geçerdi, `≥3` koşulu onu kapatıyor |
| **K3** | Reddedilen altı ad **CSS'te 0 ve JS'te 0** (`ds-file-list\|ds-file-chip\|ds-file-name\|ds-table-wrap\|ds-field--check\|ds-blockers`) **VE** `ds-cut-del` canlı tüketici **≥1** | 0 / **0 tüketici** | grep. İkinci koşul olmadan bu ölçüt bugün de yeşil olurdu — jeton listesi kararının (D1) gerçekten uygulandığını o kanıtlıyor |
| **K4** | Tender'daki **her** `<SkeletonRows>`'un kaynaktaki en yakın açık ata etiketi `<table` **VE** iç içe/öksüz `<tbody>` = **0** | **16 site, 0 doğru** (8 iç içe + 8 öksüz) | kaynak ayrıştırma (spec kalıbı) |
| **K5** | `ds-skel-stack` tender'da ≥1 **VE** boşlukta `spinner-border` = **0** **VE** düğme içi `spinner-border` = **0** | 0 / **5** / **13** | grep + kaynak ayrıştırma. Beş boşluk sitesi adıyla: `TenderIntake:198`, `BidPricing:148`, `TenderDocumentsPanel:125`, `RfqPrint:61`, `PoControlBoard:556` |
| **K6** | `RfqList`'te hata dalının çizdiği seçici, boş dalınkiyle **AYNI OLAMAZ**: hata `alert-danger` + `data-region-state="error"`, boş `EmptyState` | ikisi de `EmptyState`; `catch` (41-44) yalnız toast atıyor | `v-if` zincirini çıkar ve **çalıştır** (kurul #5) |
| ↺ **K7** (1. koşul Kapı 1, 2. koşul Kapı 2) | CSS'te `.ds-btn:disabled` kuralı **VAR** **VE** `border-style: dashed` **VE** `border-color: var(--ds-tx3)` (`--ds-ln` **DEĞİL** — 1.19:1) **VE** blok D'nin dört kuralının hepsinde `:not(:disabled)` koruması **VAR** **VE** `ds-btn` taşıyan **her** devre dışı bağlamalı `<button>`'ın ya yanında bir `ds-field-hint` ya üstünde `:title`/`aria-describedby` **VAR** | 0 kural; **12 düğme / 10 dosya**, gerçek gerekçeli **3** | CSS grep + kaynak ayrıştırma (kurul #8). **↺ İki yeni koşul:** kenar rengi (D9, yoksa biçim kodu 1.19:1'de görünmez) ve blok D koruması (D8, yoksa silahlanmamış commit düğmesi devre dışı hâlini hiç almaz). **Kapsam `<button>` ile SINIRLIDIR ve bu bilerek yazılı** — 18 `<button>`-olmayan `ds-btn` taşıyıcısı §5.6b'de, B-20'de |
| ↺ **K8** (Kapı 2) | Ödül panelinde `ds-btn--primary` sayısı **`ds-form-section` başına ≤1** (R9: `-head` ve `-foot` yuvaları **birlikte** sayılır) **VE** `ds-form-section[data-commit]` içinde **=0** **VE** `Create purchase order` **≥1** | **ödül panelinde bugün 1 primary** (`:972`) / — / 1 | kaynak ayrıştırma (Ç21). **↺ "Bugün" hücresi düzeltildi:** sürüm 1 *"`panelMode==='both'`'ta iki primary aynı anda ekranda"* diyordu ve **ölçüm 1 veriyor**. Sayma birimi R9 ile netleştirildi — sürüm 1'de tanım B5, tablo ikisi, K8 B13 diyordu |
| **K9** | `Approve decision`'ın `:disabled` ifadesi bir **silahlama ref'i** okuyor **VE** o ref bir `<input type="checkbox">`'a `v-model` ile bağlı **VE** `useConfirm` ödül panelinde geçmiyor | okumuyor; `SourcingWorkspace`'te `confirm(` 0 | ifadeyi çıkar ve **çalıştır** (Ç2) |
| ↺ **K10** (Kapı 2) | Tender'da elle `class="…badge…bg-…"` = **0** **VE** **`class="badge"` = 0** **VE** **sayfa-yerel rozet fabrikası = 0** (`headerClass\|badgeClass\|stBadge\|riskBadge\|fxBadge\|badgeMeta`, `getStatusBadgeClass` **hariç tutularak** sayılır) **VE** `<StatusBadge` ≥1 **VE** `STATUS_MAP`'te beş yeni anahtar var | **45 site / 10 dosya** · **19 site** · **26 site + 4 fabrika** · **0** · **0/5** | grep (Ç22, Ç23). **↺ Sürüm 1'in iki grep'i de yeşilken 15 elle Tabler rengi ve 4 fabrika hayatta kalabiliyordu**: depo kalıbı `class="badge"` + ayrı `:class` bağlaması, ve iki grep de tek bir `class=` özniteliği varsayıyordu. Üçüncü ve dördüncü koşul o deliği kapatıyor |
| ↺ **K11** (Kapı 2) | `ds-form-grid[data-cols="3"]` tender'da = **0** **VE** tender'da `ds-field-req` **≥1** **VE** her `ds-field-req` `aria-hidden="true"` taşıyor **VE** kardeş kontrolde `aria-required\|required` var | 0 ✔ · **tender'da `ds-field-req` = 0** · — · — | grep + kaynak ayrıştırma (Ç11, Ç14). **↺ Sürüm 1'de bu ölçüt BOŞTU: `git commit --allow-empty` onu geçerdi.** `ds-field-req` tender'da 0 olduğu için "her X şunu taşır" biçimindeki iki koşul boş küme üzerinde doğruydu, üçüncüsü de bugün doğruydu. `≥1` koşulu ölçütü gerçek yapıyor. Uygulama genelindeki iki mevcut ihlal (`Login.vue:178`, `:200` — yıldızda `aria-hidden` yok, `<input>`'ta `aria-required` da `required` da yok, `<form novalidate>`) **kapsam dışıdır ve bu yazılı**: bu tur tender'ı kapatıyor, `Login` **B-22**'de |
| **K12** | CSS'te `.ds-field`'in `display: block`'u **VAR** **VE** tender'da `ds-field` bir `ds-form-grid`/`ds-actions` **dışında** ≥1 yerde kullanılıyor | kural yok; `ds-field` tender'da 1 dosyada, o da `ds-actions` içinde | CSS grep + kaynak ayrıştırma (Ç12). İkinci koşul, kuralın gerçekten gereksizleştiğini kanıtlar |
| **K13** (Kapı 1) | `--ds-font-body` CSS'te = **0** **VE** `.btn-primary:hover` ile `.ds-btn--primary:hover` **aynı** değeri taşıyor | 2 kullanım / 0 tanım; `#1b5aa6` ≠ `#1b5ca8` | CSS grep (T1, T3) |
| ↺ **K14** (Kapı 1) | Delta + katman birleşiminde `.stbl-ds` dışına kaçan seçici = **0** **VE** kullanılan her `--ds-*` token tanımlı **VE** `--ds-ok-tx` ile `--ds-info-tx` **tanımlı** | 0 / 0 / **0 tanım** (blok L bunları getiriyor) | `python3 -m unittest stabler.tests.test_design_layer_contract.TestScopeIsolation` + token karşılaştırma. **↺ Çalıştırma biçimi düzeltildi** — sürüm 1'in pytest node id'si `unittest` süitinde geçersiz (§3.3) |
| **K15** (Kapı 1) | Değişen dosyaların hepsi `stabler/` içinde **VE** doctype JSON 0 **VE** yeni patch 0 | ✔ bugün doğru — **ihlal edilebilir** olduğu için ölçüt | `git diff --name-only` (ADR-307, kurul #7) |
| **K16** (Kapı 2) | `SourcingWorkspace`'te `table-responsive` ≥1 **VE** `PoControlBoard`'dan `tender-sourcing\|tender-rfq` bağlantısı ≥1 | **0** / **0** | grep (kurul #3, #4) |
| **K17** ← YENİ (Kapı 2) | **Manda 8'in kapısı:** tender'ın liste ekranlarında `ListToolbar` kullanan dosya sayısı **≥8** **VE** elle kurulmuş filtre/arama şeridi = **0** | **1 dosya** (`rfq/RfqList.vue`); 8 ekran kendi filtresini elle kurmuş | grep. **↺ Sürüm 1'de manda 8'in SIFIR ölçütü vardı** ve `ListToolbar` kapalı dağarcıkta bile geçmiyordu — mandayla zorunlu kılınan tek bileşen listelenmemişti |
| **K18** ← YENİ (Kapı 1) | **Manda 3'ün kapısı:** tender'da çıplak `<input type="number">` = **0** **VE** `MoneyInput\|PercentInput` ≥1 — **VEYA** §10.4'ün cevabı `docs/` altında yazılı bir kararla kapatılmış | **10 çıplak `<input type="number">`** | grep. **↺ Sürüm 1'de manda 3'ün SIFIR ölçütü vardı**: 10 ölçülmüş ihlal ve hiçbir kapı. §10.4 cevaplanmadan bu ölçüt Kapı 1'de **bloklayıcıdır** — "cevapsız" da bir ihlaldir |
| **K19** ← YENİ (Kapı 1) | **Manda 1'in korunması:** `pages/tender` içinde `/app/` veya `window.open` = **0** | 0 ✔ — **ihlal edilebilir** olduğu için ölçüt | grep. Sürüm 1'de bu manda boş geçiyordu ve hiçbir ölçüt onu korumuyordu |

### 8.3 · Bu ölçütlerin neden "hiçbir şey yapmayan bir değişiklikle" sağlanamayacağı

| Hile | Hangi ölçüt engelliyor |
|---|---|
| `tgm-*` sınıflarını silip bırakmak | K1'in 2., 3. ve 4. koşulu — stilsiz çekmece geçmez |
| Ölü dört dosyaya `ds-*` serpmek | K2 kapsamı **canlı** dosyalarla sınırlı, ve dördü adıyla dışarıda |
| Yeni sınıf yazmayıp "boşluk yok" demek | K3'ün ikinci koşulu (`ds-cut-del` ≥1 tüketici) kararın uygulandığını istiyor |
| `SkeletonRows`'u olduğu yerde bırakıp `:cols` düzeltmek | K4 **ata etiketini** ölçüyor, prop'u değil |
| Spinner'ı `v-show` ile gizlemek | K5 kaynakta `spinner-border` dizesini sayıyor |
| `catch`'e ikinci bir toast eklemek | K6 **eleman seçicisini** karşılaştırıyor; toast bir eleman değil |
| `:disabled` kuralını yazıp sebebi yazmamak | K7'nin ikinci koşulu **12 düğmenin hepsini** geziyor |
| `Approve`'a `confirm()` koymak | K9 silahlama ref'inin **checkbox'a bağlı** olmasını istiyor |
| `StatusBadge` import edip kullanmamak | K10 elle `badge bg-*` sayısının **0** olmasını da istiyor |
| Kuralı belgeye yazıp CSS'i değiştirmemek | K12 hem CSS bildirimini hem gerçek kullanımı istiyor |
| ↺ `class="badge bg-green"` yerine `class="badge" :class="'bg-green'"` yazmak | **K10'un 2. ve 3. koşulu** — sürüm 1'in iki grep'i bu kalıbın **15 sitesini** görmüyordu |
| ↺ Tender'da hiç `ds-field-req` yazmayıp K11'i boşta geçmek | **K11'in yeni `≥1` koşulu** — sürüm 1'de `git commit --allow-empty` K11'i geçerdi |
| ↺ Canlı dosyaya tek bir `class="ds-mono"` serpip K2'yi geçmek | **K2'nin yeni `≥3` koşulu** |
| ↺ `:disabled` kuralını yazıp kenarı `--ds-ln`'de bırakmak | **K7'nin yeni `border-color` koşulu** — 1.19:1'de biçim kodu yok |
| ↺ Blok D'yi korumasız bırakıp silahlanmamış commit düğmesini kırmızı çizmek | **K7'nin yeni `:not(:disabled)` koşulu** |
| ↺ 10 çıplak `<input type="number">`'ı bırakıp manda 3'ü sessizce geçmek | **K18** — sürüm 1'de paranın hiç kapısı yoktu |
| ↺ Sekiz ekranın elle filtresini bırakıp manda 8'i sessizce geçmek | **K17** — sürüm 1'de `ListToolbar` dağarcıkta bile yoktu |

---

## 9 · AŞAMA B'YE DEVREDİLENLER — kapatılmamış her şey, adıyla

| # | Devredilen | Neden Aşama A'da kapanmadı | İlk iş |
|---|---|---|---|
| **B-1** | **`table-responsive` göçü** — `SourcingWorkspace` (9 sütun), `DirectorBoard` (9), `DeclarantQueue` (9), `LogistBoard` (8) | Bu bir bileşen değil bir **göç maddesi**; `ds-table-wrap` reddedildi (Ç3) | `DirectorBoard.vue:327 .board-scroll` → `table-responsive` (T6) |
| **B-2** | **`ListToolbar` göçü** — 8 ekran | Sözlük eksikliği değil **kullanım** eksikliği; köprü zaten kapsıyor | manda 8'in gerçekten uygulanması |
| **B-3** | **`ds-link`** — 1 yeni sınıf | Gerekçesi ölçülü (`TenderOverview.vue:243-253` kendi yorumunda boşluğu yazıyor) ama bu turun kapsamı beş alandı | `.ov-link`'in merkezi karşılığı |
| **B-4** | **`ds-tabs` / `ds-tab`** — 1 yeni çift | Beş eksik sözlüğün içindeki **tek gerçek yeni bileşen**; `TenderWorkspaceTabs.vue` canlı ve 0 `ds-*` | `aria-selected` kalıbı, `ds-seg`'in kardeşi |
| **B-5** | **Salt-okuma form dili** — form-içi "yazma yetkin yok" bildirimi | Sayfa düzeyi kapandı (§6.6), form/alan düzeyi hiçbir şartnamede yok | `durum`'un yetkisiz deseninin küçük varyantı |
| **B-6** | **39+ belgesiz-ama-canlı `ds-*` sınıfı** (96'nın çoğu) | Kayıt işi, tasarım işi değil | Ekran şartnamelerinde belgelenir, icat edilmez |
| **B-7** | **`make guards` kuralları** — köprü `.btn-*` yasağı, elle `badge bg-*` yasağı | Guard **dönüşümden sonra** eklenir; önce eklenirse `make check` kırmızıya döner ve hiçbir şey ilerlemez. Ayrıca §10.2'nin onayını bekliyor | Göç bittikten sonra, tek commit |
| **B-8** | **13 düğme içi spinner + 5 boşluk spinner'ı** | Ekran ekran dokunuş | K5 |
| **B-9** | **`STATUS_MAP`'e beş anahtar** — `Tender Customs Lane`, `Tender Logistics Lane`, `Tender PO Mark`, `Supplier Quotation`, `Tender Sourcing Decision` | Hepsi `composables/status.js` içinde → ADR-307 güvenli, ama ekran dilimiyle birlikte lander | K10 |
| **B-10** | **`ds-seg`, `ds-stepper`, `ds-drawer-close`, `ds-cut-del`** `:disabled` kuralları | Dördü de bugün devre dışı bağlaması **taşımıyor** (ölçüldü) — kanıtsız kural yazılmaz | İhtiyaç doğduğunda |
| **B-11** | **`ds-drawer-foot` ad borcu** | Seçici serbest (css:669), yani panelde kullanmak doğru; ad yanıltıcı. Yeniden adlandırmak 6 dosyanın işaretlemesine dokunur | §10.6 |
| **B-12** | **`ds-panel > ds-form-body` sarmalayıcısı** — çift çerçeve tuzağı | `ds-panel` ve `ds-form-section` ikisi de `border: 1px solid var(--ds-ln)`; ödül panelinin üç bölümü tam bu tuzağın içinde. **Render'da görülmedi** → karara bağlanmadı | Aşama B'nin **ilk yerleşim sorusu** |
| **B-13** | **Sayfasız tablo davranışı** — 200+ satırda ne olur | Hiçbir şartname somut bir "N satırda çöküyor" ölçümü getirmedi; sanal kaydırma icat **edilmedi** | §10.1 |
| **B-14** | **`ds-chip` crit/today biçim ayrımı** | Ölçüldü: dört `data-tone` için **birebir aynı** 7×7 kare; `ds-sev`'de `crit` ve `today` **ikisi de dolu kare**. Gri tonlamada ayrımı yalnız **kelime** taşıyor | Ekranlarda crit ve today yan yana çıkabiliyorsa tasarım **kelimeye** güvenir |
| **B-15** | **4 çağrılmayan dosyanın kaderi** | Silmek mi bırakmak mı — ayrı karar, bu turun kapsamı değil. **↺ Maliyeti artık ölçülü:** üçünü de üç Python test modülü okuyor ve üçü de `make test` kapısında | §10.5 |
| **B-16** ← YENİ | **Üç `form-switch`'in `form-check`'e göçü** — `SourcingWorkspace:928`, `TenderDocuments:70`, `PoControlBoard:708` | Yasak yürürlükte ama göç yoktu; delta onları D11 ile kapsam dışında bıraktı. Bir kontrolü yasaklayıp aynı anda bozmak kabul edilemez | Ekran ekran; üçü de §5.5'te yeniden tasarlanan ekranlarda |
| **B-17** ← YENİ | **`EmptyState`'in `stabler-empty-*` lehçesi** — 8 sınıf, `<style scoped>`, katmanda 0 kural, **iki `border-radius: 50%`** (`:81`, `:111`) | Dördüncü lehçe. `tgm-*`'e sorulan uzlaştırma sorusu buna hiç sorulmadı, çünkü sürüm 1 *"üç lehçe"* sayıyordu. **Uygulama geneli (159 kullanım)** → tender turunun kapsamı değil (D13) | `tgm-*` tablosunun (§2) aynısı, 8 satır |
| **B-18** ← YENİ | **`--ds-soon-tx`** | `soon` kontrastı geçiyor (çip 4.72, sev 5.30) ama metinde **dolgu** token'ı kullanıyor — brief §5.2'nin token ayrımı kuralının ihlali. Görsel değişiklik üretmeyen bir yeniden adlandırma bu deltanın işi değil (D10) | `--ds-ok-tx`/`--ds-info-tx` ile aynı kalıp |
| **B-19** ← YENİ | **75 çeviri satırı** — 15 yeni anahtar × 5 katalog | Bu belge onları **yazdı** ve hiçbir listeye koymamıştı (§4.3b). `stabler-i18n` skill'i bunu bir kapı sayıyor | Ekran dilimi ile birlikte, harvest → 5 CSV |
| **B-20** ← YENİ | **`<button>` olmayan 18 `ds-btn` taşıyıcısı** — devre dışılık `.disabled` **sınıfı** ile yazılıyor, delta ona kural yazmıyor, K7 kapsamıyor | Bir bağlantının devre dışı edilmesi CSS değil **işaretleme** sorunudur (§5.6b) | Ekran kararı: bağlantıyı çizme, ya da `<button>`'a çevir |
| **B-21** ← YENİ | **İki yükleme animasyonu** — `placeholder-glow` (CDN, opaklık nabzı) ↔ `ds-shimmer` (katman, kayan gradyan) | `SkeletonRows` 79 dosya / 96 site; kökünü değiştirmek uygulamanın en çok kullanılan bileşenini tek commit'te değiştirmek olur | Köprüde `.stbl-ds .placeholder-glow .placeholder` — bileşene dokunmadan |
| **B-22** ← YENİ | **`Login.vue:178/200`'ün `ds-field-req` ihlali** | Yıldızda `aria-hidden` yok, `<input>`'ta `aria-required`/`required` yok. Tender dışı → bu turun kapsamı değil, ama K11 uygulama geneline çekilirse **bugün kırmızı** | 2 öznitelik |
| **B-23** ← YENİ | **`ds-cut-del`'in dokunma hedefi** | Ölçüldü: css:785-788 `width: 30px` yazıyor, **`height`/`min-height` YOK**; `line-height: 1` + 15px + UA dolgusu ≈ **30 × ~17px**, WCAG 2.5.8'in 24×24 asgarisinin **altında**. §0.3-D1 bedeli *"34px hedef → 30px"* diye kabul etmişti — **yanlış eksende**: gerileme genişlikte değil **yükseklikte**, ve daha ağır | `min-height: 30px` — bir bildirim, ama D1'in bedelini yeniden açtığı için ayrı karar |

---

## 10 · ZAFAR'A — bu turda karara bağlanamayanlar

↺ **Dokuzu da** karar değil; **dokuzu da bir depo kuralının, bir kurul kararının veya
bir mimari sınırın değişmesini istiyor**, ve bir şartname bunları kendi başına ezemez
(CLAUDE.md: *"On conflict, this file wins"*). Sürüm 1'de yedi vardı; çürütme turu
**10.9'u** (köprünün iki bileşene ulaşmaması) ekledi, ve **10.5** ile **10.8(b)**
artık ölçülmüş maliyetleriyle soruluyor.

### ✔ Zafar'ın kararları — 2026-09-01

Üçü kapandı, altısı açık. Kapananlar aşağıda kendi maddelerinde de işaretli.

| # | Karar | Durum |
|---|---|---|
| **10.5** | Dört çağrılmayan dosya **siliniyor**, üç test modülü birlikte düzeltiliyor | ✔ uygulandı — `1eb780a` |
| **10.8(b)** | **Şerit korunuyor**: göç eden tablo `class="ds-table table"` yazar, `ds-table` tek başına değil | ✔ kayda geçti — aşağıda ve §1.2 |
| **10.9** | Seçenek **(a)**: `inheritAttrs: false` + `v-bind="$attrs"` | ✔ uygulandı — `f267e6d` |
| **10.2** | Buton mandası değişsin | ✔ değişti — `dbafeeb`; **ama premisi düştü**, aşağıda |
| **10.8(a)** | Manda 9'un lafzı düzeltilsin | ✔ değişti — `dbafeeb` |
| **10.4** | Seçenek **(a)**: yüzde kapsamda, kendi şekliyle | ✔ değişti — `dbafeeb`; **`ds-input` DEĞİL**, aşağıda |

**10.9 lafzından bir sapma var ve ölçülmüştür.** Seçenek (a) yazıldığı gibi —
"her iki bileşene `v-bind="$attrs"`" — `DateInput`'ta **28 çağrı yerinin yerleşimini
bozardı**: 202 çağrının 28'i bir `style` geçiriyor ve hepsi **grubu** boyutlayan bir
genişlik (`width: 120px`). `MoneyInput`'ta ise 135 çağrının 5'i öznitelik geçiriyor
ve hepsi **kontrole** ait bir `class` (`is-invalid`, `form-control-sm`,
`ds-input so-rate`). Bu yüzden uygulanan biçim: `MoneyInput` her şeyi input'a verir;
`DateInput` `class` ve `style`'ı sarmalayıcıda tutar, kalan her şeyi
(`aria-invalid`, `aria-describedby`, `data-*`) input'a verir. Asimetri çağrı
yerlerinden geliyor, üsluptan değil. Sözleşme
`stabler/public/js/tests/fieldErrorReachesTheControl.spec.js` ile pinli — ve **olumlu**
yazılı: "öteki bileşenin şeklinin yokluğu" biçiminde yazılan iki kriter hiçbir şey
yazılmadan yeşildi, düzeltildi.

**10.1 · Sayfasız tablo — Aşama B'nin liste ekranlarını etkiliyor.**
Brief §5.3 sunucu sayfalaması olmadığını söylüyor (`limit_page_length=0`); beş
şartnamenin **hiçbiri** bu kısıtı ele almadı (`grep -ni 'sayfala\|pagination\|limit_page_length'`
→ **0 eşleşme**). Önerim: tablo sunucunun döndürdüğü her satırı çizer, istemci sayfalaması
da **eklenmez** (eksik veri yanılsaması yaratır), ölçek kontrolü **filtre**dir. Ama
sentetik küme 13 lot / 9 tedarikçi ile küçük; gerçek üretim verisi 200+ RFQ satırı
üretirse hiçbir şartname bir davranış tanımlamadı. **Onay gerek.**

**10.2 · ✔ KARAR: KURAL DEĞİŞTİ (`dbafeeb`) — ama ~~Aşama B'yi blokluyordu~~ BLOKLAMIYORDU.**
Kural bugün *"Secondary/neutral actions **must use** `.btn-outline-secondary` or
`.btn-ghost-secondary`"* diyor. `.stbl-ds` altında doğrusu `.ds-btn`'dir. `aksiyon`'un
önerdiği guard regex'i (`btn-(success|warning|danger|secondary|outline-[a-z]+|ghost-[a-z]+)`)
**deponun kendi mandasının zorunlu kıldığı iki sınıfı yakalar** ve `make check`'i
kırmızıya düşürür. Kural değişmeden yasak yürürlüğe giremez, guard yazılamaz (B-7).

**↺ BU MADDENİN PREMİSİ YANLIŞTI, ve iki yerinden.** Karar uygulanırken ölçüldü:

1. **Manda `.ds-btn`'i yasaklamıyor, çünkü `.stbl-ds` altında ikisi de doğru.** Köprü
   katmanı `.btn`, `.btn-sm`, `.btn-primary`, `.btn-icon`, `.btn-ghost-*` ve `.btn-link`'i
   `.stbl-ds` altında **zaten yeniden giydiriyor** (`css:950-974`) — köprünün kendi
   doktrininin (`css:894-908`) tam olarak yaptığı şey bu. Bir ekranı taşımak buton
   yazmayı **gerektirmiyor**. Yani mandanın Aşama B'yi bloklaması diye bir şey yoktu.
2. **Ve göç ters yönde bir gerileme olurdu.** Chrome + sabitlenmiş Tabler ile ölçüldü
   (2026-09-01): renk, kenar ve köşe **birebir aynı** (`#fff`/`#c7ccd4`, `#206bc4`, radius 0);
   fark yükseklik (44 ↔ 40) ve font (13.5/600 ↔ 14/800) — ve **`:disabled`**:

   | | `:disabled` |
   |---|---|
   | `btn btn-outline-secondary` (köprülü) | `opacity: .4`, `pointer-events: none` |
   | `ds-btn` | `opacity: 1`, `pointer-events: auto` — **etkin görünür ve tıklamayı alır** |

   Kurul kararının ACCEPTANCE #8'i bu yüzden var ve delta bunu zaten yazmış
   (`delta.css:67-68`) — **katmanda hâlâ yok.**

**Kural bu yüzden bir yasak değil, bir yer tarifi oldu:** hangi sözcük dağarcığının nerede
geçerli olduğunu söylüyor, **paylaşılan bileşen** durumunu adlandırıyor (`ListToolbar`
`btn btn-sm btn-primary`'yi sabit yazıyor — `ListToolbar.vue:63` — ve manda 8 onu her liste
sayfasında zorunlu kılıyor; 46 tüketicisi var, çoğu `.stbl-ds` dışında), ve devre dışı
edilebilen bir butonda `ds-btn`'i yasaklıyor. **Guard yazılmadı** ve nedeni yazılı: yazılabilir
(`type="date"` guard'ı tam o şekil, `Makefile:463-469`) ama bugün kapsamdaki ekranlar iki
dağarcığı karıştırdığı için kırmızı olurdu.

**10.3 · `10-frontend.md` "Currency display" — karşılaştırma tablosu dilimini blokluyor.**
Kural taban/USD çevrimi yasaklıyor ve **iki belgelenmiş istisnası** var (Sales Order
altbilgisi, Journal Entry kalıntısı). Karşılaştırma tablosunun üç taban-kuru sütunu
(`base_total`, `landed_charges_total`, `base_landed_total`, `SourcingWorkspace.vue:611-622`)
**üçüncü ve belgelenmemiş** bir istisna — ve brief §5.3 onu **zorunlu** kılıyor.
Mevcut ikisinin biçiminde yazılmadan o dilim başlamamalı.

**10.4 · ✔ KARAR: (a) — ama adlandırdığı sınıfla DEĞİL (`dbafeeb`).**
Kural *"amounts, rates, or balances"* diyor. Tender'da **10 çıplak `<input type="number">`**
var ve çoğu yüzde (`margin_pct`, `vat_pct`, `duty_pct`, `penalty_pct_per_day`).
`MoneyInput`'un ondalık mantığı bir yüzdeye uymuyor, ve envanterde `PercentInput` yok.
İki kabul edilebilir cevap: (a) `%` bir "rate" sayılır ve `ds-input` + `input-group-text`
("%") **resmî bir form-grameri satırı** olur; (b) yüzde alanları kısıt dışında bırakılır
ve bu **yazılı** olur. Sessiz kalmak kabul edilemez.

**✔ Zafar: (a).** Kapsama alındı — **ama `ds-input` ile değil, `form-control` ile.** (a)'nın
lafzı ölçülerek çürütüldü: Chrome + sabitlenmiş Tabler (2026-09-01), `.stbl-ds` içinde

```
.input-group > input.ds-input      → flex: 0 1 auto,  width:100%  → "%" ALT SATIRA düşer, grup 80px
.input-group > input.form-control  → flex: 1 1 auto               → aynı satır, grup 44px
```

çünkü Tabler'ın esneklik sözleşmesi yalnız `.form-control`, `.form-select` ve `.form-floating`
çocuklarını tanıyor; `ds-input` o listede yok ve `css:437`'nin `width:100%`'ü satırı dolduruyor.
Katmanın kendi yazdığı `.stbl-ds .input-group > .form-control` sıfırlaması (`css:942-944`) da
aynı şeyi söylüyor — grubun alan yuvası **bilerek** bir Bootstrap sınıfı.

**Onaylanan şekil:** `.input-group` + `.form-control` + `<span class="input-group-text">%</span>`.
İki canlı öncülü var: `BidPricing.vue:170-173` (çıplak `<input type="number">`) ve
`NewRemittance.vue:710-720` (`MoneyInput` + `hide-currency` + `:max-fraction-digits="4"`, ki o da
aynı `.form-control`'ü render eder ve yerelleştirilmiş gruplama ekler). `PercentInput` icat
**edilmedi**.

**Ve kural guard ile çelişmiyor artık:** `make guards`'ın para muafiyeti bir *ad şekli*
(`_pct|_percent|percentage`, `Makefile:508`), sözleşme değil — `vat_rate` adlı bir yüzde
"MoneyInput kullan" hatası alır. Bu yüzden adlandırma kuralın parçası oldu.

**Ölçüm ayrıca bir itirazı düşürdü:** `<input type="number">`'ın virgüllü ondalığı yiyeceğinden
şüphelenmiştim; Chrome/macOS, `lang="ru"`, "12,5" → `value="12.5"`, `badInput=false`. Başka
tarayıcı doğrulanmadı.

**10.5 · ✔ KARAR: SİLİNDİ (`1eb780a`). ↺ Dört çağrılmayan dosya, ve maliyeti — sürüm 1 soruyu maliyetsiz soruyordu.**
`TenderCrmWrapper`, `TenderExecutionFlow`, `TenderExecutiveKpis`, `TenderTrendChart` —
dördünün de `.vue`/`.js` grafiğinde **0 çağrısı var** (doğrulandı). Ama sürüm 1'in
*"0 dış referans"* ölçümü `--include='*.vue' --include='*.js'` kapsamıyla yapılmıştı.
**Python testleri kapsamın dışında kalmıştı:**

```
stabler/tests/test_tender_dashboard_i18n.py    :11, :18, :19, :57
stabler/tests/test_tender_dashboard_spa.py     :17, :18, :19
stabler/tests/test_tender_master_board_spa.py  :4, :20, :37
                                               → 10 referans / 3 modül
```

**Üçü de `.github/frappe-free-tests.txt` içinde** (satır 117, 118, 122) — yani
`make test`, yani `make check`, yani **push kapısı**. Ve iddia sadece "referans var"
değil: `test_tender_master_board_spa.py:37` →
`self.assertTrue(bool(source), "TenderCrmWrapper.vue does not exist")` ve `:38` →
`self.assertIn("<TenderCrm />", source)`. **Dosya silinemez.**

**Ölçülmüş cevap:** dördünden herhangi birini silmek **üç test modülünü birlikte
değiştirmeyi** gerektirir. Soru bu maliyetle sorulur: siliniyorlar mı (ve üç test
modülü düzeltiliyor mu), yoksa `TenderTrendChart` bir ekrana geri mi bağlanıyor?
Cevaba göre grafik sözlüğü ya tamamen kapsam dışı kalır ya da küçük bir varyant
gerekir. **Bu turun ölçemeyeceği tek sözlük sorusu bu.**

**✔ Zafar: silme.** Dördü de silindi ve üç test modülü birlikte düzeltildi (`1eb780a`).
Testler "dosya var" iddiasından davranış iddiasına çevrildi — sarmalayıcının silinmesi
rotayı kaydırmıyor (`test_crm_route_reaches_tender_crm_with_no_wrapper_level`), üç pano
bileşeni gerçekten yok (`test_unreachable_dashboard_components_are_deleted`). i18n
modülündeki `COMPONENT_LABEL_KEYS` **testiyle birlikte silindi**: tek girdisi kalkınca
sıfır kez dönen ve yine de yeşil kalan bir döngü olurdu. **Grafik sözlüğü kapsam
dışıdır** — `TenderTrendChart` geri bağlanmadı.

**10.6 · Mimari, çözülmedi: z-index.**
`.ds-drawer` z-**41** / `.ds-drawer-backdrop` z-**40** (css:645, 649) ↔ `.tgm-drawer`
z-**1050** / `.modal-backdrop` z-**1040** (`TenderMasterDrawer.vue`, aynı `<style scoped>` —
yani bugünkü değer **kasıtlı**). `SourcingWorkspace` aynı `<TenderPage>` içinde hem
`QuotationEntryDrawer`'ı (`ds-drawer`, 41) hem `LandedChargesEditor`'ı (çıplak Bootstrap
`.modal`) çiziyor. `LandedChargesEditor`'ın gerçek z-index'i CDN'den geliyor →
**bu depodan ölçülemiyor.**

**↺ Sürüm 1'in iki örneği tuzağı GÖSTERMİYORDU** (kural ayakta, kanıtı değildi):
- `MultiSelectPicker.vue:135`'in modal'ı `<Teleport to="body">` (`:134`) **içinde** →
  `ds-drawer`'ın alt ağacında değil, `<body>` çocuğu. Kardeş olarak render edilir ve
  Bootstrap `.modal`'ın z'si onu üstte tutar — yani **istenen davranış.**
- `LandedChargesEditor` `SourcingWorkspace.vue:1022`'de, `QuotationEntryDrawer` `:1007`'de
  — **kardeşler**, iç içe değil.

Yani depoda bugün **bir `ds-drawer` alt ağacında render edilen `.modal` ölçülemedi**.
Kural yazılabilir ve yazılıyor; ama *"bugün bu tuzağa düşen iki akış var"* iddiası
ölçülmemişti ve **düştü**. (`TenderMasterDrawer`'ın z-1040/1050 ölçümü doğru: `:661`
ve `:668`, aynı `<style scoped>` içinde.)
Tasarımın yaptığı iki şey: sayıyı **tek yere** indirmek (göç sonrası
`grep -c 'z-index' TenderMasterDrawer.vue` → 0), ve **hiçbir akışın bir `ds-drawer`
içinden bir Bootstrap `.modal` açmamasını** kural yapmak. Çözümü mühendislik verir.

**10.7 · Kurul kararında düzeltilmesi gereken iki cümle.**
(a) **ADR-306:** *"Kalıp repoda zaten var (76 spec'in 17'si)"* — **yanlış.** 17 dosya
`@vue/test-utils`'i **anıyor**, **0'ı** `mount(` çağırıyor. ACCEPTANCE #6 ve NOT DECIDED
zaten doğrusunu yazıyor; ADR-306'nın gövdesi ve "Keşif ajanlarının hataları" listesindeki
*"76'nın 17'si mount ediyor"* satırı onlarla çelişiyor.
(b) **ADR-302/303:** *"Bugün bilinen tek gerçek boşluk dosya-eki çipi"* — Ç1/D1 ile
**düştü**: `ds-table` + `ds-cut-del` + `FileSlot` o işi yapıyor, ve `ds-file-*` yazılmıyor.

**10.8 · Manda 9'un lafzı, ve `ds-table`'ın şeritsizliği.** *(a) ve (b) ✔ karara bağlandı.*
(a) Manda 9 *"Place animated skeleton rows inside the table body"* diyor. Ama
`SkeletonRows`'un kökü **zaten** bir `<tbody>` — lafzı harfiyen uygulamak **iç içe
`<tbody>`** üretiyor, ve bugünkü 8 site tam bunu yapmış. Doğru okuma "tablo gövdesinin
**yerine**"dir; kuralın metni bunu söyleyecek şekilde düzeltilmeli.

**✔ Zafar: metin düzeltilsin.** Düzeltildi (`dbafeeb`). Kapsam ölçüldü: **96 çağrı yerinin
16'sı** iç içe (belgedeki 8, tender kapsamıydı ve doğruydu). Ama düzeltme **daha katı
yazılamazdı**: "tablo değilse `SkeletonRows` kullanma" diyen bir kural `make check`'i kırmızıya
düşürürdü — `test_tender_desk_spa.py:23` `OperationsDesk.vue`'da `SkeletonRows`'u **şart
koşuyor**, ve o dosyadaki iki kullanımın ikisi de panel içinde, tablosuz. Kuralı izleyen biri
bileşeni silseydi hem o iddia hem `no-unused-vars` düşerdi. Bu yüzden tablosuz hâl **yasak
değil, açık bir borç** olarak yazıldı; `ds-skel-stack` onun için delta'da hazır
(`delta.css:156`) ve iddia işaretleme ile birlikte taşınacak.
(b) Manda 2'nin şerit kuralı `.table` sınıfını şart koşuyor
(`stabler.css:145`, `.table:not(.table-no-stripe)`) ve `ds-table` onu taşımıyor →
**`ds-table` şeritsiz.** ↺ **Sürüm 1 bu maddeyi sayısız yazıyordu; ölçüldü: tender'da
14 şeritli tablo** (`table card-table` ×7, `table table-vcenter card-table` ×4,
`table card-table align-middle` ×2, `table table-sm align-middle mb-0` ×1; ayrıca
5 tablo zaten `table-no-stripe` ile şeritten çıkmış). `table card-table → ds-table`
göçü, 9 sütunlu tablolarda satır takibinin tek görsel yardımını **on dört yerde**
kaldırıyor. Manda "elle `table-striped` ekleme" diyor, "her tablo şeritli olsun"
demiyor — yani **ihlal değil, ama ölçülü bir kayıp**. `tr[data-sev]` yalnız
vurgulanan satırları izletiyor, hepsini değil.

**↺ Ve sürüm 1 bir çıkış yolu bırakmamıştı:** §1.2 kapalı dağarcığı `.table`/`card-table`'ı
içermiyordu, yani `class="ds-table table"` de dağarcık dışı kalıyordu — bir ekran
şeridini geri isteyemezdi. §1.2'ye **`class="ds-table table"` kaçış satırı eklendi**;
`.table:not(.table-no-stripe)` kuralı o bileşimde çalışır. Zafar'ın kararı **hangi
varsayılan** olacağıdır: 14 tablo şeridini korusun mu (bileşim yazılır), yoksa
`ds-table`'ın sessizliği mi kazansın (şerit gider ve bu kayıt edilir).

**✔ Zafar: şerit korunsun.** Göç eden her tablonun varsayılanı `class="ds-table table"`
bileşimidir; `ds-table` tek başına yalnız `table-no-stripe` ile bilerek şeritten
çıkarılmış 5 tablo için yazılır. Aşama B'nin her tablo satırı bu bileşimle başlar, ve
9 sütunlu karşılaştırma tablosu satır takibinin tek görsel yardımını korur. Bu bir
kural değil bir **varsayılan**: bir ekran şeritten çıkmak isterse `table-no-stripe`
zaten var ve gerekçesini yazar.

**10.9 · ✔ KARAR: (a) UYGULANDI (`f267e6d`). ↺ `[aria-invalid]` köprüsü manda 3 ve manda 4'ün bileşenlerine ULAŞMIYORDU.**
Blok J'nin `aria-invalid` köprüsü doğru bir boşluğu kapatıyor ama **iki bileşene hiç
varmıyor**, ve sürüm 1 bunu ne §10'a ne §11'e yazmıştı. Ölçüldü:

```
DateInput.vue:107-109   <div class="input-group">        ← TEK kök, HER ZAMAN
                            <input :class="textClass">  ← .form-control BURADA
        grep -n 'inheritAttrs|defineOptions'  → 0 eşleşme
MoneyInput.vue:166      <input v-if="hideCurrency || (!currency && !isUZS)">  ← düşüş ÇALIŞIR
MoneyInput.vue:181      <div v-else class="input-group">                      ← düşüş DİV'E gider
        grep -n 'inheritAttrs'  → 0
```

`inheritAttrs: false` yok ve kök bir `<div>` → Vue'nun öznitelik düşüşü `aria-invalid`'i
**sarmalayıcı `<div>`'e** koyar. `.stbl-ds .form-control[aria-invalid="true"]`
**`DateInput`'ta hiçbir zaman eşleşmez**; `MoneyInput`'ta yalnız "para birimi
gösterilmiyor" dalında eşleşir — yani karşılaştırma tablosu ve teklif formu gibi
**para birimi taşıyan alanlarda kural ölü**.

**Belge bu analizi bir bölüm önce, aynı yöntemle, doğru yapıyordu:** §4.1(a) tablosu
`Typeahead` ve `MultiSelectPicker` için tam olarak *"kök `<div>`, `inheritAttrs` beyanı
0 → `id` `<div>`'e düşer"* diyor. Yöntem elindeydi, `id` için uygulanmıştı,
`aria-invalid` için uygulanmamıştı.

**Neden bu turda çözülemiyor:** çözüm bileşene bir `invalid` prop'u eklemeyi gerektirir,
ve köprünün kendi yazılı doktrini (css:894-908: *"Bu yüzden bileşenlere HİÇ
dokunulmuyor"*) bunu yasaklıyor. **Bir şartname o doktrini ezemez** (§0.2 kural 4).
**Üç kabul edilebilir cevap:** (a) `MoneyInput` ve `DateInput`'a `defineOptions({
inheritAttrs: false })` + `v-bind="$attrs"` eklenir — `Select.vue:38`'in **zaten
kullandığı** kalıp, yani köprü doktrini "bileşene dokunma" değil "bileşene **stil**
verme" diye okunursa ihlal değil; (b) alan hatası bu iki kontrolde `ds-field-err` +
`aria-describedby` ile taşınır, `aria-invalid` **hiç** yazılmaz ve bu **yazılı** olur;
(c) köprüye `.stbl-ds .input-group[aria-invalid="true"] .form-control` kuralı eklenir —
sarmalayıcıyı hedefler, bileşene dokunmaz. **Sessiz kalmak kabul edilemez:** §4.2 madde
5 ve §7'nin `ds-field` satırı bugün bu iki kontrolde **uygulanamaz**, ve ikisi de manda
ile zorunlu.

**✔ Zafar: (a).** Uygulandı — ölçülmüş bir sapmayla; gerekçesi bu bölümün başındaki
karar tablosunun altında. Köprü doktrini (`css:894-908`) "bileşene **stil** verme"
diye okundu: iki bileşenin hiçbir CSS'i değişmedi, yalnız öznitelik yönlendirmesi
değişti. §4.2 madde 5 ve §7'nin `ds-field` satırı artık bu iki kontrolde de
uygulanabilir. Kalan boşluk `Typeahead` ve `MultiSelectPicker`'dır (§4.1(a)) — aynı
kalıp, ayrı iş.

---

## 11 · ÖLÇMEDİKLERİM

Dürüstlük listesi. Bunlar bu belgenin **zayıf** yerleri ve uygulayıcı bunları bilerek
başlamalı.

- **↺ Dört tarayıcı render'ı yapıldı — dördü de tek bir soru için.** Gerçek Tabler
  `1.0.0-beta20` (CDN, `www/stabler.html:1`) + deponun kendi iki CSS'i ile,
  `getComputedStyle` ve ekran görüntüsüyle: (1) `MoneyInput`'un `.input-group`'unda bir
  `rounded-*` sarmalayıcıda mı kontrolde mi durur (→ bir regresyon yakaladı, `7df361d`);
  (2) `<input type="number">` virgüllü ondalığı yer mi (→ hayır); (3) `.stbl-ds` altında
  `ds-btn` ile köprülü `.btn` farkı (→ `:disabled` yok); (4) `ds-input` bir `.input-group`
  çocuğu olabilir mi (→ olamaz). **Dördü de bir kararı değiştirdi.** Ama aşağıdaki madde
  ayakta: hiçbiri bir *ekranı* render etmedi.
- **Ekran düzeyinde hiçbir tarayıcı render'ı, hiçbir ekran görüntüsü yok.** Bütün kaskad
  ve özgüllük akıl yürütmesi CSS **kaynağından**; `getComputedStyle` ile teyit **edilmedi**. Bu
  özellikle şunları etkiler: `.ds-btn:disabled` ile `.ds-btn--primary:hover`'ın aynı
  özgüllükte olduğu (0-3-0 elle sayıldı), ve köprünün Tabler ton varyantlarını düşürdüğü
  iddiası.
- ↺ **Kontrast oranları artık hesaplandı** (§0.1 sonu) ve sürüm 1'in bu satırdaki
  sigortası — *"kontrast yetersiz çıkarsa biçim kodu tek başına ayakta kalır"* —
  **ölçülünce iki ucundan da kopuktu**: metin 2.71:1, kenar 1.19:1. İkisi de
  düzeltildi (D9), ama **hâlâ hesap `getComputedStyle` ile teyit edilmedi** ve daha
  önemlisi: `--ds-acc`, `--ds-crit`, `--ds-today`, `--ds-soon`, `--ds-ok` **Tabler
  değişkenlerine fallback'li** (`var(--tblr-primary, #206bc4)`). Değerler CDN'den
  geliyor; üretimde farklı bir Tabler sürümü farklı bir renk verirse **bütün oranlar
  kayar**. Hesaplarım fallback değerleriyle, yani "tasarımın ölçtüğü" değerlerle —
  "üretimin gösterdiği" değerlerle değil.
- **`<tr role="button">`'ın ekran okuyucuda satır yapısını bozduğu** akıl yürütmeyle
  söylendi (Ç18); NVDA/VoiceOver ile **denenmedi**.
- **`.form-check-input` kare kutuda Tabler'ın tik SVG'sinin nasıl konumlandığı**
  denenmedi. `background-image` bir SVG data-URI'si ve `border-radius: 0` onu
  kırpabilir.
- **`ds-form-section`'ın `ds-panel` içine konunca çift çerçeve ürettiği** kaynaktan
  okundu (ikisi de `border: 1px solid var(--ds-ln)`), **render'da görülmedi**. Ödül
  panelinin üç bölümlü kurgusu (§5.5b) bu tuzağın **içinde** — B-12.
- **3.75× uzamanın gerçek piksel etkisi** hiçbir düğmede, hiçbir çipte ölçülmedi.
  Kural yalnız "sabit genişlik yasak" düzeyinde; `uzc` (Kiril) altında bir çip/rozet
  örneği **hiç görülmedi** ve *"kırılmamalı"* iddiası hâlâ test edilmemiş durumda.
- **`seed_tender_demo.py` çalıştırılmadı.** Her lot no, tutar ve tarih dosyanın
  sabitlerinden okundu — betiğin kendisi canlı siteye yazıyor ve bu işin kapsamı değil.
- **`make check` bu turda çalıştırılmadı.** Bu belge kod üretmiyor; ama delta
  uygulandığında DB'ye dokunulmadığı için `make check` yeterli kanıttır
  (`make test-bench` gerekmiyor) — ve bu iddia da **çalıştırılarak doğrulanmadı**.
- ↺ **Delta'nın 33 kuralı bir tarayıcıya hiç yüklenmedi.** Sözdizimi python ile
  ayrıştırıldı, tokenlar doğrulandı, kapsam kontrol edildi — ama render **edilmedi**.
- ↺ **`.stbl-ds .alert`'in `border: 1px solid` kısayolu** `border-color`'ı
  `currentColor`'a sıfırlıyor ve `.alert-danger`'ın kendi `border-color`'ını
  özgüllükle (0-2-0 ↔ 0-1-0) eziyor olabilir. §6.5'in *"sıfır yeni CSS"* iddiası bu
  yüzden **doğrulanmadı** — sonuç Tabler'ın metin rengine bağlı, o da CDN'den geliyor.
- ↺ **`ds-table`'ın şeritsizliğinin gerçek okunabilirlik maliyeti** ölçülmedi; yalnız
  kaç tablonun etkileneceği sayıldı (**14**).
- ↺ **Yeni iskeletlerin (§6.3, §12b) hiçbiri bir tarayıcıda çizilmedi.** `visually-hidden`
  köprüden geldiği varsayıldı ve `grep` ile doğrulanmadı; bir ekran okuyucuda da
  denenmedi.

---

## Ek · Bu belgenin on iki kaynağı ve her birinin kaderi

| Kaynak | Katkısı | Reddedilen kısmı |
|---|---|---|
| `cekmece-sartname.md` | 15 `tgm-*` uzlaştırma tablosu · `ds-drawer-head` boşluğu · bölüm numarası kararı (Ç30) | `ds-file-*` üç sınıfı (D1) · `ds-field--check` (Ç27) · `ds-col-n` bir `<th>`de (Ç26) · bölüm düzeyi `ds-field-err` (Ç6) · `ds-field-hint`'in boş hâl taşıması (Ç7) · `data-cols="3"` (Ç11) · `t("Retry")`, `t("Save tender")` |
| `form-sartname.md` | 11 gramer maddesi · etiket bağı · hata durum makinesi · `ds-field` display kusuru · jeton listesi birleşimi | mount'a dayanan 5 ölçüt · §2.1'in vaat edip teslim etmediği CSS satırı (bu belgede yazıldı) · `ds-empty[data-tone="crit"]`'in düşürülmesi (D3'te geri alındı) |
| `durum-sartname.md` | Dört hâlin tamamı · `data-region-state` · `ds-skel-stack` · `ds-empty[data-size="sm"]` · `err.status` bulgusu · 16/16 yanlış yerleşim ölçümü | 5 ölçütün hepsi mount istiyordu (§8'de kaynak-yürütmeye çevrildi) |
| `aksiyon-sartname.md` | Bölge tanımı ve B1–B12 · R1–R8 · commit grameri · `ds-btn--commit` · `:disabled` kuralı · beş ekranın aksiyon kümesi | `ds-btn--primary` yayılma yarıçapı **2.3× yanlış** (3 değil 7) · `make guards`'ın Aşama A'da eklenmesi (S9: deponun kendi mandasını kırar) · 18 spinner'ın hepsini manda 9 ihlali sayması · `<tr role="button">` (Ç18) · kendi kapalı bölge listesini iki kez ihlal etmesi (B13 ile kapandı) |
| `bosluk-sartname.md` | `ds-btn[data-size="sm"]`'in 34px'i ve `gap: 5px`'i · `form-check` köprüsü · `ds-col-head[data-sev]` · satır vurgusu · `ds-table` şeritsizliği · `btn-xs` bulgusu | `ds-table-wrap` (Ç3) · `data-state="lead"` (D4) · tek footer'lı ödül paneli (Ç21) · `Approve = primary` (Ç2, A6) · `useConfirm()` (Ç2) · `ds-panel-foot[data-state="error"]` (Ç6) · iç içe `<tbody>` (Ç4) · **`Create purchase order`'ı düşürmesi** (S8) |
| `UZLASTIRMA-celiskiler.md` | 34 çelişkinin kararı — bu belgenin omurgası | D6 (`data-icon` geometrisi), D7 (`:hover inherit`) |
| `UZLASTIRMA-delta.md` | `:not(:disabled)` korumaları · `border-style: dashed` · `data-icon` geometrisi · `[aria-invalid]` köprüsü · `ds-btn` düğme sayımı | D1, D2, D3, D4 (§0.3) |
| `UZLASTIRMA-kapsam.md` | 96/149 benimseme · beş eksik sözlük · ölü dört dosyanın doğrulaması · print kararı | `ds-btn:disabled { opacity: .5 }` önerisi — tek kodlu, ACCEPTANCE #8'i karşılamaz |
| `UZLASTIRMA-kisitlar.md` | Brief §5'in yedi maddesinin taraması · i18n hasadı · dört metin yeniden yazımı · `ds-chip`/`ds-sev` biçim kusuru (B-14) · A5, A6, A7 | — (kararları §4.3 ve §9'a girdi) |
| **`CURUTME-tutarlilik.md`** ← sürüm 2 | Blok D↔B kaskad kusuru (D8) · `[aria-invalid]` erişilemezliği (§10.9) · Şekil A'nın koşulsuz öznitelikleri · B13↔B5 iç içeliği (R9) · *"doğru kalıp hiçbir yerde"* hükmünün 71 karşı örneği · altı kanıt hatası · `.disabled` boşluğu | `EmptyState`'in bu turda uzlaştırılması (12b-R2) |
| **`CURUTME-hicbirsey.md`** ← sürüm 2 | Kontrast ölçümlerinin tamamı (D9, D10) · `form-check-input` 5 site · ölü dörtün 10 Python referansı · K10 ve K11'in oynanabilirliği · 15 çevrilmemiş dize · Kapı 1/Kapı 2 ayrımı · `ds-cut-del` yükseklik ölçümü · beş atıf hatası | §8'in baştan yazılması (12b-R4) |
| **`CURUTME-uygulanabilir.md`** ← sürüm 2 | 15 eksik iskelet (§7b) · §1.2'nin 55 sınıflık kapalılık çelişkisi · `ds-chip[ok]` 2.47:1 (D10) · form hata kutusunun tek kodu (İ7) · dokuz mandanın tek tek denetimi · `ListToolbar` ve para için sıfır ölçüt (K17, K18) · iki yükleme animasyonu · `EmptyState` dördüncü lehçesi | `--ds-soon-tx` (12b-R1) · *"bileşen dili değil karar kaydı"* hükmü (12b-R5) |

---

## 12 · DÜZELTMELER — üç çürütme raporunun izi

> **↺ 2026-09-01, kararlar uygulanırken eklenen dördüncü tur.** Zafar'ın altı kararı
> uygulanırken bağımsız bir ölçüm + çürütme turu daha koştu. Üç şey düştü, biri **bu belgenin
> kendi premisi**, biri **benim düzeltmemdi**:
>
> | Ne | Kim yanlıştı | Ne çıktı |
> |---|---|---|
> | §10.2 *"manda Aşama B'yi blokluyor"* | **bu belge** | Köprü `.btn*`'i `.stbl-ds` altında zaten giydiriyor (`css:950-974`); bloklama yok, ve göç `:disabled`'ı kaybettiriyor |
> | §10.4(a)'nın `ds-input`'u | **bu belge** | Tabler'ın `.input-group` esneklik sözleşmesi dışında; `%` alt satıra düşüyor, grup 80px. Doğrusu `.form-control` |
> | *"§10.4'ün 10'u ve §10.8'in 8'i yanlış"* | **ben** | İkisi de doğruymuş. Dar kapsamlı taramam (`pages/tender/` yalnız, gömülü bileşenler hariç) 6 buldu; tender yüzeyi = 10. 8 de tender kapsamında doğruydu |
> | §10.8(a)'nın daha katı yazılabileceği | **hiç kimse — yeni olgu** | `test_tender_desk_spa.py:23` `OperationsDesk.vue`'da `SkeletonRows`'u şart koşuyor ve iki kullanımı da tablosuz; katı kural `make check`'i kırardı |
>
> Üçüncü satır bu belgenin en pahalı hata sınıfı: **yanlış bir düzeltme, yanlış iddiadan
> pahalıdır**, çünkü bir incelemenin otoritesiyle gelir. Ölçmeden "belgedeki iki sayı tutmuyor"
> yazdım; ikisi de tutuyordu.


Bu bölüm silinmez. **Yanlış çıkmış bir iddianın kaydı, düzeltildiğinin tek kanıtıdır** —
ve bir sonraki turun bu belgeye ne kadar güvenebileceğini yalnız bu bölüm söyler.

**Girdi:** `CURUTME-tutarlilik.md` (İ1–İ6 + 6 küçük + 4 ek), `CURUTME-hicbirsey.md`
(B1–B12), `CURUTME-uygulanabilir.md` (İ1–İ7 + 9 manda + 5 yapısal).
**Toplam ayrık itiraz: 46.** İşlendi **41**, reddedildi **5**.

Üç raporun **ortak** bulduğu tek şey `form-check-input` ölçümüydü — üçü de bağımsız
olarak `"0 tender'da"` iddiasını çürüttü. Bir iddianın üç ayrı mercekten aynı anda
düşmesi, o iddianın **hiç ölçülmediğinin** kanıtıdır.

### 12a · İşlenen 41 itiraz

| # | İtiraz (kaynak) | Ne yapıldı |
|---|---|---|
| 1 | `ds-btn--commit[data-sev]` (0-3-0) blok B'yi (0-3-0) sıra ile eziyor; silahlanmamış commit düğmesi devre dışı hâlini hiç almıyor (T-İ1) | **D8.** Blok D'nin dört kuralına `:not(:disabled):not([aria-disabled="true"])`; ayrıca `border-width: 2px`'i koruyan bir devre dışı kuralı. §3.1'in *"hiçbiri diğerine bağlı değil"* cümlesi düzeltildi |
| 2 | `:not(:disabled)` koruması `[aria-disabled="true"]`'yu **dışlamıyor**; delta kendi sözlüğünü korumasız bırakıyor (H-B10a) | Blok A'nın iki seçicisine `:not([aria-disabled="true"])` eklendi |
| 3 | *"Delta hiçbir ekranı değiştirmez"* — `form-check-input` tender'da 0 değil **4** (kapsam gereği 6) (T-İ3a, H-B1, U-İ1) | **§3.1b** yazıldı: beş bloktan ekran değişiyor, her biri sayıyla |
| 4 | Üç canlı `form-switch` `border-radius: 0` ile kareleşecek; özgüllük Bootstrap'la berabere (H-B1, U-İ1) | **D11.** Seçici `.form-check:not(.form-switch) .form-check-input`; yarıçap katmanın `!important`'lı listesine. Göç **B-16** |
| 5 | §1.3'ün `form-switch` yasağı **katmanı** ölçmüş, **kodu** ölçmemiş (H-B1, U-İ1) | §1.3 satırı 3 canlı siteyle yeniden yazıldı |
| 6 | `ds-form-section-head` *"0 tüketici"* — **2** var, belgenin kendi emsal dosyasında (T-İ3b, H-B8) | Blok K yorumu ve §3.1b düzeltildi |
| 7 | §3.1 *"sıfır regresyon"* ile §2 sıra 3 *"QuotationEntryDrawer değişir"* birbiriyle çelişiyor (T-İ3c, U-İ1) | §3.1b tabloya `ds-drawer-head` satırını koydu |
| 8 | Şekil A'nın `data-region-state`/`role="status"`/`aria-label`'ı **koşulsuz**; kanca yalan söylüyor, `role="status"` `<table>` rolünü eziyor — Ç18'in kendi itirazı (T-İ4) | §6.3 iskeleti yeniden yazıldı: kanca sarmalayıcıda ve koşullu, duyuru `v-if`'li ayrı bir eleman, `<table>` örtük rolünü koruyor |
| 9 | §7'nin *"`<EmptyState>` `<tbody>` yerine"*'si geçersiz HTML (foster parenting) (T-İ4-ek) | §7 satırı düzeltildi; §6.1'e `empty` iskeleti eklendi |
| 10 | *"Bugün iki primary aynı anda ekranda"* — ölçüm **1** (T-İ5, H-B5) | §5.1-B13 gerekçesi ve K8'in "bugün" hücresi yeniden yazıldı; B13'ün meşru gerekçesi (tasarımın kendi ürettiği ihtiyaç) yazıldı |
| 11 | B13 ⊂ B5 iç içe; tanım B5, tablo ikisi, K8 B13 diyor (T-İ6, U-manda5) | **D12 + R9.** Bölge tanımı *"en küçük"* → *"en dış"*; yuva kavramı; K8'in sayma birimi netleşti |
| 12 | `ds-empty[data-size="sm"]`'in *"iki bağımsız ezme"* gerekçesi — emsal **1** (T-K1) | Blok F yorumu düzeltildi; karar (kulvar geometrisi) ayakta |
| 13 | `ds-col-head[data-sev]`'in *"iki emsal"*i — **1**; satır **454** (455 değil); `DeclarantQueue:210` bir `card-header` (T-K2) | Blok I yorumu düzeltildi |
| 14 | `.ds-kpi[data-sev]`de **`info` YOK** — blok I'in beşinci kuralı kopya değil icat (H-B11-1) | `info` kuralı **silindi** |
| 15 | Blok I tek canlı tüketicisinde **etkisiz** (satır-içi `:style` her seçiciyi yener), kaldırma hiçbir listede yok (H-B10c) | **T7** eklendi; blok I yorumuna uyarı |
| 16 | `--ds-soon-t` ↔ `--ds-info-t` **1.02:1** — blok H'nin dört ton zemini görsel olarak üç (H-B11-renk) | `info` satırından `background` **kaldırıldı**; ayrımı sol çubuk taşıyor |
| 17 | Kesikli kenar `--ds-ln` ile **1.19:1** — biçim kodu ayakta değil; §11'in sigortası kopuk (U-İ4, H-B6) | **D9.** Kenar `--ds-tx3` (2.71:1); *"üç kod"* → *"iki taşıyıcı + bir destekleyici"*; §11'in sigortası kaldırıldı |
| 18 | `ds-chip[data-tone="ok"]` metinde **dolgu** token'ı, **2.47:1**; `--ds-ok-tx` yok; brief §5.2 ihlali (U-İ5) | **D10 + blok L.** `--ds-ok-tx: #1c7430` (5.27:1) |
| 19 | `ds-sev[data-sev="info"]` **3.03:1** @10px (U-İ5) | **Blok L.** `--ds-info-tx: #5b6675` (5.83:1) |
| 20 | `ds-empty[data-tone="crit"]` boş hâlden **yalnız renkle** ayrılıyor; katmanın 3px sol çizgisi kullanılmıyor (U-İ7) | Blok F'ye `border-left: 3px solid var(--ds-crit)` |
| 21 | §7 `ds-chip`'i "üç kod" diyor, B-14 "iki" ölçüyor; uygulayıcı §7'yi okur (U-İ6) | §7'nin `ds-chip` satırı iki koda düzeltildi; `ds-sev` satırı üç koda + `crit`↔`today` istisnasına |
| 22 | 15 bileşenin **iskeleti yok**; D1'in ret gerekçesi (*"bileşim denenmedi"*) belgenin kendisine de uyuyor (U-İ3) | **§7b** yazıldı: jeton listesi, form bölümü montajı, commit bloğu, `ds-seg`, hata bölgesi. `html` bloğu 3 → **9** (`grep -c '\`\`\`html'`): §6.1 `empty` örneği · §6.3 Şekil A ve B · §6.6 yetkisiz · §7b'nin beşi |
| 23 | §1.2 *"kapalı"* iddiası tender'ın kullandığı **55 sınıfı** dışarıda bırakıyor; §1.1 onları korumayı emrediyor (U-İ2) | §1.2 iki kümeye bölündü: kayıtlı 96 (korunur) / yeni yazım dağarcığı (kapalı) |
| 24 | `ListToolbar` dağarcıkta yok, manda 8'in **sıfır ölçütü** var (U-manda8) | §1.2'ye satır; **K17** |
| 25 | Manda 3'ün **sıfır ölçütü** var — 10 ölçülmüş ihlal (U-manda3) | **K18**, Kapı 1'de bloklayıcı |
| 26 | Manda 1'i hiçbir ölçüt korumuyor (U-manda1) | **K19** |
| 27 | Manda 2: 14 şeritli tablo şeridini kaybedecek; §1.2'de kaçış yolu yok (U-manda2) | Sayı §10.8'e; §1.2'ye `class="ds-table table"` kaçış satırı |
| 28 | Manda 9: iki yükleme animasyonu (`placeholder-glow` ↔ `ds-shimmer`) (U-manda9) | §6.3'e ölçümle yazıldı; birleştirme **B-21** |
| 29 | K10 iki grep'i de yeşilken **15 elle rozet + 4 fabrika** hayatta kalıyor; "30 site" gerçekte 26 (H-B3) | K10'a iki koşul; §0.1 ve §1.3 sayıları düzeltildi; §8.3'e hile satırı |
| 30 | K11 **boş** — `ds-field-req` tender'da 0, `--allow-empty` geçer (H-B4) | K11'e `≥1` koşulu; `Login` ihlali **B-22** |
| 31 | K2'nin 11 dosyası tek `class="ds-mono"` ile geçer (H-B4-ek) | K2'ye `≥3` koşulu |
| 32 | 16 ölçütün 11–13'ü deltayla değil **Aşama B göçüyle** sağlanır, ve bu yalnız K16'da yazılı (H-B12, U-d3) | **§8.1b** — Kapı 1 / Kapı 2 ayrımı, bağlayıcı |
| 33 | *"Doğru kalıp hiçbir yerde uygulanmıyor"* — **71 karşı örnek** ve deponun **hazır guard'ı** (T-ağır) | §6.3 hükmü ve **talimatı** düzeltildi; §8.1'e üçüncü kanıt yolu eklendi |
| 34 | `SkeletonRows` 80/97 değil **79/96**; 97.'si bir test dizesi (T-K6) | §0.1 düzeltildi |
| 35 | *"Ölü dört, 0 dış referans"* — **10 Python referansı**, üçü `make test` kapısında, biri varlık iddia ediyor (H-B2) | §0.1 ve §10.5 maliyetle yeniden yazıldı |
| 36 | `<tr role="button">` *"0 emsal"* — `TenderDocuments:257` canlı, ve o ekran §5.5(d)'de yeniden tasarlanıyor (T-K3) | §1.3 düzeltildi; §5.5(d)'ye satır; **T8** |
| 37 | `a4-print` 4 dosyada değil **1**; talimat bir no-op (T-K4, H-B9b) | §1.4(e) yeniden yazıldı: print **kapsam dışı**, iş yok |
| 38 | `nav-link` köprüde **var** (css:137); `TenderWorkspaceTabs` 33-43 (T-K5, H-B9a) | §1.4(c) düzeltildi |
| 39 | Belgenin yazdığı **15 dize** katalogda yok = **75 çeviri satırı**, hiçbir listede yok (T-i18n, H-B7) | **§4.3b** + **B-19** |
| 40 | `<button>` olmayan 18 `ds-btn` taşıyıcısı; `.disabled` sınıfına kural yok; K7 kapsamıyor (T-boşluk) | **§5.6b** + **B-20**; K7'nin kapsamı açıkça `<button>` ile sınırlandı |
| 41 | Gerekçeli devre dışı düğme **3**, 4 değil; "üç dosya" ↔ beş ad ↔ ölçülen 5 (H-B11-2,3) | §0.1 ve §5.6 sayıları düzeltildi |
| 42 | `test_design_layer_contract` node id'si **çalışmıyor** (`unittest` süiti) (H-B11-4) | §3.3, §8.1, K14 düzeltildi; **T9** |
| 43 | Künye `0240c16` ≠ `HEAD` (H-B11-5) | Başlık `7dfb381`; aradaki 7 `.vue` değişikliğinin CSS'e dokunmadığı yazıldı |
| 44 | `ds-cut-del` 30px **genişlik**, ~17px yükseklik; WCAG 2.5.8 altında; D1'in bedeli yanlış eksende (H-B10b) | §7b.1 iskeletinde ölçümle yazıldı; **B-23** |
| 45 | Silahlama kutusu ödül panelindeki mevcut `form-check-input` ile **ayırt edilemez** (U-İ1-3) | §5.4'e **altıncı parça**; §7b.3 iskeletinde üç ayrım kodu |
| 46 | `data-region-state`'in beşinci değeri tanımsız, *"hepsinde"* yanlış, `empty` örneği yok (U-d4) | §6.1'e üç kapatma: enum dört, içerik kanca taşımaz, kanca bölge kökünde, `empty` iskeleti |
| 47 | `EmptyState` **dördüncü lehçe** (8 sınıf, iki `border-radius: 50%`), hiç uzlaştırılmadı (U-d5) | **D13** — bilerek kapsam dışı, gerekçesiyle; §1.2'ye not; **B-17** |

*(Numaralandırma 47'ye çıkıyor çünkü bazı itirazlar iki ayrı düzeltme üretti; ayrık
itiraz sayısı 46, uygulanan düzeltme 41 kalem — bir düzeltme birden çok itirazı
kapattığı için sayılar birebir örtüşmez.)*

### 12b · Reddedilen 5 itiraz, ve **neden**

| # | İtiraz | **RET GEREKÇESİ** |
|---|---|---|
| **R1** | *(U-İ5)* `--ds-soon-tx` de eklensin — `ds-chip[data-tone="soon"]` ve `ds-sev[data-sev="soon"]` metinde dolgu token'ı kullanıyor, brief §5.2 ihlali | **Reddedildi.** İhlal gerçek ama **ölçülen sonucu yok**: çip 4.72:1, `ds-sev` 5.30:1 — ikisi de eşiği geçiyor. Bu deltanın her satırı bir **ölçülmüş kusuru** kapatıyor; görsel değişiklik üretmeyen bir yeniden adlandırma için 4 canlı siteyi değiştirmek ADR-303'ün ispat yükünü karşılamaz. **B-18**'e yazıldı — kayıt var, iş yok |
| **R2** | *(U-d5)* `EmptyState`'in `stabler-empty-*` lehçesi §2 gibi 8 satırlık bir tabloyla uzlaştırılsın | **Reddedildi (kapsam).** `tgm-*` **1 dosyada / 46 kullanımda** yaşayan bir tender lehçesiydi; `EmptyState` **159 kullanım / uygulama geneli**. Bu turun kapsamı tender'dı ve bir tender belgesinin uygulama geneli bir bileşeni yeniden tasarlaması, §0.2 kural 4'ün (bir şartname `CLAUDE.md`'yi ezemez) kardeşi bir sınır ihlali olurdu. **Ama sürüm 1'in "üç lehçe" sayımı yanlıştı ve bu düzeltildi** (D13); dördüncüsü **B-17**'de adıyla duruyor |
| **R3** | *(T-İ2)* `[aria-invalid]` köprüsü `DateInput`'a hiç, `MoneyInput`'a kısmen ulaşmıyor → bileşenlere bir `invalid` prop'u eklensin | **Kısmen reddedildi.** Ölçüm **doğru ve kabul edildi** (aşağıda işlendi), ama **önerilen çözüm reddedildi**: köprünün kendi doktrini (css:894-908, *"Bu yüzden bileşenlere HİÇ dokunulmuyor"*) bileşen değiştirmeyi yasaklıyor, ve bir şartname o doktrini ezemez. Bunun yerine **§4.2 madde 5'e kapsam sınırı yazıldı** ve soru **§10.9** olarak **Zafar'a taşındı** — çünkü cevabı manda 3 ve manda 4'ün zorunlu kıldığı iki bileşene dokunmayı gerektiriyor |
| **R4** | *(H-B12)* §8 baştan yazılsın; ölçütlerin çoğu bu belgenin teslimatını ölçmüyor | **Kısmen reddedildi.** Kapı ayrımı **eklendi** (§8.1b), ama ölçütlerin Aşama B'yi ölçmesi bir **kusur değil**: bu belge bir **tasarım dili**, bir commit değil. Bir dilin kabul ölçütü, dilin **konuşulduğunu** ölçmek zorundadır — yoksa CSS iner, hiçbir ekran değişmez, ve "iş bitti" denir. Kapı 1'in 7 ölçütü deltayı, Kapı 2'nin 12'si dili ölçer; ikisi de gerekli |
| **R5** | *(U-hüküm)* Belge *"bir bileşen dili değil, bir karar kaydı"* — beş alan belgesini birleştirmiş ama dil üretmemiş | **Reddedildi, ama kısmen haklı olduğu için §7b yazıldı.** İtirazın ölçüsü (` ```html ` = 3) doğruydu ve **on beş iskelet eklenerek dokuza çıkarıldı**. Ama hüküm fazla geniş: bir bileşen dili yalnız iskelet değildir — §1.2'nin dağarcığı, §5.1-5.2'nin bölge cebri, §6'nın hâl grameri ve §7'nin beş-hâl sözleşmesi **davranış sözleşmeleridir** ve iskeletten daha bağlayıcıdırlar. Kalan **on** bileşenin iskeleti §12c'de **açık borç** olarak duruyor; kapatılmadı, gizlenmedi |

### 12c · Kapatılmayan borç — on bileşenin iskeleti hâlâ yok

Çürütme 15 eksik iskelet saydı; §7b beşini yazdı, §6.3/§6.6 ikisini zaten yazmıştı.
**Kalan on, adıyla, Aşama B'nin ilk işi:**

`ds-drawer[data-size="lg"]` tam çekmece · `ds-empty[data-tone="crit"]` gönderim özeti
(satır başına tıklanabilir bağlantı) · `ds-col-head[data-sev]` kulvar başlığı ·
`ds-btn[data-icon="1"]` + `aria-label` · `ds-meter` · `ds-deflist`/`ds-fill` ödül
özeti · `ds-kanban`/`ds-col`/`ds-card` · `<StatusBadge>` çağrı sözleşmesi ·
`MoneyInput`/`DateInput`/`Select`'in `id`/`v-model`/`currency` sözleşmesi ·
`ds-sla[data-state="unknown"]` beşinci hâl hücresi.

**Bunlardan sonuncu üçü en pahalısı:** bir uygulayıcı `MoneyInput`'un sözleşmesini bu
belgeden **öğrenemez**, ve o iki bileşen **manda** ile zorunlu.

### 12d · Sürüm 1'in ayakta kalan kısmı

Üç rapor da bunları bağımsız olarak yeniden ölçtü ve **birebir doğruladı** — belgenin
zayıflığı sayıların çoğunda değildi:

katman 1037 satır · `ds-*` 149 · `--ds-*` 28 · `disabled` 2 (930, 931) · `ds-btn`
kuralları 5 · tender'ın kullandığı `ds-*` 96/149, tanımsız 0 · `pages/tender` 27/17 ·
`TenderMasterDrawer` 777/46/15/0 · `SkeletonRows` **tender** 16/8/8/0 ve on altı
dosya:satırın on altısı · `spinner-border` 18 (5+13) · `ds-btn` `<button>` 36, devre
dışı 12, dosya 10 · `ds-btn--primary` 7/6 · `table-responsive` 148 · `EmptyState`
159/16 · `STATUS_MAP` 49, aranan 5'i 0 · mount altyapısı 0, `mount(` 0, 76 spec'in
17'si adını anıyor · `vitest.config.mjs:15` · `ds-cut` canlı tüketici 0 · `btn-xs`
14/5/0 · `--ds-ok-t` 0 · `--ds-font-body` 2 kullanım/0 tanım · `.btn-primary:hover`
≠ `.ds-btn--primary:hover` · `err.status` (client.js:73, :110) · `data-region-state`
çakışma 0 · `.ds-field` display kararının sıfır-regresyon iddiası · §2'nin **15
`tgm-*` ölçümünün hepsi** · kontrol edilen **tüm CSS satır atıfları** · §3.3'ün
aritmetiği (yeniden üretilebilir).

Ve iki hamle üç raporun üçünde de **doğru** bulundu: **§10'un Zafar'a taşınan yedi
maddesi** (§0.2 kural 4'ün dürüst uygulaması) ve **§11'in ölçmediklerim listesi** —
*"ikisi de bu turun ölçebildiği kusurları bulmayı mümkün kıldı."* Bir belgenin kendi
zayıflığını yazması, çürütmeyi kolaylaştırır; bu iyi bir şeydir.
