import { describe, expect, it, vi } from "vitest";
import { nextTick, ref } from "vue";

vi.mock("vue-router", () => ({ onBeforeRouteLeave: () => {} }));
vi.mock("../composables/useConfirm.js", () => ({
	useConfirm: () => ({ confirm: () => Promise.resolve(true) }),
}));
vi.mock("../composables/i18n.js", () => ({ t: (s) => s }));

const { useDirtyGuard } = await import("../composables/useDirtyGuard.js");

// useDirtyGuard also wires a real `window.addEventListener("beforeunload", ...)`
// (composables/useDirtyGuard.js:65) for the tab-close guard. tests/setup.js's
// shared `window` fixture is a plain object carrying only `__STABLER__` (for
// i18n.js) and has no DOM APIs, so invoking the composable for real needs these
// two no-ops. Added here rather than in the shared fixture: no other spec
// constructs this composable, so the concern is this file's alone.
if (typeof window.addEventListener !== "function") window.addEventListener = () => {};
if (typeof window.removeEventListener !== "function") window.removeEventListener = () => {};

/**
 * Bug measured in the browser 2026-09-05: open any "New ..." document form
 * (e.g. #/purchasing/orders/new), touch nothing, navigate away -- the
 * "Discard unsaved changes?" modal fires anyway.
 *
 * Root cause: the pristine baseline started as `ref("")` (useDirtyGuard.js:19)
 * while the deep watcher runs `immediate: true` (:30-36), so at construction
 * `isDirty = JSON.stringify(model) !== ""` is true for EVERY form -- and
 * useDocumentForm never calls reset() for a CREATE document until save()
 * succeeds (useDocumentForm.js:142), so nothing ever supplies a real baseline
 * before that first save.
 *
 * These construct the real composable directly (no component, no
 * useDocumentForm) against a model shaped like a blank "New ..." form: a
 * couple of scalar fields plus an empty `items` array, the same shape every
 * `blankModel()` under stabler/public/js/pages produces.
 */
function blankModel() {
	return { posting_date: "2026-09-05", items: [] };
}

describe("useDirtyGuard - CREATE-form baseline", () => {
	it("starts clean right after construction, before the user touches anything", () => {
		// WHAT WOULD MAKE THIS FAIL FOR THE RIGHT REASON: reverting the pristine
		// baseline to `ref("")` -- JSON.stringify(blankModel()) !== "" is true,
		// so isDirty is true before any mutation, which is exactly the bug.
		const model = ref(blankModel());
		const { isDirty } = useDirtyGuard(model, blankModel);
		expect(isDirty.value).toBe(false);
	});

	it("flips dirty once the user actually changes the model", async () => {
		const model = ref(blankModel());
		const { isDirty } = useDirtyGuard(model, blankModel);

		model.value.items.push({ item_code: "ABC-1", qty: 1 });
		await nextTick();

		expect(isDirty.value).toBe(true);
	});

	it("reset() clears the dirty flag", async () => {
		const model = ref(blankModel());
		const { isDirty, reset } = useDirtyGuard(model, blankModel);

		model.value.items.push({ item_code: "ABC-1", qty: 1 });
		await nextTick();
		expect(isDirty.value).toBe(true);

		reset();
		expect(isDirty.value).toBe(false);
	});

	it("stays clean when the model is replaced by an equal-content object (the onMounted form.value = blankForm() case)", async () => {
		// Several pages call `form.value = blankForm()` a second time in
		// onMounted, AFTER useDocumentForm already constructed `model` from the
		// first call (e.g. QuotationForm.vue:162, PurchaseOrderForm.vue:345).
		// The guard must not treat that reassignment -- new object, identical
		// content -- as a user edit.
		const model = ref(blankModel());
		const { isDirty } = useDirtyGuard(model, blankModel);

		model.value = { ...blankModel() };
		await nextTick();

		expect(isDirty.value).toBe(false);
	});
});
