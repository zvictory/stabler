"""Add batch/lot traceability fields to Work Order (Faz 4a).

One Work Order == one production batch for a batch producer (e.g. anjan
ice-cream). These informational custom fields stamp the lot number, its
manufacture date and expiry on the finished Work Order, giving forward/
backward traceability without touching ERPNext's Batch/Bundle stock engine.

Idempotent: create_custom_fields with update=True is a no-op if the fields
already exist. Fields are optional (never reqd), so tenants that carry the
Work Order doctype but don't produce batches are unaffected.
"""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute() -> None:
    create_custom_fields(
        {
            "Work Order": [
                {
                    "fieldname": "custom_batch_no",
                    "label": "Batch / lot",
                    "fieldtype": "Data",
                    "insert_after": "operator",
                    "allow_on_submit": 1,
                    "description": "Production batch/lot number for this Work Order",
                },
                {
                    "fieldname": "custom_batch_mfg_date",
                    "label": "Batch manufacture date",
                    "fieldtype": "Date",
                    "insert_after": "custom_batch_no",
                    "allow_on_submit": 1,
                },
                {
                    "fieldname": "custom_batch_expiry",
                    "label": "Batch expiry",
                    "fieldtype": "Date",
                    "insert_after": "custom_batch_mfg_date",
                    "allow_on_submit": 1,
                },
            ],
        },
        update=True,
    )
