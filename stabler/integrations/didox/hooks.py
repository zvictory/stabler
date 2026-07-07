"""doc_events glue for Didox (not wired — manual send only).

Unlike ``ehf/hooks.py``, this is intentionally NOT registered on
`Sales Invoice.on_submit` in `stabler/hooks.py`. The user chose a manual
"Send to Didox" button in the SPA (accounting reviews before sending),
so this function exists for future use if automatic submission is ever
requested, but nothing currently calls it.

If wired later, it should enqueue prepare_for_invoice() only — send_signed()
cannot run here because signing happens in the browser via the user's own
E-IMZO key and requires a round trip through stabler.api.edo.didox_send.
"""

from __future__ import annotations

import frappe


def enqueue_didox_submit(doc, method=None):  # noqa: ARG001 — Frappe signature
    if not doc or doc.docstatus != 1:
        return
    frappe.enqueue(
        "stabler.integrations.didox.submit.prepare_for_invoice",
        queue="long",
        name=doc.name,
        now=False,
    )
