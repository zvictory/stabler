import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/purchasing/PurchaseInvoiceForm.vue"), "utf8");

/**
 * UAT 2026-09-05, step 18b (RU walk): an untouched "New purchase invoice" already
 * warned "You have unsaved changes" on navigating away with nothing typed.
 *
 * `useDirtyGuard` (composables/useDirtyGuard.js) takes its dirty snapshot the
 * instant it is set up — synchronously, before `onMounted` even runs — and
 * nothing re-baselines it for a CREATE form until a successful save. (Until
 * 53462cb that snapshot was `""`, which flagged every CREATE form dirty on its
 * own; the composable now seeds it from the blank form itself, covered by
 * useDirtyGuardBaseline.spec.js. This spec is about what that fix cannot
 * reach.) `defaultOverheadDeal()` (PurchaseInvoiceForm.vue:432-449) writes the
 * GENEL GİDER default into `form.tender`/`tender_label` from `onMounted`,
 * asynchronously, well after that baseline was taken — so the default's own
 * write reads as a user edit forever after.
 *
 * `applyCreateDefaults` re-baselines once the default has landed, but only when
 * nothing else moved during that same network round trip: a real edit typed
 * while the lookup was in flight must stay dirty, or the reset would silently
 * launder it away.
 *
 * Executed against the real function body (extracted + re-run with fake
 * `form`/`defaultOverheadDeal`/`reset`), not grepped — a `reset` call that
 * fires unconditionally, or one wired to the wrong condition, both read fine
 * by eye.
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
	let at = src.indexOf(`async function ${name}(`);
	if (at === -1) at = src.indexOf(`function ${name}(`);
	expect(at, `${name} is gone — has it moved or been renamed?`).toBeGreaterThan(-1);
	const braceStart = src.indexOf("{", at);
	return src.slice(at, braceStart) + braceMatched(braceStart);
}

// applyCreateDefaults closes over `form`, `defaultOverheadDeal` and `reset`;
// hand it fakes of each. It takes no arguments itself (same call shape as
// production: `await applyCreateDefaults();`).
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

function buildApplyCreateDefaults() {
	return new AsyncFunction(
		"form",
		"defaultOverheadDeal",
		"reset",
		`${extractFunction("applyCreateDefaults")}\nreturn applyCreateDefaults();`
	);
}

describe("PurchaseInvoiceForm.applyCreateDefaults re-baselines the dirty guard after the async GENEL GİDER default", () => {
	it("resets once the default lands and nothing else changed — the untouched-new-bill case (UAT 18b)", async () => {
		const form = { value: { supplier: "", remarks: "", tender: "", tender_label: "" } };
		const resets = [];
		const reset = (snapshot) => resets.push(snapshot);
		async function defaultOverheadDeal() {
			form.value.tender = "CRM-DEAL-0001";
			form.value.tender_label = "GENEL GİDER";
		}

		await buildApplyCreateDefaults()(form, defaultOverheadDeal, reset);

		expect(resets).toHaveLength(1);
		expect(resets[0]).toMatchObject({ tender: "CRM-DEAL-0001", tender_label: "GENEL GİDER" });
	});

	it("does not reset when the user edits something else while the default is in flight", async () => {
		const form = { value: { supplier: "", remarks: "", tender: "", tender_label: "" } };
		const resets = [];
		const reset = (snapshot) => resets.push(snapshot);
		// Simulates the user typing a supplier name during defaultOverheadDeal's
		// network round trip — a real edit the reset must not swallow.
		async function defaultOverheadDeal() {
			form.value.supplier = "SUP-typed-by-user";
			form.value.tender = "CRM-DEAL-0001";
			form.value.tender_label = "GENEL GİDER";
		}

		await buildApplyCreateDefaults()(form, defaultOverheadDeal, reset);

		expect(resets).toHaveLength(0);
	});

	it("still resets when the default finds no overhead deal to apply (form stays blank)", async () => {
		const form = { value: { supplier: "", remarks: "", tender: "", tender_label: "" } };
		const resets = [];
		const reset = (snapshot) => resets.push(snapshot);
		async function defaultOverheadDeal() {
			// mirrors defaultOverheadDeal's early-return branches: no company,
			// tender module off, or no overhead deal found — form untouched.
		}

		await buildApplyCreateDefaults()(form, defaultOverheadDeal, reset);

		expect(resets).toHaveLength(1);
	});
});

// handleCompanySwitch closes over `isCreate`, `form`, `isDirty`, `overheadDeal`,
// `clearTender`, `applyCreateDefaults` and `defaultOverheadDeal`; hand it fakes
// of each, in that order.
function buildHandleCompanySwitch() {
	return new AsyncFunction(
		"isCreate",
		"form",
		"isDirty",
		"overheadDeal",
		"clearTender",
		"applyCreateDefaults",
		"defaultOverheadDeal",
		`${extractFunction("handleCompanySwitch")}\nreturn handleCompanySwitch();`
	);
}

/**
 * The same race one interaction later: the ADR-609 `watch(activeCompany, ...)`
 * clears the tender on a CREATE form and fetches the new company's GENEL GİDER
 * — one more default write after the dirty baseline, so an untouched new bill
 * went dirty again on the switch alone.
 *
 * The re-baseline is gated on whether the form was clean BEFORE the switch.
 * Re-using applyCreateDefaults unconditionally would fold a supplier the user
 * had already typed into the new baseline and silently launder that edit away.
 */
describe("PurchaseInvoiceForm.handleCompanySwitch re-baselines only a form that was clean before the switch", () => {
	function fakes({ dirty }) {
		const form = {
			value: { supplier: "", tender: "CRM-DEAL-A", tender_label: "GENEL GİDER A" },
		};
		const calls = [];
		return {
			form,
			calls,
			isCreate: { value: true },
			isDirty: { value: dirty },
			overheadDeal: { value: { name: "CRM-DEAL-A" } },
			clearTender: () => {
				calls.push("clearTender");
				form.value.tender = "";
				form.value.tender_label = "";
			},
			applyCreateDefaults: async () => calls.push("applyCreateDefaults"),
			defaultOverheadDeal: async () => calls.push("defaultOverheadDeal"),
		};
	}

	function run(f) {
		return buildHandleCompanySwitch()(
			f.isCreate,
			f.form,
			f.isDirty,
			f.overheadDeal,
			f.clearTender,
			f.applyCreateDefaults,
			f.defaultOverheadDeal
		);
	}

	it("untouched form: drops the old company's bucket and re-baselines through applyCreateDefaults", async () => {
		const f = fakes({ dirty: false });
		await run(f);
		expect(f.calls).toEqual(["clearTender", "applyCreateDefaults"]);
		expect(f.overheadDeal.value).toBeNull();
	});

	it("form the user already edited: applies the new default but never re-baselines — the edit must stay dirty", async () => {
		const f = fakes({ dirty: true });
		await run(f);
		expect(f.calls).toEqual(["clearTender", "defaultOverheadDeal"]);
	});

	it("decides from isDirty as it stood BEFORE clearTender — the clear is a write the guard flags, not a user edit", async () => {
		const f = fakes({ dirty: false });
		// Mirrors useDirtyGuard's deep watcher: the moment clearTender() writes,
		// the form differs from its baseline and isDirty reads true.
		let cleared = false;
		const clearTender = f.clearTender;
		f.clearTender = () => {
			cleared = true;
			clearTender();
		};
		f.isDirty = {
			get value() {
				return cleared;
			},
		};
		await run(f);
		expect(f.calls).toEqual(["clearTender", "applyCreateDefaults"]);
	});

	it("saved bill (not a CREATE form): touches nothing — its tender is what the ledger already says", async () => {
		const f = fakes({ dirty: false });
		f.isCreate.value = false;
		await run(f);
		expect(f.calls).toEqual([]);
		expect(f.form.value.tender).toBe("CRM-DEAL-A");
	});
});
