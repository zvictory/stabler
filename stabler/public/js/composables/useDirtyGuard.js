/**
 * useDirtyGuard — guard page leaves when a form is dirty.
 *
 * Manual QA Checklist:
 * 1. Navigate to a create/edit form (e.g. Sales Order draft).
 * 2. Type in a field or modify lines (form state becomes dirty).
 * 3. Click sidebar link or "Back". Verify that the custom styled confirm modal opens.
 * 4. Choose "Keep Editing". Verify you stay on the page with state intact.
 * 5. Choose "Discard". Verify navigation completes.
 * 6. Try reloading the tab or closing the window while dirty. Verify the browser's native tab-close confirm prompt appears.
 * 7. Save/submit the form. Navigate away. Verify no prompts appear.
 */
import { ref, watch, onBeforeUnmount } from "vue";
import { onBeforeRouteLeave } from "vue-router";
import { useConfirm } from "./useConfirm.js";
import { t } from "./i18n.js";

export function useDirtyGuard(modelRef, getPristineSnapshot) {
	// Baseline from the model's OWN construction-time value, not "" — with the
	// deep `immediate` watcher below, "" made isDirty true for every CREATE
	// form before the user touched anything (nothing calls reset() until the
	// first save; useDocumentForm.js:142), so "Discard unsaved changes?" fired
	// on navigating straight off a blank "New ..." form. Measured 2026-09-05.
	const pristineString = ref(JSON.stringify(modelRef.value));
	const { confirm } = useConfirm();

	function reset(customSnapshot = null) {
		const snapshot = customSnapshot || getPristineSnapshot();
		pristineString.value = JSON.stringify(snapshot);
		isDirty.value = false;
	}

	const isDirty = ref(false);

	watch(
		modelRef,
		(newVal) => {
			isDirty.value = JSON.stringify(newVal) !== pristineString.value;
		},
		{ deep: true, immediate: true }
	);

	async function confirmLeave() {
		if (!isDirty.value) return true;
		const ok = await confirm({
			title: t("Discard unsaved changes?"),
			body: t("You have unsaved changes. Leaving this page will discard them."),
			danger: true,
			confirmLabel: t("Discard"),
			cancelLabel: t("Keep Editing"),
		});
		return ok;
	}

	onBeforeRouteLeave(async (to, from, next) => {
		if (await confirmLeave()) {
			next();
		} else {
			next(false);
		}
	});

	function handleBeforeUnload(e) {
		if (isDirty.value) {
			e.preventDefault();
			e.returnValue = "";
		}
	}

	window.addEventListener("beforeunload", handleBeforeUnload);

	onBeforeUnmount(() => {
		window.removeEventListener("beforeunload", handleBeforeUnload);
	});

	return {
		isDirty,
		reset,
	};
}
