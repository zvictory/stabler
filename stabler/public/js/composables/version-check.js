import { ref } from "vue";

const updateAvailable = ref(false);
let started = false;
let lastCheckAt = 0;
let _loadedHash = null;

const POLL_MS = 5 * 60 * 1000; // re-check every 5 min
const THROTTLE_MS = 60 * 1000; // skip visibility checks within 60 s of the last one
const HASH_RE = /stabler\.bundle\.([A-Za-z0-9]+)\.js/;

/** Parse the hash from the <script src="…stabler.bundle.<HASH>.js"> already in the DOM. */
function loadedHash() {
	if (_loadedHash) return _loadedHash;
	const el = document.querySelector('script[src*="stabler.bundle."]');
	const m = el?.src.match(HASH_RE);
	_loadedHash = m?.[1] ?? null;
	return _loadedHash;
}

/**
 * Fetch the SPA shell (no-store) and compare its embedded bundle hash against the
 * currently-loaded one.  Silently swallows network/parse failures — no false positives.
 */
async function checkOnce() {
	const current = loadedHash();
	if (!current) return;
	lastCheckAt = Date.now();
	try {
		// The shell URL is the same page we are on, minus hash/query.
		const shellUrl = window.location.href.split("#")[0].split("?")[0];
		const res = await fetch(shellUrl, { cache: "no-store" });
		if (!res.ok) return;
		const html = await res.text();
		const m = html.match(HASH_RE);
		const server = m?.[1] ?? null;
		if (server && server !== current) {
			updateAvailable.value = true;
		}
	} catch {
		// Network error, offline, or parse failure — try again next poll.
	}
}

/**
 * Start the background version checker.  Idempotent — safe to call multiple times.
 *
 * Runs:
 *   - Once after a 10 s startup delay (lets the app settle before adding network traffic).
 *   - On a 5-min interval while the tab is open.
 *   - On tab visibility-change (catches long-idle sessions), throttled to once per 60 s.
 *
 * Stops polling once an update is detected.
 */
export function startVersionCheck() {
	if (started) return;
	started = true;

	setTimeout(checkOnce, 10_000);

	const interval = setInterval(() => {
		if (updateAvailable.value) {
			clearInterval(interval);
			return;
		}
		checkOnce();
	}, POLL_MS);

	document.addEventListener("visibilitychange", () => {
		if (document.visibilityState !== "visible") return;
		if (updateAvailable.value) return;
		if (Date.now() - lastCheckAt < THROTTLE_MS) return;
		checkOnce();
	});
}

/** Reactive accessor consumed by UpdateBanner.vue. */
export function useAppVersion() {
	return {
		updateAvailable,
		reload: () => location.reload(),
	};
}
