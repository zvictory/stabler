import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/manufacturing/ManufacturingHome.vue"), "utf8");

/**
 * Which tabs each manufacturing role is offered.
 *
 * The backend already answered this, and it answered it differently for the two
 * screens that shipped on 2026-08-28 (api/manufacturing.py):
 *
 *   work_order_plan, reschedule_work_order          -> _require_mfg_manager()
 *   list_stop_reasons, log_line_stop, list_line_stops -> _require_mfg()
 *
 * log_line_stop's own docstring says why it is the looser of the two: "the person
 * who watched the line stop is the operator, and a log only a manager can write is
 * one that gets filled in from memory at the end of the week." The first version
 * of this tab bar put BOTH new screens behind isMfgManager and redirected everyone
 * else away, so the one person the log was designed for could not open it. Nothing
 * errored; the tab simply was not there.
 *
 * Pinned in the SPA rather than only on the server because the server would have
 * accepted the operator's write all along. The screen was the lock.
 *
 * The tab list is EXECUTED, not grepped. Two earlier attempts at this file matched
 * the wrong `session.isMfgManager` (there are two branches — BOMs is the other)
 * and the `watchEffect` in the import line, and both produced green-looking
 * nonsense. A source assertion cannot tell those apart; a value can.
 */
function bracketMatched(from) {
	let depth = 0;
	for (let i = from; i < src.length; i++) {
		if (src[i] === "[") depth++;
		else if (src[i] === "]" && --depth === 0) return src.slice(from, i + 1);
	}
	throw new Error("unterminated array literal");
}

function tabsFor(isMfgManager) {
	const at = src.indexOf("const tabs = computed(() => [");
	expect(at, "the tab list is gone — has the tab bar moved?").toBeGreaterThan(-1);
	const literal = bracketMatched(src.indexOf("[", at));
	const build = new Function("session", "t", `return ${literal};`);
	return build({ isMfgManager }, (s) => s).map((tab) => tab.name);
}

function redirectList() {
	// `watchEffect(` with the paren: the bare word also appears in the vue import
	// at the top of the file, and matching that grabs the tab array instead.
	const at = src.indexOf("watchEffect(");
	expect(at, "the redirect guard is gone — has the gating moved?").toBeGreaterThan(-1);
	return JSON.parse(bracketMatched(src.indexOf("[", at)).replace(/,(\s*])/, "$1"));
}

const MANAGER = tabsFor(true);
const OPERATOR = tabsFor(false);

describe("the plan board stays a manager's screen", () => {
	it("is offered to a manager", () => {
		expect(MANAGER).toContain("manufacturing-plan");
	});

	it("is not offered to an operator, matching _require_mfg_manager on the server", () => {
		expect(OPERATOR).not.toContain("manufacturing-plan");
	});

	it("is redirected away if an operator types the URL", () => {
		expect(redirectList()).toContain("manufacturing-plan");
	});
});

describe("the line stop log is open to the operator who watched the stop", () => {
	it("is offered to an operator", () => {
		// The regression this file exists for. log_line_stop is _require_mfg(),
		// so a manager-only tab contradicts the endpoint the screen calls.
		expect(OPERATOR).toContain("manufacturing-stops");
	});

	it("is still offered to a manager too", () => {
		expect(MANAGER).toContain("manufacturing-stops");
	});

	it("is not redirected away from an operator", () => {
		expect(redirectList()).not.toContain("manufacturing-stops");
	});
});

describe("the rest of the tab bar is unchanged", () => {
	it("keeps BOMs a manager screen and work orders everyone's", () => {
		// Guards the extraction itself: if these two flipped, the helper above is
		// reading something other than the real tab list.
		expect(MANAGER).toContain("manufacturing-boms");
		expect(OPERATOR).not.toContain("manufacturing-boms");
		expect(OPERATOR).toContain("manufacturing-work-orders");
	});
});
