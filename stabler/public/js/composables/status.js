import { t } from "./i18n.js";

export const STATUS_MAP = {
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
