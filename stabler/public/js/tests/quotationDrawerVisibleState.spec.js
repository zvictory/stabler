import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../components/QuotationEntryDrawer.vue"), "utf8");

/**
 * Two things the drawer knew and did not say.
 *
 * The quotation date. `load()` reads `res.transaction_date` into the form, and
 * `minValidTill` returns it as the `:min` of the "Valid till" picker. So the
 * date silently constrains what the user may choose, and when they choose
 * wrongly the problems list tells them "Valid till date cannot be before
 * transaction date" — naming a value that appears nowhere on the drawer. The
 * user is refused by a fact they were never shown, on the screen that is
 * refusing them.
 *
 * The currency list. When `list_currencies` fails the catch narrows the list to
 * the company's own currency and says nothing. The comment is explicit that the
 * intent is to keep the field from being empty, which is right — but the result
 * is a dropdown with exactly one option, and the only place a foreign currency
 * enters the product goes quietly dead. A supplier quoting in USD cannot be
 * recorded, and nothing on screen explains why the option is missing. Degrading
 * is fine; degrading silently is not.
 */
/** The nearest `v-if="…"` BEFORE `from` — the guard the element sits under. */
function vIfBefore(from, what) {
	const at = src.lastIndexOf('v-if="', from);
	expect(at, `${what}: no enclosing v-if found`).toBeGreaterThan(-1);
	const start = at + 'v-if="'.length;
	return src.slice(start, src.indexOf('"', start));
}

function evalInScope(expression, scope) {
	const keys = Object.keys(scope);
	return new Function(...keys, `return (${expression});`)(...keys.map((k) => scope[k]));
}

describe("the drawer shows the date it is judging the user against", () => {
	it("renders the quotation date the valid-till floor comes from", () => {
		const at = src.indexOf("form.transaction_date");
		expect(at, "transaction_date never reaches the template").toBeGreaterThan(-1);
		// It must be in the template, not only in the script that loaded it.
		expect(at).toBeGreaterThan(src.indexOf("<template>"));
	});

	it("shows it only when there is one, and does not fake today's date", () => {
		// A quotation opened fresh has no transaction date yet; minValidTill
		// falls back to today. Printing today as "the quotation date" would be
		// stating a fact the record does not contain.
		const at = src.indexOf("form.transaction_date", src.indexOf("<template>"));
		const guard = vIfBefore(at, "quotation date");
		expect(evalInScope(guard, { form: { transaction_date: "" } })).toBeFalsy();
		expect(evalInScope(guard, { form: { transaction_date: "2026-08-30" } })).toBeTruthy();
	});

	it("still refuses a valid-till before it", () => {
		// The guard on the rule the visible date explains. Showing the date
		// would be pointless if the constraint it drives were dropped.
		expect(src).toMatch(/form\.value\.valid_till < minValidTill\.value/);
	});
});

describe("the drawer says when the currency list fell back", () => {
	it("records the failure instead of only narrowing the list", () => {
		const at = src.indexOf("currencies.value = currency.value ? [currency.value] : []");
		expect(at, "the fallback is gone — has the loader been rewritten?").toBeGreaterThan(-1);
		const block = src.slice(at - 400, at + 400);
		expect(block, "the catch narrows the list and still says nothing").toMatch(
			/currencyListFailed\.value = true/
		);
	});

	it("tells the user, in the template, next to the field it affects", () => {
		const at = src.indexOf("currencyListFailed", src.indexOf("<template>"));
		expect(at, "nothing in the template reads the flag").toBeGreaterThan(-1);
	});

	it("does not swallow the failure into the success path", () => {
		// The flag must be set in the catch, not unconditionally — otherwise
		// every ordinary load would claim the list is degraded.
		const tryAt = src.indexOf('call("stabler.api.sales.list_currencies")');
		const catchAt = src.indexOf("} catch {", tryAt);
		expect(src.slice(tryAt, catchAt)).not.toMatch(/currencyListFailed\.value = true/);
	});
});
