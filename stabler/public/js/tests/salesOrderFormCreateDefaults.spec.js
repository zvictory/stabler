import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));

/**
 * 53462cb follow-up, measured 2026-09-05: open "New sales order" on a company
 * that has a "Tayyor Mahsulot" warehouse, touch nothing, navigate away -- the
 * "Discard unsaved changes?" modal fires anyway, on both the Classic and the
 * Modern form.
 *
 * useDirtyGuard's baseline is the blank form as useDocumentForm constructed
 * it, BEFORE loadWarehouses() resolved: `set_warehouse: ""` and a first line
 * with `warehouse: ""`. The mount hook's create branch then rebuilds the form
 * (blankLine() now finds the warehouse) and writes set_warehouse -- two default
 * writes after the baseline, read as a user edit forever after. Same fix as
 * PurchaseInvoiceForm's applyCreateDefaults(): re-baseline once the default
 * has been applied.
 *
 * Executed against the real function body (extracted + re-run with fake
 * `form`/`blankForm`/`defaultWarehouseName`/`reset`), not grepped. The fake
 * reset() snapshots to JSON the way the real one does (useDirtyGuard.js:29),
 * so a reset that fires BEFORE the warehouse default is written reads as
 * exactly the wrong baseline it would be.
 */
function braceMatched(src, from) {
	let depth = 0;
	for (let i = from; i < src.length; i++) {
		if (src[i] === "{") depth++;
		else if (src[i] === "}" && --depth === 0) return src.slice(from, i + 1);
	}
	throw new Error("unterminated block");
}

function extractFunction(src, name) {
	let at = src.indexOf(`async function ${name}(`);
	if (at === -1) at = src.indexOf(`function ${name}(`);
	expect(at, `${name} is gone — has it moved or been renamed?`).toBeGreaterThan(-1);
	const braceStart = src.indexOf("{", at);
	return src.slice(at, braceStart) + braceMatched(src, braceStart);
}

const TAYYOR = "Tayyor Mahsulot - M";

describe.each([
	["Classic", "SalesOrderFormClassic.vue"],
	["Modern", "SalesOrderFormModern.vue"],
])(
	"SalesOrderForm%s.applyCreateDefaults re-baselines the dirty guard after the warehouse default",
	(_label, file) => {
		const src = readFileSync(resolve(here, `../pages/sales/${file}`), "utf8");

		// applyCreateDefaults closes over `form`, `blankForm`, `defaultWarehouseName`
		// and `reset`; hand it fakes of each, in that order.
		function run({ defaultWarehouse }) {
			// The construction-time blank: warehouses not loaded yet.
			const form = { value: { set_warehouse: "", items: [{ warehouse: "" }] } };
			// The mount-time blank: blankLine() now finds the default warehouse.
			const blankForm = () => ({ set_warehouse: "", items: [{ warehouse: defaultWarehouse }] });
			const resets = [];
			const reset = (snapshot) => resets.push(JSON.parse(JSON.stringify(snapshot)));
			new Function(
				"form",
				"blankForm",
				"defaultWarehouseName",
				"reset",
				`${extractFunction(src, "applyCreateDefaults")}\nreturn applyCreateDefaults();`
			)(form, blankForm, () => defaultWarehouse, reset);
			return { form, resets };
		}

		it("writes the Tayyor Mahsulot default and re-baselines to exactly that form", () => {
			const { form, resets } = run({ defaultWarehouse: TAYYOR });
			expect(form.value.set_warehouse).toBe(TAYYOR);
			expect(resets).toEqual([{ set_warehouse: TAYYOR, items: [{ warehouse: TAYYOR }] }]);
		});

		it("still re-baselines when the company has no such warehouse (the blank form is the baseline either way)", () => {
			const { resets } = run({ defaultWarehouse: "" });
			expect(resets).toEqual([{ set_warehouse: "", items: [{ warehouse: "" }] }]);
		});

		it("the mount hook's create branch goes through applyCreateDefaults, not through bare writes", () => {
			// Defining the helper is not the behaviour -- mounting a blank form has
			// to CALL it, and the warehouse write has to live inside it, ahead of the
			// reset: a bare `set_warehouse = defaultWarehouseName()` left in the hook
			// would land after the baseline again.
			const at = src.indexOf("onMounted(");
			expect(at, "the mount hook is gone").toBeGreaterThan(-1);
			const mounted = src.slice(at, src.indexOf("\n});", at));
			expect(mounted).toMatch(/applyCreateDefaults\(\)/);
			expect(mounted).not.toMatch(/set_warehouse = defaultWarehouseName\(\)/);
		});
	}
);
