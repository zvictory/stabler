import { createApp } from "vue";
import { createPinia } from "pinia";
import { router } from "./router.js";
import App from "./App.vue";
import { useSession } from "./stores/session.js";

import { useToast } from "./composables/useToast.js";
import { startVersionCheck } from "./composables/version-check.js";
import { hardRedirect } from "./composables/authRedirect.js";

if (window.location.pathname === "/login" && !window.location.hash.startsWith("#/login")) {
	const search = window.location.search || "";
	window.location.replace(`/stabler#/login${search}`);
}

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

	// A 403 can mean two very different things: the server session died (expired
	// sid, logout in another tab) or a genuine permission error on one endpoint.
	// Probe the session before redirecting so real PermissionErrors keep their
	// normal in-page handling.
	let sessionProbeInFlight = false;
	window.addEventListener("stabler:forbidden", async () => {
		if (sessionProbeInFlight || window.location.hash.startsWith("#/login")) return;
		sessionProbeInFlight = true;
		try {
			const res = await fetch("/api/method/frappe.auth.get_logged_user", {
				credentials: "same-origin",
				headers: { Accept: "application/json" },
			});
			const data = await res.json().catch(() => ({}));
			const user = data && data.message;
			if (res.ok && user && user !== "Guest") return;
			const current = window.location.hash.replace(/^#/, "") || "/dashboard";
			hardRedirect(`/login?redirect-to=${encodeURIComponent(current)}&session-expired=1`);
		} catch {
			/* network failure — can't tell, leave the page alone */
		} finally {
			sessionProbeInFlight = false;
		}
	});

	app.mount(mountEl);

	const session = useSession(pinia);
	session.ensureBoot();
	startVersionCheck();
} else {
	console.error("[stabler] #app mount point not found");
}
