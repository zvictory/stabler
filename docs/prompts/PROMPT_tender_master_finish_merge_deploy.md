# Tender Master · bitir → kararları uygula → birleştir → prod'a deploy

Bu dosyanın tamamını Claude Code'a yapıştır. **ONAY yazan yerde dur ve sor.**
Beş iş sırayla. `git add -A` YASAK; yol yol stage et.
Commit trailer: `Co-Authored-By: Claude <noreply@anthropic.com>`

---

## Onaylanan üç karar (gerekçeleri — uygulama bunlara göre)

### K1 · Parent şeridi TÜRETİLİR (elle `status` alanı şerit belirlemez)

Sebep: uygulamanın tamamında geçerli kural "pano kaynak belgenin projeksiyonudur, iş
durumunu kopyalamaz". Elle statü kaçınılmaz olarak kayar — iki lot kazanılıp üçü açıkken
kimse parent'ı "Kısmi sonuç"a çevirmeyi hatırlamaz ve pano yalan söyler. Ayrıca spec §9
kabul kriteri "parent sayıları görünen lot drill-down'una eşit olmalı" diyor; elle statüyle
bu garanti edilemez.

### K2 · `custom_parent_tender` alanı **reqd YAPILMAZ** — koşullu doğrulama + migrasyon kuyruğu

Sebep: `CRM Deal` 7 tenant'ın hepsinde var. CLAUDE.md'nin açık kuralı: *"Don't add a **reqd**
field to a doctype a non-owner tenant also carries."* Üstelik bu tam olarak v59'da bir kez
yaşandı — CRM Deal'e konan bir varsayılan `new_doc("CRM Deal")`'i kırdı (error 1054).
Doğrusu: alan opsiyonel kalır, zorunluluk **validate hook'unda koşullu** uygulanır
(deal_type=Tender **ve** şirketin tender modülü açıksa parent şart), parent'sız eski tender
lotları ise **görünür bir migrasyon kuyruğunda** listelenir — sessizce gruplanmaz (spec §8).

### K3 · MERGE (rebase değil)

Ölçtüm: dal main'den 9 commit geride, merge-base `5f5e5d7`. İki tarafın da dokunduğu 12
dosyadan **yalnızca 6'sı** gerçek çatışma adayı ve hepsi **append-only liste**:

```
.github/frappe-free-tests.txt
stabler/translations/{en,ru,uz,uzc,tr}.csv
```

Kalan 6 dosya (`api/tender.py`, `SkeletonRows.vue`, `CommercialInvoices.vue`,
`DirectorBoard.vue`, `test_list_row_ordinals.py`, `test_tender_dashboard_behavior.py`)
temiz birleşiyor: `0cf495b` (dal) ile `4014798` (main) **birebir aynı yama** —
patch-id `0af56ac…` iki tarafta da aynı. Rebase 23 commit'i CRLF'li CSV'lere karşı
tek tek oynatır → her commit'te çatışma; merge tek seferde çözülür.

---

# İŞ 1 — Elde kalan düzeltmeyi bitir

```bash
cd ~/frappe-bench-local/apps/stabler/.worktrees/tender-ops-foundation
git status --short && git diff stabler/api/tender_master.py
```

`api/tender_master.py` commit'lenmemiş: `_qualifying_parent_names(...)` artık `deal`
alıyor ve aday lot kümesini tek lota daraltıyor. **Testi yok.**

`stabler/tests/test_tender_master_api.py` içine ekle ve **önce kırmızı gör**
(düzeltmeyi geçici geri alarak):

- aynı parent altında iki lot varken `deal=LOT-A` + bir yaşam-döngüsü filtresi
  (`stage`/`status`/`risk`) → LOT-B'nin eşleşmesi parent'ı sonuca sokmamalı;
- başka şirkete ait / okuma izni olmayan `deal` → `PermissionError`;
- `deal` verilmediğinde davranış değişmemeli (regresyon).

```bash
python3 -m unittest stabler.tests.test_tender_master_api -v
```

Sonra commit et: `fix(tender): narrow CRM filters to the requested lot`

---

# İŞ 2 — K1: parent şeridini türet

## 2.1 Saf modül — `stabler/api/_tender_master_state.py`

Frappe'siz. Tek işi: çocuk lotların funnel aşamalarından üst şeridi çıkarmak.

```python
LANES = ["Preparation", "Active", "Awaiting Result", "Partial Result", "Completed"]

def derive(lot_stages: list[str]) -> str:
    """lot_stages = _funnel.classify çıktıları: seen|go|sourcing|priced|submitted|won|lost"""
```

Kurallar (öncelik yukarıdan aşağı):

| Koşul | Şerit |
|---|---|
| hiç lot yok | `Preparation` |
| **her** lot terminal (`won`/`lost`) | `Completed` |
| **bazı** lotlar terminal, bazıları değil | `Partial Result` |
| terminal yok, en az bir lot `submitted` | `Awaiting Result` |
| en az bir lot `sourcing` veya `priced` | `Active` |
| aksi halde (`seen`/`go`) | `Preparation` |

Bilinmeyen aşama **yok sayılmaz** — `Preparation`'a düşer, asla ilerleme uydurmaz.

## 2.2 Doctype

`tender_master.json` → `status` alanı: `"read_only": 1`, `reqd`'ı **kaldır**.
Alan kalır (elle not/geçmiş için) ama **şerit belirlemez**.

## 2.3 API — `api/tender_master.py`

`list_tender_masters` yanıtına her kayıt için `stage` + lot kırılımı ekle:

- Çocuk lotları **TEK sorguda** çek (`custom_parent_tender in [...]`), Python'da grupla.
- SQ sayılarını **TEK gruplu sorguda** al — `tender_funnel`'daki `sq_counts` kalıbının
  aynısı (`api/tender.py:2174`). **Döngü içinde sorgu YOK.**
- Her lot için `_funnel.classify(...)` çağır (mevcut saf modül — yeniden türetme yok).
- `_tender_master_state.derive(...)` ile `stage`'i bul.
- Karta spec §3'ün istediği sayıları koy: `lot_count`, `open_lot_count`,
  `submitted_lot_count`, `won_lot_count`, `lost_lot_count`, `estimated_total`,
  `earliest_deadline`, `policy_gap_count` (5 teklif altındaki lot sayısı), `risk_count`.
- `get_tender_master` de aynı `stage`'i döndürsün.

**Frappe v16 tuzağı:** `fields=["count(x) as n"]` gibi SQL fonksiyonunu string SELECT'te
kullanma — kaynak kontrolünden geçer, canlıda 500 atar. Düz alan çek, Python'da say.

## 2.4 SPA — `composables/tenderMaster.js`

`CRM_STAGES` yerine `LANES` (5 şerit). `normalizeTenderMaster` artık `record.stage`
kullanır; `CLOSED_STATUSES` mantığı kalkar. Kartta yeni sayıları göster.

## 2.5 Testler

`test_tender_master_state.py` (saf): tabloyu satır satır; boş lot listesi; tek lot won →
`Completed`; won+açık → `Partial Result`; hepsi `submitted` → `Awaiting Result`;
bilinmeyen aşama → `Preparation`.

`test_tender_master_api.py`'ye ekle: **parent sayıları görünen lot listesine eşit**
(spec §9); döngü içinde sorgu olmadığı (kaynak taraması); `status` alanının şeridi
belirlemediği.

Yeni test modüllerini `.github/frappe-free-tests.txt`'e `stabler.tests.<modül>`
formatında ekle.

---

# İŞ 3 — K2: koşullu zorunluluk + migrasyon kuyruğu

## 3.1 `validate_deal_parent_tender` genişlet

Mevcut hook şirket eşitliğini kontrol ediyor; şunu ekle:

```python
# Tender lot'u parent'sız kalamaz — ama bu kural YALNIZCA tender modülü
# açık şirkette ve deal_type=Tender iken uygulanır. Diğer 6 tenant'ın
# CRM Deal'i bundan hiç etkilenmez (CLAUDE.md: paylaşılan doctype'a reqd konmaz).
```

- `custom_deal_type != "Tender"` → dokunma.
- `module_map_for(doc.company).get("tender")` yanlışsa → dokunma.
- **Mevcut** kayıt güncelleniyorsa ve parent zaten boşsa → **throw etme**, sadece
  migrasyon kuyruğunda kalsın (eski veriyi kilitleme).
- **Yeni** kayıt + tender + modül açık + parent boş → `frappe.throw`.

## 3.2 Migrasyon kuyruğu

`api/tender_master.py`:

```python
@frappe.whitelist()
def orphan_tender_lots(company: str) -> dict
```

Tender tipli, parent'ı boş CRM Deal'ler. Imports/tender kapısı + şirket kapsamı +
`has_permission` filtresi. TEK sorgu.

SPA: `TenderCrm.vue` üstünde sayı > 0 ise uyarı şeridi — *"{n} tender lotu bir ihaleye
bağlı değil"* + listeye açan buton. Kayıt sessizce gruplanmayacak (spec §8).

## 3.3 Testler

Koşullu zorunluluk: tender modülü kapalı şirkette throw etmez; deal_type≠Tender'da
throw etmez; mevcut parent'sız kaydın kaydedilmesi engellenmez; yeni tender lotu
parent'sız throw eder. Kuyruk ucu: şirket kapsamı + izin filtresi + tek sorgu.

## 3.4 i18n

Yeni tüm stringler **5 dilde**: `stabler/translations/{en,ru,uz,uzc,tr}.csv`.
**Dosyalar CRLF** — satırı `\r\n` ile ekle, dosyanın sonundaki mevcut boş satırı bozma,
tüm dosyayı yeniden yazma (LF'e çevirirsen 4700 satırlık sahte diff çıkar).

```bash
python3 -m unittest $(grep -v '^#' .github/frappe-free-tests.txt | grep -v '^$' | tr '\n' ' ') 2>&1 | tail -5
npm run test:js
```

Hepsi yeşil olmadan İŞ 4'e geçme. **Buradaki sonuçları bana göster.**

---

# İŞ 4 — Birleştirme (K3: merge)

## 4.1 main'i dala al

```bash
cd ~/frappe-bench-local/apps/stabler/.worktrees/tender-ops-foundation
git fetch . main:refs/heads/main 2>/dev/null || true
git merge main
```

Beklenen çatışma: **yalnızca 6 append-only dosya.** Çözüm mekaniği:

- `.github/frappe-free-tests.txt` → iki tarafın satırlarını **birleştir**, tekilleştir,
  sırayı koru.
- 5 çeviri CSV'si → iki tarafın **yeni satırlarının hepsini** koru; **CRLF bozma**;
  çözüm sonrası her dosyayı `csv.reader` ile doğrula (malformed satır olmayacak).

Başka bir dosyada çatışma çıkarsa **DUR** ve bana getir — ölçüme göre çıkmaması gerekiyor.

```bash
python3 -c "
import csv
for l in ('en','ru','uz','uzc','tr'):
    rows=[r for r in csv.reader(open(f'stabler/translations/{l}.csv',encoding='utf-8')) if r]
    bad=[r for r in rows if len(r)!=2]
    print(l,len(rows),'malformed',bad[:2])
"
python3 -m unittest $(grep -v '^#' .github/frappe-free-tests.txt | grep -v '^$' | tr '\n' ' ') 2>&1 | tail -5
npm run test:js
make check 2>&1 | tail -30
```

`make check` hata verirse **iki listeye ayır**: (a) bizim ürettiğimiz → düzelt,
(b) dalda merge-base'te de var olan borç → dokunma, raporla.

## 4.2 Dal bütünü incelemesi

`pr-review-toolkit:code-reviewer` ile merge sonrası tüm diff'i incelet:

```bash
git log --oneline main..HEAD | cat
git diff --stat main..HEAD
```

Odak: üst kayıt hiçbir finansal/sourcing belgesi üretmiyor; parent toplamları çocukları
bir kez topluyor; `/app` linki yok; para `font-monospace`+MoneyInput; tarih
`formatDate`/`DateInput`; tablolar `table-striped` EKLEMİYOR; statü
`getStatusBadgeClass`. Bulguları bana getir.

## 4.3 main'e al

**ONAY sonrası:**

```bash
cd ~/frappe-bench-local/apps/stabler
git merge --no-ff codex/tender-ops-foundation
python3 -m unittest $(grep -v '^#' .github/frappe-free-tests.txt | grep -v '^$' | tr '\n' ' ') 2>&1 | tail -5
bench build --app stabler   # yerelde derleniyor mu
git log --oneline -3
```

Ana worktree'de `sales.py`, `composables/date.js`, `pages/sales/Customers.vue`
**kirli** — başka bir oturumun işi. **Stage etme, commit'e karıştırma.** Merge onları
etkiliyorsa dur ve bana söyle.

---

# İŞ 5 — Prod deploy

Bu deploy **iki iş paketini birlikte** taşır:

1. **Imports zinciri** (main'de bekliyordu): tedarikçi defteri CI adıyla konuşuyor,
   CI sapma tespiti, onaylı yeniden kayıt, PI/CI silme katmanı.
2. **Tender Master CRM temeli**: yeni doctype + v61 patch + `/tender/crm`.

## 5.1 Yedek + dry-run

```bash
ssh ice-production 'tar czf /root/stabler-app-$(date +%F-%H%M).tgz -C /home/frappe/frappe-bench/apps stabler && ls -lht /root/stabler-app-*.tgz | head -1'

cd ~/frappe-bench-local/apps
rsync -rltznv --no-owner --no-group --exclude-from=stabler/.rsync-exclude \
  stabler/ ice-production:/home/frappe/frappe-bench/apps/stabler/
```

**cwd tuzağı:** rsync'i bench `apps/` dizininden koş — `stabler/` app'in tamamı olsun.
Dry-run çıktısını **BANA GÖSTER**; silme listesinde kardeş dizin ya da
`stable-erp-website/` görürsen **DUR**. `-v` zorunlu (`-n` tek başına hiçbir şey basmaz;
boş çıktı "temiz" sanılır — bu daha önce yanlış doğrulamaya yol açtı).

## 5.2 ONAY sonrası uygula

```bash
cd ~/frappe-bench-local/apps
rsync -rltz --no-owner --no-group --exclude-from=stabler/.rsync-exclude \
  stabler/ ice-production:/home/frappe/frappe-bench/apps/stabler/
ssh ice-production 'chown -R frappe:frappe /home/frappe/frappe-bench/apps/stabler'
ssh ice-production 'cd /home/frappe/frappe-bench && bench build --app stabler'
```

## 5.3 Migrate — 7 SİTENİN HEPSİ (yeni doctype + v61 patch var)

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && for s in anjan dts horeca laminor mikas msa smartbox; do
  echo "=== $s ==="; bench --site "$s.erpstable.com" migrate 2>&1 | tail -4; done'
ssh ice-production 'cd /home/frappe/frappe-bench && bench restart'
```

`migrate` **site başına**; rsync ve restart bench genelinde. Yeni `Tender Master`
tablosu ve `custom_parent_tender` alanı yalnızca migrate ettiğin sitede oluşur —
birini atlarsan orada 500 alırsın (msa'da 2026-07-18'de tam bunu yaşadık).
`bench restart` **tüm tenant'ları** kısa süre etkiler — düşük trafikte koş.

## 5.4 Duman testleri (tarayıcı)

**mikas** (tender açık):
1. `#/tender/crm` → Kanban 5 şeritli; şeritler **türetilmiş** (elle statü değil);
   kart üstünde lot kırılımı + en yakın son tarih + politika açığı.
2. Bir tender kartına tıkla → yalnızca **o ihalenin** lotları; parent sayısı görünen
   lot sayısıyla **birebir**.
3. Parent'sız tender lotu varsa uyarı şeridi çıkıyor ve listeyi açıyor.
4. Sidebar: director + sourcing rolünde "Tender CRM" var; başka rollerde yok.
5. Dashboard KPI'sına tıkla → filtre `/tender/crm`'e taşınıyor ve **aynı kohortu** açıyor.

**msa** (imports açık, tender kapalı):
6. `#/tender/crm` **erişilemez** olmalı (modül kapısı).
7. `#/purchasing/suppliers` → tedarikçi → Defter: satırlar **CI numarasıyla**,
   tıklayınca CI formu; ödeme satırlarında Bank/Cash çipi.
8. Mevcut bir CI'ı doğrudan URL ile aç → dolu açılıyor (boş "New" DEĞİL);
   faturası varsa sapma bandı doğru rakamları veriyor.
9. Bir CI'da **Sil** → engel listesi gerçek bağlı kayıtları gösteriyor.
   **Gerçekten silme.**
10. `#/imports/discrepancies` + `#/reports/pi-group-container-status` hâlâ dolu.

**anjan** (ikisi de kapalı):
11. Menüde ne Tender CRM ne Imports görünüyor; `/tender/crm` doğrudan URL ile
    engelleniyor.

Her adımın sonucunu bana getir. Hata görürsen **dur**, rollback:
step 5.1'deki tar'ı geri yükle → `chown` → `bench build` → `bench restart`.

---

# Yapma

- `git add -A` yok; ana worktree'deki başka oturuma ait 3 kirli dosyayı stage etme.
- `custom_parent_tender`'ı **reqd yapma** — koşullu doğrulama K2'nin tamamı.
- Elle `status` alanını şerit kaynağı olarak bırakma (K1).
- Rebase deneme (K3) — merge.
- Çeviri CSV'lerini toptan yeniden yazma (CRLF!).
- Frappe v16'da string SELECT içinde SQL fonksiyonu kullanma.
- Dry-run çıktısını göstermeden gerçek rsync yok; 7 siteden birini migrate atlama.
- Duman testinde gerçek veri silme.
