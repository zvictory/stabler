import { describe, it, expect } from "vitest";

import { escapeIntent } from "../composables/useEscapeBack.js";

/**
 * What Escape is allowed to mean, given what is on screen.
 *
 * The rule this encodes was wrong in one specific way until 2026-08-20: the
 * handler bailed out on ANY open `.offcanvas.show`, on the reasoning that "those
 * close themselves". That is true of an offcanvas Bootstrap instantiated, and
 * false of every offcanvas this codebase hand-rolls with `:class="{ show }"` —
 * 40-odd of them, of which four reference a Bootstrap instance at all. Nothing
 * closes those. So on the journal entries page Escape became a dead key the
 * moment the editor moved into a drawer: the page's own handler was never
 * consulted, and the user had a full-height panel with no keyboard way out.
 *
 * The distinction is the page's to declare, because only the page knows which
 * overlay is its own — hence `pageOwnsDrawer`, and hence this function, which is
 * the whole policy with the DOM lookups lifted out so `make test-js` can reach
 * it (vitest runs in a node environment on purpose; see vitest.config.mjs).
 */
describe("escapeIntent", () => {
	const at = (over = {}) =>
		escapeIntent({ typing: false, modalOpen: false, drawerOpen: false, pageOwnsDrawer: false, ...over });

	it("consults the page and then leaves, when nothing is layered over it", () => {
		// The general app rule: Escape goes back, unless the page closes something first.
		expect(at()).toBe("page-then-back");
	});

	it("never steals the key from a field the user is typing in", () => {
		// Escape in an input means "abandon this value", not "abandon this page".
		expect(at({ typing: true })).toBe("skip");
		expect(at({ typing: true, drawerOpen: true, pageOwnsDrawer: true })).toBe("skip");
	});

	it("yields to an open modal, even over the page's own drawer", () => {
		// ConfirmHost renders `.modal fade show` and handles Escape itself, so the
		// "Discard this draft?" prompt must answer the key. Consulting the page here
		// would re-open the very prompt the user is trying to dismiss.
		expect(at({ modalOpen: true })).toBe("skip");
		expect(at({ modalOpen: true, drawerOpen: true, pageOwnsDrawer: true })).toBe("skip");
	});

	it("lets the page peel off a drawer it owns", () => {
		// THE REGRESSION. The journal drawer is hand-rolled; if the page is not
		// consulted, nothing on the key path closes it.
		expect(at({ drawerOpen: true, pageOwnsDrawer: true })).toBe("page-only");
	});

	it("does not navigate out from under a drawer it owns", () => {
		// "page-only", not "page-then-back": if the page declines to handle Escape
		// while its drawer is open, the fallback must not be to change route — that
		// leaves the route behind the drawer and the drawer still painted on top.
		expect(at({ drawerOpen: true, pageOwnsDrawer: true })).not.toBe("page-then-back");
	});

	it("still ignores a drawer the page did not open", () => {
		// A drawer some other component owns is that component's business; the old
		// blanket bail-out was right about this case and stays.
		expect(at({ drawerOpen: true })).toBe("skip");
	});
});
