import { t } from "./i18n.js";

export const STATUS_MAP = {
	"Proforma Invoice": {
		DRAFT: "bg-secondary-lt",
		CONFIRMED: "bg-blue-lt",
		SUPERSEDED_BY_CI: "bg-green-lt",
		CANCELLED: "bg-red-lt",
	},
	"Advance Aging": { OK: "bg-green-lt", WARN: "bg-yellow-lt", BREACH: "bg-red-lt" },
	// Stopped and Cancelled are deliberately not the same grey: one is a halted
	// order somebody has to resume, the other is over. See `workOrderStatus.js`
	// for why each colour was chosen when the list and the detail page were
	// merged onto this entry.
	"Work Order": {
		Draft: "bg-secondary-lt",
		"Not Started": "bg-yellow-lt",
		"In Process": "bg-blue-lt",
		Completed: "bg-green-lt",
		Stopped: "bg-orange-lt",
		Closed: "bg-purple-lt",
		Cancelled: "bg-red-lt",
	},
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
	// Vehicle Agreement lifecycle. Without this block only Draft and Completed
	// resolved — the generic map at the bottom of this file carries no Review,
	// Approved, Active, Rescheduled, Restructured or Terminated — so six of the
	// eight states rendered bg-secondary-lt and the portfolio lifecycle strip
	// showed a terminated agreement as identical to a live one.
	// Active is blue, not green, because Completed is green by convention
	// everywhere else in this map; making both green would rebuild the same
	// can't-tell-them-apart defect one column over.
	// Rescheduled is orange on purpose: a re-cut schedule at the same total is
	// still collectible, but it is an exception to watch, not a healthy one, and
	// colouring it green hides the risk the reschedule was taken on to avoid.
	// Restructured is a different thing and must not share that colour: it is
	// TERMINAL, stamped on the original agreement when a restructure closes it
	// and opens a successor (docs/decisions/2026-08-16-restructure-closes-and-
	// reopens.md). Purple, because green would read as settled and red as failed
	// — the original was neither; it was superseded.
	"Vehicle Agreement": {
		Draft: "bg-secondary-lt",
		Review: "bg-yellow-lt",
		Approved: "bg-azure-lt",
		Active: "bg-blue-lt",
		Rescheduled: "bg-orange-lt",
		Restructured: "bg-purple-lt",
		Completed: "bg-green-lt",
		Terminated: "bg-red-lt",
	},
	// How something is PAYING, which is a different axis from where an agreement
	// is in its lifecycle ("Vehicle Agreement" above). Neither is a stored field;
	// both are derived in api/vehicle_finance/read.py, so these keys must stay in
	// step with two functions there:
	//   _agreement_schedule_state (read.py:103-110)  Not Started/Current/Partial/Overdue/Paid
	//   agreement_detail row health (read.py:312-319) Upcoming/Partial/Overdue/Paid
	//
	// ONE map for both granularities on purpose. The agreement badge in the list
	// and the row badges in the preview drawer sit inches apart, and the same
	// word rendered in two different reds would be a defect in itself.
	//
	// Note the agreement-level derivation is EXCLUSIVE and ordered: Paid, else
	// Overdue, else Partial, else Current. So an overdue agreement that has been
	// partly paid reports "Overdue" and never "Partial". That is the right
	// primary signal — overdue carries the urgency — but it means a screen that
	// also wants to say "partly paid" must derive that from paid/outstanding and
	// render it as a SECOND badge; it cannot come out of this map.
	//
	// Current and Upcoming are blue rather than green for the same reason Active
	// is blue in the lifecycle block: Paid is green, and making both green
	// rebuilds the can't-tell-them-apart defect one column over. Not Started is
	// grey because there is nothing to pay against until activation — it is an
	// absence, not a state of health.
	"Vehicle Finance Payment Health": {
		"Not Started": "bg-secondary-lt",
		Current: "bg-blue-lt",
		Upcoming: "bg-blue-lt",
		Partial: "bg-yellow-lt",
		Overdue: "bg-red-lt",
		Paid: "bg-green-lt",
	},
	// Tender Master board lanes. These are DERIVED from the child lots
	// (api/_tender_master_state.py), not typed by anyone — the keys must stay in
	// step with LANES there and in composables/tenderMaster.js.
	"Tender Lane": {
		Preparation: "bg-secondary-lt",
		Active: "bg-blue-lt",
		"Awaiting Result": "bg-yellow-lt",
		"Partial Result": "bg-orange-lt",
		Completed: "bg-green-lt",
	},
	// How much of a PI advance belongs to ONE Commercial Invoice. Derived in
	// api/imports.py:_ci_advance_share — not a stored status, so the three keys
	// must stay in step with the `state` values that function returns.
	"CI Advance Share": {
		Planned: "bg-yellow-lt",
		Reserved: "bg-orange-lt",
		Posted: "bg-green-lt",
	},
	// The four INDEPENDENT status axes of a Remittance Transfer. They are four
	// map entries and not one because they are four different questions: a
	// transfer can be "Paid Out" (operational) while its reversal is a "Posting
	// Error" (accounting), and a single palette shared between them would let a
	// green "Posted" be misread as a green "Paid Out". Keys are the doctype's own
	// Select options (remittance_transfer.json) — the server never invents a
	// fifth value, so a missing key here means the doctype changed.
	"Remittance Transfer": {
		Draft: "bg-secondary-lt",
		Registered: "bg-blue-lt",
		"Paid Out": "bg-green-lt",
		Refunded: "bg-purple-lt",
		Expired: "bg-orange-lt",
		Exception: "bg-red-lt",
	},
	"Remittance Accounting": {
		Unposted: "bg-yellow-lt",
		Posted: "bg-green-lt",
		Reversed: "bg-purple-lt",
		"Posting Error": "bg-red-lt",
	},
	// The state of the pickup code, never the code. "Locked" is red because it
	// blocks a payout at the counter and only a Finance Manager can clear it.
	"Remittance Verification": {
		"Not Issued": "bg-secondary-lt",
		Active: "bg-blue-lt",
		Locked: "bg-red-lt",
		Consumed: "bg-green-lt",
		Expired: "bg-orange-lt",
	},
	"Remittance Refund": {
		None: "bg-secondary-lt",
		Requested: "bg-yellow-lt",
		Approved: "bg-blue-lt",
		Rejected: "bg-red-lt",
		Completed: "bg-green-lt",
	},
	"docstatus": {
		0: "bg-yellow-lt", // Draft
		1: "bg-green-lt",  // Submitted / Active
		2: "bg-red-lt",    // Cancelled
	},
	// A draft RFQ that has been handed to suppliers (mark_rfq_sent logs a
	// Communication; it never submits the RFQ -- draft-and-stop). `status` is
	// the string "Sent" here, never a docstatus, so this needs its own entry:
	// getStatusBadgeClass's docstatus branch only fires for a NUMBER status.
	// composables/rfqStatus.js is the one reader.
	"Request for Quotation": {
		Sent: "bg-green-lt",
	},
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

/**
 * The badge class for a badge whose TEXT is `status`, falling back to `docstatus`
 * only when there is no status word to show.
 *
 * This lives here, and not in the two components that draw badges, because they
 * had already drifted apart: `StatusBadge` took the colour from the status
 * string, `FormPage` took it from docstatus while printing the status string.
 * The same submitted-and-overdue invoice was therefore red in a list and green
 * on its own form. A badge states one fact, so its colour and its word have to
 * come from the same input.
 *
 * `doctype` must be the real doctype name, never a page heading -- headings are
 * translated, and a translated heading silently misses STATUS_MAP entirely.
 */
export function resolveBadgeClass(doctype, status, docstatus) {
	if (status) {
		return getStatusBadgeClass(doctype, status);
	}
	return getStatusBadgeClass(doctype, docstatus);
}

export function getDocstatusLabel(docstatus) {
	if (docstatus === 0) return t("Draft");
	if (docstatus === 1) return t("Submitted");
	if (docstatus === 2) return t("Cancelled");
	return String(docstatus);
}
