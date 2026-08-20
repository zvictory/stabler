"""The pickup code: how it is generated, how it is stored, how it is checked.

Lifted out of `stabler.api.remittance` unchanged. It lived there because the
JE-only engine was the only thing that had one; then the `Remittance Transfer`
engine grew its own register and payout and imported all four helpers back out of
the legacy module. That import is the reason the legacy engine could not be
retired: deleting it would have taken V1's pickup codes with it.

Nothing here touches frappe. That is not incidental — the code that decides
whether someone may collect a stranger's cash is pure stdlib, so its tests run in
`make check` on every push instead of in the bench-only set that gates nothing.
`test_remittance_pickup_code.py` explains what each door is holding shut.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

# Pickup-code alphabet: uppercase + digits minus ambiguous glyphs (0/O, 1/I).
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LEN = 8

# The stored code is readable by anyone who can open the Journal Entry, so it is
# kept as a salted digest and never in plaintext: `scheme$salt$digest`. Per-record
# salts rather than a site-wide pepper — a missing conf key on any of the seven
# tenants would break every payout at once.
_CODE_SCHEME = "s1"
_CODE_SALT_BYTES = 16


def _gen_pickup_code() -> str:
	return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))


def hash_pickup_code(code: str, salt: str) -> str:
	"""Storage form of a pickup code: `scheme$salt$digest`.

	Shared with the migration patch that hashes pre-existing plaintext values,
	so both sides derive the digest exactly the same way.
	"""
	digest = hashlib.sha256(f"{salt}{code.strip().upper()}".encode()).hexdigest()
	return f"{_CODE_SCHEME}${salt}${digest}"


def store_pickup_code(code: str) -> str:
	"""Hash a freshly generated code under a new random salt."""
	return hash_pickup_code(code, secrets.token_hex(_CODE_SALT_BYTES))


def is_hashed_pickup_code(stored: str) -> bool:
	parts = (stored or "").strip().split("$")
	return len(parts) == 3 and parts[0] == _CODE_SCHEME and bool(parts[1]) and bool(parts[2])


def _pickup_code_matches(stored: str, provided: str) -> bool:
	"""Constant-time compare of the provided code against the stored digest.

	A plaintext (unmigrated) stored value never matches — accepting one would
	reinstate exactly the defect this replaces.
	"""
	stored = (stored or "").strip()
	provided = (provided or "").strip().upper()
	if not stored or not provided or not is_hashed_pickup_code(stored):
		return False
	salt = stored.split("$")[1]
	return hmac.compare_digest(hash_pickup_code(provided, salt), stored)


__all__ = [
	"_gen_pickup_code",
	"_pickup_code_matches",
	"hash_pickup_code",
	"is_hashed_pickup_code",
	"store_pickup_code",
]
