# Backlog

Bu dosya `bd` (beads) yerine geçer. Beads 2026-08-18'de kaldırıldı; aşağıdaki
maddeler o araçtan aktarıldı, tespitleriyle birlikte — çoğu ölçülmüş, dosya:satır
referanslı gerçek hatalar, yeniden bulmak pahalıya gelirdi.

Bu bir kuyruk değil, **bulgu arşivi**. Sıradaki işi Zafar söyler. Bir maddeyi
bitirdiğinde satırı sil ya da `~~üstünü çiz~~`; ceremony yok.

Çalışma biçimi: kırmızı test → kod → `make check` → commit. DB'ye dokunuyorsa
ayrıca `make test-bench`.

---

## P1 — yüksek

### UZEX poller sekiz kiracıda saatlik koşuyor ve yapısal olarak hiçbir şey üretemiyor
`hata` · ölçüldü 2026-08-28, prod, salt-okunur

WP-300…309 kodda eksiksiz: `stabler/integrations/uzex/`, `stabler/tasks/uzex_poll.py`,
patch `v39_deal_uzex_fields.py`, 5 test modülü. Saatlik iş kayıtlı ve açık —
`stabler/hooks.py:120`; mikas'ta Scheduled Job Type `stopped=0`, `frequency=Hourly`.

Ama `uzex_keywords` **ne anjan ne mikas** `site_config.json`'ında var, ve
`matches_keywords` boş listede her zaman `False` döner
(`stabler/integrations/uzex/_parse.py:99` — tasarım gereği, flood guard). Yeni bir lot
hiçbir zaman Deal olmaz; izlenen Deal de 0 olduğu için güncellenecek bir şey de yok.
mikas'ta CRM Deal sayısı 0.

Yani entegrasyon canlı, ağa gidiyor ve boş dönüyor. Düzeltme tek config satırı — ama
planlar hedefte çelişiyor: `docs/plans/2026-07-11-master-roadmap.md:43` "**Mikas**/UZEX
go-live" diyor, `docs/plans/uzex-go-live-checklist.md:65` §B.1 başlığı
"(**anjan**.erpstable.com)". Aynı roadmap satırı "resmi UZEX API başvurusu" da diyor;
o kod işi değil. **Prod ayarı — Zafar kararı.**

Yeniden ölçüm:
```
ssh ice-production 'python3 -c "import json;c=json.load(open(\"/home/frappe/frappe-bench/sites/mikas.erpstable.com/site_config.json\"));print([k for k in c if \"uzex\" in k])"'
```

### Dokümanlarda sabit kiracı listesi — dokuz döngü, üçü site atlıyor
`hata` · ölçüldü 2026-08-28

Prod'da 8 site stabler taşıyor (`.claude/skills/stabler-deploy/SKILL.md`, 2026-08-20).
Ama `docs/` altındaki dokuz `for` döngüsü kiracı listesini **elle** yazıyor ve hiçbiri
8 değil:

| Dosya:satır | Liste | Atlanan |
|---|---|---|
| `docs/plans/2026-07-17-imports-PROD-deploy-runbook.md:107` | 6 site | **msa, zuma** |
| `docs/plans/2026-07-17-kassa-tender-PROD-deploy-runbook.md:100` | 6 site | **msa, zuma** |
| `docs/plans/PROMPT_deploy_departure_gate.md:147, :164` | 7 site | zuma |
| `docs/runbooks/nginx-immutable-assets.md:69, :82` | 7 site | zuma |
| `docs/runbooks/2026-08-07-credential-exposure-response.md:149, :280` | 7 site | zuma |
| `docs/runbooks/mariadb-buffer-pool.md:113` | 7 site | zuma |

`migrate` per-site olduğu için bu döngülerden biri kopyalanırsa en az bir kiracı
patch'siz kalır — ve bu, orada bir şey kırılana kadar tamamen sessizdir. Kimlik
rotasyon runbook'u da listede.

Doğru desen aynı depoda zaten var — `docs/plans/PROMPT_deploy_ci_packing.md:53` listeyi
sunucudan üretiyor: `ls sites | grep -v assets | grep "\."`. Aynı dosyanın `:57` satırı
ise "Expect exactly 7" diye sabit yazıyor.

Elle düzeltmek çözüm değil: kiracı sayısı ölçülen bir olgu, dokümana yazıldığı an
bayatlamaya başlar. Dokuz yerin hepsi dinamik desenle **değiştirilmeli**.

### anjan'da POS açık ama çalışamaz — `enable_pos=1`, 0 POS Profile, 0 İКПУ
`hata` · ölçüldü 2026-08-28, prod, salt-okunur

`v100_enable_pos.py` `enable_pos = enable_sales` yazdı, sonuç: 8 kiracının 7'sinde
`enable_pos=1`. anjan'da POS Profile **0**, `ikpu` içeren Custom Field **0**. Yani
menü açık, arkasında çalışabilir bir kurulum yok —
`docs/plans/2026-08-05-ofd-fiskalizasyon-fizibilite.md` İКПУ + kayıtlı kassayı şart
koşuyor.

Aynı kusuru `docs/plans/2026-07-18-multitenant-governance.md` beş hafta önce teşhis
etmişti: "gating çalışıyor ama yanlış tarafa ayarlı, yeni modül `default=1` geliyor".
Teşhis edilip düzeltilmediği için v100'de birebir tekrarlandı.

**Prod veri değişikliği — Zafar kararı.**

### Modül bayrak matrisi — planların yazıldığı modüller kiracılarda kapalı
`tespit` · ölçüldü 2026-08-28, prod, salt-okunur (`Stabler Company Modules`)

| Site | crm | tender | money | modern SO | mfg | pos |
|---|---|---|---|---|---|---|
| anjan | 0 | 0 | 1 | 0 | 1 | 1 |
| dts | 0 | 0 | 1 | 0 | 0 | 1 |
| horeca | 0 | 0 | 1 | 0 | 0 | 1 |
| laminor | 0 | 0 | 1 | 0 | 0 | 1 |
| mikas | 0 | 1 | 1 | 0 | 0 | 0 |
| msa | 0 | 0 | 1 | 0 | 0 | 1 |
| smartbox | 1 | 0 | 1 | 0 | 0 | 1 |
| zuma | 0 | 0 | 1 | 0 | 0 | 1 |

Üç sonuç:

- **`enable_crm` yalnız smartbox'ta 1.** Orada 14 CRM Deal var, hepsi `Administrator`,
  hepsi 2026-06-07'de 2 saniye içinde yaratılmış — tohum verisi. Yani
  `docs/plans/2026-07-29-crm-tender-to-cash.md`'nin 7 görevi (CrmHome, `Deal360View.vue`,
  `ManagerCockpit.vue`, `api/crm_analytics.py`, `api/crm_email.py`) mikas için yazıldı,
  mikas'ta kapalı, ve açık olduğu tek yerde kimse kullanmıyor.
- **`enable_tender` yalnız mikas'ta 1** ve mikas boş (0 CRM Deal / RFQ / SQ / PO / SO,
  0 Payment Entry, 0 fatura, 6 Journal Entry, 24 GL Entry). Tüm tender paketi tek bir
  boş kiracıya bakıyor.
- **`enable_modern_sales_order` sekizinde de 0.** `docs/plans/2026-08-21-so-si-modern-kapsam-karari.md`'nin
  "Modern sadece msa ve mikas'ta" cümlesi bugün hiçbir yerde doğru değil.

Yeniden ölçüm: `frappe.get_all("Stabler Company Modules", fields="*")` her sitede.


### ~~`uzc` dili Language kaydı olarak sekiz kiracıda da yok — 6 hesap kaydedilemiyor~~ ÇÖZÜLDÜ 2026-08-28
`hata` · ölçüldü 2026-08-28, prod, salt-okunur

Stabler beş dil sunuyor (en, ru, uz, uzc, tr) ve kullanıcılar `uzc`'yi seçebiliyor —
ama Frappe'nin `Language` doctype'ında **`uzc` kaydı sekiz kiracının hiçbirinde yok**
(`uz`, `ru`, `tr` hepsinde var).

Sonuç: `language = "uzc"` taşıyan hesapların `User` belgesi **hiçbir doğrulanmış yoldan
kaydedilemiyor** — Desk'ten, API'den, `user.save()` çağıran her koddan
`LinkValidationError: Could not find Language: uzc` alınıyor.

| Kiracı | Etkilenen hesap |
|---|---|
| anjan | 4 — `abdulazizmuminov107`, `davrondarmanov`, `qudratulloh`, **`zafar@stable.uz`** |
| smartbox | 1 |
| zuma | 1 |

Nasıl bulundu: `Line A Operator` rolünü silmek için beş kullanıcıdan rol ataması
kaldırılmaya çalışıldı; `User.save()` bu doğrulamada patladı. Rol sonunda `Has Role`
satırları doğrudan silinerek kaldırıldı, yani bu hata **hâlâ açık**.

Muhtemel düzeltme: her kiracıda `Language` kaydı oluşturmak
(`language_code="uzc"`, `language_name="Oʻzbekcha (kiril)"`). Prod veri değişikliği —
Zafar'ın onayını bekliyor. Yamayla mı yoksa elle mi yapılacağı da karara bağlı;
yama tercih edilirse `stabler/patches/` altına, sekiz kiracıda da idempotent çalışacak
şekilde.

**Çözüm (2026-08-28):** `Language` kaydı oluşturulmadı — Zafar `uzc`'yi seçenekten
çıkarmayı seçti. Altı hesap `uz`'ye taşındı (anjan 4, smartbox 1, zuma 1), üç seçici
temizlendi, katalog korundu. `User.save()` anjan'da yeniden denendi: **geçiyor**.
Karar: `docs/plans/2026-08-28-uzc-secenekten-cikarildi.md`.

**Not, kayıt için:** `stabler/__init__.py` zaten `frappe.get_doc`/`get_cached_doc`
için `uzc → uz` yönlendiren bir monkey-patch taşıyordu. O yama okumaları kapsıyor,
**link doğrulamasını kapsamıyor** — hatanın aylarca hayatta kalma sebebi bu. Yama
yerinde duruyor ve `uzc` katalogu için hâlâ gerekli.

---

### Sourcing: RFQ↔SQ backfill + NULL-tolerant deal_type filter
`stabler-18l` · hata *(devam ediyordu)*

Antigravity tender/sourcing incelemesinden çıkan P1/P2 düzeltmeleri.

P1: get_rfq, v83 kolonu (custom_rfq) var olur olmaz Supplier Quotation aramasını custom_crm_deal'dan custom_rfq'ya çeviriyor. v83 patch'i backfill yapmıyor ve save_supplier_quotation yalnızca yeni belgeye damgalıyor → mikas'ta mevcut her SQ, RFQ detayında kalıcı görünmez oluyor. Çözüm: (a) v83'e tek-RFQ'lu deal'lar için idempotent backfill, (b) get_rfq'da custom_rfq=<rfq> OR (custom_rfq NULL AND custom_crm_deal=deal), (c) NULL custom_rfq senaryosunu çalıştıran test.

P2/1: deal_type='Tender' typeahead filtresi de backfill'siz (v60 custom field, default Standard, UPDATE yok) → v60 öncesi deal'lar NULL, pickerlardan kayboluyor. Çözüm: crm.py extra_filters tarafında NULL-toleranslı hale getir (Standard olanlar girmemeli).

**Not:** P1 kapandi (94ceb01): get_rfq or_filters + v83 backfill + 4 mutasyon-kanitli test. make check yesil, main=origin/main=94ceb01, agac temiz. P2/1 (deal_type NULL-toleransi) BILINCLI YAZILMADI - mikas olcumu [[Standard,1],[Tender,9]] sifir NULL gosteriyor. Kalan: deploy onayi + TenderNav sourcing linki.

### LCV: submit from the SPA on a chosen distribution basis
`stabler-1dq3` · özellik *(devam ediyordu)*

OWNER-OF-RECORD for the work sitting on feat/lcv-submit-and-basis. Created 2026-08-17 because that branch had NO bead: 50 open + 50 closed beads describe none of it, and its commits carry no bead id (feat(lcv): rather than the house feat(stabler-xxx):). Without this record the two confirmed defects below have nothing to block.

WHAT IS ON THE BRANCH, three commits ahead of main:
  6c46661 feat(lcv)  Submit button on the SPA landed-cost review; a distribution basis the operator picks, persisted on a Custom Field on the source document (patch v87_lcv_distribution_method); a freeze rule once a voucher is submitted; imports/LandedCostReview.vue deleted and purchasing/LandedCostReview.vue made to serve both routes (router.js already pointed at the purchasing copy, so no route broke)
  094455f fix(lcv)   per-kg card was adding a USD receipt total to UZS voucher totals
  9545015 style(lcv) ruff I001 import grouping — the push gate rejects the branch without it

GATE: make check green at 9545015 (3421 py + 218 js). make test-bench NOT run, and this touches a patch and a Custom Field, so check alone is not proof.

DO NOT MERGE until stabler-xvsn and stabler-rctm close. Both were found by a pre-merge review of 6c46661..094455f on 2026-08-17 (three independent lenses, then three adversarial refutation attempts per finding; both survived, and the P0 was re-confirmed by hand). Together they mean the screen can show one distribution basis while the ledger uses another, and the cost-per-kg figure printed directly above the new Submit button can be understated by the damaged-goods fraction.

ALSO FOUND, not blocking, not yet filed separately — do not lose these:
  P2 lcv_math.py:421   flipping the default basis Qty -> Amount makes the automatic LCV build THROW on any receipt whose item amounts total zero; on the initial build path that throw is silent because it runs in a background job, so the landed cost never reaches valuation at all
  P2 patches/v87:61    the Custom Field is inserted with a raw frappe.get_doc({...}).insert() instead of create_custom_field(s), so CustomField.on_update re-validates the entire Purchase Receipt / GRN Checklist meta including every unrelated pre-existing custom field
  P3 patches/v87:38    the payload omits insert_after; Frappe reads falsy insert_after as 'put it at the very top of the form', ahead of the naming series
  P2 test_lcv_unification.py:117  the freeze rule is the safety property this branch introduces and has no test at the boundary that enforces it
  P2 LandedCostReview.vue:277     every new user-facing string is absent from all five translation catalogs (stabler-i18n)
  P3 imports.py:3647   existing_lcvs on the GRN branch reads grn.landed_cost_vouchers, which only _build_and_save_lcv writes, so an amended or Desk-created voucher is invisible and the card can omit customs duty already netted out of preview.total
  P3 lcv.py:393        set_distribution_method on a GRN Checklist rebuilds the whole imports review payload just to enumerate Purchase Receipt names

DoD for this bead: make check AND make test-bench, both children closed, and the branch merged to main and pushed.

### Imports: otomasyonun urettigi PI'lar Gate 4 yuzunden HIC kapitalize edilemiyor
`stabler-1mf` · hata

Olcum zinciri:
  - _capitalize_linked_bill (imports.py:8541) tek cagirana sahip: imports.py:8784, set_bill_import_refs icinde. Baska hicbir yerde cagrilmiyor.
  - build_transport_pi_payload ve build_import_expense_pi_payload (payment_math.py:143-165) olusturduklari PI'a dort v46 ref'ini (custom_commercial_invoice / custom_ci_number / custom_import_truck / custom_import_container) DOGUSTAN basiyor.
  - set_bill_import_refs Gate 4 ise ref'lerden HERHANGI BIRI doluysa elle baglamayi reddediyor ('automation-owned bills stay locked').
Sonuc: otomasyonun urettigi nakliye/hizmet PI'lari hicbir zaman Container Cost Line'a, dolayisiyla hicbir zaman Landed Cost Voucher'a ulasmiyor. Ithalat maliyet resmi bu faturalari sessizce kaybediyor.
Cozum secenekleri (karar verilmedi): (a) otomasyon PI'i olusturulurken kapitalizasyonu da yapsin, (b) Gate 4 'otomasyon ref'i' ile 'elle ref' ayrimini tasiyacak sekilde gevsetilsin, (c) otomasyon yolu _capitalize_import_cost'u dogrudan cagirsin.
Not: Part C (Import Expense kapitalizasyonu) bunu KAPSAM DISI birakiyor -- bilerek.

### ADR-008 rate freeze can collide with the +/-20% CBU tolerance at payout
`stabler-22vj` · hata

Found 2026-08-17 while writing the qzr9.9 bench test, by running it — not by reading.

stabler/api/_accounts.py:validate_exchange_rate runs from the Journal Entry 'validate' hook (stabler/hooks.py, doc_events['Journal Entry']['validate'] -> stabler.api._accounts.validate_journal_entry). It does two things to every foreign-currency row:
  1. refuses the entry when no CBU rate exists for that currency on or before the posting date;
  2. refuses the entry when the row's rate is more than +/-20% away from the CBU rate.

ADR-008 requires payout and refund to reuse register_base_rate verbatim, months later if need be. So a corridor whose market rate moves more than 20% between register and payout produces a payout that CANNOT POST: the frozen rate is by then outside the band. UZS has moved that far inside a year before.

Consequence today: the transfer is stuck. Cash was taken at register, the obligation is open, and neither payout nor refund can be posted — both reuse the frozen rate. There is no override path in remittance_accounting.py, deliberately: silently widening the band would disable a guard that exists to catch fat-finger rates.

Also note point (1) is a second, quieter trap: the obligation leg is in the RECEIVE currency, so the receive currency needs a CBU rate on file even though the remittance code never reads one. A tenant paying out in a currency the CBU feed does not carry cannot register at all. The bench test seeds both currencies for exactly this reason (test_remittance_accounting_bench.py, _rates).

Decide: exempt remittance vouchers from the band (voucher_type or the stabler_remittance_stage custom field), widen it for them, or treat a frozen rate outside the band as an approval-gated exception. This is a policy call, not a code tweak — the guard is there on purpose.

### FX residual toleransi ile farkin olculdugu presizyon ayni sey degil — KAPANDI 2026-08-20

`fx-residual-precision` · hata *(kucuk, ama P&L'e yaziyor)* · **cozuldu**

**Kapanis.** Bu kaydin sordugu sey olculdu: "uretimde bu araliga dusen gercek
bir kalinti var mi". **Yok.** UZS tabanli uc kiracinin (horeca, mikas, msa)
`tabJournal Entry Account` tablolarinda `user_remark='fx-rounding-auto'` olan
tek bir satir bile yok; anjan'in 48 satiri zaten USD tabanli, yani sikilan
toleransla kitaplanmis (maks 0,15). Daraltma bedavaydi ve yapildi: `UZS`,
`_fx_residual.ZERO_DECIMAL_CURRENCIES` kumesinden cikarildi, boylece iki notion
da 2 diyor.

Ayni kok neden onyuzde daha pahaliya mal olmustu — `money.js` UZS'yi sifir
ondalikli ilan ettigi icin `MoneyInput` kullanicinin yazdigi kurusu blur'da
yuvarliyordu: Mikas'ta `1 500 000,50` acilis bakiyesi `1 500 001` olarak
kitaplaniyordu. Ayni commit'te duzeltildi.

Bir daha sessizce sapmamasi icin `test_currency_precision_agreement.py` (bench)
eklendi: her sirketin temel para birimi icin `base_precision_for(ccy)` ile
`get_field_precision(JE.debit_in_account_currency, currency=ccy)` esit olmak
zorunda. Asagidaki kayit, karar verilmeden onceki durumu anlatiyor; tarihsel
kayit olarak birakildi.

2026-08-18'de olculdu, `fix(fx)` duzeltmesi sirasinda ortaya cikti; o commit'te
**bilerek degistirilmedi** cunku yedi kiracinin her Journal Entry ve Payment
Entry'sinde neyin kalinti sayilacagini daraltmak kendi basina bir karar.

`stabler/api/fx_balance.py:_balance_journal_entry` iki farkli presizyon
kullaniyor:

* fark, **belgenin** presizyonunda olculuyor — genesis-test.local'de UZS bir
  sirkette `JE.precision("total_debit")` = **2**, cunku `currency_precision`
  bos ve `use_number_format_from_currency` 0, dolayisiyla `get_field_precision`
  global `#,###.##` formatina dusuyor (frappe/model/meta.py:910-913);
* tolerans ise **para biriminin** presizyonunda boyutlandiriliyor —
  `_fx_residual.base_precision_for("UZS")` = **0**, yani birim 1 som.

Sonuc: 3 bacakli bir UZS kaydi `residual_tolerance(3, 0) = 1.0 * (3+2) = 5.0`
tolere ediyor. Farkin gercekte olculdugu presizyonda bu **499 birim**. UZS
kurlarinda parasal olarak onemsiz, ama Exchange Gain/Loss hesabina kimseye
sorulmadan yazilan bir tutar ve iki notion'in hangisinin kastedildigi kodda
yaziyor degildi.

Simdi yaziyor: `_balance_journal_entry` icindeki not ikisini de adlandiriyor ve
`test_fx_balance.py::ToleranceBoundaryTest` sinirl her iki para birimi sinifinda
da pinliyor (USD 0,04 kabul / 0,05 red; UZS 4 kabul / 5 red). Yani uyusmazlik
artik kazara degil, kayitli.

Karar gereken: ikisi de `doc.precision("total_debit")`'ten mi turetilsin? Bu bir
**daraltma** olur — bugun kitaplanan 0,05-4,99 arasi UZS farklari artik
kitaplanmaz ve ERPNext belgeyi "Total Debit must be equal to Total Credit" ile
reddeder. Once olculmesi gereken: uretimde bu araliga dusen gercek bir kalinti
var mi. Yoksa daraltma bedava; varsa daraltma o belgeleri kirar.

### Vehicle Agreement terminal statuses have no writers — Completed, Terminated, Restructured unreachable
`stabler-2671` · hata

Two separately-confirmed gaps merged on 2026-08-17 by an explicit dedupe pass: they are one defect with one fix surface. Filing them apart would invite two conflicting implementations of one status machine.

THE DEFECT. stabler-cibo (CLOSED, ff02c50) shipped an eight-state agreement_status enum and correctly split Rescheduled (collectible) from Restructured (terminal). Only some states got writers. api/vehicle_finance/v1.py writes agreement_status in exactly TWO places: :470 Active and :929 Rescheduled. Nothing anywhere writes Completed, Terminated or Restructured.

So: a fully paid agreement can never leave Active. settlement_writeoff has no consumer. And the restructure flow that docs/decisions/2026-08-16-restructure-closes-and-reopens.md declares binding on l0m.3.9/.3.10/.3.11 has no writer at all.

WHAT IS ALREADY DONE — do not redo any of it, a bead that re-adds these is actively wrong:
  stabler-cibo (CLOSED)  the eight-state enum, patch v85, five-language i18n
  stabler-vjfd (CLOSED, fc721f4)  the restructured_from self-link COLUMN, frappe-free chain.py maths, and chain_position / chain_length / restructure_count already exposed on agreement_list and work_queue
  stabler-exc  (CLOSED)  STATUS_MAP already carries Completed and Terminated badge colours
The schema and the READ path exist. Only the WRITER is missing.

OWNERSHIP CORRECTION. The close notes of both cibo and vjfd assert the restructure writer 'is stabler-l0m.3.10'. l0m.3.10's own description never mentions restructure — it covers agreement detail, FIFO allocation and the payment panel. This bead supersedes those two close-note claims. Either amend l0m.3.10 or treat this bead as the single owner, but do not leave two nominal owners for one flow.

SIZE WARNING. Restructure is behaviourally the larger piece: it closes the original and opens a successor per the ADR. If the merged bead breaches the micro-task budget, split it — but only under one parent that fixes the shared transition table FIRST, so both halves write through the same machine.

DoD: make check AND make test-bench.

RELATED, NOT INCLUDED: the direction-slot question (a terminal agreement still occupies its VIN slot) is filed separately and is untestable until this lands, since it turns on how terminal agreements are counted.

**Not (2026-08-19, 94d1746 + takip):** İki yazıcı kapandı — `Completed`
(`_collect_or_pay` içinde, planı ödendiğinde) ve `Terminated`
(`terminate_agreement`, `settlement_writeoff` + zorunlu gerekçe). Geçişler
`api/vehicle_finance/status.py` içinde tek bir frappe'siz tabloda; `_set_status`
tek kapı ve satırı `for_update` ile okuyup karar veriyor. `Restructured` BİLEREK
yazılmadı, ADR gereği ayrı iş — bu maddenin kalanı odur. `Review` ve `Approved`
da yazıcısız; ilk sayım onları atlamıştı, gerçek beş.
`test_the_declared_gaps_really_have_no_writer` üçünü de cırcırlıyor: birine
yazıcı gelirse test kırmızıya döner. `make check` + `make test-bench` yeşil.

### Peşinatlı sözleşme kapanırken faturası açık kalıyor — kapanmışa geri dönüş yok
`stabler-vf-adv` · hata · P2

2026-08-19 incelemesinde bulundu, `stabler/tests/test_vehicle_finance_accounting.py`
`test_completion_is_measured_on_the_schedule_not_the_invoice` ile üretiliyor.

`_reconcile_advances` (v1.py:420) peşinatı — `VFA-ADV-<sözleşme>` etiketli Payment
Entry — 0. satıra bir Payment Application yazarak kapatır. Faturaya hiç
dokunmaz: `_invoice_payload` ne `advances` doldurur ne
`allocate_advances_automatically` kurar. Sonuç: plan sıfırlanınca sözleşme
`Completed` damgalanır, fatura ise peşinat kadar açık kalır.

Kapanmış sözleşme `_COLLECTIBLE_STATUSES` dışındadır, yani `work_queue`
göremez (work.py:205), `_collect_or_pay` reddeder, `approve_reschedule`
reddeder, `terminate_agreement` reddeder. Alacak AR'da sonsuza dek açık kalır ve
modüldeki hiçbir uç nokta o sözleşmeye ulaşamaz. Düzeltmeden önce sözleşme hiç
değilse kuyrukta, yani görünür kalıyordu.

Bugün **gizli**: uygulamada `VFA-ADV-` Payment Entry üreten hiçbir uç nokta yok
— testin kendisi elle kuruyor. Ama `_reconcile_advances` ve `cancel_payment`'ın
`_ADVANCE_PREFIX` dalı tam olarak o akış için yazılmış.

KARAR GEREKEN, ikisi de savunulabilir ve seçim muhasebeye ait:
(a) `_reconcile_advances` avans PE'sini faturaya da tahsis etsin — iki ölçü
    yakınsar, kapanış her iki tanımda da aynı anda olur; ya da
(b) fatura açıkken kapanma reddedilsin ve kalıntı açık bir mutabakat işi olarak
    yüzeye çıksın.
Canlı bir alacağın üstünü sessizce kapatmak varsayılan olmamalı. Kapanış
ölçüsünü faturaya çevirmek ise ÇÖZÜM DEĞİL: peşinat taşıyan hiçbir sözleşme
kapanmaz, yani stabler-2671'in ta kendisi geri gelir.

### Remittance has no engine flag — Settings shipped without JE Legacy or Transfer V1
`stabler-3lak` · iş

Measured 2026-08-17 at HEAD da48010. Every line below was independently re-verified; nothing here is quoted from a plan without checking the code.

THE GAP. docs/plans/2026-08-16-remittance-operations-center.md:466 makes a Company setting the entire rollout mechanism: 'remittance_engine = JE Legacy | Transfer V1', default JE Legacy. Searching the whole repo for remittance_engine returns exactly ONE hit — that plan line. Zero code hits (6937 files, re-run with hidden files and no ignore).

THE ANALOGUE IS ALREADY SHIPPED CODE, so this is not a design question, it is an omission:
  vehicle_finance_settings.json:38  installment_engine, Select 'Legacy / Agreement V1', default Legacy, reqd 1
  vehicle_finance_settings.py:19    get_engine(company)
  consumers: api/vehicle_finance/permissions.py:86-89, api/vehicle_finance/work.py:580,586
Remittance Settings (remittance_settings.json) has no engine field at all — its field_order goes company, accounts, policy, cash_desks and stops.

WHY IT MATTERS NOW. stabler-vevd rewrites create_remittance to the new model. Without a flag there is no way to run the old and new paths side by side, and no way to roll back a tenant that goes wrong. Vehicle Finance learned this the expensive way and it is why stabler-cgf exists.

SECOND, SMALLER TRAP IN THE SAME AREA. public/js/router.js:458 hard-redirects the remittance root to /remittance/new, exactly the shape stabler-cgf is fixing on the installment side. Once a V1 screen exists, a JE-Legacy tenant landing there needs the same engine-aware treatment. Model this bead on cgf.

SCOPE: the flag field on Remittance Settings, a get_engine equivalent, and the gate in the API. NOT the compat wrappers or the legacy teardown — that is the follow-up bead and it depends on this one.

DEPENDS ON stabler-qzr9.11: qzr9.11 asks whether any live transfers are still open under the old model. Backfill-vs-drain IS the question that decides the flag's default and whether a migration is needed, so answer it first.

### capitalized_components matches on free-text description, so netting can silently break
`stabler-6ju` · hata

In stabler/stabler/imports_module/hooks.py, capitalized_components() sums Landed Cost Taxes and Charges by the charge's description field and matches it against the component name ('Uzbekistan Customs Duty', 'Uzbekistan Excise'). It lines up today because build_lcv_payload writes the component name into description, and the docstring justifies the choice: it needs no new field and no migration. But description is free text on a submitted document. If an operator edits or retypes it -- or a future build changes the wording, or a translation reaches it -- the netting in apply_gtd_customs_precedence silently stops matching, 'already capitalized' reads as 0, and the second voucher offers the full customs payment again. That is exactly the double-capitalization 844ea46 was written to stop, returning without any error. Needs a machine-readable marker: a dedicated field on Landed Cost Taxes and Charges (e.g. stabler_component) written by build_lcv_payload and read back here, with description left as the human-facing label. Migration required, so it is not a one-liner. Until then the guarantee rests on nobody editing a text field. Found reviewing 844ea46 before merge, 2026-08-15.

### [epic] Paralel geliştirme disiplini (dal + deploy + temizlik)
`stabler-6ws` · epic

mikas tender işi Antigravity ile ayrı dalda bitirilecek; ben altyapı ve ortak dosyalarda kalacağım. Bunun güvenli olması için deploy'un daldan çıkış yapmasını engelleyen koruma ve yazılı dallanma/birleştirme kuralları gerekiyor. Plan: ~/.claude/plans/optimized-seeking-moore.md

### Imports: msa icin nakliye/hizmet tedarikci gruplarini yapilandir (Part A)
`stabler-78u` · bakım *(devam ediyordu)*

Olcum (msa prod, salt-okunur): Stabler Settings.imports_settings tablosunda MSA icin HIC SATIR YOK, dolayisiyla imports_transport_supplier_groups_for('MSA') bos liste donuyor. Bu fonksiyonun polaritesi TERS (stabler_settings.py:180): bos liste 'bu sirkette ozellik KAPALI' demek. Sonucu uc yuzey birden olu:
  1. set_bill_import_refs (imports.py:8650) Gate 5 firlatiyor: 'Linking a bill to an import is not configured for this company.'
  2. bill_import_link_state -> _not_eligible('') -> PurchaseInvoiceForm.vue:345 paneli sessizce gizliyor
  3. unlinked_transport_bills -> configured:false -> CommercialInvoiceForm.vue toplu link paneli sessizce gizli
msa'da 18 Transporters + 14 Services tedarikcisi var ve PI_WITH_CI=0, CCL_ROWS=0 -- bugune kadar tek bir fatura baglanmamis.
Yapilacak: Stabler Settings > imports_settings altinda company=MSA icin tek satir, imports_transport_supplier_groups = 'Transporters\nServices'. KOD YOK.
Dogrulama: imports_transport_supplier_groups_for('MSA') artik bos donmemeli; bir nakliye PI baglandiginda Container Cost Line dogmali ve LCV'ye TAM BIR KEZ girmeli (rakamla capraz kontrol; 'UI acildi' kanit degil).

**Not:** BLOKE: msa'da Stabler Settings kaydedilemiyor (stabler-9z9). Part A yazımı LinkValidationError ile tümüyle reddedildi; save atomik olduğu için prod DEĞİŞMEDİ (AFTER_ROWS=[]). Önce stabler-9z9'un veri düzeltmesi gerekiyor. Kod tarafı: stabler-45b.
COZULDU (2026-08-14). Onceki BLOKE notu GECERSIZ.

Zafar'in acik onayiyla ('onayliyorum, duzelt ve Part A'yi yaz') msa prod'a iki VERI yazimi yapildi (kod deploy YOK):
1. stabler-9z9 onarimi: frappe.db.set_single_value('Stabler Settings','imports_lcv_expense_account','Expenses Included In Valuation - M')
2. Part A: imports_settings satiri -> {company: MSA, imports_transport_supplier_groups: 'Transporters\nServices'}; ci_supplier_groups BOS birakildi (CI/Proforma secici davranisi birebir ayni kalsin diye).

DOGRULAMA (msa prod, olculdu):
  STEP2_SAVED=ok  (Stabler Settings artik tam-belge save() geciyor)
  LCV_ACCT='Expenses Included In Valuation - M'  LCV_ACCT_EXISTS=true
  TRANSPORT_FOR_MSA=['Transporters','Services']  CI_FOR_MSA=[]
  unlinked_transport_bills('CI-2026-04387') -> configured=true, rows=312, capped=false
  bill_import_link_state('ACC-PINV-2026-01155') -> eligible=true, linked=false, refs 4/4 bos
  Yerel: 144 test yesil (test_lcv_math + test_bill_import_refs_source + test_bill_import_link_state_source + test_ci_bill_link_panel_source)

KALAN: plan dogrulama maddesi 4 (sayisal capraz kontrol) icin msa'da GERCEK bir nakliye PI'i bir CI'ya baglanmali. Hangi faturanin hangi CI'ya ait oldugu bir IS KARARI -> Zafar'a soruldu. Bead bu tek adim icin acik.

GOZLEM (bulgu degil, dogrulanmadi): aday listesindeki satirlar status='Draft' ile docstatus=1 birlikte raporluyor; ayrica dort ardisik ALN faturasi tam 77100.00 USD ve bill_no=null.

### Early-settlement payoff: build the contract-level unearned-markup model (B), not a per-installment amortisation schedule
`stabler-7tva` · iş

Raised by the finance panelist 2026-08-16 and judged the single strongest finding on the table.

The schedule carries one amount per row and the agreement carries one outstanding balance. There is no split of each installment into principal and disclosed-margin (vade farki) components — no amortisation schedule.

Three things are therefore uncomputable, and all three are separate asks that share this root cause:
  1. Early settlement. Closing a contract today needs a payoff figure distinct from the remaining balance. Two defensible policies exist: margin fully earned (no rebate), or margin rebated pro rata to the unexpired term. The design picks neither and the UI has nowhere to show the difference. The screen needs 'Remaining balance' and 'Payoff today' as two separate values.
  2. Provisioning. A doubtful-debt provision is taken on principal at risk, not on gross outstanding, so provisioning against the current field overstates it by the unearned margin.
  3. Revenue recognition. Margin is earned across the term, not at activation. Without the per-row split there is no accrual basis.

Do NOT paint the Operations/Agreement screens on top of this gap: a screen that shows one balance where the business needs two hardens the wrong model and every later slice inherits it.

Decide the early-settlement policy first (a business decision, Zafar), then the data model, then the UI.

**Not:** DECIDED 2026-08-16 by the panel. Option (B): a contract-level unearned-markup value plus the unexpired-term ratio. NOT (A), the per-installment principal/markup split this bead originally assumed.

The three consumers named in the description are all satisfied by (B):
  payoff        the negotiation needs a defensible starting number, not amortisation-grade precision
  provisioning  principal at risk = outstanding balance minus unearned markup, computable at contract level
  revenue       the markup is a fixed disclosed amount, not compound interest, so straight-line earning is defensible — the same pro-rata formula (B) already uses

Policy (a) 'markup fully earned, no rebate' stays REJECTED as a system-enforced rule: the owner measured that it drives the transaction out of the system entirely.

CONDITION ON THIS DECISION — do not skip it. The finance panelist rated the (B)->(A) reversal EXPENSIVE, because reconstructing past installments' split would be retroactive guesswork given partial payments and FIFO. Cheap-now plus expensive-to-reverse is exactly the shape that deserves a mitigation, and here one exists: (B) is a strict information subset of (A), and (A) is derivable from it PROVIDED two things stay true.

  1. The markup-earning rule is written down explicitly and does not change silently. Straight-line over the term is the assumption (B) rests on; if anyone later earns it on a different basis, past periods become underivable.
  2. Allocation history is never deleted or compacted. Which row each payment settled is recorded in Vehicle Finance Payment Application; that record is what makes a later per-row split reconstructable rather than guessed.

Write both into the module docstring when (B) is implemented. With them, the reversal is a migration; without them, the panelist is right and it is guesswork.

SCOPE, now much smaller than filed: a contract-level unearned-markup value (stored or derived — decide which), a payoff figure exposed as a value distinct from the outstanding balance, and a payoff screen that lets the user enter a NEGOTIATED amount with the computed figure shown as the reference. The negotiated amount is the one that posts.

### Tender intake drops the tender title: _clean_intake whitelist omits it
`stabler-ac0` · hata

save_deal_intake (stabler/api/tender.py:1606) runs _clean_intake (tender.py:1280-1300, applied at :1366), which rebuilds a fresh dict from _INTAKE_KEYS_STR / _INTAKE_KEYS_NUM only. Neither whitelist contains 'title' (nor tender_no, source, publication_date, submission_deadline, currency, estimated_total), so every one of those keys sent by TenderMasterDrawer.vue:257 is silently discarded.

Proven on production mikas 2026-08-15 during the tender CRUD live UAT:
GET /api/method/stabler.api.tender.deal_intake?deal=CRM-DEAL-2026-00107&company=Mikas -> HTTP 200, intake object returned with NO 'title' key at all.

User-visible consequence: TenderMasterDrawer.vue:147 seeds form.title from val.organization and :166 only overwrites it when intake.title exists. Re-opening 'Edit tender' therefore shows the CUSTOMER NAME in the required 'Tender Title' field, and saving writes the customer name over the real tender title. Data loss on every edit round-trip.

Not visible on the board because .ds-card-t / #crm-dw-title render _deal_label() (tender.py:1895-1900) = organization, not the title.

Evidence: docs/uat/evidence/2026-08-15-tender-crud-uat/ (UAT-A3-EDIT-OPEN, UAT-A3-EDIT-SAVE both FAIL; screenshots 04_a_edit_drawer.png, 05_a_edit_readback.png).

Out of scope of the approved delete-defect plan - filed separately, needs its own scope decision from Zafar (which of the 7 dropped keys should be persisted, and whether a backfill is needed for existing deals).

### Karar: 12 gunluk root penceresinde okunabilir olan 22 sitenin DB parolalari rotate edilsin mi
`stabler-ake` · iş

stabler-5wx'ten ayrildi. Saldirgan 2026-07-11 ile 2026-08-05 arasinda root'tu; o pencerede /home/frappe/frappe-bench/sites/*/site_config.json dosyalarindaki db_password degerleri okunabilir durumdaydi (22 site). Sizdirildigina dair KANIT YOK -- ama kanit olmadigi da soylenemez, cunku o donemin loglari rotasyonla silinmis (bkz. stabler-b5h).

Karsi agirlik: MariaDB 3306'da disaridan erisilebilir DEGIL (ufw ALLOW IN listesinde 3306 yok, ss'de 0.0.0.0:3306 yok). Yani calinmis bir parola ancak sunucuya yeniden girilirse ise yarar -- ki o durumda zaten site_config.json tekrar okunur. Rotasyonun gercek faydasi sinirli.

KARAR VERILECEK: (a) rotate etme, riski kabul et ve gerekcesini yaz; (b) 7 stabler kiracisi icin rotate et; (c) 22 sitenin tamamini rotate et. (b)/(c) icin her site basina: yeni parola uret, MariaDB'de ALTER USER, site_config.json'i guncelle, bench restart, ping ile dogrula. Kesinti riski gercek -- adim adim ve tek tek.

### Prod: phpMyAdmin kurulumunu ve nginx include'larini kaldir
`stabler-b7v` · iş

Olculdu 2026-08-07. /usr/share/phpmyadmin prod'da KURULU (28 dosya) ve /etc/nginx/conf.d/phpmyadmin.inc dort vhost tarafindan include ediliyor: domains/erpstable.com.ssl.conf, domains/laza.erpstable.com.ssl.conf, domains/silkpay.online.ssl.conf, domains/vmi2692329.contaboserver.net.ssl.conf. php-fpm soketi (/run/php/www.sock) canli.

BUGUN SOMURULEBILIR DEGIL: bes domainin hepsinde /phpmyadmin/index.php -> 404. Sebep, inc dosyasindaki 'alias /usr/share/phpmyadmin/$1' + 'SCRIPT_FILENAME $document_root$fastcgi_script_name' kombinasyonunun bozuk yol uretmesi. Yani koruma degil, KAZA. Tek satirlik bir nginx duzeltmesi ya da paket guncellemesi bunu canlandirabilir.

phppgadmin ise kurulu degil (/usr/share/phppgadmin yok) ama phppgadmin.inc yine de duruyor -- olu.

YAPILACAK: phpmyadmin paketini kaldir (veya /usr/share/phpmyadmin'i tasi), phpmyadmin.inc + phppgadmin.inc include satirlarini dort conf'tan cikar, nginx -t + reload. DB yonetimi zaten SSH uzerinden yapiliyor, web arayuzune ihtiyac yok.

### Vehicle Finance release hardening (Phase 6)
`stabler-br9` · özellik

Five-language translations, module-disabled and wrong-company leakage tests, full role-matrix tests, complete regression suite, documentation and rollout checklist for Vehicle Finance Center Agreement V1.

**Tasarım:** # Phase 6 — Release hardening (FROZEN CONTRACT)

Frozen 2026-08-15. Bead `stabler-br9`. The translation backfill is delegable to
`agy --model gemini-3.6-flash-high` **as a data task only** — but the five CSVs are
shared files, so Claude applies the result in the main tree
(`docs/runbooks/parallel-development.md` §2). Every leakage, permission and
reconciliation test is Claude's.

## Objective and business reason

Everything up to here proves the feature works for the person building it. This phase
proves it is safe for the six tenants who did not ask for it, for the roles that must
not see cost and margin, and for the four languages nobody tests by accident.

## Owner tenant and owner module

Module `installment`; engine `Agreement V1`. **The feature must be invisible and inert
where the module is off or the engine is `Legacy`.** That is the property this phase
measures, not the property it assumes.

## 1. Translations — five catalogs

Every user-facing string from Phases 1–5 ships in **en, ru, uz, uzc and tr** before
push. Harvest first, then fill:

```
bench --site <site> execute stabler.translations.harvest.run
```

Measured constraint that breaks naive tooling: **the catalogs are NOT alphabetically
sorted.** `harvest.py`'s docstring says "sorted"; the real files append in insertion
order (the sorted tail starts around row 5840 of 5847). **Append new keys at the end of
the file.** Inserting them in sorted position produces a diff that touches thousands of
lines and re-conflicts on every merge.

Stage the catalogs as the five explicit paths — never `git add stabler/translations/`,
which pulls the `.tx_*.json` caches.

Deployment consequence to record in the rollout checklist, not to execute here:
a CSV-only change is **not** covered by `bench restart` —
`stabler/www/stabler.py:_load_translations` caches each language map in Redis for an
hour, so the release needs `bench --site <s> clear-cache` on all seven sites.

## 2. Leakage tests — the six tenants who did not ask for this

| Test | Expectation |
|---|---|
| Company with `enable_installment = 0` | Every V1 endpoint raises before reading data; the SPA route guard blocks direct-URL access |
| Company with the module on and `installment_engine = "Legacy"` | Read endpoints work; every write endpoint refuses; the scheduler generates zero work items |
| A `company` argument naming a company the user cannot access | `_assert_company_scope` raises — proven per endpoint, not once |
| A record name belonging to company A, requested with `company = B` | Raises; no field of the record is returned in the error |
| Sidebar / module list for a user in a module-disabled company | Vehicle Finance absent |

The wrong-company test runs against **every** whitelisted endpoint in
`stabler.api.vehicle_finance.v1` by enumeration, so a future endpoint added without a
guard fails this test rather than shipping.

## 3. Role and capability matrix — all of it

Every capability × every role, asserted at the endpoint, not at the button:

| Capability | Roles that pass |
|---|---|
| `view` | all seven |
| `view_cost_margin` | Finance Manager, Reviewer |
| `draft_write` | Contract Clerk, Finance Manager |
| `approve` | Reviewer, Finance Manager |
| `activate` | Reviewer, Finance Manager |
| `collect` | Cashier, Collector, Finance Manager |
| `pay_supplier` | Payables Clerk, Finance Manager |
| `fifo_override` | Finance Manager |
| `cancel_same_day` | Finance Manager |
| `reschedule` | Finance Manager |
| `title_override` | Finance Manager |
| `settlement_writeoff` | Finance Manager |

System Manager and Stabler Admin pass everything. For each capability the test asserts
both directions: an authorized role succeeds **and** an unauthorized role raises. A
one-directional test passes when the guard is missing entirely.

`view_cost_margin` additionally asserts on the **response body**: for a user without it,
the cost and margin keys are absent from the payload, not merely hidden by the
template.

## 4. Regression suite — the acceptance matrix, executed

The full list from the approved plan, each as a named test:

- cash Acquisition; installment Acquisition; cash Disposition; installment Disposition
- VIN uniqueness; one inbound and one outbound chain on the same VIN
- receipt → reservation → delivery → return
- Equal Monthly and Custom schedules; row 0 down payment; balloon; currency precision;
  final-row residual; month-end and leap-year dates
- FIFO partial payment; one payment closing multiple rows; future prepayment;
  supervisor override with a stored reason
- advance before invoice, reconciled after the invoice posts
- same-day cancellation and reversal; historical schedules and applications immutable
- rescheduling with an unchanged legal total; Credit/Debit Note path when the legal
  total changes
- PI/SI, PR/DN, Payment Entry, GL and Tax Template integration
- different bank and account currencies: correct paid amount, received amount and
  exchange rates
- `Partial` **and** `Overdue` displayed together; currency-separated totals
- scheduler deduplication; broken-promise escalation
- module-disabled tenant; wrong-company access; every role's
  read/create/activate/pay/cancel/restructure permission
- Legacy pre/post parity
- no Desk links; MoneyInput / DateInput compliance
- loading, skeleton, empty, inline error and permission-denied states
- direct-route refresh
- 1440px, 1024px, 768px and 390px layouts; keyboard navigation and accessible names

## 5. Reconciliation sweep

`reconciliation_status(company)` runs clean across the whole seeded site: for every
active agreement the active schedule's derived outstanding equals the invoice
outstanding after submitted credit/debit notes and write-offs, and allocated payments
equal the submitted accounting movement. A mismatch **surfaces a blocking
`Accounting sync issue`** — the sweep asserts that a deliberately corrupted fixture
produces one, so the check is proven to be able to fail.

## 6. Documentation and rollout checklist

- `docs/runbooks/vehicle-finance-rollout.md`: the per-company switch procedure, its
  preconditions (module on, policy approved, accounts/items/tax templates configured
  for the direction, `Needs Linking` reviewed), how to verify after the switch, and
  how to switch back to `Legacy`.
- `CLAUDE.md` module table: register `installment` in `_MODULE_ROLES` and note the
  engine gate. This is a shared file — Claude edits it in the main tree.
- The five-gate deploy note: this release changes doctypes and patches, so `migrate`
  must run on **all seven sites**, and translations require `clear-cache` on all seven.
  Documented, **not executed** — production deployment requires separate explicit
  approval from Zafar.

## Forbidden and out of scope

- No production contact of any kind: no SSH, no `deploy_stabler.sh`, no production
  migrate, no `bench restart`, no production data mutation.
- No new formatter, test runner, tracker or deploy script.
- No relaxing of a failing test to make the suite green.
- No tenant-name branching introduced by a "just for the rollout" shortcut.

## Measurable acceptance criteria

1. All five catalogs contain every new key; a spot-read of one new key in each of ru,
   uz, uzc and tr returns a non-empty translation.
2. The enumerated wrong-company test covers every whitelisted V1 endpoint, and adding
   an unguarded endpoint makes it fail — proven by temporarily removing one guard.
3. Every capability has both a positive and a negative role test.
4. Cost and margin are absent from the response body for a user without
   `view_cost_margin`.
5. A module-disabled company and a `Legacy`-engine company both produce zero work
   items and zero V1 writes.
6. `reconciliation_status` is clean on the seeded site, and a corrupted fixture makes
   it raise a blocking issue.
7. `make check` and `make test-bench` are green with a **non-zero, reported** test
   count. State the number of tests that ran and the number that skipped.
8. `make guards` is green: no Desk link, no bare `<input type="date">`, no raw date
   interpolation, no manual `table-striped`, no tenant-name branch, `meta.module`
   present on the parent route, and zero bare `<input type="number">` money inputs.

## Exact verification commands

```
cd /Users/zafar/frappe-bench-local/apps/stabler
make guards
git diff --check
make check
make test-bench
cd /Users/zafar/frappe-bench-local && bench build --app stabler
bench --site genesis-test.local execute stabler.translations.harvest.run
node .claude/workflows/qa-forms.js
```

Report the ACTUAL exit code of each, plus the ran/skipped test counts. **Do not report
"tests passed" if zero tests ran, a fixture failed before the test body, or tests were
skipped** — a previous sweep returned green while 54 of 95 tests self-skipped, and
`make check`'s `test-js` silently skips when the Vitest binary is not executable.

## Required completion report

`status`, `files_changed`, `acceptance_criteria` with evidence, `commands_run` with
exit codes and test counts, `notes` naming every skipped check, and an explicit
statement that production was not touched.

### This app own create_purchase_invoice writes no receipt link, so a supplier can be paid twice
`stabler-ccgu` · hata *(devam ediyordu)*

stabler/api/purchasing.py _apply_invoice_payload (~1134-1157) writes neither purchase_receipt/pr_detail nor po_detail onto invoice items. Consequences, all confirmed against the real code and ERPNext source:

1. A receipt billed through that path keeps per_billed = 0, so it never leaves the unbilled-receipts report.
2. It is INVISIBLE to ERPNext own over-billing check (which maps by pr_detail/po_detail), so a duplicate invoice submits cleanly and the supplier can be paid twice.
3. ERPNext books such an invoice to SRBNB anyway under its "no purchase receipt present" branch, so this app own bill form drives srbnb.difference NEGATIVE by the full receipt value and fires the red reconciliation banner for something the app itself did.

Deliberately NOT fixed inside the unbilled-receipts work: setting item.purchase_receipt switches GL account resolution (erpnext purchase_invoice.py:498-521), collides with the LCV expense-account override at purchasing.py:1152-1163, and needs a UI for choosing which receipt line a bill line settles. That is a feature, not a patch.

DoD: make check AND make test-bench.

**Not:** DURUM 2026-08-17, orkestratör oturumu: (a) ve (b) MAIN'E İNDİ (2bddde1, dal commit'i cb9648c). (c) AÇIK — bu yüzden bead kapatılmadı.

Bağımsız doğrulandı, ilk oturumun raporuna güvenilerek geçilmedi:
  - _carried_receipt_links gerçekten _apply_invoice_payload:1300'de çağrılıyor ve main'in eski halinde hiç yoktu. Planda olmayan üçüncü bulgu gerçek: bir draft'ı AÇIP KAYDETMEK, create_purchase_invoice_from_pr'ın doğru kurduğu bağlar dahil, hepsini sessizce siliyordu. Yani tüm kontrolleri kaldırmanın yolu bir kaydetmeydi.
  - make check exit 0 (cb9648c'de ayrık HEAD ile ölçüldü).
  - test_pi_receipt_link 14/14 OK — ama make check içinde DEĞİL. Modül .github/frappe-free-tests.txt'ye eklenmemiş (dalda da eklenmemişti) ve FrappeTestCase kullanıyor, yani BENCH tarafına düşüyor. Yeri doğru; sadece ilk raporun 'make check yeşil + 14/14 yeşil' ifadesi ikisini aynı koşu gibi okutuyor. Ayrı koşulardan geliyorlar.
  - make test-bench EXIT 0, ratchet OK, ana ağaç TEK elde tutulurken cb9648c'de ölçüldü.

(c) HÂLÂ AÇIK: SPA'da purchase_receipt geçiren bir alan yok, dolayısıyla (b) bugün yalnızca API çağıranları için erişilebilir. Kullanıcıya görünen bir yolu yok.

DEVREDİLMEDİ, ilk oturumun işaret ettiği ve hâlâ geçerli: _apply_invoice_payload sonundaki LCV expense-account override'ı bağlı satırlarda da çalışmaya devam ediyor. Bead'in başından beri gösterdiği çakışma çözülmedi.

NOT — stabler-vha8 bu oturumda açılan bir kopya bead'di ve kapatıldı; verisi stabler-w2dd'ye taşındı. w2dd'nin teşhisi bugün baştan yazıldı: sorun test kararsızlığı değil, tek bench + tek çalışma ağacı üzerinde karşılıklı dışlama olmaması. Ağaç tek elde tutulunca üç farklı dalda üç koşu da aynı sonucu verdi.

### Installment landing redirect must be engine-aware (needs a boot field)
`stabler-cgf` · iş

The frozen stabler-l0m.3 design asks for router.js '' -> /installment/operations and overdue -> operations?view=overdue. Applying that today BREAKS every Legacy-engine tenant:

- Vehicle Finance Settings.installment_engine defaults to 'Legacy' (permissions.py:80-91).
- operations_summary and work_queue both throw 'Agreement V1 is not enabled for this company.' via _guard_view -> _require_agreement_v1.
- The SPA carries no engine flag: stores/session.js:20-105 exposes modules, allowed_modules and cost_visible only.

So a Legacy tenant opening /installment would land on an error screen and lose the Overdue page entirely.

Decision taken in slice 3a: ADD /installment/operations only; leave '' -> /installment/new and the overdue route untouched.

This bead: expose the engine on boot (model it on cost_visible in stores/session.js:31 and the organization.boot payload), then make the landing redirect and the legacy/V1 page choice engine-aware. Backend + router.js, Claude-only.

Also correct the parent stabler-l0m.3 design text: it names stabler.api.vehicle_finance.v1.* but the real paths are read.operations_summary and work.work_queue.

### Tender CRM full CRUD: wire edit mode + delete action
`stabler-cm5` · özellik *(devam ediyordu)*

Wire TenderMasterDrawer edit mode into TenderCrm drawer (Edit button), add oversight-gated Delete, re-gate crm.delete_deal to _require_crm_or_tender so tender-only tenants (enable_crm=0) can delete, complete intake round-trip on edit.

### Refund cash-out has no counted-cash confirmation, and payout has no identity gate
`stabler-ddnb` · hata

Kalan is, stabler-qzr9.14 kapatilirken ayrildi (2026-08-17). Iki eksigin ikisi de PARA HAREKET ETTIREN butonlarda; guvenlik omurgasi (butonlar yalnizca allowed_actions'tan, kod hicbir okumada donmuyor) saglam ve dokunulmayacak.

1. REFUND NAKIT ADIMINDA SAYILAN-PARA ONAYI YOK. RemittanceRefund.vue:1038-1088 adim 3'un tamami: bir uyari, onay izi, posting-date girdisi ve :1074-1078'deki buton - tek kapisi ':disabled="!!busy"'. Dosyada hic checkbox yok (grep checkbox/form-check-input sifir hit). submitComplete (:450-472) yalnizca can(COMPLETE_REFUND) ve busy'ye bakiyor. Yani musteriye nakit iade eden buton, ekran render olur olmaz aktif. Ayni proje ayni deseni payout tarafinda DOGRU yapiyor: RemittancePayout.vue:774-784 cashConfirmed kutusu ve :798'de disabled ifadesinde kullanimi.

2. PAYOUT'TA KIMLIK KONTROLU KAPISI YOK. RemittancePayout.vue:798 ':disabled="submitting || !canPayout || !cashConfirmed || !pickupCode"'. Dosyadaki tek iki kutu deskConfirmed (:702-707) ve cashConfirmed (:774-784); adim 3'un basligi 'Payout desk' (:681), kimlik adimi degil. Alicinin kimligi hic sorulmuyor, dolayisiyla bead'in zorunlu kildigi ucuncu on kosul disabled ifadesinde yok.

3. KOD DOGRULAMA KAPISI BUGUNKU API ILE IMKANSIZ (kismi). Bead 'Pay out butonu kod DOGRULANANA kadar kapali, tiklamadan sonra toast degil' diyor. :798 yalnizca kutunun BOS OLMAMASINI kontrol ediyor. Daha guclu kapiyi kuracak endpoint yok: remittance.js:51-163'te verify cagrisi yok, remittance_commands.py'deki sekiz whitelist'te (363, 519, 674, 737, 912, 957, 1006, 1079) de yok. Dogrulama hala payout_transfer icinde ve yanlis kod tiklamadan SONRA hata satiri olarak cikiyor (:306-315) - bead'in reddettigi sekil. Bu maddeyi kapatmak yeni bir salt-dogrulama endpoint'i gerektirir; deneme sayacini artirmadan dogrulamanin kilit politikasiyla nasil uzlasacagi bu bead'in karar verecegi sey.

4. POSTING ONIZLEMESI EKRANDA DENKLESMIYOR (kismi). RemittancePayout.vue:737-761 iki satirlik 'Effect / Amount' tablosu; borc/alacak sutunu, toplam satiri ve gorunur denklik yok - denklik yalnizca iki ayni rakamla ima ediliyor. Ustelik tam degil: komisyon bacaklari disarida birakilip :766-772'de duz metne cevrilmis.

5. 'Pay refund cash' etiketi yok (kozmetik): buton 'Complete refund' (:1085), kart basligi '3. Pay the money back' (:1040).

DoD: make check.

### Audit CI landed-cost links and design UAT loop
`stabler-hhu` · iş *(devam ediyordu)*

Inspect current PI/CI customs, transport and other-expense implementation; prove whether CI-to-transport references exist; design a realistic UAT suite and a Claude-to-AGY repeatable audit/fix loop.

### Vehicle Finance Center Agreement V1
`stabler-l0m` · epic

Implement the approved Vehicle Finance Center plan: VIN/Serial No Vehicle Unit, acquisition/disposition cash/installment Agreements, immutable flexible schedules, append-only payment applications, Operations/Vehicle 360 UI, legacy compatibility, permissions, tests, and portable stabler-council adapters. Agreement V1 remains disabled by default and is not deployed without accounting/tax approval.

**Not:** Implementation paused by user on 2026-08-15. Priority is a standalone Claude Design-style HTML prototype; no repo implementation files may change before prototype review.
2026-08-15 — PAUSE LIFTED. Zafar approved the product plan and Claude Design V3 (/Users/zafar/Downloads/Vehicle Finance Center v3.html) and issued explicit authorization to implement through tested commits, merge to main and push. NOT authorized: deploy, SSH to prod, prod migrate, bench restart, prod data mutation. Phase 0 discovery complete; contracts frozen into the design field of .1-.5 plus a new Phase 6 bead.
2026-08-15 — Phase 0 complete. Six frozen contracts loaded into bead design fields and verified byte-identical (sha256): l0m.1=Phase1 domain foundation, l0m.2=Phase2 accounting/payment engine, l0m.3=Phase3 production Vue UI, l0m.4=Phase4 work tracking, l0m.5=Phase5 legacy dual-read/rollout, br9=Phase6 release hardening. l0m.6 (portable stabler-council adapters) is NOT Phase 6 and stays out of this epic's scope. No repository file has been created or modified yet; no git mutation; no production contact.
## P1 — epic-level scope gap: the Completed/Terminated lifecycle is assigned to no phase

Adjudicated 2026-08-15 by re-reading the frozen phase contracts.

Phase 1 built the DATA MODEL for an agreement lifecycle:
- design-phase1.md:151  agreement_status Select declares Completed and Terminated
- design-phase1.md:154  terminated_reason (Small Text)
- design-phase1.md:158  settlement_document_type / settlement_document
- design-phase1.md:293  a `settlement_writeoff` capability -> Manager
- design-phase1.md:123  "docstatus 2 reserved for a draft-level mistake ONLY.
                         Terminated does not cancel accounting."

No phase's BEHAVIOURAL contract assigns the transitions:
- design-phase2.md has 17 sections; none is Settlement, Completion or Termination.
- None of phase 2's 8 acceptance criteria mentions complete / terminate / settle.
- design-phase2.md:172-173 — "Repossession is NOT invoice cancellation: use the
  native return document ... and set `title_status = Repossessed`." That is the
  TITLE axis, deliberately not agreement_status.
- grep of design-phase3/4/5/6 for completed|terminat|repossess|settle_agreement|
  lifecycle returns exactly one hit: design-phase3.md:79, a UI element.

Measured in code: agreement_status has exactly two writers repo-wide —
v1.py:467 "Active" (activate_agreement) and v1.py:926 "Restructured"
(approve_reschedule). Nothing anywhere writes Completed or Terminated, and no
test asserts either. There is no settle_agreement / complete_agreement /
terminate_agreement / repossess endpoint, and the settlement_writeoff
capability has no consumer.

VERDICT: this is NOT a phase-2 contract violation — phase 2 delivered exactly
what its contract named, so it does not retroactively block the merged phase 2.
It IS an epic-level planning gap: a fully paid agreement can never reach
Completed, and termination/repossession has no backend transition. Assign it to
a phase (phase 6 hardening is the natural home, or a new child bead) before
release.

### Blocking business question for Zafar — answer BEFORE writing any terminate endpoint
"Terminated is a status, never a cancellation", so a terminated agreement stays
at docstatus = 1. vehicle_agreement._assert_single_direction_per_unit counts
peers with docstatus < 2, so a repossessed vehicle could never carry a second
Disposition agreement — the VIN would be permanently unsellable. Not reachable
today only because nothing sets Terminated. Zafar must choose the rule: does a
Terminated (or Completed) agreement free the direction slot for that Vehicle
Unit, and if so, is the slot freed on termination or on the return document?
2026-08-15 — Second epic-level planning gap found and closed, structurally identical to the recorded Completed/Terminated gap: Phase 1 gave the domain model, Phase 2 gave the WRITE surface, no phase was ever assigned the READ/query surface. Measured: Phase 3's frozen contract names 17 backend resources across 8 screens; only 6 existed (Phase 2's write endpoints). New bead stabler-l0m.7 (Phase 2.5, V1-only for agreement_list/agreement_detail — legacy dual-read stays Phase 5) now sits between Phase 2 and Phase 4 in the dependency chain: l0m.7 → l0m.4 → l0m.3. l0m.3 reverted in_progress → open since it has zero files and cannot proceed until l0m.4 closes.

### Vehicle Finance Operations, Vehicles and Agreements UI
`stabler-l0m.3` · özellik

Build Operations, Vehicles, Agreement list/detail/create/review and Calendar using shared controls and production states.

**Not:** 2026-08-15 — UNBLOCKED. Blockers stabler-l0m.7 (Phase 2.5 read/query surface) and stabler-l0m.4 (follow-up + work queue) are both closed; the bead is in `bd ready`.

Verified 2026-08-15: all 17 backend resources named by the frozen contract are whitelisted and live in stabler/api/vehicle_finance/ — operations_summary, work_queue, vehicle_list, vehicle_detail, agreement_list, agreement_detail, allocation_preview, collect_customer_payment, pay_supplier, cancel_payment, record_promise, log_followup, save_draft_agreement, schedule_preview, activation_preview, activate_agreement, calendar_events. Three further endpoints exist beyond the contract (reschedule_preview, approve_reschedule, reconciliation_status).

Frontend state: still zero V1 Vue files. Only the five legacy pages exist under stabler/public/js/pages/installment/ (InstallmentHome, Contracts, Overdue, InstallmentCalendar, NewContract).

Sizing: 8 screens is an epic, not a micro-task. Slice per screen before starting — the contract itself says one screen at a time. router.js, Sidebar.vue and the five translation CSVs stay in the main tree (Claude), never in an agy worktree.
2026-08-15 — SLICED. Do not work this bead directly; it is now an epic. Work the slices in dependency order:

  stabler-l0m.3.7  (3a) Operations landing + V1 route shell   ← READY, start here
  stabler-l0m.3.8  (3b) Vehicles + Vehicle 360                 ← blocked by 3a
  stabler-l0m.3.9  (3c) Agreements list + read-only drawer     ← blocked by 3a
  stabler-l0m.3.10 (3d) Agreement detail + payment panel  P0   ← blocked by 3c · Claude only, no agy
  stabler-l0m.3.11 (3e) New Transaction four-step page         ← blocked by 3d
  stabler-l0m.3.12 (3f) Calendar                               ← blocked by 3d

Slice IDs run .7-.12 because six earlier create attempts consumed .1-.6 on a prefix-mismatch error (db prefix is 'st-', every existing bead uses 'stabler-'; created with --force to keep the family consistent). Numbering gap is cosmetic.

**Tasarım:** # Phase 3 — Production Vue UI (FROZEN CONTRACT)

Frozen 2026-08-15. Delegable to `agy --model gemini-3.6-flash-high` **per screen**,
one bead slice at a time, only after the Phase 2 API shapes are live and callable.
Claude keeps `router.js`, `Sidebar.vue` and the five translation CSVs — they are
shared files, editable only in the main tree (`docs/runbooks/parallel-development.md`
§2).

## Objective and business reason

Replace the five legacy installment pages with the approved Vehicle Finance Center V3
screens, wired to the whitelisted `stabler.api.vehicle_finance.*` callables. The V3 HTML at
`/Users/zafar/Downloads/Vehicle Finance Center v3.html` is a **visual and interaction
reference only**. Do not copy its bundled React/runtime code into Stabler.

### CORRECTED 2026-08-15 — the dotted paths, measured from the source

This design originally said every screen is wired to `stabler.api.vehicle_finance.v1.*`.
That is **wrong for ten of the twenty callables** and it survived into slice 3a's contract
before being caught. `v1.py` is the money-movement module only. Verified map — use these
exact paths, do not guess and do not assume a callable lives in `v1`:

```
read.operations_summary     read.agreement_detail    read.vehicle_detail
read.agreement_list         read.vehicle_list        read.schedule_preview
read.save_draft_agreement

work.work_queue             work.record_promise      work.log_followup
work.calendar_events

v1.allocation_preview       v1.collect_customer_payment   v1.pay_supplier
v1.cancel_payment           v1.activation_preview         v1.activate_agreement
v1.reschedule_preview       v1.approve_reschedule         v1.reconciliation_status
```

Regenerate this list before each slice with:

```
for f in stabler/api/vehicle_finance/*.py; do m=$(basename "$f" .py); \
  awk -v M="$m" '/@frappe.whitelist\(\)/{w=1;next} w&&/^def /{gsub(/\(.*/,"",$2); print M"."$2; w=0}' "$f"; done | sort
```

## Owner tenant and owner module

Module key stays `installment`. The parent route keeps
`meta: { module: "installment" }`. Behaviour additionally respects
`Vehicle Finance Settings.installment_engine`: `Legacy` renders the existing pages,
`Agreement V1` renders the new ones.

## Stabler UI invariants — QUOTED VERBATIM, non-negotiable

- The SPA never links to the Frappe Desk (`/app/...`) — no `<a href>`, no
  `window.open`, no router meta.
- Every monetary input uses `MoneyInput`; `qty` stays a plain number input.
- Every date input uses `DateInput`; every displayed date uses
  `formatDate` / `formatDateTime` from `composables/date.js`.
- Status badges resolve through `getStatusBadgeClass` in `composables/status.js`.
- Tables are striped globally — never add `table-striped`.
- One `.btn-primary` per visual region.
- Amounts render in their transaction currency only.
- Lists use `ListToolbar.vue` with auto-apply filters and `SkeletonRows.vue`.
- Code is English-first. User-facing strings ship in en, ru, uz, uzc and tr before push.
- Never branch on tenant name.

Measured gap this phase must close: **none of the five existing installment pages use
`ListToolbar.vue` or `SkeletonRows.vue`**, both mandated by `CLAUDE.md`. The rebuild
fixes that.

## Routing

`stabler/public/js/router.js:462-470` today:

```
{ path: "", redirect: "/installment/new" }
new | contracts | overdue | calendar
```

becomes:

> **DEFERRED 2026-08-15 — the two redirect lines below MUST NOT be applied yet.**
> Bead `stabler-cgf` owns them. Applying them today breaks every Legacy-engine tenant:
> `Vehicle Finance Settings.installment_engine` defaults to `Legacy`
> (`permissions.py:80-91`); `_guard_view` → `_require_agreement_v1` throws
> *"Agreement V1 is not enabled for this company."*; and the SPA carries **no engine
> flag on boot** — `stores/session.js:20-105` exposes `modules`, `allowed_modules` and
> `cost_visible` only. A Legacy tenant opening `/installment` would land on an error
> screen and lose the Overdue page entirely.
>
> The two lines held back are the `path: ""` redirect and the `path: "overdue"` redirect.
> Slice 3a (`stabler-l0m.3.7`) therefore **added `operations` alongside the legacy
> children** and left `""` → `/installment/new` and `overdue` untouched. Every later
> slice does the same until `stabler-cgf` exposes the engine on boot.

```
{ path: "",           redirect: "/installment/operations" }   ← DEFERRED, see above
{ path: "operations", name: "vf-operations",  component: Operations }   ← module landing
{ path: "vehicles",   name: "vf-vehicles",    component: Vehicles }
{ path: "vehicles/:name", name: "vf-vehicle-360", component: Vehicle360 }
{ path: "agreements", name: "vf-agreements",  component: Agreements }
{ path: "agreements/:name", name: "vf-agreement", component: AgreementDetail }
{ path: "new",        name: "installment-new", component: NewTransaction }
{ path: "calendar",   name: "installment-calendar", component: Calendar }
{ path: "overdue",    redirect: { name: "vf-operations", query: { view: "overdue" } } }   ← DEFERRED, see above
```

`Overdue` becomes a **saved Operations view**, not a top-level page; the old URL keeps
working via redirect — **once `stabler-cgf` lands**, not before. Existing `contracts`
redirects to `agreements`. No Desk link anywhere.

Every record route reads its **route param**, not the document engine's `isCreate`, in
`onMounted` (`if (docName.value) load()`), so a direct-URL open or a browser refresh
renders the populated record and never a blank "New …" form. This is a named regression
class in `CLAUDE.md`.

## Screens — exact V3 inventory

### Operations (default landing)
Filters: `All directions | Acquisition | Disposition`, `All currencies | USD | UZS`.
Fixed note, rendered literally: **"One currency per agreement — totals are listed per
currency, never summed."** Currency scorecards, metric cards, a `Portfolio` lifecycle
strip, `Saved views` with counts, and the queues: critical overdue, due today, next 7
days, monitoring — each with title, count, note and per-currency totals.

Work table columns: `№ | Direction | Vehicle / VIN | Party | Agreement | Reason |
Outstanding | Due | Owner | Last contact | Next action`, plus three row actions
(primary / second / third). Empty state: `Nothing in this view` + the view-specific note
+ `Back to all work`.

Source: `operations_summary` and `work_queue`.

### Vehicles
Header `{{ vehCount }} vehicles`. Columns: `№ | Vehicle / VIN | Vehicle state |
Acquisition | Sale | Location / possession | Finance state`. VIN cell renders
`{{ vin }} · {{ serial }}`; possession cell renders `Title: {{ title }}`. Row action
`Vehicle 360`. Empty: `No vehicle matches the current filters` + `Clear filters`.

Source: `vehicle_list`.

### Vehicle 360
Back link `All vehicles`. Three status blocks: **Vehicle**, **Title**, **Possession**.
Two legs (acquisition, disposition), each with `Party | Agreement | Total | Paid |
Outstanding | Currency | health | Next due | Down payment` and an `Open agreement`
action; an empty leg renders its own empty text. Sections **Evidence**, **Activity &
audit**, and **Cost & margin** behind a `Role protected` badge with the literal note
**"Legs are held in their own currency — no converted margin is shown."** Cost/margin
renders only when the API says the user holds `view_cost_margin`; the prototype's
"Reveal (simulate Finance Manager)" button is prototype-only and **must not ship** —
the server decides, and hidden numbers are never sent to the client.

Source: `vehicle_detail`.

### Agreements
Header `{{ agrTotals }}` (per-currency, never summed). Columns: `№ | Vehicle / VIN |
Party | Direction | Type | Agreement | Next due | Total | Paid | Outstanding | Payment
state | Owner`. `Partial` is a **secondary** badge next to the payment state — Partial
and Overdue may both be true, and Overdue carries the visual urgency. Row actions
`Preview` (read-only drawer) and `Open`. Search note: **"Search covers agreement ID,
vehicle, VIN and party."**

Source: `agreement_list`.

### Agreement detail
Status blocks: **Agreement**, **Payment health** (+ `Partial`), **Vehicle**, **Title**,
**Owner**. Summary tiles: `Contract total` with the sub-label *incl. down payment*,
`Paid`, `Outstanding`, `Overdue`, `Next due`, `Down payment`.

Actions: the direction-specific pay/collect action, two secondary actions,
`Update next action`, and `Cancel mistaken payment (same day · Finance Manager)` —
rendered only when the API reports the capability.

Payment panel: `{{ payLabel }} — allocation preview ({{ cur }})`,
`Payment amount ({{ cur }})` as a **MoneyInput**, `Contract outstanding`, `Payment`,
`Remaining after payment`, an inline error slot, `Confirm {{ payVerb }}` / `Cancel`.
The preview comes from `allocation_preview` — **never computed in the browser**.

Allocation table, header rendered literally:
**`FIFO allocation — down payment row is settled first`**, columns
`Seq | Due | Row | Outstanding | Allocated | Balance after`.

Schedule table: `Seq | Row | Due date | Scheduled | Paid | Outstanding | Payment health
| Payment Entry`, with a footer line `Schedule total (incl. seq 0)` and the
total-check indicator.

**Separate payable and receivable actions** — an Acquisition screen never shows a
collect button and a Disposition screen never shows a pay button.

Source: `agreement_detail`, `allocation_preview`, `collect_customer_payment`,
`pay_supplier`, `cancel_payment`, `record_promise`, `log_followup`.

### New Transaction — full page, four steps
1. `Transaction type` — `Direction · we buy or we sell` (Acquisition | Disposition),
   `Settlement` (Cash | Installment).
2. `Parties, vehicle & currency` — vehicle typeahead, party typeahead whose label
   follows the direction, `Agreement currency` with the literal note
   **"Fixed for the life of this agreement"**.
3. `Price components` — `Cash price`, `Disclosed markup (fixed)`, `Approved fees`,
   `Tax`, `Down payment (schedule row 0)`, `Agreement total (fixed on submit)`.
   Every one is a **MoneyInput**.
4. `Schedule` — `Equal monthly` | `Custom`, `Agreement / start date`,
   `First installment date`, `Number of installments`, `Balloon (last row)`; rows
   `Seq | Row | Due date | Amount | Note`; `Add row`; footer
   `Schedule total (incl. row 0)` **must equal** the agreement total.

Sidebar: `Summary · {{ cur }}`, `Agreement total`, and an **`Invariants`** list whose
pass/fail comes from `schedule_preview` — the server is the arbiter. Actions
`Save draft` and `Review & activate`, the latter showing
`Documents that would be created` from `activation_preview`.

**Production correction over the prototype:** each Custom-schedule input needs a unique
accessible name, e.g. `Installment 3 due date` and `Installment 3 amount`.

Source: `save_draft_agreement`, `schedule_preview`, `activation_preview`,
`activate_agreement`.

### Calendar
`{{ monthLabel }}`, filters `All | Payable | Receivable` and `All cur. | USD | UZS`,
legend `Overdue | Partial | Upcoming`, month grid, and an `Agenda — {{ monthLabel }}`
list with `{{ count }} item(s)` and per-currency totals. Empty:
`No scheduled movement this month.` Literal note: **"Daily totals are listed per
currency. Clicking an event opens a read-only preview — money movement happens on the
agreement screen."** On mobile the month grid collapses to the agenda.

Source: `calendar_events`.

### Drawer and modal
Drawer carries a `Read only` badge, `Total | Outstanding | Next due | Health`, an
`Open rows` table (`Seq | Due | | Outstanding`), and `Open agreement` / `Close`.
**Drawers are read-only** — every money movement happens on a full page. Modal carries
title, context, optional fields, a warning line, `Cancel` and a confirm label; a toast
reports the result.

## Frontend states — required on every screen

`loading` (SkeletonRows inside the table body, never a spinner in a void) ·
`empty` (the exact V3 empty text and its clearing action) · `error` (inline, with the
server message, never a bare "something went wrong") · `permission-denied` (the action
is absent, not merely disabled, and the screen explains it) · `module-disabled`
(handled by the route guard).

## Forbidden

- **No hardcoded dashboard amounts and no demo record arrays.** Every number comes from
  an API response. Measured precedent: `CommercialInvoiceForm.vue` shipped hardcoded
  `ref()` values that compiled, passed tests, deployed and lied.
- No bulk collect / pay / reschedule. No list multi-select.
- No client-side allocation, total or status computation.
- No Desk link, no `window.open("/app/…")`.
- No edits to `router.js`, `Sidebar.vue` or the translation CSVs from inside a worktree.

## Responsive and accessibility

Verify at **1440px, 1024px, 768px and 390px**. Mobile drawer navigation rows are
`min-height: 40px`; every mobile interactive target is at least 40×40px. The horizontal
module tab strip needs a visible overflow/fade affordance. Keyboard navigation reaches
every action, and every input has an accessible name. Use only the spelling
**Installment**.

## Measurable acceptance criteria

1. Every screen renders from live API data on a seeded local site; grepping the new
   `.vue` files finds no literal amount and no demo array.
2. `make guards` passes — it mechanically checks Desk links, bare `<input type="date">`,
   raw date interpolation, manual `table-striped`, tenant-name branching, `meta.module`
   on parent routes, and bare `<input type="number">` for money v-models (a hard zero
   since 2026-07-27).
3. Direct-URL open and browser refresh of an agreement and a vehicle render populated,
   not blank.
4. The allocation preview shown in the browser is byte-identical to
   `allocation_preview`'s response for the same input.
5. Cost/margin is absent from the network payload for a user without
   `view_cost_margin` — verified in the response body, not just the DOM.
6. Loading, empty, error and permission-denied states are each demonstrable.
7. `bench build --app stabler` succeeds.
8. Layouts verified at all four widths; every Custom-schedule input has a unique
   accessible name.

## Exact verification commands

```
cd /Users/zafar/frappe-bench-local/apps/stabler
npx eslint stabler/public/js/pages/installment --max-warnings=0
make guards
git diff --check
make check
cd /Users/zafar/frappe-bench-local && bench build --app stabler
node .claude/workflows/qa-forms.js
```

Report the ACTUAL exit code of each. Note that `make check`'s `test-js` target
**silently skips** when the Vitest binary is not executable — if it skips, say so
rather than reporting a pass.

## Required completion report

`status`, `files_changed`, `acceptance_criteria` with evidence, `commands_run` with
exit codes, `notes` naming every skipped check.

### Phase 3d — Agreement detail and payment panel (money path)
`stabler-l0m.3.10` · özellik

Slice of stabler-l0m.3. THE RISKY SLICE — money movement, FIFO allocation, capability gating. NOT delegable to agy; Claude implements this in the main thread.

Sources: agreement_detail, allocation_preview, collect_customer_payment, pay_supplier, cancel_payment, record_promise, log_followup.

Status blocks: Agreement, Payment health (+ Partial), Vehicle, Title, Owner. Summary tiles: Contract total (sub-label 'incl. down payment'), Paid, Outstanding, Overdue, Next due, Down payment.

Actions: the direction-specific pay/collect action, two secondary actions, 'Update next action', and 'Cancel mistaken payment (same day · Finance Manager)' rendered ONLY when the API reports the capability.

Payment panel: '{{ payLabel }} — allocation preview ({{ cur }})', 'Payment amount ({{ cur }})' as a MoneyInput, Contract outstanding, Payment, Remaining after payment, inline error slot, 'Confirm {{ payVerb }}' / 'Cancel'. The preview comes from allocation_preview and is NEVER computed in the browser.

Allocation table header rendered literally: 'FIFO allocation — down payment row is settled first', columns Seq | Due | Row | Outstanding | Allocated | Balance after.

Schedule table: Seq | Row | Due date | Scheduled | Paid | Outstanding | Payment health | Payment Entry, footer 'Schedule total (incl. seq 0)' plus the total-check indicator.

Separate payable and receivable actions: an Acquisition screen never shows a collect button, a Disposition screen never shows a pay button.

**Not:** 2026-08-16 — SIRALAMA, risk değil. Zafar remittance rebuild'i bu dilimin önüne aldı, o yüzden P0'dan P1'e indirildi. Dilimin kendisi hâlâ epic'in en riskli parçası (para hareketi, FIFO tahsis, capability gating) ve hâlâ agy'ye delege EDİLMEZ — Claude ana thread'de yazar. Remittance rebuild ilerleyince tekrar P0'a çekilecek.

### Phase 3e — New Transaction four-step full page
`stabler-l0m.3.11` · özellik

Slice of stabler-l0m.3. Sources: save_draft_agreement, schedule_preview, activation_preview, activate_agreement.

Step 1 Transaction type: 'Direction · we buy or we sell' (Acquisition | Disposition), Settlement (Cash | Installment).
Step 2 Parties, vehicle & currency: vehicle typeahead, party typeahead whose label follows the direction, 'Agreement currency' with the literal note 'Fixed for the life of this agreement'.
Step 3 Price components: Cash price, Disclosed markup (fixed), Approved fees, Tax, Down payment (schedule row 0), Agreement total (fixed on submit) — EVERY ONE a MoneyInput.
Step 4 Schedule: Equal monthly | Custom, Agreement/start date, First installment date, Number of installments, Balloon (last row); rows Seq | Row | Due date | Amount | Note; 'Add row'; footer 'Schedule total (incl. row 0)' must equal the agreement total.

Sidebar: 'Summary · {{ cur }}', Agreement total, and an 'Invariants' list whose pass/fail comes from schedule_preview — the server is the arbiter, never the browser. Actions 'Save draft' and 'Review & activate', the latter showing 'Documents that would be created' from activation_preview.

Production correction over the prototype: each Custom-schedule input needs a unique accessible name, e.g. 'Installment 3 due date' and 'Installment 3 amount'.

### Phase 3f — Calendar month grid and agenda
`stabler-l0m.3.12` · özellik

Final slice of stabler-l0m.3. Source: calendar_events.

'{{ monthLabel }}', filters All | Payable | Receivable and All cur. | USD | UZS, legend Overdue | Partial | Upcoming, month grid, and an 'Agenda — {{ monthLabel }}' list with '{{ count }} item(s)' and per-currency totals. Empty: 'No scheduled movement this month.'

Literal note: 'Daily totals are listed per currency. Clicking an event opens a read-only preview — money movement happens on the agreement screen.'

On mobile the month grid collapses to the agenda.

### Phase 3b — Vehicles list and Vehicle 360
`stabler-l0m.3.8` · özellik

Slice of stabler-l0m.3. Sources: vehicle_list, vehicle_detail.

Vehicles: header '{{ vehCount }} vehicles'; columns No | Vehicle/VIN | Vehicle state | Acquisition | Sale | Location/possession | Finance state. VIN cell '{{ vin }} · {{ serial }}', possession cell 'Title: {{ title }}'. Row action 'Vehicle 360'. Empty: 'No vehicle matches the current filters' + 'Clear filters'.

Vehicle 360: back link 'All vehicles'; status blocks Vehicle / Title / Possession; two legs (acquisition, disposition) each with Party | Agreement | Total | Paid | Outstanding | Currency | health | Next due | Down payment and an 'Open agreement' action, each leg with its own empty text; sections Evidence, Activity & audit, Cost & margin behind a 'Role protected' badge with the literal note 'Legs are held in their own currency — no converted margin is shown.'

Hard requirement: cost/margin renders only when the API reports view_cost_margin. The prototype's 'Reveal (simulate Finance Manager)' button MUST NOT ship — the server decides and hidden numbers are never sent to the client.

### Vehicle Finance legacy compatibility and phased rollout
`stabler-l0m.5` · özellik

Keep installment endpoints stable, dual-read legacy flagged invoices, safe linking/backfill reports, feature flags and tenant leakage tests.

**Tasarım:** # Phase 5 — Legacy compatibility, dual-read and phased rollout (FROZEN CONTRACT)

Frozen 2026-08-15. **Mostly NOT delegable.** The dual-read mapping and the parity
proofs are Claude's: this is the phase where an existing production contract can be
made to display a wrong outstanding balance. A bounded Vue slice for the
`Needs Linking` screen may go to `agy --model gemini-3.6-flash-high` after the
read-model is frozen and callable.

## Objective and business reason

Seven tenants already carry live installment contracts recorded by the legacy engine.
Those records must keep working, keep displaying the same numbers, and become visible
inside the new Vehicle Finance Center **without being rewritten**. The new engine ships
switched OFF; a company adopts it deliberately, one company at a time.

## Owner tenant and owner module

Module `installment`. The switch is `Vehicle Finance Settings.installment_engine`,
per company, default **`Legacy`**. There is no global flag and no tenant-name branch.

## The compatibility surface — byte-identical

`stabler/api/installment.py` keeps **every** function and **every** signature it has
today, including `side=buy|sell`:

```
preview_schedule  list_cars      quick_create_item  create_sell_contract
create_buy_contract  list_contracts  contract_detail  collect_payment
cancel_collection  overdue_rows   calendar_events
```

The existing response shapes are **not reinterpreted**. A field that means one thing
today means the same thing after this phase. Acceptance criterion 1 is mechanical:
`git diff stabler/api/installment.py` is empty at the end of Phases 1–5.

New behaviour lives only under `stabler.api.vehicle_finance.v1`.

## What a legacy record is

A legacy record is a submitted Sales Invoice or Purchase Invoice carrying the custom
field `stabler_installment_plan = 1`, with its `payment_schedule` child rows and,
where payments exist, Payment Entries whose `reference_no` starts with `INST-` and
whose `stabler_installment_alloc` JSON holds the allocation.

Legacy truth therefore lives in:
- `tabSales Invoice` / `tabPurchase Invoice` — the legal document;
- `tabPayment Schedule` — `payment_amount`, `paid_amount`, `outstanding` (mutable,
  written by `_apply_collection_to_schedule`);
- `tabPayment Entry.stabler_installment_alloc` — the allocation JSON.

## Dual-read

`agreement_list` and `agreement_detail` return legacy records alongside Agreement V1
records, flagged `record_kind = "Legacy Agreement"`. Rules:

1. **A legacy record is read-only in the new UI.** No activation, no reschedule, no
   FIFO override, no cancel-payment through the V1 endpoints. Money movement on a
   legacy contract continues to go through `installment.collect_payment` and
   `installment.cancel_collection`, unchanged.
2. **Legacy numbers are read from the legacy source, never recomputed.** `total`,
   `paid` and `outstanding` for a legacy record come from the invoice and its
   `payment_schedule` rows exactly as `contract_detail` computes them today. The
   Phase 2 Payment-Application derivation is **not** applied to legacy rows — that
   would be a second, disagreeing definition of the same number.
3. A legacy record has no Schedule Version, no Payment Application and no work item.
   It appears in lists and in Vehicle 360 when linked; it does not enter the Phase 4
   scheduler.
4. Payment health for a legacy row is derived from the same `due_date` / `outstanding`
   comparison the legacy `overdue_rows` uses, so the two screens cannot disagree.

## Linking legacy records to vehicles — `Needs Linking`

A legacy invoice references an Item, and sometimes a Serial No, but the legacy engine
never required a VIN. Therefore:

> **Never guess VIN. Unmatched legacy records remain `Needs Linking`.**

Quoted verbatim into any delegated slice. Concretely:

- A legacy record links to a `Vehicle Unit` **only** when the invoice (or its
  delivery/receipt document) carries an explicit Serial No that resolves to exactly
  one `Vehicle Unit` in the same company. One unambiguous serial → one link.
- Zero matches, more than one match, a serial in a different company, or a serial that
  is not a `Vehicle Unit` → `link_status = "Needs Linking"`. No fuzzy matching on
  model, item code, chassis-looking substrings, party name, amount or date. No
  "closest" anything.
- Linking is a **human action** through a dedicated screen: the user picks the vehicle,
  the server records who linked it and when. It is reversible by unlinking, and both
  events are recorded.
- Linking writes a link field only. It never touches the invoice, the payment schedule,
  the Payment Entries or the GL.

`Vehicle 360` shows a linked legacy record in the relevant leg with a `Legacy` badge
and no V1 actions.

## Backend behaviour and interfaces

Additions to `stabler.api.vehicle_finance.v1` (no change to the frozen list's meaning):

### `agreement_list(company, …)` / `agreement_detail(agreement)`
Accept and return legacy records. Each row carries `record_kind` (`"Agreement V1"` or
`"Legacy Agreement"`), `link_status` (`"Linked"` | `"Needs Linking"` | `"Not applicable"`)
and `available_actions` — which, for a legacy record, contains only read actions.
`agreement_detail` on a legacy name returns the legacy schedule rows in the same shape
the V1 detail uses, so the UI has one renderer, **fed by two sources that are never
mixed inside one record**.

### `legacy_link_candidates(company, invoice_type, invoice_name)`
Returns the explicit serial(s) found on the document and the `Vehicle Unit` each one
resolves to, or an empty list. **It never ranks and never suggests a best guess.** An
empty list is a legitimate, common answer.

### `link_legacy_record(company, invoice_type, invoice_name, vehicle_unit)`
Requires `draft_write`. Validates: the invoice is flagged `stabler_installment_plan`;
the invoice and the vehicle belong to `company`; the vehicle is not already linked to a
different legacy record on the same leg. Writes the link plus `linked_by` / `linked_on`.
Never mutates accounting.

### `unlink_legacy_record(company, invoice_type, invoice_name, reason)`
Requires `draft_write`, `reason` is mandatory, and the previous link stays in history.

### `engine_status(company)`
Returns the company's `installment_engine`, the counts of V1 and legacy records, and
the count still in `Needs Linking`. This is what the rollout checklist reads.

Guard order on every endpoint, unchanged:
`_require_company` → `_assert_company_scope` → `_vehicle_finance_module_enabled` →
`_assert_capability` → `_assert_can_read` / `_assert_can_write`.

Note the deliberate absence of an engine check on the read endpoints: a company on
`Legacy` must still be able to *see* its legacy records through the new list once the
UI is switched on. The **write** endpoints of Phases 1–2 keep their engine check.

## The engine switch

`installment_engine` is per company and defaults to `Legacy`.

- `Legacy` → the V1 write endpoints refuse; the SPA renders the existing pages; the
  Phase 4 scheduler generates nothing.
- `Agreement V1` → new agreements use the new engine. **Existing legacy records do not
  migrate.** They stay legacy forever, readable, payable through the legacy endpoints,
  until they are settled by the ordinary passage of payments.

There is no bulk conversion, no back-fill of Agreements from invoices, and no patch
that writes Agreement rows from legacy data. That is the single most dangerous thing
this phase could do, and it is explicitly out of scope.

Switching a company to `Agreement V1` requires `Finance Manager` and is refused unless
the Phase 2 activation gate's configuration checks pass for that company — otherwise a
tenant flips the switch and every activation then fails at the last step.

## Migration and compatibility requirements

- No patch modifies an existing Sales Invoice, Purchase Invoice, Payment Schedule row
  or Payment Entry.
- The only new patch is the `Vehicle Finance Settings` row creation, which is **lazy**
  (created on first read with `installment_engine = "Legacy"`), not a backfill —
  `patches.txt` carries both `[pre_model_sync]` and `[post_model_sync]` markers, and
  where a patch is registered decides whether the DDL has synced yet — a backfill
  placed in the wrong half would either silently skip or crash on a missing column,
  so lazy creation sidesteps that risk entirely.
- Any patch added here is idempotent and guards with `frappe.db.has_column` /
  `frappe.db.exists`.
- The legacy custom fields `stabler_installment_plan` and `stabler_installment_alloc`
  are **not** removed, renamed or re-purposed.

## Parity proof — the acceptance that matters

Before and after this phase, for every legacy record on a seeded site:

```
grand_total      unchanged
sum(paid_amount) unchanged
outstanding      unchanged
count(rows)      unchanged
```

The test captures the three numbers per legacy invoice into a snapshot, runs the new
read path, and asserts equality **per record**, not on an aggregate — an aggregate can
be right while two records are wrong in opposite directions.

## Forbidden and out of scope

- No VIN guessing, no fuzzy matching, no heuristic auto-link. Ever.
- No rewriting, re-posting or cancelling of legacy accounting documents.
- No back-fill of Agreements, Schedule Versions or Payment Applications from legacy
  invoices.
- No change to any existing `installment.py` signature or response meaning.
- No global engine flag; no tenant-name branch.
- No mixing of the two derivations inside one record.

## Frontend states

The `Needs Linking` screen: `loading` (SkeletonRows), `empty`
(`Nothing needs linking` — a legitimate steady state), `error` (inline),
`permission-denied` (the link action is absent). A legacy row anywhere in the UI carries
a `Legacy` badge resolved through `getStatusBadgeClass`, and its V1 actions are
**absent**, not disabled-with-a-tooltip.

## Edge cases

- A legacy invoice whose serial matches a `Vehicle Unit` in a *different* company →
  `Needs Linking`, never linked.
- A legacy invoice with two serials → `Needs Linking` (one agreement = one vehicle).
- A vehicle already carrying a V1 acquisition and a legacy disposition → allowed; they
  are different legs.
- A legacy invoice that is cancelled (`docstatus = 2`) → excluded from the lists, as
  the legacy screens exclude it today.
- A company on `Agreement V1` with unsettled legacy records → both kinds listed
  together, each with its own `record_kind`.
- A legacy payment recorded *after* the company switched to `Agreement V1` → still goes
  through `installment.collect_payment`, still updates the legacy schedule, still shows
  the same numbers.

## Measurable acceptance criteria

1. `git diff stabler/api/installment.py` is empty.
2. Per-record parity: `grand_total`, paid and outstanding are identical before and
   after, proven per invoice on a seeded site.
3. A legacy record exposed through `agreement_detail` offers zero write actions, and
   calling a V1 write endpoint with a legacy name raises.
4. `legacy_link_candidates` returns an empty list for a record with no explicit serial,
   and the record's `link_status` is `Needs Linking`.
5. No code path links a record automatically — proven by a test that seeds an
   ambiguous record and asserts it stays `Needs Linking` after a full list read.
6. A company defaults to `installment_engine = "Legacy"`, and a V1 write endpoint
   refuses on that company.
7. Switching the engine changes no existing record — record counts and the three
   parity numbers are identical either side of the switch.
8. Module-disabled and wrong-company arguments raise before any data is read.

## Exact verification commands

```
cd /Users/zafar/frappe-bench-local/apps/stabler
python -m pytest stabler/tests/test_vehicle_finance_legacy.py -q
cd /Users/zafar/frappe-bench-local && bench --site genesis-test.local run-tests --module stabler.tests.test_vehicle_finance_legacy_parity
cd /Users/zafar/frappe-bench-local/apps/stabler && make guards
git diff --check
make check
make test-bench
```

Report the ACTUAL exit code of each. **Do not report "tests passed" if zero tests ran,
a fixture failed before the test body, or tests were skipped.**

## Required completion report

`status`, `files_changed`, `acceptance_criteria` with evidence, `commands_run` with
exit codes, `notes` naming every skipped check.

### Portable stabler-council adapters
`stabler-l0m.6` · özellik

Create canonical council package, generated Claude/Codex/Gemini/GLM/ChatGPT adapters and hash-based drift check.

### Nothing creates Remittance Settings or the three GL accounts it requires per Company
`stabler-mwp5` · iş

GO-LIVE BLOCKER. Measured 2026-08-17 at HEAD da48010, with three corrections to the original claim.

THE GAP. remittance_settings.json:24-26 carries reqd 1 on all three account fields — this is SHIPPED CODE, not a plan intention (bead qzr9.6, commit ae23dda). And remittance_accounting.py throws individually for each missing piece: :100-103 'Remittance is not configured for {0}', then :120-121, :129-130, :134-136 for a missing receiver-obligation, deferred-commission and commission-income account.

Grepping stabler/patches/ for receiver_obligation, deferred_commission or commission_income returns ZERO. No patch, no fixture, no install hook, no maintenance seeder creates them. Refutation attempts that failed: stabler/fixtures/ holds only vertical_packs; hooks.py declares no fixtures, no after_install and no after_migrate (only before_tests at :81).

So on every Company today, the FIRST registration attempt throws. Nothing downstream notices until someone tries.

SCOPE CORRECTION — the unit is per COMPANY, not per site. enable_remittance lives on Stabler Company Modules (stabler_company_modules.json:143-149, default 0) and is read at api/organization.py:98. Patch v13 backfilled pre-existing rows to 1, so the real work list is 'every Company with enable_remittance on', which may be more or fewer than the 7 deploy sites.

TENANT-LIST CORRECTION — the deploy skill names 7 sites (anjan, dts, horeca, laminor, mikas, msa, smartbox). An earlier note in this session claimed 8 including 'zuma'; grepping the tree for zuma returns zero hits. Separately, stabler-q14t claims prod really does carry 8. Resolve that against the live bench before counting, and do not take either number from a document.

SCOPE: DATA AND PROVISIONING ONLY — explicitly not doctype work. qzr9.6 already built the doctype, the three fields and the cash_desk_accounts child table. Include the one-time USDT Currency Exchange seed here; the RECURRING monthly rate is a separate bead because it fails differently, silently and later.

SEQUENCING: stabler-wgnh proposes replacing the single receiver_obligation_account Link with a per-currency child table. If wgnh lands first, this bead provisions a different shape — so either depend on wgnh or freeze the current shape explicitly.

NEEDS A BUSINESS ANSWER FIRST: the plan's own Assumptions section says the GL account mapping requires local accounting approval before go-live. Provisioning the wrong accounts across every tenant is expensive to undo.

### stabler-deploy runbook says 7 stabler sites; production has 8 — zuma is missing
`stabler-q14t` · hata

Measured on prod 2026-08-16 during the qzr9.5 deploy, by enumerating every site and
grepping `bench --site <s> list-apps` for stabler:

  anjan, dts, horeca, laminor, mikas, msa, smartbox, zuma   <- eight

`.claude/skills/stabler-deploy/SKILL.md` names seven and omits zuma.erpstable.com. It
repeats "all 7 sites" for both the per-site steps: `bench migrate` (step 5) and
`bench --site <site> clear-cache` (step 7).

Why it matters: rsync and restart are bench-wide, so zuma receives the CODE regardless.
migrate and clear-cache are per-site. Following the doc literally ships zuma new code
without its DDL and without clearing its Redis translation cache — exactly the failure
the doc itself documents as the 2026-07-18 msa near-miss.

This deploy included zuma manually; v86 applied on all eight (zuma returned early, it
does not carry the stabler_pickup_code custom field).

Fix: correct the site list and both "all 7" counts in the skill. Better, replace the
hardcoded list with the enumeration command so it cannot drift again:
  for s in $(ls sites); do bench --site $s list-apps 2>/dev/null | grep -q '^stabler' && echo $s; done
Also check whether docs/runbooks/ and deploy_stabler.sh carry the same stale list.

### Remittance Operations Center — rebuild to the ADR model
`stabler-qzr9` · özellik

Rebuild the remittance module to the model locked in docs/plans/2026-08-16-remittance-operations-center.md (ADR-002 … ADR-009) and reviewed in docs/plans/2026-08-16-remittance-design-council-decision.md.

The July backend (patch v33, JE-only Register/Payout/Refund) does not match this model: no single commission_pct, no frozen triple, obligation not valued at principal, no settings doctype, no cash-desk account mapping, single-step refund, no allowed_actions, no idempotency. The frontend has no Payout or Refund screen at all.

Design prototype (accepted, verified by measurement): scratchpad design_v2/Remittance Operations Center v2.html. Design prompt of record: docs/plans/PROMPT_remittance_design_v2.txt.

Zafar ordered this AHEAD of the Vehicle Finance slices (2026-08-16).

**Not:** 2026-08-16 (birleştirme oturumu 2b92e3c7) — iki oturum tek yerde toplandı.

DESIGN PROTOTYPE — KALICI YOL. Epic açıklamasındaki 'scratchpad design_v2/…' yolu
5b26d484 oturumuna aitti ve /private/tmp altındaydı (silinebilir). Tüm klasör
kopyalandı:
  ~/Downloads/stabler-design_v2-2026-08-16/
Kabul edilen prototip: 'Remittance Operations Center v2.html' (self-contained),
düzenlenebilir kaynak '.dc.html', değişiklik kaydı
'Remittance Operations Center v2 - change log.md'.
Aynı klasörde Vehicle Finance Center v3 ve Imports form mockup'ları da var.

BAĞIMLILIK GRAFİĞİ DÜZELTİLDİ. Bu epic'in 14 çocuğu ters yönde bağlanmıştı:
her kenar erken görevden geç göreve gidiyordu (API frontend'e, frontend i18n'e,
P0 güvenlik yaması tüm yeniden yazıma bağlıydı). Tek açık iş .17 idi — henüz
var olmayan string'lerin çevirisi. 18 kenar silindi, 19 doğru kenar eklendi,
bd dep cycles temiz. Yeni sıra:
  .5 (bağımsız, P0 canlı açık) · .6 → .7 → {.8 → .9} → .10 → {.12 .13 .14 .15 .16} → .17 → .18
  .11 (mevcut JE kayıtlarının göçü) .7'den sonra, .18'den önce.

### Audit and migrate the existing JE-only remittance transfers
`stabler-qzr9.11` · iş

OPEN QUESTION Zafar has not answered: are there live transfers registered under the old model and still awaiting payout?

First step is a count per tenant, not a migration. Only then decide: backfill the new Remittance Transfer master from the existing JE chain, or drain the old ones through the old code path and start the new model clean.

Whatever is chosen, an old-model transfer must never open in a new-model screen with missing fields.

### Remittance UAT and production go-live gate
`stabler-qzr9.18` · iş

Acceptance tests from the plan, run against a live bench: cross-currency register/payout/refund all balancing in base; rate changed between register and payout leaves a zero obligation balance; concurrent payout vs refund; 5-attempt lock and manager unlock; idempotent replay of register/payout/refund; a Cashier never sees Approve refund.

STANDING GATE, not a task step: production deploy requires explicit approval from Zafar. One bench restart blips all seven tenants.

OPEN POLICY QUESTION that must be answered before go-live, not after: the model verifies receivers by name plus pickup code with no KYC. That was decided under a domestic branch-network assumption. Tashkent / Istanbul / Dubai / Moscow is cross-border money transfer.

**Not:** KABUL TESTİ LİSTESİ EKSİK — 2026-08-17'de ölçüldü, ayrı bead yerine buraya katlandı.

Bu bead'in adlandırdığı testler eşzamanlılık, 5 deneme kilidi, idempotent replay ve 'bir Cashier Approve refund görmez' kapsıyor. Planın :486-491 arasında şart koştuğu ŞU DÖRDÜ HİÇBİR YERDE YOK:

1. enable_remittance modül-kapalı kontrolü. Ölçüldü: remittance API'si enable_remittance'ı HİÇ kontrol etmiyor. Modül kapalı bir tenant'ta doğrudan API çağrısı geçer.
2. Yanlış-şirket sızıntı testi (direct API).
3. a11y / klavye erişimi.
4. Responsive: 1440 / 1024 / 768 / 390 px.

EV PRECEDENTİ: Vehicle Finance'in ikizi stabler-br9 ilk ikisini açıkça taşıyor ('module-disabled and wrong-company leakage tests, full role-matrix tests'). Remittance'ın karşılığı yoktu — artık bu bead.

DİKKAT: br9'da da a11y satırı YOK. Yani a11y/responsive kabul kriteri tüm repo'da sahipsiz; burada remittance için sahipleniliyor, Vehicle Finance tarafı hâlâ açıkta.

Ayrıca bu bead'in blokçularına stabler-mwp5 (tenant başına GL hesapları ve Remittance Settings satırı) eklenmeli — canlıya çıkış engeli ve bu bead onu saymıyordu.

### Imports: /money/expenses uzerinden girilen CI gideri Landed Cost'a ulassin (Part C)
`stabler-tir` · özellik *(devam ediyordu)*

Olculen kod boslugu: /money/expenses ekraninin CI damgasi YAZILIP HIC OKUNMAYAN olu bir etiket. Dort bagimsiz kanit: (1) Container Cost Line alanlari yalniz purchase_invoice tasiyor, (2) lcv_math LCV satirlarini yalniz Container Cost Line'lardan kuruyor, (3) _related_import_bills (imports.py:3507) yalniz FROM tabPurchase Invoice okuyor, (4) msa prod JE_WITH_CI=0.
Tasarim karari: kaynak doctype Journal Entry DEGIL, Import Expense. Cunku Import Expense zaten CI/konteyner/kamyon tasiyor, zaten calculate_ci_cost_overview'in expenses kaynagi (listeleme yarisi bedava), zaten JE'yi journal_entry alaninda tutuyor ve _post_expense_kasa_entry (imports.py:2681) tam ters yonu kurulu birakmis.
C1: /money/expenses CI secildiginde (ve imports modulu acikken) karsilik gelen Import Expense dogar; journal_entry dolu oldugu icin _post_expense_kasa_entry idempotency guard'i IKINCI BIR JE POSTALAMAZ. CI bossa tek satir kod calismaz -- davranis byte-identical.
C2: Container Cost Line'a import_expense Link alani + idempotent has_column-korumali patch; 7 sitede migrate (once table_exists).
C3: imports.py:8580-8646 cekirdegi _capitalize_import_cost(...source_field, source_name) olarak cikarilir; _capitalize_linked_bill ince sarmalayici olur, PI yolu bit duzeyinde degismez.
C4 (KRITIK): lcv_math 170/178/222 satirlarindaki ln.get('purchase_invoice') testi 'bu satir bir belgeden mi geldi?' anlamina genisletilir. Yapilmazsa Import-Expense kaynakli satirlar 'elle yazilmis' sayilir, vouchered_hand_line gercek bir PI linkini bloklar ve supersede_billed yanlis tarafi ezer. MUTASYON TESTIYLE pinlenir.
C5: set/clear_expense_landed_cost, set_bill_import_refs'in dokuz kapisini yansitir; Gate 5 yerine HESAP-TIPI kapisi (borc hesabi 'Expenses Included In Valuation' olmali, yoksa maliyet iki kez duser) ve operator onayindan gecen cost_component (muhafazakar harita: Transport->Cross-Border Transport, Insurance->Insurance, DIGER HER SEY->Other).
Risk: YUKSEK (para matematigi + stok degerleme + de-duplikasyon) -> agy'ye DEVREDILMEZ, Claude ana thread.

**Not:** C2 (Container Cost Line.import_expense), C3 (hooks build from both sources), C4 (lcv_math SOURCE_FIELDS), C5 (set_/clear_expense_landed_cost + valuation-account gate + cost_component map + 37 mutation-verified tests) committed as bf4e6c3 on feat/imports-expense-landed-cost. Remaining: C1 (money.py submit_expense_entry spawns Import Expense; Expenses.vue CI-dependent category + default valuation account), i18n backfill in 5 catalogs, bench build. NOT deployed - needs Zafar's approval.

### Receiver obligation is one account, but receive currency varies per corridor
`stabler-wgnh` · iş

Remittance Settings carries a single receiver_obligation_account (Link, one row per company). ADR-006 says the obligation is carried in the RECEIVE currency. An ERPNext Account holds exactly one account_currency, so one field can serve exactly one receive currency.

Measured 2026-08-17 in erpnext/accounts/doctype/journal_entry/journal_entry.py:955 — validate_multi_currency OVERWRITES each row's account_currency from the Account record. So posting a EUR obligation leg to a UZS account does not fail; it silently reinterprets the EUR figure as UZS. That is a silent money bug, not a validation error.

stabler-qzr9.9 therefore verifies the account currency in resolve_accounts() and THROWS when the transfer's receive_currency does not match the configured obligation account. That is correct-by-failure: a tenant can register USD->UZS today only if its obligation account is in UZS, and a second receive currency is refused with a message naming the mismatch.

The fix is a per-currency obligation account, the same shape cash_desk_accounts already uses: a child table (currency, account) on Remittance Settings plus a get_obligation_account(company, currency) resolver, replacing the single Link field. Same question applies to deferred_commission_account and commission_income_account, which qzr9.9 requires to be BASE-currency accounts (the worked example at plan lines 189-201 is consistent with that, since its base currency is the send currency).

Doctype change + migration, so it is not part of the accounting bead. Needed before any tenant runs more than one receive currency.

### Register writes no expires_at — the Expired and Expiring<12h queues have no writer
`stabler-xhv1` · hata

Found 2026-08-17 while implementing stabler-vevd (the register command).

remittance_transfer.json carries expires_at (Datetime). stabler-vevd's register_remittance sets operational_status, verification_status, registered_by, registered_at and the pickup code hash — but deliberately NOT expires_at, because the only expiry number configured anywhere is Remittance Settings.default_quote_expiry_hours, and a QUOTE expiry is not the same thing as a PICKUP deadline. Writing one from the other would put an invented policy number into a money flow.

Consequence: expires_at is NULL on every transfer the new command registers. Three consumers named in the design have nothing to read:
  - the 'Expiring < 12h' queue (ops-center bead)
  - the 'Expired / refund required' queue
  - the 'Expires at' row of the quote panel (NewRemittance design)
and operational_status 'Expired' has no writer at all, the same defect shape as stabler-2671 for Vehicle Agreement.

DECIDE, then implement in the register command:
  (a) expires_at = registered_at + default_quote_expiry_hours, i.e. the quote hours ARE the pickup deadline — then rename the settings field, it is lying about its scope; or
  (b) a separate pickup-validity policy field on Remittance Settings, and Zafar picks the number; or
  (c) transfers do not expire and the two queues plus the Expired status come out of the design.

NOT the same as the lockout bead ('does a pickup-code lockout expire, or is manager unlock the only exit'): that one is about code_locked / lockout_minutes after failed attempts. This is about the transfer's own deadline.

### make test-bench never runs the CRM integration modules
`stabler-ytx` · hata

TEST_SITE defaults to genesis-test.local, which does not have the crm app installed. CRM Deal, CRM Organization and CRM Deal Status tables are absent, so test_crm_deal_trash_integration skips every test - 10/10 skipped, exit 0, reported as OK.

This means the integration module that shipped with the CRM Stage Event fix has never actually executed under the DoD command. It only runs against the local 'stabler' site (crm 2.0.0-dev installed, allow_tests true), where it passes 10/10.

A skip that reports OK is exactly the false green the module's own docstring warns about. Options: install crm on genesis-test.local, add a second TEST_SITE for crm-bearing modules, or make the Makefile fail when a bench module skips everything.

Related pre-existing red, unrelated to CRM and confirmed by stashing: test_supplier_quotations_api (import error in api/purchasing.py:21) and test_tender_flow_contract:167 (asserts ':deal="null"' in CRM.vue).

**Not:** MEASURED on genesis-test.local at HEAD cb5871d (not estimated):

Scale: BENCH_TESTS resolves to 50 modules, not 15. CLAUDE.md ('the other 15 modules') and Makefile:150 ('these 15 need a real site') are both stale. Derived list is correct; the prose is not.

Coverage: 387 tests ran, 13 skipped = 3.4% of bench assertions never executed. THREE modules assert nothing while the gate reports OK, from three different causes:

1. test_crm_deal_trash_integration - 10/10 skipped. Cause: crm app not installed (tabCRM Deal, tabCRM Organization, tabCRM Deal Status absent).
2. test_related_documents_integration - 3/3 skipped. Cause: NOT a missing app - no seeded fixture data ('referansli Payment Entry yok - ciplak site'). Installing crm does not fix this one.
3. test_deploy_migrate_gate - collects ZERO tests. 'class TestDeployMigrateGate:' does not subclass TestCase, so unittest collects nothing; no 'Running N tests' line, no 'Ran N tests', exit 0. It is also excluded from the frappe-free list, so this module runs in NO gate at all. Static AST scan: the only such class among the 50.

So the banner cannot key on 'app not installed' alone. The honest predicate is 'this module asserted nothing': ran==skipped, or zero tests collected.

HAS_COLUMN QUESTION (answered, guard unchanged):
Is there a path to frappe.db.has_column in clear_deal_automation_activities on a site without crm (3 of 7 stabler sites)? No, for two independent reasons, both proven on genesis-test.local (crm absent):
  bench execute frappe.db.has_column --args '["CRM Activity","custom_rule_name"]' -> true, no exception
  bench execute frappe.db.has_column --args '["CRM Deal","name"]'                 -> TableMissingError
CRM Activity is a stabler-owned doctype (stabler/stabler/doctype/crm_activity/), so its table exists on every migrated stabler site regardless of crm. The rule's TableMissingError hazard applies to probing a FOREIGN app's table, which this guard does not do. Second reason: the handler is dispatched only from doc_events['CRM Deal']['on_trash'], which cannot fire where CRM Deal does not exist. Guard stays as written; no test change.

### Legacy remittance endpoints and screens have no owner — plan says wrap, qzr9.10 says replace
`stabler-zm7y` · iş

Split out of the engine-flag work by an explicit dedupe pass, 2026-08-17. The flag is the switch; this bead is what the switch selects between.

THE CONTRADICTION, both sides verified:
  plan line 473 requires the old endpoint signatures to survive
  stabler-qzr9.10 says it 'replaces the July endpoints'
  stabler-vevd explicitly disclaims it: 'compatibility wrappers are their own bead'
So the work is asserted by one document, denied by another, and owned by nobody.

UNOWNED SURFACE in stabler/api/remittance.py:
  remittance_accounts   :223
  list_corridors        :249
  create_remittance     :258
  payout_remittance     :455
  refund_remittance     :555
  list_remittances      :651
  remittance_detail     :722
plus three legacy Vue pages under public/js/pages/remittance/.

ALREADY BROKEN, INDEPENDENT OF THE REWRITE. list_corridors at :249 is still called from public/js/pages/remittance/NewRemittance.vue:147, but ADR-009 deleted the Remittance Corridor doctype and no such doctype exists anywhere in the tree. That is a live orphan today, not a future concern — check what that endpoint actually returns before deciding whether the screen is currently degraded.

ALSO ORPHANED BY THE REWRITE, worth measuring here: list_remittances at :651 is raw SQL over tabJournal Entry, and public/js/pages/remittance/RemittanceTransfers.vue:122,164 renders a StatusBadge with doctype 'Remittance Transfer' against a Journal Entry docstatus — a badge named after a doctype the app never reads.

SCOPE: decide per endpoint whether it is wrapped, deprecated behind the engine flag, or deleted; then do it. Retire or migrate the legacy Vue pages the same way.

BLOCKED BY the engine flag bead — you cannot deprecate a path before there is a switch to select the other one.

## P2 — orta

### Digest guard asserts permlevel 1 instead of deriving it from the field
`stabler-16kc` · iş

Found 2026-08-17 by an adversarial review of the narrowed guard in stabler/stabler/doctype/remittance_transfer/remittance_transfer.py (_assert_new_rows_carry_the_code_digest).

THE ASYMMETRY. Frappe decides whether to reset a field with 'df.permlevel not in has_access_to' (frappe/model/base_document.py:1479). The guard instead asserts the level IS 1: 'any(cint(level) == 1 for level in self.get_permlevel_access("write"))'. Those agree only while pickup_code_hash sits at permlevel 1.

WHY THAT IS REACHABLE WITHOUT A CODE CHANGE. permlevel is a customizable DocField property (frappe/custom/doctype/customize_form/customize_form.py:773 lists it in docfield_properties as Int) and Meta.apply_property_setters (frappe/model/meta.py:436-444) casts it onto df.permlevel at runtime. So a System Manager can move the field to permlevel 2 through Customize Form.

FAILING SCENARIO. Field moved to permlevel 2; v89's DocPerm rows stay at permlevel 1. A Remittance Cashier registers. get_permlevel_access('write') == [1]. Frappe sees 2 not in [1] and blanks the digest. The guard evaluates 'is 1 in [1]' -> True -> returns silently. Cash is taken, the transfer registers, and payout later throws 'has no usable pickup code on file' permanently. The pre-narrowing guard caught this; the narrowed one does not.

Judged P3 in review, not P2: it needs a deliberate Property Setter on a hidden read-only hash field, and nothing in the repo does that today. Filed rather than fixed inline because the principled fix -- derive the level from self.meta.get_field('pickup_code_hash').permlevel -- costs the frappe-free fake in stabler/tests/test_remittance_transfer_doctype.py a meta stub, which is a wider change than the bug being fixed there warranted.

NOTE the same hardcoding exists in stabler/patches/v89_remittance_pickup_hash_permlevel.py. Fix both or neither.

DoD: make check.

### make check can pass or fail on stale bytecode after a same-length edit
`stabler-5er6` · iş

Measured 2026-08-17 while mutation-testing reconciliation_comparable. Replacing >= with <= or == keeps the source file byte-length identical; CPython timestamp+size .pyc invalidation did not fire, so the suite executed the OLD bytecode while the source on disk was correct. Symptom: make check reported failures that contradicted the source, and an earlier mutation run reported identical failure counts for three different mutations — all of them actually running one cached build.

Effect on the gate: a green make check is not by itself proof after an edit that does not change file length. Options: run the unit passes with python3 -B, or purge __pycache__ in the test target, or set PYTHONDONTWRITEBYTECODE for the suite.

Not fixed inline because it changes the shared gate for every branch.

DoD: demonstrate the failure, then show the same mutation being caught after the fix.

### Translation catalogs are not in Python sorted() order — the first harvest after the LF fix still rewrites ~6477 rows
`stabler-5ql8` · iş

Measured 2026-08-17 while closing stabler-abs7 (harvester CRLF fix, commit 3965fa0).

abs7 removed the CRLF rewrite. A harvest run should now be a no-op on unchanged keys.
It is not: the first run still rewrites ~6477 of the 6493 rows in each of the five
catalogs, because the ORDER the rows are committed in is not the order Python's
sorted() produces. The catalogs are case-insensitively sorted by hand (and by every
insertion script this repo has, including the one used for the Wave 1 strings);
harvest.py re-sorts with plain sorted(), which is codepoint order — so uppercase,
lowercase and non-ASCII msgids land in different places.

CONSEQUENCE: the conflict class abs7 was filed to kill survives one more time. Anyone
who runs harvest before this is normalized ships a 6477-line diff and re-conflicts with
every open branch that touched a catalog.

SCOPE: one normalization commit that rewrites all five catalogs into whichever order is
chosen, plus a decision on WHICH order is canonical:
  (a) make harvest.py sort case-insensitively (key=str.casefold) to match what is
      committed today, and leave the files alone — smallest diff, keeps the catalogs
      human-scannable; or
  (b) re-sort all five files into plain sorted() order and keep harvest.py as is —
      one 6477-line commit now, and every future hand-insertion must use codepoint
      order or the churn comes back.
(a) is the recommendation: the committed order is the one humans and every insertion
script already produce.

Whichever is chosen, land it on a quiet tree with no open catalog branches — the
normalization commit conflicts with everything by construction.

DoD: make check, plus running harvest on a live bench and confirming the diff is empty
for unchanged keys.

### PurchaseReceipts.vue uses the any-invoice predicate and hides partly-billed receipts
`stabler-by0h` · iş

stabler/public/js/pages/purchasing/PurchaseReceipts.vue:163-168 treats any invoice (draft or submitted) as "billed", which is the same defect the unbilled-receipts draft guard deliberately avoids: a partly-billed receipt still carries unbilled exposure and must remain actionable.

Explicitly do NOT "align" the newer unbilled-receipts page to this one — that would propagate the defect. Fix this page to the docstatus-aware predicate instead.

DoD: make check AND make test-bench.

### Sticky per-user defaults for commission_pct and exchange rate
`stabler-dbbh` · özellik

Split out of stabler-qzr9.8, which shipped the frappe-free pricing engine only.

ADR-009 says the cashier types commission_pct and the rate — no tariff record, no corridor — and that both should come back pre-filled next time. No such mechanism exists in the app: frappe.defaults.get_user_default is used for Company only (customer_hooks.py:166, api/payment_import.py:279, api/sales_import.py:349), and useListViewState.js keeps list state in localStorage, not form values.

So this needs a real decision + storage: per-user (and probably per origin desk + per currency pair) last-used commission_pct and rate, written on successful register and read when the register screen opens. Touches the DB, so it is out of scope for a frappe-free bead and make check alone will not prove it.

Blocked-by nothing in principle, but it only becomes visible once the register screen exists (stabler-qzr9.10 / the frontend slices).

### Prove on a real ledger that re-stamping a draft LCV re-spreads the charges
`stabler-dblq` · iş

Follow-up to stabler-xvsn (fixed in ab4a84e), which re-stamps a draft Landed Cost Voucher with the operator's chosen distribution basis and saves it so ERPNext redistributes.

The claim 'saving redistributes' is currently supported by reading erpnext/stock/doctype/landed_cost_voucher/landed_cost_voucher.py:89 (validate -> set_applicable_charges_on_item, which reads distribute_charges_based_on) and by a fake voucher in stabler/tests/test_lcv_distribution_restamp.py whose save() only records that it was called. A fake can be told to agree with anything.

This is the same reason test_remittance_accounting_bench.py exists: the arithmetic is provable without a bench, but that ERPNext leaves it alone is not, and ERPNext is the half that fails silently.

SCOPE: a bench test that builds a draft LCV on one basis against a real Purchase Receipt with at least two items of different value-per-qty, reads the per-item applicable_charges off the draft, calls set_distribution_method with the other basis, and asserts the per-item charges actually CHANGED to the new split — not merely that the label changed. Then submits and reads the same figures back off the submitted voucher.

Two items of different value-per-qty is the point: with a single item, or with items of equal value-per-qty, Qty and Amount produce the same split and the test would pass on code that does nothing.

Home: test_lcv_unification.py already has the bench fixtures for a Purchase Receipt LCV.

DoD: make test-bench.

### Nothing in the Vue SPA is mounted in tests — @vue/test-utils is not a devDependency
`stabler-edxe` · iş

Measured 2026-08-16 while landing stabler-l0m.3.9, and already documented in tests/installmentOperations.spec.js:14-19 as a known constraint.

vitest.config.mjs sets environment: 'node' and states the scope is 'PURE logic only. No DOM, no component mounting', because @vue/test-utils is absent from package.json.

The workaround in use is real but limited: specs regex-extract a computed/function body out of the .vue source and run it via new Function, plus toContain/not.toContain assertions against the source text. That catches a wrong sort direction and a forbidden /app/ link. It cannot catch: a v-if bound to the wrong ref, a prop passed with the wrong name, a slot that never renders, a component imported but never placed in the template, or a drawer that opens over the wrong row.

So every SPA page in this repo — including the two shipped in stabler-l0m.3.9 — has NEVER been rendered by an automated test. That is a coverage claim worth stating out loud rather than discovering later.

Work: decide whether to add @vue/test-utils + jsdom and mount at least the list/table pages, or to accept source-contract testing as the ceiling and say so explicitly in vitest.config.mjs and the frontend rules. Either is defensible; the current state is neither documented as a decision nor closed as a gap.

### Translation harvest has a 604-key backlog and re-sorts all five CSVs
`stabler-f720` · iş

Measured 2026-08-16 while landing stabler-l0m.3.9.

`bench --site genesis-test.local execute stabler.translations.harvest.run` reported:
  added per lang: {'en': 632, 'ru': 605, 'uz': 604, 'uzc': 604, 'tr': 604}

Two separate problems.

1. BACKLOG. ~604 user-facing keys exist in code and are missing from the catalogs. Every one of them renders as its raw English source string on the ru/uz/uzc/tr sites today. Nobody has run harvest in a long time, and the stabler-i18n skill says reviewers reject PRs that leave new strings untranslated — that rule is currently being enforced per-PR while 604 keys sit unlandeded behind it.

2. HARVEST REWRITES THE WHOLE FILE. It re-sorts all five CSVs, producing a 33,013-insertion / 29,967-deletion diff for what should be an append. Worse, the existing files are not sorted under ANY simple collation — python default, casefold and lower all disagree with the file's own order (first break: '1 line: price below agreed' before '1 USD ='). So harvest's sort is not idempotent with whatever produced the current order, and every run churns the entire catalog.

Consequence: harvest is effectively unusable inside a micro-task. In stabler-l0m.3.9 the 21 new keys had to be appended by hand to keep the commit reviewable, which is exactly the manual step harvest exists to remove.

Work: decide the canonical sort (or drop sorting and always append), make harvest idempotent against it, then land the 604-key backlog as its own commit — separately from any feature, because a 604-key translation pass needs a native-speaker review that no feature PR should be blocking on.

### Sizing table's 3-8 file band is breached by every feature commit; the 60% rule is now 240k tokens
`stabler-fbfh` · iş

Panel tarafindan 2026-08-17'de acikta birakildi (oturum af78e8ec). Iki sayi olculdu ve ikisi de artik gerekcesini tasimiyor:

1) SIZING BANDI. .claude/rules/00-context-budget.md sizing tablosu 'Files touched 3-8 = micro-task, >8 = split into an epic' diyor. Son 20 commit'te dosya sayisi olculdu: 8,8,1,7,5,12,8,15,1,2,1,2,3,9,5,3,2,1,2,3. Uc commit tavani asiyor (ff02c50=15, a61120b=12, fcd7c7b=9) ve >=7 dosyali HER commit feat/fix; 1-3 dosyalilarin neredeyse tamami docs. Yani medyani dokumantasyon asagi cekiyor, ozellik isi tavanin ustunde kumeleniyor. Son uc ozellik commit'inin ihlal ettigi bir satir hicbir seyi kisitlamiyor. Karar: bandi feat/fix commit'lerinden yeniden turet, ya da satiri kaldir. Prose review degil, olcum.

2) %60 KURALI MUTLAK DEGERDE. .claude/settings.json autoCompactWindow=400000. %60 x 400k = 240k token, Opus'ta gercek para. Kuralin yazili amaci 'A planned handoff is faster and lossless; a compaction is neither' — ama PreCompact hook'u (.claude/hooks/precompact-handoff.sh) artik handoff'u otomatik yaziyor ve 2026-08-16'da auto trigger ile gercekten yazdi, yani kayip argumani zayifladi. Kalan gerekce dikkat kalitesi ve maliyet, ikisi de bu oturumda OLCULMEDI. Bu yuzden panel yeni bir mutlak token sayisi YAZMADI: olculmemis sayi kurala girmez.

Bunu ne cozer: ayni gorevi kucuk ve buyuk context altinda kosturup hata oraninda fark olcmek, ya da oranin yerine 'kalan is tek atomik commit'e sigmiyorsa dur' gibi gozlemlenebilir bir esik koymak.

### The digest guard's error message can never be translated — the msgid in en.csv is truncated
`stabler-gfdw` · hata

2026-08-17, commit 043c29a ile gonderildi ve ayni gun dogrulama turunda yakalandi.

remittance_transfer.py:116-122'deki frappe.throw mesaji UC bitisik string literalinin birlesimi. Cikarici yalnizca ILKINI yakalamis:

  en.csv:447  'This transfer was saved without its pickup-code digest. The field is ,This transfer was saved without its pickup-code digest. The field is '

Calisma zamanindaki dize ise ucunun birlesimi ('...The field is permlevel 1 and your roles have no write grant at that level, so it was discarded. Run the remittance role patch on this site before registering.'). msgid hicbir zaman eslesmiyor, yani en.csv kaydi olu. ru/uz/uzc/tr'de kayit SIFIR (grep -c dordunde de 0).

SONUC: bu mesaji tezgahta bir kasiyer okuyacak ve bes dilin HICBIRINDE cevrilmeyecek. Repo kurali bes dil gonderildigi.

DUZELTME: mesaji tek literale cevir (ya da cikaricinin bitisik literalleri birlestirmesini sagla), sonra stabler-i18n skill'indeki hasat akisini kosup bes CSV'yi de guncelle. Bes CSV'yi ACIKCA evrele, translations/ dizinini butun olarak degil.

NOT - ayni sekildeki baska mesajlar olabilir: cikaricinin bitisik literalleri nasil ele aldigini bir kez olcup, ayni tuzaga dusmus baska msgid var mi diye taramak bu bead'in parcasi. Tekil bir yazim hatasi degil, arac davranisi.

### A terminal Vehicle Agreement still occupies its VIN direction slot — a repossessed car cannot be resold
`stabler-j73j` · iş

NEEDS A DECISION FROM ZAFAR. This is a business question, not a coding task, and it is the only genuinely unresolved one in the Vehicle Finance tree. It sits in the stabler-l0m epic notes as a P1 with no owning bead — scanning all 269 beads for terminat, repossess, settle_agreement or complete_agreement matched only l0m itself.

THE MECHANISM. vehicle_agreement._assert_single_direction_per_unit counts peer agreements at docstatus < 2. A Terminated agreement stays at docstatus 1. So once a VIN has been financed and the agreement terminated — repossession, write-off, whatever — that vehicle can never carry a second Disposition agreement. It is permanently unsellable inside the system.

THE QUESTION, in two parts:
  1. Does completing or terminating an agreement free the vehicle direction slot?
  2. If yes, at WHICH moment — at termination, or at the vehicle return document?
The second half matters operationally: between repossession and the car physically coming back, the slot is either free (and someone can sell a car you do not hold) or held (and you cannot list a car you have recovered).

CURRENTLY LATENT, and only by accident: no terminate or complete endpoint exists yet, so nothing can reach the terminal state at all. The moment the terminal-status writers land, this becomes live.

SIBLING QUESTION, ask them together: stabler-k38z (open) — trade-in has no representation in the Acquisition/Disposition direction model. Different defect, same direction-model decision, same person to ask.

BLOCKED BY the terminal-status writer bead: this is untestable until an agreement can actually reach a terminal state.

### No frontend spec exists for any of the seven remittance screens
`stabler-jtxi` · iş

2026-08-17'de bes ayri bead dogrulamasinin HEPSINDE ayni bosluk cikti, o yuzden tek yerde toplandi.

git ls-tree -r --name-only main | grep spec -> stabler/public/js/tests/ altinda 17-23 spec dosyasi var (authApi, crm360, piAllocation, rfqForm, vehicleFinanceAgreements, installmentOperations, sourcingWorkspace, ...). Remittance icin SIFIR.

Yani make check'in test-js bacagi asagidakilerin hicbirini korumuyor - hepsi bu ay yazilmis, hicbiri test edilmemis:
 - RemittanceOperations.vue: currencyLines (:242-249), rowActions (:323-325), queueCount, policy_configured bos-durum ayrimi
 - RemittancePayout.vue: disabled ifadesi (:798), kodun temizlenmesi (:183, :290, :309, onBeforeUnmount :338)
 - RemittanceRefund.vue: allowed_actions'tan buton cizimi (:198-202)
 - NewRemittanceV1.vue: roundHalfUp (:227-234) ve roundLikeFlt (:245-256) - kendi yorumu 20,042'de 2 sapma oldugunu soyleyen ELLE YAZILMIS sunucu yuvarlama aynalari. Sunucu fiyatlamasindan sapmalari sessiz para hatasi olur ve bugun hicbir sey olcmuyor.
 - RemittanceTransferDetail.vue / RemittanceReconciliation.vue / RemittanceSettings.vue

Hicbir bead bunu adiyla sart kosmadigi icin bu bir DoD boslugu, ihlal degil - ama ev deseni mevcut ve izlenmemis.

EN AZ SUNU KAPSA: allowed_actions disinda hicbir butonun cizilmedigi, teslim kodunun hicbir yerde yankilanmadigi, ve istemci yuvarlamasinin _remittance_pricing ile ayni sonucu verdigi.

DoD: make check (test-js bacagi).

### Vehicle attributes still missing after measuring the schema: odometer, insurance expiry, transfer date, engine no, power of attorney
`stabler-kfd4` · iş

Raised by the car-dealer panelist 2026-08-16, whose first three points were all the same shape: the design models the vehicle as a finance line, not as a physical asset with a legal state.

Concretely missing, each with the operational consequence the dealer named:
  - plate, chassis/engine number, odometer, inspection (ekspertiz) report — cannot quote a price without them, so the dealer keeps a separate spreadsheet
  - notary transfer date and power-of-attorney status — 'Location / possession' shows where the car physically is, but not whether title has passed. Selling a car whose transfer was never completed leaves the risk with the dealer.
  - insurance (kasko/trafik) and roadworthiness-inspection expiry dates — while an installment car is still registered to the dealer, an uninsured accident is the dealer's liability

The design does carry 'Title' and 'Possession' fields on the vehicle detail, so the axis is acknowledged; what is absent is the dated, trackable version of it.

Scope this against the vehicle_unit doctype before designing UI — some of these may already exist as fields.

**Not:** CORRECTED 2026-08-16. This bead was filed from the panelist's reading of the DESIGN MOCKUP, without measuring the doctype. Most of what it claimed was missing already exists. My error, and the same one twice in this session: treating a plausible match for a gap as a gap.

MEASURED — vehicle_unit.json already carries:
  registration_number   plate
  registration_expiry   registration/road-tax expiry
  inspection_due        roadworthiness inspection
  title_status          Select: Pending / Company Held / Transferred / Lien / Repossessed
  possession_note       labelled 'Location / possession'
  keys_count            how many keys are held
  condition_notes       free text
  document_folder       document path
  vin, model_label, operational_status (Expected/Received/Available/Reserved/Delivered/Returned)

So the dealer's lien/repossession concern and the plate, inspection and registration-expiry asks are ALREADY MODELLED. vehicle_agreement.json also carries terminated_reason, which covers the owner panelist's 'why was it terminated' question at the schema level.

WHAT IS GENUINELY STILL ABSENT, after measurement:
  1. odometer / kilometre — no field at all. The dealer cannot quote a price without it.
  2. insurance (kasko) expiry — registration_expiry and inspection_due exist, insurance is a third date and has no field. This is the one with liability attached: an uninsured accident on a vehicle still registered to the dealer is the dealer's loss.
  3. notary transfer DATE — title_status carries 'Transferred' as a state but nothing stamps WHEN. Without the date there is no evidence trail.
  4. engine number — vin covers the chassis; the engine number is separate on a Turkish/Uzbek registration and is absent.
  5. power of attorney (vekalet) — no field and no title_status value for it, though it is a real intermediate state between Company Held and Transferred.
  6. structured expertise report — condition_notes is free text and document_folder is a path string; there is no structured record or link.

Scope is therefore much smaller than filed: five fields and one decision about whether the expertise report deserves its own doctype. Items 1 and 2 are the ones with money and liability behind them; do those first.

The UI question is separate and mostly independent: several of these fields exist in the schema but the design mockup surfaces none of them.

### The aging strip stopped pricing the buckets you did not pick
`stabler-mn8r` · hata

Selecting one ageing bucket makes the other three KPI cards read 0. totals is computed by summarise() over the bucket-FILTERED scan and all four KPI cards read it, so an operator working the 31-60 list sees the red 90+ card at 0 while real escalation-level exposure sits there. The endpoint ALREADY runs an unfiltered scan for the SRBNB total and throws away everything but one number. KpiCard.vue own docstring states the principle being broken.

FIX (stabler/api/purchasing.py unbilled_receipts):
1. Hoist the supplier predicate into scope_conds/scope_params (base + supplier). Keep conds/params (scope + bucket) for the paged rows query.
2. scoped = _unbilled_scan(scope_where, scope_params); bucket_totals = summarise(scoped).
3. scanned = scoped if not bucket else [r for r in scoped if r["bucket"] == bucket]; totals = summarise(scanned).
4. When supplier is falsy, scoped IS the company-wide set -> reuse bucket_totals["total_unbilled"] as company_total and drop the second scan. Bucket-only selection goes 2 scans -> 1.
5. Return bucket_totals. WATCH has_more: it stays derived from scanned; if scanned silently becomes the unfiltered set the pager offers pages the server will not send.

UnbilledReceipts.vue: all FIVE cards (hero + four buckets) read bucket_totals, so the four buckets still sum to the total above them. Relabel the toolbar summary figure to "Unbilled (filtered)" when bucket || supplier is set.

CHEAP ESCAPE HATCH if the bench is unavailable: render an em dash instead of money(0) for unselected buckets. Two client-only lines, removes the entire stated harm (the false zero), zero server change. Take that and keep this bead for the correct numbers — do NOT ship a half restructure.

DoD: make check AND make test-bench.
New frappe-free tests: test_python_bucket_subset_matches_the_sql_bucket_bounds; test_the_four_bucket_totals_sum_to_the_scope_total.
New bench test: test_srbnb_difference_is_unchanged_when_only_a_bucket_is_selected.

**Not:** 2026-08-17 df3ba08: the CLIENT-ONLY escape hatch has SHIPPED — unselected bucket cards render an em dash instead of money(0), so the false zero (the entire stated harm) is gone from the screen. This bead now covers ONLY the remaining half: return a bucket-independent summary (bucket_totals) from the endpoint so the cards show the real figures, plus the has_more regression watch. Do not re-do the client change. Still needs make test-bench.

### Translation catalogs are ~590 keys behind in ru/uz/uzc/tr
`stabler-ne8v` · iş

Measured 2026-08-16 while landing stabler-gcc9: a single harvest run
(`bench --site <site> execute stabler.translations.harvest.run`) wanted to append
615 keys to en.csv and 587-588 to each of ru/uz/uzc/tr. Those are strings that
shipped without ever being translated.

gcc9 added only its own four keys by hand and reverted the harvest, deliberately:
~590 untranslated rows do not belong inside a P0 security fix, and the reviewer
rule rejects new user-facing strings that are untranslated in any of the five
languages — so merging them blind would have shipped exactly what the rule forbids.

This bead is the separate change: run the harvest, then actually translate the
backlog into ru, uz, uzc and tr. Expect it to be large and mostly mechanical.
Stage the five CSVs explicitly, never the whole translations/ dir (it pulls the
.tx_*.json caches). After deploying, `bench --site <site> clear-cache` on all
seven sites — bench restart does not clear the Redis translation cache.

### github/main is 87 commits behind origin/main — the GitHub mirror stopped being fed
`stabler-pb7e` · iş

Olculdu 2026-08-17 (oturum af78e8ec), 11547a9 push'u sirasinda:

  git remote -v      -> origin = git@gitlab.com:zvictory2001/stabler.git  (main'in upstream'i)
                        github = git@github.com:zvictory/stabler.git
  git log main..github/main   -> 0    (iraksama YOK)
  git log github/main..main   -> 87   (sadece geride)

Yani GitHub bir mirror ve beslenmeyi birakmis; force gerekmez, duz fast-forward. CLAUDE.md
'main is the single source of truth' diyor ve prod main'den beslenir; ama GitHub'i okuyan
herhangi bir sey (CI, baska bir makine, bir insan) 87 commit bayat kod goruyor. Sessiz bayat
durum, bu repo'nun kurallarinin tam olarak nefret ettigi sekil.

Karar gerekiyor: (a) her push'ta iki remote'a da gonder (git push origin main && git push
github main, ya da remote.pushDefault / bir pre-push hook), (b) GitHub'i bilincli olarak
terk et ve remote'u kaldir ki kimse bayat olani okumasin. Ikisinin arasinda kalmak en kotusu.
Zafar'in karari: GitHub'i kim/ne okuyor?

### Remittance i18n — five CSVs
`stabler-qzr9.17` · iş

en, ru, uz, uzc, tr. Follow the stabler-i18n skill. Stage the five CSVs explicitly, never the translations directory (it pulls the .tx_ caches).

### Decide: does a pickup-code lockout expire, or is manager unlock the only exit?
`stabler-tegf` · iş

The two planning documents contradict each other and neither resolves it.

- OPS:336 lists `lockout_minutes` (Int) as a Remittance Settings policy field, which
  implies a time-based auto-unlock. It is the only one of the four policy fields the doc
  gives NO default for.
- COUNCIL:400, describing verified prototype behaviour: "tek çıkış manager unlock" — the
  only exit is a manager unlock.

Both cannot be true. stabler-qzr9.6 shipped the field with a chosen default of 30, and
stabler-qzr9.7 shipped `code_locked` + `code_locked_at` on the transfer WITHOUT an
auto-unlock, because implementing one the council says should not exist is the worse
error of the two.

So `lockout_minutes` currently has no consumer. Resolve it one way:
(a) manager unlock only -> delete lockout_minutes from Remittance Settings, or
(b) time-based auto-unlock -> qzr9.10 reads lockout_minutes and clears the lock when
    code_locked_at + lockout_minutes has passed, and Zafar picks the real number.

This is a security-relevant policy call, not a coding preference: (b) hands an attacker
unlimited attempt batches separated by a wait, against a 2^40 code space.

**Not:** NOT: commit 0e4e88c'nin mesajı bu bead'e 'stabler-vqx0' diye atıf yapıyor — yanlış. Doğru id bu bead: stabler-tegf. Commit push edildiği için mesajı düzeltmek force-push gerektirirdi; hatanın kendisinden daha zararlı olurdu.

### Around 690 user-facing keys across the app have never been harvested
`stabler-y1bw` · iş

Measured 2026-08-17 by running the harvester against a clean worktree: it reported 730 keys missing from en.csv. Roughly 40 of those belong to the new unbilled-receipts page; the remaining ~690 are accumulated across the rest of the app.

Every one of those strings renders as its English source in ru, uz, uzc and tr — four of the five languages shipped. This is not one feature debt; it is the catalogs having drifted behind the code for a long time.

Blocked by the CRLF bead: harvesting today rewrites all five files end to end, so the real additions cannot be reviewed and the commit cannot be merged sanely. Fix the line endings first, then harvest once and translate in reviewable batches.

Do NOT fold this into a feature branch.

### Collateral and follow-up discipline: guarantor, promissory note, structured next-action, broken-promise counter
`stabler-zua5` · iş

Three panelists converged on the follow-up loop being unclosable as designed. Raised 2026-08-16.

GUARANTOR AND PROMISSORY NOTE (dealer, point 8). None of the four wizard steps has a guarantor, promissory note or cheque field. The dealer's verdict: most installment vehicle sales are secured by a note, and without it 'I cannot enter the sale into the system properly, I track it on paper outside'. Work that escapes to paper is work the system does not have.

STRUCTURED NEXT ACTION (dealer, point 6). 'Next action' and 'Last contact' are the right idea but, as free text, will be empty within three months. They need fixed choices — called / messaged / went to notary — or they become dead columns.

BROKEN-PROMISE COUNTER (owner, point 6). record_promise exists but nothing counts promises. A customer saying 'I will pay Friday' for the third time is indistinguishable from a first-time promise, so no escalation can be triggered off it.

These are one bead because they are one loop: secure the debt, record the contact in a countable form, escalate when the count says so.
