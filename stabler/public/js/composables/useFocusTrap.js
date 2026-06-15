import { watch, nextTick, onBeforeUnmount } from "vue";

// Keep keyboard focus inside an open overlay (modal/drawer). While `isOpen` is
// truthy, Tab/Shift+Tab cycle within `containerRef`, and if focus ever escapes
// (e.g. a child input unmounts and focus falls to <body>), the next Tab pulls it
// back in. Teleported menus (Typeahead/Select options) live outside the
// container but are not tab-stops, so they're unaffected.
const FOCUSABLE = [
	"a[href]",
	"button:not([disabled])",
	"input:not([disabled])",
	"select:not([disabled])",
	"textarea:not([disabled])",
	'[tabindex]:not([tabindex="-1"])',
].join(",");

export function useFocusTrap(containerRef, isOpen, opts = {}) {
	function visible(el) {
		return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
	}
	function focusables() {
		const c = containerRef.value;
		if (!c) return [];
		return Array.from(c.querySelectorAll(FOCUSABLE)).filter(visible);
	}

	function onKeydown(e) {
		if (e.key !== "Tab") return;
		const c = containerRef.value;
		if (!c) return;
		const els = focusables();
		if (!els.length) return;
		const first = els[0];
		const last = els[els.length - 1];
		const active = document.activeElement;
		if (!c.contains(active)) {
			// focus escaped (unmounted input → body) — bring it back
			e.preventDefault();
			first.focus();
			return;
		}
		if (e.shiftKey && active === first) {
			e.preventDefault();
			last.focus();
		} else if (!e.shiftKey && active === last) {
			e.preventDefault();
			first.focus();
		}
	}

	watch(
		() => (typeof isOpen === "function" ? isOpen() : isOpen.value),
		async (open) => {
			if (open) {
				document.addEventListener("keydown", onKeydown, true);
				await nextTick();
				const els = focusables();
				(opts.initialFocus?.() || els[0])?.focus();
			} else {
				document.removeEventListener("keydown", onKeydown, true);
			}
		},
		{ immediate: true },
	);

	onBeforeUnmount(() => document.removeEventListener("keydown", onKeydown, true));
}
