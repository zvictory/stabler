import { createApp } from "vue";
import { createPinia } from "pinia";
import { router } from "./router.js";
import App from "./App.vue";
import { useSession } from "./stores/session.js";

import { useToast } from "./composables/useToast.js";

const mountEl = document.getElementById("app");
if (mountEl) {
	const app = createApp(App);
	const pinia = createPinia();
	app.use(pinia);
	app.use(router);

	// Global error handler for Vue components
	app.config.errorHandler = (err) => {
		console.error("[stabler] global error:", err);
		const isConflict =
			err && (
				err.status === 409 ||
				err.status === 417 ||
				(err.message && err.message.includes("changed by someone else")) ||
				(err.response && err.response.exception && err.response.exception.includes("TimestampMismatchError")) ||
				(err.response && err.response.exc_type === "TimestampMismatchError")
			);
		if (!isConflict) {
			const toast = useToast();
			toast.error(err?.message || String(err));
		}
	};

	// Global unhandled promise rejection handler
	window.addEventListener("unhandledrejection", (event) => {
		const err = event.reason;
		if (!err) return;
		const isConflict =
			err.status === 409 ||
			err.status === 417 ||
			(err.message && err.message.includes("changed by someone else")) ||
			(err.response && err.response.exception && err.response.exception.includes("TimestampMismatchError")) ||
			(err.response && err.response.exc_type === "TimestampMismatchError");

		if (isConflict) return; // Handled by useDocumentForm reload dialog

		if (err.message && (err.message.includes("Navigation cancelled") || err.message.includes("Redirected when going from"))) {
			return; // Ignore router cancellations
		}

		console.error("[stabler] unhandled rejection:", err);
		const toast = useToast();
		toast.error(err.message || String(err));
	});

	app.mount(mountEl);

	const session = useSession(pinia);
	session.ensureBoot();
} else {
	console.error("[stabler] #app mount point not found");
}
