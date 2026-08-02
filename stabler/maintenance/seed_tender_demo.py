"""Mikas tender hattı için canlı demo verisi — her yeni panoda görünecek şekilde.

Çalıştırma:
    bench --site mikas.erpstable.com execute stabler.maintenance.seed_tender_demo.seed

Temizlik:
    bench --site mikas.erpstable.com execute stabler.maintenance.seed_tender_demo.unseed

NE ÜRETİYOR VE NEDEN
--------------------
Amaç ekranları "dolu göstermek" değil; YEDİ panonun YEDİSİNİN de kendi sorusuna
gerçek bir cevap verebilmesi. O yüzden veri, her ekranın gösterdiği ayrımı
içerecek şekilde kuruluyor:

  Operasyon Masası   — bugün ve geçmiş son tarihler, atanmış ve atanmamış lotlar
  Tender CRM         — yedi kulvarın hepsinde kart, teklif seti tam/eksik
  Direktör panosu    — kazanılmış, kaybedilmiş ve süren işler bir arada
  Süreç akışı        — bir adım eşiğin içinde, biri sınırda, biri aşmış,
                       ve BİRİ ölçülemez
  Gümrük kuyruğu     — beklemede / işlemde / çekilmiş, ve ETA'sı geçmiş bir satır
  Lojistik panosu    — geciken, yolda ve teslim edilmiş sevkiyat bir arada
  Sözleşme panosu    — kazanılan iki lotun siparişi, iki ayrı kulvarda

Son üç satır bu betiğe sonradan eklendi. İlk hâli yalnız CRM Deal üretiyordu;
gümrük ve lojistik panolarının okuduğu tek kayıt tipi Purchase Order, sözleşme
panosununki ise Sales Order olduğu için üçü de seed'den sonra BOŞ açılıyordu —
ve betiğin kendi çıktı satırı dört pano sayıp diğerlerini hiç anmayarak bunu
itiraf ediyordu.

Son madde bilinçli: damgası olmayan anlaşmalar demo'da da var, çünkü gerçek
sitede de olacaklar (v66 öncesi taşınmış her kayıt). "Ölçülemiyor" satırını
görmeden ekranın dürüstlüğü test edilmiş olmaz — boş bir ekran her zaman
temiz görünür.

GÜVENLİK
--------
Tek işaret: her demo kaydının adında/başlığında ` [DEMO]` geçiyor. `unseed()`
YALNIZ o işareti taşıyanları siliyor; işaretsiz hiçbir kayda dokunmuyor.

İstisna işlem belgeleri: Supplier Quotation, Purchase Order ve Sales Order'ın
taşıyabileceği bir başlık yok, demo oldukları `custom_crm_deal` ile bağlı
oldukları demo anlaşmadan biliniyor. O yüzden `unseed()` üçünü de
anlaşmalardan ÖNCE, yalnız demo anlaşmalara bağlı olanları seçerek siliyor.
Gerçek tender verisi olan bir sitede seed() çalıştırmak da güvenli — yeni
kayıtlar ekliyor, var olanı değiştirmiyor.

Idempotent: demo zaten varsa seed() hiçbir şey yapmadan çıkıyor.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import add_days, flt, now, nowdate

DEMO_SUFFIX = " [DEMO]"

#: (lot_no, buyer, stage, gün_önce_taşındı, sq_sayısı, ülke_sayısı, tutar)
#: `gün_önce_taşındı` None ise damga YAZILMIYOR — süreç akışında
#: "ölçülemiyor" satırını üretmek için.
#:
#: Eşikler: seen 3 · go 5 · sourcing 14 · priced 3 · submitted 30.
#: Adımların durumu bu sayılardan çıkıyor, elle yazılmıyor.
DEMO_LOTS = [
	# seen — eşik 3 gün: biri taze, biri sınırda
	("UTY-2026-4301", "O'zbekiston temir yo'llari AJ", "seen", 1, 0, 0, 0),
	("UTY-2026-4302", "Toshkent vagon ta'mirlash zavodi", "seen", 3, 0, 0, 0),
	# go — eşik 5 gün: ortalama sınıra yakın
	("UTY-2026-4305", "O'zbekiston temir yo'llari AJ", "go", 4, 1, 1, 1840000000),
	("UTY-2026-4306", "Signal va aloqa boshqarmasi", "go", 5, 0, 0, 640000000),
	# sourcing — eşik 14 gün: adım AŞMIŞ durumda
	("UTY-2026-4308", "Signal va aloqa boshqarmasi", "sourcing", 19, 5, 3, 920000000),
	("UTY-2026-4309", "Qurilish materiallari kombinati", "sourcing", 26, 3, 1, 410000000),
	# priced — eşik 3 gün: darboğaz (oransal olarak en kötü)
	("UTY-2026-4310", "O'zbekiston temir yo'llari AJ", "priced", 8, 6, 2, 3150000000),
	("UTY-2026-4311", "Neft mahsulotlari bazasi", "priced", 6, 5, 2, 780000000),
	# submitted — damga YOK: "ölçülemiyor" satırı
	("UTY-2026-4312", "Neft mahsulotlari bazasi", "submitted", None, 4, 2, 480000000),
	("UTY-2026-4313", "Toshkent vagon ta'mirlash zavodi", "submitted", None, 5, 2, 1120000000),
	# sonuçlanmışlar — direktör panosunun kazanma oranı için
	("UTY-2026-4314", "Qurilish materiallari kombinati", "won", 40, 5, 2, 2270000000),
	("UTY-2026-4315", "O'zbekiston temir yo'llari AJ", "won", 55, 6, 3, 1650000000),
	("UTY-2026-4316", "Signal va aloqa boshqarmasi", "lost", 48, 5, 2, 890000000),
]

#: Son tarihler operasyon masasının severity dilini üretiyor: biri geçmiş,
#: biri bugün, biri 48 saat içinde, kalanı ileride.
DEADLINE_OFFSETS = {
	"UTY-2026-4305": -1,  # geçmiş
	"UTY-2026-4308": 0,  # bugün
	"UTY-2026-4310": 2,  # 48 saat
	"UTY-2026-4302": 11,
	"UTY-2026-4306": 18,
	"UTY-2026-4309": 25,
	"UTY-2026-4311": 6,
	"UTY-2026-4312": 32,
	"UTY-2026-4313": 9,
}


#: Teslim son tarihi lot başına. Varsayılan 90 gün; kazanılmış lotlarda
#: sözleşme tarihi daha yakın, çünkü lojistik panosunun "geciken" tanımı
#: ETA ile teslim tarihini karşılaştırıyor — hepsi 90 gün olursa hiçbir
#: sevkiyat gecikmiş çıkmaz ve o kulvar hiç test edilmez.
DELIVERY_OFFSETS = {
	"UTY-2026-4314": 30,
	"UTY-2026-4315": 60,
}

#: Teklifin maliyet tabanı (mal bedeli), lot başına.
#:
#: Direktör panosundaki marj HESAPLANAN bir sayı: `_compute_bid_pnl` net
#: hasılattan bu tabanı, borsa komisyonunu ve vergileri düşüyor. Taban yoksa
#: marj her satırda %100 çıkar — pano dolu görünür, tek bir şey söylemez.
#:
#: KAZANILMIŞ lotlar bilerek burada YOK. Onların tabanı gerçek siparişlerden
#: geliyor (`_bid_inputs`, saklanan `landed_goods` boşsa `po_landed`'a
#: düşüyor); elle bir sayı yazmak o bağı koparır ve plan/gerçek ayrımı demo'da
#: hiç görülmez.
#:
#: Sayılar tek bir orandan türetilmedi: her lot farklı bir marj göstersin diye
#: seçildi (4310 ≈ %18, 4311 ≈ %8, 4312 ≈ %25, 4313 ≈ %15). 4316 kaybedilen
#: lot ve tabanı en düşük olan — yani en yüksek marjla teklif verilmiş,
#: kaybedilme nedeni panodan okunabiliyor.
LANDED_BASIS = {
	"UTY-2026-4310": 2_300_000_000,
	"UTY-2026-4311": 640_000_000,
	"UTY-2026-4312": 320_000_000,
	"UTY-2026-4313": 850_000_000,
	"UTY-2026-4316": 540_000_000,
}

#: Kazanılan lotların sipariş hattı — gümrük kuyruğunu ve lojistik panosunu
#: besleyen tek kayıt tipi Purchase Order.
#:
#: (lot_no, tedarikçi, ülke, eta_gün_farkı, alınan_yüzde, tnved, gümrük_masrafı,
#:  mal_bedeli)
#:
#: `mal_bedeli` sipariş kaleminin fiyatı. Sıfır bırakılamaz: kazanılmış lotun
#: maliyet tabanı bu siparişlerden okunuyor (`_deal_landed` = base_grand_total
#: + masraflar), bedelsiz siparişle "sıfır değerli malın gümrüğü" gibi bir
#: maliyet çıkıyordu. İki lotun toplamları farklı marj üretecek şekilde seçildi
#: (4314 ≈ %12,5 · 4315 ≈ %19,6), ki pano tek renk göstermesin.
#:
#: Beş satır, iki panonun BÜTÜN durumlarını üretecek şekilde seçildi:
#:
#:   lojistik    geciken 2 (ETA sözleşme tarihini aşıyor) · yolda 2 · teslim 1
#:   gümrük      risk 1 (ETA geçmiş) · uyarı 2 (≤7 gün) · sakin 2
#:               pending 1 (masrafsız) · in_progress 3 (gümrük masrafı var) ·
#:               cleared 1 (mal alınmış)
#:
#: 4314'ün ilk satırı bilerek çelişkili: ETA altı gün önce geçmiş ama teslim
#: tarihi hâlâ ileride. Lojistik panosu ona "yolda" diyor (kuralı `eta >
#: delivery`, bugünü hiç kullanmıyor), gümrük kuyruğu aynı satıra "risk"
#: diyor (kuralı `days < 0`). Demo bu ayrımı GİZLEMEMELİ — iki ekranın aynı
#: sevkiyat için farklı şey söylemesi, düzeltilmesi gereken şeyin kendisi.
DEMO_PURCHASE_ORDERS = [
	("UTY-2026-4314", "Hebei Rail Parts", "China", -6, 0, "7302 10 900 0", 41_000_000, 620_000_000),
	("UTY-2026-4314", "Temiryo'l ta'minot", "Uzbekistan", 4, 100, "", 0, 430_000_000),
	("UTY-2026-4314", "UralVagonSnab", "Russian Federation", 45, 0, "7302 40 000 0", 88_000_000, 590_000_000),
	("UTY-2026-4315", "Shandong Heavy", "China", 3, 40, "8607 19 100 0", 62_000_000, 780_000_000),
	("UTY-2026-4315", "Sanoat kompleks", "Uzbekistan", 75, 0, "", 0, 340_000_000),
]

#: Kazanılan lotların sözleşme hattı — sözleşme panosunun (`/tender/board`)
#: okuduğu tek kayıt tipi Sales Order.
#:
#: (lot_no, pano_kulvarı, faturalanan_yüzde)
#:
#: Tutar burada BİLEREK yok: sipariş bedeli DEMO_LOTS'taki lot değerinden
#: okunuyor. Direktör panosunun satır değeri `so_revenue or bid_price`
#: (tender.py:1951) — yani bir Sales Order doğduğu anda o satırın değeri
#: saklanan teklif fiyatından siparişin toplamına GEÇİYOR. İki sayıyı ayrı ayrı
#: yazmak, portföy toplamını sessizce kaydırmanın en kolay yolu olurdu. Tek
#: kaynak lot değeri: miktar 1, fiyat = değer, vergi yok — ve `_contracts()`
#: eşitliği insert'ten sonra kontrol edip tutmuyorsa duruyor.
#:
#: `faturalanan_yüzde` plan/gerçek ayrımını görünür kılıyor: teklif P&L'inin
#: gerçek tarafı hasılatı `base_grand_total × per_billed` ile okuyor
#: (`_deal_revenue_actual`). İkisi de 0 kalırsa o panel "faturalanmadı" der ve
#: hiç ölçülmez; ikisi de 100 olursa plan ile gerçek birebir aynı çıkar ve
#: ayrım yine görünmez. O yüzden 4314 kısmen faturalanmış (kulvarı da bu yüzden
#: Invoicing), 4315 hiç faturalanmamış.
DEMO_SALES_ORDERS = [
	("UTY-2026-4314", "Invoicing", 60),
	("UTY-2026-4315", "Procurement", 0),
]

#: Demo tedarikçileri, ülke başına üç isim. Ülke veriyle geliyor, isimden
#: tahmin edilmiyor: CRM panosunun `country_count` rozetini üreten alan
#: `Supplier.country` — orası boşsa rozet, teklifler dursa bile 0 gösterir.
DEMO_SUPPLIERS = [
	("Uzbekistan", ["Temiryo'l ta'minot", "Sanoat kompleks", "Toshkent metall"]),
	("China", ["Hebei Rail Parts", "Shandong Heavy", "Ningbo Import"]),
	# "Russian Federation", "Russia" değil: Country doctype'ının kayıt adı budur.
	# Yanlış ad sessizce düşerdi — bkz. _supplier'daki throw.
	("Russian Federation", ["UralVagonSnab", "SibTransDetal", "Rostov Metiz"]),
]

#: Tekliflerin üzerine yazıldığı kalem. Stok kalemi DEĞİL: demo'nun ambar,
#: parti ya da stok hareketi üretmesi gerekmiyor.
DEMO_ITEM = "Rels birikmasi"


def _pick_suppliers(sq_count: int, countries: int) -> list[tuple[str, str]]:
	"""`sq_count` teklifi TAM `countries` ülkeye dağıt — (ad, ülke) çiftleri.

	Panoda iki ayrı rozet var: `has_min_5` teklif SAYISINI, `has_2_countries`
	ülke ÇEŞİDİNİ ölçüyor. İkisi birbirinden bağımsız kırılabilsin diye dağıtım
	round-robin — yoksa "5 teklif topladım ama hepsi tek ülkeden" hâli hiç
	üretilemez ve o rozet test edilmemiş kalır.

	Havuz yetmediğinde aynı tedarikçiden ikinci teklif üretmek yerine duruyoruz:
	sq_count doğru çıkar ama veri yalan söyler.
	"""
	if sq_count <= 0:
		return []
	countries = max(1, min(countries or 1, len(DEMO_SUPPLIERS)))
	per_country = -(-sq_count // countries)  # tavana yuvarlayan bölme
	if per_country > min(len(names) for _, names in DEMO_SUPPLIERS[:countries]):
		frappe.throw(
			f"Demo supplier pool too small: {sq_count} quotations across {countries} "
			f"countries needs {per_country} suppliers per country."
		)
	return [
		(DEMO_SUPPLIERS[i % countries][1][i // countries], DEMO_SUPPLIERS[i % countries][0])
		for i in range(sq_count)
	]


def _guard(company: str) -> None:
	"""Eksik bir bağımlılıkta sessizce yarım veri bırakmak yerine yüksek sesle dur."""
	# DocType kaydını sor, tabloyu DEĞİL. `crm` hiç kurulmamış ya da kaldırılmış bir
	# sitede `tabCRM Deal` geride kalabiliyor (ölçüldü 2026-08-02, yerel `stabler`
	# sitesi: tablo var, 55 kolon, 0 satır, DocType kaydı yok). O durumda
	# table_exists bayat tabloya bakıp True döner, bu kontrol geçer ve betik
	# aşağıdaki custom_tender_intake dalında ölür — mesajı "migrate çalıştır" der.
	# Ama DocType'ı olmayan bir yerde migrate o custom field'ı asla yaratamaz:
	# kullanıcı düzelmeyecek bir komutu tekrar tekrar çalıştırır. Eksik bağımlılığın
	# adı `crm` uygulaması; kontrol de onu sormalı.
	if not frappe.db.exists("DocType", "CRM Deal"):
		frappe.throw(
			"CRM Deal doctype not found. The 'crm' app must be installed on this site.\n"
			"  bench get-app crm && bench --site <site> install-app crm"
		)
	if not frappe.db.exists("Company", company):
		frappe.throw(f"Unknown company: {company}. Pass the exact Company record name.")
	if not frappe.db.has_column("CRM Deal", "custom_tender_intake"):
		frappe.throw(
			"custom_tender_intake is missing — run `bench --site <site> migrate` first "
			"so patches v37 and v66 create the tender fields."
		)
	# Teklif seti olmadan CRM panosunun yarısı (≥5 teklif · ≥2 ülke) ölçülemez.
	# Sessizce teklifsiz demo bırakmak, düzeltilen hatanın ta kendisiydi.
	if not frappe.db.has_column("Supplier Quotation", "custom_crm_deal"):
		frappe.throw(
			"Supplier Quotation.custom_crm_deal is missing — run `bench --site <site> "
			"migrate` first so patch v30 links quotations to deals."
		)
	# Aynı gerekçe siparişler için: gümrük kuyruğu ve lojistik panosunun okuduğu
	# tek bağ bu kolon. Kontrol BAŞTA, `_orders()` içinde değil — orada durmak
	# on üç anlaşma ve teklif setleri yaratıldıktan SONRA durmak demek, yani
	# tam olarak kaçınılmak istenen yarım demo.
	if not frappe.db.has_column("Purchase Order", "custom_crm_deal"):
		frappe.throw(
			"Purchase Order.custom_crm_deal is missing — run `bench --site <site> migrate` "
			"first, or the customs and logistics boards would have nothing to read."
		)
	# Sözleşme panosu ile direktör panosunun hasılat sütunu aynı kolonu okuyor;
	# yoksa biri boş açılır, diğeri değeri sessizce teklif fiyatına düşürür.
	if not frappe.db.has_column("Sales Order", "custom_crm_deal"):
		frappe.throw(
			"Sales Order.custom_crm_deal is missing — run `bench --site <site> migrate` "
			"first, or the contract board would have nothing to read."
		)


def _demo_exists() -> bool:
	return bool(frappe.db.exists("CRM Deal", {"custom_tender_intake": ["like", f"%{DEMO_SUFFIX}%"]}))


def _org(name: str) -> str:
	"""Demo alıcı kurumu; varsa yeniden kullan."""
	title = f"{name}{DEMO_SUFFIX}"
	existing = frappe.db.exists("CRM Organization", {"organization_name": title})
	if existing:
		return existing
	doc = frappe.new_doc("CRM Organization")
	doc.organization_name = title
	doc.insert(ignore_permissions=True)
	return doc.name


def _supplier(name: str, country: str) -> str:
	"""Demo tedarikçisi; varsa yeniden kullan."""
	title = f"{name}{DEMO_SUFFIX}"
	existing = frappe.db.exists("Supplier", {"supplier_name": title})
	if existing:
		return existing
	doc = frappe.new_doc("Supplier")
	doc.supplier_name = title
	# Sessizce atlamak yok. Panonun "kaç ülkeden teklif geldi" sayısı DOĞRUDAN bu
	# alandan türüyor; yazılamayan ülke, Supplier'ı sistem varsayılanına düşürür ve
	# sayı hiçbir hata vermeden küçülür. Ölçüldü 2026-08-01, mikas: "Russia" Country
	# listesinde yok ("Russian Federation" var), iki tedarikçi Uzbekistan'a düştü ve
	# üç ülkelik demo panoda iki ülke olarak göründü.
	if not frappe.db.exists("Country", country):
		frappe.throw(
			f"Country '{country}' bu sitede yok — demo tedarikçisi yanlış ülkeye "
			f"düşerdi ve pano ülke sayısını sessizce eksik gösterirdi."
		)
	doc.country = country
	group = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
	if group:
		doc.supplier_group = group
	doc.insert(ignore_permissions=True)
	return doc.name


def _demo_item() -> str:
	"""Tekliflerin satırında duracak kalem; varsa yeniden kullan."""
	title = f"{DEMO_ITEM}{DEMO_SUFFIX}"
	existing = frappe.db.exists("Item", {"item_name": title})
	if existing:
		return existing
	doc = frappe.new_doc("Item")
	doc.item_code = title
	doc.item_name = title
	doc.item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or frappe.db.get_value(
		"Item Group", {}, "name"
	)
	doc.stock_uom = frappe.db.get_value("UOM", {"name": "Nos"}) or frappe.db.get_value("UOM", {}, "name")
	doc.is_stock_item = 0
	doc.insert(ignore_permissions=True)
	return doc.name


def _quotations(
	deal: str, company: str, lot_no: str, sq_count: int, countries: int, value: int, bid_deadline: str
) -> int:
	"""Lotun teklif setini GERÇEKTEN yarat, sayısını intake'e yazmakla yetinme.

	CRM panosu `sq_count`'u kolondan değil, `custom_crm_deal` ile bağlı Supplier
	Quotation kayıtlarını sayarak buluyor; `country_count` da o tekliflerin
	tedarikçilerinin ülkesinden. Yani teklif belgesi yoksa demo kartlarda rozet
	0/0 kalır — ekranın anlatmak istediği tek şey kaybolur.

	Belgeler taslak bırakılıyor: pano `docstatus < 2` sayıyor, taslak da o
	kümede. Onaylamak muhasebeye hiçbir şey eklemez, geri almayı zorlaştırır.
	"""
	picks = _pick_suppliers(sq_count, countries)
	if not picks:
		return 0
	item = _demo_item()
	# Teklifler son tarihten önce toplanmış olmalı; ileri tarihli bir lotta
	# "bugün"ü aşmasın diye bugünle sınırlanıyor.
	txn_date = min(add_days(bid_deadline, -7), nowdate())
	for i, (supplier_name, country) in enumerate(picks):
		quotation = frappe.new_doc("Supplier Quotation")
		quotation.company = company
		quotation.supplier = _supplier(supplier_name, country)
		quotation.transaction_date = txn_date
		quotation.valid_till = add_days(bid_deadline, 30)
		quotation.custom_crm_deal = deal
		quotation.append(
			"items",
			{
				"item_code": item,
				"item_name": f"{lot_no}{DEMO_SUFFIX}",
				"description": f"{lot_no}{DEMO_SUFFIX}",
				"qty": 1,
				# Teklifler birbirinden farklı: tek fiyatlı bir set, fiyat
				# karşılaştırma ekranını da sınamaz.
				"rate": round(value * (0.92 + i * 0.03)),
				"schedule_date": bid_deadline,
			},
		)
		quotation.insert(ignore_permissions=True)
	return len(picks)


def _orders(deal_by_lot: dict[str, str], company: str) -> int:
	"""Kazanılan lotların siparişlerini yarat — gümrük ve lojistik panolarının
	okuduğu TEK kayıt tipi bu.

	İki ekran da `custom_crm_deal` ile bir anlaşmaya bağlı Purchase Order
	satırlarını gösteriyor (`_po_rows_for_views`). Sipariş yoksa iki pano da
	boş açılır — demo altı panonun dördünü besleyip ikisini karanlıkta
	bırakıyordu.

	Belgeler taslak bırakılıyor, teklifler gibi: panolar `docstatus < 2`
	okuyor, taslak o kümede. `per_received` normalde mal kabulünden hesaplanır;
	burada doğrudan kolona yazılıyor çünkü demo'nun Purchase Receipt üretmesi
	stok ve muhasebe hareketi demek olurdu. Yani "alındı" yüzdesi demo'da bir
	gösterge, arkasında irsaliye yok — bilerek.
	"""
	has_landed = frappe.db.has_column("Purchase Order", "custom_landed_charges")
	item = _demo_item()
	made = 0
	for lot_no, supplier_name, country, eta_days, received_pct, tnved, customs, goods in DEMO_PURCHASE_ORDERS:
		deal = deal_by_lot.get(lot_no)
		if not deal:
			continue
		eta = add_days(nowdate(), eta_days)
		order = frappe.new_doc("Purchase Order")
		order.company = company
		order.custom_crm_deal = deal
		order.supplier = _supplier(supplier_name, country)
		# Sipariş tarihi ETA'dan önce olmalı; geçmiş ETA'lı satırda bugünü
		# aşmasın diye bugünle sınırlanıyor.
		order.transaction_date = min(add_days(eta, -30), nowdate())
		order.schedule_date = eta
		if has_landed and customs:
			order.custom_landed_charges = json.dumps(
				[
					{
						"type": "customs",
						"label": f"Bojxona to'lovi{DEMO_SUFFIX}",
						"amount": customs,
						"tnved": tnved,
					}
				],
				ensure_ascii=False,
			)
		order.append(
			"items",
			{
				"item_code": item,
				"item_name": f"{lot_no}{DEMO_SUFFIX}",
				"description": f"{lot_no}{DEMO_SUFFIX}",
				"qty": 1,
				"rate": goods,
				"schedule_date": eta,
			},
		)
		order.insert(ignore_permissions=True)
		if received_pct:
			frappe.db.set_value(
				"Purchase Order", order.name, "per_received", received_pct, update_modified=False
			)
		made += 1
	return made


def _customer(name: str) -> str:
	"""Sözleşmenin alıcısı; varsa yeniden kullan.

	CRM Organization ile Customer ayrı doctype'lar — pano CRM tarafını, Sales
	Order muhasebe tarafını okuyor. Demo ikisini aynı isimle yaratıyor ki
	sözleşme panosundaki alıcı adı, CRM kartındaki kurumla göz kararı eşleşsin.
	"""
	title = f"{name}{DEMO_SUFFIX}"
	existing = frappe.db.exists("Customer", {"customer_name": title})
	if existing:
		return existing
	doc = frappe.new_doc("Customer")
	doc.customer_name = title
	doc.customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	doc.territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
	doc.insert(ignore_permissions=True)
	return doc.name


def _contracts(deal_by_lot: dict[str, str], company: str) -> int:
	"""Kazanılan lotların sözleşmelerini yarat — sözleşme panosunun beslendiği
	tek kayıt tipi Sales Order.

	Bu tohumun tek ONAYLANMIŞ belgesi, ve bu bir istisna değil zorunluluk:
	`so_board` `docstatus: 1` süzüyor (tender.py:99), yani taslak bırakılan bir
	sipariş panoda hiç görünmez. Teklif ve satın alma siparişlerini taslak
	bırakma gerekçesi ("onaylamak muhasebeye bir şey eklemez, geri almayı
	zorlaştırır") burada tersine dönüyor. Onay yine de güvenli: Sales Order
	submit'i GL kaydı yazmıyor, demo kalemi de stok kalemi değil
	(`is_stock_item = 0`), dolayısıyla ambar hareketi de doğmuyor.

	`per_billed` normalde faturadan hesaplanır; `_orders()`'daki `per_received`
	gibi doğrudan kolona yazılıyor — demo'nun Sales Invoice üretmesi gerçek
	muhasebe hareketi demek olurdu. Yani "faturalanan" yüzdesi demo'da bir
	gösterge, arkasında fatura yok — bilerek.
	"""
	value_by_lot = {lot[0]: lot[6] for lot in DEMO_LOTS}
	buyer_by_lot = {lot[0]: lot[1] for lot in DEMO_LOTS}
	item = _demo_item()
	made = 0
	for lot_no, stage, billed_pct in DEMO_SALES_ORDERS:
		deal = deal_by_lot.get(lot_no)
		if not deal:
			continue
		value = value_by_lot[lot_no]
		delivery = add_days(nowdate(), DELIVERY_OFFSETS.get(lot_no, 90))
		order = frappe.new_doc("Sales Order")
		order.company = company
		order.customer = _customer(buyer_by_lot[lot_no])
		order.transaction_date = nowdate()
		order.delivery_date = delivery
		order.custom_crm_deal = deal
		# Ambar bu demo için anlamsız (kalem stok kalemi değil), ama boş
		# bırakılamıyor: ERPNext satırın ambarını oturumun kullanıcı
		# varsayılanından dolduruyor ve o varsayılan BAŞKA bir şirkete ait
		# olabiliyor. Ölçüldü 2026-08-02, yerel `stabler`: Administrator'ın
		# varsayılanı anjan'ın "Tayyor mahsulot - A" ambarıydı, insert
		# InvalidWarehouseCompany ile düştü. Şirketin kendi ambarı yazılıyor.
		warehouse = frappe.db.get_value(
			"Warehouse", {"company": company, "is_group": 0}, "name", order_by="name asc"
		)
		if warehouse:
			order.set_warehouse = warehouse
		# Kulvar yoksa alan boş kalsın: `so_board` boş kulvarı ilk açık kulvara
		# yerleştiriyor (lazy placement), var olmayan bir kulvara Link yazmak ise
		# insert'i düşürürdü.
		if frappe.db.exists("Stabler SO Stage", stage):
			order.custom_board_stage = stage
		order.append(
			"items",
			{
				"item_code": item,
				"item_name": f"{lot_no}{DEMO_SUFFIX}",
				"description": f"{lot_no}{DEMO_SUFFIX}",
				"qty": 1,
				"rate": value,
				"delivery_date": delivery,
			},
		)
		order.insert(ignore_permissions=True)
		# Sessiz kayma buradan olurdu: sitede varsayılan bir satış vergisi
		# şablonu ya da lot değerinden farklı bir kur varsa toplam lot değerini
		# tutmaz, direktör panosunun DOĞRULANMIŞ portföy rakamı da o anda
		# değişir — çünkü satır değeri Sales Order doğar doğmaz teklif fiyatını
		# bırakıp bu toplamı okumaya başlıyor. Eşitlik tutmuyorsa yarım demo
		# bırakmak yerine duruyoruz.
		if flt(order.grand_total) != flt(value) or flt(order.base_grand_total) != flt(value):
			frappe.throw(
				f"{lot_no}: sales order total {order.grand_total} (base {order.base_grand_total}) "
				f"!= lot value {value}. A default sales tax template or a non-1 exchange rate is "
				f"in play; the director board's portfolio figure would shift silently."
			)
		order.submit()
		if billed_pct:
			frappe.db.set_value("Sales Order", order.name, "per_billed", billed_pct, update_modified=False)
		made += 1
	return made


def _pick_team(limit: int = 3) -> list[str]:
	"""Atama için gerçek kullanıcılar; yoksa boş dön."""
	return [
		u.name
		for u in frappe.get_all(
			"User",
			filters={"enabled": 1, "user_type": "System User", "name": ["!=", "Administrator"]},
			fields=["name"],
			limit=limit,
			order_by="creation asc",
		)
	]


def _intake(lot_no: str, buyer: str, stage: str, value: int, owner: str, assignee: str = "") -> dict:
	"""Aşamanın gerektirdiği KANITI üret, aşamayı yazmakla yetinme.

	`_funnel.classify` olgulardan aşama türetiyor; intake bu olguları taşımazsa
	damgalı aşama ile türetilen aşama ayrışır ve ekranlar birbirini tutmaz.
	"""
	intake: dict = {
		"lot_no": f"{lot_no}{DEMO_SUFFIX}",
		"buyer": buyer,
		"contract_value": value,
		"bid_deadline": add_days(nowdate(), DEADLINE_OFFSETS.get(lot_no, 21)),
		"delivery_deadline": add_days(nowdate(), DELIVERY_OFFSETS.get(lot_no, 90)),
		"documents": [
			{"name": "Texnik spetsifikatsiya", "status": "ready", "role": "general"},
			{
				"name": "Kafolat xati",
				"status": "ready" if stage in ("priced", "submitted", "won", "lost") else "pending",
				"role": "general",
			},
			{
				"name": "Litsenziya nusxasi / Сертификат",
				"status": "ready" if stage != "seen" else "pending",
				"role": "customs",
			},
			{
				"name": "Narx taklifi / Инвойс",
				"status": "ready" if stage in ("submitted", "won", "lost") else "pending",
				"role": "finance",
			},
			{
				"name": "ГТД / Gümrük beyannamesi",
				"status": "ready" if stage in ("won", "done") else "pending",
				"role": "customs",
			},
			{
				"name": "CMR / Transport nakladnoyasi",
				"status": "ready" if stage in ("won", "done") else "pending",
				"role": "logistics",
			},
		],
	}
	if stage != "seen":
		intake["go_no_go"] = "go"
		intake["go_no_go_at"] = now()
	if stage in ("submitted", "won", "lost"):
		# İkisi birden şart: `_has_submission_evidence` sonucu değil, KATILIMI
		# kanıt sayıyor.
		intake["submitted_at"] = now()
		intake["submitted_by"] = owner
	if stage in ("won", "lost"):
		intake["result"] = stage
	# Atama, tedarik penceresinin görünürlük sınırı: `/tender/my-tenders` ve
	# masanın sourcing süzgeci bu alandan okuyor, ekip yükü de kırılımını
	# buradan alıyor. Atamasız demo'da üçü de belge sahibine çöküyordu — yani
	# tek satır, hep aynı isim. `seen` lotları BİLEREK atamasız kalıyor: yeni
	# gelen ilan henüz kimsenin değil, ve panonun "sahipsiz" hâlini de birinin
	# göstermesi lazım.
	if assignee:
		intake["assigned_to"] = assignee
		intake["assigned_to_name"] = frappe.db.get_value("User", assignee, "full_name") or assignee
		intake["assigned_at"] = now()
		intake["assigned_by"] = owner
	return intake


def _pick_owner() -> str:
	users = frappe.get_all(
		"User",
		filters={"enabled": 1, "user_type": "System User", "name": ["!=", "Administrator"]},
		fields=["name"],
		limit=1,
		order_by="creation asc",
	)
	return users[0].name if users else "Administrator"


def seed(company: str = "Mikas"):
	"""13 demo tender anlaşması — her aşamada, her severity'de kayıt."""
	_guard(company)
	if _demo_exists():
		print("Tender demo data already present — nothing to do. Run unseed() first to recreate.")
		return

	owner = _pick_owner()
	team = _pick_team()
	has_stage = frappe.db.has_column("CRM Deal", "custom_tender_stage")
	has_stamp = frappe.db.has_column("CRM Deal", "custom_tender_stage_entered_at")
	has_pricing = frappe.db.has_column("CRM Deal", "custom_bid_pricing")
	created = []
	deal_by_lot: dict[str, str] = {}
	sq_total = 0
	assigned_n = 0

	for lot_no, buyer, stage, moved_days, sq_count, countries, value in DEMO_LOTS:
		# `seen` dışındaki her lot ekipte bir kişiye düşüyor; sırayla, ki ekip
		# yükü paneli tek çubuk değil gerçek bir dağılım göstersin.
		assignee = team[assigned_n % len(team)] if team and stage != "seen" else ""
		if assignee:
			assigned_n += 1
		intake = _intake(lot_no, buyer, stage, value, owner, assignee)
		deal = frappe.new_doc("CRM Deal")
		deal.company = company
		deal.organization = _org(buyer)
		deal.custom_tender_intake = json.dumps(intake, ensure_ascii=False)
		if has_pricing and stage in ("priced", "submitted", "won", "lost"):
			# Anahtarlar `_compute_bid_pnl`'in OKUDUĞU adlar olmak zorunda.
			# Ölçüldü 2026-08-02, yerel Mikas: burada `unit_price` yazıyordu ve
			# motorda öyle bir anahtar yok — yedi fiyatlanmış lotun beşi direktör
			# panosunda değer=0 göründü, marj ise saklanan `margin_pct` neyse o
			# çıktı (%12, on üç satırın hepsinde aynı). Yani pano bir hesap değil
			# bir sabit gösteriyordu ve fiyat motoru demo'da hiç çalışmıyordu.
			#
			# mode="price": sözleşme bedeli GİRDİ, marj sonuç. Direktörün portföy
			# değeri böylece lot değerlerinin toplamına eşit oluyor, arada sihirli
			# bir katsayı kalmıyor. `landed_goods` yalnız siparişsiz lotlara
			# yazılıyor; kazanılmışlarda motor gerçek siparişlere düşsün diye.
			pricing = {"mode": "price", "bid_price": value}
			if lot_no in LANDED_BASIS:
				pricing["landed_goods"] = LANDED_BASIS[lot_no]
			deal.custom_bid_pricing = json.dumps(pricing, ensure_ascii=False)
		deal.insert(ignore_permissions=True)
		created.append((deal.name, lot_no, stage, moved_days))
		deal_by_lot[lot_no] = deal.name
		sq_total += _quotations(
			deal.name, company, lot_no, sq_count, countries, value, intake["bid_deadline"]
		)

		if has_stage:
			frappe.db.set_value("CRM Deal", deal.name, "custom_tender_stage", stage)
		# Damga BİLEREK bazı kayıtlarda yok: süreç akışının "ölçülemiyor"
		# satırı gerçek sitede de olacak, demo onu saklamamalı.
		if has_stamp and moved_days is not None:
			frappe.db.set_value(
				"CRM Deal",
				deal.name,
				"custom_tender_stage_entered_at",
				add_days(nowdate(), -moved_days),
				update_modified=False,
			)
			_stage_history(deal.name, company, stage, moved_days)

	po_total = _orders(deal_by_lot, company)
	so_total = _contracts(deal_by_lot, company)

	frappe.db.commit()
	print(
		f"Seeded {len(created)} demo tender deals, {sq_total} supplier quotations, "
		f"{po_total} purchase orders and {so_total} sales orders on {company}:"
	)
	for name, lot_no, stage, moved in created:
		print(f"  {name}  {lot_no}  stage={stage}  moved={moved if moved is not None else 'no stamp'}")
	if not team:
		print("\n  NOTE: no non-Administrator user on this site — nothing could be assigned,")
		print("        so team load and /tender/my-tenders will still read empty.")
	print(
		"\nVisible on: /tender/desk · /tender/crm · /tender/portfolio · /tender/flow"
		" · /tender/customs · /tender/logistics · /tender/board"
	)


def _stage_history(deal: str, company: str, stage: str, moved_days: int) -> None:
	"""Aşamaya nasıl gelindiğinin kaydı.

	Süreç akışı "nerede oyalandık" sorusunu geçmişten okuyor; yalnız son
	damgayı yazmak, her anlaşmayı doğrudan bugünkü kulvarına doğmuş gösterir.
	"""
	from stabler.api._funnel import ORDER

	if stage not in ORDER:
		path = ["seen", "go", "sourcing", "priced", "submitted"]
	else:
		path = ORDER[: ORDER.index(stage) + 1]

	previous = ""
	span = max(1, moved_days)
	for i, step in enumerate(path):
		when = add_days(nowdate(), -(span + (len(path) - i) * 3))
		try:
			event = frappe.new_doc("CRM Stage Event")
			event.update(
				{
					"company": company,
					"reference_doctype": "CRM Deal",
					"reference_name": deal,
					"deal": deal,
					"axis": "tender_stage",
					"from_tender_stage": previous,
					"to_tender_stage": step,
					"changed_at": when,
					"changed_by": frappe.session.user,
				}
			)
			event.insert(ignore_permissions=True)
		except Exception:
			# Geçmiş demo'nun süsü; yazılamıyorsa anlaşmayı yaratmaktan
			# vazgeçmek yanlış olur.
			frappe.log_error(title="Demo stage event skipped", message=frappe.get_traceback())
		previous = step


def unseed(company: str = "Mikas"):
	"""YALNIZ ` [DEMO]` işaretli kayıtları sil. İşaretsiz hiçbir şeye dokunma."""
	deals = frappe.get_all(
		"CRM Deal",
		filters={"company": company, "custom_tender_intake": ["like", f"%{DEMO_SUFFIX}%"]},
		fields=["name"],
		limit_page_length=0,
	)
	# Teklifler anlaşmalardan ÖNCE siliniyor: bağlantı `custom_crm_deal` üzerinden
	# kuruluyor, anlaşma gidince demo teklifleri hangi kaydın olduğu artık
	# bilinemez ve sitede sahipsiz kalırlar.
	deal_names = [row["name"] for row in deals]
	# Siparişler de tekliflerle aynı durumda: kendi başlıklarında ` [DEMO]`
	# taşımıyorlar, demo oldukları yalnız bağlı oldukları anlaşmadan biliniyor.
	# O yüzden üçü de anlaşmalardan ÖNCE gidiyor. Sales Order onaylanmış
	# durumda; `force=True` onaylanmış belgeyi de siliyor (GL kaydı yok, iptal
	# edilecek bir muhasebe hareketi de yok).
	removed = {"Supplier Quotation": 0, "Purchase Order": 0, "Sales Order": 0}
	for doctype in removed:
		if not deal_names or not frappe.db.has_column(doctype, "custom_crm_deal"):
			continue
		for row in frappe.get_all(
			doctype,
			filters={"custom_crm_deal": ["in", deal_names]},
			fields=["name"],
			limit_page_length=0,
		):
			frappe.delete_doc(doctype, row["name"], force=True, ignore_permissions=True)
			removed[doctype] += 1

	for row in deals:
		# Olay kayıtları değişmez (on_trash engelliyor); anlaşmayı silmeden
		# önce doğrudan tablodan düşürülüyor — demo verisi tarih değil.
		frappe.db.sql("DELETE FROM `tabCRM Stage Event` WHERE deal = %(deal)s", {"deal": row["name"]})
		frappe.delete_doc("CRM Deal", row["name"], force=True, ignore_permissions=True)

	orgs = frappe.get_all(
		"CRM Organization",
		filters={"organization_name": ["like", f"%{DEMO_SUFFIX}"]},
		fields=["name"],
		limit_page_length=0,
	)
	for row in orgs:
		if not frappe.db.exists("CRM Deal", {"organization": row["name"]}):
			frappe.delete_doc("CRM Organization", row["name"], force=True, ignore_permissions=True)

	# Tedarikçi ve kalem `force` OLMADAN siliniyor: işaretli olsalar bile
	# demo dışı bir belge bağlanmışsa Frappe LinkExistsError atar ve kayıt
	# yerinde kalır. Temizlik, sildiğinden emin olmadığı şeyi zorlamamalı.
	extras_removed = 0
	for doctype, field in (
		("Supplier", "supplier_name"),
		("Customer", "customer_name"),
		("Item", "item_name"),
	):
		for row in frappe.get_all(
			doctype,
			filters={field: ["like", f"%{DEMO_SUFFIX}"]},
			fields=["name"],
			limit_page_length=0,
		):
			try:
				frappe.delete_doc(doctype, row["name"], ignore_permissions=True)
				extras_removed += 1
			except frappe.LinkExistsError:
				print(f"  kept {doctype} {row['name']} — still linked by a non-demo document")

	frappe.db.commit()
	print(
		f"Removed {len(deals)} demo tender deals, {removed['Supplier Quotation']} supplier "
		f"quotations, {removed['Purchase Order']} purchase orders, {removed['Sales Order']} "
		f"sales orders, {extras_removed} demo suppliers/customers/items and up to "
		f"{len(orgs)} demo organizations."
	)
