import { onMounted, onBeforeUnmount } from "vue";
import { useRouter } from "vue-router";

/**
 * General app rule: pressing Escape goes back.
 *
 * Skips when the user is typing (INPUT/TEXTAREA/SELECT/contentEditable) or when a
 * Bootstrap modal/offcanvas is open (those close themselves). A page can pass an
 * `onEscape` callback to close its own open detail/form first — return `true` to
 * signal "handled, don't navigate". Otherwise it falls back to router.back(), or
 * `backPath` when there's no history to go back to.
 *
 * Usage:
 *   useEscapeBack(() => { if (detailOpen.value) { close(); return true; } });
 *   useEscapeBack(null, "/money");   // plain back, fallback route
 */
export function useEscapeBack(onEscape = null, backPath = "/") {
	const router = useRouter();

	function handler(e) {
		if (e.key !== "Escape" || e.defaultPrevented) return;
		const tag = document.activeElement?.tagName;
		if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
		if (document.activeElement?.isContentEditable) return;
		if (document.querySelector(".modal.show, .offcanvas.show")) return;
		// Let the page close its own open pane/form first.
		if (typeof onEscape === "function" && onEscape() === true) return;
		if (window.history.state?.back != null) router.back();
		else router.push(backPath);
	}

	onMounted(() => window.addEventListener("keydown", handler));
	onBeforeUnmount(() => window.removeEventListener("keydown", handler));
}
