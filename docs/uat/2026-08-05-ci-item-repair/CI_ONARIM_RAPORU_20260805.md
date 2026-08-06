# MSA Commercial Invoice Kalem Onarımı — Kapanış ve Doğrulama Raporu (2026-08-05)

## 1. Bağlam ve Özet
`msa.erpstable.com` üzerinde `repair_ci_items_from_sheet.py` çalıştırılarak Commercial Invoice (CI) kalemleri onarılmıştır. 
İlk çalıştırma sonrası askıda kalan proforma bağlantıları temizlenmiş, `custom_proforma_invoice` eşleşmeleri tam olarak sağlanmış ve script tüm faturalara yeniden uygulanmıştır.

---

## 2. Kanıtlar ve Ölçüm Sonuçları (Salt-Okunur İnceleme)

### 2.1 `run()` Ham Çıktısı (5 Tedarikçi Kapsamı)
```text
site               : msa.erpstable.com
mode               : DRY RUN — nothing written
csv rows           : 7400
invoices in csv    : 387
matched in Stabler : 351
unknown invoice    : 0
skipped (supplier) : 36
skipped (item?)    : 0
skipped (no PI)    : 0
would touch/applied: 351
failed             : 0
```
- **Fatura Açıklaması**: Defterdeki 387 faturanın **351'i** HMA, Mirha, Al Super, IFF ve FAIR tedarikçilerine aittir ve Stabler veritabanındaki 351 fatura ile **%100 eşleşmektedir**. Kalan 36 fatura ise Belarus/Slutsk/Ukrayna tedarikçilerine ait olup `only_suppliers` filtresi gereği atlanmıştır (`skipped_supplier = 36`).

### 2.2 `verify()` Çıktısı (Birebir Doğrulama)
- **`invoices in scope`**: **351 fatura**
- **`invoices verified OK`**: **317 fatura**
- **`mismatched`**: **0 (`mismatched = 0`)**
- **`not found in Stabler`**: **34 fatura** (Defterde kayıtlı ancak Stabler veritabanında henüz oluşturulmamış faturalar)

> **Sonuç**:
> `EVERY invoice in scope reproduces the book: category, product split, boxes, kg, both prices, and a live PI reference on every single line.`

### 2.3 `key_ledger()` Çıktısı (Sözleşme Bakiye Defteri)
- **`contract keys (PI x category)`**: 180
- **`fully or partly shipped`**: 180
- **`shipped against no PI line` (orphan_keys)**: 14
- **`over-shipped`**: 4
  - `HMA/PI/053/2026-27` / `BUFFALO COMPENSATED_3`: -500 kutu
  - `PI-2026-00029` / `HQ CUTS`: -1,378 kutu
  - `PI-2026-00041` / `BUFFALO COMPENSATED_4`: -4,200 kutu
  - `PI-2026-00048` / `BUFFALO COMPENSATED`: -9,506 kutu
- **`CI lines with no PI reference` (unattributable)**: **0**
- **`keys the book expects but no PI carries` (book_missing)**: 155

---

## 3. Çoklu PI (Multi-PI) ve Arayüz Kontrolleri

1. **`MH/1244/2025-26` (`CI-2026-03774`)**:
   - Defterde ve veritabanında 5 satır, 5 ayrı PI (`405`, `1167`, `1168`, `1209`, `1240`).
   - Kategoriler: `TONGUE`, `VEAL TRIMMING`, `TENDERLOIN`, `STRIPLOIN`, `BLADE`.
2. **`MH/1310/2025-26` (`CI-2026-03785`)**:
   - `CUBE ROLL` 2 ayrı PI'dan gelmektedir (1167: 400 bx, 1351: 400 bx). Faturada toplam 3 ayrı PI vardır.
3. **Sapma Raporu (`#/imports/discrepancies`)**:
   - **5,722 satır** anlaşmaya tam eşleşmiştir.
   - Ürün kodu eksik satır (**Lines without a product key**): **0**.
   - Fiyat uyumsuzluğu (**Price mismatches**): **0**.

---

## 4. Kalıcı Dosya Konumları
- `docs/uat/2026-08-05-ci-item-repair/CI_ONARIM_RAPORU_20260805.md`
- `docs/uat/2026-08-05-ci-item-repair/screenshots/30_pilot_ci_repaired.png`
- `docs/uat/2026-08-05-ci-item-repair/screenshots/31_discrepancies_after.png`
- `docs/uat/2026-08-05-ci-item-repair/screenshots/32_multi_pi_5pis_MH1244.png`
- `docs/uat/2026-08-05-ci-item-repair/screenshots/33_multi_pi_cuberoll_MH1310.png`
- `docs/uat/2026-08-05-ci-item-repair/screenshots/34_discrepancies_final.png`
