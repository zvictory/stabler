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

const READY = { producedQty: 12, sweepPending: false, sweepAck: false };

function isDisabled(overrides = {}) {
	const scope = { ...READY, ...overrides };
	const fn = new Function(
		"producedQty",
		"sweepPending",
		"sweepAck",
		`return (${EXPR});`
	);
	return !!fn(scope.producedQty, scope.sweepPending, scope.sweepAck);
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
	it("asks the server what finishing would sweep when the dialog opens", () => {
		// Not after the refusal: by then the pallet is walked and the numbers are
		// typed. Seeing it on open is what lets them go fetch the packer instead.
		const body = functionBody("openFinish");
		expect(body).toContain("wo_consumption_preview");
		expect(body).toContain("sweep_risk");
	});

	it("clears the previous order's acknowledgement when the dialog opens", () => {
		// A kiosk is one screen for a whole shift. A tick left over from the last
		// order would wave the next one straight through the guard.
		const body = functionBody("openFinish");
		expect(body).toMatch(/sweepAck\.value\s*=\s*false/);
		expect(body).toMatch(/sweepBlocked\.value\s*=\s*false/);
	});

	it("names the items in the dialog rather than only counting them", () => {
		// "2 items" tells the operator nothing they can act on. The names tell
		// them which colleague to go and find.
		expect(src).toMatch(/v-for="[^"]*\bin\s+finishSweep"/);
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
