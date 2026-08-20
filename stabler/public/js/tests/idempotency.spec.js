import { describe, expect, it } from "vitest";

import { createIntentKey } from "../composables/idempotency.js";

/**
 * The whole value of this object is WHEN the key changes, so that is what is
 * tested. A key that changed on every attempt would leave the duplicate the
 * server cannot see; a key that never changed would make the operator's second,
 * genuinely different expense look like a retry of the first and silently
 * return the wrong document.
 */
describe("createIntentKey", () => {
	const counting = () => {
		let n = 0;
		return () => `key-${++n}`;
	};

	it("hands the same key to a retry of a failed attempt", () => {
		const intent = createIntentKey(counting());

		expect(intent.begin()).toBe("key-1");
		expect(intent.begin()).toBe("key-1");
	});

	it("hands a new key to the next save once the first one landed", () => {
		const intent = createIntentKey(counting());

		intent.begin();
		intent.settle();

		expect(intent.begin()).toBe("key-2");
	});

	it("holds nothing before the first attempt and nothing after it settles", () => {
		const intent = createIntentKey(counting());

		expect(intent.peek()).toBeNull();
		intent.begin();
		expect(intent.peek()).toBe("key-1");
		intent.settle();
		expect(intent.peek()).toBeNull();
	});

	it("defaults to a generator that does not repeat itself", () => {
		const intent = createIntentKey();

		const first = intent.begin();
		intent.settle();

		expect(first).toEqual(expect.any(String));
		expect(intent.begin()).not.toBe(first);
	});
});
