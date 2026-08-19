"""J3 (idempotency review 2026-08-20): `eta_payment_alert` must not re-send.

`check_upcoming_deadlines` runs on a nightly tick AND can be invoked by hand
with `bench execute` — before this fix it inserted a fresh Notification Log
(and fired Telegram) on every call, so the nightly tick plus one manual
re-run on the same day sent the same "pay this CI" alert twice.

The fix follows `stabler/tasks/uzex_poll.py::_notify` — dedupe on
`(document_name, subject)` before inserting — with one addition uzex does not
need. The key here is the Commercial Invoice name PLUS the computed deadline
PLUS the calendar day. Deadline, because that is the fact that actually
changes: a re-run against the same CI with the same `eta_transit_port` must
produce the same subject (already exists → skipped), but a CI whose ETA got
corrected is a genuinely new deadline and must still alert, and a second
overdue CI must never be swallowed by the first one's key. Calendar day,
because this is a daily alarm and an overdue CI's (name, deadline) pair never
changes again — see `ANewDayStillAlerts` below for why keying on those two
alone would trade the duplicate for a permanent silence.
"""

from __future__ import annotations

import importlib
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_SANDBOX = ModuleSandbox()
_MODULE = "stabler.tasks.eta_payment_alert"


class _Row(dict):
	"""A frappe.get_all row: dict data, attribute access (ci.name, ci.supplier)."""

	def __getattr__(self, key):
		try:
			return self[key]
		except KeyError as exc:
			raise AttributeError(key) from exc


class _NotificationDoc:
	"""Stands in for `frappe.new_doc("Notification Log")`."""

	def __init__(self, sink, clock):
		self.__dict__["_sink"] = sink
		self.__dict__["_clock"] = clock

	def insert(self, ignore_permissions=False):
		row = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
		# `creation` is stamped by the database, never by the task — but the
		# dedupe guard reads it, so the double has to behave like the DB here or
		# it would answer the day-scoping question without ever asking it.
		row["creation"] = f"{self._clock[0]} 03:00:00"
		self._sink.append(row)


def _load(invoices_by_call, today_holder=None):
	"""Import eta_payment_alert against a hand-built frappe.

	``invoices_by_call`` is a list of invoice-row lists, one per call to
	``check_upcoming_deadlines()`` the test makes (so a test can change what
	the CI's ETA looks like between calls). ``today_holder`` is a one-item list
	the test mutates between calls, so the same loaded module can be asked
	"what day is it" differently on each call — two nightly ticks, not two
	hand-runs. ``inserted`` accumulates every Notification Log actually
	inserted, across every call, so the dedupe guard is exercised against real
	prior state rather than a canned answer.
	"""
	today_holder = today_holder if today_holder is not None else ["2026-08-20"]
	calls = iter(invoices_by_call)
	inserted: list[dict] = []

	frappe = types.ModuleType("frappe")

	def _match(row, key, want):
		if isinstance(want, list):
			op, value = want
			if op != ">=":
				raise AssertionError(f"the double does not model this operator: {op!r}")
			return str(row.get(key, "")) >= str(value)
		return row.get(key) == want

	def _exists(doctype, filters):
		# Faithful to the real guard: apply the given filters, don't just say yes.
		if doctype != "Notification Log":
			return False
		return any(all(_match(row, k, v) for k, v in filters.items()) for row in inserted)

	def _get_all(doctype, filters=None, fields=None, pluck=None):
		if doctype == "Company":
			return ["Anjan"]
		if doctype == "Commercial Invoice":
			return next(calls)
		raise AssertionError(f"unexpected get_all({doctype!r})")

	def _new_doc(doctype):
		doc = _NotificationDoc(inserted, today_holder)
		doc.doctype = doctype
		return doc

	frappe.db = types.SimpleNamespace(exists=_exists)
	frappe.get_all = _get_all
	frappe.new_doc = _new_doc
	frappe.conf = types.SimpleNamespace()  # no telegram creds -> network path skipped

	frappe_utils = types.ModuleType("frappe.utils")
	frappe_utils.add_days = lambda *a, **k: None
	frappe_utils.getdate = lambda s: s
	frappe_utils.today = lambda: today_holder[0]
	frappe.utils = frappe_utils

	settings_mod = types.ModuleType("stabler.stabler.doctype.stabler_settings.stabler_settings")
	settings_mod.module_map_for = lambda company: {"imports": True}

	rules_mod = types.ModuleType("stabler.api._imports_rules")
	# Identity: the test drives the deadline directly through eta_transit_port.
	rules_mod.get_7day_payment_deadline = lambda eta: eta

	_SANDBOX.evict(
		_MODULE,
		"frappe",
		"frappe.utils",
		"stabler.stabler.doctype.stabler_settings.stabler_settings",
		"stabler.api._imports_rules",
	)
	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.utils": frappe_utils,
			"stabler.stabler.doctype.stabler_settings.stabler_settings": settings_mod,
			"stabler.api._imports_rules": rules_mod,
		}
	)
	module = importlib.import_module(_MODULE)
	return module, inserted


def _ci(name, deadline, supplier="Acme", agreed_total=1000.0):
	return _Row(
		name=name,
		eta_transit_port=deadline,
		company="Anjan",
		supplier=supplier,
		agreed_total=agreed_total,
	)


def tearDownModule():
	_SANDBOX.restore()


class RepeatRunsDoNotResend(unittest.TestCase):
	"""Same CI, same deadline, called twice — the nightly-tick-plus-manual-run case."""

	def test_second_call_same_day_sends_nothing_new(self):
		ci = _ci("CI-0001", "2026-08-19")
		module, inserted = _load([[ci], [ci]])

		module.check_upcoming_deadlines()
		self.assertEqual(len(inserted), 1)

		module.check_upcoming_deadlines()
		self.assertEqual(len(inserted), 1, "a repeat run must not insert a second alert")


class GenuinelyNewSituationsStillAlert(unittest.TestCase):
	"""The direction that matters more: a dedupe that over-suppresses is the worse bug."""

	def test_a_different_overdue_ci_still_alerts(self):
		ci_a = _ci("CI-0001", "2026-08-19")
		ci_b = _ci("CI-0002", "2026-08-19")
		module, inserted = _load([[ci_a, ci_b]])

		module.check_upcoming_deadlines()
		self.assertEqual(len(inserted), 2, "two distinct overdue CIs must both alert")

	def test_a_corrected_later_deadline_on_the_same_ci_still_alerts(self):
		# First run: ETA gives a deadline that's already overdue and alerts.
		ci_first = _ci("CI-0001", "2026-08-10")
		# Second run: the ETA got corrected -> a new, different (later) deadline,
		# still overdue by "today" but for a materially different reason.
		ci_second = _ci("CI-0001", "2026-08-19")
		module, inserted = _load([[ci_first], [ci_second]])

		module.check_upcoming_deadlines()
		self.assertEqual(len(inserted), 1)

		module.check_upcoming_deadlines()
		self.assertEqual(len(inserted), 2, "a genuinely new deadline for the same CI must not be swallowed")


class ANewDayStillAlerts(unittest.TestCase):
	"""A payment deadline that is already past does not stop being past.

	`check_upcoming_deadlines` sits on the `daily` scheduler (`hooks.py:103`)
	and the CI stays in its query until the invoice is cancelled or delivered,
	so an unpaid overdue payment is meant to be raised every night until
	somebody acts on it. Keying the dedupe on (CI, deadline) alone keys it on
	two facts that never change again: the nag would fire once, on the day the
	deadline passed, and stay silent for the rest of the invoice's life. That
	is a worse failure than the duplicate the dedupe exists to remove — and it
	is the reasoning this commit's sibling, `repost_queue_alert`, already
	applies to itself.
	"""

	def test_the_same_overdue_ci_on_a_later_day_still_alerts(self):
		ci = _ci("CI-0001", "2026-08-19")
		today_holder = ["2026-08-20"]
		module, inserted = _load([[ci], [ci]], today_holder)

		module.check_upcoming_deadlines()
		self.assertEqual(len(inserted), 1)

		today_holder[0] = "2026-08-21"
		module.check_upcoming_deadlines()
		self.assertEqual(len(inserted), 2, "an overdue payment must still be raised on the next nightly tick")


if __name__ == "__main__":
	unittest.main()
