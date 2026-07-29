"""Add CRM daily-work fields without changing existing deal behavior."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("DocType", "CRM Deal"):
		return

	create_custom_fields(
		{
			"CRM Deal": [
				{"fieldname": "deal_type", "label": "Deal Type", "fieldtype": "Select", "options": "Standard\nTender", "default": "Standard", "insert_after": "company"},
				{"fieldname": "next_action_type", "label": "Next Action Type", "fieldtype": "Select", "options": "\nCall\nEmail\nMeeting\nTask\nOther", "insert_after": "deal_type"},
				{"fieldname": "next_action_at", "label": "Next Action At", "fieldtype": "Datetime", "insert_after": "next_action_type"},
				{"fieldname": "next_action_owner", "label": "Next Action Owner", "fieldtype": "Link", "options": "User", "insert_after": "next_action_at"},
				{"fieldname": "stage_entered_at", "label": "Stage Entered At", "fieldtype": "Datetime", "read_only": 1, "insert_after": "next_action_owner"},
				{"fieldname": "won_at", "label": "Won At", "fieldtype": "Datetime", "read_only": 1, "insert_after": "stage_entered_at"},
				{"fieldname": "lost_at", "label": "Lost At", "fieldtype": "Datetime", "read_only": 1, "insert_after": "won_at"},
				{"fieldname": "loss_reason", "label": "Loss Reason", "fieldtype": "Small Text", "insert_after": "lost_at"},
				{"fieldname": "forecast_category", "label": "Forecast Category", "fieldtype": "Select", "options": "\nPipeline\nBest Case\nCommit\nClosed", "insert_after": "loss_reason"},
			]
		},
		ignore_validate=True,
	)
