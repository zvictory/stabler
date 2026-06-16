"""Pure hash-chain logic for audit tamper-evidence — no Frappe, no I/O.

Provides a deterministic SHA-256 chain over an ordered sequence of audit rows
so that any post-hoc edit, deletion, insertion or reordering of Version rows
is detectable.

Public API
----------
``row_hash(prev_hash, payload_dict) -> str``
    SHA-256 hex digest over the canonical (sorted-keys, no-whitespace) JSON
    serialisation of ``payload_dict`` prepended by ``prev_hash``.

``build_chain(rows) -> list[dict]``
    Accepts an iterable of plain dicts (each representing one Version row).
    Returns a *new* list where every element is the original dict augmented
    with three keys:

        seq        int   1-based position in the chain
        prev_hash  str   hash of the preceding entry ("0" * 64 for seq=1)
        hash       str   SHA-256 of (prev_hash + canonical JSON of this row)

``verify_chain(rows) -> tuple[bool, int | None]``
    Accepts a list previously produced by ``build_chain`` (or loaded from
    storage with seq/prev_hash/hash fields intact).
    Returns ``(True, None)`` when every link is intact, or
    ``(False, first_broken_seq)`` identifying the first broken link.
    An empty list is considered valid: ``(True, None)``.

Design notes
------------
* Canonical JSON: ``json.dumps(payload, sort_keys=True, separators=(',', ':'),
  ensure_ascii=True)``.  ``ensure_ascii=True`` avoids encoding ambiguity.
  ``sort_keys=True`` makes the output independent of insertion order.
  ``separators=(',', ':')`` removes all whitespace.
* The chain input for ``row_hash`` is ``prev_hash + ":" + canonical_json``.
  The colon separator is a fixed delimiter that can never appear at the start
  of a hex digest, so there is no ambiguity between the two parts.
* The "prev_hash" for the genesis entry (seq=1) is the all-zeros sentinel
  ``"0" * 64`` — the same length as a real SHA-256 hex digest, so the genesis
  hash is not distinguishable in structure from any other link.
* ``build_chain`` never mutates the input dicts; it yields copies.
* Keys added by ``build_chain`` (``seq``, ``prev_hash``, ``hash``) are
  excluded from the payload fed to ``row_hash`` so the hash is stable
  regardless of whether the row dict already carries those keys.
"""

from __future__ import annotations

import hashlib
import json

# Sentinel prev_hash used for the first entry in the chain.
_GENESIS_PREV = "0" * 64

# Keys injected by build_chain; must be stripped before hashing so that
# re-building the chain over stored rows produces the same hashes.
_CHAIN_KEYS = frozenset({"seq", "prev_hash", "hash"})


def _canonical(payload_dict: dict) -> str:
	"""Deterministic, whitespace-free JSON string of *payload_dict*."""
	return json.dumps(payload_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def row_hash(prev_hash: str, payload_dict: dict) -> str:
	"""Return the SHA-256 hex digest that seals one chain link.

	Parameters
	----------
	prev_hash:
	    Hex digest of the preceding row, or ``"0" * 64`` for the genesis entry.
	payload_dict:
	    The audit row dict.  Keys listed in ``_CHAIN_KEYS`` are excluded so
	    the hash is idempotent whether or not the dict already has chain fields.
	"""
	clean = {k: v for k, v in payload_dict.items() if k not in _CHAIN_KEYS}
	material = prev_hash + ":" + _canonical(clean)
	return hashlib.sha256(material.encode("utf-8")).hexdigest()


def build_chain(rows) -> list[dict]:
	"""Annotate an iterable of audit-row dicts with seq/prev_hash/hash.

	Returns a fresh list; input objects are not mutated.

	Parameters
	----------
	rows:
	    An iterable of plain dicts.  The order of iteration defines the chain
	    order, so callers must pass rows sorted by ``creation asc`` (or
	    whatever ordering they consider canonical) *before* calling this.
	"""
	result: list[dict] = []
	prev = _GENESIS_PREV
	for seq, row in enumerate(rows, start=1):
		# Strip any pre-existing chain keys so we hash the raw payload only.
		clean = {k: v for k, v in row.items() if k not in _CHAIN_KEYS}
		h = row_hash(prev, clean)
		annotated = dict(clean)
		annotated["seq"] = seq
		annotated["prev_hash"] = prev
		annotated["hash"] = h
		result.append(annotated)
		prev = h
	return result


def verify_chain(rows) -> tuple[bool, int | None]:
	"""Verify the integrity of a chain produced by ``build_chain``.

	Accepts a list of dicts that carry ``seq``, ``prev_hash``, and ``hash``
	fields (as stored or as returned by ``build_chain``).

	Returns
	-------
	(True, None)
	    The chain is intact: every row's ``hash`` recomputes correctly from its
	    ``prev_hash`` and its payload, and every ``prev_hash`` equals the
	    ``hash`` of the preceding row.
	(False, first_broken_seq)
	    The chain is broken; ``first_broken_seq`` is the ``seq`` value of the
	    earliest inconsistency found.

	An empty list returns ``(True, None)`` — a chain with no rows is vacuously
	valid.
	"""
	if not rows:
		return True, None

	expected_prev = _GENESIS_PREV
	for row in rows:
		seq = row.get("seq")
		stored_prev = row.get("prev_hash")
		stored_hash = row.get("hash")

		# Check that prev_hash matches what we computed for the prior row.
		if stored_prev != expected_prev:
			return False, seq

		# Recompute the hash from payload (exclude chain keys).
		computed = row_hash(stored_prev, row)
		if computed != stored_hash:
			return False, seq

		expected_prev = stored_hash

	return True, None
