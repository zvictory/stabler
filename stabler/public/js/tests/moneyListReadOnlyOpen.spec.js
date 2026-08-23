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
 * P0-MONEY-2 — a click on a list row dropped straight into an edit form that
 * cancels and reposts a submitted ledger document.
 *
 * `openInForm()` loaded the voucher and went directly to `openEditFromDetail()`
 * for anything the row happened to be. On a submitted entry that form's save
 * runs `amend_expense_entry`, which calls `source.cancel()` on the original and
 * posts a replacement (money.py:3517). Measured on prod 2026-08-22: anjan holds
 * 25 133 submitted journal entries, 6 060 cancelled, and 383 already carry an
 * `amended_from` — so this path is not hypothetical, it has fired 383 times.
 *
 * Both screens already had a read-only detail card, reachable from `openDetail`
 * and already offering a deliberate button labelled "Amend" for a submitted
 * entry and "Edit draft" for a draft. The row click simply skipped past it.
 *
 * The predicate is stated as "not a draft" rather than "is submitted" so that it
 * fails safe: a cancelled voucher (which `openEditFromDetail` never checked for
 * either) and a voucher whose docstatus did not arrive both land on the card
 * instead of in an editor.
 */
function lift(source, name, label) {
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
	return { source, start, bodyStart, end: i };
}

// Only for a plain (non-async) function: `new Function` builds a sync function,
// so lifting a body containing `await` this way is a SyntaxError, not a failure
// of the code under test.
function liftFn(source, name, label) {
	const { start, bodyStart, end } = lift(source, name, label);
	const marker = `function ${name}(`;
	const args = source.slice(start + marker.length, source.indexOf(")", start));
	return new Function(...args.split(",").map((s) => s.trim()), source.slice(bodyStart + 1, end));
}

function bodyOf(source, name, label) {
	const { bodyStart, end } = lift(source, name, label);
	return source.slice(bodyStart, end);
}

describe.each(Object.entries(SCREENS))("%s — a row click may not start an amend", (label, src) => {
	const opensReadOnly = liftFn(src, "opensReadOnly", label);

	// The whole point: a posted GL document is shown, not opened for editing.
	it("keeps a submitted voucher read-only", () => {
		expect(opensReadOnly(1)).toBe(true);
	});

	// A draft has no GL entries and no original to cancel, so the fast path
	// straight into the form is kept -- this fix is about the ledger, not about
	// adding a click to every edit.
	it("still opens a draft straight in the form", () => {
		expect(opensReadOnly(0)).toBe(false);
	});

	// `openEditFromDetail` never looked at docstatus at all, so a cancelled
	// voucher used to load into the editor too.
	it("keeps a cancelled voucher read-only", () => {
		expect(opensReadOnly(2)).toBe(true);
	});

	// Fails safe. A detail payload that arrives without a docstatus must not be
	// treated as a draft -- that is the one wrong guess with ledger consequences.
	it.each([[undefined], [null], [""], ["nonsense"]])(
		"treats an unusable docstatus %p as read-only",
		(bad) => {
			expect(opensReadOnly(bad)).toBe(true);
		}
	);

	// The guard is worthless if it is consulted after the editor is populated.
	it("consults the guard before populating the editor", () => {
		const body = bodyOf(src, "openInForm", label);
		const guard = body.indexOf("opensReadOnly");
		const edit = body.indexOf("openEditFromDetail");
		expect(guard, `${label}: openInForm never calls opensReadOnly`).toBeGreaterThan(-1);
		expect(edit, `${label}: openInForm no longer opens the editor at all`).toBeGreaterThan(-1);
		expect(guard).toBeLessThan(edit);
	});
});
