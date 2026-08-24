import { ref } from "vue";

const jobsDown = ref(false);
let state = { downStreak: 0, warn: false };
let started = false;

const POLL_MS = 60 * 1000;
const WARN_AFTER = 2; // consecutive down samples before the banner appears
const STREAK_CAP = 10;

/**
 * Fold one poll result into the banner's state.
 *
 * Two down samples, not one: `bench restart` takes the workers out for at least
 * supervisor's `startsecs` (20 s on prod), so a single poll landing in that
 * window sees a genuinely empty worker set on an ordinary deploy. Warning there
 * would fire the banner on every release and teach everyone to ignore it.
 *
 * Recovery is immediate, though — a banner that outlives its outage is worse
 * than no banner at all.
 */
export function nextHealthState(prev, ok) {
	if (ok) return { downStreak: 0, warn: false };
	const downStreak = Math.min(prev.downStreak + 1, STREAK_CAP);
	return { downStreak, warn: downStreak >= WARN_AFTER };
}

async function checkOnce() {
	let ok = true;
	try {
		// Raw fetch, not `api/client.js::call()`, for the same reason
		// version-check.js and useTelemetry.js use raw fetch: `call()` throws on
		// a bad response and dispatches `stabler:forbidden` on 403. Both are
		// right for a call the user asked for and wrong for a silent 60 s poll —
		// an expired session would bounce someone out of a half-filled form
		// because a background health check happened to fire.
		const res = await fetch("/api/method/stabler.api.health.background_jobs", {
			credentials: "same-origin",
			headers: { Accept: "application/json" },
			cache: "no-store",
		});
		// A non-OK HTTP response says nothing about the queue — the web layer
		// itself is unhappy, and the user can already see that. Only a verdict
		// the endpoint actually produced may move the banner.
		if (!res.ok) return;
		ok = Boolean((await res.json())?.message?.ok);
	} catch {
		// Offline, or the tab lost the network. Not evidence about the queue.
		return;
	}
	state = nextHealthState(state, ok);
	jobsDown.value = state.warn;
}

/** Start polling the queue's health. Idempotent — safe to call more than once. */
export function startBackgroundHealthCheck() {
	if (started) return;
	started = true;
	setTimeout(checkOnce, 15_000); // let the app settle before adding traffic
	setInterval(checkOnce, POLL_MS);
}

/** Reactive accessor consumed by BackgroundJobsBanner.vue. */
export function useBackgroundHealth() {
	return { jobsDown };
}
