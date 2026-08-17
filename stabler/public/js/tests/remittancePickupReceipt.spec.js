import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const receiptPath = resolve(here, "../pages/remittance/PickupCodeReceipt.vue");
const homePath = resolve(here, "../pages/remittance/RemittanceHome.vue");
const src = readFileSync(receiptPath, "utf8");
const homeSrc = readFileSync(homePath, "utf8");

/**
 * The pickup code exists in exactly one place for exactly one moment.
 *
 * The server hands the plaintext back on the registering call alone and every
 * read path is guarded by `assert_no_pickup_code`, so this component holds the
 * only copy. Unmounting it destroys that copy — after the cash has already been
 * taken — and the only remaining exit is a refund.
 *
 * The acknowledgement checkbox used to gate this card's own button and nothing
 * else, while the module tab strip is rendered by RemittanceHome OUTSIDE
 * `<router-view>`. One click on Operations, Payout or any sidebar link took the
 * code with it. These tests exist so that never silently comes back.
 *
 * @vue/test-utils is not a devDependency of this repo (same constraint as
 * installmentOperations.spec.js and vehicleFinanceAgreements.spec.js), so the
 * component is not mounted. Instead the decision functions are executed straight
 * out of the shipped SFC — a `toContain` assertion would pass just as happily
 * for a guard wired backwards, which is the failure mode that matters here.
 */
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

function extractFunction(name, args, deps, { async: isAsync = false } = {}) {
	const marker = `function ${name}(`;
	const start = src.indexOf(marker);
	expect(start, `${name} not found in PickupCodeReceipt.vue`).toBeGreaterThan(-1);
	const bodyStart = src.indexOf("{", start) + 1;
	const end = src.indexOf("\n}", bodyStart);
	expect(end, `${name} has no closing brace at column 0`).toBeGreaterThan(bodyStart);
	const body = src.slice(bodyStart, end);
	const Ctor = isAsync ? AsyncFunction : Function;
	const fn = new Ctor(...args, ...Object.keys(deps), body); /* eslint-disable-line no-new-func */
	return (...callArgs) => fn(...callArgs, ...Object.values(deps));
}

const t = (s) => s;

function mayLeaveWith({ atRisk, answer }) {
	const confirm = vi.fn().mockResolvedValue(answer);
	const run = extractFunction(
		"mayLeave",
		[],
		{ codeAtRisk: { value: atRisk }, confirm, t },
		{ async: true }
	);
	return { run, confirm };
}

describe("leaving the receipt while the code is still on screen", () => {
	it("does not interrupt when there is no code to lose", async () => {
		// A replay carries no code at all (`register_remittance` answers a reused
		// client_request_id with pickup_code: null). Prompting there would ask the
		// cashier to protect something that does not exist.
		const { run, confirm } = mayLeaveWith({ atRisk: false, answer: false });
		await expect(run()).resolves.toBe(true);
		expect(confirm).not.toHaveBeenCalled();
	});

	it("keeps the cashier on the receipt when they choose to stay", async () => {
		const { run } = mayLeaveWith({ atRisk: true, answer: false });
		await expect(run()).resolves.toBe(false);
	});

	it("lets them leave when they choose to, so nobody is trapped at the counter", async () => {
		// Deliberately an ASK, not a refusal. A hard block would strand a cashier
		// whose customer has already walked away, and the only escape it would
		// leave is ticking a box that says they handed the code over.
		const { run } = mayLeaveWith({ atRisk: true, answer: true });
		await expect(run()).resolves.toBe(true);
	});

	it("asks in a dialog that cannot be waved away by a stray click", async () => {
		// dismissable:false is what separates this from an ordinary confirm —
		// ConfirmHost.vue:78 resolves false on a backdrop click otherwise, and a
		// cashier reaching for the tab strip would dismiss it by accident.
		const { run, confirm } = mayLeaveWith({ atRisk: true, answer: true });
		await run();
		const opts = confirm.mock.calls[0][0];
		expect(opts.dismissable).toBe(false);
		expect(opts.danger).toBe(true);
	});

	it("says what is lost, not that something is unsaved", async () => {
		// The cashier has to be able to tell this apart from a discardable draft:
		// the money is already taken and a refund is the only way back.
		const { run, confirm } = mayLeaveWith({ atRisk: true, answer: true });
		await run();
		const { body } = confirm.mock.calls[0][0];
		expect(body).toMatch(/shown once/i);
		expect(body).toMatch(/refunded/i);
	});
});

describe("reload and tab-close, which the router never sees", () => {
	function unloadWith(atRisk) {
		const run = extractFunction("handleBeforeUnload", ["event"], {
			codeAtRisk: { value: atRisk },
		});
		const event = { preventDefault: vi.fn(), returnValue: undefined };
		run(event);
		return event;
	}

	it("stops a reload while the code is unacknowledged", () => {
		const event = unloadWith(true);
		expect(event.preventDefault).toHaveBeenCalled();
		expect(event.returnValue).toBe("");
	});

	it("stays out of the way once there is nothing to lose", () => {
		// Otherwise every cashier gets a browser prompt on every reload and learns
		// to click through it — including the one time it mattered.
		const event = unloadWith(false);
		expect(event.preventDefault).not.toHaveBeenCalled();
	});
});

describe("the guards are actually wired to the component", () => {
	// These three are structural. They cannot be executed without mounting, and
	// each one is a way the tested logic above could ship switched off.

	it("registers the route guard, so tab and sidebar clicks reach mayLeave", () => {
		// Read the guard's OWN body, not the whole file. Searching the file for
		// "mayLeave()" matches its `async function mayLeave()` declaration, so a
		// guard rewritten to a bare `next()` — every navigation allowed, no prompt,
		// the exact bug this bead fixes — sailed through that check.
		const start = src.indexOf("onBeforeRouteLeave(");
		expect(start, "onBeforeRouteLeave is not registered").toBeGreaterThan(-1);
		const end = src.indexOf("\n});", start);
		expect(end, "the guard has no closing '});'").toBeGreaterThan(start);
		const guardBody = src.slice(start, end);
		expect(guardBody).toMatch(/mayLeave\(/);
		expect(guardBody).toMatch(/next\(/);
	});

	it("registers and removes the beforeunload listener", () => {
		// Left attached after unmount it would fire for every later screen, so the
		// removal is part of the behaviour, not tidiness.
		expect(src).toMatch(/addEventListener\("beforeunload", handleBeforeUnload\)/);
		expect(src).toMatch(/removeEventListener\("beforeunload", handleBeforeUnload\)/);
	});

	it("is reached by the company switch, which navigates rather than re-rendering", () => {
		// RemittanceHome answers an engine change with router.replace. That is a
		// navigation, so the route guard covers it; if this ever becomes a plain
		// re-render the code would be destroyed with no prompt at all.
		expect(homeSrc).toMatch(/router\.replace\(/);
	});
});
