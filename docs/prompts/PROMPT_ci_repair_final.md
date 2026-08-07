# PROMPT — CI onarımı: 5 tedarikçi, son tur

> Ajana ver. Yeni kod yazma. Ham SQL ile **yazma** yok — okuma serbest.
> Script: `stabler/maintenance/repair_ci_items_from_sheet.py` (güncel sürüm repoda).

## Amaç — tek cümleyle

Anlaşma **vendor kategorisi** üzerinden yapılır (bir kategori = bir konteynerin tarifi),
proforma o kategoriden **N konteyner** sipariş eder, ve o siparişe karşı gelen her sevkiyat
satırı CI'da **aynı kategoriyi** göstermek ve **aynı PI'ı** işaret etmek zorundadır.
`(PI, kategori)` bu defterin hesap kalemidir: sipariş − sevk = kalan bakiye.

Kapsam: **HMA, Mirha, Al Super, IFF, FAIR** → 351 fatura, 7 270 mal satırı, 57 PI,
**205 `(PI, kategori)` anahtarı**.

Not: alt kesim kırılımı (TOPSIDE / SILVER SIDE / NECK …) PI ile CI arasında **karşılaştırılmaz**.
Demet "compensated"tır; konteynerin içindeki karışım değişebilir, sözleşmesel olan demet toplamıdır.

## Bir CI birden fazla PI taşıyabilir — bu istisna değil, kural

Kapsamdaki **351 faturanın 82'si birden fazla proformadan mal taşıyor** (784 satır):

| CI başına PI sayısı | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| fatura | 269 | 56 | 20 | 4 | 2 |

En uçtaki örnek `MH/1244/2025-26`: tek faturada **5 ayrı PI**
(`HMA/PI/405/2025-26`, `1167`, `1168`, `1209`, `1240`).

Ve daha incesi: **16 satırda aynı faturada aynı kategori iki farklı PI'dan geliyor.**
Örnek `MH/1310/2025-26` → CUBE ROLL hem `HMA/PI/1167/2025-26`'dan hem `HMA/PI/1351/2025-26`'dan.

Bunun üç sonucu var, üçü de bu turda uygulanıyor:

1. **PI referansı satırda tutulur, başlıkta değil.** Başlıktaki tek bağlantı bu 82 fatura için
   tanımı gereği yanlıştır.
2. **Sessiz yanlış atama tehlikesi gerçektir.** Sapma motoru
   `COALESCE(NULLIF(cii.custom_proforma_invoice,''), ci.custom_proforma_invoice)` ile çalışıyor:
   satırda referans yoksa **başlıktakini devralır**. Yani PI'sız bir satır "eşleşmemiş" görünmez —
   *yanlış kontrattan düşer*. `require_pi=1` tam olarak bunu engellemek için var.
3. **Doğrulama artık PI'ı anahtara dahil ediyor.** `verify()` satır karşılaştırmasını
   `(PI, kategori, kutu, kg)` üzerinden yapıyor. PI anahtardan çıkarılırsa, yanlış kontrata
   yazılmış bir satır testi geçerdi.
   `key_ledger()` ise **başlık fallback'ini bilerek uygulamaz** — sadece satırdaki referansa bakar,
   böylece "atanmış gibi görünen" satırlar ortaya çıkar.

## Sıra

### 1. Dry run
```bash
cd /Users/zafar/frappe-bench-local/apps/stabler
bash docs/data/run_ci_repair.sh
```
Çıktıda üç satır kritik:
- `skipped (no PI)` → PI'ı Stabler'da bulunmayan faturalar. Altındaki
  **"PI references not found in Stabler (create these first)"** listesi = önce açılması gereken PI'lar.
- `skipped (item?)` + `ci_repair_unresolved_*.csv` → eşleşmeyen ürün. Beklenti: boş veya sadece
  `888888888 | BELLY FAT`.
- `skipped (supplier)` → kapsam dışı 36 fatura. Bu normaldir, hata değildir.

**Eksik PI varsa önce onları aç** (Frappe üzerinden, ham SQL değil), sonra dry-run'ı tekrarla.
PI'sız satır yazmak yasak: PI referansı olmayan satır tanımı gereği eşleşemez, yani onarım
"Вне ПИ" durumunu yeniden üretir.

### 2. Uygula
```bash
bash docs/data/run_ci_repair.sh apply
```
Her fatura önce JSON'a yedeklenir. `failed` boş olmalı.

### 3. Doğrula — CI defterle birebir mi
```bash
ssh ice-production "cd /home/frappe/frappe-bench && sudo -u frappe bench --site msa.erpstable.com execute \
 stabler.maintenance.repair_ci_items_from_sheet.verify \
 --kwargs '{\"csv_path\":\"/home/frappe/msa_ci_lines.csv\",\"company\":\"MSA\",\"only_suppliers\":\"HMA,Mirha,Al Super,IFF,FAIR\"}'"
```
Bu artık toplamlara değil **satır çoklu-kümesine** bakıyor: her satır için `(PI, kategori, kutu, kg)`.
Ayrıca her satırda kategori dolu mu, PI referansı dolu mu, o PI gerçekten var mı, ürün
`ITEM-GENERIC` değil mi — dördü birden.

**Başarı ölçütü, birebir bu satır:**
```
EVERY invoice in scope reproduces the book: category, product split,
boxes, kg, both prices, and a live PI reference on every single line.
```

### 4. Doğrula — sözleşme defteri tutuyor mu
```bash
ssh ice-production "cd /home/frappe/frappe-bench && sudo -u frappe bench --site msa.erpstable.com execute \
 stabler.maintenance.repair_ci_items_from_sheet.key_ledger \
 --kwargs '{\"csv_path\":\"/home/frappe/msa_ci_lines.csv\",\"company\":\"MSA\",\"only_suppliers\":\"HMA,Mirha,Al Super,IFF,FAIR\"}'"
```
`(PI, kategori)` başına sipariş / sevk / kalan bakiye. Dört şey raporlanır:
- `shipped against no PI line` → CI'da var, hiçbir PI o kategoriyi sipariş etmemiş
- `over-shipped` → kalan bakiye negatif (**bir bulgudur, hata değil — asla sıfıra kırpılmaz**)
- `CI lines with no PI reference` → 0 olmalı
- `keys the book expects but no PI carries` → PI tarafında da onarım gerektiğinin işareti

**Başarı ölçütü:**
```
Every shipped box sits on a contract key its proforma booked.
```

### 5. Arayüzden gözle
- Onarılan 2 CI: her satırda **Категория поставщика** dolu, **Реф. ПИ** dolu, "Вне ПИ" yok.
- **Çoklu PI kontrolü:** `MH/1244/2025-26` faturasını aç — satırlardaki **Реф. ПИ** kolonu
  5 farklı PI göstermeli, hepsi tek bir PI'a düşmüş olmamalı. Ayrıca `MH/1310/2025-26`:
  iki CUBE ROLL satırı **farklı** PI göstermeli. Ekran görüntüsü al.
- Bir PI aç: "Fulfillment Summary" gerçek sevk edilen kg'yi gösteriyor, "Shipment match"
  paneli eşleşen satırları sayıyor.
- `#/imports/discrepancies`: öncesi/sonrası sayı.

## Rapor

`docs/uat/2026-08-05-ci-item-repair/` altına ekle:
1. dry-run çıktısı (üç kritik satır dahil)
2. `verify()` çıktısının tamamı — mismatched varsa her satırı
3. `key_ledger()` çıktısı — 205 anahtarın durumu, orphan / over-shipped listesi
3b. Çoklu PI kanıtı — `MH/1244/2025-26` (5 PI) ve `MH/1310/2025-26` (aynı kategori, iki PI)
    ekran görüntüleri
4. açılan PI'lar ve Item'lar (varsa), kim açtı, hangi değerlerle
5. yedek dosya yolları
6. kapsam dışı bırakılanlar: 36 fatura (Слуцкий + Belarus/Ukrayna), 81 masraf satırı
   (`docs/data/msa_ci_service_lines.csv`, 1 212 204 $ — `Import Expense` işi olarak ayrı açılacak)

## Durma koşulları
`failed` > 0 · `verify` mismatched > 0 · `key_ledger` içinde `CI lines with no PI reference` > 0
→ geri al (`restore()` + JSON yedeği), dur, raporla.
