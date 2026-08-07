# PROMPT — MSA Commercial Invoice kalem onarımı (prod uygulama)

> SSH erişimi olan ajana (Antigravity / zcode) bu dosyanın tamamını ver.
> Yeni kod yazılmayacak. Hazır script çalıştırılacak, sonuç doğrulanacak, raporlanacak.

---

## 0) Durum

`msa.erpstable.com` (Frappe + `stabler`) üzerinde **Commercial Invoice (CI) kalemleri bozuk**:
eski MSAERP sqlite'ından veri aktaran `stabler/maintenance/migrate_msaerp_imports.py`,
kaynakta ürün bağlantısı olmayan satırlar için `ensure_item()` içinde sessizce
**`ITEM-GENERIC`** placeholder'ı yazmış ve kategoriyi **NULL** bırakmış; üstelik
`ignore_validate` + `ignore_links` ile kaydettiği için hiçbir uyarı üretmemiş.
Ayrıca script her çalıştığında `frappe.db.delete("Commercial Invoice Item", {"parent": ci})`
yapıp kalemleri baştan yazıyor — yani yıkıcı ve idempotent değil.

**Sonuç:** PI ↔ CI eşleşmesi çöktü. Eşleşme anahtarı `(PI, kategori)` — ürün değil
(`stabler/api/_imports_rules.py`, satır 926-930). Kategorisi boş satır hiçbir PI satırıyla
eşleşemez → arayüzde "Вне ПИ" / "N строк(и) расходятся с ПИ".

**Doğruluk kaynağı:** MSA'nın operasyon defteri (`CI MSA.xlsx / Sheet1`) — 7 400 satır,
387 invoice, 90 PI, 31 830 861 kg. Defterin kendi kontrol toplamlarıyla iki kez çapraz
doğrulandı (1 570 317 kutu, 127 032 500 $ beyan).

---

## 1) Girdiler (repoda hazır, `/Users/zafar/frappe-bench-local/apps/stabler/`)

| Dosya | İçerik |
|---|---|
| `stabler/maintenance/repair_ci_items_from_sheet.py` | onarım + `verify()` + `restore()` |
| `docs/data/msa_ci_lines.csv` | 7 400 satırlık kaynak veri |
| `docs/data/msa_ci_expected_totals.csv` | 387 invoice için beklenen toplamlar |
| `docs/data/msa_item_alias_template.csv` | 38 farklı `Article \| ürün` çifti |
| `docs/data/run_ci_repair.sh` | tek komutluk çalıştırıcı |
| `docs/data/msa_ci_service_lines.csv` | 81 masraf satırı — **bu işin kapsamı dışında** |

Alan eşlemesi (script'te uygulanmış): `docs_price` ← defterin `docs price`,
`rate` ← `Agreed price / kg`, `docs_amount` ← `сумма`, `amount` ← kg × agreed.
İkisi 7 269 fiyatlı satırın 5 520'sinde farklı — beyan sabit, gerçek fiyat ürün bazında.

---

## 2) Kesin kurallar

- **Yalnızca `msa.erpstable.com`.** Başka site yok. Her adımdan önce siteyi doğrula.
- **`bench restart` YOK, `bench migrate` YOK, `bench build` YOK.** Script `bench execute`
  ile import edilir; kod değişikliği gerektirmez. Restart 7 tenant'ı birden etkiler.
- **rsync'te `--delete` YOK.** Tek dosya kopyalanacak, `scp` yeterli.
- Yeni kod yazma, mevcut script'i düzenleme. Hata çıkarsa **dur ve raporla**.
- `git add -A` yok; zaten commit atman gerekmiyor.
- Uygulama adımından önce **site yedeği zorunlu**.

---

## 3) Adımlar

### A. Ön kontrol
```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com list-apps | grep stabler'
ssh ice-production 'df -h /home/frappe | tail -1'
```
`stabler` çıkmazsa **DUR**.

Hasarın gerçek boyutunu ölç (salt-okunur):
```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com execute frappe.db.sql \
 --args "[\"SELECT COUNT(*) rows_, COUNT(DISTINCT parent) cis FROM \`tabCommercial Invoice Item\` WHERE item=%s\", [\"ITEM-GENERIC\"], 1]"'
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com execute frappe.db.sql \
 --args "[\"SELECT COUNT(*) rows_, COUNT(DISTINCT parent) cis FROM \`tabCommercial Invoice Item\` WHERE COALESCE(category,\x27\x27)=\x27\x27\", [], 1]"'
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com execute frappe.db.get_value \
 --args "[\"Item\",\"ITEM-GENERIC\",\"creation\"]"'
```
Son sorgu, bozan migrasyonun **ne zaman çalıştığını** verir. Üç sonucu da rapora yaz.

### B. Dry run (hiçbir şey yazmaz)
```bash
cd /Users/zafar/frappe-bench-local/apps/stabler
bash docs/data/run_ci_repair.sh
```
Çıktıdan şunları rapora al: `matched`, `unknown invoice`, `skipped (item?)`,
`ITEM-GENERIC lines being replaced`, `category-less lines being replaced`,
ve **eşleşmeyen `Article | ürün` listesi**.

### C. Alias döngüsü (yalnızca eşleşmeyen varsa)
Script eşleşmeyenleri hazır formatta yazar:
`sites/msa.erpstable.com/private/files/ci_repair_unresolved_<stamp>.csv`
```bash
scp ice-production:/home/frappe/frappe-bench/sites/msa.erpstable.com/private/files/ci_repair_unresolved_*.csv /tmp/
```
`item_code` kolonunu doldur. Doğru Item'ı bulmak için:
```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com execute frappe.db.sql \
 --args "[\"SELECT item_code,item_name FROM \`tabItem\` WHERE item_name LIKE %s OR item_code LIKE %s LIMIT 20\", [\"%TOPSIDE%\",\"%41%\"], 1]"'
```
**Var olmayan Item'ı uydurma, yeni Item yaratma.** Karşılığı gerçekten yoksa o satırı boş
bırak — script o invoice'ı atlar ve raporlar; bu, yanlış ürün yazmaktan iyidir.
Doldurduğun dosyayı `docs/data/msa_item_alias.csv` olarak kaydet (runner otomatik alır),
dry-run'ı tekrarla. Eşleşmeyen sayısı 0 veya kabul edilebilir olana kadar döngü.

### D. Yedek (uygulamadan önce, zorunlu)
```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com backup --with-files'
```
Yedek dosyasının yolunu rapora yaz.

### E. Pilot — tek invoice
```bash
bash docs/data/run_ci_repair.sh apply MH/104/202526
```
Sonra **arayüzden gözle doğrula**: `https://msa.erpstable.com/stabler#/imports/commercial-invoices/<CI>`
- Kalemler ürün bazında mı geldi (ITEM-GENERIC kalmadı mı)?
- Her satırda **Категория поставщика** dolu mu?
- "Вне ПИ" / "расходятся с ПИ" uyarıları kayboldu mu?
- Alt toplamlar (agreed / docs / nakit farkı) `msa_ci_expected_totals.csv`'deki satırla aynı mı?
Ekran görüntüsü al. **Bir tanesi bile tutmuyorsa DUR ve raporla.**

### F. Tam uygulama
```bash
bash docs/data/run_ci_repair.sh apply
```
Çıktıdaki `applied` ve `failed` sayılarını al. `failed` boş değilse her birinin hatasını yaz.

### G. Doğrulama (script'in kendi doğrulayıcısı)
```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com execute \
 stabler.maintenance.repair_ci_items_from_sheet.verify \
 --kwargs "{\"csv_path\":\"/home/frappe/msa_ci_lines.csv\",\"company\":\"MSA\"}"'
```
Bu, veritabanını CSV ile satır satır karşılaştırır: satır sayısı, kutu, kg, agreed, docs,
kalan `ITEM-GENERIC`, kategorisiz satır. **Beklenen: `mismatched = 0`.**
Kalan `ITEM-GENERIC` sayısını da A adımındaki ilk ölçümle karşılaştır.

### H. Sistem etkisi kontrolü (arayüzden)
- `#/imports/discrepancies` — sapma sayısı düştü mü? Öncesi/sonrası rakamı yaz.
- Onarılan 2-3 CI'ı aç, "Связанные контейнеры" ve PI eşleşme panelini kontrol et.
- Bir PI aç (`#/imports/proformas/<PI>`) — "Fulfillment Summary" artık gerçek kg gösteriyor mu?

---

## 4) Geri alma

Script dokunduğu her CI'ı önce JSON'a döker:
`sites/msa.erpstable.com/private/files/ci_items_backup_<stamp>.json`
```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com execute \
 stabler.maintenance.repair_ci_items_from_sheet.restore \
 --kwargs "{\"backup_path\":\"<yol>\",\"dry_run\":0}"'
```
Bu yetmezse D adımındaki site yedeği.

**Şu durumlarda geri al ve dur:** pilot invoice arayüzde yanlış görünüyorsa; `verify`
mismatched > 0 ise; `failed` listesi 5'ten fazlaysa; toplam kg/tutar beklenenden sapıyorsa.

---

## 5) Rapor

`CI_ONARIM_RAPORU_<tarih>.md`:
1. **Öncesi** — kaç `ITEM-GENERIC` satırı, kaç kategorisiz satır, kaç CI; `ITEM-GENERIC` Item'ının `creation` tarihi.
2. **Dry run** — matched / unknown / skipped sayıları, eşleşmeyen ürün listesi ve nasıl çözüldüğü.
3. **Uygulama** — applied / failed, yedek dosya yolları.
4. **`verify` çıktısı** — ok / mismatched / missing; mismatched varsa her biri.
5. **Sonrası** — kalan `ITEM-GENERIC` sayısı, sapma raporundaki değişim, ekran görüntüleri.
6. **Kapsam dışı kalanlar** — Stabler'da bulunamayan invoice'lar (defterde var, sistemde yok) ve
   81 masraf satırı; bunlar ayrı bir iş olarak listelenecek.
