import { call } from "./client.js";

// The remittance engine, whole. Reads live in `remittance_queries`, mutations in
// `remittance_commands`; both are re-exported from one object so a screen imports
// one thing and never has to know which Python module answers.
//
// This module existed first as a fence: it deliberately excluded the JE-only
// endpoints in `stabler.api.remittance` so no V1 screen could reach one by
// accident. That engine was retired on 2026-08-20 with no tenant running it, so
// the fence has nothing left to keep out — but the shape it produced, one import
// per screen, is why every screen still reads this way.
//
// Parameter names below are the Python signatures verbatim: Frappe binds POST
// form keys to keyword arguments by name, so a renamed key is a TypeError at the
// server, not a lint error here.
const READ = "stabler.api.remittance_queries";
const CMD = "stabler.api.remittance_commands";

// Wire values, not labels. These are the queue identifiers
// `remittance_queries.QUEUES` branches on and the action identifiers
// `_remittance_actions.ACTIONS` hands back on every row — deliberately
// untranslated, because a Russian browser and a Turkish browser have to agree
// about what the server offered. Render the human label from these, never the
// other way round.
export const REMITTANCE_QUEUES = Object.freeze({
	READY_FOR_PAYOUT: "ready_for_payout",
	EXPIRING_12H: "expiring_12h",
	EXPIRED_REFUND_REQUIRED: "expired_refund_required",
	REFUND_AWAITING_APPROVAL: "refund_awaiting_approval",
	LOCKED_PICKUP_CODE: "locked_pickup_code",
	ACCOUNTING_EXCEPTION: "accounting_exception",
});

export const REMITTANCE_ACTIONS = Object.freeze({
	PAYOUT: "payout",
	UNLOCK_PICKUP_CODE: "unlock_pickup_code",
	REQUEST_REFUND: "request_refund",
	APPROVE_REFUND: "approve_refund",
	REJECT_REFUND: "reject_refund",
	COMPLETE_REFUND: "complete_refund",
});

// Frappe's `cint("true")` is 0, and `client.js` stringifies every value it
// sends — so a raw JS boolean on a Check-shaped argument arrives as the string
// "true" and reads as false. Send the digit.
function checkbox(value) {
	if (value === undefined || value === null || value === "") return undefined;
	return value ? 1 : 0;
}

export const remittanceApi = {
	// ----------------------------------------------------------------- reads --
	// Scorecards plus the count of all six queues, for one company. Money comes
	// back as per-currency rows and never as a total: USD, EUR and USDT are not
	// added together anywhere in this product. Pass `currency` to narrow to one
	// send-leg currency.
	operationsSummary: (company, currency = null, desk = null) =>
		call(`${READ}.operations_summary`, { company, currency, desk }),

	// One of the six queues, paged. `queue` must be a REMITTANCE_QUEUES value.
	//
	// Read `policy_configured` before rendering an empty state: the two expiry
	// queues answer `false` because nothing writes `expires_at` yet, and the
	// screen must say "no expiry policy is configured" rather than "nothing is
	// expiring" — those are opposite claims and only one is true.
	//
	// `currency` narrows the send leg and `desk` narrows to one cash desk on
	// either leg — the same two the summary takes, so one filter bar can drive
	// both without a tile counting rows the list below is not showing.
	workQueue: (company, queue, limit = 50, offset = 0, currency = null, desk = null) =>
		call(`${READ}.work_queue`, { company, queue, limit, offset, currency, desk }),

	// The company's configured cash desks. One spelling for every screen that
	// offers a desk — the New Transfer form picks an origin and a destination from
	// this, Operations filters by it. `Remittance Settings` is a Single per
	// company, so `parent` is the company name.
	cashDesks: (company) =>
		call("frappe.client.get_list", {
			doctype: "Remittance Cash Desk Account",
			parent: "Remittance Settings",
			filters: { parenttype: "Remittance Settings", parent: company },
			fields: ["branch", "city", "currency"],
			limit_page_length: 0,
			order_by: "idx asc",
		}),

	// The searchable transfer list. Takes one options object because it carries
	// nine arguments and a positional call would silently transpose two of them.
	// `query` matches reference / sender / receiver / desk; `status` is the
	// operational axis; `has_exception` narrows to the accounting exceptions
	// (pass false to exclude them, omit to ignore the axis).
	transfers: ({
		company,
		query = null,
		status = null,
		currency = null,
		from_date = null,
		to_date = null,
		has_exception = null,
		limit = 50,
		offset = 0,
	}) =>
		call(`${READ}.transfers`, {
			company,
			query,
			status,
			currency,
			from_date,
			to_date,
			has_exception: checkbox(has_exception),
			limit,
			offset,
		}),

	// One transfer in full: the frozen quote, all four status axes kept apart,
	// the append-only stage timeline, the linked Journal Entries, the refund
	// trail and the audit stamps.
	//
	// `code_state` on the response is the ATTEMPT COUNTER and the lockout, never
	// the code. No read path in this product returns the code or its digest — the
	// plaintext is shown exactly once, by the register receipt. The block is named
	// `code_state` rather than `pickup_code` because the server's response guard
	// refuses that key outright, whatever it holds.
	transferDetail: (name) => call(`${READ}.transfer_detail`, { name }),

	// Register cash-in, open in-transit liability, payout/refund cash-out,
	// deferred vs earned commission, master-vs-JE variance and the aged set.
	// The flows respect the date window; the open liability is all-time on
	// purpose — an obligation does not stop being owed because you narrowed a
	// filter.
	reconciliation: (company, from_date = null, to_date = null) =>
		call(`${READ}.reconciliation`, { company, from_date, to_date }),

	// -------------------------------------------------------------- commands --
	// Take the cash, open the obligation, hand back the pickup code ONCE.
	// `client_request_id` is required and is the idempotency key: replaying it
	// with the same values returns the original transfer instead of registering a
	// second one, and replaying it with different values is refused. Generate it
	// once per attempt (crypto.randomUUID()) and reuse it across retries.
	//
	// `amount` is read against `commission_mode`: "Exclusive" means it is the
	// principal and commission is added on top, "Inclusive" means it is what the
	// sender hands over and commission comes out of it.
	//
	// The response carries `pickup_code` exactly once. It is never retrievable
	// again — show the receipt, then drop it.
	registerRemittance: (payload) => call(`${CMD}.register_remittance`, payload),

	// The cashier-facing payout queue from the command module, searchable by
	// remittance id, client request id or either party's name. `workQueue` with
	// REMITTANCE_QUEUES.READY_FOR_PAYOUT is the operations-screen equivalent and
	// carries the fuller row; this is the one the payout screen searches.
	payoutQueue: (company, query = null, limit = 50) =>
		call(`${CMD}.payout_queue`, { company, query, limit }),

	// Verify the receiver's code, close the obligation, hand over the cash.
	// A wrong code costs an attempt and eventually locks the transfer; only
	// `unlockPickupCode` reopens it.
	payoutTransfer: (name, pickup_code, client_request_id, posting_date = null) =>
		call(`${CMD}.payout_transfer`, { name, pickup_code, client_request_id, posting_date }),

	// Ask whether a code opens a transfer, without handing anything over, so the
	// Pay out button can be gated on a verified code instead of reporting a wrong
	// one after the click. It costs the same failed attempt a payout would: a free
	// check would be a brute-force oracle in front of the lockout.
	verifyPickupCode: (name, pickup_code, client_request_id) =>
		call(`${CMD}.verify_pickup_code`, { name, pickup_code, client_request_id }),

	// The journal entry a stage will write, built by the poster's own code so the
	// screen and the ledger cannot disagree. Read-only: no draft entry is created.
	postingPreview: (name, stage, posting_date = null) =>
		call(`${READ}.posting_preview`, { name, stage, posting_date }),

	// A Finance Manager reopens a locked code. The only exit from a lockout —
	// there is no timer, by design, so that a lockout that lapsed is never
	// mistaken for one that was never applied.
	unlockPickupCode: (name, reason = null) => call(`${CMD}.unlock_pickup_code`, { name, reason }),

	// Three steps, and only the last one moves money.
	// request → approve (or reject) → complete.
	requestRefund: (name, reason, client_request_id) =>
		call(`${CMD}.request_refund`, { name, reason, client_request_id }),

	approveRefund: (name, client_request_id, note = null) =>
		call(`${CMD}.approve_refund`, { name, client_request_id, note }),

	rejectRefund: (name, reason, client_request_id) =>
		call(`${CMD}.reject_refund`, { name, reason, client_request_id }),

	// The step that posts: the cash is counted back out at the origin desk.
	completeRefund: (name, client_request_id, posting_date = null) =>
		call(`${CMD}.complete_refund`, { name, client_request_id, posting_date }),
};
