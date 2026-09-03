import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

import { chargeTypeLabel, chargeTypes } from "../composables/landedChargeTypes.js";

const here = dirname(fileURLToPath(import.meta.url));
const editor = readFileSync(resolve(here, "../components/LandedChargesEditor.vue"), "utf8");
const board = readFileSync(resolve(here, "../pages/tender/PoControlBoard.vue"), "utf8");
const shared = readFileSync(resolve(here, "../composables/landedChargeTypes.js"), "utf8");
const catalogue = readFileSync(resolve(here, "../../../api/_landed_charge_types.py"), "utf8");

/**
 * ADR-606 — ONE predetermined landed-charge list, read from the server.
 *
 * The defect, measured 2026-09-03: two lists, in two components, for the same
 * costs. `PoControlBoard.vue` offered eleven lower-case keys on a Purchase
 * Order's landed plan (transport, customs, …, broker, loading, other);
 * `LandedChargesEditor.vue` offered six Title-Case ones on the Supplier
 * Quotation estimate that PRECEDES that very order (Freight, Customs Duty,
 * Handling & Terminal, Insurance, VAT, Other). They do not overlap on a single
 * string. So the estimate an officer types on Monday and the plan they type on
 * Friday describe the same freight under two names, and nothing — no screen, no
 * report, no future tender P&L — can put the two beside each other.
 *
 * The fix is not "make the two literals equal", which is two lists that happen
 * to agree until someone edits one. The list is defined once, on the server
 * (`api/_landed_charge_types.py`), and both editors read it. These specs are the
 * mechanical half of that: a component may not grow a list of its own again.
 */

/** The server's list, read from the module that defines it. */
const CANONICAL = [...catalogue.matchAll(/\{"key": "([a-z]+)", "label": "([^"]+)"\}/g)].map(
	([, key, label]) => ({ key, label }),
);

function braceMatched(src, from) {
	let depth = 0;
	for (let i = from; i < src.length; i++) {
		if (src[i] === "{") depth++;
		else if (src[i] === "}" && --depth === 0) return src.slice(from, i + 1);
	}
	throw new Error("unterminated block");
}

function extractFunction(src, name) {
	const at = src.indexOf(`function ${name}(`);
	expect(at, `${name} is gone — has it moved or been renamed?`).toBeGreaterThan(-1);
	const braceStart = src.indexOf("{", at);
	return src.slice(at, braceStart) + braceMatched(src, braceStart);
}

const load = (src, name, ...deps) =>
	new Function(`${[...deps, name].map((n) => extractFunction(src, n)).join("\n")}\nreturn ${name};`)();

/** `addLine`/`addChargeLine` push into a component ref; hand them a stand-in. */
function addedLine(src, name, refName) {
	const rows = { value: [] };
	new Function(refName, `${extractFunction(src, name)}\nreturn ${name};`)(rows)();
	return rows.value[0];
}

describe("the list is defined once, on the server", () => {
	it("reads nine types out of the module that defines them", () => {
		// Guards the parser above, not the product: a spec that silently matched
		// zero entries would make every assertion below vacuously true.
		expect(CANONICAL.map((c) => c.key)).toEqual([
			"transport",
			"customs",
			"declarant",
			"certification",
			"insurance",
			"storage",
			"bank",
			"legal",
			"other",
		]);
	});

	it("neither editor carries a charge-type list of its own", () => {
		// WHAT WOULD MAKE THIS FAIL: pasting `const CHARGE_TYPES = [...]` back
		// into either component — which is the state this ADR is about, and it
		// looks harmless right up until the two copies disagree.
		for (const [name, src] of [
			["LandedChargesEditor.vue", editor],
			["PoControlBoard.vue", board],
		]) {
			expect(src, `${name} still declares its own CHARGE_TYPES array`).not.toMatch(
				/CHARGE_TYPES\s*=\s*\[/,
			);
		}
	});

	it("neither editor authors a label for any of the nine types", () => {
		// The subtler regrowth: no array, but a `chargeLabel()` returning an
		// object of nine `t("…")` calls. That is the same list, spelled sideways,
		// and it drifts from the server's the first time one side is edited.
		// WHAT WOULD MAKE THIS FAIL: PoControlBoard's old label map coming back.
		for (const { label } of CANONICAL) {
			const authored = new RegExp(`t\\(\\s*["'\`]${label.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&")}`);
			expect(editor, `LandedChargesEditor.vue authors the label "${label}"`).not.toMatch(authored);
			expect(board, `PoControlBoard.vue authors the label "${label}"`).not.toMatch(authored);
		}
		// And the option text comes from the shared lookup, so a local one cannot
		// be slipped in beside a `v-for` over the server's own list.
		expect(editor).toMatch(/v-for="opt in chargeTypes"[\s\S]{0,200}chargeTypeLabel\(opt\.key\)/);
		expect(board).toMatch(/v-for="ct in chargeTypes"[\s\S]{0,200}chargeTypeLabel\(ct\.key\)/);
	});

	it("both editors read the list through the one composable", () => {
		expect(editor).toMatch(
			/import \{[^}]*chargeTypes[^}]*\} from "\.\.\/composables\/landedChargeTypes\.js"/,
		);
		expect(board).toMatch(
			/import \{[^}]*chargeTypes[^}]*\} from "\.\.\/\.\.\/composables\/landedChargeTypes\.js"/,
		);
		// Both <select>s must render THAT list, not something derived beside it.
		expect(editor).toMatch(/v-for="[a-z]+ in chargeTypes"/);
		expect(board).toMatch(/v-for="[a-z]+ in chargeTypes"/);
	});

	it("only the composable knows the endpoint", () => {
		// One reader, one cache, one place to change when the payload moves.
		expect(shared).toContain("stabler.api.tender.landed_charge_types");
		expect(editor).not.toContain("landed_charge_types");
		expect(board).not.toContain("landed_charge_types");
	});
});

describe("a legacy line shows the type the server resolved it to", () => {
	it("labels a legacy Freight line with the canonical transport label", () => {
		// The whole point of the alias table, seen from the officer's chair: a
		// quotation stored under "Freight" in 2025 opens on the same option a PO
		// plan stored under "transport" opens on, and both read the same words.
		chargeTypes.value = CANONICAL;
		const legacy = { charge_type: "Freight", charge_type_canonical: "transport" };
		const loaded = load(editor, "loadedLine")(legacy);
		expect(loaded.charge_type).toBe("transport");
		expect(chargeTypeLabel(loaded.charge_type)).toBe("Freight / transport");
	});

	it("moves a legacy PO broker line onto the declarant option", () => {
		// `broker` and `declarant` were two options on ONE list for the same
		// person. WHAT WOULD MAKE THIS FAIL: binding `c.type` — the select would
		// fall back to its first option and a save would silently retype the line.
		const line = load(board, "editorLine")({ type: "broker", type_canonical: "declarant" });
		expect(line.type).toBe("declarant");
	});

	it("keeps the words off an unrecognised quotation type", () => {
		// Quotation charge types are free text on disk ("Local Delivery"). The
		// server maps them to `other` and hands back what it could not recognise;
		// dropping that here leaves a line reading "Other" and nothing else.
		const loaded = load(editor, "loadedLine")({
			charge_type: "Local Delivery",
			charge_type_canonical: "other",
			charge_type_unmapped: "Local Delivery",
			description: "",
		});
		expect(loaded.charge_type).toBe("other");
		expect(loaded.description).toBe("Local Delivery");
	});

	it("never overwrites a description the officer already wrote", () => {
		const loaded = load(editor, "loadedLine")({
			charge_type: "Local Delivery",
			charge_type_canonical: "other",
			charge_type_unmapped: "Local Delivery",
			description: "port fees, Nukus",
		});
		expect(loaded.description).toBe("port fees, Nukus");
	});
});

describe("a new line starts on the same type in both editors", () => {
	it("adds a transport line, not a Freight one and not an Other one", () => {
		// `LandedChargesEditor` defaulted to "Freight" and the PO board to
		// "transport" — the same default, spelled two ways, which is how the two
		// lists stayed invisible for so long: the common case matched.
		expect(addedLine(editor, "addChargeLine", "charges").charge_type).toBe("transport");
		expect(addedLine(board, "addLine", "editorLines").type).toBe("transport");
	});
});

describe("`other` is the one type that has to be named", () => {
	it("flags an other line with nothing written beside it", () => {
		// ADR-606: `other` names no cost on its own. An estimate whose largest
		// line reads "Other" is not an estimate anyone can check.
		// WHAT WOULD MAKE THIS FAIL: dropping the check, or blocking the save
		// instead — the council's rule is flag, don't block; an estimate typed
		// under deadline must stay saveable half-finished.
		const quotation = load(editor, "needsChargeLabel");
		expect(quotation({ charge_type: "other", description: "" })).toBe(true);
		expect(quotation({ charge_type: "other", description: "port fees" })).toBe(false);
		expect(quotation({ charge_type: "transport", description: "" })).toBe(false);

		const po = load(board, "needsChargeLabel");
		expect(po({ type: "other", label: "" })).toBe(true);
		expect(po({ type: "other", label: "   " })).toBe(true);
		expect(po({ type: "other", label: "port fees" })).toBe(false);
		expect(po({ type: "transport", label: "" })).toBe(false);
	});

	it("says so on the row, and does not disable Save", () => {
		expect(editor).toMatch(/needsChargeLabel\(line\)/);
		expect(board).toMatch(/needsChargeLabel\(l\)/);
		const saveButton = editor.slice(editor.indexOf('class="btn btn-primary"'));
		expect(saveButton.slice(0, 200)).not.toMatch(/needsChargeLabel/);
	});
});

describe("the icons stay client-side, and cover every type", () => {
	it("gives all nine types an icon", () => {
		// The ADR allows the iconography to stay in the component — it is not the
		// list, it is a presentation of it. The risk it carries instead: a type
		// added on the server renders with a blank or a fallback icon nobody
		// notices. WHAT WOULD MAKE THIS FAIL: a tenth type, or a renamed key.
		const chargeIcon = load(board, "chargeIcon");
		for (const { key } of CANONICAL) {
			expect(chargeIcon(key), `${key} has no icon`).toMatch(/^ti-\S+$/);
		}
	});
});
