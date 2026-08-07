# PROMPT — CI formu yeniden düzeni + maliyet/transport/fatura bloğu

> Onaylanmış tasarım: `docs/uat/2026-08-05-ci-transport/ci_form_v4.html`.
> Backend + frontend + çeviri. Prod'a deploy bu görevin kapsamında **değil**.

---

## 0) Kapsam — 7 madde

1. `CiLogisticsOverview` **ikiye bölünür**: aksiyon butonları statü çubuğuna çıkar, checklist en alta iner.
2. `Связанные заказы на закупку` (PO links) kartı **kaldırılır** — ⚠ veri akışı korunur, bkz. §1.
3. Kalem tablosuna **fiyat doğrulama** ve **себест./кг** kolonları eklenir.
4. Kalemlerin altına **tek satırlık sözleşme özeti** (PI + kategori + bu sevkiyat + rozet + link).
5. Konteyner tablosuna **4 kolon**: avans %70, telex/BL, gate-in→ГТД süresi, себест./кг.
6. Yeni blok: **Транспорт, расходы и счета поставщиков** — giderler + bağlı Purchase Invoice'lar + faturasız kalanlar.
7. Yeni blok: **Себестоимость партии** — operasyonel ve muhasebe rakamı yan yana, aradaki fark açıkça.

Ek olarak §7'de ayrı bir düzeltme var (PI panelindeki `max(0, …)`).

**Alarm şeridi YOK.** Uyarılar ait oldukları satırda: demurrage konteyner satırında, ödenmemiş avans o satırda, fiyat sapması kalem satırında. Toplu uyarı görünümü `ImportsDashboard`'un işi, CI'da tekrarlanmaz.

---

## 1) ⚠ İlk okunacak: PO kartında veri kaybı tuzağı

`po_links` yalnızca görüntü değil, **kaydediliyor**:
`CommercialInvoiceForm.vue` ~815 `const poLinks = form.value.po_links.filter(...)` → ~822/832 payload.

Sadece **şablondaki kartı** (~1605-1625) sil. Şunlara dokunma:
`blankForm()` içindeki `po_links: []` (~135) · `fromDetail` içindeki `po_links` (~552) · payload (~815, 822, 832).
Aksi halde PO bağlantısı olan bir CI kaydedilince bağlantılar **sessizce silinir**.
Kart kalkınca `addPoLink` / `removePoLink` / `poOptions` boşta kalıyorsa onları sil, veri akışı kalsın.

---

## 2) Backend — tek yeni endpoint + bir imza genişletmesi

### 2.1 `_related_import_bills` konteyner **listesi** almalı

Bugün (imports.py:2895) tek `container` alıyor. CI seviyesinde faturayı bulmak için CI'ın **tüm** konteynerleri gerekiyor:

```python
def _related_import_bills(company, *, containers, ci, trucks, ref_cols, today_d):
```
`containers` bir liste; `pi.custom_import_container IN (...)`. `container_cost_ledger`'daki mevcut çağrı `containers=[container]` olarak güncellenir — davranışı değişmez. `_enrich_bill_rows` (kategori türetme, `overdue`, `due_date`) aynen kullanılır, yeniden yazılmaz.

### 2.2 `ci_cost_overview(commercial_invoice)` — bloklar 5 ve 6'nın tek kaynağı

```python
@frappe.whitelist()
def ci_cost_overview(commercial_invoice: str) -> dict:
```

**Yeni doctype, yeni alan, yeni Custom Field YOK.** Kaynaklar zaten var:

| Ne | Nereden |
|---|---|
| giderler | `Import Expense` (commercial_invoice / container / truck) |
| tedarikçi faturaları | `_related_import_bills(...)` → `custom_commercial_invoice`, `custom_import_container`, `custom_import_truck` |
| konteyner maliyet satırları | `Import Container.cost_lines` (`Container Cost Line`) |
| konteyner başı toplam ve `per_kg` | `rules.container_cost_summary(...)` + `rules.per_kg(...)` — **yeniden hesaplama, bunları çağır** |
| gümrük vergileri | `Customs Declaration.total_duties` (bu CI'ın beyannameleri) |
| muhasebeye giren | `_ci_landed_cost_vouchers(ci)` → GRN üzerinden LCV toplamı |

**İzin ve maskeleme — zorunlu:**
`_assert_imports_access(company)` + `_assert_can_read("Commercial Invoice", name)`, ve
`rules.mask_named(...)` üç maske ile: `EXPENSE_MASK_FIELDS` (bank/cash), `LANDED_BILL_MASK_FIELDS` (grand_total, outstanding), `CONTAINER_COST_LINE_MASK_FIELDS`. Görünürlük `_cost_visible()`.

**Kategori sabiti** (modül başına, tek satırda değişebilsin):
```python
#: The transport chain — what the block's headline total means. Customs and
#: documentation belong to the same shipment but not to moving it, so they are
#: returned separately instead of being folded in silently.
TRANSPORT_CATEGORIES = ("Transport", "Border Crossing", "Handling", "Storage", "Insurance")
```

**Konteynere dağıtım:** `expense.container` doluysa doğrudan (`allocation="direct"`); boşsa CI konteynerlerine **ağırlığa göre** (`allocation="weight"`), ağırlık yoksa eşit (`"equal"`); `truck` doluysa `"truck"`, hiçbiri yoksa `"invoice"`. Satır hangi yolla dağıtıldığını taşır.

**Mutabakat (blok 5'in alt satırı):**
`unbilled = Σ lojistik gider − Σ lojistik faturası`. Fatura kategorisi `derive_bill_category` ile geliyor; `product` kategorisi mutabakatın dışında (malın kendi faturası).

**Dönüş şekli:**
```python
{
 "expenses": [ {name, category, is_transport, supplier, supplier_name, invoice_reference,
                expense_date, purchase_invoice, container, truck, allocation,
                amount, currency, bank_payment, cash_payment, status} ],
 "bills":    [ {name, supplier, supplier_name, bill_no, category, grand_total,
                outstanding_amount, status, due_date, overdue,
                custom_commercial_invoice, custom_import_container, custom_import_truck} ],
 "unbilled": [ ...expense alt kümesi, purchase_invoice boş olanlar... ],
 "by_vendor":    [ {supplier, supplier_name, docs, amount, paid, outstanding} ],
 "by_container": [ {container, logistics_amount, per_kg, landed_per_kg} ],
 "operational": {"goods":0.0,"transport":0.0,"other":0.0,"duties":0.0,
                 "total":0.0,"per_kg":0.0,"duties_estimated":True},
 "accounting":  {"billed_goods":0.0,"lcv_total":0.0,"total":0.0,"per_kg":0.0},
 "gap": {"amount":0.0,"per_kg":0.0},
 "totals": {"transport":0.0,"billed":0.0,"unbilled":0.0,
            "paid":0.0,"outstanding":0.0,"containers":0,"cargo_kg":0.0},
 "currency":"USD",
}
```
- `duties_estimated=True` → ГТД henüz çıkmadıysa vergi beyan değerinden hesaplanır ve arayüzde **«расчёт»** rozetiyle gösterilir; çıkmışsa gerçek `total_duties`.
- `per_kg` her yerde `rules.per_kg` ile (sıfıra bölme koruması tek yerde).
- `outstanding` negatif olabilir → **kırpma yok**, olduğu gibi dön.

### 2.3 Fiyat doğrulama — yeni mantık yazma

Kalem satırındaki «против договора» rozeti **mevcut sapma motorundan** gelir: `get_ci_pi_discrepancies` (ve `_imports_rules`'daki `PRICE_TOLERANCE = 0.005`, "bir anahtar birden fazla sözleşme fiyatı taşıyabilir → herhangi biriyle eşleşme uygunluktur" kuralı). Bu CI'a scope'lanmış çağrı yoksa, var olan fonksiyona `commercial_invoice` filtresi ekle — **paralel bir fiyat karşılaştırması yazma.** İki motor olması bu projede zaten bir kez pahalıya mal oldu.

### 2.4 Testler
`stabler/tests/` altına saf fonksiyon testleri: dağıtım (direct / weight / equal / ağırlıksız), kategori ayrımı, `unbilled` mutabakatı, `gap` hesabı. Frappe'siz çalışsın — matematiği `imports_module` altında saf bir yardımcıya çıkar, endpoint onu çağırsın.

---

## 3) Frontend — `CommercialInvoiceForm.vue`

### 3.1 Yeni blok sırası
```
статус + действия  →  4 сводных плитки  →  1 шапка  →  2 товары  →  3 свод по договорам
→ 4 контейнеры  →  5 транспорт/расходы/счета  →  6 себестоимость  →  7 документы
→ 8 фуры  →  9 логистическая готовность (детали)
```

### 3.2 Статус çubuğu (готовность butonları buraya)
`CiLogisticsOverview`'daki `Создать/Открыть GRN`, `Продвинуть контейнеры`, `Обновить ожидаемые кол-ва` butonları statü çubuğuna taşınır; mevcut `advanceStatus` / `rollback` butonlarıyla aynı satırda. Butonların **mantığı taşınmaz** — aynı fonksiyonlar çağrılır, sadece konumları değişir. Sağ uçta ETD/ETA ve gecikme.

### 3.3 4 sводная плитка
`Товар · согласовано` (altında докум. + fark) · `Логистика и пошлины` · `Себестоимость / кг` (altında учёт rakamı ve разрыв) · `Не оплачено` (altında satıcı / nakliyeci kırılımı). Veri yoksa plitka gizlenir.

### 3.4 Товары — 2 yeni kolon
- **Против договора**: `= 4,35` yeşil / `≠ 3,45 · −1 400 $` sarı. Tooltip: anahtarın taşıdığı tüm sözleşme fiyatları.
- **Себест./кг**: satırın согл. fiyatı + o satıra düşen lojistik payı.
- Sapmalı satırın zemini hafif sarı. Kart başlığındaki rozet: `1 строка: цена ниже договорной`.

### 3.5 Свод по договорам (tablo değil)
Bu CI'ın dokunduğu her `(PI, kategori)` için **tek satır**: PI linki · kategori rozeti · «в этом инвойсе N кор.» · sağda tek rozet (`перегруз −200 кор.` kırmızı / `остаток 4 200 кор.` yeşil) · `открыть ПИ →`.
Miktar izlemenin detayı PI formunda kalır, burada **tekrarlanmaz**.

### 3.6 Контейнеры — 4 yeni kolon
`Аванс 70%` (`payment_70_status/amount/date`) · `Телекс / BL` (`bl_type`, `telex_release_date`) · `Gate-in → ГТД` (`gate_in_date` → `Customs Declaration.declaration_date`; beyanname yoksa geçen gün sayısı kırmızı) · `Себест./кг` (`by_container`).
Ödenmemiş avans veya gecikmiş beyanname olan satırın zemini uyarı rengi.

### 3.7 Blok 5 — Транспорт, расходы и счета поставщиков
Üç tablo, mockup'taki sırayla:
1. **Счета поставщиков** — Счёт (PINV linki + `bill_no`) · Поставщик · Тип rozeti (товар/фрахт/транспорт/расход) · Привязан к (инвойс / konteyner linki / фура) · Сумма · Остаток · Срок (`overdue` ise `просрочен N дн.` kırmızı).
2. **Расходы, по которым счёта ещё нет** — `purchase_invoice` boş olan `Import Expense` satırları.
3. **Сверка satırı**: `расходы X − счета на логистику Y = Z без счёта`.
Alt şerit: `+ Добавить расход` · `Привязать счёт` · `Неразнесённые затраты →`.

### 3.8 Blok 6 — Себестоимость партии
İki sütun: solda **операционно** (товар / фрахт+транспорт / порт+страховка / пошлины `расчёт` rozetiyle), sağda **в учёте** (проведённый инвойс + LCV). Altta kesikli çerçeveli kutu: `Разрыв X $ · Y $/кг ещё не разнесён на запасы` + `Неразнесённые затраты →` linki.

### 3.9 Blok 7 — Документы полосасы
5 küçük kutu: Упаковочный · Вет-сертификат (bitiş tarihiyle; süresi dolmuşsa kırmızı) · ГТД · GRN · LCV. Veriler mevcut doctype'lardan; yeni alan yok.

### 3.10 UI kuralları (CLAUDE.md)
- Yükleme sırasında `SkeletonRows.vue`; boşlukta spinner yok.
- Boş durumlar sessiz kaybolmaz: gider yoksa blok 5 yine görünür, tek satır boş durum + `+ Добавить расход`.
- Para `formatMoney`/`fm()`; hücrede para birimi rozeti tekrarlanmaz, başlıkta yazar.
- Maskelenmiş alan (`null`) → `•••`, `0` yazma.
- Tüm metinler `t()` ile ve **5 çeviri dosyasında**: `en, ru, tr, uz, uzc`. Rusça karşılıklar mockup'taki gibi.
- Yeni sayfa yok; linkler: konteyner `/imports/containers/<name>`, gider `/imports/expenses`, fatura `/purchasing/invoices/<name>`, PI `/imports/proformas/<name>`.

---

## 4) Ayrı düzeltme — PI panelinde gizlenen aşırı sevkiyat

`get_pi_invoiced_summary` (imports.py:4796-4797):
```python
rem_b = max(0, pi_b - inv_b)
rem_q = max(0.0, flt(pi_q - inv_q, 2))
```
`max(0, …)` negatif bakiyeyi gizliyor; `_imports_rules` bunu açıkça yasaklıyor
(*"max(0,…) is forbidden here: it hid 21 over-shipped keys / 25 959 boxes in the real book"*).
**Anahtarı değiştirme** — izleme kategori+item olarak kalıyor. Sadece kırpmayı kaldır ve PI formunda negatif kalan kırmızı gösterilsin. İki satır + bir stil.

---

## 5) Doğrulama

1. `bench build --app stabler` temiz; `bench run-tests --app stabler` yeşil (yeni testler dahil).
2. Canlı msa'da gözle:
   - Blok sırası doğru; готовность butonları üstte, checklist altta.
   - **PO testi (atlanamaz):** PO bağlantısı olan bir CI'ı aç → kaydet → tekrar aç → bağlantılar duruyor mu.
   - Gideri ve faturası olan bir CI: nakliyeci, kendi invoisi, PINV linki, konteyner dağılımı, `сверка` satırı doğru mu.
   - Konteynere kesilmiş bir fatura (`custom_import_container`) CI blok 5'te görünüyor mu.
   - Gideri olmayan bir CI: boş durumlar düzgün, `NaN` / sonsuz spinner yok.
   - Fiyatı sözleşmeden farklı bir satır: sarı rozet ve fark tutarı doğru mu.
   - Maliyet yetkisi olmayan kullanıcı: banka/nakit ve fatura tutarları maskeli mi.
   - Aşırı sevkiyatlı bir PI: negatif kalan artık görünüyor mu (§4).
3. Ekran görüntüleri `docs/uat/2026-08-05-ci-transport/screenshots/`.

## 6) Kurallar
- Prod'a deploy yok. Ham SQL ile veri yazma yok. Yeni doctype/alan yok.
- Mevcut `list_import_expenses`, `container_cost_ledger`, `get_ci_pi_discrepancies` davranışları değişmez — yalnızca çağrılır.
- Aynı işi yapan ikinci bir hesap yazma; var olanı genişlet.
