import { ref } from "vue";

const currentConfirm = ref(null);

export function useConfirm() {
	function confirm({ title, body, danger = false, confirmLabel = "Confirm", cancelLabel = "Cancel", dismissable = true }) {
		return new Promise((resolve) => {
			currentConfirm.value = {
				title,
				body,
				danger,
				confirmLabel,
				cancelLabel,
				dismissable,
				resolve: (val) => {
					currentConfirm.value = null;
					resolve(val);
				},
			};
		});
	}

	/**
	 * Ask for a line of text, in the app's own dialog.
	 *
	 * Built on the same state as `confirm` rather than beside it: ConfirmHost is
	 * 130 lines of focus management, Escape handling and a tab trap, and a
	 * parallel PromptHost would be a second copy of every one of them.
	 *
	 * Resolves the trimmed text, or **null** when the user backs out — cancel
	 * and "typed nothing" are different intentions, and only one of them should
	 * ever be reported to the user as a failure. `window.prompt`, which this
	 * replaces, drew the same distinction.
	 */
	function prompt({
		title,
		body = "",
		label = "",
		text = "",
		placeholder = "",
		confirmLabel = "Save",
		cancelLabel = "Cancel",
		required = true,
	}) {
		return new Promise((resolve) => {
			currentConfirm.value = {
				title,
				body,
				danger: false,
				confirmLabel,
				cancelLabel,
				dismissable: true,
				input: { label, text, placeholder, required },
				resolve: (val) => {
					currentConfirm.value = null;
					resolve(typeof val === "string" ? val.trim() : null);
				},
			};
		});
	}

	return {
		currentConfirm,
		confirm,
		prompt,
	};
}
