import { t } from "./i18n.js";

export const STATUS_MAP = {
	"Proforma Invoice": {
		DRAFT: "bg-secondary-lt",
		CONFIRMED: "bg-blue-lt",
		SUPERSEDED_BY_CI: "bg-green-lt",
		CANCELLED: "bg-red-lt",
	},
	"Advance Aging": { OK: "bg-green-lt", WARN: "bg-yellow-lt", BREACH: "bg-red-lt" },
	// How far a Commercial Invoice line drifts from the Proforma it ships
	// against. `error` = the line's key is on no PI at all; `warn` = a column
	// (price, quantity arithmetic) disagrees; `info` = a compensated bundle was
	// split into sub-cuts, which is expected.
	"PI Compliance": { error: "bg-red-lt", warn: "bg-yellow-lt", info: "bg-azure-lt" },
	"Budget Variance": {
		favorable: "bg-green-lt",
		unfavorable: "bg-red-lt",
		on_budget: "bg-secondary-lt",
	},
	"Attendance Status": {
		present: "bg-green-lt",
		late_flat: "bg-yellow-lt",
		late_step: "bg-orange-lt",
		half_day: "bg-azure-lt",
		absent: "bg-red-lt",
		holiday: "bg-purple-lt",
	},
	"Gate Device": {
		Active: "bg-green-lt",
		Paused: "bg-yellow-lt",
		Error: "bg-red-lt",
	},
	"Device Mapping": {
		Active: "bg-green-lt",
		Inactive: "bg-secondary-lt",
	},
	"Raw Gate Event": {
		Pending: "bg-yellow-lt",
		Processed: "bg-green-lt",
		Duplicate: "bg-secondary-lt",
		Unmatched: "bg-orange-lt",
		Error: "bg-red-lt",
	},
	"Attendance Exception": {
		Open: "bg-yellow-lt",
		Resolved: "bg-green-lt",
		Ignored: "bg-secondary-lt",
	},
	"Correction Status": {
		Draft: "bg-secondary-lt",
		Pending: "bg-yellow-lt",
		Approved: "bg-green-lt",
		Rejected: "bg-red-lt",
		Applied: "bg-blue-lt",
	},
	"Summary Status": {
		Draft: "bg-secondary-lt",
		Ready: "bg-azure-lt",
		Locked: "bg-green-lt",
	},
	"Employee": {
		Active: "bg-success-lt",
		Inactive: "bg-secondary-lt",
		Suspended: "bg-yellow-lt",
		Left: "bg-red-lt",
	},
	// Customer hierarchy job/location status (child customers only).
	"Customer": {
		Active: "bg-green-lt",
		Completed: "bg-blue-lt",
		"On Hold": "bg-yellow-lt",
		Cancelled: "bg-secondary-lt",
	},
	"Sales Order": {
		Draft: "bg-secondary-lt",
		"To Deliver and Bill": "bg-yellow-lt",
		"To Bill": "bg-orange-lt",
		"To Deliver": "bg-blue-lt",
		Completed: "bg-green-lt",
		Cancelled: "bg-red-lt",
		Closed: "bg-secondary-lt",
		"On Hold": "bg-purple-lt",
	},
	"Purchase Order": {
		Draft: "bg-secondary-lt",
		"To Receive and Bill": "bg-yellow-lt",
		"To Bill": "bg-orange-lt",
		"To Receive": "bg-blue-lt",
		Completed: "bg-green-lt",
		Cancelled: "bg-red-lt",
		Closed: "bg-secondary-lt",
		"On Hold": "bg-purple-lt",
	},
	"Sales Invoice": {
		Paid: "bg-green-lt",
		Unpaid: "bg-yellow-lt",
		Overdue: "bg-red-lt",
		Return: "bg-secondary-lt",
		"Credit Note Issued": "bg-purple-lt",
		"Partly Paid": "bg-blue-lt",
		Draft: "bg-secondary-lt",
	},
	"Purchase Invoice": {
		Paid: "bg-green-lt",
		Unpaid: "bg-yellow-lt",
		Overdue: "bg-red-lt",
		Return: "bg-secondary-lt",
		"Credit Note Issued": "bg-purple-lt",
		"Partly Paid": "bg-blue-lt",
		Draft: "bg-secondary-lt",
	},
	// Imports — Import Order (native PO) derived lifecycle badge (WP8, never stored).
	"Import Order": {
		DRAFT: "bg-secondary-lt",
		CONFIRMED: "bg-blue-lt",
		ADVANCE_PAID: "bg-purple-lt",
		SHIPPING: "bg-azure-lt",
		COMPLETED: "bg-green-lt",
		CANCELLED: "bg-red-lt",
	},
	// Import Order advance-payment badge (advance_paid vs prepayment base).
	"Import Order Payment": {
		PAID: "bg-green-lt",
		PARTIAL: "bg-blue-lt",
		NOT_PAID: "bg-orange-lt",
	},
	// Imports — Commercial Invoice / Import Container share the 9-status logistics pipeline.
	"Commercial Invoice": {
		BOOKED: "bg-secondary-lt",
		STUFFED: "bg-blue-lt",
		GATE_IN: "bg-azure-lt",
		ON_BOARD: "bg-blue-lt",
		IN_TRANSIT: "bg-purple-lt",
		DISCHARGED: "bg-teal-lt",
		AVAILABLE: "bg-orange-lt",
		ARRIVED_AT_IRAN: "bg-yellow-lt",
		DELIVERED_TO_UZBEKISTAN: "bg-green-lt",
		Cancelled: "bg-red-lt",
	},
	"Import Container": {
		BOOKED: "bg-secondary-lt",
		STUFFED: "bg-blue-lt",
		GATE_IN: "bg-azure-lt",
		ON_BOARD: "bg-blue-lt",
		IN_TRANSIT: "bg-purple-lt",
		DISCHARGED: "bg-teal-lt",
		AVAILABLE: "bg-orange-lt",
		ARRIVED_AT_IRAN: "bg-yellow-lt",
		DELIVERED_TO_UZBEKISTAN: "bg-green-lt",
		Cancelled: "bg-red-lt",
	},
	"Import Truck": {
		PENDING: "bg-secondary-lt",
		DEPARTED_IRAN: "bg-blue-lt",
		AT_BORDER: "bg-azure-lt",
		CROSSED_BORDER: "bg-purple-lt",
		IN_TRANSIT: "bg-blue-lt",
		ARRIVED: "bg-teal-lt",
		UNLOADING: "bg-orange-lt",
		GRN_CREATED: "bg-yellow-lt",
		COMPLETED: "bg-green-lt",
		Cancelled: "bg-red-lt",
	},
	// Imports receiving (WP6a) — GRN Checklist header progress status.
	"GRN Checklist": {
		Pending: "bg-secondary-lt",
		Receiving: "bg-blue-lt",
		Complete: "bg-green-lt",
		Discrepancy: "bg-red-lt",
	},
	// GRN variance band — colour follows severity (±2/5/10 thresholds).
	"GRN Variance Category": {
		NORMAL: "bg-green-lt",
		MINOR: "bg-yellow-lt",
		MAJOR: "bg-orange-lt",
		CRITICAL: "bg-red-lt",
	},
	// Per-line GRN item receiving status.
	"GRN Checklist Item": {
		Pending: "bg-secondary-lt",
		Partial: "bg-blue-lt",
		Complete: "bg-green-lt",
		Discrepancy: "bg-red-lt",
	},
	"Vet Certificate": {
		Pending: "bg-yellow-lt",
		Approved: "bg-green-lt",
		Rejected: "bg-red-lt",
		Expired: "bg-secondary-lt",
	},
	// Imports documents (WP6b).
	"Customs Declaration": {
		Draft: "bg-secondary-lt",
		Submitted: "bg-blue-lt",
		"Under Review": "bg-yellow-lt",
		Approved: "bg-green-lt",
		Rejected: "bg-red-lt",
	},
	"Freight Booking": {
		Pending: "bg-secondary-lt",
		Booked: "bg-blue-lt",
		"In Transit": "bg-purple-lt",
		Delivered: "bg-green-lt",
		Cancelled: "bg-red-lt",
	},
	"Import Expense": {
		Pending: "bg-yellow-lt",
		Partial: "bg-blue-lt",
		Paid: "bg-green-lt",
	},
	"Stabler Approval Request": {
		Pending: "bg-yellow-lt",
		Approved: "bg-green-lt",
		Rejected: "bg-red-lt",
		Cancelled: "bg-secondary-lt",
	},
	"Stabler Bank Import": {
		Imported: "bg-green-lt",
		Partial: "bg-yellow-lt",
		Failed: "bg-red-lt",
	},
	"Stabler Process": {
		Draft: "bg-secondary-lt",
		Active: "bg-green-lt",
	},
	"Promo Plan": {
		Draft: "bg-yellow-lt",
		Planned: "bg-yellow-lt",
		Active: "bg-success-lt",
		Closed: "bg-secondary-lt",
	},
	"Marketing Claim": {
		Pending: "bg-yellow-lt",
		UnderReview: "bg-blue-lt",
		Approved: "bg-success-lt",
		Paid: "bg-teal-lt",
		Rejected: "bg-red-lt",
	},
	"Salary Slip": {
		Draft: "bg-secondary-lt",
		Submitted: "bg-success-lt",
		Withheld: "bg-yellow-lt",
		Cancelled: "bg-secondary-lt",
	},
	"EDO Status": {
		Draft: "bg-secondary-lt",
		Signed: "bg-blue-lt",
		Sent: "bg-azure-lt",
		Accepted: "bg-success-lt",
		Rejected: "bg-red-lt",
		Error: "bg-red-lt",
	},
	"EHF Status": {
		Pending: "bg-yellow-lt",
		Submitted: "bg-azure-lt",
		Accepted: "bg-success-lt",
		Rejected: "bg-red-lt",
		Error: "bg-red-lt",
	},
	"1C Sync": {
		Pending: "bg-yellow-lt",
		OK: "bg-success-lt",
		Error: "bg-red-lt",
	},
	"Installment Schedule State": {
		paid: "bg-green-lt",
		partial: "bg-yellow-lt",
		overdue: "bg-red-lt",
		upcoming: "bg-blue-lt",
	},
	"docstatus": {
		0: "bg-yellow-lt", // Draft
		1: "bg-green-lt",  // Submitted / Active
		2: "bg-red-lt",    // Cancelled
	}
};

export function getStatusBadgeClass(doctype, status) {
	if (typeof status === "number") {
		return STATUS_MAP.docstatus[status] || "bg-secondary-lt";
	}
	const doctypeMap = STATUS_MAP[doctype];
	if (doctypeMap && status in doctypeMap) {
		return doctypeMap[status];
	}
	const genericMap = {
		Draft: "bg-secondary-lt",
		Submitted: "bg-green-lt",
		Cancelled: "bg-red-lt",
		Paid: "bg-green-lt",
		Unpaid: "bg-yellow-lt",
		Overdue: "bg-red-lt",
		Completed: "bg-green-lt",
		Open: "bg-blue-lt",
		Closed: "bg-secondary-lt",
		"Partly Billed": "bg-orange-lt",
		"Return Issued": "bg-red-lt",
		"Unpaid and Discounted": "bg-yellow-lt",
		"Debit Note Issued": "bg-purple-lt",
	};
	return genericMap[status] || "bg-secondary-lt";
}

export function getDocstatusLabel(docstatus) {
	if (docstatus === 0) return t("Draft");
	if (docstatus === 1) return t("Submitted");
	if (docstatus === 2) return t("Cancelled");
	return String(docstatus);
}
