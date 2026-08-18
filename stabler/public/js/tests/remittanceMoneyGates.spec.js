import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const payoutSrc = readFileSync(resolve(here, "../pages/remittance/RemittancePayout.vue"), "utf8");
const refundSrc = readFileSync(resolve(here, "../pages/remittance/RemittanceRefund.vue"), "utf8");

/**
 * The two buttons that move cash, and the conditions under which they are live.
 *
 * Both were reachable too early. Payout accepted a code that had never been
 * checked — the box only had to be non-empty — so a wrong code was discovered
 * AFTER the cashier had confirmed the desk and counted the notes, as an error line
 * under a form they had already committed to. Refund was worse: its cash step had
 * a red warning, a posting-date input and a live button, and no confirmation of
 * any kind. It was clickable the moment the card rendered.
 *
 * These tests execute the real `:disabled` expression out of the shipped SFC
 * rather than asserting that the source *contains* a flag name. A `toContain`
 * assertion passes just as happily on a guard wired backwards, or on one whose
 * flag is read but never able to be false — which is exactly the failure this
 * file exists to catch. @vue/test-utils is not a devDependency here (same
 * constraint as remittancePickupReceipt.spec.js), so the component is not
 * mounted; the expression is.
 */
function disabledExpression(src, clickHandler, label) {
	const click = src.indexOf(`@click="${clickHandler}"`);
	expect(click, `${label}: no button bound to ${clickHandler}`).toBeGreaterThan(-1);
	const marker = ':disabled="';
	const start = src.lastIndexOf(marker, click);
	expect(start, `${label}: the ${clickHandler} button carries no :disabled binding`).toBeGreaterThan(
		-1
	);
	const bodyStart = start + marker.length;
	const end = src.indexOf('"', bodyStart);
	expect(end, `${label}: unterminated :disabled binding`).toBeGreaterThan(bodyStart);
	return src.slice(bodyStart, end);
}

/**
 * Compile the template expression into a function of the flags it reads.
 *
 * `new Function` over a string is the point, not an oversight: the string is the
 * shipped `:disabled` expression, read out of a file in this repository at test
 * time, and executing it is the only way to prove it decides correctly rather
 * than merely mentioning the right words. Nothing here is user input, and the
 * same construction is how `remittancePickupReceipt.spec.js` runs the receipt's
 * real guard functions. Do not pass anything to this that did not come out of a
 * repository source file.
 */
function gate(expression, flags) {
	// eslint-disable-next-line no-new-func
	return new Function(...flags, `return (${expression});`);
}

/**
 * The guard prologue of a handler: from its signature to its first side effect.
 *
 * Both end markers occur EARLIER in their file inside sibling handlers, so the
 * search has to start at the function, not at the top of the source. Slicing on a
 * bare `indexOf` produced an empty body and a test that could only pass by
 * accident.
 */
function handlerBody(src, signature, endMarker) {
	const start = src.indexOf(signature);
	expect(start, `${signature} not found`).toBeGreaterThan(-1);
	const end = src.indexOf(endMarker, start);
	expect(end, `${signature} has no ${endMarker}`).toBeGreaterThan(start);
	return src.slice(start, end);
}

describe("Pay out is gated on all three preconditions, not one of them", () => {
	const FLAGS = [
		"submitting",
		"canPayout",
		"codeVerified",
		"identityChecked",
		"cashConfirmed",
		"pickupCode",
	];
	const READY = {
		submitting: false,
		canPayout: true,
		codeVerified: true,
		identityChecked: true,
		cashConfirmed: true,
		pickupCode: "ABCD2345",
	};
	const isDisabled = gate(
		disabledExpression(payoutSrc, "payout", "RemittancePayout.vue"),
		FLAGS
	);
	const call = (state) => isDisabled(...FLAGS.map((flag) => state[flag]));

	it("is live only when the code is verified, the identity checked and the cash counted", () => {
		expect(call(READY)).toBe(false);
	});

	// Each of these is a way somebody has actually handed money over: the code was
	// never checked, the receiver was never asked for a document, the notes were
	// never counted. Named one by one so a regression says WHICH gate was dropped.
	it.each([
		["the code has not been verified", "codeVerified", false],
		["the receiver's identity was not checked", "identityChecked", false],
		["the cash has not been counted", "cashConfirmed", false],
		["there is no code in the box", "pickupCode", ""],
		["the role does not allow payout", "canPayout", false],
		["a payout is already in flight", "submitting", true],
	])("stays disabled when %s", (_why, flag, value) => {
		expect(call({ ...READY, [flag]: value })).toBe(true);
	});
});

describe("Pay refund cash is gated on a counted-cash confirmation", () => {
	const FLAGS = ["busy", "refundCashConfirmed"];
	const isDisabled = gate(
		disabledExpression(refundSrc, "submitComplete", "RemittanceRefund.vue"),
		FLAGS
	);

	it("is live once the cashier confirms the count", () => {
		expect(isDisabled("", true)).toBe(false);
	});

	it("stays disabled until the cash is counted", () => {
		// The defect, pinned: before this the only gate was `busy`, so the button
		// that hands cash back to the sender was live on first render.
		expect(isDisabled("", false)).toBe(true);
	});

	it("stays disabled while another refund action is in flight", () => {
		expect(isDisabled("complete_refund", true)).toBe(true);
	});
});

describe("The submit handlers refuse what the buttons hide", () => {
	// A disabled button is a UI affordance, not a guard: the handler is still
	// reachable from a stale click or a keyboard activation mid-update. Both
	// handlers therefore repeat the preconditions, and these assertions read the
	// handler body rather than the template.
	it("payout() will not post without a verified code and all three confirmations", () => {
		const body = handlerBody(payoutSrc, "async function payout()", "const requestId =");
		for (const flag of ["codeVerified", "identityChecked", "cashConfirmed", "pickupCode"]) {
			expect(body, `payout() does not re-check ${flag}`).toContain(flag);
		}
	});

	it("submitComplete() will not post without the counted-cash confirmation", () => {
		const body = handlerBody(refundSrc, "async function submitComplete()", "await confirm(");
		expect(body).toContain("refundCashConfirmed");
	});
});
