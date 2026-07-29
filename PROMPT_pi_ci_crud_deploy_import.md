# msa — A·PI/CI tam CRUD → B·Deploy → C·Ödeme importu

Bu dosyanın tamamını Claude Code'a yapıştır, `~/frappe-bench-local/apps/stabler` içinden.
Üç iş SIRAYLA. **ONAY yazan yerde dur ve sor.** Her fazın sonunda çıktıyı göster.

Bağlam: `docs/plans/2026-07-29-pi-ci-full-crud.md` (tasarım kararları orada,
oku ve ona uy). Repo HEAD `2cd9e45` olmalı, kirli izlenen dosya olmamalı:

```bash
cd ~/frappe-bench-local/apps/stabler && git log --oneline -1 && git status --short | grep -v '^??'
```

`stabler/api/sales.py`, `composables/date.js`, `pages/sales/Customers.vue`,
`pages/purchasing/Suppliers.vue` başka bir oturuma ait olabilir — **onlara dokunma,
stage etme.** `git add -A` YASAK, yol yol stage et.

---

# İŞ A — PI/CI tam CRUD (kod)

Bugün C/R/U var, **D yok**. Bunu ekliyoruz + iki kontrol aksiyonu.

## A.1 Saf kural modülü — `stabler/api/_imports_delete.py`

Frappe'siz, test edilebilir. Tek işi: bulunan referansları **engel** ve **devir**
diye ayırmak.

```python
def classify_impact(refs: dict) -> dict:
    """refs = {"<Doctype>": [ {"name":..., "docstatus":..., "status":...}, ... ]}
    döner: {"blockers": [{"doctype","name","reason"}], "cascade": {dt: [names]},
            "deletable": bool}"""
```

Kurallar (planın §3'ü):

- **ENGEL** — muhasebe/resmî belge, asla otomatik silinmez:
  `Purchase Invoice` (docstatus < 2), `Payment Entry` (docstatus < 2),
  `Landed Cost Voucher` (docstatus < 2), `GRN Checklist` (docstatus == 1),
  `Customs Declaration` (herhangi bir kayıt).
- **DEVİR** — operasyonel çocuk, yalnız `cascade=1` ile silinir:
  `Import Container`, `Import Truck`, `Freight Booking`, `Vet Certificate`,
  `Commercial Invoice PO Link`, `GRN Checklist` (docstatus == 0).
- Referans yoksa `deletable=True`, `blockers=[]`.
- Her engel **adı konmuş sebep** taşır (`reason`), boş string olamaz.
- Bilinmeyen doctype **sessizce yok sayılmaz** → engel say (fail-closed).

## A.2 Uçlar — `stabler/api/imports.py`

```python
@frappe.whitelist()
def delete_commercial_invoice(company, name, cascade=0, dry_run=1) -> dict
@frappe.whitelist()
def delete_proforma_invoice(company, name, cascade=0, dry_run=1) -> dict
@frappe.whitelist()
def unlink_proforma_from_ci(company, proforma, commercial_invoice) -> dict
```

Ortak kurallar:

- `_assert_imports_access(company)` + `_assert_cost_visible()` +
  `_assert_can_write("<Doctype>", name, "delete")`.
- `dry_run` **varsayılan 1** ve hiçbir mutasyona ULAŞMADAN döner
  (plan: `{blockers, cascade, deletable, dry_run: True}`).
- `dry_run=0` iken `blockers` doluysa `frappe.throw(blockers[0]["reason"])`.
- `cascade=0` iken devir listesi doluysa da dur — kullanıcı açıkça istemeli.
- Silme sırası: önce çocuklar (devir), sonra ana belge; hepsi TEK transaction,
  hata olursa `frappe.db.rollback()`.
- CI referanslarını toplarken **doctype başına tek sorgu** (N+1 yok).
  CI'a bağlanan alanlar (kod taramasıyla doğrulandı):
  `GRN Checklist.commercial_invoice`, `Customs Declaration.commercial_invoice`,
  `Import Truck.commercial_invoice`, `Import Container.commercial_invoice`,
  `Commercial Invoice PO Link.commercial_invoice`, `Vet Certificate.commercial_invoice`,
  `Import Expense.commercial_invoice`, `Freight Booking.commercial_invoice`,
  `Proforma Invoice.commercial_invoice`, artı
  `Purchase Invoice.custom_commercial_invoice` (kolon varsa) ve
  `Payment Entry.custom_import_container` (bu CI'ın konteynerleri üzerinden).
- PI referansları: `Commercial Invoice Item.custom_proforma_invoice`,
  `Commercial Invoice.custom_proforma_invoice` (kolon varsa).
  **PI silinirken CI satırları SİLİNMEZ** — sadece `custom_proforma_invoice`
  boşaltılır (sapmalar ekranı onları "PI'sız sevk" olarak zaten gösteriyor).
- `unlink_proforma_from_ci`: PI'ın `commercial_invoice` alanını temizler,
  statüyü `SUPERSEDED_BY_CI` → `CONFIRMED` yapar, CI'ın
  `custom_proforma_invoice` alanını temizler. İdempotent (bağ yoksa no-op).
  Statü geri alma için mevcut `assert_transition` geri-düzeltme kalıbını kullan
  (yetkili rol + sebep); yeni bir bypass icat etme.

## A.3 UI

- `public/js/pages/imports/CommercialInvoiceForm.vue` ve
  `public/js/pages/imports/ProformaForm.vue` → footer'a **Sil**
  (`btn-outline-danger`, form başına en fazla bir `btn-primary` kuralı bozulmasın).
- Akış: tıkla → `dry_run: 1` planı çek → modal:
  engeller kırmızı liste (**her engelin yanında o kaydı açan router-link**),
  devir listesi kalem kalem, "Bağlı kayıtları da sil" checkbox (`cascade`),
  sonra kırmızı onay (`danger: true`) → `dry_run: 0`.
- `useConfirm` imzası: `{ title, body, danger, confirmLabel }` — `message`/
  `confirmText` YOK.
- Engel varsa silme düğmesi pasif kalsın; sebep tooltip'te görünsün.
- CI formunda ayrıca **PI bağını kaldır** düğmesi (PI bağlıysa görünür).
- Desk (`/app/...`) linki YASAK. Tarih alanları `formatDate`/`DateInput`,
  para `formatMoney`/MoneyInput, statü `getStatusBadgeClass`.

## A.4 Testler — `stabler/tests/`

`test_imports_delete_math.py` (saf):
- GL belgesi HER ZAMAN engel (5 tipin her biri ayrı subTest)
- submitted GRN engel, draft GRN devir
- referans yoksa `deletable=True`
- bilinmeyen doctype fail-closed (engel)
- her blocker'ın `reason`'ı dolu

`test_imports_delete_source.py` (yapısal):
- üç uç `@frappe.whitelist()` + imports-gated + `_assert_can_write(..., "delete")`
- `dry_run` varsayılanı 1; dry-run herhangi bir `.delete(`/`db_set`/`.cancel(`
  satırına ULAŞMADAN döner (index karşılaştırması)
- `cascade=0` iken çocuk silinmiyor
- referans toplama döngü İÇİNDE sorgu yok (N+1 guard)
- PI silmede CI satırı silinmiyor, sadece alan boşaltılıyor
- UI önce `dry_run: 1` çekiyor, sonra `confirm`, sonra `dry_run: 0`
  (kontrolü **fonksiyona daraltarak** yap — formda başka confirm'ler var,
  global `index()` yanlış eşleşir)
- `/app` linki yok

İkisini de `.github/frappe-free-tests.txt` içine `stabler.tests.<modül>`
formatında ekle (dosya yolu DEĞİL).

## A.5 i18n + doğrulama

- Yeni tüm kullanıcı stringleri **5 dilde**: `stabler/translations/{en,ru,uz,uzc,tr}.csv`.
  **Dosyalar CRLF** — satırı `\r\n` ile ekle, dosyanın sonundaki mevcut boş
  satırı bozma, tüm dosyayı yeniden yazma (LF'e çevirirsen 4700 satırlık sahte
  diff çıkar).
- `python3 -m unittest $(grep -v '^#' .github/frappe-free-tests.txt | grep -v '^$' | tr '\n' ' ')`
  → hepsi yeşil (şu an 1790).
- `bench build --app stabler` yerelde geçmeli.
- Commit: yol yol stage, trailer `Co-Authored-By: Claude <noreply@anthropic.com>`.

**Bittiğinde bana göster:** yeni uçların imzaları, test sayısı, commit hash.
**ONAY almadan İŞ B'ye geçme.**

---

# İŞ B — Deploy

Gidecekler: `fe25fec` (tedarikçi defteri CI adıyla konuşuyor),
`4ce31e7` (kayıttan sonra değişen CI tespiti), `069bc95` (onaylı yeniden kayıt),
`2cd9e45` (plan) + İŞ A commit'i.

```bash
ssh ice-production 'tar czf /root/stabler-app-$(date +%F-%H%M).tgz -C /home/frappe/frappe-bench/apps stabler && ls -lht /root/stabler-app-*.tgz | head -1'

cd ~/frappe-bench-local/apps
rsync -rltznv --no-owner --no-group --exclude-from=stabler/.rsync-exclude \
  stabler/ ice-production:/home/frappe/frappe-bench/apps/stabler/
```

**cwd tuzağı:** rsync'i bench `apps/` dizininden koş. Dry-run çıktısını BANA
GÖSTER; silme listesinde kardeş dizin ya da `stable-erp-website/` görürsen DUR.
`-v` zorunlu (`-n` tek başına hiçbir şey basmaz, boş çıktı "temiz" sanılır).

**ONAY** sonrası aynı komut `-rltz` ile, ardından:

```bash
ssh ice-production 'chown -R frappe:frappe /home/frappe/frappe-bench/apps/stabler'
ssh ice-production 'cd /home/frappe/frappe-bench && bench build --app stabler'
ssh ice-production 'cd /home/frappe/frappe-bench && for s in anjan dts horeca laminor mikas msa smartbox; do
  echo "=== $s ==="; bench --site "$s.erpstable.com" migrate 2>&1 | tail -3; done'
ssh ice-production 'cd /home/frappe/frappe-bench && bench restart'
```

`bench restart` TÜM tenantları kısa süre etkiler — düşük trafikte koş.

## B.1 Duman testleri (msa, tarayıcı)

1. `#/purchasing/suppliers` → bir tedarikçi → Defter: satırlar CI numarasıyla,
   tıklayınca CI formu açılıyor; ödeme satırlarında Bank/Cash çipi; yanlarındaki
   soluk PINV-… drawer'ı açıyor.
2. `#/imports/commercial-invoices/<mevcut bir CI>` → doğrudan URL ile açılıyor
   (boş "New" formu DEĞİL); faturası varsa sapma bandı doğru rakamları veriyor.
3. Sapma bandındaki **İptal et ve yeniden kaydet** → plan modalı çıkıyor
   (İPTAL et, uygulama). Plan metni hangi faturayı iptal edeceğini ve kaç
   ödemenin taşınacağını söylüyor mu?
4. Bir CI'da **Sil** → engeller listesi gerçek bağlı kayıtları gösteriyor
   (faturası olan CI'da "canlı borç" engeli çıkmalı). **Gerçekten silme.**
5. `#/imports/discrepancies` ve `#/reports/pi-group-container-status` hâlâ dolu.

Hata görürsen dur, ekran çıktısını getir.

---

# İŞ C — Ödeme importu

`PROMPT_import_vendor_history.md` dosyasını aç ve **onu baştan sona uygula**
(audit → SUPPLIER_MAP onayı → `ensure_accounts` → mali yıl → 394 PE →
CI→PInv → FIFO mahsup → `compare()`).

Deploy'dan SONRA koşuyoruz ki defter dolarken satırlar zaten CI adıyla görünsün.

Bitince `compare()` tablosunu bana getir: her vendor'ın ledger kapanışı vs
Excel Остаток (HMA ~9,3M · FAIR 3,08M · MIRHA 1,47M · ALS 2,44M ·
AL-DUA 1,02M · IFF ~0). Delta ≠ 0 hata değil bilgi — sevk edilmemiş PI kalanı,
Excel'in kendi tutarsızlıkları (IFF +217; ALS −63 988 banka), ya da convert
exceptions.

---

# Yapma

- `git add -A` yok; başka oturuma ait dosyaları stage etme.
- İŞ A onayı olmadan deploy, deploy dry-run'ı gösterilmeden gerçek rsync yok.
- Silme uçlarında `cascade`/`dry_run` varsayılanlarını gevşetme.
- Muhasebe belgesi olan bir CI'ı zorla silme — engel kalkmaz, önce fatura iptal.
- Çeviri CSV'lerini toptan yeniden yazma (CRLF!).
- Prod'da `bench --site ... console` ile veri yazan tek satır bile İŞ C'nin
  onay kapıları dışında koşmasın.
