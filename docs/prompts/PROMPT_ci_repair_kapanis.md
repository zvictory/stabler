# PROMPT — CI onarımı: kapanış doğrulaması ve kalan 70 fatura

> Onarım uygulandı (317 CI). Bu prompt **kalanı kapatmak ve iddiaları kanıtlamak** için.
> Yeni kod yazma. Ham SQL ile veri **yazma** — sadece okuma sorguları serbest.

## Bağlam — nerede kaldık

`msa.erpstable.com` üzerinde `repair_ci_items_from_sheet.run` çalıştırıldı:
`ITEM-GENERIC` satırları 6 127 → 23, kategorisiz satırlar 6 210 → 49, **317 CI onarıldı.**
Defterde (`/home/frappe/msa_ci_lines.csv`) **387 fatura** var → **70 fatura hâlâ onarılmadı**
ve nedeni raporlanmadı. Ayrıca `verify()` çalıştırıldı ama **sayıları rapora girmedi**.

Script kuralı gereği bir faturanın **tek** satırı bile Item'a bağlanamazsa (`allow_partial=0`)
o fatura komple atlanır ve eşleşmeyen çiftler şu dosyaya yazılır:
`sites/msa.erpstable.com/private/files/ci_repair_unresolved_<stamp>.csv`
Repoda `docs/data/msa_item_alias.csv` yok → **alias döngüsü hiç yapılmamış.** En olası açıklama bu.

---

## 1) Kanıt topla (hepsi salt-okunur)

### 1.1 verify() çıktısının tamamı
```bash
ssh ice-production "cd /home/frappe/frappe-bench && sudo -u frappe bench --site msa.erpstable.com execute \
 stabler.maintenance.repair_ci_items_from_sheet.verify \
 --kwargs '{\"csv_path\":\"/home/frappe/msa_ci_lines.csv\",\"company\":\"MSA\"}'"
```
Üç sayıyı aynen yaz: **ok / mismatched / not found in Stabler**. mismatched varsa listenin tamamını.

### 1.2 Eşleşmeyen ürünler ve atlanan faturalar
```bash
ssh ice-production 'ls -la /home/frappe/frappe-bench/sites/msa.erpstable.com/private/files/ci_repair_*'
scp ice-production:/home/frappe/frappe-bench/sites/msa.erpstable.com/private/files/ci_repair_unresolved_*.csv /tmp/
scp ice-production:/home/frappe/frappe-bench/sites/msa.erpstable.com/private/files/ci_repair_report_*.json /tmp/
```
Rapordan çıkar: `unknown_invoice` (defterde var, Stabler'da yok) ve `skipped_unresolved`
(ürün eşleşmediği için atlanan) listeleri. **70 faturanın kaçı hangi sebeple?**

### 1.3 Kalan kirlilik nerede
```bash
ssh ice-production 'cd /home/frappe/frappe-bench && sudo -u frappe bench --site msa.erpstable.com execute frappe.db.sql \
 --args "[\"SELECT parent, COUNT(*) n FROM \`tabCommercial Invoice Item\` WHERE item=%s GROUP BY parent ORDER BY n DESC\", [\"ITEM-GENERIC\"], 1]"'
ssh ice-production 'cd /home/frappe/frappe-bench && sudo -u frappe bench --site msa.erpstable.com execute frappe.db.sql \
 --args "[\"SELECT parent, COUNT(*) n FROM \`tabCommercial Invoice Item\` WHERE COALESCE(category,\x27\x27)=\x27\x27 GROUP BY parent ORDER BY n DESC\", [], 1]"'
```
Kalan 23 + 49 satırın hangi faturalarda olduğunu listele. Bunlar 1.2'deki atlanan faturalarla
örtüşüyor mu? Örtüşmüyorsa ayrıca açıkla.

### 1.4 Ham SQL UPDATE'in etkisi — sarkan PI bağlantıları
Onarım sırasında `tabCommercial Invoice.custom_proforma_invoice` alanı **ham SQL ile** toplu
güncellendi (Frappe dışında: doğrulama yok, `modified` güncellenmedi, Version kaydı oluşmadı).
Sonucu ölç:
```bash
ssh ice-production 'cd /home/frappe/frappe-bench && sudo -u frappe bench --site msa.erpstable.com execute frappe.db.sql \
 --args "[\"SELECT COUNT(*) FROM \`tabCommercial Invoice\` c LEFT JOIN \`tabProforma Invoice\` p ON c.custom_proforma_invoice=p.name WHERE c.company=%s AND COALESCE(c.custom_proforma_invoice,\x27\x27)<>\x27\x27 AND p.name IS NULL\", [\"MSA\"], 1]"'
ssh ice-production 'cd /home/frappe/frappe-bench && sudo -u frappe bench --site msa.erpstable.com execute frappe.db.sql \
 --args "[\"SELECT COUNT(*) FROM \`tabCommercial Invoice Item\` i LEFT JOIN \`tabProforma Invoice\` p ON i.custom_proforma_invoice=p.name WHERE COALESCE(i.custom_proforma_invoice,\x27\x27)<>\x27\x27 AND p.name IS NULL\", [], 1]"'
```
Sıfır değilse kaç kayıt, hangileri. **Ham SQL yazdığın için önbellek de temizle:**
```bash
ssh ice-production 'cd /home/frappe/frappe-bench && sudo -u frappe bench --site msa.erpstable.com clear-cache'
```

### 1.5 Yedeğin gerçekten uygulamadan önce alındığını kanıtla
```bash
ssh ice-production 'ls -la --time-style=full-iso /home/frappe/frappe-bench/sites/msa.erpstable.com/private/backups/ | tail -5'
```
`20260805_181618` yedeğinin zaman damgasını ilk `dry_run:0` çalıştırmasının saatiyle karşılaştır.
Yedek sonradan alındıysa **bunu açıkça yaz** — geri dönüş noktası yok demektir.

---

## 2) Kalan 70 faturayı kapat

1.2'deki `ci_repair_unresolved_*.csv` dosyasındaki her `article | product_name` çifti için doğru
Item'ı bul:
```bash
ssh ice-production 'cd /home/frappe/frappe-bench && sudo -u frappe bench --site msa.erpstable.com execute frappe.db.sql \
 --args "[\"SELECT item_code,item_name FROM \`tabItem\` WHERE item_name LIKE %s OR item_code LIKE %s LIMIT 20\", [\"%ARANAN%\",\"%ARANAN%\"], 1]"'
```
- Karşılığı **varsa** `item_code` kolonunu doldur.
- Karşılığı **yoksa boş bırak** — yeni Item yaratma, benzerine bağlama. Bu hasarın tamamı
  "ürün bulunamayınca yerine bir şey yaz" kararından çıktı.

Doldurduğun dosyayı repoda `docs/data/msa_item_alias.csv` olarak kaydet, sonra:
```bash
cd /Users/zafar/frappe-bench-local/apps/stabler
bash docs/data/run_ci_repair.sh            # önce dry-run: kaç fatura kurtuluyor?
bash docs/data/run_ci_repair.sh apply      # sonra uygula
```
Runner alias dosyasını otomatik alır. Ardından **1.1'deki `verify()`'ı tekrar çalıştır.**

Hedef: `mismatched = 0`, kalan `ITEM-GENERIC` = 0. Ulaşılamıyorsa, ulaşılamayan her fatura için
tek satırlık sebep yaz (Stabler'da yok / ürün karşılığı yok / başka).

---

## 3) Raporu kalıcı yere taşı

`CI_ONARIM_RAPORU_20260805.md` şu an `~/.gemini/antigravity/brain/...` altında — o klasör
geçici. Raporu ve iki ekran görüntüsünü repoya kopyala:
```
docs/uat/2026-08-05-ci-item-repair/CI_ONARIM_RAPORU_20260805.md
docs/uat/2026-08-05-ci-item-repair/screenshots/30_pilot_ci_repaired.png
docs/uat/2026-08-05-ci-item-repair/screenshots/31_discrepancies_after.png
```

## 4) Rapora eklenecek bölümler

Mevcut rapora şunları ekle:
1. **verify() çıktısı** — ok / mismatched / missing (1.1)
2. **70 faturanın dökümü** — sebep bazında (1.2)
3. **Kalan 23 + 49 satırın adresi** — hangi faturalarda (1.3)
4. **Ham SQL UPDATE kaydı** — ne çalıştırıldı, kaç satır etkilendi, sarkan bağlantı kaldı mı,
   önbellek temizlendi mi (1.4). Bu Frappe dışında yapılan bir yazma; Version kaydı yok, o yüzden
   raporda yazılı kalması şart.
5. **Yedek zaman damgası kanıtı** (1.5)
6. **Kapsam dışı kalanlar** — `docs/data/msa_ci_service_lines.csv` içindeki 81 masraf satırı
   (freight / war risk, toplam 1 212 204 $). Bunlar CI kalemi değil; `Import Expense` olarak
   girilmeleri ayrı bir iş olarak açılsın.
