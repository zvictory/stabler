# PROMPT — CI v4: mutabakat ve muhasebe rakamı düzeltmesi

> Kısa görev. Smoke çıktıları iki defekt gösterdi; ikisi de `_imports_rules.calculate_ci_cost_overview`
> içinde, birkaç satır. Sonra doğrulama tekrarlanacak.

## Neden — kendi çıktın

| senaryo | transport | billed | unbilled | faturanın kategorisi |
|---|---|---|---|---|
| CI-2026-00983 | 1 500 | **0** | **0** | `product` (ACC-PINV-2026-00878) |
| CI-2026-00980 | 850 | **0** | **0** | `product` (ACC-PINV-2026-00879) |

İki senaryoda da giderin bir faturası **var** (`purchase_invoice` dolu) ama `billed = 0`.
Сверка satırı `1500 − 0 = 0` yazıyor.

## 1 · `billed_total` gider→fatura bağından kurulacak

`_imports_rules.py:1728`:
```python
non_product_bills = [b for b in bills if b.get("category") != "product"]
billed_total = round(sum(float(b.get("grand_total") or 0.0) for b in non_product_bills), 2)
```
`derive_bill_category` bir faturayı transport sayması için fura referansı, `Cross-Border Transport` /
`Import Service` kalem kodu ya da `XBORDER-`/`IMPEXP-`/`FREIGHT-` ön eki arıyor. CI'a veya konteynere
bağlanmış, düz numaralı bir nakliye faturası bunların hiçbirine uymuyor → `product` düşüyor.

**Kategoriyi tahmin etme.** `Import Expense.category` zaten "Transport" diyor; bağ da elimizde:
```
billed_total = Σ grand_total  (sayılan lojistik giderlerin `purchase_invoice`'ları, tekilleştirilmiş)
             + Σ grand_total  (hiçbir gidere bağlı olmayan, kategorisi `product` DIŞINDA olan faturalar)
```
İkinci terim, sisteme gider kaydı açılmadan doğrudan girilmiş nakliye faturalarını kaçırmamak için.
Aynı fatura iki terime birden girmesin — `name` üzerinden tekilleştir.

**Kapanması gereken kimlik:**
```
totals.transport  ==  totals.billed + totals.unbilled        (± 0.01)
```
Bunu `calculate_ci_cost_overview`'un testine **assert** olarak ekle. Kapanmıyorsa fark
`totals["reconciliation_diff"]` olarak dönsün — sessizce yutulmasın.

## 2 · `accounting.billed_goods` beyan tutarı değil, kesilmiş fatura olacak

`_imports_rules.py:1710`:
```python
acc_goods = round(float(items_docs_total or 0.0), 2)
```
Bu CI'ın **beyan (docs) tutarı** — muhasebeye giren rakam değil. Blok 6'nın sağ sütunu bu yüzden
yanlış şeyi ölçüyor ve `gap` iki ayrı kavramı (nakit/beyan farkı + LCV eksikliği) tek rakama karıştırıyor.
Dev fixture'ında 0 olduğu için görünmedi; prod'da beyan tutarını yazıp "в учёте" diyecek.

**Yeni tanım:**
```python
acc_goods = Σ grand_total  (kategorisi `product` olan faturalar)     # gerçekten kesilmiş mal faturası
acc_total = acc_goods + lcv_total
gap       = operational.total − acc_total
```
`items_docs_total` bu sütundan tamamen çıksın. Fonksiyon imzasında kalabilir (başka yerde
kullanılıyorsa), ama `accounting`'i beslemesin.

## 3 · Şirket uyumsuzluğu — prod'da var mı (salt-okunur)

(b) senaryosu ancak fixture'daki `company` alanları `UPDATE` edildikten sonra geçti. Endpoint
faturaları `pi.company = %(company)s` ile filtreliyor; prod'da uyumsuzluk varsa fatura **sessizce
kaybolur**. Tek sorguyla ölç, sonucu rapora yaz:
```bash
bench --site msa.erpstable.com execute frappe.db.sql --args '["
SELECT COUNT(*) FROM `tabPurchase Invoice` pi
JOIN `tabCommercial Invoice` ci ON ci.name = pi.custom_commercial_invoice
WHERE COALESCE(pi.custom_commercial_invoice,\"\") != \"\" AND pi.company != ci.company", [], 1]'
```
Sıfır değilse kaç kayıt ve hangileri — düzeltme ayrı iş olarak açılır, bu turda dokunma.

## 4 · Doğrulamayı tekrarla — bu sefer ağırlıklı bir CI ile

Üç fixture'ın da `cargo_kg` değeri 0'dı, dolayısıyla `per_kg`, `landed_per_kg` ve `gap.per_kg`
hiç sıfırdan farklı üretilmedi. Tasarımın manşet rakamı hâlâ doğrulanmamış durumda.

`total_kg` dolu, gideri ve faturası olan bir CI seç (yoksa dev sitesinde bir tane kur) ve smoke'u
tekrar çalıştır. Çıktıda şunları göster:
- `totals.transport`, `totals.billed`, `totals.unbilled` ve **kimliğin kapandığı**
- `operational.per_kg`, `accounting.per_kg`, `gap.per_kg` — üçü de sıfırdan farklı
- `by_container[*].per_kg` ve `landed_per_kg` — konteyner başına dağılım
- `accounting.billed_goods` artık `product` faturadan geliyor (beyan tutarına eşit **değil**)

Diğer iki senaryo (konteyner bağlantılı fatura, gidersiz CI) da tekrar koşsun — regresyon.

## Bitiş kriteri
- `transport == billed + unbilled` üç senaryoda da kapanıyor, testte assert var.
- `accounting.billed_goods` beyan tutarından bağımsız.
- Ağırlıklı CI'da üç `per_kg` da sıfırdan farklı.
- Şirket uyumsuzluğu sayısı raporda.
- `bench build --app stabler`, `bench run-tests --app stabler`, `npm run test:js` yeşil.

## Kurallar
Prod'a deploy yok · prod'da veri yazma yok (3. madde salt-okunur) · yeni doctype/alan yok ·
dev fixture'ını değiştirirsen **raporda yaz**, sessizce düzeltme.
