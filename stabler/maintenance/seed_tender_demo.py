"""Mikas tender hattı için canlı demo verisi — her yeni panoda görünecek şekilde.

Çalıştırma:
    bench --site mikas.erpstable.com execute stabler.maintenance.seed_tender_demo.seed

Temizlik:
    bench --site mikas.erpstable.com execute stabler.maintenance.seed_tender_demo.unseed

NE ÜRETİYOR VE NEDEN
--------------------
Amaç ekranları "dolu göstermek" değil; dört panonun DÖRDÜNÜN de kendi sorusuna
gerçek bir cevap verebilmesi. O yüzden veri, her ekranın gösterdiği ayrımı
içerecek şekilde kuruluyor:

  Operasyon Masası   — bugün ve geçmiş son tarihler, sahipsiz kalmış lotlar
  Tender CRM         — yedi kulvarın hepsinde kart, teklif seti tam/eksik
  Direktör panosu    — kazanılmış, kaybedilmiş ve süren işler bir arada
  Süreç akışı        — bir adım eşiğin içinde, biri sınırda, biri aşmış,
                       ve BİRİ ölçülemez

Son madde bilinçli: damgası olmayan anlaşmalar demo'da da var, çünkü gerçek
sitede de olacaklar (v66 öncesi taşınmış her kayıt). "Ölçülemiyor" satırını
görmeden ekranın dürüstlüğü test edilmiş olmaz — boş bir ekran her zaman
temiz görünür.

GÜVENLİK
--------
Tek işaret: her demo kaydının adında/başlığında ` [DEMO]` geçiyor. `unseed()`
YALNIZ o işareti taşıyanları siliyor; işaretsiz hiçbir kayda dokunmuyor.
Gerçek tender verisi olan bir sitede seed() çalıştırmak da güvenli — yeni
kayıtlar ekliyor, var olanı değiştirmiyor.

Idempotent: demo zaten varsa seed() hiçbir şey yapmadan çıkıyor.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import add_days, now, nowdate

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
	"UTY-2026-4305": -1,   # geçmiş
	"UTY-2026-4308": 0,    # bugün
	"UTY-2026-4310": 2,    # 48 saat
	"UTY-2026-4302": 11,
	"UTY-2026-4306": 18,
	"UTY-2026-4309": 25,
	"UTY-2026-4311": 6,
	"UTY-2026-4312": 32,
	"UTY-2026-4313": 9,
}


def _guard(company: str) -> None:
	"""Eksik bir bağımlılıkta sessizce yarım veri bırakmak yerine yüksek sesle dur."""
	if not frappe.db.table_exists("CRM Deal"):
		frappe.throw(
			"CRM Deal table not found. The 'crm' app must be installed on this site.\n"
			"  bench get-app crm && bench --site <site> install-app crm"
		)
	if not frappe.db.exists("Company", company):
		frappe.throw(f"Unknown company: {company}. Pass the exact Company record name.")
	if not frappe.db.has_column("CRM Deal", "custom_tender_intake"):
		frappe.throw(
			"custom_tender_intake is missing — run `bench --site <site> migrate` first "
			"so patches v37 and v66 create the tender fields."
		)


def _demo_exists() -> bool:
	return bool(
		frappe.db.exists("CRM Deal", {"custom_tender_intake": ["like", f"%{DEMO_SUFFIX}%"]})
	)


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


def _intake(lot_no: str, buyer: str, stage: str, sq_count: int, value: int, owner: str) -> dict:
	"""Aşamanın gerektirdiği KANITI üret, aşamayı yazmakla yetinme.

	`_funnel.classify` olgulardan aşama türetiyor; intake bu olguları taşımazsa
	damgalı aşama ile türetilen aşama ayrışır ve ekranlar birbirini tutmaz.
	"""
	intake: dict = {
		"lot_no": f"{lot_no}{DEMO_SUFFIX}",
		"buyer": buyer,
		"contract_value": value,
		"bid_deadline": add_days(nowdate(), DEADLINE_OFFSETS.get(lot_no, 21)),
		"delivery_deadline": add_days(nowdate(), 90),
		"documents": [
			{"name": "Texnik spetsifikatsiya", "status": "ready"},
			{"name": "Kafolat xati", "status": "ready" if stage in ("priced", "submitted", "won", "lost") else "pending"},
			{"name": "Litsenziya nusxasi", "status": "ready" if stage != "seen" else "pending"},
			{"name": "Narx taklifi", "status": "ready" if stage in ("submitted", "won", "lost") else "pending"},
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
	has_stage = frappe.db.has_column("CRM Deal", "custom_tender_stage")
	has_stamp = frappe.db.has_column("CRM Deal", "custom_tender_stage_entered_at")
	has_pricing = frappe.db.has_column("CRM Deal", "custom_bid_pricing")
	created = []

	for lot_no, buyer, stage, moved_days, sq_count, countries, value in DEMO_LOTS:
		deal = frappe.new_doc("CRM Deal")
		deal.company = company
		deal.organization = _org(buyer)
		deal.custom_tender_intake = json.dumps(
			_intake(lot_no, buyer, stage, sq_count, value, owner), ensure_ascii=False
		)
		if has_pricing and stage in ("priced", "submitted", "won", "lost"):
			deal.custom_bid_pricing = json.dumps({"unit_price": value, "margin_pct": 12}, ensure_ascii=False)
		deal.insert(ignore_permissions=True)
		created.append((deal.name, lot_no, stage, moved_days))

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

	frappe.db.commit()
	print(f"Seeded {len(created)} demo tender deals on {company}:")
	for name, lot_no, stage, moved in created:
		print(f"  {name}  {lot_no}  stage={stage}  moved={moved if moved is not None else 'no stamp'}")
	print("\nVisible on: /tender/desk · /tender/crm · /tender/portfolio · /tender/flow")


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
	for row in deals:
		# Olay kayıtları değişmez (on_trash engelliyor); anlaşmayı silmeden
		# önce doğrudan tablodan düşürülüyor — demo verisi tarih değil.
		frappe.db.sql(
			"DELETE FROM `tabCRM Stage Event` WHERE deal = %(deal)s", {"deal": row["name"]}
		)
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

	frappe.db.commit()
	print(f"Removed {len(deals)} demo tender deals and up to {len(orgs)} demo organizations.")
