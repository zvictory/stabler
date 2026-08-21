"""Behaviour contract for the tender master fields inside the intake JSON.

`TenderMasterDrawer.vue` sends seven header fields — `title`, `tender_no`,
`source`, `publication_date`, `submission_deadline`, `currency`,
`estimated_total` — inside `intakePayload` to `save_deal_intake`. Until this
module existed, `_clean_intake` rebuilt the stored JSON from `_INTAKE_KEYS_STR`
/ `_INTAKE_KEYS_NUM` alone, and neither whitelist named any of the seven: they
were silently discarded on every save.

`title` is the sharp edge. It is not a real `CRM Deal` field (`save_deal`'s
`_DEAL_MUTABLE_FIELDS` does not carry it — see `stabler/api/crm.py:79`), so the
intake JSON is its *only* storage. `TenderMasterDrawer.vue:147` seeds the form
from `val.organization` before the intake read-back arrives, and only
overwrites it when `intake.title` is truthy (`:166`). So a dropped `title` key
does not read back empty and obviously wrong — it reads back as the customer's
name, sitting quietly in a required field, and a save from that state persists
the customer's name over the real title forever. Proven on production mikas
2026-08-15: `docs/uat/evidence/2026-08-15-tender-crud-uat/README.md`.

`_clean_intake` needs `frappe.utils.now()` (bound to `frappe.local`, which a
site-free process never binds) for its document-audit stamp, unrelated to
anything this module exercises. Rather than fake the whole `frappe` package,
each test patches only `tender.now` — the name `tender.py` itself bound via
`from frappe.utils import ... now ...` — and restores it in `tearDown`, the
same discipline `ModuleSandbox` exists for elsewhere in this suite: a leaked
patch would only surface under `make test`'s single-process re-run, not here.
`frappe.session.user` is sidestepped instead of patched, via the
`audit_actor` parameter `_clean_intake` already accepts for trusted callers
(see `set_tender_go_no_go_from_trusted_source`).

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_intake_master_fields -v
"""

from __future__ import annotations

import json
import unittest

import stabler.api.tender as tender

_ACTOR = "test@example.com"
_NOW = "2026-08-10 10:00:00"

_MASTER_FIELDS = {
	"title": "ЁЖ-2026 темиз йўл лоти",
	"tender_no": "TN-2026-00042",
	"source": "UZEX",
	"publication_date": "2026-08-01",
	"submission_deadline": "2026-08-20",
	"currency": "USD",
	"estimated_total": "15000.50",
}


def _round_trip(payload: dict, prior: dict | None = None) -> dict:
	"""`_clean_intake` then the exact JSON round trip `save_deal_intake` /
	`deal_intake` perform via `frappe.db.set_value` + `_parse_intake`."""
	cleaned = tender._clean_intake(payload, prior or {}, audit_actor=_ACTOR)
	stored = json.dumps(cleaned, ensure_ascii=False)
	return tender._parse_intake(stored)


class TestTenderMasterFieldsSurviveTheIntakeRoundTrip(unittest.TestCase):
	def setUp(self):
		self._orig_now = tender.now
		tender.now = lambda: _NOW

	def tearDown(self):
		tender.now = self._orig_now

	def test_all_seven_master_fields_survive_clean_store_and_reload(self):
		"""The whitelist regression this module exists to catch.

		Every key `TenderMasterDrawer.vue` sends alongside the lot-level
		fields must come back unchanged. Before the fix this dict comes back
		missing all seven keys outright (not empty — absent)."""
		out = _round_trip(dict(_MASTER_FIELDS, lot_no="LOT-1"))
		for key, value in _MASTER_FIELDS.items():
			with self.subTest(key=key):
				if key == "estimated_total":
					self.assertEqual(out[key], 15000.5)
				else:
					self.assertEqual(out[key], value)
		# The pre-existing whitelist must still work unmodified.
		self.assertEqual(out["lot_no"], "LOT-1")

	def test_title_is_preserved_verbatim_it_has_no_other_home(self):
		"""`title` is not a `CRM Deal` field (`crm.py::_DEAL_MUTABLE_FIELDS`
		does not carry it) — the intake JSON is the only place it is ever
		stored. Losing this key does not just blank the field on reload, it
		makes the true title unrecoverable."""
		out = _round_trip({"title": "Real Tender Title", "lot_no": "L1"})
		self.assertEqual(out["title"], "Real Tender Title")

	def test_estimated_total_is_cleaned_as_a_number_not_a_string(self):
		"""Belongs in `_INTAKE_KEYS_NUM`: a currency amount, like `won_price`.

		Landing it in `_INTAKE_KEYS_STR` instead would not lose the value, but
		it would silently change its type on every read — any caller doing
		arithmetic on it (as `_fx_summary` does for the sibling `fx_amount`
		key) would break the moment this field carried a real number."""
		out = _round_trip({"estimated_total": "2500.75"})
		self.assertIsInstance(out["estimated_total"], float)
		self.assertEqual(out["estimated_total"], 2500.75)

	def test_dates_are_preserved_as_iso_strings_not_coerced_to_zero(self):
		"""`publication_date` / `submission_deadline` belong in
		`_INTAKE_KEYS_STR`, matching the existing `bid_deadline` /
		`delivery_deadline` / `guarantee_return` date keys. `_INTAKE_KEYS_NUM`
		runs `_num()` (`float(v)`) on every key it owns — an ISO date string
		is not a valid float, so a date key placed there would silently
		become `0.0` on every save instead of raising."""
		out = _round_trip({"publication_date": "2026-08-01", "submission_deadline": "2026-08-20"})
		self.assertEqual(out["publication_date"], "2026-08-01")
		self.assertEqual(out["submission_deadline"], "2026-08-20")

	def test_absent_master_fields_default_to_empty_not_an_error(self):
		"""A payload that predates this fix (or a caller that never touches
		these fields, like `set_tender_go_no_go_from_trusted_source`) must
		still clean without raising."""
		out = _round_trip({"lot_no": "LOT-1"})
		for key in ("title", "tender_no", "source", "publication_date", "submission_deadline", "currency"):
			with self.subTest(key=key):
				self.assertEqual(out[key], "")
		self.assertEqual(out["estimated_total"], 0.0)

	def test_an_edit_does_not_erase_a_previously_saved_title(self):
		"""The real failure sequence: create with a title, then an unrelated
		intake edit (e.g. a lot-level field) must not wipe it out."""
		first = _round_trip(dict(_MASTER_FIELDS, lot_no="LOT-1"))
		second = _round_trip({**_MASTER_FIELDS, "lot_no": "LOT-1-updated"}, prior=first)
		self.assertEqual(second["title"], _MASTER_FIELDS["title"])
		self.assertEqual(second["lot_no"], "LOT-1-updated")


if __name__ == "__main__":
	unittest.main()
