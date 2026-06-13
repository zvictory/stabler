import { ref } from "vue";

const currentConfirm = ref(null);

export function useConfirm() {
	function confirm({ title, body, danger = false, confirmLabel = "Confirm", cancelLabel = "Cancel" }) {
		return new Promise((resolve) => {
			currentConfirm.value = {
				title,
				body,
				danger,
				confirmLabel,
				cancelLabel,
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
