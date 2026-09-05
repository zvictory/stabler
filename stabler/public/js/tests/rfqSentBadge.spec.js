import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/rfq/RfqDetail.vue"), "utf8");

/**
 * UAT G.13 (RU walk, steps 06d/06e): the RFQ detail header kept showing the
 * "Draft" badge after the user clicked "Mark as sent". `mark_rfq_sent`
 * (sourcing.py) never submits the RFQ -- it only logs a Communication, by
 * design (Stabler's draft-and-stop philosophy) -- so `docstatus` alone can
 * never distinguish "drafted" from "drafted and handed to suppliers". The
 * server now answers `sent_count`/`sent_on` on `get_rfq`; `rfqStatusBadge`
 * is the one place that turns them into what the header actually draws.
 *
 * Executed, not grepped -- same shape as rfqDetailTargetRate.spec.js.
 */
function braceMatched(from) {
	let depth = 0;
	for (let i = from; i < src.length; i++) {
		if (src[i] === "{") depth++;
		else if (src[i] === "}" && --depth === 0) return src.slice(from, i + 1);
	}
	throw new Error("unterminated block");
}

function extractFunction(name) {
	const at = src.indexOf(`function ${name}(`);
	expect(at, `${name} is gone — has it moved or been renamed?`).toBeGreaterThan(-1);
	// `markSent` is declared `async function markSent() {` -- the marker above
	// starts matching at "function", so the "async " prefix has to be restored
	// by hand or `new Function` compiles a sync body containing `await`.
	const isAsync = src.slice(0, at).trimEnd().endsWith("async");
	const braceStart = src.indexOf("{", at);
	const body = src.slice(at, braceStart) + braceMatched(braceStart);
	return isAsync ? `async ${body}` : body;
}

// `rfqStatusBadge` closes over the three imports every other badge on this
// page already uses; stand them in so the mocks and the real STATUS_MAP
// docstatus map (status.js) cannot silently drift apart.
function loadRfqStatusBadge() {
	const t = (s) => s;
	const getDocstatusLabel = (docstatus) => {
		if (docstatus === 0) return "Draft";
		if (docstatus === 1) return "Submitted";
		if (docstatus === 2) return "Cancelled";
		return String(docstatus);
	};
	// Mirrors composables/status.js: a NUMBER status resolves purely off the
	// docstatus map and ignores doctype -- there is no "Request for Quotation"
	// entry in STATUS_MAP, so the real function cannot be asked for "Sent"
	// this way. That is exactly why the fallback below has to exist.
	const getStatusBadgeClass = (_doctype, status) =>
		({ 0: "bg-yellow-lt", 1: "bg-green-lt", 2: "bg-red-lt" })[status] || "bg-secondary-lt";
	const factory = new Function(
		"t",
		"getDocstatusLabel",
		"getStatusBadgeClass",
		`${extractFunction("rfqStatusBadge")}\nreturn rfqStatusBadge;`
	);
	return factory(t, getDocstatusLabel, getStatusBadgeClass);
}

describe("rfqStatusBadge decides the RFQ detail header badge", () => {
	it("keeps the Draft badge for a draft RFQ that was never marked sent", () => {
		const badge = loadRfqStatusBadge()({ docstatus: 0, sent_count: 0 });
		expect(badge).toEqual({ label: "Draft", badgeClass: "bg-yellow-lt" });
	});

	it("switches a draft RFQ to Sent, with a positive badge class, once it has been marked sent", () => {
		// This is the bug: docstatus stays 0 after mark_rfq_sent, so without
		// sent_count the badge had no way to ever say anything but "Draft".
		const badge = loadRfqStatusBadge()({ docstatus: 0, sent_count: 1 });
		expect(badge.label).toBe("Sent");
		// No "Sent" entry exists in STATUS_MAP for this doctype, so this must
		// be the same positive class family the suppliers table already uses
		// for "Received" (bg-green-lt text-green), not the fallback grey.
		expect(badge.badgeClass).toBe("bg-green-lt text-green");
	});

	it("still reads Sent when the RFQ was marked sent more than once", () => {
		const badge = loadRfqStatusBadge()({ docstatus: 0, sent_count: 3 });
		expect(badge.label).toBe("Sent");
	});

	it("leaves a submitted RFQ's badge exactly as before, regardless of sent_count", () => {
		const badge = loadRfqStatusBadge()({ docstatus: 1, sent_count: 2 });
		expect(badge).toEqual({ label: "Submitted", badgeClass: "bg-green-lt" });
	});

	it("leaves a cancelled RFQ's badge exactly as before, regardless of sent_count", () => {
		const badge = loadRfqStatusBadge()({ docstatus: 2, sent_count: 1 });
		expect(badge).toEqual({ label: "Cancelled", badgeClass: "bg-red-lt" });
	});
});

// markSent closes over these refs/helpers; stand them in as plain { value }
// boxes the same way rfqDetailTargetRate.spec.js and
// sourcingAddQuotationEvent.spec.js already do for this file's other handlers.
function buildMarkSent({ marking, rfq, call, sendChannel, activeCompany, toast, t, load }) {
	const factory = new Function(
		"marking",
		"rfq",
		"call",
		"sendChannel",
		"activeCompany",
		"toast",
		"t",
		"load",
		`${extractFunction("markSent")}\nreturn markSent;`
	);
	return factory(marking, rfq, call, sendChannel, activeCompany, toast, t, load);
}

describe("RfqDetail.markSent refreshes the page after a successful send", () => {
	function deps(overrides = {}) {
		return {
			marking: { value: false },
			rfq: { value: { name: "RFQ-1" } },
			call: vi
				.fn()
				.mockResolvedValue({ communication: "COMM-1", rfq: "RFQ-1", channel: "whatsapp" }),
			sendChannel: { value: "whatsapp" },
			activeCompany: { value: "ACME" },
			toast: { success: vi.fn(), error: vi.fn() },
			t: (s) => s,
			load: vi.fn().mockResolvedValue(undefined),
			...overrides,
		};
	}

	it("re-fetches the RFQ so the badge updates without a manual reload", async () => {
		// Before the fix: markSent toasted success and left `rfq.value` (hence
		// the badge) exactly as it was before the click -- the UAT bug.
		const d = deps();
		await buildMarkSent(d)();
		expect(d.call).toHaveBeenCalledWith("stabler.api.sourcing.mark_rfq_sent", {
			name: "RFQ-1",
			channel: "whatsapp",
			company: "ACME",
		});
		expect(d.load).toHaveBeenCalledTimes(1);
		expect(d.toast.success).toHaveBeenCalled();
		expect(d.marking.value).toBe(false);
	});

	it("does not refresh, and surfaces the error, when the server call fails", async () => {
		const d = deps({ call: vi.fn().mockRejectedValue(new Error("boom")) });
		await buildMarkSent(d)();
		expect(d.load).not.toHaveBeenCalled();
		expect(d.toast.error).toHaveBeenCalled();
		expect(d.marking.value).toBe(false);
	});
});
