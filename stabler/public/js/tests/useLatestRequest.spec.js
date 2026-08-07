import { describe, expect, it } from "vitest";

import { useLatestRequest } from "../composables/useLatestRequest.js";

// loadExposure (Suppliers.vue) writes a shared ref after an `await` with no
// check that the supplier it was called for is still selected. Click A, switch
// to B before A resolves, and A's slow response can land after B's and paint
// A's numbers under B's name. These tests mirror that shape with a plain
// variable in place of the ref -- no DOM, no component mount (see
// vitest.config.mjs: environment "node", no @vue/test-utils in this repo).

function deferred() {
	let resolve;
	const promise = new Promise((res) => {
		resolve = res;
	});
	return { promise, resolve };
}

describe("useLatestRequest", () => {
	it("drops a stale response that resolves after a newer request", async () => {
		const req = useLatestRequest();
		let panel = null;

		const a = deferred();
		const isCurrentA = req.take();
		const loadA = a.promise.then((value) => {
			if (isCurrentA()) panel = value;
		});

		const b = deferred();
		const isCurrentB = req.take();
		const loadB = b.promise.then((value) => {
			if (isCurrentB()) panel = value;
		});

		// B was requested after A but its response lands first.
		b.resolve("B");
		await loadB;
		expect(panel).toBe("B");

		// A's late response must not overwrite B's figures.
		a.resolve("A");
		await loadA;
		expect(panel).toBe("B");
	});

	it("invalidate() makes an in-flight ticket stale (deselect / company switch)", async () => {
		const req = useLatestRequest();
		let panel = "unchanged";

		const a = deferred();
		const isCurrentA = req.take();
		const loadA = a.promise.then((value) => {
			if (isCurrentA()) panel = value;
		});

		req.invalidate(); // e.g. the user deselected the supplier

		a.resolve("A");
		await loadA;
		expect(panel).toBe("unchanged");
	});

	it("a lone request is still current when it resolves", async () => {
		const req = useLatestRequest();
		let panel = null;

		const a = deferred();
		const isCurrentA = req.take();
		const loadA = a.promise.then((value) => {
			if (isCurrentA()) panel = value;
		});

		a.resolve("A");
		await loadA;
		expect(panel).toBe("A");
	});

	it("resolving in request order still ends on the newest ticket", async () => {
		const req = useLatestRequest();
		let panel = null;

		const a = deferred();
		const isCurrentA = req.take();
		const loadA = a.promise.then((value) => {
			if (isCurrentA()) panel = value;
		});

		a.resolve("A");
		await loadA;
		expect(panel).toBe("A");

		const b = deferred();
		const isCurrentB = req.take();
		const loadB = b.promise.then((value) => {
			if (isCurrentB()) panel = value;
		});

		b.resolve("B");
		await loadB;
		expect(panel).toBe("B");
	});
});
