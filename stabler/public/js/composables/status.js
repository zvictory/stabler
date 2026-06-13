import { t } from "./i18n.js";

export const STATUS_MAP = {
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
