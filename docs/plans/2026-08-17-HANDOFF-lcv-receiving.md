# HANDOFF — `feat/lcv-submit-and-basis` → Claude Code

Yazan: Cowork oturumu (bulut), 2026-08-17. Devralan: yerel Claude Code.
Dal: **`feat/lcv-submit-and-basis`**, ana working tree'de (`apps/stabler`), `main`'in 7 commit önünde.

Kararlar: `docs/plans/2026-08-16-landed-cost-calculation-design-council-decision.md` ·
`docs/plans/2026-08-16-satin-alma-ambar-zinciri-tasarim-kurulu-karari.md` ·
mockup `docs/plans/assets/landed-cost-calculation-mockup.html` ·
iş kuyruğu taslağı `scratch/create-import-chain-beads.sh` (bd'ye **girilmedi**).

---

## ⛔ İLK İŞ — devralmadan önce iki şey

### 1. `v87` patch numarası çakışması (gerçek, şimdi düzeltilmeli)

```
benim dal            : stabler/patches/v87_lcv_distribution_method.py
feat/remittance-roles: stabler/patches/v87_remittance_roles.py
```

İkisi de `patches.txt`'e ekleme yaptı. Kim ikinci merge ederse **yeniden numaralamak
zorunda**. Migrasyon sırası bu numaraya bağlı ve iki v87 sessizce kalıcı olur.

Öneri: remittance daha eski iş, v87'yi ona bırak; bu dalın patch'i **v88**'e taşınsın —
dosya adı, dosya içindeki docstring referansları, `patches.txt` satırı ve
`stabler/api/lcv.py`'deki `#: ... v87_lcv_distribution_method` yorumu birlikte.

### 2. Bu daldaki 2 commit benim değil

`9545015 style(lcv)` ve `ab4a84e fix(stabler-xvsn)` — **ana working tree'de çalışan başka
bir oturum** tarafından bu dala atıldı. İkincisi benim LCV işimde gerçek bir açık
kapatıyor (aşağıda). Yani bu dalda tek bir yazar yok; `git log` okurken varsayma.

Aynı sebep: ana working tree'nin `.git/index`'ine bir ara remittance dosyaları stage
edilmişti. Ana tree'yi paylaşan başka bir şey var. **Bu daldan devam edeceksen, kendi
worktree'ni aç** (`.worktrees/` deseni repoda zaten var) — aksi halde `git checkout`'un
o oturumun HEAD'ini de oynatır.

---

## Remittance / vehicle finance etkileniyor mu? — Hayır, bir istisnayla

`git worktree list` çıktısı: her iş kendi worktree'sinde, **kendi HEAD ve kendi index'iyle**.
Benim `checkout -b` ve commit'lerim onlara dokunmadı.

| Dal | Yer | `main`'in önünde | Benimle dosya kesişimi |
|---|---|---|---|
| `feat/remittance-payout` | `.claude/worktrees/wf_…-1` | 1 | yalnız `frappe-free-tests.txt` |
| `fix/remittance-je-cancel-guard` | `…-2` | 1 | yalnız `frappe-free-tests.txt` |
| `feat/remittance-roles` | `…-3` | 1 | `frappe-free-tests.txt` + **`patches.txt` / v87** ⛔ |
| `fix/usdt-exchange-rate` | `…-4` (locked) | 1 | yalnız `frappe-free-tests.txt` |
| `feat/vehicle-finance-operations-screen` | `.worktrees/agy-…l0m.3.7` | **0** | — |
| `fix/ci-expense-real-records` | `.worktrees/claude` | **0** | — |
| `feat/imports-lcv-cancel-action` | `.worktrees/agy-…bf8` | **0** | — |

- **Vehicle finance dalı `main`'in 0 commit önünde** — commit'lenmiş bekleyen iş yok. O
  worktree'de commit'lenmemiş çalışma varsa buradan görünmez, ve worktree izole olduğu
  için önemi de yok.
- `main` şu an `5c5986c feat(stabler-vevd)` — bir remittance commit'i. Yani bu dal
  **onların son işinin üstüne** kurulu, geride değil.
- Merge sırasında beklenen tek sürtünme: **`.github/frappe-free-tests.txt`** — beş dal da
  sonuna satır ekliyor. Hepsi append, çözümü mekanik.
- ⚠️ `git worktree list` yedi worktree'nin altısını **`prunable`** gösteriyor (dizinleri
  yok). `git worktree prune` temizler — ama `fix/usdt-exchange-rate` **locked**, ona
  dokunma. Bu benim kararım değil, senin.

---

## Dalda ne var (7 commit)

| Commit | Ne |
|---|---|
| `6c46661` | LCV artık SPA'dan submit edilebiliyor; ölü `imports/LandedCostReview.vue` silindi (433 satır); `unitCostAnalysis` kartı kurtarıldı. `distribute_charges_based_on` açıldı (`Qty`\|`Amount`, varsayılan **`Amount`**), kaynak belgede kalıcı, ilk submit'te **server-side donuyor**. Patch v87 (→ v88 olacak). |
| `094455f` | **Review P0**: per-kg kartı USD makbuz toplamını UZS voucher toplamlarına ekliyordu. `base_grand_total` eklendi; kart imports'a kısıtlandı (`received_total_kg` PR rotasında ağırlık değil, işlem UOM'u); taslak voucher'lar toplama dahil. |
| `9545015` | *(başka oturum)* ruff import gruplaması |
| `45c6eaa` | Rate 0 sert blok + `Truck Receipt Item.rate` kaçış kapısı, **aynı commit'te**. Submit throw eder, validate yalnız `msgprint` (throw olsaydı taslak kaydedilemezdi ve boşaltma anındaki kanıt yok olurdu). Artı yabancı para birimli PO guard'ı. |
| `ab4a84e` | *(başka oturum, bead `stabler-xvsn`)* **Benim işimdeki gerçek açık**: bazı kaynak belgede saklanıyordu ama voucher kendi kopyasını inşa anında yazıyor, ve `grn_on_submit` taslağı arka plan işinde kimse ekranı açmadan kuyruğa alıyor. Ekran "By weight" derken ERPNext değere göre kapitalize ediyordu. Artık baz seçilince ayakta duran taslaklar yeniden damgalanıp kaydediliyor; donmuş bazdan önce gelen taslağı submit reddediyor. |
| `110de06` | **Review P0**: rate kutusu `:language` almıyordu → `MoneyInput` "en" varsayılanında virgülü binlik ayracı sayıyor, **"4,75" → 475**. ru/uz/uzc/tr operatörü için 100 kat hata, fiyat giriş yolunda. Artı: SPA'nın erken-uyarı mekanizması ulaşılamazdı (`po_rate`'i hiçbir endpoint dönmüyordu); doğru fiş hâlâ "rate set to 0" diyordu; para birimi karşılaştırması `receipt_math`'e taşındı ve testlendi. |
| `a2c584f` | **Faturalanmamış mal kabulleri raporu** — SRBNB (GR/IR) yaşlandırma + mutabakat. Frappe-free `_unbilled_receipts.py`, whitelisted `purchasing.unbilled_receipts`, yeni SPA sayfası iki modül prefix'inde. `create_purchase_invoice_from_pr` **zaten doğruydu, dokunulmadı** — eksik olan onu kullanmanı söyleyen listeydi. |

---

## ⛔ AÇIK REVIEW BULGULARI — `a2c584f` üzerinde, HİÇBİRİ DÜZELTİLMEDİ

Son commit review'dan geçti, 4 bulgu çıktı, ve **düzeltme turu başlamadan oturum
kesildi**. Bu dalın en önemli devir kalemi budur. Bulgular repo'nun kendi
`stabler-diff-reviewer` ajanı tarafından, `file:line` kanıtıyla üretildi.

### P0 — geriye dönük `as_of`, `srbnb.difference`'ı uydurma yapıyor ve banner birini suçluyor
Rapor iki yanı sadece görünüşte tarihliyor. **GL yanı tarihsel** (`posting_date <= as_of`);
**makbuz yanı değil** — `per_billed` üzerinden filtreliyor ve değerliyor, o da *güncel*
durum. `as_of` ile bugün arasında faturalanan her makbuz `total_unbilled`'dan düşüyor
ama SRBNB alacağı `gl_balance`'ta kalıyor (kapatan faturanın GL'i kesim tarihinden sonra).

Örnek: `as_of = 2026-07-31`, PR-001 07-10'da 500.000.000 UZS, faturası 08-05'te submit.
`per_billed` artık 100 → satır düşüyor, `total_unbilled = 0`; 07-31 itibarıyla
`gl_balance = 500.000.000`. `difference = +500.000.000`, filtre yok → SPA **danger**
durumunu basıyor ve muhasebeciye "SRBNB'ye doğrudan yevmiye atılmış" diyor. **Hiçbir şey
yanlış değil.** Dönem tahakkuk mutabakatı bu raporun en doğal kullanımı ve bu, commit
mesajının "asla yapmayacağız" dediği yanlış suçlamanın ta kendisi.

`_srbnb_reconciliation` docstring'i mekanizmayı zaten itiraf ediyor; kod ona göre
davranmıyor. `UnbilledReceipts.vue:151`'de `reconcilable = !supplier && !bucket` —
`as_of` içinde yok, ve üstündeki yorum "sunucu iki yanı da tarihliyor" diyor, ki yanlış.

**Önerilen düzeltme:** `srbnb`'ye `comparable: bool` ekle (`as_of < today` iken false);
false ise SPA farkı ve suçlamayı bastırsın, iki sayıyı yine göstersin. `difference`'ın
false durumunda `None` mu sayı mı olacağına bilinçli karar ver ve docstring'de savun.
Doğru-ama-büyük düzeltme (`as_of` itibarıyla faturalamayı `Purchase Invoice Item`'dan
yeniden kurmak) ayrı iş; bayrak dürüst ara çözüm.

### P1 — fatura zaten varken satır değişmiyor, taslaklar üst üste biniyor
**Taslak** Purchase Invoice `per_billed`'ı oynatmıyor (ERPNext submit'te güncelliyor).
Satır aksiyonu başarılı olup `load()` çalıştıktan sonra aynı satır aynı "Create invoice"
butonuyla geri geliyor; payload'da mevcut faturayı gösteren bir alan yok. Tekrar tıklama
veya ikinci operatör bir makbuza N taslak yığıyor; `Accounts Settings.over_billing_allowance`
sıfır değilse kopyası submit olabiliyor.

**Ayrıca kayda geç, düzeltme:** bu uygulamanın kendi `create_purchase_invoice`'ı
(`purchasing.py` ~1095) satırlara ne `purchase_receipt`/`pr_detail` ne `po_detail`
yazıyor. O yolla faturalanan makbuzun `per_billed`'ı 0 kalıyor, bu listeden hiç çıkmıyor,
**ve ERPNext'in over-billing kontrolüne görünmez** — kopya temiz submit oluyor, tedarikçi
iki kez ödenebiliyor. Farklı bir fonksiyonda, önceden var olan kusur; `existing_invoice`
onu **tespit edemez** (bağ yok ki bulunsun). Endpoint docstring'ine raporun kör noktası
olarak yazılmalı ki boş `existing_invoice` "fatura yok" kanıtı sanılmasın.

**Önerilen düzeltme:** satıra `existing_invoice: {name, docstatus} | None` ekle
(`tabPurchase Invoice Item.purchase_receipt = pr.name`, parent `docstatus < 2`, submitted
olan taslağa tercih edilir), sayfa başına **tek** batched sorgu — satır başına değil.
Doluysa buton yerine faturaya link.

### P2 — bir kova seçilince diğer üç yaşlandırma kartı sıfır gösteriyor
`totals` kova-filtreli tarama üzerinden hesaplanıyor ve dört KPI kartı ondan besleniyor.
31–60 listesini çalışan operatör şeride bakıyor ve kırmızı "90+" kartı **0 сўм** okuyor,
orada gerçek eskalasyon-seviyesi maruziyet varken. Endpoint kova-filtresiz taramayı
**zaten yapıyor** ve tek sayı dışında her şeyi atıyor. `KpiCard.vue` kendi docstring'inde
bu ilkeyi yazmış: "sayfa toplamı gibi görünen daraltılmış sayı, seçim-duyarlı kartların
asla yapmaması gereken hatadır."

**Önerilen düzeltme:** ikinci bir özet bloğu dön (`bucket_totals`) — tedarikçiye göre
kapsamlı ama **kova-filtresiz**, mevcut taramayı yeniden kullanarak. Şerit onu okusun;
tablo ve toolbar `totals`'ta kalsın.

### P2 — banner SRBNB'ye yazamayacak bir sebebi adlandırıyor, yazabilenleri atlıyor
Banner "Update Stock açık bir Purchase Invoice" diyor. Oysa ERPNext'in
`PurchaseInvoice.set_expense_account`'u `update_stock` açıkken stok kaleminin gider
hesabını **ambar hesabına** yönlendiriyor, kapalıyken SRBNB'ye — yani banner'ın suçladığı
vaka, SRBNB'ye yazamayan **tek** vaka. Yazabilen ve eksik olan tersi: makbuza referans
vermeyen, `update_stock` **kapalı** bir fatura SRBNB'yi borçlandırıyor (bu uygulamanın
kendi `create_purchase_invoice`'ı tam olarak onu üretiyor) ve farkı negatife çekiyor.

Gerçek sebepler: SRBNB'yi borçlandıran iade makbuzu (bu liste `is_return`'ü tasarım gereği
dışlıyor); makbuza referans vermeyen fatura; `base_grand_total` içindeki hiç SRBNB'ye
girmemiş vergi/masraf (bugün latent — bu uygulamanın ürettiği makbuzda vergi şablonu yok,
ama Desk'ten girilen bir makbuz bunu bozar); `as_of` sonrası submit edilen faturalar (P0).
**Benim commit mesajımdaki gerekçe de yanlış, o da düzeltilmeli.**

---

## Kalan iş (30 günlük listeden)

`docs/plans/2026-08-16-satin-alma-ambar-zinciri-tasarim-kurulu-karari.md` bölüm 6.
1, 2, 3, 4 numara bu dalda **yapıldı**. Kalan:

- **5 — hasarlı kg deftere girsin**: ERPNext'in native `rejected_qty` + `rejected_warehouse`
  alanlarını aç. Bugün `receipt_math.good_qty` yalnız `Good` kg'ı yazıyor; hasarlı kg GRN
  varyansında sayılıyor ama deftere **hiç** girmiyor, yani fiziksel sayım asla tutmuyor.
  Yeni doctype yok, yeni ambar mantığı yok. Kiracı başına bir `Rejected/Damaged` ambar
  kurulumu gerekiyor. **S**, ama `make test-bench` şart.
- **6 — batch = konteyner**: `hooks.py:625` `batch_name`'e container için `None` geçiyor
  (`receipt_math.batch_name` prefix'i `container_number or commercial_invoice or "IMP"`),
  yani batch id her zaman `{CI}-{item}-{tarih}` ve bir varış tarihinin tüm konteynerleri
  tek batch'te birleşiyor. `has_batch_no` varsa expiry zorunlu + `> mal kabul tarihi`;
  yoksa logger değil `frappe.throw`. **Aciliyet sebebi farklı: gecikilen her gün kalıcı
  olarak ayrıştırılamaz batch üretiyor** — birleşmiş batch hareket ettikten sonra
  bölünemez. **S/M**, `test-bench`.
- **Dolgular**: %70 avans PE'yi submit et + `payment_70_status`'u salt-okunur türet ·
  Proforma geçiş guard'ı (imports'ta guard'ı olmayan tek doctype; rate-0 kusurunun yukarı
  akış kaynağı) · ölü `Freight Booking` doctype'ını sil (önce 7 kiracıda kayıt sayısına bak).
- **Ölçüm, kod değil, ve hâlâ yapılmadı**: kaç Landed Cost Voucher `docstatus=0`'da
  duruyor, toplam `total_taxes_and_charges` ne? Kiracı başına. Büyükse envanter **şu anda**
  eksik değerlenmiş demektir ve öncelik bu listenin hiçbir maddesi değil, o sayıdır.

**Ertelendi — Zafar kararı 2026-08-16, çalışma yok:** veteriner sertifikası kapısı, soğuk
zincir sıcaklık kontrolü, karantina. Kurulun bulguları karar dokümanı bölüm 6b'de kayıtta;
risk kabul edilmiş bir iş kararı, çözülmüş değil.

---

## Doğrulama durumu — neyin koştuğu, neyin koşmadığı

Bu bulut ortamında `apps/stabler` dışında hiçbir şey mount değil, cihaz VM'inde ağ yok ve
bench venv'i erişilemez. Yani:

**Koştu ve geçti:** `make guards` (exit 0, tüm ağaç — Desk linki, striping, ham tarih,
çıplak date input) · `eslint` (değişen tüm `.vue`/`.js`, exit 0) · `python3 -m py_compile` ·
tüm frappe-free unittest seti (`.github/frappe-free-tests.txt` üzerinden, OK) · `@vue/compiler-sfc`
ile SFC derlemesi + `bindingMetadata` (her template identifier bağlı) · her yeni kuralın
tersine çevrilip suite'in kızardığının doğrulanması.

**HİÇ koşmadı — senin ilk işin:**
- ⚠️ **`ruff check` / `ruff format --check`.** Cihazda ruff yok, ağ yok, buluta dosya
  staging'i **`session_stale_relogin`** ile bloklandı (masaüstünde giriş banner'ı var,
  yeniden giriş gerekiyor). Format elle denetlendi (tab, trailing whitespace, E302/E303/E305;
  `E501` proje ignore listesinde). Başka bir oturumun commit mesajı bir ara benim
  `receipt_math.py`'nin ruff format'ta kırmızı olduğunu söylemişti — E302'yi buldum ve
  düzelttim ama `ruff format` daha katı. **`make fix` sonra `make check`.**
- ⚠️ **`make test-bench`.** Bu işin tamamı DB'ye bağımlı: endpoint SQL'leri, `DATEDIFF`
  kovaları, SRBNB GL sorgusu, izin ve tenant guard'ları, `lcv_ref` damgalama/bırakma,
  patch idempotansı, doctype model sync'in `Truck Receipt Item.rate` kolonunu açması.
  **`make check` tek başına bu iş için ispat değildir.**
- `make lint-changed`, `compile`, `test`, `test-js` (vitest) — venv/darwin `node_modules`.
- Tarayıcıda hiçbir şey açılmadı. `ti-filter-off` ikonunun pinlenmiş Tabler build'inde
  olduğu doğrulanamadı (ağ yok); kullandığım diğer tüm ikonlar repoda zaten var.

## i18n borcu

Beş katalog (`en/ru/uz/uzc/tr`) **backfill edilmedi** — repo kuralı mantık durulduktan
sonra diyor. Yeni `t()` anahtarları: LCV review sayfası ~23, `UnbilledReceipts.vue` 56
(43'ü yeni, 14'ü katalogda mevcut), Truck Receipt formu 6. Artı `frappe._()` ile sarılmış
yeni sunucu mesajları (rate-0 blok, yabancı para birimi PO, unpriced msgprint, SRBNB).
Üç toast metni artık **kullanılmıyor** ve CSV'lerden düşebilir: eski
"an accountant must review and submit it in the books" üçlüsü.

`stabler-i18n` skill'i workflow'u anlatıyor. CSV'ler açıkça beş dosya olarak stage edilir,
asla `translations/` dizini komple (`.tx_*.json` cache'lerini çeker).

## Merge / deploy

Merge edilmedi, push edilmedi — bilinçli. Repo kuralı: `main` tek doğruluk kaynağı,
`--no-ff` ile merge (bu repo **rebase etmiyor** — CRLF çeviri CSV'leri her commit'te
yeniden çakışıyor, ölçülmüş), ve **production deploy her zaman Zafar'ın açık onayını
gerektirir** — tek `bench restart` yedi kiracıyı birden etkiliyor.

Merge etmeden önce: v87 → v88 yeniden numaralama, 4 açık review bulgusu, `make fix`,
`make check`, `make test-bench`.

## Küçük artıklar

- `.git/_stale_locks/` — `device_bash` mount'ta `unlink` yapamadığı için git kendi
  `.lock` dosyalarını temizleyemedi; oraya taşıdım. Silinebilir.
- `_to_delete/lcv-dead-duplicate/` — silinen ölü `imports/LandedCostReview.vue` (aynı
  sebep: `rm` yasak, `mv` ile taşındı). Git'te silme olarak kayıtlı; klasör silinebilir.
- `scratch/_superseded/create-landed-cost-beads.sh` — yalnız landed cost kapsamındaki eski
  bead script'i; `scratch/create-import-chain-beads.sh` onun yerine geçti.
- `scratch/` gitignored, `_to_delete/` untracked.
