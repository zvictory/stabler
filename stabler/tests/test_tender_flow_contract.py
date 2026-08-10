"""mikas ihale akışının sözleşmesi: ihaleyi aç → lotu aç → ata → belgeyi yükle.

Bu dosya bir regresyon testi değil, bir **karar kaydı**dır. 2026-08-10'da akış
uçtan uca ölçüldü ve şu karar verildi:

    Direktör    ihaleyi (Tender Master) açar ve ihale seviyesindeki zorunlu
                belge listesini orada tanımlar;
                aynı tahtadan lotu açar ve lotu bir sourcing kullanıcısına atar.
    Atama       belge merkezinin başladığı andır.
    Yükleme     satırın `role` alanına göre daralır: `customs` satırını gümrükçü,
                `logistics` satırını lojistikçi, `general`/`finance` satırını
                sourcing yükler; direktör hepsini yükleyebilir.
    Okuma       dört tender görünümüne de açıktır.

Ölçülen mevcut durum bu kararın beş yerinde tutmuyor. Tutmayan her madde
`@unittest.expectedFailure` ile işaretli ve bead id'si docstring'inde. Kasıt
şu: testler **bugün yeşil** (main kırılmaz), ama düzeltme indiği anda
"unexpected success" olarak patlar ve dekoratörün kaldırılmasını zorlar. Karar
ile kod arasındaki fark böylece sessizce yaşayamaz.

  PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_flow_contract -v
"""

from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path

from stabler.api._tender_documents import VALID_DOC_ROLES, default_doc_requirements
from stabler.tests.test_tender_documents import _FakeFrappe

ROOT = Path(__file__).resolve().parents[1]
CRM = (ROOT / "public/js/pages/tender/TenderCrm.vue").read_text(encoding="utf-8")
BOARD = (ROOT / "public/js/pages/tender/TenderMasterBoard.vue").read_text(encoding="utf-8")
DRAWER = (ROOT / "public/js/components/TenderMasterDrawer.vue").read_text(encoding="utf-8")
TENDER_PY = (ROOT / "api/tender.py").read_text(encoding="utf-8")


def _load_api(fake: _FakeFrappe, *, views=("sourcing",), user="sourcer@acme.test"):
	"""`tender_documents`'ı sahte Frappe ile yükler — rol penceresi GERÇEK.

	`test_tender_documents._load_api` `_require_tender_view`'i her zaman geçen bir
	stub'a bağlar; orada test edilen şey belge mantığı, kapı değil. Burada tam
	tersi test ediliyor, o yüzden stub kullanıcının sahip olduğu görünümleri
	bilir: üretim kodu hangi pencereyi *istediğini* seçer, stub yalnız o
	pencerenin açık olup olmadığını söyler. Böylece çağrı yeri değişince test de
	değişir.
	"""
	for name in ("stabler.api.tender_documents", "stabler.api.tender_master"):
		sys.modules.pop(name, None)

	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.PermissionError = PermissionError
	frappe.ValidationError = ValueError
	frappe.DoesNotExistError = LookupError
	frappe.session = types.SimpleNamespace(user=user)
	frappe.response = {}
	frappe.exists = fake.exists
	frappe.get_doc = fake.get_doc
	frappe.db = types.SimpleNamespace(exists=fake.exists)
	frappe.has_permission = lambda _dt, ptype="read", doc=None: True
	frappe.throw = lambda message, exception=ValueError: (_ for _ in ()).throw(exception(message))
	frappe.whitelist = lambda *a, **kw: (
		(a[0] if a and not callable(a[0]) else (lambda fn: fn)) if a else (lambda fn: fn)
	)

	utils = types.ModuleType("frappe.utils")
	utils.now = lambda: "2026-08-10 10:00:00"
	sys.modules["frappe"] = frappe
	sys.modules["frappe.utils"] = utils

	pure = importlib.import_module("stabler.api._tender_documents")

	tender_master_mod = types.ModuleType("stabler.api.tender_master")
	tender_master_mod._assert_company_scope = lambda company=None: company or "ACME"

	def _require_view(view, _company):
		if view not in views:
			raise PermissionError("Not permitted")

	tender_mod = types.ModuleType("stabler.api.tender")
	tender_mod._require_tender = lambda _company=None: None
	tender_mod._require_tender_view = _require_view
	# Karar "dört görünümden herhangi biri" dediği için düzeltmenin çoğul kapıyı
	# kullanması bekleniyor; modül onu import etmeye kalkarsa burada bulsun.
	tender_mod._require_any_tender_view = lambda wanted, _company: (
		None if set(wanted) & set(views) else (_ for _ in ()).throw(PermissionError("Not permitted"))
	)
	sys.modules["stabler.api.tender_master"] = tender_master_mod
	sys.modules["stabler.api.tender"] = tender_mod
	sys.modules["stabler.api._tender_documents"] = pure

	return importlib.import_module("stabler.api.tender_documents")


class TestWhatTheDecisionStandsOn(unittest.TestCase):
	"""Kararın dayandığı, bugün de doğru olan zemin. Bunlar kalıcı yeşil."""

	def test_every_seeded_requirement_carries_the_role_the_write_gate_keys_on(self):
		"""Rol bazlı yazma kapısı ek şema istemiyor: `role` zaten her satırda.

		Şablon satırlarından biri rolsüz doğarsa, o satırı kimin yükleyeceği
		tanımsız kalır ve kapı sessizce "herkes"e döner.
		"""
		for req in default_doc_requirements():
			with self.subTest(key=req["key"]):
				self.assertIn(req["role"], VALID_DOC_ROLES)

	def test_the_tender_is_born_on_the_master_board(self):
		"""Zincirin başı ölçülmüş yer: Level 1 tahtası + Tender Master çekmecesi."""
		self.assertIn("TenderMasterDrawer", BOARD)
		self.assertIn("tender_master.save_tender_master", DRAWER)

	def test_opening_a_master_card_lands_on_the_lot_board(self):
		"""Level 1 → Level 2 geçişi `?tender=` sorgusuyla yapılıyor."""
		self.assertIn('path: "/tender/crm"', BOARD)
		self.assertIn("query: { tender:", BOARD)


class TestWhatTheDecisionStillNeeds(unittest.TestCase):
	"""Karar ile kod arasındaki beş fark. Düzeltme inince dekoratör kalkar."""

	@unittest.expectedFailure
	def test_the_director_authors_the_tender_level_checklist(self):
		"""stabler-vgk.7 — İhale seviyesi belge listesinin hiç UI'ı yok.

		`Tender Master.custom_tender_documents` yalnız `v76` patch'i tarafından
		seed ediliyor; çekmece 9 alan yazıyor ve belge listesi onların arasında
		değil. Liste ihalede tanımlanmazsa her lot kendi listesini uydurur.
		"""
		self.assertIn("custom_tender_documents", DRAWER)

	@unittest.expectedFailure
	def test_the_lot_is_opened_from_the_tender_board(self):
		"""stabler-vgk.8 — Level 2'de lot açma eylemi yok.

		Bugün kullanıcı tender modülünden çıkıp `/crm/deals`'a gidiyor ve lotu
		ihaleye yalnız `tender_no` seçimiyle bağlıyor. Zincir modülün dışına
		çıkıyor; kullanıcı "ihaleyi açtım, lot nerede" diye kalıyor.
		"""
		self.assertIn("save_deal", CRM)

	@unittest.expectedFailure
	def test_the_lot_is_assigned_where_the_lot_is_opened(self):
		"""stabler-vgk.9 — Atama lotun açıldığı ekranda değil.

		`assign_tender` yalnız `DirectorBoard.vue`'da çağrılıyor. Atama belge
		merkezini başlatan olay olduğu için, lotun görüldüğü yerde olmalı.
		"""
		self.assertIn("assign_tender", CRM)

	@unittest.expectedFailure
	def test_a_pure_sourcing_role_can_be_assigned_a_lot(self):
		"""stabler-vgk.10 — Atanabilir kullanıcı listesi sourcing rolünü atlıyor.

		`_TENDER_VIEW_ROLES["sourcing"]` `Stabler Tender Sourcing`'i içeriyor ama
		`tender_managers` yalnız `Sales User`/`Sales Manager` tarıyor: sourcing
		ekranlarını görebilen bir kullanıcı direktörün atama listesinde çıkmıyor.
		"""
		block = TENDER_PY[TENDER_PY.index("def tender_managers(") :][:900]
		self.assertIn("Stabler Tender Sourcing", block)

	@unittest.expectedFailure
	def test_customs_can_read_the_document_center(self):
		"""stabler-vgk.1 — Okuma sourcing'e kilitli; gümrükçü kendi panosundan 403 alıyor.

		`DeclarantQueue.vue:153` kullanıcıyı doğrudan `/tender/documents`'a
		linkliyor ve `_get_deal_and_master` orada `sourcing` istiyor.
		"""
		api = _load_api(_FakeFrappe(), views=("declarant",), user="declarant@acme.test")
		res = api.list_tender_documents(deal="LOT-1", company="ACME")
		self.assertIn("requirements", res)

	@unittest.expectedFailure
	def test_customs_uploads_its_own_customs_row(self):
		"""stabler-vgk.1 — ГТД'yi fiilen gümrükçü alıyor; yükleyebilmeli."""
		fake = _FakeFrappe()
		api = _load_api(fake, views=("declarant",), user="declarant@acme.test")
		res = api.upload_tender_document(
			deal="LOT-1",
			requirement_key="gtd",  # role="customs"
			file_name="gtd_2026.pdf",
			file_url="/private/files/gtd_2026.pdf",
			company="ACME",
		)
		self.assertTrue(res)

	@unittest.expectedFailure
	def test_sourcing_does_not_upload_a_customs_row(self):
		"""stabler-vgk.1 — Yazma satırın rolüne göre daralmalı, tek pencereye değil.

		Bugün sourcing penceresi bütün satırlara yazıyor: rol alanı taşınıyor ama
		hiçbir yerde okunmuyor, yani "kim yükler" sorusunun kodda cevabı yok.
		"""
		api = _load_api(_FakeFrappe(), views=("sourcing",))
		with self.assertRaises(PermissionError):
			api.upload_tender_document(
				deal="LOT-1",
				requirement_key="gtd",  # role="customs"
				file_name="gtd_2026.pdf",
				file_url="/private/files/gtd_2026.pdf",
				company="ACME",
			)


if __name__ == "__main__":
	unittest.main()
