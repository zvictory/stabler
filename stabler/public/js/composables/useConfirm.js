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

	return {
		currentConfirm,
		confirm,
	};
}
