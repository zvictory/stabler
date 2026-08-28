"""Whether an integration may queue work at all.

Measured on prod 2026-08-28, read-only, across all eight stabler tenants:

    onec_outbox          unset on 8 / 8
    onec_rest_endpoint   unset on 8 / 8
    eimzo_endpoint       unset on 8 / 8
    ehf_stub_signature   unset on 8 / 8

Neither integration is configured anywhere. What they did instead of nothing:

    anjan `EHF Submission` rows                    8576
    …with status Error                             8576   (all of them)
    …that ever succeeded                              0
    span                        2026-05-30 -> 2026-08-28
    in the last 7 days                              481
    msa / mikas / dts             790 / 1 / 0, all Error

Every one carries `build/sign failed: EIMZO endpoint not configured`. So for
three months every submitted invoice on every tenant queued a background job,
which built a document, failed, and stored the failure on that document rather
than in the log — which is why nobody saw it. The 1C half is worse off still:
`1C Sync Log` does not even exist as a table on any of those sites, so its jobs
cannot record that they ran.

The gate is therefore not a new switch anybody has to set. It is the question
the work already asks itself one layer down — `_push_file` returns
"onec_outbox not configured", `sign()` raises "EIMZO endpoint not configured" —
asked before the job is queued instead of after a worker has picked it up. The
moment somebody configures either one, it starts working again with no further
change.

Kept frappe-free so it lands in `make check`: these are decisions about four
config values, and none of them needs a database.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest \
        stabler.tests.test_integration_enqueue_gates -v
"""

from __future__ import annotations

import unittest

from stabler.integrations._gates import ehf_can_submit, one_c_can_push


class TestOneCAsksAboutTheModeItIsIn(unittest.TestCase):
	"""`push()` branches on `onec_mode` and each branch reads a different config
	key. A gate that checked only one of them would either keep queueing work
	that cannot run, or — the damaging direction — silently switch off a REST
	installation because the file outbox happens to be empty."""

	def test_file_mode_without_an_outbox_queues_nothing(self):
		self.assertFalse(one_c_can_push("file", outbox=None, rest_endpoint=None))

	def test_file_mode_with_an_outbox_queues(self):
		self.assertTrue(one_c_can_push("file", outbox="/var/1c/outbox", rest_endpoint=None))

	def test_rest_mode_reads_the_rest_endpoint_and_not_the_outbox(self):
		self.assertTrue(one_c_can_push("rest", outbox=None, rest_endpoint="https://1c.local/api"))

	def test_rest_mode_with_only_an_outbox_queues_nothing(self):
		"""The case that catches a gate wired to the wrong key. A site that
		switched to REST and left its old outbox path behind would otherwise
		queue jobs that report "ok, written to file" and reach no 1C at all."""
		self.assertFalse(one_c_can_push("rest", outbox="/var/1c/outbox", rest_endpoint=None))

	def test_a_blank_mode_is_read_as_file(self):
		"""`push()` itself falls back to "file" with `or "file"`. The gate has to
		agree with it, or a site with no Stabler Settings row would have its
		working file drop refused before the job is even made."""
		for mode in (None, "", "   "):
			with self.subTest(mode=mode):
				self.assertTrue(one_c_can_push(mode, outbox="/var/1c/outbox", rest_endpoint=None))
				self.assertFalse(one_c_can_push(mode, outbox=None, rest_endpoint="https://1c/api"))

	def test_an_unknown_mode_is_also_read_as_file(self):
		self.assertTrue(one_c_can_push("Ftp", outbox="/var/1c/outbox", rest_endpoint=None))

	def test_a_blank_path_is_not_a_path(self):
		"""`site_config.json` carrying `"onec_outbox": ""` is how a setting gets
		half-removed, and an empty string is truthy in exactly the places that
		matter here if the check is `is not None`."""
		self.assertFalse(one_c_can_push("file", outbox="", rest_endpoint=None))
		self.assertFalse(one_c_can_push("file", outbox="   ", rest_endpoint=None))


class TestEhfNeedsSomethingThatCanSign(unittest.TestCase):
	def test_nothing_configured_queues_nothing(self):
		"""8576 rows on anjan, every one of them this case."""
		self.assertFalse(ehf_can_submit(eimzo_endpoint=None, stub_signature=None))

	def test_a_real_endpoint_queues(self):
		self.assertTrue(ehf_can_submit(eimzo_endpoint="http://127.0.0.1:9090", stub_signature=None))

	def test_the_development_stub_queues(self):
		"""The stub is the other way `sign()` can succeed, so a gate that only
		looked for the endpoint would break every developer's bench."""
		self.assertTrue(ehf_can_submit(eimzo_endpoint=None, stub_signature=1))

	def test_a_stub_switched_off_is_not_a_signer(self):
		"""`ehf_stub_signature: 0` is how somebody turns the stub off, and 0 is
		exactly the value a truthiness check on `getattr(...) is not None` reads
		as "configured". `sign()` uses `int(... or 0)`; this has to match it."""
		self.assertFalse(ehf_can_submit(eimzo_endpoint=None, stub_signature=0))

	def test_a_stub_written_as_a_string_is_read_as_a_number(self):
		"""site_config.json is hand-edited JSON, so "0" and "1" both occur."""
		self.assertFalse(ehf_can_submit(eimzo_endpoint=None, stub_signature="0"))
		self.assertTrue(ehf_can_submit(eimzo_endpoint=None, stub_signature="1"))

	def test_nonsense_in_the_stub_field_does_not_enable_it(self):
		"""An unparseable value is not a licence to queue three months of
		failures. `sign()` would raise on it anyway; the gate refuses earlier."""
		self.assertFalse(ehf_can_submit(eimzo_endpoint=None, stub_signature="evet"))

	def test_a_blank_endpoint_is_not_an_endpoint(self):
		self.assertFalse(ehf_can_submit(eimzo_endpoint="", stub_signature=None))
		self.assertFalse(ehf_can_submit(eimzo_endpoint="   ", stub_signature=None))


if __name__ == "__main__":
	unittest.main()
