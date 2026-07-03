"""Patch v32: persist installment collection allocations for same-day cancel.

Adds a hidden `stabler_installment_alloc` Long Text on Payment Entry. The
collection endpoint writes a JSON snapshot of exactly which schedule rows a
collection covered (row_name, allocated_amount, previous paid/outstanding), so
`cancel_collection` can reverse precisely — newest-covered row first — even when
several collections landed against the same contract on the same day.

Idempotent: guarded by Custom Field existence.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    if not frappe.db.exists(
        "Custom Field", {"dt": "Payment Entry", "fieldname": "stabler_installment_alloc"}
    ):
        create_custom_fields(
            {
                "Payment Entry": [
                    {
                        "fieldname": "stabler_installment_alloc",
                        "label": "Stabler Installment Allocation",
                        "fieldtype": "Long Text",
                        "insert_after": "reference_no",
                        "hidden": 1,
                        "no_copy": 1,
                        "read_only": 1,
                    }
                ]
            },
            ignore_validate=True,
        )
