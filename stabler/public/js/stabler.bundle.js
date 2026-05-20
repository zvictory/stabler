import { createApp } from "vue";
import { createPinia } from "pinia";
import { router } from "./router.js";
import App from "./App.vue";
import { useSession } from "./stores/session.js";

const mountEl = document.getElementById("app");
if (mountEl) {
	const app = createApp(App);
	const pinia = createPinia();
	app.use(pinia);
	app.use(router);
	app.mount(mountEl);

	// Best-effort: pull roles + module flags so the sidebar can gate Admin
	// and per-module tabs. Non-fatal if backend `boot` isn't deployed yet.
	const session = useSession(pinia);
	session.ensureBoot();
} else {
	console.error("[stabler] #app mount point not found");
}
