import { ref, watch, onBeforeUnmount } from "vue";
import { onBeforeRouteLeave } from "vue-router";
import { useConfirm } from "./useConfirm.js";
import { t } from "./i18n.js";

export function useDirtyGuard(modelRef, getPristineSnapshot) {
	const pristineString = ref("");
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
