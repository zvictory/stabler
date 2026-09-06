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
 * (blankLine() now finds the warehouse), writes set_warehouse and, on a deep
 * link, the route prefills (?new_for / ?customer through pickCustomer(),
 * ?crm_deal, ?agreement) -- default writes after the baseline, read as a user
 * edit forever after. Same fix as PurchaseInvoiceForm's applyCreateDefaults():
 * re-baseline once the defaults have been applied, and -- because the customer
 * lookup is a network round trip the user can type through -- only when
 * nothing outside the prefilled fields moved meanwhile.
 *
 * Executed against the real function bodies (extracted + re-run with fakes),
 * not grepped. The fake reset() snapshots to JSON the way the real one does
 * (useDirtyGuard.js:29), so a reset that fires BEFORE a default is written
 * reads as exactly the wrong baseline it would be.
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

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const TAYYOR = "Tayyor Mahsulot - M";

// What each form's pickCustomer() writes on a deep link -- Modern also carries
// the customer's outstanding balance.
const CUSTOMER_PREFILL = {
	customer: "CUST-0001",
	customer_name: "Acme",
	currency: "USD",
	price_list: "Standard Selling",
};
const MODERN_CUSTOMER_PREFILL = {
	...CUSTOMER_PREFILL,
	customer_outstanding: 1500,
	customer_outstanding_currency: "USD",
};

describe.each([
	["Classic", "SalesOrderFormClassic.vue", CUSTOMER_PREFILL],
	["Modern", "SalesOrderFormModern.vue", MODERN_CUSTOMER_PREFILL],
])(
	"SalesOrderForm%s.applyCreateDefaults re-baselines the dirty guard after the create defaults",
	(_label, file, customerPrefill) => {
		const src = readFileSync(resolve(here, `../pages/sales/${file}`), "utf8");

		// applyCreateDefaults closes over `form`, `blankForm`, `defaultWarehouseName`,
		// `applyRoutePrefills` and `reset`; hand it fakes of each, in that order.
		async function run({ defaultWarehouse, prefill = async () => {} }) {
			// The construction-time blank: warehouses not loaded yet.
			const form = { value: { set_warehouse: "", remarks: "", items: [{ warehouse: "" }] } };
			// The mount-time blank: blankLine() now finds the default warehouse.
			const blankForm = () => ({
				set_warehouse: "",
				remarks: "",
				items: [{ warehouse: defaultWarehouse }],
			});
			const resets = [];
			const reset = (snapshot) => resets.push(JSON.parse(JSON.stringify(snapshot)));
			await new AsyncFunction(
				"form",
				"blankForm",
				"defaultWarehouseName",
				"applyRoutePrefills",
				"reset",
				`${extractFunction(src, "applyCreateDefaults")}\nreturn applyCreateDefaults();`
			)(
				form,
				blankForm,
				() => defaultWarehouse,
				() => prefill(form),
				reset
			);
			return { form, resets };
		}

		it("plain new form: writes the Tayyor Mahsulot default and re-baselines to exactly that form", async () => {
			const { form, resets } = await run({ defaultWarehouse: TAYYOR });
			expect(form.value.set_warehouse).toBe(TAYYOR);
			expect(resets).toEqual([
				{ set_warehouse: TAYYOR, remarks: "", items: [{ warehouse: TAYYOR }] },
			]);
		});

		it("still re-baselines when the company has no such warehouse (the blank form is the baseline either way)", async () => {
			const { resets } = await run({ defaultWarehouse: "" });
			expect(resets).toEqual([{ set_warehouse: "", remarks: "", items: [{ warehouse: "" }] }]);
		});

		it("deep link: the customer, deal and agreement prefills are part of the baseline, not edits", async () => {
			const { resets } = await run({
				defaultWarehouse: TAYYOR,
				prefill: async (form) => {
					Object.assign(form.value, customerPrefill, {
						crm_deal: "CRM-DEAL-7",
						agreement: "AGR-3",
					});
				},
			});
			expect(resets).toEqual([
				{
					set_warehouse: TAYYOR,
					remarks: "",
					items: [{ warehouse: TAYYOR }],
					...customerPrefill,
					crm_deal: "CRM-DEAL-7",
					agreement: "AGR-3",
				},
			]);
		});

		it("deep link: a remark typed while the customer lookup was in flight keeps the form dirty", async () => {
			const { resets } = await run({
				defaultWarehouse: TAYYOR,
				prefill: async (form) => {
					Object.assign(form.value, customerPrefill);
					// The user typing during pickCustomer()'s network round trip -- a
					// real edit the re-baseline must not swallow.
					form.value.remarks = "call before delivery";
				},
			});
			expect(resets).toEqual([]);
		});

		// applyRoutePrefills closes over `route`, `form` and `prefillNewForCustomer`.
		async function runPrefills(query) {
			const form = { value: { crm_deal: "", agreement: "" } };
			const lookedUp = [];
			await new AsyncFunction(
				"route",
				"form",
				"prefillNewForCustomer",
				`${extractFunction(src, "applyRoutePrefills")}\nreturn applyRoutePrefills();`
			)({ query }, form, async (name) => lookedUp.push(name));
			return { form, lookedUp };
		}

		it("applyRoutePrefills: ?new_for looks the customer up and ?crm_deal / ?agreement land on the form", async () => {
			const { form, lookedUp } = await runPrefills({
				new_for: "CUST-0001",
				crm_deal: "CRM-DEAL-7",
				agreement: "AGR-3",
			});
			expect(lookedUp).toEqual(["CUST-0001"]);
			expect(form.value).toEqual({ crm_deal: "CRM-DEAL-7", agreement: "AGR-3" });
		});

		it("applyRoutePrefills: ?customer is the older alias of ?new_for, and no query touches nothing", async () => {
			expect((await runPrefills({ customer: "CUST-0002" })).lookedUp).toEqual(["CUST-0002"]);
			const { form, lookedUp } = await runPrefills({});
			expect(lookedUp).toEqual([]);
			expect(form.value).toEqual({ crm_deal: "", agreement: "" });
		});

		it("the mount hook's create branch goes through applyCreateDefaults, with no default or prefill left in the hook", () => {
			// Defining the helpers is not the behaviour -- mounting a blank form has
			// to CALL applyCreateDefaults, and every default write has to live inside
			// it, ahead of the reset: a bare set_warehouse write or a route prefill
			// left in the hook would land after the baseline again.
			const at = src.indexOf("onMounted(");
			expect(at, "the mount hook is gone").toBeGreaterThan(-1);
			const mounted = src.slice(at, src.indexOf("\n});", at));
			expect(mounted).toMatch(/applyCreateDefaults\(\)/);
			expect(mounted).not.toMatch(/set_warehouse = defaultWarehouseName\(\)/);
			expect(mounted).not.toMatch(/prefillNewForCustomer\(|route\.query/);
		});
	}
);
