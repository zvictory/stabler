"""Asgari fixture seti — bench-only (entegrasyon) testleri için.

`hooks.py` içinde `before_tests` olarak kayıtlı. Frappe bu hook'u **uygulama
bazlı** okur (`frappe/testing/environment.py:193` → `get_hooks(..., app_name=app)`),
yani `bench run-tests --app stabler` yalnızca stabler'ın hook'unu koşturur.
ERPNext v16 böyle bir hook tanımlamıyor; bu yüzden çıplak bir test sitesinde
hiç Company oluşmuyordu ve 95 testin 54'ü kendi kendini `skipTest` ile atlıyordu
(`make test-bench` yine 0 dönüyordu — boş bir yeşil).

`make test-bench` her modül için bench'i ayrı çağırdığı için bu fonksiyon bir
taramada ~15 kez koşar: her adım idempotent olmak zorunda.
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate, nowdate

BASE_CURRENCY = "UZS"
FX_CURRENCY = "USD"
FX_ACCOUNT = "_Test FX Account"
TEST_COMPANY = "_Test Company"
TEST_ABBR = "_TC"
TEST_SUPPLIER = "_Test Supplier"
TEST_ITEM = "_Test Item"
TEST_UOM = "Nos"


def before_tests() -> None:
	_ensure_base_currency()
	_ensure_company()
	_ensure_fiscal_years()
	_ensure_non_base_account()
	_ensure_price_lists()
	_ensure_supplier()
	_ensure_uom()
	_ensure_item()
	frappe.db.commit()


def _ensure_base_currency() -> None:
	"""Sistem varsayılanını şirketin para birimine çeker.

	Frappe kutudan INR ile gelir. Şirket UZS iken belgeler para birimini
	sistem varsayılanından aldığı için her kayıt "INR → UZS kuru yok"
	diye patlıyordu. Yedi kiracının hepsi UZS tabanlı; test sitesini de
	öyle kuruyoruz ki kur kaydı gerekmesin.
	"""
	frappe.db.set_value("Currency", BASE_CURRENCY, "enabled", 1)
	if frappe.db.get_single_value("Global Defaults", "default_currency") != BASE_CURRENCY:
		frappe.db.set_single_value("Global Defaults", "default_currency", BASE_CURRENCY)
		frappe.db.set_default("currency", BASE_CURRENCY)
		frappe.clear_cache()


def _ensure_company() -> None:
	"""Company + Standard hesap planı + varsayılan depolar.

	Company.on_update hesap planını ve depoları kendisi kurar; testlerin
	aradığı Cash/Bank/Receivable/Income yaprak hesapları ile
	`{company} - {abbr}` depoları buradan gelir. Ayrıca herhangi bir
	Company varsa yenisini kurmuyoruz — testler `get_value("Company", {})`
	ile ilk kaydı alıyor, gerçek bir sitede o zaten doludur.
	"""
	if frappe.db.get_value("Company", {}, "name"):
		return

	frappe.get_doc(
		{
			"doctype": "Company",
			"company_name": TEST_COMPANY,
			"abbr": TEST_ABBR,
			"default_currency": BASE_CURRENCY,
			"country": "Uzbekistan",
			"chart_of_accounts": "Standard",
		}
	).insert(ignore_permissions=True)


def _ensure_fiscal_years() -> None:
	"""Takvim yılı bazlı mali yıllar — geçen, bu ve gelecek yıl.

	Mali yılları normalde kurulum sihirbazı açar; testlerde o hiç koşmaz ve
	her muhasebe kaydı `FiscalYearError` ile düşer. Testler bugünün tarihine
	ve yakın geçmişe/geleceğe kayıt attığı için üç yılı birden açıyoruz.
	Şirket bağlantısı boş bırakıldığında mali yıl tüm şirketlere uygulanır.
	"""
	this_year = getdate(nowdate()).year
	for year in (this_year - 1, this_year, this_year + 1):
		if frappe.db.exists("Fiscal Year", str(year)):
			continue
		frappe.get_doc(
			{
				"doctype": "Fiscal Year",
				"year": str(year),
				"year_start_date": f"{year}-01-01",
				"year_end_date": f"{year}-12-31",
			}
		).insert(ignore_permissions=True)


def _ensure_non_base_account() -> None:
	"""Taban dışı para birimli (USD) bir hesap.

	GL bütünlük taramasının D2 kuralı `account_currency <> default_currency`
	ile çalışır; taban dışı tek bir hesap yoksa o kural hiç sınanamaz.
	Gerçek kiracılarda da durum böyle: UZS tabanlı şirkette USD kasası var.

	Testler şirketi `get_value("Company", {})` ile seçiyor — sıralaması
	garanti değil ve sızıntı bırakan testler sitede fazladan şirket
	bırakabiliyor. Bu yüzden hesabı hangi şirketin seçileceğini tahmin
	etmeye çalışmadan hepsine kuruyoruz.

	`account_type` bilerek boş: Frappe'nin `get_value`'su varsayılan olarak
	`modified desc` sıralar, yani yeni eklenen kayıt her genel aramayı
	kazanır. Tip verilseydi `_leaf_account(company, "Bank")` gibi çağrılar
	testin beklediği standart hesap yerine bu fixture'ı çekerdi.
	"""
	companies = frappe.get_all("Company", fields=["name", "abbr", "default_currency"])
	if not companies:
		return

	frappe.db.set_value("Currency", FX_CURRENCY, "enabled", 1)
	for company in companies:
		if company.default_currency == FX_CURRENCY:
			continue
		if frappe.db.exists("Account", f"{FX_ACCOUNT} - {company.abbr}"):
			continue

		parent = frappe.db.get_value(
			"Account", {"company": company.name, "is_group": 1, "root_type": "Asset"}, "name"
		)
		if not parent:
			continue

		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": FX_ACCOUNT,
				"company": company.name,
				"parent_account": parent,
				"account_currency": FX_CURRENCY,
				"is_group": 0,
			}
		).insert(ignore_permissions=True)


def _ensure_price_lists() -> None:
	"""Standart alış/satış fiyat listeleri.

	Bunları da kurulum sihirbazı açar. Yokken Sales Invoice
	`selling_price_list` / `price_list_currency` / `plc_conversion_rate`
	zorunlu alanlarını dolduramıyor.
	"""
	for name, kind in (("Standard Buying", "buying"), ("Standard Selling", "selling")):
		if frappe.db.exists("Price List", name):
			continue
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": name,
				"currency": BASE_CURRENCY,
				"enabled": 1,
				kind: 1,
			}
		).insert(ignore_permissions=True)


def _ensure_supplier() -> None:
	if frappe.db.exists("Supplier", TEST_SUPPLIER):
		return

	frappe.get_doc(
		{
			"doctype": "Supplier",
			"supplier_name": TEST_SUPPLIER,
			"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
			"supplier_type": "Company",
		}
	).insert(ignore_permissions=True)


def _ensure_uom() -> None:
	"""Test kaleminin ölçü birimi.

	`Nos` ERPNext'in kurulum sihirbazından geliyor; sihirbazın koşmadığı
	ya da UOM kataloğu yerelleştirilmiş bir sitede hiç bulunmuyor (yerel
	test sitesinde ölçüldü: 236 UOM var, `Nos` yok). Eskiden burada
	`get_value(...) or "Nos"` yazıyordu — yedek değer de aynı bulunamayan
	adı verdiği için Item "Could not find Default Unit of Measure: Nos"
	ile patlıyor, `before_tests` düşüyor ve bench testlerinin tamamı
	çalışmadan kalıyordu.
	"""
	if frappe.db.exists("UOM", TEST_UOM):
		return

	frappe.get_doc({"doctype": "UOM", "uom_name": TEST_UOM}).insert(ignore_permissions=True)


def _ensure_item() -> None:
	if frappe.db.exists("Item", TEST_ITEM):
		return

	frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": TEST_ITEM,
			"item_name": TEST_ITEM,
			"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
			"stock_uom": TEST_UOM,
			"is_stock_item": 1,
		}
	).insert(ignore_permissions=True)
