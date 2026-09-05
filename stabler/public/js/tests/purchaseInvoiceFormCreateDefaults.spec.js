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
 * instant it is set up — a `watch(model, ..., { immediate: true })` against a
 * pristine string that starts as `""`, so it fires `true` synchronously, before
 * `onMounted` even runs. Nothing re-baselines it for a CREATE form until a
 * successful save. `defaultOverheadDeal()` (PurchaseInvoiceForm.vue:431-448)
 * writes the GENEL GİDER default into `form.tender`/`tender_label` from
 * `onMounted`, asynchronously, well after that broken baseline was taken — so
 * the default's own write reads as a user edit forever after.
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
