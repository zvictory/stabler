import { onMounted, onBeforeUnmount } from "vue";
import { useRouter } from "vue-router";

/**
 * What Escape means, given what is layered over the page.
 *
 *   "skip"           – not ours. The user is typing, a modal is up and owns the
 *                      key, or the open drawer belongs to someone else.
 *   "page-only"      – ask the page to close its own drawer, and stop there.
 *   "page-then-back" – the general rule: let the page close its own pane, and
 *                      otherwise go back.
 *
 * The `pageOwnsDrawer` input is why this is a parameter and not a DOM query. The
 * handler below used to bail on ANY open `.offcanvas.show`, on the reasoning
 * that "those close themselves" — true of an offcanvas Bootstrap instantiated,
 * false of every one this codebase hand-rolls with `:class="{ show }"`. Nothing
 * closes those, so Escape silently became a dead key on the page that opened
 * one. Only the page knows which overlay is its own, so only the page can say.
 *
 * Exported separately from the DOM wrapper so `make test-js` can reach it:
 * vitest runs in a node environment on purpose (see vitest.config.mjs).
 */
export function escapeIntent({ typing, modalOpen, drawerOpen, pageOwnsDrawer }) {
	if (typing || modalOpen) return "skip";
	if (drawerOpen) return pageOwnsDrawer ? "page-only" : "skip";
	return "page-then-back";
}

/**
 * General app rule: pressing Escape goes back.
 *
 * Skips when the user is typing (INPUT/TEXTAREA/SELECT/contentEditable) or when a
 * Bootstrap modal is open (those close themselves). A page can pass an
 * `onEscape` callback to close its own open detail/form first — return `true` to
 * signal "handled, don't navigate". Otherwise it falls back to router.back(), or
 * `backPath` when there's no history to go back to.
 *
 * A page that renders its own offcanvas must say so with `ownsDrawer`, or Escape
 * will not reach it while that drawer is open.
 *
 * Usage:
 *   useEscapeBack(() => { if (detailOpen.value) { close(); return true; } });
 *   useEscapeBack(null, "/money");   // plain back, fallback route
 *   useEscapeBack(fn, "/money", { ownsDrawer: () => pane.value !== "empty" });
 */
export function useEscapeBack(onEscape = null, backPath = "/", { ownsDrawer = false } = {}) {
	const router = useRouter();

	function handler(e) {
		if (e.key !== "Escape" || e.defaultPrevented) return;
		const el = document.activeElement;
		const tag = el?.tagName;
		const intent = escapeIntent({
			typing: tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || !!el?.isContentEditable,
			modalOpen: !!document.querySelector(".modal.show"),
			drawerOpen: !!document.querySelector(".offcanvas.show"),
			pageOwnsDrawer: typeof ownsDrawer === "function" ? !!ownsDrawer() : !!ownsDrawer,
		});
		if (intent === "skip") return;
		// Let the page close its own open pane/form first.
		if (typeof onEscape === "function" && onEscape() === true) return;
		if (intent === "page-only") return;
		if (window.history.state?.back != null) router.back();
		else router.push(backPath);
	}

	onMounted(() => window.addEventListener("keydown", handler));
	onBeforeUnmount(() => window.removeEventListener("keydown", handler));
}
