"""The procurement policy thresholds — one home, frappe-free.

A lot's pricing is defensible when it rests on at least `MIN_QUOTATIONS`
supplier quotations drawn from at least `MIN_COUNTRIES` countries. The award
gate (`Tender Sourcing Decision.validate`) refuses a short set without a written
exception; every other subsystem only *reports* against these numbers.

They live here rather than on the doctype because the doctype imports frappe,
and the pure derivation engines — `_desk_rules`, and anything else in
`.github/frappe-free-tests.txt` — cannot import frappe without taking
`make check` down. A canonical constant the reporters are unable to read is not
canonical; it is merely first. That is how the same threshold came to be spelled
in twenty places while the doctype's own docstring claimed it was named once.

Read them as module attributes (`policy.MIN_QUOTATIONS`), not by binding the
value at import time — the tests move the number to prove each reporter follows
it, and a bound copy would not.
"""

from __future__ import annotations

#: Minimum supplier quotations for a defensible lot.
MIN_QUOTATIONS = 5

#: Minimum distinct supplier countries across that set.
MIN_COUNTRIES = 2
