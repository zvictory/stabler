import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";
import { getStatusBadgeClass } from "../composables/status.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/rfq/RfqDetail.vue"), "utf8");
const listSrc = readFileSync(resolve(here, "../pages/tender/rfq/RfqList.vue"), "utf8");
const moduleSrc = readFileSync(resolve(here, "../composables/rfqStatus.js"), "utf8");

/**
 * UAT G.13 (RU walk, steps 06d/06e): the RFQ detail header kept showing the
 * "Draft" badge after the user clicked "Mark as sent". `mark_rfq_sent`
 * (sourcing.py) never submits the RFQ -- it only logs a Communication, by
 * design (Stabler's draft-and-stop philosophy) -- so `docstatus` alone can
 * never distinguish "drafted" from "drafted and handed to suppliers". The
 * server now answers `sent_count`/`sent_on` on `get_rfq`; `rfqStatusBadge`
 * is the one place that turns them into what the header actually draws.
 *
 * Review follow-up (P2): `rfqStatusBadge` used to be a page-local function in
 * RfqDetail.vue with a hardcoded "bg-green-lt text-green" class, in violation
 * of the "Centralized status codes" rule (10-frontend.md) -- every badge must
 * resolve through `getStatusBadgeClass`. It now lives in
 * composables/rfqStatus.js, so the extraction below points there instead.
 *
 * Executed, not grepped -- same shape as rfqDetailTargetRate.spec.js.
 * `getStatusBadgeClass` is the REAL one (composables/status.js), not a stand-
 * in: the "Sent" class must come from STATUS_MAP's own entry, so the test can
 * only go green once that entry exists. `t`/`getDocstatusLabel` stay faked to
 * keep the Draft/Submitted/Cancelled assertions decoupled from whatever
 * locale tests/setup.js's fixture happens to translate them to.
 */
function braceMatched(source, from) {
	let depth = 0;
	for (let i = from; i < source.length; i++) {
		if (source[i] === "{") depth++;
		else if (source[i] === "}" && --depth === 0) return source.slice(from, i + 1);
	}
	throw new Error("unterminated block");
}

function extractFunction(source, name) {
	const at = source.indexOf(`function ${name}(`);
	expect(at, `${name} is gone — has it moved or been renamed?`).toBeGreaterThan(-1);
	// `markSent` is declared `async function markSent() {` -- the marker above
	// starts matching at "function", so the "async " prefix has to be restored
	// by hand or `new Function` compiles a sync body containing `await`.
	const isAsync = source.slice(0, at).trimEnd().endsWith("async");
	const braceStart = source.indexOf("{", at);
	const body = source.slice(at, braceStart) + braceMatched(source, braceStart);
	return isAsync ? `async ${body}` : body;
}

// `rfqStatusBadge` closes over the three imports composables/rfqStatus.js
// itself uses; stand in `t`/`getDocstatusLabel` (so a label assertion cannot
// drift onto whatever tests/setup.js's fixture translates "Draft" to) but
// inject the REAL `getStatusBadgeClass` so the "Sent" class can only resolve
// once STATUS_MAP actually carries the entry.
function loadRfqStatusBadge() {
	const t = (s) => s;
	const getDocstatusLabel = (docstatus) => {
		if (docstatus === 0) return "Draft";
		if (docstatus === 1) return "Submitted";
		if (docstatus === 2) return "Cancelled";
		return String(docstatus);
	};
	const factory = new Function(
		"t",
		"getDocstatusLabel",
		"getStatusBadgeClass",
		`${extractFunction(moduleSrc, "rfqStatusBadge")}\nreturn rfqStatusBadge;`
	);
	return factory(t, getDocstatusLabel, getStatusBadgeClass);
}

describe("rfqStatusBadge decides the RFQ status badge (shared by list and detail)", () => {
	it("keeps the Draft badge for a draft RFQ that was never marked sent", () => {
		const badge = loadRfqStatusBadge()({ docstatus: 0, sent_count: 0 });
		expect(badge).toEqual({ label: "Draft", badgeClass: "bg-yellow-lt" });
	});

	it("switches a draft RFQ to Sent, with a positive badge class, once it has been marked sent", () => {
		// This is the bug: docstatus stays 0 after mark_rfq_sent, so without
		// sent_count the badge had no way to ever say anything but "Draft".
		const badge = loadRfqStatusBadge()({ docstatus: 0, sent_count: 1 });
		expect(badge.label).toBe("Sent");
		// Centralized status codes (10-frontend.md): the class must come from
		// STATUS_MAP's own "Request for Quotation" entry now, not a hardcoded
		// per-page literal -- the same positive family the suppliers table
		// uses for "Received", but resolved through the one place status
		// classes are decided.
		expect(badge.badgeClass).toBe("bg-green-lt");
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

describe("RfqDetail.vue and RfqList.vue both resolve the badge through composables/rfqStatus.js", () => {
	it("RfqDetail imports the shared rfqStatusBadge instead of defining its own", () => {
		expect(src).toMatch(/import\s*\{\s*rfqStatusBadge\s*\}\s*from\s*["'].*composables\/rfqStatus\.js["']/);
		expect(src).not.toMatch(/function rfqStatusBadge\(/);
	});

	it("RfqList imports the shared rfqStatusBadge instead of resolving docstatus on its own (P3)", () => {
		// UAT gap this closes: RfqList rendered raw `docstatus` and showed
		// "Draft" for the same RFQ RfqDetail already read as "Sent".
		expect(listSrc).toMatch(/import\s*\{\s*rfqStatusBadge\s*\}\s*from\s*["'].*composables\/rfqStatus\.js["']/);
	});

	it("RfqList's status cell renders the label and class from rfqStatusBadge(r), not getDocstatusLabel/getStatusBadgeClass", () => {
		const at = listSrc.indexOf('<span class="badge" :class="rfqStatusBadge(r)');
		expect(at, "the status badge span is gone, moved, or still resolves docstatus directly").toBeGreaterThan(-1);
		const cell = listSrc.slice(at, listSrc.indexOf("</td>", at));
		expect(cell).toContain("rfqStatusBadge(r).badgeClass");
		expect(cell).toContain("rfqStatusBadge(r).label");
		expect(cell).not.toMatch(/getDocstatusLabel|getStatusBadgeClass/);
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
		`${extractFunction(src, "markSent")}\nreturn markSent;`
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
