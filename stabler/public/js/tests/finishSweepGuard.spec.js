import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(
	resolve(here, "../pages/manufacturing/ManufacturingOperatorBoard.vue"),
	"utf8"
);

/**
 * Finishing an order posts a Manufacture entry, and ERPNext builds that entry
 * from everything still unconsumed on the Work Order — the other operator's
 * material included. `Work Order Item.consumed_qty` is a running accumulator
 * that records whatever entry names the line, so whoever presses Finish first
 * takes the absent colleague's material onto their own document, and the
 * deviation panel then scores a shift that person never worked. Measured on
 * genesis-test 2026-08-25: MAT-STE-2026-00037, PROBE-LABEL consumed_qty
 * 0.0 -> 10.0 on the pourer's entry, the packer clean for an order he never
 * touched.
 *
 * `_assert_sweep_is_acknowledged` refuses that server-side. These tests cover
 * the half that makes the refusal usable instead of a wall: the operator is
 * shown the list up front and has to make one deliberate gesture. Without the
 * gesture the refusal has no exit and the shift stops.
 *
 * Same constraint as operatorWriteOffGate.spec.js — @vue/test-utils is not a
 * devDependency, so the component is not mounted. The :disabled expression is
 * pulled out of the shipped SFC and EXECUTED; a toContain() assertion passes
 * just as happily on a guard wired backwards.
 */
function disabledExpression(clickHandler, label) {
	const click = src.indexOf(`@click="${clickHandler}"`);
	expect(click, `${label}: no button bound to ${clickHandler}`).toBeGreaterThan(-1);
	const marker = ':disabled="';
	const start = src.lastIndexOf(marker, click);
	expect(start, `${label}: the ${clickHandler} button carries no :disabled binding`).toBeGreaterThan(-1);
	const bodyStart = start + marker.length;
	const end = src.indexOf('"', bodyStart);
	expect(end, `${label}: unterminated :disabled binding`).toBeGreaterThan(bodyStart);
	return src.slice(bodyStart, end);
}

/** The body of a top-level `function name(...)`, up to its column-0 brace. */
function functionBody(name) {
	const start = src.indexOf(`function ${name}(`);
	expect(start, `no function ${name} in the SFC`).toBeGreaterThan(-1);
	const end = src.indexOf("\n}", start);
	expect(end, `unterminated function ${name}`).toBeGreaterThan(start);
	return src.slice(start, end);
}

const EXPR = disabledExpression("confirmFinish", "finish");

// `unfiledScrap` joined the guard when the reject box gained a reason
// (kioskRejectPath.spec.js owns it, and pins what it does). It is held at false
// here so these cases still describe the sweep and nothing else.
const READY = { producedQty: 12, sweepPending: false, sweepAck: false, unfiledScrap: false };

function isDisabled(overrides = {}) {
	const scope = { ...READY, ...overrides };
	const fn = new Function(...Object.keys(scope), `return (${EXPR});`);
	return !!fn(...Object.values(scope));
}

describe("finish button, when the other operator has not written off yet", () => {
	it("is live on an ordinary order with a count on it", () => {
		expect(isDisabled()).toBe(false);
	});

	it("refuses while a sweep is pending and nobody has acknowledged it", () => {
		// The whole point. Without this the operator taps through by habit and
		// the absent colleague's material lands on their document silently.
		expect(isDisabled({ sweepPending: true })).toBe(true);
	});

	it("goes live once the operator has acknowledged the sweep", () => {
		// The floor does sometimes have to finish without the other operator —
		// they went home, they are on another line. This is a warning with an
		// exit, not a lock.
		expect(isDisabled({ sweepPending: true, sweepAck: true })).toBe(false);
	});

	it("still refuses a missing count, acknowledged or not", () => {
		expect(isDisabled({ producedQty: 0 })).toBe(true);
		expect(isDisabled({ producedQty: 0, sweepPending: true, sweepAck: true })).toBe(true);
	});
});

describe("the sweep warning reaches the operator before they count", () => {
	// The early warning was withdrawn on 2026-08-31, and this is the test that
	// used to demand it: `openFinish` called `wo_consumption_preview` so the
	// operator met the sweep on open rather than as a refusal after the pallet was
	// walked. That preview answers with item codes and quantities, and Anjan's
	// requirement is that an operator never sees either. The early warning was
	// only worth its cost while the operator could act on it — go and fetch the
	// packer — and they no longer can: the write-off left this screen in the same
	// change, so there is no packer writing anything off. Measured across all 8
	// stabler tenants that day: 0 Material Consumption entries have ever been
	// posted and 0 Items carry an operator role, so the warning had never actually
	// fired for anyone.
	it("no longer asks an endpoint that answers with item names", () => {
		expect(functionBody("openFinish")).not.toContain("wo_consumption_preview");
	});

	it("clears the previous order's acknowledgement when the dialog opens", () => {
		// A kiosk is one screen for a whole shift. A tick left over from the last
		// order would wave the next one straight through the guard.
		const body = functionBody("openFinish");
		expect(body).toMatch(/sweepAck\.value\s*=\s*false/);
		expect(body).toMatch(/sweepBlocked\.value\s*=\s*false/);
	});

	it("shows the warning without listing what would be swept", () => {
		// The refusal still has to be answerable — the checkbox is what the server
		// is waiting for — but the list under it was the recipe, one item and
		// quantity per line.
		expect(src).not.toMatch(/v-for="[^"]*\bin\s+finishSweep"/);
		expect(src).toContain('id="sweep-ack"');
	});
});

describe("the acknowledgement that is sent", () => {
	it("is passed through from the operator's gesture, not hardcoded", () => {
		const body = functionBody("confirmFinish");
		expect(body).toContain("acknowledge_sweep");
		// The mutation this exists to catch: `acknowledge_sweep: true` posted on
		// every finish makes the server guard decorative — it would then never
		// refuse anything, and nothing else in the suite would notice.
		expect(body).not.toMatch(/acknowledge_sweep:\s*true/);
	});

	it("re-offers the acknowledgement when the server refuses a finish it never previewed", () => {
		// The preview and the finish are two round trips. If only the first one
		// fails the operator would meet a refusal with no checkbox to tick and no
		// way forward — the deadlock this whole guard would otherwise create.
		// Matched on the exception class, not the message: the message is
		// translated into five languages and matching its text breaks in four.
		const body = functionBody("confirmFinish");
		expect(body).toContain("SweepNotAcknowledged");
		expect(body).toMatch(/sweepBlocked\.value\s*=\s*true/);
	});
});
