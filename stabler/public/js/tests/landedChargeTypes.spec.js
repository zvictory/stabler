import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

import { chargeTypeLabel, chargeTypes } from "../composables/landedChargeTypes.js";
// The real conversion rule, injected into the extracted `priceLines` — a total
// computed with a stub is not the total the footer shows.
import { convertedPreview } from "../composables/landedLine.js";

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

/** The server's VAT aliases, read from the module that defines them. */
const VAT_ALIASES = [
	...(catalogue.match(/_VAT_ALIASES = frozenset\(\{([^}]*)\}\)/)?.[1] || "").matchAll(/"([^"]+)"/g),
].map(([, alias]) => alias);

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

/** Same trick for a module-level object literal, so a spec can read its keys. */
function extractConst(src, name) {
	const at = src.indexOf(`const ${name} = `);
	expect(at, `${name} is gone — has it moved or been renamed?`).toBeGreaterThan(-1);
	return `const ${name} = ${braceMatched(src, src.indexOf("{", at))};`;
}

const extractDecl = (src, name) =>
	src.includes(`function ${name}(`) ? extractFunction(src, name) : extractConst(src, name);

const load = (src, name, ...deps) =>
	new Function(`${[...deps, name].map((n) => extractDecl(src, n)).join("\n")}\nreturn ${name};`)();

const loadConst = (src, name) => new Function(`${extractConst(src, name)}\nreturn ${name};`)();

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
		// Same guard, for the other list this spec reads out of that module. Not
		// against an empty parse -- that fails loudly on its own, because with no
		// aliases `readBack` is the identity and the invariant below goes red on
		// the no-edit alias case. Against a CHANGE: the invariant models the
		// server's forcing from this list, so a spelling added or removed there
		// silently changes what the model claims, and this is the only assertion
		// that notices (measured: a fourth alias fails this line and nothing else).
		expect(VAT_ALIASES).toEqual(["vat", "value added tax", "ндс"]);
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
		expect(loaded.charge_type_canonical).toBe("transport");
		expect(chargeTypeLabel(loaded.charge_type_canonical)).toBe("Freight / transport");
	});

	it("moves a legacy PO broker line onto the declarant option", () => {
		// `broker` and `declarant` were two options on ONE list for the same
		// person. WHAT WOULD MAKE THIS FAIL: binding `c.type` — the select would
		// fall back to its first option and a save would silently retype the line.
		const line = load(board, "editorLine")({ type: "broker", type_canonical: "declarant" });
		expect(line.type_canonical).toBe("declarant");
	});

	it("keeps the words of an unrecognised quotation type on screen", () => {
		// Quotation charge types are free text on disk ("Local Delivery"). The
		// server maps them to `other` and hands back what it could not
		// recognise; dropping that here leaves a line reading "Other" and
		// nothing else. The claim is unchanged; where the words go is not. They
		// used to be seeded into `description`, which is a field the save sends
		// — so a line with no description grew one. They ride their own key now
		// and the template shows them as the placeholder.
		const loaded = load(editor, "loadedLine")({
			charge_type: "Local Delivery",
			charge_type_canonical: "other",
			charge_type_unmapped: "Local Delivery",
			description: "",
		});
		expect(loaded.charge_type_canonical).toBe("other");
		expect(loaded.charge_type_unmapped).toBe("Local Delivery");
		expect(loaded.description).toBe("");
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
		const quotationLine = addedLine(editor, "addChargeLine", "charges");
		expect(quotationLine.charge_type).toBe("transport");
		expect(quotationLine.charge_type_canonical).toBe("transport");
		const poLine = addedLine(board, "addLine", "editorLines");
		expect(poLine.type).toBe("transport");
		expect(poLine.type_canonical).toBe("transport");
	});
});

describe("opening a plan and saving it does not rename what is on disk", () => {
	// The review's P0. `save_po_landed_charges` and `update_quotation_landed`
	// REPLACE the stored array, so whatever the editor hands back becomes the
	// disk. The row used to be loaded with the CANONICAL key in the field the
	// save sends, so pressing Save for any reason at all — a corrected amount, a
	// linked invoice — rewrote every legacy `broker` to `declarant` and every
	// `Freight` to `transport`. That is the one thing ADR-606 promised not to do,
	// and it is not cosmetic: `api/lcv.py` identifies an LCV row as
	// `label or type`, and a label is optional, so a renamed line stops matching
	// the descriptions an earlier LCV already consumed and the same charge is
	// posted into valuation and the GL a second time.
	//
	// So the stored key and the displayed key are two fields. The <select> binds
	// the display one; only an explicit pick by the officer writes it into the
	// stored one.
	it("hands back the PO line's stored key, not the one the select showed", () => {
		const savedLine = load(board, "savedLine");
		for (const [stored, canonical] of [
			["broker", "declarant"],
			["loading", "storage"],
			["transport", "transport"],
		]) {
			const row = load(board, "editorLine")({ type: stored, type_canonical: canonical, amount_given: 100 });
			expect(savedLine(row).type, `a ${stored} line came back as something else`).toBe(stored);
		}
	});

	it("hands back the quotation line's stored charge_type", () => {
		const savedChargeLine = load(editor, "savedChargeLine");
		for (const [stored, canonical] of [
			["Freight", "transport"],
			["Customs Duty", "customs"],
			["VAT", "other"],
			["General", "other"],
			["Local Delivery", "other"],
		]) {
			const row = load(editor, "loadedLine")({
				charge_type: stored,
				charge_type_canonical: canonical,
				amount: 100,
			});
			expect(savedChargeLine(row).charge_type, `a ${stored} line came back as something else`).toBe(
				stored,
			);
		}
	});

	it("does not turn the unrecognised type into a description", () => {
		// The server hands back the words it could not map (`charge_type_unmapped`)
		// so the officer can still read them. Seeding the DESCRIPTION with them
		// was the same mistake as seeding `charge_type` with the canonical key:
		// the field is what `savedChargeLine` sends, so a line stored as
		// `{charge_type: "Local Delivery", description: ""}` grew a description
		// on the next save made for an unrelated reason. The words are a
		// placeholder now — visible, and not something the officer wrote.
		// WHAT WOULD MAKE THIS FAIL: `description: c.description || c.charge_type_unmapped`.
		const row = load(editor, "loadedLine")({
			charge_type: "Local Delivery",
			charge_type_canonical: "other",
			charge_type_unmapped: "Local Delivery",
			description: "",
			amount: 100,
		});
		const sent = load(editor, "savedChargeLine")(row);
		expect(sent.description).toBe("");
		expect(sent.charge_type).toBe("Local Delivery");
		// And nothing else travels. The read adds keys to the line the write must
		// not send back — `charge_type_canonical`, `charge_type_unmapped`,
		// `charge_type_is_vat`, `company_amount`, `unvalued` — and this save
		// REPLACES the stored array, so a derived key that rejoins the payload
		// lands on disk as evidence. Asserting the exact set is the only version
		// of this that fails; every `toBe` above passes with extras present.
		// WHAT WOULD MAKE THIS FAIL: any key added to or dropped from the RAW
		// shape (`_landed.raw_charge_line`) without this list moving with it.
		expect(Object.keys(sent).sort()).toEqual([
			"amount",
			"amount_original",
			"charge_type",
			"currency",
			"description",
			"fx_rate",
			"is_recoverable_vat",
			"rate_date",
		]);
		// Still shown, just not as data: the template reads it as the placeholder.
		expect(row.charge_type_unmapped).toBe("Local Delivery");
		expect(editor.slice(editor.indexOf("<template>"))).toMatch(
			/:placeholder="line\.charge_type_unmapped \|\|/,
		);
	});

	it("writes the new key only when the officer picks one", () => {
		// The other half: a rename the officer ASKED for must reach the disk.
		// WHAT WOULD MAKE THIS FAIL: dropping `onTypeChange`, which would leave
		// the select purely decorative — every pick silently discarded on save.
		const poRow = load(board, "editorLine")({ type: "broker", type_canonical: "declarant" });
		poRow.type_canonical = "legal";
		load(board, "onTypeChange")(poRow);
		expect(load(board, "savedLine")(poRow).type).toBe("legal");

		const quotationRow = load(editor, "loadedLine")({
			charge_type: "Freight",
			charge_type_canonical: "transport",
		});
		quotationRow.charge_type_canonical = "insurance";
		load(editor, "onTypeChange")(quotationRow);
		expect(load(editor, "savedChargeLine")(quotationRow).charge_type).toBe("insurance");
	});

	it("binds the select to the display key in both editors", () => {
		// The regression is one attribute wide, so it is asserted as one.
		expect(board).toMatch(/<select v-model="l\.type_canonical"[\s\S]{0,120}@change="onTypeChange\(l\)"/);
		expect(editor).toMatch(
			/<select v-model="line\.charge_type_canonical"[\s\S]{0,120}@change="onTypeChange\(line\)"/,
		);
	});
});

describe("un-ticking recoverable VAT is an edit, and has to reach the store", () => {
	// The review's P1, and the one place where NOT rewriting the stored type is
	// the bug. `_landed.py` forces `is_recoverable_vat` ON for any line whose
	// STORED `charge_type` is a VAT spelling, and never rewrites that spelling.
	// So an officer who un-ticks the box on a legacy "VAT" line watched the
	// modal's total gain the 300 while `base_landed_total` — the figure that
	// ranks the vendors — kept the old one, and on reopen the box was ticked
	// again. The edit was discarded silently, and the two totals disagreed in
	// between.
	//
	// The fix is not a client-side alias list (a second copy of the table, which
	// is the defect ADR-606 exists to remove). The server states the fact:
	// `charge_type_is_vat` rides beside `charge_type_canonical`, and the
	// checkbox handler reads it.
	const untick = (row) => {
		row.is_recoverable_vat = false;
		load(editor, "onVatChange")(row);
		return row;
	};

	/** `_landed.parse_landed_charges`, for the one field under test: the flag
	 *  comes back FORCED when the STORED spelling is an alias. Modelled here
	 *  rather than stubbed, and from the server's own table (parsed above) so
	 *  this spec cannot drift from the read it is claiming about. */
	const readBack = (sent) => {
		const spelling = String(sent.charge_type || "").trim().toLowerCase();
		return { ...sent, is_recoverable_vat: Boolean(sent.is_recoverable_vat) || VAT_ALIASES.includes(spelling) };
	};

	/** Exactly what `parse_landed_charges` returns for a line stored as "VAT"
	 *  with `is_recoverable_vat` false on disk: the flag comes back FORCED. */
	const SERVER_VAT_STORED_FALSE = {
		charge_type: "VAT",
		charge_type_canonical: "other",
		charge_type_unmapped: "",
		charge_type_is_vat: true,
		is_recoverable_vat: true,
		is_recoverable_vat_stored: false,
		amount: 300,
	};
	/** The same line as main's editor left it: the forced flag persisted. */
	const SERVER_VAT_STORED_TRUE = { ...SERVER_VAT_STORED_FALSE, is_recoverable_vat_stored: true };
	/** Never VAT by spelling; the officer ticked the box by hand. */
	const SERVER_FREIGHT_STORED_TRUE = {
		charge_type: "Freight",
		charge_type_canonical: "transport",
		charge_type_unmapped: "",
		charge_type_is_vat: false,
		is_recoverable_vat: true,
		is_recoverable_vat_stored: true,
		amount: 300,
	};

	const legacyVatRow = () =>
		load(editor, "loadedLine")({
			charge_type: "VAT",
			charge_type_canonical: "other",
			charge_type_is_vat: true,
			is_recoverable_vat: true,
			amount: 300,
		});

	it("moves the stored type off the VAT spelling the server would re-flag", () => {
		// WHAT WOULD MAKE THIS FAIL: leaving `charge_type` alone — the save
		// posts "VAT" again, `_landed.py:149` turns the flag back on, and the
		// officer's edit never happened.
		const sent = load(editor, "savedChargeLine")(untick(legacyVatRow()));
		expect(sent.charge_type).toBe("other");
		expect(sent.is_recoverable_vat).toBe(false);
	});

	it("counts the line the officer just made ordinary", () => {
		const priceLines = new Function(
			"convertedPreview",
			`${extractFunction(editor, "priceLines")}\nreturn priceLines;`,
		)(convertedPreview);
		expect(priceLines([legacyVatRow()]).total).toBe(0);
		expect(priceLines([untick(legacyVatRow())]).total).toBe(300);
	});

	it("asks what the charge is, now that it is no longer VAT", () => {
		// `other` with nothing beside it. The prompt is the right one: a line
		// that stopped being recoverable VAT has to say what it is instead.
		expect(load(editor, "needsChargeLabel")(untick(legacyVatRow()))).toBe(true);
	});

	it("rewrites nothing when the box is ticked back on", () => {
		// Only the un-tick is an edit the server cannot infer. Rewriting on both
		// edges would rename lines nobody renamed — the P0 again, one checkbox
		// further along.
		// WHAT WOULD MAKE THIS FAIL: an unconditional `charge_type = canonical`.
		const row = legacyVatRow();
		row.is_recoverable_vat = true;
		load(editor, "onVatChange")(row);
		expect(load(editor, "savedChargeLine")(row).charge_type).toBe("VAT");
	});

	it("leaves an ordinary line alone when its box is cleared", () => {
		// A `transport` line whose officer ticked the box by mistake and cleared
		// it again: nothing about it was ever VAT, so nothing may move.
		const row = load(editor, "loadedLine")({
			charge_type: "Freight",
			charge_type_canonical: "transport",
			charge_type_is_vat: false,
			is_recoverable_vat: true,
			amount: 300,
		});
		expect(load(editor, "savedChargeLine")(untick(row)).charge_type).toBe("Freight");
	});

	it("wires the handler to the checkbox", () => {
		expect(editor.slice(editor.indexOf("<template>"))).toMatch(
			/v-model="line\.is_recoverable_vat"[\s\S]{0,200}@change="onVatChange\(line\)"/,
		);
	});

	it("hands back the flag that was on disk, not the one the alias table forced", () => {
		// `is_recoverable_vat` was the last stored key a no-edit save still moved.
		// The valued line carries the MERGED flag — raw flag OR the stored
		// spelling is an alias — because every consumer of the read needs that.
		// Sending it back persisted the alias table's verdict into the evidence
		// field: disk `{"charge_type": "VAT", "is_recoverable_vat": false}`, one
		// save made for an unrelated reason, and the flag is true on disk.
		//
		// Not fixed by sending `flag && !charge_type_is_vat` — that only inverts
		// the drift, normalising a row main's editor had already persisted as
		// true back to false, so saved and never-saved rows still diverge. The
		// rule is the one `charge_type` follows: hand back what was loaded unless
		// the officer changed it. On an alias-spelled line the box is DISPLAYED
		// ticked, so the only edit available is the un-tick, and `onVatChange`
		// clears `charge_type_is_vat` on exactly that edge.
		const saved = (valued) => load(editor, "savedChargeLine")(load(editor, "loadedLine")(valued));

		// Stored false, forced true by the spelling: the disk's false goes back.
		// WHAT WOULD MAKE THIS FAIL: sending `Boolean(c.is_recoverable_vat)`.
		expect(saved(SERVER_VAT_STORED_FALSE).is_recoverable_vat).toBe(false);
		expect(saved(SERVER_VAT_STORED_FALSE).charge_type).toBe("VAT");

		// Stored true — a row main's editor already persisted. Still true.
		// WHAT WOULD MAKE THIS FAIL: `flag && !c.charge_type_is_vat`.
		expect(saved(SERVER_VAT_STORED_TRUE).is_recoverable_vat).toBe(true);
		expect(saved(SERVER_VAT_STORED_TRUE).charge_type).toBe("VAT");

		// Hand-ticked on a line that was never VAT: sent as displayed, as before.
		expect(saved(SERVER_FREIGHT_STORED_TRUE).is_recoverable_vat).toBe(true);
		expect(saved(SERVER_FREIGHT_STORED_TRUE).charge_type).toBe("Freight");

		// And the un-tick still gets through: `onVatChange` has cleared
		// `charge_type_is_vat`, so what is displayed is what is sent.
		const untickedRow = untick(load(editor, "loadedLine")(SERVER_VAT_STORED_FALSE));
		const sent = load(editor, "savedChargeLine")(untickedRow);
		expect(sent.is_recoverable_vat).toBe(false);
		expect(sent.charge_type).toBe("other");
	});

	it("retires the alias fact when the officer renames the line", () => {
		// The P0 in e300618, and the false premise under it: the un-tick was NOT
		// the only edit available on an alias-spelled line. The <select> is the
		// second, `needsChargeLabel` red-flags exactly these rows and invites a
		// pick, and `onTypeChange` moved only `charge_type` — so after renaming
		// a stored "VAT" line to Freight, `charge_type_is_vat` was a stale true
		// and `savedChargeLine` sent the disk's false while the box on screen
		// still read ticked. None of the nine canonical keys is a VAT alias, so
		// the server never forces the flag again: the officer sees a line
		// excluded from the footer and saves one that capitalizes 300 into
		// `base_landed_total` — which is what `rank_quotations_landed` ranks and
		// `_snapshot_rows` freezes. An award decided against a total nobody saw.
		//
		// So a type change retires the fact too, and the checkbox follows the
		// disk on the way past: the officer WATCHES the box un-tick and can
		// re-tick it if the charge really is recoverable.
		// WHAT WOULD MAKE THIS FAIL: `onTypeChange` moving only `charge_type`.
		const renamed = (valued) => {
			const row = load(editor, "loadedLine")(valued);
			row.charge_type_canonical = "transport";
			load(editor, "onTypeChange")(row);
			return row;
		};

		const fromFalse = renamed(SERVER_VAT_STORED_FALSE);
		expect(fromFalse.is_recoverable_vat).toBe(false);
		expect(fromFalse.charge_type_is_vat).toBe(false);
		expect(load(editor, "savedChargeLine")(fromFalse)).toMatchObject({
			charge_type: "transport",
			is_recoverable_vat: false,
		});

		// Stored true: nothing invented, nothing lost — the box stays ticked.
		const fromTrue = renamed(SERVER_VAT_STORED_TRUE);
		expect(fromTrue.is_recoverable_vat).toBe(true);
		expect(load(editor, "savedChargeLine")(fromTrue)).toMatchObject({
			charge_type: "transport",
			is_recoverable_vat: true,
		});
	});

	it("shows the officer the state the next read will show them", () => {
		// The invariant the P0 broke, stated over every edit sequence a row can
		// reach rather than over the one that happened to be found. Not
		// `sent === shown`: round 4 made the no-edit save on an alias-spelled
		// line send the disk's flag while displaying the forced one, and that is
		// correct precisely BECAUSE the read forces it again. What must hold is
		// one step further out — the screen the officer is looking at is the
		// screen they get back. Anything else is an estimate that changed itself
		// while nobody was looking, and `base_landed_total` is downstream of it.
		// WHAT WOULD MAKE THIS FAIL: any edit that leaves `charge_type_is_vat`
		// disagreeing with the `charge_type` beside it.
		const onVat = load(editor, "onVatChange");
		const onType = load(editor, "onTypeChange");
		const sequences = {
			"no edit": () => {},
			"un-tick": (r) => {
				r.is_recoverable_vat = false;
				onVat(r);
			},
			"un-tick, then re-tick": (r) => {
				r.is_recoverable_vat = false;
				onVat(r);
				r.is_recoverable_vat = true;
				onVat(r);
			},
			"type change": (r) => {
				r.charge_type_canonical = "transport";
				onType(r);
			},
			"type change, then tick": (r) => {
				r.charge_type_canonical = "transport";
				onType(r);
				r.is_recoverable_vat = true;
				onVat(r);
			},
			"tick, then type change": (r) => {
				r.is_recoverable_vat = true;
				onVat(r);
				r.charge_type_canonical = "transport";
				onType(r);
			},
		};
		for (const [state, valued] of Object.entries({
			"VAT, stored false": SERVER_VAT_STORED_FALSE,
			"VAT, stored true": SERVER_VAT_STORED_TRUE,
			"Freight, stored true": SERVER_FREIGHT_STORED_TRUE,
		})) {
			for (const [name, edit] of Object.entries(sequences)) {
				const row = load(editor, "loadedLine")(valued);
				edit(row);
				const shown = row.is_recoverable_vat;
				const reread = readBack(load(editor, "savedChargeLine")(row));
				expect(reread.is_recoverable_vat, `${state} + ${name}`).toBe(shown);
			}
		}
	});

	it("takes the fact from the server, and does not keep a list of its own", () => {
		// WHAT WOULD MAKE THIS FAIL: any VAT spelling appearing in the component.
		// One list, on the server — that is the whole ADR.
		expect(extractFunction(editor, "onVatChange")).toMatch(/charge_type_is_vat/);
		expect(editor).not.toMatch(/["']value added tax["']/i);
		expect(editor).not.toMatch(/["']НДС["']/i);
	});
});

describe("a failed load never becomes an empty save", () => {
	// Both editors used to fetch the charges and the type list with one
	// `Promise.all`, catch, toast, and drop out of `loading` with an EMPTY row
	// array and an enabled Save. `save_po_landed_charges` replaces the whole
	// array, so one pressed button after a transient failure of a constant
	// endpoint wiped a Purchase Order's landed plan — or a quotation's estimate.
	it("keeps an explicit error state instead of an empty table", () => {
		expect(board).toMatch(/editorError/);
		expect(editor).toMatch(/loadError/);
		// The table must not render on the error branch, or an empty plan is
		// exactly what the officer sees and believes.
		expect(board).toMatch(/v-else-if="editorError"/);
		expect(editor).toMatch(/v-else-if="loadError"/);
	});

	it("disables Save while the load has failed", () => {
		const poSave = board.slice(board.indexOf('@click="saveEditor"') - 300, board.indexOf('@click="saveEditor"'));
		expect(poSave).toMatch(/:disabled="[^"]*editorError/);
		const quotationSave = editor.slice(
			editor.indexOf('@click="save"') - 300,
			editor.indexOf('@click="save"'),
		);
		expect(quotationSave).toMatch(/:disabled="[^"]*loadError/);
	});

	it("refuses to send anything even if the button is reached", () => {
		// A disabled attribute is a rendering, not a guarantee — the save path
		// itself has to refuse, or a re-render race puts an empty array on disk.
		// Read as source rather than composed: both are `async`, which
		// `extractFunction` cannot hand to `new Function`.
		expect(extractFunction(board, "saveEditor")).toMatch(/if \(editorError\.value\) return;/);
		expect(extractFunction(editor, "save")).toMatch(/if \(loadError\.value\) return;/);
	});

	it("treats a missing type list as a failed load, not a usable editor", () => {
		// The two awaits are sequential and share ONE try, so a rejected type
		// list DOES abort the charge read — deliberately. A <select> with no
		// options cannot be used, so an editor that cannot offer the nine types
		// must not offer to save over the array it is about to replace. (This
		// spec was called "fetches the constant list separately" and its comment
		// claimed a rejected constant must not abort the data read. It does
		// abort it, and should; the name and the reason were both wrong.)
		// WHAT WOULD MAKE THIS FAIL: `Promise.all([...])` coming back, whose
		// rejection landed in a catch that toasted and left Save enabled over
		// zero rows; or the list fetch moving out of the try that sets the error.
		for (const [src, fn] of [
			[board, "openEditor"],
			[editor, "load"],
		]) {
			const body = extractFunction(src, fn);
			expect(body).not.toMatch(/Promise\.all\(\[[\s\S]{0,200}loadChargeTypes\(\)/);
			expect(body).toMatch(/try \{/);
			expect(body.indexOf("await loadChargeTypes()")).toBeGreaterThan(body.indexOf("try {"));
			expect(body.indexOf("call(")).toBeGreaterThan(body.indexOf("await loadChargeTypes()"));
		}
	});
});

describe("`other` is the one type that has to be named", () => {
	it("flags an other line with nothing written beside it", () => {
		// ADR-606: `other` names no cost on its own. An estimate whose largest
		// line reads "Other" is not an estimate anyone can check.
		// WHAT WOULD MAKE THIS FAIL: dropping the check, or blocking the save
		// instead — the council's rule is flag, don't block; an estimate typed
		// under deadline must stay saveable half-finished.
		// Asked of the DISPLAYED type, not the stored one: the officer is being
		// asked about the option in front of them. A legacy line stored "General"
		// shows as Other, so it is flagged; one stored "Freight" is not.
		const quotation = load(editor, "needsChargeLabel");
		expect(quotation({ charge_type: "General", charge_type_canonical: "other", description: "" })).toBe(true);
		expect(quotation({ charge_type: "other", charge_type_canonical: "other", description: "port fees" })).toBe(false);
		expect(quotation({ charge_type: "Freight", charge_type_canonical: "transport", description: "" })).toBe(false);

		const po = load(board, "needsChargeLabel");
		expect(po({ type: "other", type_canonical: "other", label: "" })).toBe(true);
		expect(po({ type: "other", type_canonical: "other", label: "   " })).toBe(true);
		expect(po({ type: "other", type_canonical: "other", label: "port fees" })).toBe(false);
		expect(po({ type: "broker", type_canonical: "declarant", label: "" })).toBe(false);
	});

	it("says so on the row, and does not disable Save", () => {
		// Asserted on the RENDERING. `toMatch(/needsChargeLabel\(line\)/)` over
		// the whole file was satisfied by the function DECLARATION, so deleting
		// every use in both templates left this green — the predicate existed
		// and nothing drew it.
		// WHAT WOULD MAKE THIS FAIL: removing the invalid-state class or the
		// hint from either template.
		const quotationTemplate = editor.slice(editor.indexOf("<template>"));
		expect(quotationTemplate).toMatch(/:class="\{ 'is-invalid': needsChargeLabel\(line\) \}"/);
		expect(quotationTemplate).toMatch(/v-if="needsChargeLabel\(line\)"/);

		const boardTemplate = board.slice(board.indexOf("<template>"));
		expect(boardTemplate).toMatch(/:class="\{ 'is-invalid': needsChargeLabel\(l\) \}"/);
		expect(boardTemplate).toMatch(/v-if="needsChargeLabel\(l\)"/);

		const saveButton = editor.slice(editor.indexOf('class="btn btn-primary"'));
		expect(saveButton.slice(0, 200)).not.toMatch(/needsChargeLabel/);
	});

	it("does not ask a line that already says what it is", () => {
		// A legacy line stored "Local Delivery" resolves to `other`, and its
		// words now live in the placeholder rather than the description — so the
		// naive predicate would paint every such row red and demand a name it
		// has already got, on disk. The question is whether the cost is NAMED,
		// not which field names it.
		// WHAT WOULD MAKE THIS FAIL: dropping the `charge_type_unmapped` half.
		const quotation = load(editor, "needsChargeLabel");
		expect(
			quotation({
				charge_type: "Local Delivery",
				charge_type_canonical: "other",
				charge_type_unmapped: "Local Delivery",
				description: "",
			}),
		).toBe(false);
		expect(
			quotation({ charge_type: "General", charge_type_canonical: "other", charge_type_unmapped: "", description: "" }),
		).toBe(true);
	});
});

describe("the icons stay client-side, and cover every type", () => {
	it("keys the icon map by exactly the nine the server ships", () => {
		// The ADR allows the iconography to stay in the component — it is not the
		// list, it is a presentation of it. The risk it carries instead: a type
		// added on the server renders with the fallback icon and nobody notices.
		//
		// So this reads the MAP's own keys. Calling `chargeIcon(key)` and
		// checking the answer looks like `ti-…` cannot fail at all: the function
		// ends in `|| "ti-dots"`, so a tenth type — the exact thing this spec
		// exists to catch — would have passed it wearing the `other` icon.
		// WHAT WOULD MAKE THIS FAIL: a tenth type, or a renamed key.
		expect(Object.keys(loadConst(board, "CHARGE_ICONS"))).toEqual(CANONICAL.map((c) => c.key));
	});

	it("still answers with a real icon for every one of them", () => {
		const chargeIcon = load(board, "chargeIcon", "CHARGE_ICONS");
		for (const { key } of CANONICAL) {
			expect(chargeIcon(key), `${key} has no icon`).toMatch(/^ti-\S+$/);
		}
	});
});
