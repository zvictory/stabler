import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/DeclarantQueue.vue"), "utf8");

/**
 * Who decides when a customs deadline turns orange.
 *
 * The server already decided. `declarant_queue` derives `risk` from the very
 * `days_left` it sends on the same row — negative is `risk`, seven or fewer is
 * `warn`, otherwise `good` — and sends both. The screen ignored `risk`
 * entirely and re-derived the answer inline from `days_left`, in two places,
 * each with its own hard-coded 7.
 *
 * That is the same rule written three times for one queue, and the module-wide
 * count was five. A threshold copied is a threshold that drifts: the day
 * procurement decides a customs deadline warns at ten days, the server changes
 * and both of these keep saying seven, with nothing failing anywhere.
 *
 * The thresholds are IDENTICAL today, deliberately — this change is meant to
 * alter nothing a user sees. It removes the second and third copies.
 *
 * What it does NOT fix, because it cannot be fixed from the client: the sister
 * board reads a `risk` field of the same name that answers a different
 * question. `logist_board` sets `"risk": "risk" if late else "good"`, where
 * `late` is `eta > delivery` — whether the shipment will miss its deadline,
 * not how near the deadline is — and has no `warn` value at all. So one name
 * carries two meanings across two endpoints, and no amount of client work
 * makes the two boards agree. That belongs on the server and is recorded, not
 * guessed at here.
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

const etaClass = new Function(`${extractFunction("etaClass")}\nreturn etaClass;`)();

describe("the queue renders the severity the server decided", () => {
	it("marks an overdue clearance red, and emphatically so on the card", () => {
		expect(etaClass({ risk: "risk", days_left: -3 })).toBe("text-red");
		expect(etaClass({ risk: "risk", days_left: -3 }, true)).toBe("text-red fw-bold");
	});

	it("marks a clearance inside the window orange", () => {
		// Five days out. This is the case the sister board renders plain, and
		// the reason the two disagree on the same PO.
		expect(etaClass({ risk: "warn", days_left: 5 })).toBe("text-warning");
		expect(etaClass({ risk: "warn", days_left: 5 }, true)).toBe("text-warning fw-semibold");
	});

	it("leaves everything else unmarked", () => {
		expect(etaClass({ risk: "good", days_left: 30 })).toBe("");
		expect(etaClass({ risk: "good", days_left: 30 }, true)).toBe("");
	});

	it("says nothing about a PO with no date at all", () => {
		// `days_left` is null and the server answers `good`. The fifth state is
		// not a severity, and colouring it would be inventing one.
		expect(etaClass({ risk: "good", days_left: null }, true)).toBe("");
	});

	it("ignores days_left even when it contradicts the server's answer", () => {
		// The point of the change, stated as behaviour: the server is the one
		// source. If these ever disagree the server wins, which is what stops a
		// second copy of the threshold from mattering.
		expect(etaClass({ risk: "good", days_left: 2 })).toBe("");
		expect(etaClass({ risk: "warn", days_left: 400 })).toBe("text-warning");
	});
});

describe("the threshold no longer lives in this file", () => {
	it("carries no hard-coded deadline window", () => {
		// The regression guard. Both re-derivations used a literal 7.
		expect(src).not.toMatch(/days_left\s*<=\s*7/);
		expect(src).not.toMatch(/days_left\s*!=\s*null\s*&&\s*days_left\s*<\s*0/);
	});

	it("colours both the card and the table row through the one function", () => {
		expect((src.match(/etaClass\(/g) || []).length).toBeGreaterThanOrEqual(2);
	});
});
