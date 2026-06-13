import { ref } from "vue";

const toasts = ref([]);
let nextId = 0;

export function useToast() {
	function addToast(message, type = "info", duration = 3000) {
		const id = nextId++;
		const toast = { id, message, type };
		toasts.value.push(toast);

		if (duration > 0) {
			setTimeout(() => {
				removeToast(id);
			}, duration);
		}
		return id;
	}

	function removeToast(id) {
		toasts.value = toasts.value.filter((t) => t.id !== id);
	}

	return {
		toasts,
		success: (msg, duration) => addToast(msg, "success", duration),
		error: (msg, duration) => addToast(msg, "danger", duration),
		info: (msg, duration) => addToast(msg, "info", duration),
		warning: (msg, duration) => addToast(msg, "warning", duration),
		remove: removeToast,
	};
}
