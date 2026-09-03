"""The ONE predetermined landed-charge list (ADR-606), and the aliases into it.

Frappe-free and site-free, like `_landed.py` beside it, so both landed readers
and the tests can import it without a bench.

Why this module exists. Measured 2026-09-03: two client-side lists described the
same costs and did not overlap -- `PoControlBoard.vue` offered eleven lower-case
keys on a Purchase Order's landed line, `LandedChargesEditor.vue` six Title-Case
ones on a Supplier Quotation's estimate. They are the same money at two moments,
the estimate before the order and the plan after it, so "Freight" and "transport"
had to be recognised as one cost before a plan-vs-actual comparison could exist
at all. Zafar's decision: one list, nine types, defined here, read by both
editors through `tender.landed_charge_types`.

Two rules the rest of the codebase depends on:

  * **Nothing here rewrites stored data.** The RAW shapes (`raw_charge_line`,
    `sanitize_charge_lines`, `tender._raw_landed_lines`) keep whatever string a
    row already carries. Canonicalisation is a READ-time derivation, exactly like
    every other figure in `_landed.py`: the valued shape is the stored line
    untouched PLUS what it resolves to.
  * **VAT is not a type.** It is the `is_recoverable_vat` flag, because a VAT
    line is not a different kind of cost -- it is a cost that is recoverable,
    which is what decides whether it capitalizes (IAS 2 §11). The stored value
    still exists on disk, so the alias below maps it to `other` AND forces the
    flag, or the rename would capitalize recoverable input tax into the landed
    cost of the goods and move which bid wins the tender.

Labels are English on the wire; the SPA translates them with `t()` at render
time, so one payload serves every language. They are added to the five
catalogues by hand -- there is no `t("Freight / transport")` literal for the
harvester to find -- and `test_landed_charge_types` is what checks that.
"""

from __future__ import annotations

# The nine types, in the order both <select>s render them (ADR-606, karar 3).
CHARGE_TYPES: tuple[dict[str, str], ...] = (
	{"key": "transport", "label": "Freight / transport"},
	{"key": "customs", "label": "Customs duty"},
	{"key": "declarant", "label": "Customs broker / declarant"},
	{"key": "certification", "label": "Certification"},
	{"key": "insurance", "label": "Insurance"},
	{"key": "storage", "label": "Storage / terminal / handling"},
	{"key": "bank", "label": "Bank charges"},
	{"key": "legal", "label": "Legal / lawyer"},
	# `other` is the only type that needs the free-text box filled in: on its own
	# it names no cost. Both editors flag an `other` line with an empty label.
	{"key": "other", "label": "Other"},
)

CHARGE_TYPE_KEYS: tuple[str, ...] = tuple(entry["key"] for entry in CHARGE_TYPES)

FALLBACK_CHARGE_TYPE = "other"

# Recoverable VAT as it was stored when it was still a type. Matched
# case-insensitively; `_landed.py:136` used to carry this set inline as
# `charge_type.upper() in ("VAT", "VALUE ADDED TAX", "НДС")`.
#
# These three and no more. Membership here decides whether a stored line
# capitalizes, so an alias added because it READS like VAT restates a company's
# landed cost: "Import VAT" was an ordinary charge before this module existed,
# and flagging it drops its amount out of `base_landed_total` -- possibly out of
# `cheapest_landed`, which decides a tender. A spelling joins this set only on
# evidence that the stored data meant recoverable VAT.
_VAT_ALIASES = frozenset({"vat", "value added tax", "ндс"})

# Every value that can be on disk today -> the canonical key it means. Keys are
# lower-cased; lookups lower-case and strip. Anything not here is an unknown
# string, which lands on `other` and keeps its own text (see `resolve_charge_type`).
_ALIASES: dict[str, str] = {
	# The nine themselves.
	**{key: key for key in CHARGE_TYPE_KEYS},
	# PoControlBoard.vue's eleven: two of them are renames, not new costs.
	"broker": "declarant",  # the customs broker IS the declarant
	"loading": "storage",  # loading/unloading is terminal handling
	# LandedChargesEditor.vue's six.
	"freight": "transport",
	"customs duty": "customs",
	"handling & terminal": "storage",
	# The server's own empty sentinel: `raw_charge_line` writes "General" when a
	# line names no type at all. It is not a cost and not an unknown string worth
	# preserving as a description. The empty string is deliberately NOT here --
	# `is_known_charge_type` is what write paths gate on, and answering True for
	# "" let a whitespace-only type persist as "" rather than fall back.
	"general": FALLBACK_CHARGE_TYPE,
	# VAT is the flag now, and the line is an ordinary charge under `other`.
	**dict.fromkeys(_VAT_ALIASES, FALLBACK_CHARGE_TYPE),
}

# What a Purchase Order's landed line may hold on disk: the nine, plus the two
# keys the board itself once wrote and the decision renames on READ. See
# `is_stored_po_charge_type` for why this is not the alias table.
PO_CHARGE_TYPE_KEYS: frozenset[str] = frozenset(CHARGE_TYPE_KEYS) | {"broker", "loading"}


def _normalise(value) -> str:
	return str(value or "").strip().lower()


def canonical_charge_type(value) -> str:
	"""The canonical key for a stored charge type. Never raises, never empty."""
	return _ALIASES.get(_normalise(value), FALLBACK_CHARGE_TYPE)


def is_known_charge_type(value) -> bool:
	"""True when the alias table recognises the stored string."""
	return _normalise(value) in _ALIASES


def is_stored_po_charge_type(value) -> bool:
	"""True when a Purchase Order landed line may PERSIST `value` as its `type`.

	Narrower than `is_known_charge_type` on purpose. That answers "does the
	reader understand this?" and takes the whole alias table -- including the
	quotation spellings ("Freight", "Handling & Terminal") and the VAT ones,
	which are values only a Supplier Quotation ever stored. A PO `type` is a KEY
	and this is the WRITE path behind a whitelisted endpoint, so it decides what
	a POST can put on disk: gating it on the alias table let a caller persist
	`"vat"`, which no board can produce and which `lcv_math.is_vat_component`
	matches on a substring, quietly dropping the line from the landed cost
	voucher. The nine, plus the two legacy keys `PoControlBoard.vue` itself
	wrote -- exactly the eleven `tender._CHARGE_TYPES` held before ADR-606.
	"""
	return _normalise(value) in PO_CHARGE_TYPE_KEYS


def is_vat_charge_type(value) -> bool:
	"""True for a line stored under the type VAT used to be (IAS 2 §11)."""
	return _normalise(value) in _VAT_ALIASES


def resolve_charge_type(value) -> tuple[str, str]:
	"""(canonical key, the text the table did not recognise).

	The second half is what stops a rename from deleting the officer's words. A
	quotation charge type is free text on disk -- "Local Delivery", "Freight &
	Customs" -- and mapping it to `other` and stopping there would leave a line
	reading "Other" with nothing to say what it was. It is empty whenever the
	value IS recognised, so a legacy `Freight` line does not grow a description
	saying "Freight".
	"""
	if is_known_charge_type(value):
		return canonical_charge_type(value), ""
	return FALLBACK_CHARGE_TYPE, str(value or "").strip()


def charge_type_label(key) -> str:
	"""The English label for a canonical key; the key itself when unknown."""
	for entry in CHARGE_TYPES:
		if entry["key"] == key:
			return entry["label"]
	return str(key or "")
