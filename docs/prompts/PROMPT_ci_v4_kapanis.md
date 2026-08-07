# PROMPT — CI v4: iki kapanış maddesi

> Kısa görev. Yeni özellik yok, iki açık madde kapatılacak.
> Bu turda düzeltilen iki blocker (`_related_import_bills` imzası, `Customs Declaration.released`)
> zaten yamandı — onlara dokunma, sadece doğrula.

## A · `ci_cost_overview` gerçekten çalıştırılacak

Endpoint bugüne kadar bir kez bile çağrılmadı; iki blocker da bu yüzden kaçtı.
Saf fonksiyon testi (`test_ci_cost_overview.py`) bunu yakalayamaz, yakalayamayacak da.

1. **Canlı smoke** — üç farklı CI ile, çıktıyı olduğu gibi rapora yapıştır:
```bash
bench --site msa.erpstable.com execute stabler.api.imports.ci_cost_overview \
  --kwargs '{"commercial_invoice":"<CI>"}'
```
   - (a) gideri **ve** faturası olan bir CI
   - (b) konteynerine fatura kesilmiş bir CI (`Purchase Invoice.custom_import_container` dolu) —
     `_related_import_bills`'in liste kabul etmesinin tek sebebi buydu, kanıtı da bu
   - (c) hiç gideri olmayan bir CI — boş liste dönmeli, hata değil

   Kontrol: `expenses`, `bills`, `unbilled`, `by_vendor`, `by_container`,
   `operational`, `accounting`, `gap`, `totals` anahtarları geliyor mu;
   `unbilled` mutabakatı (`расходы − счета`) tutuyor mu; `duties_estimated`
   ГТД'si çıkmış CI'da `False`, çıkmamışta `True` mu.

2. **Regresyon:** `container_cost_ledger` da aynı fonksiyonu çağırıyor, imzası değişti:
```bash
bench --site msa.erpstable.com execute stabler.api.imports.container_cost_ledger \
  --kwargs '{"container":"<konteyner>"}'
```
   `bills` listesi eskisi gibi dolu gelmeli.

3. **Maskeleme:** maliyet yetkisi olmayan bir kullanıcıyla (b)'yi tekrarla —
   `amount`, `bank_payment`, `cash_payment`, `grand_total`, `outstanding_amount`
   `null` gelmeli, `0` değil. Arayüzde `•••` görünmeli.

4. Bu üç çağrıyı kalıcılaştır: `docs/uat/scripts/` altına bir smoke script
   (mevcut `verify_ci_transport_ui.js` kalıbında) ya da Frappe test'i.

## B · Fiyat karşılaştırması sunucuya taşınacak

`CommercialInvoiceForm.vue:196-200` ve `:246`'da ikinci bir uygulama var:
```js
const PRICE_TOLERANCE = 0.005;
const priceEq = (a, b) => round4(Math.abs(round4(a) - round4(b))) <= PRICE_TOLERANCE;
... code: "price_agreed"
```
Aynı kural sunucuda zaten var: `_imports_rules.PRICE_TOLERANCE`, `DIFF_LABELS`,
ve **`get_ci_pi_discrepancies(company, ci=...)`** — CI filtresi mevcut (imports.py:5225).
Bu fonksiyon `(проформа, категория)` anahtarıyla karşılaştırıyor, `error`/`warn`
satırlarını döndürüyor, `sub_cut` gibi `info` satırlarını dışarıda tutuyor.

Yapılacak:
1. `PRICE_TOLERANCE`, `priceEq` ve elle üretilen `price_agreed` kodunu Vue'dan **sil**.
2. Form yüklenirken `get_ci_pi_discrepancies(company, ci=form.name)` çağır
   (`ci_cost_overview` ile aynı anda, `Promise.all`).
3. «Против договора» rozetini dönen satırlardan bas: `price_agreed` / `price_docs`
   kodu olan satır → sarı rozet + fark tutarı; hiç satır yoksa → yeşil `= <fiyat>`.
   Rozet metni `DIFF_LABELS`'daki koda göre `t()` ile çevrilsin (kodlar zaten 5 CSV'de).
4. Tooltip'te anahtarın taşıdığı sözleşme fiyatları — sunucudan geliyorsa onu kullan,
   gelmiyorsa tooltip'i çıkar; **istemcide yeniden hesaplama**.

Gerekçe: bu projede aynı soruya iki motorun iki cevap vermesi
(`get_pi_invoiced_summary` vs `_imports_rules`) bugün bir gün kaybettirdi.
Tolerans sabiti ve "bir anahtar birden fazla sözleşme fiyatı taşıyabilir" kuralı
tek yerde kalmalı.

## Bitiş kriteri
- Üç smoke çağrısının çıktısı raporda, üçü de hatasız.
- `container_cost_ledger` regresyonu temiz.
- Maskeli kullanıcıda finansal alanlar `null`.
- Vue'da `PRICE_TOLERANCE` / `priceEq` araması **0 sonuç**.
- `bench build --app stabler` yeşil (bundle tarihi kaynakla aynı).
- `bench run-tests --app stabler` ve `npm run test:js` yeşil.

## Kurallar
Prod'a deploy yok · yeni doctype/alan yok · ham SQL ile yazma yok ·
`ci_cost_overview` ve `_imports_rules.calculate_ci_cost_overview` mantığını değiştirme,
sadece çağır ve doğrula.
