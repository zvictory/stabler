"""Regression guard for the Custom DocPerm shadowing incident (2026-08-03/04).

WHY this matters, not just what it does:

In Frappe, a single row in ``tabCustom DocPerm`` for a doctype makes that
doctype's ENTIRE standard ``tabDocPerm`` set inert. So inserting one permission
row "to grant a new role access" silently REVOKES every standard role's access to
that doctype. That is how ordinary users lost `read` on Customer/Item and
`report` on GL Entry on prod — no code changed, only a permission row appeared.

The invariant these tests encode: **whenever a doctype carries Custom DocPerm
rows, every (role, permlevel) pair that the standard set grants read or report
must also be present in the custom set** — otherwise those roles lose access
without anyone editing them.

They also pin the two defects of the previous ad-hoc repair helper:
  * it matched on ``role`` only, so permlevel-1 rows were never restored;
  * it mutated permission tables from an unauthenticated whitelisted endpoint.

The tests are pure unit tests over synthetic permission rows — the DB accessors
are patched out, so no site fixtures are required.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import frappe

from stabler.api import permissions as perm

# Flag columns used by the fixtures; the real list is derived from meta.
_FLAGS = ["read", "report", "select", "write"]


def _row(role, permlevel=0, read=1, report=0, select=1, write=0):
	return frappe._dict(
		role=role,
		permlevel=permlevel,
		read=read,
		report=report,
		select=select,
		write=write,
	)


# The shape actually seen on prod: one hand-inserted row shadowing the whole set.
_GL_ENTRY_STANDARD = [
	_row("Accounts Manager", read=1, report=1),
	_row("Accounts User", read=1, report=1),
	_row("Auditor", read=1, report=1),
]


class TestDetectShadowedDoctypes(unittest.TestCase):
	def _detect(self, standard, custom_keys, newest=None, **kwargs):
		with (
			patch.object(perm, "_custom_docperm_doctypes", return_value=["GL Entry"]),
			patch.object(perm, "_standard_docperms", return_value=standard),
			patch.object(perm, "_custom_docperm_keys", return_value=set(custom_keys)),
			patch.object(perm, "_custom_docperm_newest_creation", return_value=newest),
		):
			return perm.detect_shadowed_doctypes(**kwargs)

	def test_single_shadowing_row_reports_the_roles_that_lost_access(self):
		"""The incident shape: one custom row, three standard roles silently revoked."""
		findings = self._detect(_GL_ENTRY_STANDARD, {("Dokon POS", 0)})

		self.assertEqual(len(findings), 1)
		self.assertEqual(findings[0]["doctype"], "GL Entry")
		self.assertEqual(
			{m["role"] for m in findings[0]["missing"]},
			{"Accounts Manager", "Accounts User", "Auditor"},
		)

	def test_fully_mirrored_custom_set_is_clean(self):
		"""A custom set produced via add_permission() copies everything — no finding."""
		keys = {(r.role, r.permlevel) for r in _GL_ENTRY_STANDARD}
		self.assertEqual(self._detect(_GL_ENTRY_STANDARD, keys), [])

	def test_missing_permlevel_1_row_is_caught(self):
		"""The case the old role-only sync could never see.

		Matching on ``role`` alone treats permlevel-1 as already covered by the
		permlevel-0 row, so masked cost fields stay unreadable forever.
		"""
		standard = [
			_row("Sales User", permlevel=0),
			_row("Sales User", permlevel=1),
		]
		findings = self._detect(standard, {("Sales User", 0)})

		self.assertEqual(len(findings), 1)
		self.assertEqual(
			findings[0]["missing"], [{"role": "Sales User", "permlevel": 1, "read": 1, "report": 0}]
		)

	def test_roles_without_read_or_report_are_not_reported(self):
		"""Only access-granting rows matter; a no-op standard row is not drift."""
		standard = [_row("Guest", read=0, report=0, select=0)]
		self.assertEqual(self._detect(standard, {("Someone", 0)}), [])

	def test_changed_after_suppresses_the_inherited_baseline(self):
		"""6 of 7 sites carry HR-era shadowing from 2012–2022.

		Alerting on it every night would make the nightly scan pure noise and hide
		the next real incident, so the scan filters by when the custom set was
		last touched.
		"""
		findings = self._detect(
			_GL_ENTRY_STANDARD,
			{("HR Manager", 0)},
			newest="2013-06-24 10:00:00",
			changed_after="2026-08-03 00:00:00",
		)
		self.assertEqual(findings, [])

	def test_changed_after_still_reports_a_recently_touched_doctype(self):
		"""A row added inside the window is drift — and stays reported until fixed."""
		findings = self._detect(
			_GL_ENTRY_STANDARD,
			{("Dokon POS", 0)},
			newest="2026-08-04 15:30:38",
			changed_after="2026-08-03 00:00:00",
		)
		self.assertEqual(len(findings), 1)
		self.assertEqual(findings[0]["doctype"], "GL Entry")

	def test_no_cutoff_reports_everything(self):
		"""The admin-facing report endpoint asks explicitly — it gets the full picture."""
		findings = self._detect(_GL_ENTRY_STANDARD, {("HR Manager", 0)}, newest="2013-06-24 10:00:00")
		self.assertEqual(len(findings), 1)


class TestRepairShadowedDocperms(unittest.TestCase):
	def _repair(self, standard, custom_keys, **kwargs):
		"""Run the repair against synthetic rows; returns (result, inserted_rows)."""
		inserted = []

		def fake_get_doc(row):
			inserted.append(row)
			doc = MagicMock()
			doc.insert = MagicMock()
			return doc

		with (
			patch.object(perm, "_custom_docperm_doctypes", return_value=["GL Entry"]),
			patch.object(perm, "_standard_docperms", return_value=standard),
			patch.object(perm, "_custom_docperm_keys", return_value=set(custom_keys)),
			patch.object(perm, "_perm_flag_columns", return_value=_FLAGS),
			patch.object(frappe, "get_doc", side_effect=fake_get_doc),
			patch.object(frappe, "logger", return_value=MagicMock()),
		):
			result = perm.repair_shadowed_docperms(**kwargs)
		return result, inserted

	def test_restores_missing_rows_verbatim_from_the_standard_set(self):
		result, inserted = self._repair(_GL_ENTRY_STANDARD, {("Dokon POS", 0)})

		self.assertEqual(result["repaired"], {"GL Entry": 3})
		self.assertEqual({r["role"] for r in inserted}, {"Accounts Manager", "Accounts User", "Auditor"})
		# Flags are copied, not invented — report=1 is what unblocks the GL report.
		self.assertTrue(all(r["report"] == 1 for r in inserted))
		self.assertTrue(all(r["parent"] == "GL Entry" for r in inserted))

	def test_is_idempotent(self):
		"""Second run must add nothing — the patch may be replayed by migrate."""
		keys = {(r.role, r.permlevel) for r in _GL_ENTRY_STANDARD}
		result, inserted = self._repair(_GL_ENTRY_STANDARD, keys)

		self.assertEqual(result["repaired"], {})
		self.assertEqual(inserted, [])

	def test_never_removes_or_rewrites_an_existing_row(self):
		"""Repair must not widen a restriction someone set deliberately.

		The pre-existing custom row for 'Dokon POS' is left exactly as-is; only
		absent (role, permlevel) pairs are inserted.
		"""
		_, inserted = self._repair(_GL_ENTRY_STANDARD, {("Dokon POS", 0)})
		self.assertNotIn("Dokon POS", {r["role"] for r in inserted})

	def test_only_created_after_skips_pre_incident_custom_sets(self):
		"""Old custom sets are deliberate admin restrictions — never touch them.

		Several prod sites carry long-standing restrictions on Account, Company,
		Cost Center and friends. A blanket mirror would silently re-grant them.
		"""
		with patch.object(frappe.db, "sql", return_value=[("2013-06-24 10:00:00",)]):
			result, inserted = self._repair(
				_GL_ENTRY_STANDARD,
				{("Dokon POS", 0)},
				only_created_after="2026-08-03 00:00:00",
			)

		self.assertEqual(result["skipped"], ["GL Entry"])
		self.assertEqual(result["repaired"], {})
		self.assertEqual(inserted, [])

	def test_only_created_after_repairs_incident_window_custom_sets(self):
		with patch.object(frappe.db, "sql", return_value=[("2026-08-04 15:30:38",)]):
			result, _ = self._repair(
				_GL_ENTRY_STANDARD,
				{("Dokon POS", 0)},
				only_created_after="2026-08-03 00:00:00",
			)

		self.assertEqual(result["repaired"], {"GL Entry": 3})
		self.assertEqual(result["skipped"], [])


class TestShadowReportEndpoint(unittest.TestCase):
	# frappe.session is a frappe._dict, which unittest.mock cannot patch
	# (it has no real __dict__ entry for `user`) — swap it by hand.
	def setUp(self):
		self._original_user = frappe.session.user

	def tearDown(self):
		frappe.session.user = self._original_user

	def test_report_endpoint_is_admin_only(self):
		"""The predecessor endpoint was whitelisted with no guard at all.

		It let any authenticated user rewrite permission tables and flush the site
		cache. The replacement is read-only AND role-guarded; this test fails if
		the guard is ever dropped again.
		"""
		frappe.session.user = "someone@example.com"
		with (
			patch.object(frappe, "get_roles", return_value=["Sales User"]),
			patch.object(perm, "detect_shadowed_doctypes", return_value=[]) as detect,
		):
			with self.assertRaises(frappe.PermissionError):
				perm.docperm_shadow_report()
			detect.assert_not_called()

	def test_guest_is_rejected(self):
		"""``_is_admin`` returns True for Guest — the endpoint must not use it."""
		frappe.session.user = "Guest"
		with patch.object(frappe, "get_roles", return_value=["Guest"]):
			with self.assertRaises(frappe.PermissionError):
				perm.docperm_shadow_report()

	def test_admin_role_gets_the_report(self):
		frappe.session.user = "admin@example.com"
		with (
			patch.object(frappe, "get_roles", return_value=["Stabler Admin"]),
			patch.object(perm, "detect_shadowed_doctypes", return_value=[{"doctype": "GL Entry"}]),
		):
			self.assertEqual(perm.docperm_shadow_report(), {"findings": [{"doctype": "GL Entry"}]})
