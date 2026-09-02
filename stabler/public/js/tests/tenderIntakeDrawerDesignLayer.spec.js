import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "fs";
import { dirname, join, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const JS_ROOT = resolve(here, "..");
const src = readFileSync(resolve(JS_ROOT, "components/TenderMasterDrawer.vue"), "utf8");
const crm = readFileSync(resolve(JS_ROOT, "pages/tender/TenderCrm.vue"), "utf8");
const shell = readFileSync(resolve(JS_ROOT, "pages/tender/TenderPage.vue"), "utf8");
const layer = readFileSync(resolve(JS_ROOT, "../css/stabler-modernist.css"), "utf8");

/**
 * Prompt 01 — the tender intake drawer speaks the module's design layer.
 *
 * The council's gate (2026-09-01 ACCEPTANCE #1) is deliberately a CONJUNCTION:
 * `tgm-` to zero AND `ds-drawer` AND `ds-form-section` AND `data-size="lg"`.
 * Deleting fifteen class names satisfies the first clause on its own and leaves
 * an unstyled drawer, so every clause below is asserted against the same tag —
 * and the layer is scoped under `.stbl-ds` (`test_design_layer_contract.py:65`),
 * so the mount site is asserted too. A class name nobody's CSS can reach is a
 * rename, not a migration.
 *
 * DOM-less on purpose: `vitest.config.mjs:15` is `environment: "node"` and
 * `@vue/test-utils` is not a dependency. Where the claim is about BEHAVIOUR the
 * expression or function is extracted from the source and EXECUTED, in the idiom
 * of `sourcingAwardPanel.spec.js` — a `toContain` passes just as happily on a
 * branch wired backwards.
 */

/** The full opening tag that carries `needle`. */
function tagCarrying(needle, what) {
	const at = src.indexOf(needle);
	expect(at, `${what}: "${needle}" not found — has the markup moved?`).toBeGreaterThan(-1);
	const open = src.lastIndexOf("<", at);
	const close = src.indexOf(">", at);
	expect(close, `${what}: unterminated tag`).toBeGreaterThan(open);
	return src.slice(open, close + 1);
}

function braceMatched(text, from) {
	let depth = 0;
	for (let i = from; i < text.length; i++) {
		if (text[i] === "{") depth++;
		else if (text[i] === "}" && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error("unterminated block");
}

/** `async function name(…) {…}`, lifted out of the `<script setup>` block. */
function extractFunction(name) {
	const at = src.search(new RegExp(`(?:async\\s+)?function ${name}\\(`));
	expect(at, `${name}() is gone — has it moved or been renamed?`).toBeGreaterThan(-1);
	const braceStart = src.indexOf("{", at);
	return src.slice(at, braceStart) + braceMatched(src, braceStart);
}

/** Evaluate a template expression against a supplied render scope. */
function evalInScope(expression, scope) {
	const keys = Object.keys(scope);
	return new Function(...keys, `return (${expression});`)(...keys.map((k) => scope[k]));
}

/** Every `.vue` file under the SPA source tree. */
function vueFiles(dir = JS_ROOT, out = []) {
	for (const entry of readdirSync(dir, { withFileTypes: true })) {
		const full = join(dir, entry.name);
		if (entry.isDirectory()) vueFiles(full, out);
		else if (entry.name.endsWith(".vue")) out.push(full);
	}
	return out;
}

/**
 * A stubbed `save()` run: returns what the drawer asked the server to do.
 *
 * The row is the seed's own — `("UTY-2026-4309", "Qurilish materiallari
 * kombinati", "sourcing", 26, 3, 1, 410000000)` in `seed_tender_demo.py`,
 * with its item (`DEMO_ITEM + DEMO_SUFFIX`). Nothing here is invented:
 * ACCEPTANCE #9, and a fixture reading "Acme Corp / Lot-001 / $1,000" would
 * also have hidden the one thing this drawer gets wrong about long buyer
 * names in four alphabets.
 */
function runSave(overrides = {}) {
	const form = {
		name: "",
		organization: "Qurilish materiallari kombinati",
		tender_no: "UTY-2026-4309",
		title: "Qurilish materiallari kombinati · UTY-2026-4309",
		source: "UZEX",
		publication_date: "2026-09-01",
		submission_deadline: "2026-09-28",
		currency: "UZS",
		estimated_total: 0,
		items: [],
		files: [],
		go_no_go: "",
		guarantee_amount: 0,
		guarantee_return: "",
		penalty_pct_per_day: null,
		cert_required: 0,
		purchase_method: "",
		...overrides,
	};
	const calls = [];
	const errors = [];
	const emitted = [];
	const scope = {
		form,
		saving: { value: false },
		activeCompany: { value: "Mikas" },
		itemTotal: { value: (form.items || []).reduce((s, l) => s + (Number(l.amount) || 0), 0) },
		call: (method, args) => {
			calls.push({ method, args });
			return Promise.resolve({ name: "CRM-DEAL-0001" });
		},
		toast: { error: (m) => errors.push(m), success: () => {} },
		t: (s) => s,
		emit: (...a) => emitted.push(a),
	};
	// `close` is the drawer's OWN function, lifted from the same source and given
	// the recording `emit` — a hand-written stub would have hidden which events
	// the board actually receives, and `update:open` is the one that shuts the
	// drawer after a save.
	const keys = Object.keys(scope);
	const build = (name) =>
		new Function(...keys, `${extractFunction(name)}\nreturn ${name};`)(
			...keys.map((k) => scope[k])
		);
	scope.close = build("close");
	keys.push("close");
	const save = new Function(...keys, `${extractFunction("save")}\nreturn save;`)(
		...keys.map((k) => scope[k])
	);
	return save().then(() => ({ calls, errors, emitted }));
}

describe("ACCEPTANCE #1 — the third dialect is gone and the layer is actually wearing it", () => {
	it("carries no `tgm-` token anywhere in the file", () => {
		// WHAT WOULD MAKE THIS FAIL: putting a single `tgm-*` class back on any
		// element, or leaving one of its rules behind in the scoped <style> block.
		// 46 sites over 15 classes were measured here on 2026-09-01; the whole
		// private dialect lived in this one file and ADR-301 retires it.
		expect(src).not.toContain("tgm-");
	});

	it('puts `ds-drawer` and `data-size="lg"` on the SAME element', () => {
		// WHAT WOULD MAKE THIS FAIL: renaming the shell to `ds-drawer` but dropping
		// the size hook (the drawer silently reverts to the layer's 542px default),
		// or parking `data-size` on a wrapper the width rule cannot see —
		// `.stbl-ds .ds-drawer[data-size="lg"]` is one compound selector.
		const dialog = tagCarrying('class="ds-drawer"', "drawer shell");
		expect(dialog).toContain('data-size="lg"');
		expect(layer).toContain('.stbl-ds .ds-drawer[data-size="lg"]');
	});

	it("frames all five sections with `ds-form-section`, each with a head and a body", () => {
		// WHAT WOULD MAKE THIS FAIL: migrating the shell but leaving the sections in
		// the old dialect, or splitting the head/body pair so the grey section head
		// (`ds-form-section-head`) and its padded body (`ds-form-body`) stop matching.
		const sections = src.match(/class="ds-form-section"/g) || [];
		expect(sections.length).toBe(5);
		expect((src.match(/class="ds-form-section-head"/g) || []).length).toBe(5);
		expect((src.match(/class="ds-form-body"/g) || []).length).toBe(5);
	});

	it("keeps each section letter inside its heading rather than in a badge of its own", () => {
		// WHAT WOULD MAKE THIS FAIL: reviving the `A` badge element next to the
		// heading. The canvas settled this on 2026-09-01: a letter in its own box
		// drifts from its section the first time the form is reordered, and a
		// translator cannot see what it belongs to.
		for (const letter of ["A", "B", "C", "D", "E"]) {
			const head = src.indexOf(`>${letter} · `);
			expect(head, `section ${letter}'s heading is not one string`).toBeGreaterThan(-1);
			expect(src.slice(src.lastIndexOf("<", head), head)).toContain('class="ds-label"');
		}
	});
});

describe("the fields speak the layer's grammar, and the controls stay bridged", () => {
	it("has no `form-label` and no Bootstrap grid left in the form", () => {
		// WHAT WOULD MAKE THIS FAIL: putting one `form-label` or one `row`/`col-*`
		// back. The layer ships this vocabulary already (`ds-field` 6 rules,
		// `ds-form-grid` 5, `ds-label` 8) — a field that keeps Bootstrap's label and
		// grid is being carried by the bridge, not by the layer, and the next screen
		// copied from this one carries the same half-migration forward.
		expect(src).not.toContain("form-label");
		// Tokenised, not a substring match: `ds-file-row` ends in "row" and is not
		// a Bootstrap grid class.
		const classTokens = [...src.matchAll(/class="([^"]*)"/g)].flatMap((m) => m[1].split(/\s+/));
		const grid = classTokens.filter((c) => c === "row" || /^col(-\w+)?(-\d+|-auto)?$/.test(c));
		expect(grid).toEqual([]);
	});

	it("wraps every labelled field in `ds-field` with exactly one `ds-label`", () => {
		// WHAT WOULD MAKE THIS FAIL: a `ds-field` with no label (an unnamed control),
		// or a field label written outside a `ds-field` (the layer's `min-width: 0`
		// is what stops a long Uzbek label — measured worst case is 3.75x the
		// English — from blowing the two-column grid open).
		const fields = src.match(/class="ds-field[ "]/g) || [];
		const labels = src.match(/<label class="ds-label"/g) || [];
		expect(fields.length).toBeGreaterThan(0);
		expect(labels.length).toBe(fields.length);
	});

	it("never asks the grid for three columns", () => {
		// WHAT WOULD MAKE THIS FAIL: `data-cols="3"`, which section E used to be
		// (`col-6 col-md-4`, three across). It is forbidden in this module: three
		// columns do not survive the interface-language growth, and the layer's own
		// 640px rule collapses them all to one anyway.
		expect((src.match(/class="ds-form-grid"/g) || []).length).toBeGreaterThan(0);
		for (const grid of src.match(/<div class="ds-form-grid" data-cols="\d"/g) || []) {
			expect(grid).toContain('data-cols="2"');
		}
		expect(src).not.toContain('data-cols="3"');
	});

	it("leaves the controls themselves on the bridged Bootstrap classes", () => {
		// WHAT WOULD MAKE THIS FAIL: rewriting the inputs to `ds-input`. MoneyInput,
		// DateInput and Typeahead render `.form-control` themselves and are shared
		// with screens outside `.stbl-ds`, so migrating the two bare controls beside
		// them would leave one form speaking two input vocabularies — and `ds-input`
		// is explicitly banned inside an `.input-group`.
		expect(src).not.toContain("ds-input");
		expect(src).toContain('class="form-control"');
		expect(src).toContain('class="form-select"');
	});
});

describe("the drawer is mounted where the layer can reach it", () => {
	it("is rendered inside `<TenderPage>`, whose root carries `stbl-ds`", () => {
		// WHAT WOULD MAKE THIS FAIL: dropping `stbl-ds` from the tender shell, or
		// moving the drawer out of `<TenderPage>` (e.g. to the router view). Every
		// rule in `stabler-modernist.css` is scoped under `.stbl-ds`, so outside
		// that subtree the migrated class names style exactly nothing — the
		// "unstyled drawer" the council's conjunction exists to reject.
		expect(shell).toMatch(/class="[^"]*\bstbl-ds\b/);
		const open = crm.indexOf("<TenderPage");
		const shut = crm.indexOf("</TenderPage>");
		const mount = crm.indexOf("<TenderMasterDrawer");
		expect(open).toBeGreaterThan(-1);
		expect(mount).toBeGreaterThan(open);
		expect(mount).toBeLessThan(shut);
	});

	it("has exactly one mount site in the whole SPA", () => {
		// WHAT WOULD MAKE THIS FAIL: a second screen mounting the drawer — which is
		// how it would come back outside a `.stbl-ds` subtree without anyone
		// noticing, and ADR-201 makes this drawer the sole writer of intake anyway.
		const mounts = vueFiles().filter((f) =>
			readFileSync(f, "utf8").includes("<TenderMasterDrawer")
		);
		expect(mounts.map((f) => f.slice(JS_ROOT.length + 1))).toEqual(["pages/tender/TenderCrm.vue"]);
	});

	it("uses the layer's own backdrop, which sits BELOW the drawer", () => {
		// WHAT WOULD MAKE THIS FAIL: keeping Bootstrap's `.modal-backdrop`. The old
		// shell was z-index 1050 with a 1040 scrim; `.ds-drawer` is 41. A Bootstrap
		// backdrop left behind paints its scrim over the migrated drawer and eats
		// every click in it — the drawer would look right and do nothing.
		expect(src).not.toContain("modal-backdrop");
		expect(src).toContain("ds-drawer-backdrop");
		const zIndex = (selector) => {
			const at = layer.indexOf(selector);
			expect(at, `${selector} is not in the layer`).toBeGreaterThan(-1);
			return Number(braceMatched(layer, layer.indexOf("{", at)).match(/z-index:\s*(\d+)/)[1]);
		};
		expect(zIndex(".stbl-ds .ds-drawer-backdrop")).toBeLessThan(zIndex(".stbl-ds .ds-drawer {"));
	});

	it("styles the file list it now names", () => {
		// WHAT WOULD MAKE THIS FAIL: naming the attachment rows `ds-file-*` while no
		// rule answers to those names — the tender pack would render as bare text
		// with no row, no border and no truncation. `ds-file-list` is the component
		// the 2026-09-01 canvas settled (ADR-302 vs Phase A §1.2), and the shipped
		// layer had no home for the three `tgm-file-*` classes it replaces.
		expect(tagCarrying('class="ds-file-list"', "file list")).toContain('data-mode="edit"');
		for (const cls of ["ds-file-list", "ds-file-row", "ds-file-name"]) {
			expect(layer, `${cls} is named but unstyled`).toContain(`.stbl-ds .${cls}`);
		}
	});

	it("renders file rows only from the form's own files", () => {
		// WHAT WOULD MAKE THIS FAIL: a hand-written example row inside the new file
		// list. ACCEPTANCE #9: nothing on a delivered screen may be invented — every
		// name and size on this surface arrives with the record.
		const rows = [...src.matchAll(/class="ds-file-row"/g)];
		expect(rows.length).toBe(1);
		expect(tagCarrying('class="ds-file-row"', "file row")).toContain(
			'v-for="(f, i) in form.files"'
		);
	});
});

describe("ACCEPTANCE #6 — the drawer's behaviour, executed from source", () => {
	it("saves the deal and then overlays the intake, in that order", async () => {
		// WHAT WOULD MAKE THIS FAIL: the migration reordering or dropping either
		// call. The intake overlay needs the deal name the first call returns, so a
		// swap loses every field the CRM Deal does not itself store — `title` has no
		// other home at all.
		const { calls, emitted } = await runSave();
		expect(calls.map((c) => c.method)).toEqual([
			"stabler.api.crm.save_deal",
			"stabler.api.tender.save_deal_intake",
		]);
		expect(calls[1].args.deal).toBe("CRM-DEAL-0001");
		// And it tells the board, then shuts. `@saved="load"` (TenderCrm.vue:943) is
		// the only thing that puts the new tender on the kanban — without the event
		// the deal exists on the server and the user is looking at a board that does
		// not have it. `update:open` is the drawer's half of `v-model:open`; dropping
		// it leaves the form standing open over a save that already happened, which
		// invites the second click that creates the duplicate.
		expect(emitted).toEqual([
			["saved", { name: "CRM-DEAL-0001" }],
			["update:open", false],
			["close"],
		]);
	});

	it("saves a tender with no items at all", async () => {
		// WHAT WOULD MAKE THIS FAIL: making items block the save. S7 (settled
		// 2026-09-01) keeps this a single form precisely because the user holding a
		// freshly published notice does not yet know the item list; only buyer and
		// title block. An empty list is a normal state here, not an error.
		const { calls, errors } = await runSave({ items: [] });
		expect(errors).toEqual([]);
		expect(calls[1].args.intake.items).toEqual([]);
	});

	it("refuses to save without a buyer or without a title, and calls nothing", async () => {
		// WHAT WOULD MAKE THIS FAIL: losing either guard while migrating the labels.
		// A deal saved with no organization lands on the board as an anonymous card
		// nobody can trace back to a buyer.
		const noBuyer = await runSave({ organization: "" });
		expect(noBuyer.calls).toEqual([]);
		expect(noBuyer.errors).toEqual(["Customer is required"]);
		const noTitle = await runSave({ title: "" });
		expect(noTitle.calls).toEqual([]);
		expect(noTitle.errors).toEqual(["Title is required"]);
	});

	it("falls back to the line total when no estimated total was typed", async () => {
		// WHAT WOULD MAKE THIS FAIL: dropping the `|| itemTotal.value` fallback. A
		// deal whose value is 0 sorts to the bottom of every lane on the CRM board
		// and drops out of the pipeline figure, even though its lines add up.
		const items = [
			{ item_code: "Rels birikmasi [DEMO]", qty: 2, rate: 205000000, amount: 410000000 },
		];
		const { calls } = await runSave({ items, estimated_total: 0 });
		expect(calls[0].args.data.deal_value).toBe(410000000);
		expect(calls[1].args.intake.estimated_total).toBe(410000000);
	});

	it("never disables Save because the item list is empty", async () => {
		// WHAT WOULD MAKE THIS FAIL: widening the footer button's guard from
		// `saving` to anything about items. A greyed-out Save with no stated reason
		// is the defect prompt 01 set out to remove, and S7 says an itemless tender
		// is savable.
		const at = src.indexOf('t("Save Tender")');
		expect(at, "the Save action is gone").toBeGreaterThan(-1);
		const guard = src.slice(0, at).lastIndexOf(':disabled="');
		const expression = src.slice(guard + ':disabled="'.length, src.indexOf('"', guard + 12));
		// A template auto-unwraps refs, so the render scope holds plain values.
		expect(evalInScope(expression, { saving: false, form: { items: [] } })).toBe(false);
		expect(evalInScope(expression, { saving: true, form: { items: [] } })).toBe(true);
	});
});
