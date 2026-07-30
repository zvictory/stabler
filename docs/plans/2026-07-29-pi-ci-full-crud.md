# PI / CI tam CRUD — silinebilir, değiştirilebilir, kontrol edilebilir

**Tarih:** 2026-07-29 · **Tenant:** msa (imports modülü) · **Durum:** plan, onay bekliyor

Sahibin talebi: "PI/CI'lar full CRUD olması lazım, değişebilir ve silinebilir
olsun, istediğimiz gibi kontrol edebilmemiz lazım."

---

## 1 · Bugün ne var, ne yok (kod denetimi)

| | Proforma Invoice | Commercial Invoice |
|---|---|---|
| **C**reate | `save_proforma` ✅ | `create_commercial_invoice` ✅ |
| **R**ead | `list_proformas`, `get_proforma` ✅ | `list_commercial_invoices`, `get_commercial_invoice` ✅ |
| **U**pdate | `save_proforma` ✅ (durum kilidi yok) | `update_commercial_invoice` ✅ (durum kilidi yok) |
| **D**elete | ❌ **uç yok, düğme yok** | ❌ **uç yok, düğme yok** |

Yani asıl eksik **silme**. Güncelleme zaten serbest: statü hattı yalnız
*statü geçişlerini* denetliyor, alan düzenlemeyi engellemiyor.

## 2 · Silmenin gerçek zorluğu: neyin üstüne basıyoruz

Kod taramasıyla çıkan bağımlılıklar:

**CI'a bağlananlar (9 doctype):** Import Container, Import Truck, Customs
Declaration, GRN Checklist, Vet Certificate, Freight Booking, Import Expense,
Commercial Invoice PO Link, Proforma Invoice (`commercial_invoice`) — artı
`custom_commercial_invoice` üzerinden **Purchase Invoice**.

**PI'a bağlananlar:** Commercial Invoice Item (`custom_proforma_invoice`),
Commercial Invoice başlığı (`custom_proforma_invoice`), PI Group üyeliği.

Bunları görmeden silmek defterde ve akışta yetim kayıt bırakır.

## 3 · Tasarım — "önce etkisini göster, sonra sil"

Uygulamanın geri kalanıyla aynı doktrin: sessiz davranış yok, plan önce.

### Uçlar

```
delete_commercial_invoice(company, name, cascade=0, dry_run=1)
delete_proforma_invoice  (company, name, cascade=0, dry_run=1)
```

`dry_run=1` (varsayılan) hiçbir şey yazmaz; **etki raporu** döner:
`{blockers: [...], cascade: {doctype: [isimler]}, deletable: bool}`.

### Kural: muhasebe engeller, operasyon devreder

**ENGEL (asla otomatik silinmez, adı konmuş sebeple durur):**

- İptal edilmemiş **Purchase Invoice** (GL'de canlı borç) — önce
  faturayı iptal et; bunun için `rebook_ci_invoice`/iptal makinesi zaten var.
- İptal edilmemiş **Payment Entry** (konteyner avansı)
- **Landed Cost Voucher**
- **Submitted GRN Checklist** (stok girmiş)
- **Customs Declaration** (GTD alınmış — resmî belge)

**DEVİR (`cascade=1` ile açık onaydan sonra silinir):**

- Import Container, Import Truck, Freight Booking, Vet Certificate,
  Commercial Invoice PO Link, draft GRN Checklist
- PI tarafında: CI satırlarındaki `custom_proforma_invoice` referansı
  **silinmez, boşaltılır** (satır kalır, anlaşma bağı düşer) — sapmalar
  ekranı bunları "PI'sız sevk" olarak zaten gösteriyor.

### Neden salt "cascade delete" değil

Konteyner silmek gerçek bir olay; sahibi bunu görerek onaylamalı. Bu yüzden
plan ekranda kalem kalem çıkar, `cascade=1` ayrı bir kutu.

## 4 · Ek kontrol aksiyonları (aynı pakette)

- **`unlink_proforma_from_ci(pi, ci)`** — supersede bağını geri al. Bugün
  `link_proforma_to_ci` tek yönlü; yanlış eşleşme düzeltilemiyor.
- **PI durum geri alma** — `SUPERSEDED_BY_CI` → `CONFIRMED` (yetkili rol +
  sebep, CI statü hattındaki geri-düzeltme kalıbının aynısı).
- **Liste ekranlarında toplu silme yok** — tek tek, etki raporlu. Toplu
  silme bu veri modelinde kaza üretir.

## 5 · UI

- CI formu ve PI formunda footer'da **Sil** (danger, `btn-outline-danger`).
  Tıklayınca etki raporu modalı: engeller kırmızı, devir listesi kalem kalem,
  "Bağlı kayıtları da sil" onay kutusu, sonra kırmızı onay.
- Engel varsa silme düğmesi pasif; her engelin yanında **onu çözecek ekrana
  link** (ör. "PINV-… iptal et" → fatura formu).

## 6 · Testler (bu sınıfın hataları geri gelmesin)

- Saf modül `_imports_delete.py`: `classify_impact(refs)` → engel/devir ayrımı;
  GL belgesi her zaman engel; boş referans seti her zaman silinebilir.
- Yapısal: `dry_run` varsayılan 1; dry-run hiçbir mutasyona ulaşmadan döner;
  `cascade=0` iken çocuk kayıt silinmez; uçlar imports-gated + `_assert_can_write`
  (`delete`); UI önce planı çeker sonra onay ister.
- i18n 5 dil.

## 7 · Sıralama (bekleyen işlerle birlikte)

1. **Deploy** — `fe25fec` + `4ce31e7` + `069bc95` (tedarikçi defteri CI adıyla,
   sapma tespiti, yeniden kayıt). Canlıda değil.
2. **Ödeme importu** — `PROMPT_import_vendor_history.md` (394 PE, gerçek tarih).
3. **Bu paket** — PI/CI silme + unlink + durum geri alma.

Not: 3'ü 1'den önce yapmak deploy'u büyütür; 2'yi 1'den önce koşmak ise
defterin CI adlarını göstermeden dolmasına yol açar. Önerilen sıra yukarıdaki.
