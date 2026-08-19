"""J3 (idempotency review 2026-08-20): `repost_queue_alert` must not re-send.

`check_repost_queue` is a daily alarm, but it runs on the nightly tick AND can
be invoked by hand with `bench execute` — before this fix it inserted a fresh
Notification Log (and fired Telegram) on every call, so a manual re-run on
the same day duplicated that day's alarm.

Unlike `eta_payment_alert`, there is no document to key off — this is a
queue-level health check, not a per-record one — and the numbers inside the
message (queued count, failed count, oldest age) keep drifting between calls,
so keying on the message text would barely dedupe at all and reproduce the
bug in a subtler form. The stable "same underlying situation" here is the
calendar day: `_announce` dedupes on (for_user, subject-with-today's-date),
so re-runs on the SAME day collapse to one alert, but the alarm still fires
again on a NEW day if the queue is still unhealthy — a "daily alarm" that
goes silent after day one is exactly the failure mode this review is about.
"""

from __future__ import annotations

import importlib
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_SANDBOX = ModuleSandbox()
_MODULE = "stabler.tasks.repost_queue_alert"


class _NotificationDoc:
	def __init__(self, sink):
		self.__dict__["_sink"] = sink

	def insert(self, ignore_permissions=False):
		self._sink.append({k: v for k, v in self.__dict__.items() if not k.startswith("_")})


def _date_diff(a, b):
	ay, am, ad = (int(p) for p in str(a).split("-"))
	by, bm, bd = (int(p) for p in str(b).split("-"))
	from datetime import date

	return (date(ay, am, ad) - date(by, bm, bd)).days


def _load(status, today_holder):
	"""Import repost_queue_alert against a hand-built frappe.

	``today_holder`` is a one-item list the test mutates between calls so the
	same loaded module can be asked "what day is it" differently on each call,
	without re-importing (mirrors two invocations of the real scheduled task).
	"""
	inserted: list[dict] = []

	frappe = types.ModuleType("frappe")

	def _exists(doctype, filters):
		if doctype == "Stabler Company Modules":
			return True  # at least one company opted into the valuation guard
		if doctype == "Notification Log":
			# Faithful to the real guard: apply the given filters, don't just say yes.
			return any(all(row.get(k) == v for k, v in filters.items()) for row in inserted)
		raise AssertionError(f"unexpected frappe.db.exists({doctype!r})")

	def _new_doc(doctype):
		doc = _NotificationDoc(inserted)
		doc.doctype = doctype
		return doc

	frappe.db = types.SimpleNamespace(
		exists=_exists,
		get_single_value=lambda *a, **k: None,  # falls back to the coded defaults
	)
	frappe.new_doc = _new_doc
	frappe.conf = types.SimpleNamespace()  # no telegram creds -> network path skipped

	frappe_utils = types.ModuleType("frappe.utils")
	frappe_utils.date_diff = _date_diff
	frappe_utils.getdate = lambda s: s
	frappe_utils.today = lambda: today_holder[0]
	frappe.utils = frappe_utils

	monitor_mod = types.ModuleType("stabler.api.repost_monitor")
	monitor_mod.repost_status = lambda: status

	_SANDBOX.evict(_MODULE, "frappe", "frappe.utils", "stabler.api.repost_monitor")
	_SANDBOX.install(
		{"frappe": frappe, "frappe.utils": frappe_utils, "stabler.api.repost_monitor": monitor_mod}
	)
	module = importlib.import_module(_MODULE)
	return module, inserted


_UNHEALTHY = {"queued": 250, "errors": ["boom"], "oldest_queued": "2026-08-01", "in_progress": []}


def tearDownModule():
	_SANDBOX.restore()


class RepeatRunsSameDayDoNotResend(unittest.TestCase):
	"""The nightly-tick-plus-manual-run case: same day, same unhealthy queue."""

	def test_second_call_same_day_sends_nothing_new(self):
		today_holder = ["2026-08-20"]
		module, inserted = _load(_UNHEALTHY, today_holder)

		module.check_repost_queue()
		self.assertEqual(len(inserted), 1)

		module.check_repost_queue()
		self.assertEqual(len(inserted), 1, "a repeat run the same day must not insert a second alert")


class ANewDayStillAlerts(unittest.TestCase):
	"""The direction that matters more: a dedupe that over-suppresses is the worse bug.

	A daily alarm that fires once and then never again for a queue that stayed
	broken for a week is worse than the duplicate it was built to fix.
	"""

	def test_the_same_unhealthy_queue_on_a_later_day_still_alerts(self):
		today_holder = ["2026-08-20"]
		module, inserted = _load(_UNHEALTHY, today_holder)

		module.check_repost_queue()
		self.assertEqual(len(inserted), 1)

		today_holder[0] = "2026-08-21"
		module.check_repost_queue()
		self.assertEqual(
			len(inserted), 2, "the same unhealthy queue on a new day must still raise a fresh alarm"
		)


if __name__ == "__main__":
	unittest.main()
