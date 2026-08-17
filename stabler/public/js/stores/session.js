import { defineStore } from "pinia";
import { orgApi } from "../api/organization.js";
import { call } from "../api/client.js";

const boot = window.__STABLER__ || {};

const STORAGE_KEY = "stabler.activeCompany";

// `Remittance Settings.remittance_engine`. Legacy is the shipped default and the
// answer for every unknown, so the Transfer V1 screens are something a company opts
// into and never something it lands in by accident.
const REMITTANCE_LEGACY = "Legacy";
const REMITTANCE_V1 = "V1";

function initialCompany() {
	const saved = localStorage.getItem(STORAGE_KEY);
	if (saved && boot.companies?.some((c) => c.name === saved)) {
		return saved;
	}
	if (boot.companies?.some((c) => c.name === "Mikas")) {
		return "Mikas";
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
		// Imports landed-cost visibility (WP6b). Seeded from the shell, refreshed by
		// boot(). Null = unknown (pre-boot); treat as hidden until confirmed.
		costVisible: typeof boot.cost_visible === "boolean" ? boot.cost_visible : null,
		// Remittance engine, and the company it was answered for. The pair travels
		// together on purpose: this flag is per company, and a bare string outlives
		// the question it answered — activeCompany is seeded from localStorage and can
		// differ from the company boot() described. The HTML shell does not seed it,
		// so both start null (unknown) and read as Legacy until boot() answers.
		remittanceEngine: null,
		remittanceEngineCompany: null,
		rolesLoaded: Array.isArray(boot.roles) && boot.roles.length > 0,
		tenderViews: [],
		tenderViewsLoaded: false,
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
		isMfgManager(state) {
			return this.isAdmin || (state.roles?.includes("Manufacturing Manager") ?? false);
		},
		// True only when the ACTIVE company is known to run Transfer V1. Unknown reads
		// as Legacy, and a value answered for another company reads as Legacy too —
		// the alternative is opening the payout and refund desks on a tenant whose
		// answer was never asked for. Admin does NOT override this: the engine is a
		// company's accounting decision, not a permission.
		isRemittanceV1(state) {
			return (
				state.remittanceEngine === REMITTANCE_V1 &&
				!!state.activeCompany &&
				state.remittanceEngineCompany === state.activeCompany
			);
		},
		// Returns a function so callers can pass a module key: session.canAccessModule("sales")
		// Null allowedModules (boot not yet loaded) defaults open — matches pre-boot behavior.
		canAccessModule(state) {
			return (key) => {
				const companyOn =
					!state.modules ||
					(state.modules[key] !== false && state.modules[key] !== 0);
				if (!companyOn) return false;
				if (this.isAdmin) return true;
				const userOn =
					!state.allowedModules ||
					!state.allowedModules.length ||
					state.allowedModules.includes(key);
				return companyOn && userOn;
			};
		},
	},
	actions: {
		async setCompany(company) {
			if (!company || company === this.activeCompany) return;
			this.activeCompany = company;
			this.tenderViews = [];
			this.tenderViewsLoaded = false;
			this._tenderViewsRequestCompany = null;
			localStorage.setItem(STORAGE_KEY, company);
			try {
				const r = await orgApi.switchCompany(company);
				if (this.activeCompany !== company) return;
				if (r && r.modules) this.modules = r.modules;
				if (r && r.remittance_engine) {
					this.remittanceEngine = r.remittance_engine;
					this.remittanceEngineCompany = company;
				}
				await this.ensureTenderViews();
			} catch (e) {
				/* Non-fatal: backend default sync is best-effort. */
			}
		},
		async ensureBoot() {
			if (this.rolesLoaded) return;
			if (!this.user?.id || this.user.id === "Guest" || window.location.hash.includes("/login")) return;
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
						if (typeof data.cost_visible === "boolean") this.costVisible = data.cost_visible;
						// boot() answers the engine for the company the SERVER holds as
						// default, which is not always the one the browser restored. Bind
						// it to that company and let ensureRemittanceEngine() close the gap.
						if (data.remittance_engine && data.default_company) {
							this.remittanceEngine = data.remittance_engine;
							this.remittanceEngineCompany = data.default_company;
						}
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
		// Resolve the remittance engine for whichever company is active now.
		//
		// boot() and switch_company() both carry the value for free, so this only ever
		// makes a request when what the store holds describes a different company —
		// the first navigation after a login where localStorage restored a company the
		// server does not consider default. Resolves to Legacy on any failure and does
		// NOT cache that, so a transient error closes the gate for one navigation
		// rather than for the session.
		async ensureRemittanceEngine() {
			const company = this.activeCompany;
			if (!company) return REMITTANCE_LEGACY;
			if (this.remittanceEngineCompany === company) return this.remittanceEngine || REMITTANCE_LEGACY;
			if (this._remittanceEnginePromise && this._remittanceEngineRequestCompany === company) {
				return this._remittanceEnginePromise;
			}
			const request = call("stabler.api.organization.remittance_engine", { company })
				.then((r) => {
					const engine = r?.remittance_engine || REMITTANCE_LEGACY;
					// Bind only if the answer still describes the company on screen: a
					// switch mid-flight makes this reply an answer about the past.
					if (this.activeCompany === company && r?.company === company) {
						this.remittanceEngine = engine;
						this.remittanceEngineCompany = company;
					}
					return engine;
				})
				.catch(() => REMITTANCE_LEGACY)
				.finally(() => {
					if (this._remittanceEnginePromise === request) {
						this._remittanceEnginePromise = null;
						this._remittanceEngineRequestCompany = null;
					}
				});
			this._remittanceEnginePromise = request;
			this._remittanceEngineRequestCompany = company;
			return request;
		},
		async ensureTenderViews() {
			if (!this.user?.id || this.user.id === "Guest" || window.location.hash.includes("/login")) return [];
			if (!this.canAccessModule("tender")) return [];
			if (this.tenderViewsLoaded) return this.tenderViews;
			const company = this.activeCompany;
			if (this._tenderViewsPromise && this._tenderViewsRequestCompany === company) {
				return this._tenderViewsPromise;
			}
			const request = call("stabler.api.tender.tender_views", {})
				.then((result) => {
					const views = Array.isArray(result?.views) ? result.views : [];
					if (this.activeCompany === company) {
						this.tenderViews = views;
						this.tenderViewsLoaded = true;
					}
					return views;
				})
				.finally(() => {
					if (this._tenderViewsPromise === request) {
						this._tenderViewsPromise = null;
						this._tenderViewsRequestCompany = null;
					}
				});
			this._tenderViewsPromise = request;
			this._tenderViewsRequestCompany = company;
			return request;
		},
		setupRehydration() {
			document.addEventListener("visibilitychange", () => {
				if (document.visibilityState === "visible") {
					if (!this.user?.id || this.user.id === "Guest" || window.location.hash.includes("/login")) return;
					this.rolesLoaded = false;
					this.tenderViews = [];
					this.tenderViewsLoaded = false;
					this._tenderViewsRequestCompany = null;
					this.ensureBoot().then(() => this.ensureTenderViews());
				}
			});
		},
	},
});
