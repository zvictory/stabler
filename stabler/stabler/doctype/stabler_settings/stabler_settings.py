import json

import frappe
from frappe.model.document import Document


class StablerSettings(Document):
	pass


# Canonical opt-in module defaults for a brand-new company (and the no-row
# fallback). Lean ERP core — money+sales+purchasing+inventory — is ON; every
# specialized module is opt-in per owner-tenant. SINGLE SOURCE OF TRUTH: keep
# this in sync with the `Stabler Company Modules` doctype `default`s; both
# get_company_module_row and module_map_for derive from it, and
# organization.update_company_modules seeds new rows from _default_enable_row.
# Rationale: docs/plans/2026-07-18-multitenant-governance.md
DEFAULT_MODULE_ENABLED = {
	"money": True,
	"sales": True,
	"purchasing": True,
	"inventory": True,
	"manufacturing": False,
	"hr": False,
	"stock_reservation": False,
	"compliance": False,
	"field_sales": False,
	"marketing": False,
	"crm": False,
	"service": False,
	"bpm": False,
	"tender": False,
	"remittance": False,
	"installment": False,
	"imports": False,
	"agreements": False,
	# Satış Siparişi olmadan fatura. Varsayılan KAPALI: fatura normalde
	# gönderilmiş bir SO'dan çıkar; bu istisnayı kiracı başına açmak gerekir.
	"direct_invoicing": False,
	# Satış siparişi satırlarında ölçü sütunları (boy/en/yükseklik/adet)
	# varsayılan olarak görünsün mü. YALNIZ GÖRÜNÜM tercihi: ölçülü bir kalemin
	# miktarı bu bayraktan bağımsız olarak hep ölçüden hesaplanır ve satırdaki
	# kalem ölçülüyse sütun bayrak kapalıyken de açılır — aksi hâlde kullanıcı
	# türetilmiş bir miktarı açıklamasız görürdü. Varsayılan kapalı: kiracıların
	# çoğu (horeca, smartbox, msa) hiç ölçülü ürün satmıyor.
	"dimensional_lines": False,
	# Yeni Satış Siparişi satırı stok birimi yerine en büyük koli/kutu birimini
	# (conversion_factor > 1) mi seçsin. Varsayılan KAPALI: kayış (dts) ya da
	# hizmet (horeca) satan kiracıda stok birimi doğrudur, koliye sessizce
	# geçmemeli.
	"sales_box_uom": False,
	# Satış Siparişi'nin yeniden tasarlanmış tek sütunlu formu mu çizilsin.
	# Varsayılan KAPALI: yedi kiracının hepsi tanıdık klasik formda kalır,
	# yeni tasarımı isteyen kiracı bunu kendi açar. Bir izin değil, bir tercih.
	"modern_sales_order": False,
	"valuation_guard": False,
}


def desk_access_enabled() -> bool:
	"""True when this site lets non-admins into the classic Frappe Desk.

	Per-site switch, read by middleware/desk_gate.py and api/desk_write_guard.py.
	Tenant variance lives in config, never in code constants — see
	docs/plans/2026-07-18-multitenant-governance.md.
	"""
	try:
		return bool(frappe.db.get_single_value("Stabler Settings", "allow_desk_access"))
	except Exception:
		# Fresh install / mid-migrate: doctype or column not there yet — stay closed.
		return False


def _default_enable_row(company: str) -> dict:
	"""Child-row seed ({company, enable_*}) derived from DEFAULT_MODULE_ENABLED."""
	row = {"company": company}
	row.update({f"enable_{key}": int(val) for key, val in DEFAULT_MODULE_ENABLED.items()})
	return row


def get_company_module_row(company: str):
	"""Return the child row for `company`, creating defaults on demand.

	Defaults all modules to enabled when no explicit row exists yet.
	"""
	if not company or not frappe.db.exists("Company", company):
		return None
	settings = frappe.get_single("Stabler Settings")
	for row in settings.company_modules or []:
		if row.company == company:
			return row
	row = settings.append("company_modules", _default_enable_row(company))
	settings.save(ignore_permissions=True)
	frappe.db.commit()
	return row


def stage_sla_for(company: str) -> dict:
	"""Bu şirketin tender aşama eşikleri, gün. Ayarlanmamışsa varsayılanlar.

	`module_map_for` ile aynı şekil ve aynı sebeple: kiracıya özel olan şey
	config'de yaşar, kodda değil. Fark, dönen değerin bir bayrak değil bir SAYI
	olması — o yüzden "satır yok" ile "satırda 0 var" ayrımı burada korunuyor.

	Satır varsa ama bir aşamanın hücresi boşsa (Frappe Int'i 0 olarak saklar)
	o aşama TAKİPTEN ÇIKMIŞ sayılıyor, varsayılana geri dönmüyor. Yönetici bir
	alanı bilerek sıfırladığında ekranın onu görmezden gelmesi gerekiyor;
	varsayılana düşmek, kapatma niyetini sessizce geri alırdı.
	"""
	from stabler.api._tender_sla import DEFAULT_STAGE_SLA_DAYS

	row = None
	if company:
		try:
			settings = frappe.get_single("Stabler Settings")
			for candidate in settings.get("tender_stage_sla") or []:
				if candidate.company == company:
					row = candidate
					break
		except Exception:
			# Tablo henüz senkronlanmamış olabilir (yama öncesi migrate).
			row = None

	if not row:
		return dict(DEFAULT_STAGE_SLA_DAYS)

	return {stage: int(getattr(row, f"sla_{stage}_days", 0) or 0) for stage in DEFAULT_STAGE_SLA_DAYS}


def imports_supplier_groups_for(company: str) -> list[str]:
	"""Bu şirketin ithalat tedarikçi gruplarını döndürür. Ayarlanmamışsa BOŞ liste.

	`stage_sla_for` ile aynı şekil ve aynı sebeple: hangi grubun "et tedarikçisi",
	hangisinin "nakliyeci" sayıldığı kiracıya göre değişir, o yüzden config'de
	yaşar, kodda değil (bkz. docs/plans/2026-07-18-multitenant-governance.md).

	Boş liste "kısıtlama yok" demektir — satır yoksa, alan boşsa ya da tablo
	henüz senkronlanmamışsa hepsi aynı kapıya çıkar: çağıran hiçbir filtre
	uygulamaz ve ekran bugünkü davranışında kalır. Sessizce boş bir listeye
	düşmek burada güvenli olan taraf; ters yönde bir hata tedarikçi seçiciyi
	boşaltırdı.

	Alan çok satırlı metin: her satırda bir grup adı. JSON listesi de kabul
	edilir (yönetici yapıştırdıysa çalışsın diye).
	"""
	if not company:
		return []

	raw = ""
	try:
		settings = frappe.get_single("Stabler Settings")
		for candidate in settings.get("imports_settings") or []:
			if candidate.company == company:
				raw = (candidate.ci_supplier_groups or "").strip()
				break
	except Exception:
		# Tablo henüz senkronlanmamış olabilir (yama öncesi migrate).
		return []

	if not raw:
		return []

	if raw.startswith("["):
		try:
			parsed = json.loads(raw)
			if isinstance(parsed, list):
				return [str(item).strip() for item in parsed if str(item).strip()]
		except ValueError:
			# Bozuk JSON: satır satır okumaya düş, yönetici öyle yazmış olabilir.
			pass

	return [line.strip() for line in raw.splitlines() if line.strip()]


def imports_transport_supplier_groups_for(company: str) -> list[str]:
	"""Nakliye/hizmet faturası elle bir Ticari Fatura'ya bağlanabilen tedarikçi grupları.

	`imports_supplier_groups_for` ile aynı okuma biçimi (aynı satır, aynı
	try/except, aynı JSON-ya-da-satır ayrıştırma) ama TERS anlam taşır ve bu
	yüzden ayrı bir alan, ayrı bir okuyucu:

	- `ci_supplier_groups` bir SEÇİCİ KISITIDIR — boş liste "kısıt yok" demektir.
	- burası bir YETKİDİR — boş liste "bu şirkette özellik KAPALI" demektir.
	  Hiçbir varsayılan, hiçbir yedek liste yok: ayarlanmamışsa hiçbir fatura
	  elle bağlanamaz. Ters yönde bir varsayılan, keyfî bir borcun ithalat
	  maliyetine iliştirilmesinin önündeki tek engeli kaldırırdı.

	Çağıran tarafın boş listeyi "izin yok" diye okuması şarttır; buradan boş
	dönmek bir hata değil, yapılandırılmamış olmanın normal sonucudur.
	"""
	if not company:
		return []

	raw = ""
	try:
		settings = frappe.get_single("Stabler Settings")
		for candidate in settings.get("imports_settings") or []:
			if candidate.company == company:
				raw = (candidate.get("imports_transport_supplier_groups") or "").strip()
				break
	except Exception:
		# Tablo/alan henüz senkronlanmamış olabilir (yama öncesi migrate).
		return []

	if not raw:
		return []

	if raw.startswith("["):
		try:
			parsed = json.loads(raw)
			if isinstance(parsed, list):
				return [str(item).strip() for item in parsed if str(item).strip()]
		except ValueError:
			# Bozuk JSON: satır satır okumaya düş, yönetici öyle yazmış olabilir.
			pass

	return [line.strip() for line in raw.splitlines() if line.strip()]


def module_map_for(company: str) -> dict:
	row = get_company_module_row(company) if company else None
	if not row:
		return dict(DEFAULT_MODULE_ENABLED)
	return {
		key: bool(getattr(row, f"enable_{key}", int(default)))
		for key, default in DEFAULT_MODULE_ENABLED.items()
	}
