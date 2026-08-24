import { describe, expect, it } from "vitest";

import { nextHealthState } from "../composables/backgroundHealth.js";

// The banner must survive an ordinary deploy. `bench restart` takes the workers
// out for at least the 20 s of supervisor's startsecs, so any poll that lands in
// that window sees a genuinely down queue — and it is not an outage.
describe("nextHealthState", () => {
	it("does not warn on a single down sample", () => {
		const s = nextHealthState({ downStreak: 0, warn: false }, false);
		expect(s.warn).toBe(false);
		expect(s.downStreak).toBe(1);
	});

	it("warns once the queue is down twice in a row", () => {
		let s = nextHealthState({ downStreak: 0, warn: false }, false);
		s = nextHealthState(s, false);
		expect(s.warn).toBe(true);
	});

	it("clears the warning on the first healthy sample", () => {
		// Recovery must not lag: a banner that outlives the outage teaches
		// people to ignore it, which is worse than not having one.
		let s = { downStreak: 5, warn: true };
		s = nextHealthState(s, true);
		expect(s.warn).toBe(false);
		expect(s.downStreak).toBe(0);
	});

	it("keeps the streak bounded while the outage lasts", () => {
		// 43.7 h at one poll a minute is 2 622 samples; the counter exists to
		// decide "twice", not to measure the outage.
		let s = { downStreak: 0, warn: false };
		for (let i = 0; i < 5000; i++) s = nextHealthState(s, false);
		expect(s.warn).toBe(true);
		expect(s.downStreak).toBeLessThanOrEqual(10);
	});
});
