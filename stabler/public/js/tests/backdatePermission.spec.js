import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

// What the fake server was asked, and what it answers. `answer` is swapped per
// test before the module under test is re-imported.
const asked = [];
let answer = () => Promise.resolve({ can_backdate: true });

vi.mock("../api/client.js", () => ({
	call: (name, args) => {
		asked.push(name);
		return answer(name, args);
	},
}));

// The answer is cached at module scope on purpose — one request per page load,
// not one per form — so each test needs its own instance of the module.
async function fresh() {
	vi.resetModules();
	asked.length = 0;
	return await import("../composables/backdate.js");
}

const settle = () => new Promise((r) => setTimeout(r, 0));

describe("backdate permission", () => {
	it("assumes the user may backdate until the server says otherwise", async () => {
		// The form renders before the answer arrives. Starting closed would
		// flash a disabled past at every user for the length of one round trip,
		// including the administrators who are allowed to use it.
		answer = () => new Promise(() => {});
		const { useCanBackdate } = await fresh();

		expect(useCanBackdate().value).toBe(true);
	});

	it("closes the past when the server refuses it", async () => {
		answer = () => Promise.resolve({ can_backdate: false });
		const { useCanBackdate } = await fresh();
		const canBackdate = useCanBackdate();

		await settle();

		expect(canBackdate.value).toBe(false);
	});

	it("leaves the past open for a user the server allows", async () => {
		answer = () => Promise.resolve({ can_backdate: true });
		const { useCanBackdate } = await fresh();
		const canBackdate = useCanBackdate();

		await settle();

		expect(canBackdate.value).toBe(true);
	});

	it("keeps backdating available when the endpoint is not installed", async () => {
		// The rule and this endpoint both live in `stable_app`, which is on
		// production and on no development bench. A site without it has no
		// backdating rule to obey; a site with it must not lose the capability
		// to a timeout. The validate hook is the source of truth either way, so
		// guessing `true` costs one honest error message, while guessing
		// `false` silently removes a permission the user really holds.
		answer = () => Promise.reject(new Error("ModuleNotFoundError: stable_app"));
		const { useCanBackdate } = await fresh();
		const canBackdate = useCanBackdate();

		await settle();

		expect(canBackdate.value).toBe(true);
	});

	it("asks the server once however many forms ask it", async () => {
		answer = () => Promise.resolve({ can_backdate: false });
		const { useCanBackdate } = await fresh();
		const first = useCanBackdate();
		const second = useCanBackdate();

		await settle();

		expect(asked).toEqual(["stable_app.api.guards.can_backdate"]);
		expect(first.value).toBe(false);
		expect(second.value).toBe(false);
	});
});

describe("earliestPostingDate", () => {
	it("leaves the calendar unbounded when backdating is allowed", async () => {
		const { earliestPostingDate } = await fresh();

		expect(earliestPostingDate(true, "2026-08-27")).toBe("");
	});

	it("floors the calendar at today when it is not", async () => {
		const { earliestPostingDate } = await fresh();

		expect(earliestPostingDate(false, "2026-08-27")).toBe("2026-08-27");
	});
});

const here = dirname(fileURLToPath(import.meta.url));
const stockEntries = readFileSync(resolve(here, "../pages/inventory/StockEntries.vue"), "utf8");

describe("the stock entry create form", () => {
	// `set_posting_time = 1` (inventory.py, 2026-08-27) is what makes this
	// matter: the operator's chosen date now survives to `validate` instead of
	// being reset to today in silence, so stable_app's guard refuses the
	// submission where it used to quietly succeed on the wrong date. An
	// unconstrained picker offers a value the server will not take.
	it("binds the posting-date picker to the permission", () => {
		const tag = stockEntries.match(/<DateInput\s+v-model="form\.posting_date"[^>]*\/>/);

		expect(tag, "the create form's posting-date input").toBeTruthy();
		expect(tag[0]).toMatch(/:min="minPostingDate"/);
	});

	it("says why the past is closed rather than just refusing it", () => {
		expect(stockEntries).toMatch(/v-if="!canBackdate"/);
		expect(stockEntries).toContain("Only an administrator can post to an earlier date.");
	});
});
