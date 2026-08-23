import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const SCREENS = {
	Expenses: readFileSync(resolve(here, "../pages/money/Expenses.vue"), "utf8"),
	Transfers: readFileSync(resolve(here, "../pages/money/Transfers.vue"), "utf8"),
};

/**
 * P0-MONEY-2, second half — "Amend" is not an edit, and said so nowhere.
 *
 * `amend_expense_entry` cancels the original voucher outright and posts a
 * replacement in its place. Worse, P0-MONEY-3: when the amount trips the
 * maker-checker threshold, `submit_or_route` leaves that replacement a DRAFT.
 * The original is then gone from the ledger and nothing has taken its place.
 * The only notice was a toast fired AFTER the save.
 *
 * Commit 1ad5cc0 stopped a list-row click from reaching the editor at all, so
 * getting here is now deliberate. Deliberate is not the same as informed: the
 * word on the button was the entire warning. This dialog states what happens.
 *
 * It cannot state the threshold. No whitelisted endpoint exposes it and the
 * session does not carry it, so the approval clause is written as a condition,
 * not as a prediction about this particular amount.
 */
function bodyOf(source, name, label) {
	const marker = `function ${name}(`;
	const start = source.indexOf(marker);
	expect(start, `${label} defines no ${name}()`).toBeGreaterThan(-1);
	let depth = 0;
	let i = source.indexOf("{", start);
	const bodyStart = i;
	for (; i < source.length; i++) {
		if (source[i] === "{") depth++;
		else if (source[i] === "}" && --depth === 0) break;
	}
	return source.slice(bodyStart, i);
}

function liftFn(source, name, label) {
	const marker = `function ${name}(`;
	const start = source.indexOf(marker);
	expect(start, `${label} defines no ${name}()`).toBeGreaterThan(-1);
	const args = source.slice(start + marker.length, source.indexOf(")", start));
	const body = bodyOf(source, name, label);
	return new Function(...args.split(",").map((s) => s.trim()), body.slice(1, -1));
}

describe.each(Object.entries(SCREENS))("%s — amending a posted voucher", (label, src) => {
	const required = liftFn(src, "amendConfirmationRequired", label);

	// The case the dialog exists for.
	it("asks before amending a submitted voucher", () => {
		expect(required(1)).toBe(true);
	});

	// A draft edit cancels nothing and posts nothing. Asking there would train
	// people to dismiss the dialog without reading it, which is how a warning
	// stops being a warning.
	it("does not ask when editing a draft", () => {
		expect(required(0)).toBe(false);
	});

	// A cancelled voucher never reaches the editor (opensReadOnly keeps it on the
	// card), so there is nothing to confirm.
	it("does not ask for a cancelled voucher", () => {
		expect(required(2)).toBe(false);
	});

	it("asks before the editor is populated, not after", () => {
		const body = bodyOf(src, "openEditFromDetail", label);
		const ask = body.indexOf("amendConfirmationRequired");
		const populate = body.indexOf("form.value =");
		expect(ask, `${label}: openEditFromDetail never checks whether to confirm`).toBeGreaterThan(-1);
		expect(populate, `${label}: openEditFromDetail no longer populates the form`).toBeGreaterThan(-1);
		expect(ask).toBeLessThan(populate);
	});

	// A dialog the user can walk past by pressing Enter is not a confirmation of
	// a ledger cancellation. The house pattern for destructive work is danger.
	it("marks the dialog destructive and names the replacement behaviour", () => {
		const body = bodyOf(src, "confirmAmend", label);
		expect(body).toMatch(/danger:\s*true/);
		expect(body).toMatch(/cancels \{name\}/);
		expect(body).toMatch(/requires approval/);
	});
});
