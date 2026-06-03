import { defineStore } from "pinia";
import { orgApi } from "../api/organization.js";
import { call } from "../api/client.js";

const boot = window.__STABLER__ || {};

const STORAGE_KEY = "stabler.activeCompany";

function initialCompany() {
	const saved = localStorage.getItem(STORAGE_KEY);
	if (saved && boot.companies?.some((c) => c.name === saved)) {
		return saved;
	}
	return boot.defaultCompany || boot.companies?.[0]?.name || "";
}

export const useSession = defineStore("session", {
	state: () => ({
		user: boot.user || { id: "", name: "", image: "", language: "en" },
		companies: boot.companies || [],
		activeCompany: initialCompany(),
		csrfToken: boot.csrfToken || "",
		roles: boot.roles || [],
		modules: boot.modules || null,
		allowedModules: boot.allowed_modules || null,
		rolesLoaded: Array.isArray(boot.roles) && boot.roles.length > 0,
	}),
	getters: {
		currentCompany(state) {
			return state.companies.find((c) => c.name === state.activeCompany) || null;
		},
		currency() {
			return this.currentCompany?.default_currency || "USD";
		},
		isAdmin(state) {
			return state.roles?.includes("System Manager") || state.roles?.includes("Stabler Admin");
		},
		// Returns a function so callers can pass a module key: session.canAccessModule("sales")
		// Null allowedModules (boot not yet loaded) defaults open — matches pre-boot behavior.
		canAccessModule(state) {
			return (key) => {
				if (this.isAdmin) return true;
				const companyOn =
					!state.modules ||
					(state.modules[key] !== false && state.modules[key] !== 0);
				const userOn =
					!state.allowedModules || state.allowedModules.includes(key);
				return companyOn && userOn;
			};
		},
	},
	actions: {
		async setCompany(company) {
			if (!company || company === this.activeCompany) return;
			this.activeCompany = company;
			localStorage.setItem(STORAGE_KEY, company);
			try {
				const r = await orgApi.switchCompany(company);
				if (r && r.modules) this.modules = r.modules;
			} catch (e) {
				/* Non-fatal: backend default sync is best-effort. */
			}
		},
		async ensureBoot() {
			if (this.rolesLoaded) return;
			// Deduplicate concurrent calls (e.g. bundle fire-and-forget + router await).
			if (this._bootPromise) return this._bootPromise;
			this._bootPromise = (async () => {
				try {
					const data = await call("stabler.api.organization.boot");
					if (data) {
						if (Array.isArray(data.roles)) this.roles = data.roles;
						if (Array.isArray(data.companies)) this.companies = data.companies;
						if (data.modules) this.modules = data.modules;
						if (Array.isArray(data.allowed_modules)) this.allowedModules = data.allowed_modules;
						if (data.user) this.user = { ...this.user, ...data.user };
					}
				} catch (e) {
					/* Non-fatal: org.boot may not exist yet (added in Task #6). */
				} finally {
					this.rolesLoaded = true;
					this._bootPromise = null;
				}
			})();
			return this._bootPromise;
		},
		setupRehydration() {
			document.addEventListener("visibilitychange", () => {
				if (document.visibilityState === "visible") {
					this.rolesLoaded = false;
					this.ensureBoot();
				}
			});
		},
	},
});
