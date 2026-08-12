"""Behaviour contracts for the Tender Document Center (B1 pure logic + B2 API).

The pure-logic layer (``_tender_documents``) needs no Frappe at all, so its
contracts are direct imports. The API layer (``tender_documents``) is loaded
against a fake Frappe double, following the same mock style as
``test_tender_master_api``: a ``_Doc`` that records writes and a ``_FakeFrappe``
that owns the in-memory doctype store.

Covers the derived-completion rules that make the document center honest:
- a file or a waiver satisfies a requirement (K2);
- a hand-set ``done`` with neither is flagged ``unverified`` (K3);
- waiver requires a written justification;
- the two-level merge (tender master + lot) tags scope correctly.
"""

from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))


class _Doc(dict):
	def __getattr__(self, field):
		return self.get(field)

	def __setattr__(self, field, value):
		self[field] = value

	def get(self, field, default=None):
		return super().get(field, default)

	def db_set(self, fieldname, value, **_kwargs):
		# The API persists file/waiver state via db_set; record it so the tests can
		# assert exactly which field was written and with what payload.
		self[fieldname] = value
		self.setdefault("_db_sets", {})[fieldname] = value
		return self


class _FakeFrappe:
	"""Minimal Frappe double backing the document-center API tests."""

	def __init__(self):
		self.docs = {
			("Tender Master", "TND-1"): _Doc(
				name="TND-1",
				company="ACME",
				custom_tender_documents=json.dumps(
					[
						{
							"key": "master_cert",
							"label": "Tender cert",
							"required": True,
							"scope": "tender",
							"role": "general",
						},
					]
				),
			),
			("CRM Deal", "LOT-1"): _Doc(
				name="LOT-1",
				company="ACME",
				custom_parent_tender="TND-1",
				custom_tender_intake=json.dumps(
					{
						"documents": [
							{
								"key": "gtd",
								"label": "ГТД",
								"required": True,
								"scope": "lot",
								"role": "customs",
							},
							{
								"key": "invoice",
								"label": "Invoys",
								"required": True,
								"scope": "lot",
								"role": "finance",
							},
						],
					}
				),
			),
		}

		# File rows the fake site owns; uploads are validated against these.
		self.file_urls = {
			"/private/files/gtd_2026.pdf",
			"/private/files/tnd_cert.pdf",
			"/files/x.pdf",
			"/files/a.pdf",
			"/files/b.pdf",
			"/files/only.pdf",
			"/files/inv.pdf",
			"/files/c.pdf",
		}

	def exists(self, doctype, name):
		if isinstance(name, dict):  # File lookup by filters
			return name.get("file_url") in self.file_urls
		return (doctype, name) in self.docs

	def get_doc(self, doctype, name):
		return self.docs[(doctype, name)]


class TestParseDocRequirements(unittest.TestCase):
	"""Pure-logic contracts for parse_doc_requirements (single source of truth)."""

	def test_empty_inputs_return_empty_list(self):
		from stabler.api._tender_documents import parse_doc_requirements

		for raw in (None, [], "", "not json", {}):
			with self.subTest(raw=raw):
				self.assertEqual(parse_doc_requirements(raw), [])

	def test_file_satisfies_requirement(self):
		from stabler.api._tender_documents import parse_doc_requirements

		res = parse_doc_requirements(
			[
				{
					"key": "gtd",
					"label": "ГТД",
					"required": True,
					"files": [{"file_name": "gtd.pdf", "file_url": "/files/gtd.pdf"}],
				},
			]
		)
		self.assertTrue(res[0]["done"])
		self.assertFalse(res[0]["unverified"])
		self.assertEqual(res[0]["file_count"], 1)
		self.assertEqual(res[0]["latest_file"]["file_name"], "gtd.pdf")

	def test_waiver_satisfies_requirement(self):
		from stabler.api._tender_documents import parse_doc_requirements

		res = parse_doc_requirements(
			[
				{
					"key": "cert",
					"label": "Cert",
					"required": True,
					"waiver_reason": "alt doc",
					"waived_by": "u@x",
				},
			]
		)
		self.assertTrue(res[0]["done"])
		self.assertFalse(res[0]["unverified"])
		self.assertEqual(res[0]["waiver_reason"], "alt doc")
		self.assertEqual(res[0]["waived_by"], "u@x")

	def test_legacy_done_without_file_is_unverified(self):
		from stabler.api._tender_documents import parse_doc_requirements

		res = parse_doc_requirements([{"key": "old", "label": "Old", "required": True, "done": True}])
		self.assertFalse(res[0]["done"])  # derived done is False (no file/waiver)
		self.assertTrue(res[0]["unverified"])  # but the legacy flag is surfaced

	def test_legacy_name_status_rows_survive_parsing(self):
		"""Pre-document-center intake rows are `[{name, status}]`.

		Without the `name` fallback every one of them fails the `if not label`
		guard, so an existing tender's whole checklist parses to zero
		requirements and the document center silently shows nothing to do.
		"""
		from stabler.api._tender_documents import parse_doc_requirements

		res = parse_doc_requirements(
			[
				{"name": "Texnik spetsifikatsiya", "status": "ready"},
				{"name": "Narx taklifi", "status": "pending"},
			]
		)
		self.assertEqual(len(res), 2)
		self.assertEqual(res[0]["label"], "Texnik spetsifikatsiya")
		self.assertEqual(res[0]["key"], "texnik_spetsifikatsiya")
		# `ready` is a hand-tick with nothing attached — same standing as the
		# legacy `done` flag, so it may surface as unverified but must never
		# satisfy the ready-gate on its own.
		self.assertFalse(res[0]["done"])
		self.assertTrue(res[0]["unverified"])
		self.assertFalse(res[1]["done"])
		self.assertFalse(res[1]["unverified"])

	def test_key_derived_from_label_and_slugged(self):
		from stabler.api._tender_documents import parse_doc_requirements

		res = parse_doc_requirements([{"label": "Packing List"}])
		self.assertEqual(res[0]["key"], "packing_list")

	def test_scope_and_role_defaults_and_clamping(self):
		from stabler.api._tender_documents import VALID_DOC_ROLES, parse_doc_requirements

		res = parse_doc_requirements([{"label": "X", "scope": "bogus", "role": "bogus"}])
		self.assertEqual(res[0]["scope"], "lot")  # unknown scope → lot
		self.assertEqual(res[0]["role"], "general")  # unknown role → general
		self.assertIn("general", VALID_DOC_ROLES)

	def test_date_backported_into_shape(self):
		from stabler.api._tender_documents import parse_doc_requirements

		res = parse_doc_requirements([{"label": "X", "date": "2026-08-05"}])
		self.assertEqual(res[0]["date"], "2026-08-05")


class TestDocsSummary(unittest.TestCase):
	def test_readiness_zero_when_nothing_satisfied(self):
		from stabler.api._tender_documents import default_doc_requirements, docs_summary

		summary = docs_summary(default_doc_requirements())
		self.assertEqual(summary["done_required"], 0)
		self.assertEqual(summary["readiness_pct"], 0)
		self.assertGreater(summary["required"], 0)
		self.assertEqual(len(summary["missing"]), summary["required"])

	def test_role_filter_scopes_summary(self):
		from stabler.api._tender_documents import default_doc_requirements, docs_summary

		reqs = default_doc_requirements()
		customs = docs_summary(reqs, role="customs")
		self.assertEqual(customs["total"], 2)  # gtd + origin_cert
		self.assertEqual(customs["required"], 1)  # only gtd required

	def test_unverified_counted(self):
		from stabler.api._tender_documents import docs_summary, parse_doc_requirements

		reqs = parse_doc_requirements(
			[
				{"key": "a", "label": "A", "required": True, "done": True},  # unverified
				{"key": "b", "label": "B", "required": True, "files": [{"file_url": "/x"}]},
			]
		)
		summary = docs_summary(reqs)
		self.assertEqual(summary["unverified"], 1)
		self.assertEqual(summary["done_required"], 1)  # only b is truly done


class TestDefaultDocRequirements(unittest.TestCase):
	def test_seeds_seven_with_explicit_roles(self):
		from stabler.api._tender_documents import default_doc_requirements

		reqs = default_doc_requirements()
		keys = {r["key"] for r in reqs}
		self.assertEqual(
			keys, {"gtd", "origin_cert", "cmr", "packing_list", "invoice", "tech_spec", "price_offer"}
		)
		roles = {r["role"] for r in reqs}
		self.assertIn("customs", roles)
		self.assertIn("logistics", roles)
		self.assertIn("finance", roles)


def _load_api(fake: _FakeFrappe):
	"""Load tender_documents.py against a fake Frappe (no bench required)."""
	for name in ("stabler.api.tender_documents", "stabler.api.tender_master"):
		sys.modules.pop(name, None)

	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.PermissionError = PermissionError
	frappe.ValidationError = ValueError
	frappe.DoesNotExistError = LookupError
	frappe.session = types.SimpleNamespace(user="sourcer@acme.test")
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
	utils.now = lambda: "2026-08-06 10:00:00"
	sys.modules["frappe"] = frappe
	sys.modules["frappe.utils"] = utils

	# _tender_documents is pure Python — pre-load it so the API module imports it
	# from sys.modules without re-triggering the package __init__ frappe path.
	import importlib

	pure = importlib.import_module("stabler.api._tender_documents")

	# tender_master exposes _assert_company_scope (the canonical str-returning
	# wrapper); tender exposes the two role/module gates the API imports.
	tender_master_mod = types.ModuleType("stabler.api.tender_master")
	tender_master_mod._assert_company_scope = lambda company=None: company or "ACME"
	tender_mod = types.ModuleType("stabler.api.tender")
	tender_mod._require_tender = lambda _company=None: None
	tender_mod._require_tender_view = lambda _view, _company: None
	tender_mod._require_any_tender_view = lambda _views, _company: None
	tender_mod._deal_label = lambda deal: deal
	tender_mod._tender_deal_names = lambda company: set()
	sys.modules["stabler.api.tender_master"] = tender_master_mod
	sys.modules["stabler.api.tender"] = tender_mod
	sys.modules["stabler.api._tender_documents"] = pure

	return importlib.import_module("stabler.api.tender_documents")


class TestTenderDocumentsApi(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def test_list_merges_tender_master_and_lot_with_scope(self):
		res = self.api.list_tender_documents(deal="LOT-1", company="ACME")
		scopes = {r["key"]: r["scope"] for r in res["requirements"]}
		self.assertEqual(scopes["master_cert"], "tender")
		self.assertEqual(scopes["gtd"], "lot")
		self.assertIn("summary", res)
		self.assertEqual(res["tender_master"], "TND-1")

	def test_upload_to_lot_requirement_attaches_file_and_marks_done(self):
		res = self.api.upload_tender_document(
			deal="LOT-1",
			requirement_key="gtd",
			file_name="gtd_2026.pdf",
			file_url="/private/files/gtd_2026.pdf",
			company="ACME",
		)
		gtd = next(r for r in res["requirements"] if r["key"] == "gtd")
		self.assertTrue(gtd["done"])
		self.assertFalse(gtd["unverified"])
		self.assertEqual(gtd["latest_file"]["file_name"], "gtd_2026.pdf")
		self.assertEqual(gtd["latest_file"]["uploaded_by"], "sourcer@acme.test")
		# The lot payload was persisted via db_set on the CRM Deal.
		deal = self.fake.docs[("CRM Deal", "LOT-1")]
		self.assertIn("custom_tender_intake", deal.get("_db_sets", {}))

	def test_upload_to_tender_master_requirement_persists_on_master(self):
		res = self.api.upload_tender_document(
			deal="LOT-1",
			requirement_key="master_cert",
			file_name="tnd_cert.pdf",
			file_url="/private/files/tnd_cert.pdf",
			company="ACME",
		)
		mc = next(r for r in res["requirements"] if r["key"] == "master_cert")
		self.assertTrue(mc["done"])
		master = self.fake.docs[("Tender Master", "TND-1")]
		self.assertIn("custom_tender_documents", master.get("_db_sets", {}))

	def test_upload_unknown_requirement_raises(self):
		with self.assertRaises(LookupError):
			self.api.upload_tender_document(
				deal="LOT-1",
				requirement_key="nope",
				file_name="x.pdf",
				file_url="/files/x.pdf",
				company="ACME",
			)

	def test_upload_missing_file_fields_raises(self):
		with self.assertRaises(ValueError):
			self.api.upload_tender_document(
				deal="LOT-1",
				requirement_key="gtd",
				file_name="",
				file_url="",
				company="ACME",
			)

	def test_upload_rejects_non_local_file_url(self):
		"""Only site-local file paths may be stored.

		The stored URL is later fed to the download endpoint's redirect, so an
		external, protocol-relative or traversing value would make the trusted
		site origin bounce users to an attacker's page (phishing / referrer leak).
		"""
		for bad in (
			"https://evil.example/x.pdf",
			"//evil.example/x.pdf",
			"/files/../../etc/passwd",
			"/etc/passwd",
			"/files/x.pdf\r\nLocation: https://evil.example",
		):
			with self.subTest(file_url=bad), self.assertRaises(ValueError):
				self.api.upload_tender_document(
					deal="LOT-1",
					requirement_key="gtd",
					file_name="x.pdf",
					file_url=bad,
					company="ACME",
				)

	def test_upload_rejects_url_with_no_file_record(self):
		with self.assertRaises(ValueError):
			self.api.upload_tender_document(
				deal="LOT-1",
				requirement_key="gtd",
				file_name="ghost.pdf",
				file_url="/files/ghost.pdf",
				company="ACME",
			)

	def test_download_refuses_legacy_external_url(self):
		"""Rows written before the upload-side check must not redirect off-site."""
		deal = self.fake.docs[("CRM Deal", "LOT-1")]
		deal["custom_tender_intake"] = json.dumps(
			{
				"documents": [
					{
						"key": "gtd",
						"label": "ГТД",
						"required": True,
						"scope": "lot",
						"role": "customs",
						"files": [{"file_name": "x.pdf", "file_url": "https://evil.example/x.pdf"}],
					},
				]
			}
		)
		with self.assertRaises(ValueError):
			self.api.download_tender_document(
				deal="LOT-1",
				requirement_key="gtd",
				file_url="https://evil.example/x.pdf",
				company="ACME",
			)

	def test_download_redirects_to_local_file(self):
		self.api.upload_tender_document(
			deal="LOT-1",
			requirement_key="gtd",
			file_name="gtd_2026.pdf",
			file_url="/private/files/gtd_2026.pdf",
			company="ACME",
		)
		self.api.download_tender_document(
			deal="LOT-1",
			requirement_key="gtd",
			file_url="/private/files/gtd_2026.pdf",
			company="ACME",
		)
		import frappe as fake_frappe

		self.assertEqual(fake_frappe.response["type"], "redirect")
		self.assertEqual(fake_frappe.response["location"], "/private/files/gtd_2026.pdf")

	def test_waive_sets_reason_and_actor(self):
		res = self.api.waive_tender_document(
			deal="LOT-1",
			requirement_key="invoice",
			reason="Digital copy acceptable",
			company="ACME",
		)
		inv = next(r for r in res["requirements"] if r["key"] == "invoice")
		self.assertTrue(inv["done"])
		self.assertEqual(inv["waiver_reason"], "Digital copy acceptable")
		self.assertEqual(inv["waived_by"], "sourcer@acme.test")

	def test_waive_requires_reason(self):
		with self.assertRaises(ValueError):
			self.api.waive_tender_document(
				deal="LOT-1", requirement_key="invoice", reason="  ", company="ACME"
			)

	def test_download_unknown_requirement_raises(self):
		with self.assertRaises(LookupError):
			self.api.download_tender_document(
				deal="LOT-1", requirement_key="nope", file_url="/files/x.pdf", company="ACME"
			)

	def test_remove_specific_file_keeps_others_and_stays_done(self):
		# Seed two files on the gtd requirement, then remove just one.
		self.api.upload_tender_document(
			deal="LOT-1", requirement_key="gtd", file_name="a.pdf", file_url="/files/a.pdf", company="ACME"
		)
		self.api.upload_tender_document(
			deal="LOT-1", requirement_key="gtd", file_name="b.pdf", file_url="/files/b.pdf", company="ACME"
		)
		res = self.api.remove_tender_document(
			deal="LOT-1", requirement_key="gtd", file_url="/files/a.pdf", company="ACME"
		)
		gtd = next(r for r in res["requirements"] if r["key"] == "gtd")
		self.assertEqual(gtd["file_count"], 1)
		self.assertEqual(gtd["latest_file"]["file_url"], "/files/b.pdf")
		self.assertTrue(gtd["done"])  # still satisfied by the remaining file

	def test_remove_last_file_reopens_requirement(self):
		self.api.upload_tender_document(
			deal="LOT-1",
			requirement_key="gtd",
			file_name="only.pdf",
			file_url="/files/only.pdf",
			company="ACME",
		)
		res = self.api.remove_tender_document(
			deal="LOT-1", requirement_key="gtd", file_url="/files/only.pdf", company="ACME"
		)
		gtd = next(r for r in res["requirements"] if r["key"] == "gtd")
		self.assertEqual(gtd["file_count"], 0)
		self.assertFalse(gtd["done"])  # reopened — no satisfied-looking empty slot
		self.assertFalse(gtd["unverified"])  # never silently re-stick the legacy flag

	def test_remove_all_files_when_no_url_given(self):
		self.api.upload_tender_document(
			deal="LOT-1", requirement_key="gtd", file_name="a.pdf", file_url="/files/a.pdf", company="ACME"
		)
		self.api.upload_tender_document(
			deal="LOT-1", requirement_key="gtd", file_name="b.pdf", file_url="/files/b.pdf", company="ACME"
		)
		res = self.api.remove_tender_document(deal="LOT-1", requirement_key="gtd", company="ACME")
		gtd = next(r for r in res["requirements"] if r["key"] == "gtd")
		self.assertEqual(gtd["file_count"], 0)
		self.assertFalse(gtd["done"])

	def test_remove_preserves_waiver_so_stays_done(self):
		# Waive first, then attach + remove a file: the waiver should still satisfy.
		self.api.waive_tender_document(
			deal="LOT-1", requirement_key="invoice", reason="digital ok", company="ACME"
		)
		self.api.upload_tender_document(
			deal="LOT-1",
			requirement_key="invoice",
			file_name="inv.pdf",
			file_url="/files/inv.pdf",
			company="ACME",
		)
		res = self.api.remove_tender_document(
			deal="LOT-1", requirement_key="invoice", file_url="/files/inv.pdf", company="ACME"
		)
		inv = next(r for r in res["requirements"] if r["key"] == "invoice")
		self.assertEqual(inv["file_count"], 0)
		self.assertTrue(inv["done"])  # waiver still satisfies it
		self.assertEqual(inv["waiver_reason"], "digital ok")

	def test_remove_unknown_requirement_raises(self):
		with self.assertRaises(LookupError):
			self.api.remove_tender_document(deal="LOT-1", requirement_key="nope", company="ACME")

	def test_master_wins_when_key_exists_on_both_layers(self):
		"""A key present on both Tender Master and lot resolves to the master layer.

		This documents the original design (master-precedence): when the same slug
		appears on both the parent tender and the lot, the master owns it. If this
		precedence is ever flipped to lot-priority, this test fails as a tripwire —
		the change must be deliberate, because the two-level merge in
		list_tender_documents dedupes on key too.
		"""
		# master_cert is defined on the Tender Master; upload by that key must land there.
		self.api.upload_tender_document(
			deal="LOT-1",
			requirement_key="master_cert",
			file_name="c.pdf",
			file_url="/files/c.pdf",
			company="ACME",
		)
		master = self.fake.docs[("Tender Master", "TND-1")]
		deal = self.fake.docs[("CRM Deal", "LOT-1")]
		self.assertIn("custom_tender_documents", master.get("_db_sets", {}))
		self.assertNotIn("custom_tender_intake", deal.get("_db_sets", {}))


class TestCompanyModuleGuards(unittest.TestCase):
	def test_get_company_module_row_checks_company_exists(self):
		"""get_company_module_row must check frappe.db.exists before saving to prevent LinkValidationError."""
		import os

		path = os.path.join(
			os.path.dirname(__file__),
			"..",
			"stabler",
			"doctype",
			"stabler_settings",
			"stabler_settings.py",
		)
		with open(path, encoding="utf-8") as f:
			source = f.read()

		self.assertIn('if not company or not frappe.db.exists("Company", company):', source)


if __name__ == "__main__":
	unittest.main()
