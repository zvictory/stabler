# DEVİR — MSA doğrudan fatura ekranı

Yazan: `msa` oturumu, 2026-08-18. Cross-session mesaj karşı tarafın onayında
süresi dolduğu için devir bu dosyaya bırakıldı.

## Nerede

- Worktree: `/Users/zafar/frappe-bench-local/apps/stabler/.worktrees/si-boxes`
- Dal: `fix/si-custom-boxes` — ağaç temiz, **main'e merge EDİLMEDİ**
  (kullanıcı "şimdilik dalda bırak" dedi; ayrıca `main`'de başka bir oturumun
  commit'siz dosyaları vardı).

| Commit | Ne |
|---|---|
| `0e8a4b1` | koli regresyonu: `create_direct_sales_invoice` satır sözlüğü `custom_boxes`/`custom_box_kg` yazmıyordu, `sales_invoice_detail` geri okumuyordu |
| `fac1b24` | `_direct_invoice_item_rows` — create ve update aynı satır kurucusundan geçsin diye |
| `5cd750b` | `SalesInvoiceFormModern.vue` (yeni, 571) + `NewDirectInvoicePage.vue` silindi (491) + router + viewer'a Düzenle düğmesi + 11 test |

Prod ölçümü (2026-08-18): `Sales Invoice Item`'da koli taşıyan SON satır
**2026-07-28**. Üç hafta sessiz kayıp.

## Neden böyle — dokunmadan önce oku

- **MSA sipariş kullanmıyor.** Satış Siparişi **0**, Satış Faturası **4937**.
  `enable_modern_sales_order` işlemsizdir; o bayrak yalnız `router.js`'teki
  `orders/new` + `orders/:name` rotalarını etkiler. İstenen, Modern *deneyimin*
  fatura yazarken olmasıydı.
- **`LineItemsEditor.vue`'ya koli öğretme.** Sütunları Item/Qty/UOM/Rate/Amount —
  koli yok. Onu satır ızgarası yapmak koliyi yeniden düşürürdü; ona koli
  öğretmek altı kiracının SO ekranına dokunmak olurdu. Izgara faturaya özel
  kaldı. Bir test bu sınırı kilitliyor: `LineItemsEditor` `boxes`/`box_kg`/
  `custom_boxes` öğrenirse **kırmızı** olur. **Bu testi gevşetme.**
- **Kapı: `canAccessModule("direct_invoicing")` KULLANILAMAZ.**
  `direct_invoicing`, `organization.py`'deki `_MODULE_ROLES`'ta **yok** ve o
  harita "haritada olmayan anahtar admin-only" diyor → MSA'nın admin olmayan
  kasiyerleri kilitlenirdi. Uygulanan: `session.modules.direct_invoicing`
  (backend'in `module_map_for(company).get("direct_invoicing")` kontrolüyle
  birebir) **+** rol katmanı `imports` üzerinden. Eski ekran `imports`'a
  bakıyordu, backend `direct_invoicing`'e — o uyuşmazlık da kapandı.
- **Taslak kaydet ile gönder ayrı düğme.** Gönderilen fatura GL + SLE + e-fatura
  yazar; tek düğme geri alınamaz postingi ekrandaki en kolay şey yapardı.

Tam karar zemini: `docs/plans/`'ta değil — `~/.claude/plans/https-msa-erpstable-com-stabler-sales-in-joyful-sketch.md`,
sonundaki "Uygulama sonrası düzeltmeler" bölümü dahil.

## Doğrulama durumu

- `make check` **yeşil** (3883 Python + 265 JS), commit başına.
- **9 mutasyonun 9'u** tam bir testi kırmızıya çekti: doctype→SO, update ucu,
  `boxes`, `box_kg`, kapı bayrağı, `saveDraft`, `confirm`, rota, ve
  `LineItemsEditor`'a koli sızdırma. Testler yük taşıyor.

## Kapanmamış borçlar

1. **`make test-bench` KOŞULAMADI.** Bench uygulamayı `main` ağacından yüklüyor,
   orada `update_sales_invoice` yok (`grep -c` = 0). O uç **DB'ye yazar**;
   `make check` onun için yeterli kanıt **değil**. Merge sonrası koşulmalı.
   İlgili modüller: `test_customer_hierarchy_integration`,
   `test_related_documents_integration`, `test_vehicle_finance_accounting`,
   `test_vehicle_finance_read`.
2. **Tarayıcıda smoke yapılmadı.** Deploy runbook'unun regresyon sınıfı:
   `…/stabler#/sales/invoices/<mevcut SINV>` doğrudan URL ile **dolu** açılmalı,
   boş "New" formu değil.
3. **22 kullanıcı dizesi beş dilin hiçbirinde yok** (AMOUNT, BOXES, BOX KG,
   Save Draft, Save & Submit, New Direct Sales Invoice, …). **Devralınan** açık:
   hepsi silinen sayfadan taşındı ve orada da çevrilmemişti. Bu işte yeni anahtar
   eklenmedi. Bilerek kapsam dışı bırakıldı.

## Kullanıcının kararına bırakılanlar — kendiliğinden yapma

- **Giriş zinciri.** MSA'nın stok/muhasebe zemini yok: canlı `Stock Ledger Entry`
  **2** (ikisi de 2026-08-18'in faturaları), Delivery Note 0, Stock Entry 0,
  Landed Cost Voucher 0, `update_stock=1` Alış Faturası 0. `Bin` toplam
  **−440 kg**, stok değeri **−24 068 000 UZS**. `create_direct_sales_invoice`
  `sales.py`'de `update_stock = 1`'i **hardcode** ediyor. Giriş zinciri
  (PR → LCV → PI) kurulmadan yayılırsa COGS sıfır maliyetle yazılır ve giriş
  belgesi geldiğinde `repost_item_valuation` geriye dönük tüm SLE/GLE'yi yeniden
  yazar.
- **`ACC-SINV-2026-31303`** — müşterisi "Test CO", canlı GL'e 13 128 000 COGS ve
  −240 kg yazdı. İptal edilsin mi?
- **Merge.**

## Geçici veri düzeltmeleri (kalıcı çözüm değil)

msa'da 26 kalemde batch kapatıldı; bir kaleme `valuation_rate` 54 700 UZS/kg girildi.

## Kurallar

Prod deploy her zaman Zafar'ın **açık** onayını ister — asla çıkarım yapma.
`git add -A` yok, explicit path. Trailer: `Co-Authored-By: Claude <noreply@anthropic.com>`.
Kiracı adına dallanma yok. `make check` commit başına yeşil.
