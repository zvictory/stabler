# Stabler · RFQ kalem varsayılanları — hepsi birden, tek turda

> **Devir belgesi.** Kullanıcı üçüncü kez aynı ekranda tökezledi:
> depo düzeldi, arkasından `UOM Conversion Factor` çıktı. **Arkada iki tane
> daha var.** Bu belge dördünü birden kapatır ve bir de yanlış bir varsayımı
> geri alır.
>
> Bu turda hiçbir şey tahmin edilmedi: kök neden gerçek ERPNext ve Frappe
> kaynağından okundu, kusur repo'nun kendi frappe-free koşumunda **yeniden
> üretildi**, önerilen düzeltme aynı koşumda **çalıştırılıp doğrulandı**
> (151 modül, 150 OK — düşen tek modül aşağıda §3'te açıklanan iki yanlış
> assertion).
>
> **Önceki belgeler geçerli:** `PROMPT_tender_sourcing_phase2_handoff.md` (§0, §2),
> `PROMPT_landed_cost_at_quotation.md` (§1.7), `PROMPT_belge_merkezi.md` (§1.3),
> `PROMPT_seviye1_ihale_panosu.md` (§1.3),
> `PROMPT_teklif_girisi_ve_bagsiz_teklifler.md` (Bölüm 0),
> `PROMPT_rol_kuyruklari.md` (§0).

**Repo:** `~/frappe-bench-local/apps/stabler` · **Dal:** `design/modernist-operations-desk`
**Son commit:** `6d96c3c feat(tender): role queues release`

**Tarayıcı duman testleri SENDE DEĞİL.** Kullanıcı kendisi yapıyor.

---

# BÖLÜM 1 — Kök neden (kaynaktan okundu, tahmin değil)

## 1.1 · `Request for Quotation` ERPNext'in TEK istisnası

`erpnext/buying/doctype/request_for_quotation/request_for_quotation.py:73`:

```python
def validate(self):
	self.validate_duplicate_supplier()
	self.validate_supplier_list()
	super().validate_qty_is_not_zero()
	validate_for_items(self)
	super().set_qty_as_per_stock_uom()
	self.update_email_id()
```

**`super().validate()` YOK.** Dört süper metodu tek tek seçiyor. Yani
`AccountsController.validate:225`'teki

```python
if self.get("_action") and self._action != "update_after_submit":
	self.set_missing_values(for_validate=True)
```

satırı **RFQ için hiç çalışmıyor.** Karşılaştırma: `Supplier Quotation.validate:114`
ilk satırında `super().validate()` diyor — bu yüzden teklif tarafında
uom / stock_uom / conversion_factor kendiliğinden doluyor ve depo düzeltilir
düzeltilmez kaydedilebildi.

Desk'te RFQ formunun çalışmasının sebebi sunucu değil: **istemci** kalem
seçilince `get_item_details`'i çağırıp bu alanları dolduruyor. SPA'dan
sunucuya doğrudan yazınca o adım hiç yaşanmıyor.

## 1.2 · Bu yüzden dört alan boş kalıyor, dördü de reddediliyor

`Request for Quotation Item` JSON'ında `reqd=1` olanlar: `item_code`, `qty`,
`schedule_date`, `uom`, `stock_uom`, `conversion_factor`.
`warehouse` **reqd değil** — o ayrı bir kod yolundan geliyor.

Hataların **çıkış sırası** (Frappe `document.py:734` önce
`run_before_save_methods()` yani controller `validate`, **sonra** `_validate()`
yani zorunlu alan kontrolü çalıştırıyor):

| # | Hata | Kaynak |
|---|---|---|
| 1 | `Row #1: Warehouse is mandatory for stock Item …` | `buying/utils.py:104` `validate_stock_item_warehouse` |
| 2 | `Row #1: UOM Conversion Factor is mandatory.` | `buying_controller.py:709` `set_qty_as_per_stock_uom` |
| 3 | `uom` zorunlu | Frappe `document.py:1491` `_validate_mandatory` |
| 4 | `stock_uom` zorunlu | aynı |
| 5 | `schedule_date` zorunlu | aynı |

Kullanıcı 1'i gördü, düzelttik; 2'yi gördü. **3, 4, 5 sırada bekliyor.**

`schedule_date` için ek not: alanın JSON'da `default: "Today"` değeri var ama
Frappe `base_document.py:476 _init_child` **çocuk satıra doctype varsayılanı
uygulamıyor** — `append` ile eklenen satır o varsayılanı almıyor. Yani
kullanıcı modalda tarih girmezse bu da patlıyor.

## 1.3 · Yeniden üretim (repo'nun kendi koşumu)

`create_rfq`'nun bugün RFQ satırına ne koyduğu:

```
--- item row #1 ---
  conversion_factor = None        <- FAIL
  item_code         = 'RAIL-01'
  qty               = 3.0
  schedule_date     = None        <- FAIL
  stock_uom         = None        <- FAIL
  uom               = None        <- FAIL
  warehouse         = 'Stores - ACME'   <- OK (24880f1 ile geldi)
```

---

# BÖLÜM 2 — Düzeltme (yazıldı, koşturuldu, geçti)

## 2.1 · Doğru UOM hangisi

`erpnext/stock/get_item_details.py:479-486`: `purchase_uom` dalı yalnız
`Purchase Order`, `Purchase Receipt`, `Purchase Invoice`, `Supplier Quotation`
ve satınalma tipli `Material Request` için. **`Request for Quotation` o listede
YOK**, `else` dalına düşüyor:

```python
else:
	ctx.uom = item.stock_uom
```

Yani RFQ'da Desk formu da `stock_uom` kullanıyor. Bizim de öyle yapmamız,
tedarikçiye sorduğumuz birimin RFQ nereden açılırsa açılsın aynı kalmasını
sağlıyor. `purchase_uom` kullanmak "daha doğru" görünür ama Desk ile ayrışır.

## 2.2 · Uygulanacak yardımcı

`api/sourcing.py`'ye ekle ve `create_rfq` içinde `_resolve_warehouse`'dan
hemen sonra çağır. **Bu kod aynen koşturuldu ve beş alanın beşini de
dolduruyor:**

```python
def _apply_rfq_item_defaults(lines: list[dict], fallback_schedule_date) -> None:
	"""Fill the item defaults the Desk form fetches client-side.

	`Request for Quotation` is the one buying document whose controller does NOT
	call `super().validate()` — it cherry-picks four supers instead — so
	`AccountsController.validate` never runs and `set_missing_values` is never
	called for it. Supplier Quotation gets uom / stock_uom / conversion_factor
	filled for free; an RFQ built server-side gets nothing, and ERPNext then
	rejects the row for a field the user was never shown a box for.

	Verified against erpnext/buying/doctype/request_for_quotation/
	request_for_quotation.py::validate and controllers/accounts_controller.py:225.
	"""
	for line in lines:
		stock_uom = frappe.db.get_value("Item", line["item_code"], "stock_uom")
		# RFQ is deliberately ABSENT from get_item_details' purchase_uom branch
		# (erpnext/stock/get_item_details.py:479-486), so the Desk form lands on
		# stock_uom for this doctype too. Matching it keeps the unit we ask the
		# supplier in identical whether the RFQ was raised here or in Desk.
		uom = line.get("uom") or stock_uom
		line["stock_uom"] = stock_uom
		line["uom"] = uom
		if uom == stock_uom:
			line["conversion_factor"] = 1.0
		else:
			from erpnext.stock.get_item_details import get_conversion_factor

			line["conversion_factor"] = (
				get_conversion_factor(line["item_code"], uom).get("conversion_factor") or 1.0
			)
		# reqd on Request for Quotation Item, and frappe applies no doctype
		# default to a row created by `append` (base_document._init_child).
		line["schedule_date"] = line.get("schedule_date") or fallback_schedule_date or today()
```

`get_conversion_factor` **tembel import** — frappe-free testler o dalı hiç
görmesin diye fonksiyonun içinde. Modül başına taşıma.

Satır ekleme sadeleşir, çünkü `schedule_date` artık yardımcıda çözülüyor:

```python
	for line in lines:
		doc.append("items", dict(line))
```

## 2.3 · Benim yanlışım: `set_warehouse` diye bir alan yok

Önceki promptta "hem satır hem başlık `set_warehouse`" yazmıştım. **Yanlış.**
Kaynaktan doğruladım:

```
set_warehouse in RFQ header: False
set_warehouse in Supplier Quotation header: False
```

`set_warehouse` **Sales Order / Purchase Order / Purchase Invoice /
Purchase Receipt** üzerinde var — `api/sales.py` ve `api/purchasing.py` doğru
kullanıyor. `Request for Quotation` ve `Supplier Quotation` üzerinde **yok**.

Dolayısıyla `api/sourcing.py:331` ve `:427`'deki

```python
	if target_wh:
		doc.set_warehouse = target_wh
```

**iki satır da ölü.** Frappe bilinmeyen alanı `get_valid_dict`'te sessizce
düşürüyor; zararsız ama okuyan "depo başlıktan yayılıyor" sanıyor —
oysa işi yapan tek şey `_resolve_warehouse`'un satırlara yazdığı
`line["warehouse"]`. İkisini de **sil**, yerine tek satır yorum bırak:

> RFQ ve Supplier Quotation'da `set_warehouse` alanı yok (PO/PR/PI/SO'da var);
> depo satır bazında yazılır.

---

# BÖLÜM 3 — Testler: iki tanesi olmayan bir alanı doğruluyor

`stabler/tests/test_sourcing_api.py` içinde **dört** assertion var:

```
514: self.assertEqual(doc.get("set_warehouse"), "Stores - ACME")   # TestCreateRfq
520: self.assertEqual(doc.get("set_warehouse"), "Stores - ACME")   # TestCreateRfq
724: self.assertEqual(doc.get("set_warehouse"), "Stores - ACME")   # quotation
739: self.assertEqual(doc.get("set_warehouse"), "Stores - ACME")   # quotation
```

Dördü de yeşil, çünkü sahte `_Doc` bir `dict` ve **her attribute'u kabul
ediyor** — gerçek doctype'ta olmayan bir alanı da. Yani test, üretimde hiçbir
şey yapmayan bir satırı "çalışıyor" diye kilitliyor.

**Silme, DÜZELT:** assertion'ları `doc["items"][0]["warehouse"]` üzerine çevir.
Depo gerçekten oraya yazılıyor ve gerçekten orada gerekiyor
(`buying/utils.py:104` satıra bakıyor, başlığa değil).

Bu, `CLAUDE.md`'nin "test silme" kuralının tam olarak beklediği durum: hedef
davranış **yaşıyor**, sadece test yanlış yere bakıyordu.

## Eklenecek regresyon testleri

`TestCreateRfq` içine, hepsi `doc["items"][0]` üzerinden:

- [ ] `uom` ve `stock_uom` kalemin `stock_uom`'undan doluyor.
- [ ] `conversion_factor == 1.0` (uom == stock_uom olduğunda).
- [ ] Çağıran açıkça farklı bir `uom` geçerse `uom` o oluyor ve
      `conversion_factor` 1.0 **değil** — `get_conversion_factor`'a düşüyor.
- [ ] `schedule_date` boşsa başlığın `schedule_date`'i, o da boşsa `today()`.
- [ ] Başlıkta `schedule_date` doluyken satır kendi tarihini **koruyor**
      (ezilmiyor).
- [ ] `warehouse` **satırda**; `set_warehouse` diye bir şey aranmıyor.

Sahte fixture'a Item'ların `stock_uom`'u eklenmeli — bugün yok:

```python
("Item", "RAIL-01"): _Doc(name="RAIL-01", is_stock_item=1, stock_uom="Nos"),
("Item", "SERVICE-01"): _Doc(name="SERVICE-01", is_stock_item=0, stock_uom="Nos"),
```

→ `fix(tender): the RFQ line ERPNext was never given a chance to fill`

---

# BÖLÜM 4 — İki küçük not

## 4.1 · `valid_till` karşılaştırması metin karşılaştırması

`6ce5093` ile gelen düzeltme doğru çalışıyor ve düzenleme yolunu da doğru
kapsıyor (`sourcing.py:310` belgenin kendi `transaction_date`'ini alıyor).
Tek pürüz: `sourcing.py:318`

```python
if valid_till and str(valid_till) < effective_tx_date:
```

**metin** karşılaştırıyor. ISO `YYYY-MM-DD` geldiği sürece doğru sonuç verir ve
`DateInput` bugün ISO emit ediyor. Ama `2026-8-2` gibi sıfırsız bir gün ya da
başka bir çağıran formatı sessizce yanlış cevap verir. ERPNext kendi kuralında
(`supplier_quotation.py:166`) `getdate()` kullanıyor:

```python
if self.valid_till and getdate(self.valid_till) < getdate(self.transaction_date):
```

Biz de `frappe.utils.getdate` ile karşılaştıralım. Tek satır, mevcut testler
aynen geçmeli.

→ aynı commit'e katılabilir ya da `fix(tender): compare dates as dates`

## 4.2 · `create_rfq` sonrası bekleyen başka zorunlu alan YOK

Kontrol edildi — `Request for Quotation` başlığında `reqd=1` olanlar:
`naming_series`, `company`, `transaction_date`, `suppliers`, `items`, `status`,
`subject`. `naming_series`, `status` ve `subject` `frappe.new_doc`'un uyguladığı
doctype varsayılanlarından geliyor; kalan dördünü `create_rfq` zaten yazıyor.
`Request for Quotation Supplier`'da tek zorunlu alan `supplier`, o da yazılıyor.

Yani Bölüm 2 uygulandığında **zorunlu alan zinciri biter.** Bu turdan sonra
kullanıcıya "bir tane daha çıktı" dedirtmemeli.

---

# BÖLÜM 5 — Sonra

Rol kuyrukları (C1–C5) `6d96c3c` ile indi. `PROMPT_rol_kuyruklari.md`'nin
"Sonraki iş" bölümü sıradaki işi tarif ediyor: **finans kuyruğu** (spec §4,
altıncı satır) — `belge bekliyor → kaydedildi → vadesi geldi → tahsil edildi →
marj sapması`. Yetki kapısı (`_tender_finance_chain`, workspace'in `has_finance`
kapısı) ve son kulvarın planlanan-gerçekleşen karşılaştırması yüzünden ayrı
tutulmuştu. **Bölüm 1–4 bitmeden başlama.**

---

# Çalışma şekli

- Görev başına bir commit; TDD: düşen test → RED → uygula → GREEN → commit.
- Her görev sonunda dur ve göster.
- `git add` ile **yol** ver, dizin verme. Ağaçta ~20 takip edilmeyen
  `PROMPT_*.md` ve `stabler/integrations/msa_migrate/*.py` var — hiçbiri bu
  turun işi değil.
- `make fix`'i tüm ağaçta koşturma; yalnız elinle değiştirdiğin dosyada
  `ruff format <dosya>`.
- **Test silme.** Bölüm 3'teki dört assertion **düzeltilecek**, silinmeyecek.
- `make test` her görev sonunda **0 düşen modül** (taban: 151 modül).
- ERPNext davranışına dair her varsayımı kaynaktan doğrula. Bu belgedeki her
  iddianın yanında dosya ve satır var; seninkinin de olsun.

# Kabul kriterleri

- [ ] Stok kalemi içeren, tarihsiz bir RFQ **hatasız oluşturuluyor** — beş
      hatanın hiçbiri çıkmıyor.
- [ ] RFQ satırında `uom`, `stock_uom`, `conversion_factor`, `schedule_date`,
      `warehouse` dolu.
- [ ] `uom` `stock_uom`'a eşit (RFQ'da `purchase_uom` kullanılmıyor).
- [ ] `set_warehouse` ataması `api/sourcing.py`'den tamamen kalktı; yerinde
      sebebini söyleyen bir yorum var.
- [ ] Dört `set_warehouse` assertion'ı satır seviyesine çevrildi, hiçbiri
      silinmedi.
- [ ] `valid_till` karşılaştırması `getdate` ile yapılıyor.
- [ ] `make test` 151 modül, 0 düşen.
