import { onMounted, onUnmounted } from "vue";

/**
 * Periodically re-run `refreshFn` while the component is mounted AND the tab is
 * visible. Gives tender boards a "live" feel without websockets.
 *
 * Behaviour:
 *   - Ticks every `intervalMs` (default 60 s) while the tab is visible.
 *   - PAUSES while the tab is hidden (`document.hidden`) — a backgrounded board
 *     issues zero network requests.
 *   - When the tab becomes visible again it fires once immediately (opt-out via
 *     `refreshOnReveal:false`) so the user sees fresh data the moment they return.
 *   - Never overlaps: a still-running refresh skips the next tick.
 *   - Swallows errors — an auto-refresh must never surface as an error toast; the
 *     next tick (or the page's own loader) retries.
 *   - Tears down BOTH the interval and the visibilitychange listener on unmount,
 *     so there is no timer or listener leak.
 *
 * The initial load stays the page's responsibility (its own `onMounted(load)`);
 * this composable only adds the recurring refresh.
 *
 * @param {() => (void | Promise<void>)} refreshFn - loader to re-run each tick.
 * @param {{ intervalMs?: number, refreshOnReveal?: boolean }} [opts]
 */
export function useAutoRefresh(refreshFn, opts = {}) {
	const intervalMs = opts.intervalMs ?? 60_000;
	const refreshOnReveal = opts.refreshOnReveal ?? true;

	let timer = null;
	let running = false;

	async function tick() {
		if (document.hidden) return; // paused while backgrounded
		if (running) return; // never overlap a slow refresh
		running = true;
		try {
			await refreshFn();
		} catch {
			// Auto-refresh failures are silent by design — retry next tick.
		} finally {
			running = false;
		}
	}

	function onVisibility() {
		if (document.hidden) return;
		if (refreshOnReveal) tick();
	}

	onMounted(() => {
		timer = setInterval(tick, intervalMs);
		document.addEventListener("visibilitychange", onVisibility);
	});

	onUnmounted(() => {
		if (timer) clearInterval(timer);
		timer = null;
		document.removeEventListener("visibilitychange", onVisibility);
	});
}
