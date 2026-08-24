"""What the web layer is allowed to conclude about the background queue.

Written before `stabler/stabler/job_health.py` existed. The 2026-07-28 outage
ran 43.7 h with gunicorn serving all eight tenants normally while not a single
background job was processed, and nothing in the product said so. These tests
pin the readings that would have surfaced it — and the one false alarm that
would have cost the banner its credibility on the first deploy.
"""

import unittest

from stabler.stabler.job_health import verdict


def _code_only(src: str) -> str:
	"""The module's code with every comment and string literal removed.

	These guards assert what the endpoint *does*. Matching raw source instead
	made both of them fail on this file's own prose — the docstring says
	"needs nothing enqueued" and names `_require_admin` to explain why it is
	absent. A guard that reads documentation cannot tell a promise from an
	implementation, in either direction.
	"""
	import io as _io
	import tokenize

	kept = [
		tok.string
		for tok in tokenize.generate_tokens(_io.StringIO(src).readline)
		if tok.type not in (tokenize.COMMENT, tokenize.STRING)
	]
	return " ".join(kept)


class TestJobHealthVerdict(unittest.TestCase):
	def test_unreachable_queue_is_never_reported_healthy(self):
		"""The outage opened with redis refusing connections on 11000.

		If an unreachable queue read as OK, the banner would stay silent through
		precisely the failure it was built for. "I could not look" must never be
		rendered as "I looked and it is fine".
		"""
		v = verdict(0, error="Error 111 connecting to 127.0.0.1:11000")
		self.assertFalse(v["ok"])
		self.assertEqual(v["reason"], "queue-unreachable")

	def test_an_unreachable_queue_outranks_a_worker_count(self):
		"""A count obtained without reaching redis cannot have come from redis.

		Reporting OK here would mean trusting a number the caller could not have
		read, which is how a caller's default argument becomes a false all-clear.
		"""
		v = verdict(4, error="Connection refused")
		self.assertFalse(v["ok"])
		self.assertEqual(v["reason"], "queue-unreachable")

	def test_no_registered_workers_is_down(self):
		"""Redis answered and nobody is listening — the 43.7 h state exactly."""
		v = verdict(0)
		self.assertFalse(v["ok"])
		self.assertEqual(v["reason"], "no-workers")

	def test_registered_workers_read_as_healthy(self):
		v = verdict(4)
		self.assertTrue(v["ok"])
		self.assertEqual(v["workers"], 4)
		self.assertEqual(v["reason"], "")

	def test_never_raises_on_junk(self):
		"""A health check that throws when things are broken reports nothing.

		The caller is a whitelisted endpoint polled by every open tab; an
		exception there turns a degraded bench into a 500 storm on top of it.
		"""
		for junk in (None, "", "4", -1, 0.0):
			with self.subTest(junk=junk):
				self.assertIn("ok", verdict(junk))

	def test_a_negative_count_is_not_healthy(self):
		"""Guards the coercion: int(-1) is truthy, so a naive check passes it."""
		self.assertFalse(verdict(-1)["ok"])


class TestBackgroundJobsEndpointSource(unittest.TestCase):
	"""The one alarm in this app that has to survive a dead queue.

	Every other alarm — `tasks/repost_queue_alert.py`, `tasks/eta_payment_alert.py`
	— runs as a scheduled job, so all of them were dead for the same 43.7 h as the
	workers they would have reported on. This endpoint answers from inside a
	request the SPA is already making, and these tests keep it that way.
	"""

	def setUp(self):
		import os

		path = os.path.join(os.path.dirname(__file__), "..", "api", "health.py")
		with open(path, encoding="utf-8") as fh:
			self.src = fh.read()
		self.code = _code_only(self.src)

	def test_it_never_enqueues(self):
		"""Enqueuing anything would make the check depend on the workers it checks."""
		self.assertNotIn("enqueue", self.code)

	def test_the_redis_call_sits_inside_the_try(self):
		"""Position, not presence: a `try` further down the file proves nothing."""
		try_at = self.src.index("\ttry:")
		call_at = self.src.index("get_redis_conn().scard")
		except_at = self.src.index("\texcept Exception")
		self.assertLess(try_at, call_at)
		self.assertLess(call_at, except_at)

	def test_it_is_not_gated_behind_admin(self):
		"""A paused queue affects whoever is doing the work, not just the admin.

		Gating this behind `_require_admin` would leave every ordinary user with
		exactly the silence that let the outage run for two days.
		"""
		self.assertIn("@frappe.whitelist()", self.src)
		self.assertNotIn("_require_admin", self.code)
