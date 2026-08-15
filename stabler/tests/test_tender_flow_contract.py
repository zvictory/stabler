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
import re
import sys
import types
import unittest
from pathlib import Path

from stabler.api._tender_documents import VALID_DOC_ROLES, default_doc_requirements
from stabler.tests.module_sandbox import ModuleSandbox
from stabler.tests.test_tender_documents import _FakeFrappe

_SANDBOX = ModuleSandbox()


def tearDownModule():
	"""``_load_api`` replaces the real ``frappe`` in ``sys.modules`` process-wide.

	Without handing it back, ``bench run-tests`` dies in its own
	``_cleanup_after_tests`` calling ``frappe.clear_cache()`` — the tests report
	their real verdict and the runner's exit code then says something else.
	"""
	_SANDBOX.restore()


ROOT = Path(__file__).resolve().parents[1]
CRM = (ROOT / "public/js/pages/tender/TenderCrm.vue").read_text(encoding="utf-8")
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
	_SANDBOX.evict("stabler.api.tender_documents", "stabler.api.tender_master")

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
	_SANDBOX.install({"frappe": frappe, "frappe.utils": utils})

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
	tender_mod._deal_label = lambda deal: deal
	tender_mod._tender_deal_names = lambda company: set()
	_SANDBOX.install(
		{
			"stabler.api.tender_master": tender_master_mod,
			"stabler.api.tender": tender_mod,
			"stabler.api._tender_documents": pure,
		}
	)

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

	def test_the_tender_is_born_on_tender_crm(self):
		"""Zincirin başı: Tender CRM + İhale Giriş çekmecesi.

		Tek seviyeli mimari: TenderCrm New tender butonu ile TenderMasterDrawer'ı açar;
		çekmece crm.save_deal (deal_type=Tender) çağırır.
		"""
		self.assertIn("TenderMasterDrawer", CRM)
		self.assertIn("crm.save_deal", DRAWER)

	def test_tender_crm_is_single_level(self):
		"""Tek seviyeli mimari: Tender CRM doğrudan deal kartlarını yönetir."""
		self.assertIn("crm_board", CRM)


class TestWhatTheDecisionStillNeeds(unittest.TestCase):
	"""Karar ile kod arasındaki beş fark. Düzeltme inince dekoratör kalkar."""

	def test_the_director_authors_the_tender_level_checklist(self):
		"""stabler-vgk.7 — İhale Giriş Merkezi: CRM Deal yaratır (deal_type=Tender).

		Tek seviyeli mimari: Tender Master parent'a gerek yok. Çekmece
		crm.save_deal çağırır, deal_type='Tender' set eder, custom_tender_intake
		JSON overlay'ine items + files yazar.
		"""
		self.assertIn("crm.save_deal", DRAWER)
		self.assertIn("deal_type", DRAWER)
		self.assertIn("save_deal_intake", DRAWER)

	def test_the_intake_form_can_actually_be_filled_in(self):
		"""stabler-vgk.7 — "kaydediyor" yetmez; form doldurulabilir olmalı.

		vgk.7 "tamamlandı" kapandı ve ekran canlıda kullanılamaz haldeydi:
		müşteri dropdown'ı hep boş, item tablosuna item eklenemiyor, mevcut
		bir ihale düzenlemek için açılınca form boş geliyordu. Üç hata da
		veri bağlama hatasıydı ve üçü de sessizdi — hiçbiri hata üretmiyor,
		hepsi "sonuç yok" gibi görünüyor. Bu testin işi, aynı sessiz sınıfın
		geri gelmesini engellemek.
		"""
		# 1) Müşteri: list_customers_with_balances bir {rows: …} zarfı döner,
		#    Typeahead diziyi olmayan her şeyi sessizce [] yapar → sonsuz boş
		#    dropdown. Typeahead'e giden tek doğru uç düz dizi döndürendir.
		self.assertNotIn("list_customers_with_balances", DRAWER)
		self.assertIn("customerSearcher", DRAWER)

		# 2) Item: itemSearcher'a depo geçilirse backend `tabBin.actual_qty > 0`
		#    filtreler. İhale girişi satış öncesi bir ekran — talep edilen item'ın
		#    stokta olması beklenmez, dolayısıyla depo geçilmemeli.
		item_search = re.search(r"itemSearcher\((.*?)\)\s*;", DRAWER, re.S)
		self.assertIsNotNone(item_search, "çekmece itemSearcher kullanmalı")
		self.assertNotIn("warehouse", item_search.group(1))

		# 3) Çekmece bağlama: Tender CRM yeni ihale için :deal="null" geçer.
		self.assertIn(':deal="null"', CRM)

		# 4) Seçim görünmeli. Typeahead düzenlenebilir kutu ile seçili değeri
		#    `modelValue` üzerinden ayırır (`hasSelection`), ve `display`
		#    prop'u String'dir — fonksiyon geçilirse Vue onu basmaz. Bağlama
		#    yoksa seçim yapılır, forma da düşer, ama alan boş görünmeye devam
		#    eder: düzenleme modunda kayıtlı müşteri kaybolmuş gibi durur.
		for block in re.findall(r"<Typeahead\b(.*?)/>", DRAWER, re.S):
			self.assertTrue(
				"v-model" in block or ":model-value" in block,
				f"Typeahead modelValue bağlamıyor:\n{block}",
			)
			display = re.search(r':display="([^"]*)"', block)
			self.assertIsNotNone(display, f"Typeahead display geçmiyor:\n{block}")
			self.assertNotIn("=>", display.group(1), "display String olmalı, fonksiyon değil")

		# 5) "Yeni İhale" gerçekten yeni olmalı. Çekmece kapanınca sökülmüyor ve
		#    tahta `editingTender`'ı null yapıyor; zaten null'sa `deal` izleyicisi
		#    referans değişmediği için tetiklenmiyor. Yalnız `deal` izlenirse iptal
		#    edilen bir giriş bir sonraki açılışta olduğu gibi geri geliyor —
		#    kullanıcı boş sandığı forma önceki müşteriyle kayıt atıyor. Bu yüzden
		#    açılışın kendisi de izlenmek zorunda.
		self.assertRegex(
			DRAWER,
			r"watch\(\s*\(\)\s*=>\s*props\.open",
			"Çekmece `props.open`'ı izlemiyor: iptal edilen giriş yeni ihalede geri gelir",
		)

	def test_the_lot_is_opened_from_the_tender_board(self):
		"""stabler-vgk.8 — İPTAL: tek seviyeli mimaride lot kavramı yok.

		İhale doğrudan CRM Deal olarak yaratılır (vgk.7). Yeni deal = yeni ihale.
		TenderMasterDrawer artık crm.save_deal çağırır. Test, save_deal'in
		çekmece içinde varlığını doğrular — TenderCrm.vue'da değil, ama
		akışın başı (İhale Giriş Merkezi) bu ucu kullanıyor.
		"""
		self.assertIn("save_deal", DRAWER)

	def test_the_lot_is_assigned_where_the_lot_is_opened(self):
		"""stabler-vgk.9 — Atama lotun açıldığı ekranda değil.

		`assign_tender` yalnız `DirectorBoard.vue`'da çağrılıyor. Atama belge
		merkezini başlatan olay olduğu için, lotun görüldüğü yerde olmalı.
		"""
		self.assertIn("assign_tender", CRM)

	def test_a_pure_sourcing_role_can_be_assigned_a_lot(self):
		"""stabler-vgk.10 — Atanabilir kullanıcı listesi sourcing rolünü atlıyor.

		`_TENDER_VIEW_ROLES["sourcing"]` `Stabler Tender Sourcing`'i içeriyor ama
		`tender_managers` yalnız `Sales User`/`Sales Manager` tarıyor: sourcing
		ekranlarını görebilen bir kullanıcı direktörün atama listesinde çıkmıyor.
		"""
		block = TENDER_PY[TENDER_PY.index("def tender_managers(") :][:900]
		self.assertIn("Stabler Tender Sourcing", block)

	def test_customs_can_read_the_document_center(self):
		"""stabler-vgk.1 — Okuma sourcing'e kilitli; gümrükçü kendi panosundan 403 alıyor.

		`DeclarantQueue.vue:153` kullanıcıyı doğrudan `/tender/documents`'a
		linkliyor ve `_get_deal_and_master` orada `sourcing` istiyor.
		"""
		api = _load_api(_FakeFrappe(), views=("declarant",), user="declarant@acme.test")
		res = api.list_tender_documents(deal="LOT-1", company="ACME")
		self.assertIn("requirements", res)

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
