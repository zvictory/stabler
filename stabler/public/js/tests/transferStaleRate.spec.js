import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(resolve(here, "../pages/money/Transfers.vue"), "utf8");

/**
 * P0-TRF-1 — a failed rate lookup left the PREVIOUS pair's quote standing, and
 * that quote decides the direction, not just the price.
 *
 * `fetchExchangeRate` had two exits that touched no state: a bare `return` when
 * the API answered <= 0, and a `catch` that only wrote to the console.
 * `get_exchange_rate_for_currencies` throws outright on a missing pair
 * (money.py:3057-3061), so the catch was the common path, not the rare one.
 *
 * What survived was not merely a stale number. `fxBaseCur` feeds `fromIsBase`,
 * and `derive()` reads it to choose between `amt * R` and `amt / R`. Post a
 * USD->UZS transfer at 12 950, switch to EUR->UZS with no EUR rate on file, and
 * the from-leg is EUR while `fxBaseCur` still says USD: the form divides where
 * it should multiply, and posts a transfer inverted as well as mispriced --
 * while the screen shows "CBU: 12 950" and a blue AUTO badge asserting the
 * number came from the Central Bank. `canSubmit` only ever asked whether the
 * rate was positive. Expenses.vue has shown `rateError` on both branches for
 * some time; Transfers had no such thing.
 *
 * The clear is deliberately scoped to the PAIR, not fired on every fetch. A
 * quote's direction is a fact about the pair and does not expire when the day
 * does -- and the date watcher deliberately keeps a rate the user typed
 * (see the comment above `reanchorRate`). Clearing on every fetch would strip
 * the direction from underneath that surviving rate and invert it on the next
 * keystroke: the very defect being fixed, introduced through the fix.
 */
function bodyOf(source, name) {
	const marker = `function ${name}(`;
	const start = source.indexOf(marker);
	expect(start, `Transfers defines no ${name}()`).toBeGreaterThan(-1);
	let depth = 0;
	let i = source.indexOf("{", start);
	const bodyStart = i;
	for (; i < source.length; i++) {
		if (source[i] === "{") depth++;
		else if (source[i] === "}" && --depth === 0) break;
	}
	return source.slice(bodyStart, i);
}

function liftFn(source, name) {
	const marker = `function ${name}(`;
	const start = source.indexOf(marker);
	expect(start, `Transfers defines no ${name}()`).toBeGreaterThan(-1);
	const args = source.slice(start + marker.length, source.indexOf(")", start));
	const body = bodyOf(source, name);
	return new Function(...args.split(",").map((s) => s.trim()), body.slice(1, -1));
}

describe("Transfers — a quote that no longer belongs to the pair on screen", () => {
	const survives = liftFn(SRC, "quoteSurvives");

	// The transfer that is actually being posted keeps its quote: a date change
	// re-prices, it does not re-point.
	it("keeps the quote when only the date moved", () => {
		expect(survives("USD→UZS", "USD", "UZS")).toBe(true);
	});

	// P0-TRF-1 itself.
	it("drops the quote when the pair changed", () => {
		expect(survives("USD→UZS", "EUR", "UZS")).toBe(false);
	});

	// The subtler half: both currencies are still involved, so a membership
	// test would pass this. 1 USD = 12 950 UZS is the wrong way round the
	// moment the legs swap.
	it("drops the quote when the legs were swapped", () => {
		expect(survives("USD→UZS", "UZS", "USD")).toBe(false);
	});

	it("has no quote to keep before the first fetch", () => {
		expect(survives("", "USD", "UZS")).toBe(false);
	});
});

describe("Transfers — an answer that is not a rate", () => {
	const quote = liftFn(SRC, "canonicalQuote");

	// The `raw <= 0` exit. Returning nothing is what lets the caller clear;
	// the old code returned nothing AND kept everything.
	it("yields no quote for a non-positive answer", () => {
		expect(quote(0, "EUR", "UZS")).toBe(null);
		expect(quote(null, "EUR", "UZS")).toBe(null);
		expect(quote(-1, "EUR", "UZS")).toBe(null);
	});

	it("quotes the strong currency as the base", () => {
		expect(quote(12950, "USD", "UZS")).toMatchObject({ base: "USD", counter: "UZS" });
	});

	// Never show 1 UZS = 0.000077 USD.
	it("flips a sub-1 answer instead of showing it", () => {
		const q = quote(1 / 12950, "UZS", "USD");
		expect(q.base).toBe("USD");
		expect(Math.round(q.rate)).toBe(12950);
	});
});

describe("Transfers — neither failure exit is silent", () => {
	const body = bodyOf(SRC, "fetchExchangeRate");

	it("reports a missing rate when the API answers with none", () => {
		const [beforeCatch] = body.split("} catch");
		expect(beforeCatch, "the <= 0 exit says nothing").toMatch(/rateError\.value = t\(/);
	});

	it("reports a missing rate when the call throws", () => {
		const afterCatch = body.slice(body.indexOf("} catch"));
		expect(afterCatch, "the catch only writes to the console").toMatch(/rateError\.value = t\(/);
	});

	// The accounts can move while a fetch is in flight; a quote for the pair
	// nobody is looking at any more must not land on the pair that is.
	it("drops an answer that arrived for a pair already left behind", () => {
		expect(body).toMatch(/asked !==/);
	});

	// The guard is the fix. Clearing unconditionally would pass every test
	// above -- `quoteSurvives` would still answer correctly -- while stripping
	// the direction out from under a rate the date watcher had kept.
	it("clears the quote only when the pair actually changed", () => {
		const at = body.indexOf("if (!quoteSurvives(");
		expect(at, "the clear is not guarded by the pair at all").toBeGreaterThan(-1);
		let depth = 0;
		let i = body.indexOf("{", at);
		for (; i < body.length; i++) {
			if (body[i] === "{") depth++;
			else if (body[i] === "}" && --depth === 0) break;
		}
		const guarded = body.slice(at, i);
		expect(guarded, "fxBaseCur is cleared outside the pair guard").toMatch(/fxBaseCur\.value = ""/);
		expect(guarded).toMatch(/cbuRate\.value = null/);
		// And nowhere else in the function.
		expect((body.match(/fxBaseCur\.value = ""/g) || []).length).toBe(1);
	});

	it("shows the error where the rate is entered", () => {
		expect(SRC).toMatch(/v-if="rateError"/);
	});

	// AUTO asserts the number came from the Central Bank. With no rate on file
	// it asserts something untrue, in blue, next to an empty field.
	it("stops claiming AUTO once the lookup failed", () => {
		expect(SRC).toMatch(/v-if="!rateManuallyEdited && !rateError"/);
	});
});
