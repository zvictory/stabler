"""Thorough unit tests for stabler.api._audit_chain.

No Frappe, no I/O — runs under plain ``python3 -m unittest``.

Coverage
--------
- ``row_hash`` produces a stable hex digest for identical inputs.
- ``row_hash`` differs when payload or prev_hash changes.
- ``build_chain`` correctly annotates seq / prev_hash / hash.
- ``build_chain`` links each row to the previous hash.
- The genesis entry uses the all-zeros sentinel as prev_hash.
- ``build_chain`` does not mutate input dicts.
- ``build_chain`` strips pre-existing chain keys before hashing so that
  re-building over stored rows gives the same hashes.
- ``verify_chain`` returns (True, None) for a clean chain.
- ``verify_chain`` returns (True, None) for an empty list.
- ``verify_chain`` detects a tampered payload in the middle.
- ``verify_chain`` detects a deletion (row removed).
- ``verify_chain`` detects reordering of rows.
- ``verify_chain`` detects a tampered hash field.
- ``verify_chain`` detects a tampered prev_hash field.
- Single-element chain verifies correctly.
"""

from __future__ import annotations

import copy
import unittest

from stabler.api._audit_chain import (
	_GENESIS_PREV,
	build_chain,
	row_hash,
	verify_chain,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _rows(n: int = 5) -> list[dict]:
	"""Return n distinct plain dicts simulating audit rows."""
	return [
		{
			"name": f"VER-{i:04d}",
			"owner": "admin@x.uz",
			"creation": f"2026-01-{i:02d} 12:00:00",
			"data": f"payload-{i}",
		}
		for i in range(1, n + 1)
	]


# --------------------------------------------------------------------------- #
# row_hash
# --------------------------------------------------------------------------- #


class RowHashStabilityTest(unittest.TestCase):
	"""row_hash must be deterministic and change when inputs change."""

	def test_same_input_same_hash(self):
		payload = {"name": "VER-0001", "owner": "a@b.uz", "creation": "2026-01-01"}
		h1 = row_hash(_GENESIS_PREV, payload)
		h2 = row_hash(_GENESIS_PREV, payload)
		self.assertEqual(h1, h2)

	def test_hash_is_64_hex_chars(self):
		h = row_hash(_GENESIS_PREV, {"x": 1})
		self.assertEqual(len(h), 64)
		self.assertTrue(all(c in "0123456789abcdef" for c in h))

	def test_different_payload_different_hash(self):
		h1 = row_hash(_GENESIS_PREV, {"amount": 100})
		h2 = row_hash(_GENESIS_PREV, {"amount": 101})
		self.assertNotEqual(h1, h2)

	def test_different_prev_hash_different_hash(self):
		payload = {"a": "b"}
		h1 = row_hash(_GENESIS_PREV, payload)
		h2 = row_hash("a" * 64, payload)
		self.assertNotEqual(h1, h2)

	def test_sort_keys_canonical_order_independence(self):
		# Dict with keys in different insertion order must hash identically.
		d1 = {"z": 1, "a": 2, "m": 3}
		d2 = {"a": 2, "m": 3, "z": 1}
		self.assertEqual(row_hash(_GENESIS_PREV, d1), row_hash(_GENESIS_PREV, d2))

	def test_chain_keys_stripped_before_hashing(self):
		# A dict that already carries seq/prev_hash/hash must hash the same as
		# one that does not — the chain metadata is not part of the content.
		base = {"name": "V1", "data": "x"}
		with_chain = dict(base, seq=1, prev_hash=_GENESIS_PREV, hash="deadbeef" * 8)
		self.assertEqual(
			row_hash(_GENESIS_PREV, base),
			row_hash(_GENESIS_PREV, with_chain),
		)


# --------------------------------------------------------------------------- #
# build_chain
# --------------------------------------------------------------------------- #


class BuildChainTest(unittest.TestCase):
	def test_empty_input_returns_empty_list(self):
		self.assertEqual(build_chain([]), [])

	def test_seq_starts_at_one_and_increments(self):
		chain = build_chain(_rows(3))
		self.assertEqual([r["seq"] for r in chain], [1, 2, 3])

	def test_genesis_prev_hash_is_sentinel(self):
		chain = build_chain(_rows(1))
		self.assertEqual(chain[0]["prev_hash"], _GENESIS_PREV)

	def test_each_prev_hash_equals_preceding_hash(self):
		chain = build_chain(_rows(4))
		for i in range(1, len(chain)):
			self.assertEqual(chain[i]["prev_hash"], chain[i - 1]["hash"])

	def test_hash_field_present_and_hex(self):
		chain = build_chain(_rows(3))
		for row in chain:
			self.assertIn("hash", row)
			self.assertEqual(len(row["hash"]), 64)

	def test_does_not_mutate_input_dicts(self):
		rows = _rows(3)
		originals = [dict(r) for r in rows]
		build_chain(rows)
		for original, after in zip(originals, rows, strict=True):
			self.assertEqual(original, after)

	def test_rebuild_over_stored_rows_gives_same_hashes(self):
		# Simulate storing the chain and re-building it: must be idempotent.
		chain1 = build_chain(_rows(5))
		chain2 = build_chain(chain1)  # chain1 rows already have seq/prev_hash/hash
		self.assertEqual(
			[r["hash"] for r in chain1],
			[r["hash"] for r in chain2],
		)

	def test_single_row_chain(self):
		rows = [{"name": "V1", "owner": "a@b.uz"}]
		chain = build_chain(rows)
		self.assertEqual(len(chain), 1)
		self.assertEqual(chain[0]["seq"], 1)
		self.assertEqual(chain[0]["prev_hash"], _GENESIS_PREV)
		expected_hash = row_hash(_GENESIS_PREV, {"name": "V1", "owner": "a@b.uz"})
		self.assertEqual(chain[0]["hash"], expected_hash)


# --------------------------------------------------------------------------- #
# verify_chain
# --------------------------------------------------------------------------- #


class VerifyChainTest(unittest.TestCase):
	def _make(self, n: int = 5) -> list[dict]:
		return build_chain(_rows(n))

	def test_empty_chain_is_valid(self):
		ok, broken = verify_chain([])
		self.assertTrue(ok)
		self.assertIsNone(broken)

	def test_clean_chain_passes(self):
		ok, broken = verify_chain(self._make(6))
		self.assertTrue(ok)
		self.assertIsNone(broken)

	def test_single_row_passes(self):
		ok, broken = verify_chain(self._make(1))
		self.assertTrue(ok)
		self.assertIsNone(broken)

	def test_tamper_payload_in_first_row_detected(self):
		chain = self._make(4)
		chain[0]["data"] = "TAMPERED"
		ok, broken = verify_chain(chain)
		self.assertFalse(ok)
		self.assertEqual(broken, 1)  # seq 1

	def test_tamper_payload_in_middle_detected(self):
		chain = self._make(5)
		chain[2]["owner"] = "attacker@evil.com"
		ok, broken = verify_chain(chain)
		self.assertFalse(ok)
		# seq 3 is where the tamper lives; the break is first detected there.
		self.assertEqual(broken, 3)

	def test_tamper_payload_in_last_row_detected(self):
		chain = self._make(4)
		chain[-1]["creation"] = "1970-01-01 00:00:00"
		ok, broken = verify_chain(chain)
		self.assertFalse(ok)
		self.assertEqual(broken, 4)

	def test_row_deleted_from_middle_detected(self):
		chain = self._make(5)
		# Remove seq=3; seq=4's prev_hash now won't match seq=2's hash.
		del chain[2]
		ok, broken = verify_chain(chain)
		self.assertFalse(ok)
		# The first broken link is the row after the deletion (originally seq 4).
		self.assertEqual(broken, 4)

	def test_row_deleted_from_start_detected(self):
		chain = self._make(4)
		del chain[0]
		ok, _broken = verify_chain(chain)
		self.assertFalse(ok)
		# seq 2 now has _GENESIS_PREV as its stored prev_hash but we compare
		# against _GENESIS_PREV for the first element — actually seq 2's
		# prev_hash won't equal _GENESIS_PREV, it equals chain[0]'s hash.
		self.assertFalse(ok)

	def test_rows_reordered_detected(self):
		chain = self._make(5)
		# Swap seq=2 and seq=3.
		chain[1], chain[2] = chain[2], chain[1]
		ok, broken = verify_chain(chain)
		self.assertFalse(ok)
		# The swap means seq=3 (now at index 1) has wrong prev_hash.
		self.assertEqual(broken, 3)

	def test_tampered_hash_field_detected(self):
		chain = self._make(3)
		# Forge the hash field of row 2 without changing payload.
		chain[1] = dict(chain[1], hash="deadbeef" * 8)
		ok, broken = verify_chain(chain)
		self.assertFalse(ok)
		# Row 2's hash is wrong (computed != stored).
		self.assertEqual(broken, 2)

	def test_tampered_prev_hash_field_detected(self):
		chain = self._make(3)
		# Change the prev_hash of row 2 to an arbitrary value.
		chain[1] = dict(chain[1], prev_hash="cafebabe" * 8)
		ok, broken = verify_chain(chain)
		self.assertFalse(ok)
		self.assertEqual(broken, 2)

	def test_two_row_clean_chain(self):
		chain = self._make(2)
		ok, broken = verify_chain(chain)
		self.assertTrue(ok)
		self.assertIsNone(broken)

	def test_insertion_in_middle_detected(self):
		chain = self._make(4)
		# Insert a foreign row with faked chain fields — its prev_hash will be
		# wrong relative to what verify expects at that position.
		intruder = {
			"name": "FAKE",
			"seq": 99,
			"prev_hash": chain[1]["hash"],
			"hash": "ff" * 32,
		}
		chain.insert(2, intruder)
		ok, _broken = verify_chain(chain)
		self.assertFalse(ok)


# --------------------------------------------------------------------------- #
# Hash value regression — locks down the exact algorithm
# --------------------------------------------------------------------------- #


class HashRegressionTest(unittest.TestCase):
	"""Guard against accidental algorithm changes by pinning a known digest."""

	def test_genesis_hash_is_stable(self):
		import hashlib
		import json

		payload = {"name": "VER-0001"}
		canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
		material = (_GENESIS_PREV + ":" + canonical).encode("utf-8")
		expected = hashlib.sha256(material).hexdigest()
		self.assertEqual(row_hash(_GENESIS_PREV, payload), expected)


if __name__ == "__main__":
	unittest.main()
