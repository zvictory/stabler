# PROMPT — CI formu: bölüm sırası + transport giderleri bloğu

> Uygulama görevi. Onaylanmış tasarım: `ci_form_mockup.html`.
> Tek dosya değil, backend + frontend + çeviri. Sonunda canlı doğrulama.

---

## 0) Ne yapılacak — üç madde

1. **`Логистическая готовность` (CiLogisticsOverview) en alta insin.** Şu an durum çubuğunun
   hemen altında, şapkadan önce açılıyor. Yeni sıra:
   şapka → товары → контейнеры → **транспортные расходы** → фуры → **логистическая готовность**.
2. **`Связанные заказы на закупку` (PO links) kartı kaldırılsın.**
3. **Yeni kart: `Транспортные расходы`** — konteyner listesinin altında; hangi nakliyeci,
   nakliyecinin kendi invoisi, sistemdeki gider/fatura belgesi, konteyner kırılımı ve toplam.

---

## 1) ⚠️ PO kartında veri kaybı tuzağı — önce bunu oku

`po_links` yalnızca görüntü değil, **kaydediliyor**: `CommercialInvoiceForm.vue` satır ~815
`const poLinks = form.value.po_links.filter(...)` → satır ~822/832 payload'a giriyor.

Sadece **şablondaki kartı** (satır ~1605-1625) sil. Şunlara **dokunma**:
- `blankForm()` içindeki `po_links: []` (satır ~135)
- `fromDetail` içindeki `po_links: (d.po_links || []).map(...)` (satır ~552)
- kaydetme payload'ındaki `po_links` (satır ~815, 822, 832)

Aksi halde mevcut PO bağlantıları olan bir CI kaydedildiğinde **bağlantılar sessizce silinir**.
Kart kalktıktan sonra `addPoLink` / `removePoLink` / `poOptions` kullanılmıyorsa onları da sil
(lint temiz kalsın), ama veri akışı aynen kalsın.

---

## 2) Backend — yeni endpoint

`stabler/api/imports.py` içine, `list_import_expenses`'in yanına:

```python
@frappe.whitelist()
def ci_transport_costs(commercial_invoice: str) -> dict:
```

**Kurallar:**
- Yeni doctype, yeni alan, yeni Custom Field **yok**. Veri zaten `Import Expense`'te:
  `commercial_invoice, container, truck, category, expense_date, supplier, invoice_reference,
  description, amount, currency, bank_payment, cash_payment, status, purchase_invoice`.
- İzin: `_assert_imports_access(company)` + `_assert_can_read("Commercial Invoice", name)`.
- **Maskeleme zorunlu:** dönen satırlara `rules.mask_named(rows, rules.EXPENSE_MASK_FIELDS, _cost_visible())`
  uygula — `bank_payment` / `cash_payment` maliyet yetkisi olmayan kullanıcıya gösterilmez
  (`list_import_expenses` ile birebir aynı davranış).
- `supplier_name` için `tabSupplier`'dan join et; ham `name` gösterme.

**Kategori ayrımı** — modülün başına sabit olarak koy, tek satırda değişebilsin:
```python
#: The transport chain — what the card's headline total means. Customs and
#: documentation are costs of the same shipment but not of moving it, so they
#: are returned separately instead of being hidden or silently added in.
TRANSPORT_CATEGORIES = ("Transport", "Border Crossing", "Handling", "Storage", "Insurance")
```
`Customs`, `Documentation`, `Other` → `other_rows` + `other_total` olarak ayrı dönsün.

**Konteynere dağıtım** (mockup'taki iki durum):
- `expense.container` doluysa → doğrudan o konteynere, `allocation: "direct"`.
- Boşsa → CI'ın konteynerlerine **ağırlığa göre** (`total_kg`) dağıt, `allocation: "weight"`.
  Konteynerlerde ağırlık yoksa eşit böl, `allocation: "equal"`.
- `truck` doluysa satırda göster ama konteynere dağıtma; `allocation: "truck"`.
- Hiçbiri yoksa → `allocation: "invoice"` (tüm faturaya ait, ör. sigorta).

**Dönüş:**
```python
{
  "rows": [ {name, category, is_transport, supplier, supplier_name, invoice_reference,
             expense_date, purchase_invoice, container, truck, allocation,
             amount, currency, bank_payment, cash_payment, status} ],
  "by_vendor":    [ {supplier, supplier_name, docs, amount, paid, outstanding} ],
  "by_container": [ {container, amount} ],
  "other_rows": [...], "other_total": 0.0,
  "totals": {"transport": 0.0, "paid": 0.0, "outstanding": 0.0,
             "per_container": 0.0, "per_kg": 0.0,
             "containers": 0, "cargo_kg": 0.0, "goods_per_kg": 0.0, "landed_per_kg": 0.0},
  "currency": "USD",
}
```
- `paid` = `bank_payment + cash_payment`; `outstanding` = `amount - paid` (negatif olabilir → aynen dön, kırpma).
- `cargo_kg` = CI'ın `total_kg`'si; 0 ise `per_kg` = 0 (sıfıra bölme yok).
- `goods_per_kg` = `agreed_total / total_kg`, `landed_per_kg` = `goods_per_kg + per_kg`.

**Test:** `stabler/tests/` altına saf fonksiyon testi ekle — dağıtım matematiği
(direct / weight / equal / eksik ağırlık) ve kategori ayrımı. Frappe'siz çalışsın:
dağıtımı `imports_module` altında saf bir yardımcıya çıkar, endpoint onu çağırsın.

---

## 3) Frontend — `CommercialInvoiceForm.vue`

### 3.1 Sıra
- `<CiLogisticsOverview .../>` bloğunu (satır ~1218) **`Связанные фуры` kartından sonraya** taşı.
- PO kartını sil (bkz. bölüm 1).

### 3.2 Üst ölçü şeridine 4. kutu
`Транспортные расходы` — büyük rakam toplam, altında küçük satır:
`{per_container} / контейнер · {per_kg} / кг`. Veri yoksa kutu gösterilmesin.

### 3.3 Konteyner tablosuna yeni kolon
`Транспорт по контейнеру` — `by_container`'dan. Alt toplam satırına da yaz.

### 3.4 Yeni kart — `Транспортные расходы`
Konum: `Связанные контейнеры` kartından hemen sonra. İçerik sırası mockup'taki gibi:

1. **Not satırı** (alert değil, küçük açıklama): gider başka tedarikçiye ait, burada sadece
   bağlantı var; konteynere bağlıysa doğrudan, değilse ağırlığa göre dağıtılıyor.
2. **3 kutu:** Всего транспорт · На контейнер · На кг (altında ödeme ilerleme çubuğu +
   "оплачено X% · Y к оплате").
3. **`По перевозчикам` mini tablosu:** Поставщик услуги · Док. · Сумма · Оплачено · К оплате.
   Alt toplam satırı. `outstanding > 0` kırmızı.
4. **`Документы расходов` tablosu:** Категория · Перевозчик / инвойс перевозчика ·
   Документ в системе · Контейнер · Сумма · Оплата · Статус · →
   - "Перевозчик / инвойс": üstte `supplier_name` (link), altında küçük `invoice_reference` + tarih.
   - "Документ в системе": `purchase_invoice` varsa link (`/purchasing/invoices/<name>`),
     yoksa `не проведён`; altında küçük `Import Expense` adı.
   - "Контейнер": `direct` → konteyner linki + «прямая привязка»; `weight` → «N конт.» + «по весу»;
     `invoice` → «—» + «на весь инвойс»; `truck` → fura numarası.
   - Satır tıklanınca `/imports/expenses` sayfasına git (mevcut rota, satır 231).
5. **Alt şerit:** `+ Добавить расход` · `Открыть все расходы по этому инвойсу →` ·
   sağda `Себестоимость с транспортом: {landed_per_kg} $/кг ({goods_per_kg} + {per_kg})`.
6. **`Прочие расходы`** (Customs / Documentation / Other) varsa aynı kartın altında ayrı
   küçük bir tablo + kendi alt toplamı. Headline toplama **dahil değil**.

### 3.5 Zorunlu UI kuralları (CLAUDE.md)
- Yükleme sırasında `SkeletonRows.vue` — boşlukta spinner yok.
- Gider yoksa: kart yine görünür, içinde tek satırlık boş durum
  («Транспортных расходов пока нет» + `+ Добавить расход`). Sessizce kaybolmasın.
- Para: `formatMoney` / mevcut `fm()` helper'ı. Hücrede para birimi rozeti tekrarlanmaz,
  başlıkta yazar.
- `bank_payment` / `cash_payment` maskeliyse (`null` geldiyse) o hücrede `•••` göster,
  0 yazma.
- Tüm metinler `t()` ile ve **5 çeviri dosyasına** eklenmiş: `en, ru, tr, uz, uzc`.
  Rusça karşılıklar mockup'taki gibi.

---

## 4) Doğrulama

1. `bench build --app stabler` temiz derleniyor.
2. `bench run-tests --app stabler` — yeni dağıtım testleri dahil yeşil.
3. **Canlı (msa) CI'da gözle:**
   - Bölüm sırası: шапка → товары → контейнеры → транспорт → фуры → логистическая готовность.
   - PO kartı yok; **PO bağlantısı olan bir CI'ı aç, kaydet, tekrar aç — bağlantılar duruyor mu.**
     (Bölüm 1'deki tuzağın testi. Bu adım atlanamaz.)
   - Gideri olan bir CI: nakliyeci, invoisi, PINV linki, konteyner dağılımı, toplamlar doğru mu.
   - Gideri olmayan bir CI: boş durum düzgün mü, `NaN` / sonsuz spinner yok.
   - Maliyet yetkisi olmayan bir kullanıcıyla: banka/nakit kolonları maskeli mi.
4. Ekran görüntüleri `docs/uat/2026-08-05-ci-transport/screenshots/` altına.

## 5) Kurallar
- Prod'a deploy **yok** — sadece kod + yerel test. Deploy ayrı adım.
- Ham SQL ile veri yazma yok. Yeni doctype/alan yok.
- Mevcut `list_import_expenses` davranışını değiştirme; yeni endpoint ondan bağımsız.
