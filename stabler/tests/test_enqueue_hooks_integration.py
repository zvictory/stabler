"""The two hooks that decide whether a background job is made at all.

`_gates.py` decides the question; this proves the hooks actually ask it — that
the gate is wired into the path a submitted document takes, and wired in the
right direction. `test_integration_enqueue_gates` can be entirely green while
`enqueue_push` ignores it, and that is precisely the bug being fixed: the
"skip when EHF is disabled" policy has been in `ehf/hooks.py`'s docstring since
the module was written and was never in its code.

Bench-side rather than frappe-free because the hooks read `frappe.conf` and
`Stabler Settings`, and because `frappe.enqueue` is the thing being watched.
No document is created: the doc is a stub with the two attributes the hooks
read, so this measures the hook and nothing underneath it.

Why it matters in numbers, measured on prod 2026-08-28: 8576 EHF Submission
rows on anjan since 2026-05-30, every one status Error, none ever successful,
481 in the last 7 days — one background job per submitted invoice, on all eight
tenants, for three months, against an integration configured on none of them.

    bench --site genesis-test.local run-tests \
        --module stabler.tests.test_enqueue_hooks_integration
"""

from __future__ import annotations

from contextlib import contextmanager

import frappe
from frappe.tests.utils import FrappeTestCase

from stabler.integrations.ehf import hooks as ehf_hooks
from stabler.integrations.one_c import hooks as one_c_hooks


class _Doc:
	"""The two attributes the hooks read. Nothing is inserted."""

	def __init__(self, docstatus=1, doctype="Sales Invoice", name="SINV-TEST-0001"):
		self.docstatus = docstatus
		self.doctype = doctype
		self.name = name


@contextmanager
def _conf(**values):
	"""Set site config keys for the block, restoring exactly what was there.

	`None` means "absent", which is what all four of these keys are on all eight
	prod tenants — so the default case has to be reachable from a dev bench that
	may well have them set.
	"""
	missing = object()
	before = {key: frappe.conf.get(key, missing) for key in values}
	try:
		for key, value in values.items():
			if value is None:
				frappe.conf.pop(key, None)
			else:
				frappe.conf[key] = value
		yield
	finally:
		for key, old in before.items():
			if old is missing:
				frappe.conf.pop(key, None)
			else:
				frappe.conf[key] = old


@contextmanager
def _watch_enqueue():
	"""Record calls to `frappe.enqueue` instead of making jobs.

	Both hook modules call `frappe.enqueue` through the module object, so
	patching the attribute on `frappe` covers both call sites.
	"""
	calls = []
	original = frappe.enqueue
	frappe.enqueue = lambda *a, **kw: calls.append((a, kw))
	try:
		yield calls
	finally:
		frappe.enqueue = original


class TestOneCPushIsNotQueuedWithoutSomewhereToPushIt(FrappeTestCase):
	def test_an_unconfigured_site_makes_no_job(self):
		"""The prod case on 8 / 8 tenants. Each of these jobs used to run, find no
		outbox, and fail into a `1C Sync Log` table that does not exist on any of
		those sites — so it could not even record that it had run."""
		with _conf(onec_outbox=None, onec_rest_endpoint=None), _watch_enqueue() as calls:
			one_c_hooks.enqueue_push(_Doc())
		self.assertEqual(calls, [])

	def test_a_configured_outbox_still_makes_the_job(self):
		"""The direction that matters more than the fix: a gate that switched off
		a working file drop would lose documents 1C is waiting for."""
		with _conf(onec_outbox="/tmp/stabler-1c-outbox"), _watch_enqueue() as calls:
			one_c_hooks.enqueue_push(_Doc())
		self.assertEqual(len(calls), 1)
		self.assertEqual(calls[0][0][0], "stabler.integrations.one_c.outbound.push")
		self.assertEqual(calls[0][1]["name"], "SINV-TEST-0001")

	def test_a_draft_is_still_refused_before_the_gate_is_consulted(self):
		"""The pre-existing docstatus guard has to survive the new one."""
		with _conf(onec_outbox="/tmp/stabler-1c-outbox"), _watch_enqueue() as calls:
			one_c_hooks.enqueue_push(_Doc(docstatus=0))
		self.assertEqual(calls, [])


class TestEhfSubmissionIsNotQueuedWithoutASigner(FrappeTestCase):
	def test_an_unconfigured_site_makes_no_job(self):
		"""8576 rows on anjan, every one of them this case."""
		with _conf(eimzo_endpoint=None, ehf_stub_signature=None), _watch_enqueue() as calls:
			ehf_hooks.enqueue_ehf_submit(_Doc())
		self.assertEqual(calls, [])

	def test_a_configured_endpoint_still_makes_the_job(self):
		with _conf(eimzo_endpoint="http://127.0.0.1:9090"), _watch_enqueue() as calls:
			ehf_hooks.enqueue_ehf_submit(_Doc())
		self.assertEqual(len(calls), 1)
		self.assertEqual(calls[0][0][0], "stabler.integrations.ehf.submit.submit_for_invoice")

	def test_the_development_stub_still_makes_the_job(self):
		"""A dev bench signs with the stub and no endpoint; the gate must not be
		the thing that stops EHF working locally."""
		with _conf(eimzo_endpoint=None, ehf_stub_signature=1), _watch_enqueue() as calls:
			ehf_hooks.enqueue_ehf_submit(_Doc())
		self.assertEqual(len(calls), 1)

	def test_a_draft_is_still_refused_before_the_gate_is_consulted(self):
		with _conf(eimzo_endpoint="http://127.0.0.1:9090"), _watch_enqueue() as calls:
			ehf_hooks.enqueue_ehf_submit(_Doc(docstatus=0))
		self.assertEqual(calls, [])
