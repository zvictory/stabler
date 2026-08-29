import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/SourcingWorkspace.vue"), "utf8");

/**
 * Which award panel the sourcing workspace shows, and whether the only route to
 * a Purchase Order survives a page reload.
 *
 * The bug this file exists for: the approved read-only panel — and the "Create
 * purchase order" button inside it — used to render on
 * `decisionData?.decision?.status === 'Approved'`, while the endpoint behind
 * `decision` (`sourcing.get_sourcing_decision` → `_open_decision`) filtered
 * `status="Draft"` and nothing else. So that expression could only ever be true
 * from the in-session reply of `approve_sourcing_decision`. Reload the page and
 * an already-awarded lot rendered the NEW-award form instead, with no way to
 * reach the PO route at all — while `purchasing._assert_awarded` (the server
 * gate that landed the same week) refuses every quotation that form can produce.
 * The legitimate path existed only inside the browser tab that clicked approve.
 *
 * The fix splits the response into `decision` (the open DRAFT) and `award` (the
 * approval standing right now), because BOTH can be true at once: re-awarding a
 * lot whose winner fell through means a fresh draft sitting on top of a standing
 * award, and the panel must not have to choose between showing the award (and
 * never being able to re-award) and showing the draft (and losing the PO route).
 *
 * Same shape as manufacturingTabGates.spec.js: the decision function and the
 * template's own `v-if` expressions are EXECUTED, not grepped. A `toContain`
 * assertion passes just as happily on a branch wired backwards — which is
 * precisely the failure mode here, since the broken version DID mention
 * "Approved" in the very expression that could never be true.
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
	const braceStart = src.indexOf("{", at);
	return src.slice(at, braceStart) + braceMatched(braceStart);
}

/** The `v-if="…"` expression on the first tag at or after `from`. */
function vIfAt(from, what) {
	const at = src.indexOf('v-if="', from);
	expect(at, `${what}: no v-if found — has the branch moved?`).toBeGreaterThan(-1);
	const start = at + 'v-if="'.length;
	const end = src.indexOf('"', start);
	return src.slice(start, end);
}

/** The nearest `v-if="…"` BEFORE `from` — the guard a nested element sits under. */
function vIfBefore(from, what) {
	const at = src.lastIndexOf('v-if="', from);
	expect(at, `${what}: no enclosing v-if found`).toBeGreaterThan(-1);
	return vIfAt(at, what);
}

function anchor(marker) {
	const at = src.indexOf(marker);
	expect(at, `the "${marker}" marker is gone — has the panel been rewritten?`).toBeGreaterThan(-1);
	return at;
}

const awardPanelMode = new Function(
	`${extractFunction("awardPanelMode")}\nreturn awardPanelMode;`
)();

/** Evaluate a template expression against a supplied render scope. */
function evalInScope(expression, scope) {
	const keys = Object.keys(scope);
	return new Function(...keys, `return (${expression});`)(...keys.map((k) => scope[k]));
}

const APPROVED = {
	name: "TSD-2026-0007",
	status: "Approved",
	selected_quotation: "SQ-WINNER",
	cheapest_quotation: "SQ-CHEAP",
	approved_by: "director@mikas.example",
	approved_at: "2026-08-28 14:02:00",
};
const DRAFT = { name: "TSD-2026-0009", status: "Draft", selected_quotation: "SQ-SECOND" };

describe("the sourcing workspace decides which award panel to show", () => {
	it("shows the approved panel for a lot awarded in an earlier session", () => {
		// The regression. After a reload there is no draft at all — only the
		// standing award — and this is the state in which the PO button has to
		// come back. The old expression answered "form" here.
		expect(awardPanelMode({ decision: null, award: APPROVED }, false)).toBe("approved");
	});

	it("shows the new-award form for a lot nobody has awarded", () => {
		expect(awardPanelMode({ decision: null, award: null }, false)).toBe("form");
	});

	it("shows the form alone while an award is still only a draft", () => {
		// A draft is not an award: no PO may be created from it, so no approved
		// panel and no PO button — that is what _assert_awarded enforces server-side.
		expect(awardPanelMode({ decision: DRAFT, award: null }, false)).toBe("form");
	});

	it("keeps the standing award on screen while a re-award draft is open", () => {
		// The winner fell through and sourcing has drafted a replacement. The old
		// award is still the one in force until a director approves the new one,
		// so hiding it would hide the PO route that is still legitimately open.
		expect(awardPanelMode({ decision: DRAFT, award: APPROVED }, false)).toBe("both");
	});

	it("opens the form beneath the award when sourcing asks to re-award", () => {
		// Re-awarding must stay reachable on an awarded lot — otherwise the fix
		// for the reload bug would trade one dead end for another.
		expect(awardPanelMode({ decision: null, award: APPROVED }, true)).toBe("both");
	});

	it("falls back to the form when the decision call failed", () => {
		// loadDecision() sets decisionData to null on error. A panel that throws
		// here would take the whole workspace down with it.
		expect(awardPanelMode(null, false)).toBe("form");
	});
});

describe("the template branches on that decision, not on an in-session status", () => {
	const approvedPanel = vIfAt(anchor("Case 1: Award is APPROVED"), "approved panel");
	const awardForm = vIfAt(anchor("Case 2: Draft or New Award Form"), "award form");

	it("renders the approved panel in exactly the two modes that have an award", () => {
		expect(evalInScope(approvedPanel, { panelMode: "approved" })).toBe(true);
		expect(evalInScope(approvedPanel, { panelMode: "both" })).toBe(true);
		expect(evalInScope(approvedPanel, { panelMode: "form" })).toBe(false);
	});

	it("renders the award form in exactly the two modes that accept one", () => {
		expect(evalInScope(awardForm, { panelMode: "form" })).toBe(true);
		expect(evalInScope(awardForm, { panelMode: "both" })).toBe(true);
		expect(evalInScope(awardForm, { panelMode: "approved" })).toBe(false);
	});
});

describe("the Create purchase order button is driven by the standing award", () => {
	// `@click="createPo(` and not the bare word: `createPo(` first appears as the
	// function's own definition up in <script>, where there is no v-if to find.
	const buttonGuard = vIfBefore(anchor('@click="createPo('), "PO button");

	it("is offered for an award whose winning quotation is known", () => {
		// If this guard still read `decisionData.decision.…` it would throw on a
		// reload (decision is null there), not merely hide — hence executing it.
		expect(Boolean(evalInScope(buttonGuard, { standingAward: APPROVED }))).toBe(true);
	});

	it("is withheld when the award names no quotation to buy from", () => {
		expect(
			Boolean(evalInScope(buttonGuard, { standingAward: { ...APPROVED, selected_quotation: "" } }))
		).toBe(false);
	});
});

describe("the approved panel names the winner from the award, not from the form", () => {
	it("reads the awarded row, so a reload cannot label the cheapest bid as the winner", () => {
		// `selectedRow` follows `awardForm.selected_quotation`, and loadDecision
		// seeds that form with the CHEAPEST bid whenever there is no open draft —
		// exactly the reload case. Showing selectedRow in the approved panel would
		// print the wrong supplier under "Selected winner" with no error anywhere.
		const literal = extractFunction("awardedRowOf");
		const awardedRowOf = new Function(`${literal}\nreturn awardedRowOf;`)();
		const rows = [
			{ name: "SQ-CHEAP", supplier_name: "Cheap Co" },
			{ name: "SQ-WINNER", supplier_name: "Winner Co" },
		];
		expect(awardedRowOf(rows, APPROVED)?.supplier_name).toBe("Winner Co");
		expect(awardedRowOf(rows, null)).toBeUndefined();
	});
});
