<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { useSession } from "../stores/session.js";
import { orgApi } from "../api/organization.js";
import { call } from "../api/client.js";
import { t } from "../composables/i18n.js";
import { useToast } from "../composables/useToast.js";
import Select from "./Select.vue";

const toast = useToast();

async function logout() {
	await call("logout");
	window.location.href = "/login";
}

const LANGUAGES = [
	{ code: "en", label: "English" },
	{ code: "ru", label: "Русский" },
	{ code: "uz", label: "O‘zbekcha" },
	{ code: "uzc", label: "Ўзбекча" },
	{ code: "tr", label: "Türkçe" },
];

const route = useRoute();
const session = useSession();

const isActive = (path) => computed(() => route.path === path || route.path.startsWith(path + "/"));

const items = computed(() => {
	const list = [
		{ name: "dashboard", path: "/dashboard", label: t("Dashboard"), icon: "ti-home", show: session.canAccessModule("dashboard") },
		{ name: "pos", path: "/pos", label: t("POS"), icon: "ti-building-store", show: session.canAccessModule("sales") },
		{ name: "money", path: "/money", label: t("Money"), icon: "ti-coin", show: session.canAccessModule("money") },
		{ name: "sales", path: "/sales", label: t("Sales"), icon: "ti-trending-up", show: session.canAccessModule("sales") },
		{ name: "purchasing", path: "/purchasing", label: t("Purchasing"), icon: "ti-shopping-cart", show: session.canAccessModule("purchasing") },
			{ name: "imports", path: "/imports", label: t("Imports"), icon: "ti-plane", show: session.canAccessModule("imports") },
		{ name: "inventory", path: "/inventory", label: t("Inventory"), icon: "ti-package", show: session.canAccessModule("inventory") },
		{ name: "manufacturing", path: "/manufacturing", label: t("Manufacturing"), icon: "ti-tools", show: session.canAccessModule("manufacturing") },
		{ name: "hr", path: "/hr", label: t("People"), icon: "ti-users-group", show: session.canAccessModule("hr") },
		{ name: "sfa", path: "/sfa", label: t("Field Sales"), icon: "ti-route", show: session.canAccessModule("field_sales") },
		{ name: "marketing", path: "/marketing", label: t("Trade Marketing"), icon: "ti-target-arrow", show: session.canAccessModule("marketing") },
		{ name: "crm", path: "/crm", label: t("CRM"), icon: "ti-address-book", show: session.canAccessModule("crm") },
		{ name: "tender", path: "/tender/board", label: t("Tender"), icon: "ti-gavel", show: session.canAccessModule("tender") },
		{ name: "service", path: "/service", label: t("Service"), icon: "ti-tool", show: session.canAccessModule("service") },
		{ name: "bpm", path: "/bpm", label: t("Processes"), icon: "ti-sitemap", show: session.canAccessModule("bpm") },
		{ name: "remittance", path: "/remittance", label: t("Remittance"), icon: "ti-send", show: session.canAccessModule("remittance") },
		{ name: "installment", path: "/installment", label: t("Installment"), icon: "ti-calendar-dollar", show: session.canAccessModule("installment") },
		{
			name: "reports",
			path: "/reports",
			label: t("Reports"),
			icon: "ti-report-analytics",
			show: session.isAdmin || session.canAccessModule("sales") || session.canAccessModule("purchasing") || session.canAccessModule("hr") || session.canAccessModule("money") || session.canAccessModule("inventory"),
		},
	];
	if (session.isAdmin) {
		list.push({ name: "admin", path: "/admin", label: t("Admin"), icon: "ti-settings", show: true });
	}
	return list.filter((i) => i.show);
});

const sections = computed(() => {
	const byName = new Map(items.value.map((item) => [item.name, item]));
	const groups = [
		{ label: "", names: ["dashboard"] },
		{ label: t("Commerce"), names: ["pos", "sales", "crm", "sfa", "marketing"] },
		{ label: t("Operations"), names: ["purchasing", "imports", "inventory", "manufacturing", "service", "bpm"] },
		{ label: t("Finance"), names: ["money", "remittance", "installment"] },
		{ label: t("Company"), names: ["hr", "reports", "admin"] },
	];
	return groups
		.map((group) => ({
			label: group.label,
			items: group.names.map((name) => byName.get(name)).filter(Boolean),
		}))
		.filter((group) => group.items.length);
});

const initial = computed(() =>
	(session.user?.name || session.user?.id || "U").trim().slice(0, 1).toUpperCase()
);

function onCompanyChange(value) {
	session.setCompany(value);
}

const currentLanguage = computed(() => session.user?.language || "en");
const userMenuOpen = ref(false);
const userMenuTrigger = ref(null);
const userMenuEl = ref(null);
const userMenuStyle = ref({});

function positionUserMenu() {
	const trigger = userMenuTrigger.value;
	if (!trigger) return;
	const rect = trigger.getBoundingClientRect();
	const viewportPadding = 8;
	const gap = 4;
	const width = Math.min(Math.max(rect.width, 240), window.innerWidth - viewportPadding * 2);
	const left = Math.max(
		viewportPadding,
		Math.min(rect.left, window.innerWidth - width - viewportPadding)
	);
	const availableAbove = Math.max(0, rect.top - gap - viewportPadding);
	userMenuStyle.value = {
		position: "fixed",
		left: `${left}px`,
		bottom: `${window.innerHeight - rect.top + 4}px`,
		width: `${width}px`,
		maxHeight: `${availableAbove}px`,
		overflowY: "auto",
		zIndex: 1080,
	};
}

function removeUserMenuListeners() {
	document.removeEventListener("pointerdown", onUserMenuPointerDown);
	document.removeEventListener("keydown", onUserMenuKeydown);
	window.removeEventListener("resize", positionUserMenu);
	window.removeEventListener("scroll", positionUserMenu, true);
}

function closeUserMenu(restoreFocus = false) {
	if (!userMenuOpen.value) return;
	userMenuOpen.value = false;
	removeUserMenuListeners();
	if (restoreFocus) nextTick(() => userMenuTrigger.value?.focus());
}

function onUserMenuPointerDown(event) {
	const target = event.target;
	if (!(target instanceof Node)) return;
	if (userMenuTrigger.value?.contains(target) || userMenuEl.value?.contains(target)) return;
	closeUserMenu();
}

function onUserMenuKeydown(event) {
	if (event.key === "Escape") {
		event.preventDefault();
		closeUserMenu(true);
	}
}

async function toggleUserMenu(event) {
	if (userMenuOpen.value) {
		closeUserMenu(true);
		return;
	}
	userMenuOpen.value = true;
	await nextTick();
	positionUserMenu();
	document.addEventListener("pointerdown", onUserMenuPointerDown);
	document.addEventListener("keydown", onUserMenuKeydown);
	window.addEventListener("resize", positionUserMenu);
	window.addEventListener("scroll", positionUserMenu, true);
	if (event.detail === 0) {
		userMenuEl.value?.querySelector("a, button:not(:disabled)")?.focus();
	}
}

watch(() => route.fullPath, () => closeUserMenu());
onBeforeUnmount(removeUserMenuListeners);

async function setLanguage(code) {
	if (code === currentLanguage.value) return;
	try {
		await orgApi.updateLanguage(code);
	} catch (e) {
		toast.error(e?.message || t("Failed to switch language."));
		return;
	}
	// Bundle for the new language is fetched on a full reload (controller
	// injects window.__STABLER__.translations from <lang>.csv at render time).
	window.location.reload();
}

const cbuLoading = ref(false);

async function downloadCbuRates() {
	if (cbuLoading.value) return;
	cbuLoading.value = true;
	try {
		const res = await call("stabler.api.compliance.refresh_cbu_rates");
		const codes = Object.keys(res?.inserted || {});
		if (codes.length) {
			toast.success(t("CBU rates updated: {rates}", { rates: codes.join(", ") }));
		} else {
			toast.info(t("CBU rates are already up to date."));
		}
	} catch (e) {
		toast.error(e?.message || t("Failed to update CBU rates."));
	} finally {
		cbuLoading.value = false;
	}
}
</script>

<template>
	<aside class="navbar navbar-vertical navbar-expand-lg" data-bs-theme="dark">
		<div class="container-fluid">
			<button
				class="navbar-toggler"
				type="button"
				data-bs-toggle="collapse"
				data-bs-target="#sidebar-menu"
			>
				<span class="navbar-toggler-icon"></span>
			</button>
			<h1 class="navbar-brand navbar-brand-autodark">
				<router-link to="/dashboard" class="d-flex align-items-center gap-2 text-decoration-none">
					<img src="/assets/stabler/icons/scale.svg" width="32" height="32" alt="Stabler" />
					<span class="fw-bold">Stabler</span>
				</router-link>
			</h1>
			<div class="collapse navbar-collapse" id="sidebar-menu">
				<ul class="navbar-nav stbl-nav pt-lg-3">
					<template v-for="section in sections" :key="section.label || 'root'">
						<li v-if="section.label" class="stbl-nav-section">{{ section.label }}</li>
						<li
							v-for="item in section.items"
							:key="item.name"
							class="nav-item"
							:class="{ active: isActive(item.path).value }"
						>
							<router-link :to="item.path" class="nav-link">
								<span class="nav-link-icon"><i class="ti" :class="item.icon"></i></span>
								<span class="nav-link-title">{{ item.label }}</span>
							</router-link>
						</li>
					</template>
				</ul>

				<!-- Sidebar footer: company switcher + user menu pinned to bottom -->
				<div class="mt-auto pt-3 border-top border-secondary-subtle">
					<div v-if="session.companies.length" class="px-2 mb-2">
						<label class="form-label small text-secondary mb-1">{{ t("Company") }}</label>
						<Select
							:options="session.companies"
							value-key="name"
							label-key="name"
							:model-value="session.activeCompany"
							size="sm"
							@change="onCompanyChange"
							aria-label="Active company"
						/>
					</div>

					<div class="px-2 pb-2">
						<button
							ref="userMenuTrigger"
							type="button"
							class="d-flex align-items-center w-100 border-0 bg-transparent text-start text-reset p-2 rounded user-menu-trigger"
							aria-haspopup="menu"
							:aria-expanded="userMenuOpen"
							aria-controls="sidebar-user-menu"
							@click="toggleUserMenu"
						>
							<span
								v-if="session.user.image"
								class="avatar avatar-sm"
								:style="{ backgroundImage: `url('${session.user.image}')` }"
							></span>
							<span v-else class="avatar avatar-sm">{{ initial }}</span>
							<div class="ms-2 flex-grow-1 text-truncate">
								<div class="text-truncate">{{ session.user.name || session.user.id }}</div>
								<div class="mt-1 small text-secondary text-truncate">
									{{ session.activeCompany || "—" }}
								</div>
							</div>
							<i class="ti ti-dots-vertical text-secondary"></i>
						</button>
					</div>
				</div>
			</div>
		</div>
	</aside>

	<Teleport to="body">
		<div
			v-if="userMenuOpen"
			id="sidebar-user-menu"
			ref="userMenuEl"
			class="dropdown-menu show stbl-menu stbl-menu--nocheck"
			:style="userMenuStyle"
			role="menu"
		>
			<h6 class="dropdown-header">{{ t("Language") }}</h6>
			<a
				v-for="lng in LANGUAGES"
				:key="lng.code"
				href="#"
				class="dropdown-item stbl-menu-item d-flex justify-content-between align-items-center"
				role="menuitem"
				@click.prevent="setLanguage(lng.code)"
			>
				<span>{{ lng.label }}</span>
				<i v-if="lng.code === currentLanguage" class="ti ti-check text-primary"></i>
			</a>
			<div class="dropdown-divider"></div>
			<h6 class="dropdown-header">{{ t("Tools") }}</h6>
			<button
				type="button"
				class="dropdown-item stbl-menu-item"
				role="menuitem"
				:disabled="cbuLoading"
				@click="downloadCbuRates"
			>
				<i class="ti me-2" :class="cbuLoading ? 'ti-loader-2 ti-spin' : 'ti-refresh'"></i>
				{{ t("Download CBU exchange rates") }}
			</button>
			<div class="dropdown-divider"></div>
			<router-link
				to="/profile"
				class="dropdown-item stbl-menu-item"
				role="menuitem"
				@click="closeUserMenu"
			>
				<i class="ti ti-user me-2"></i>{{ t("Profile") }}
			</router-link>
			<div class="dropdown-divider"></div>
			<button
				type="button"
				class="dropdown-item stbl-menu-item text-danger"
				role="menuitem"
				@click="logout"
			>
				<i class="ti ti-logout me-2"></i>{{ t("Log out") }}
			</button>
		</div>
	</Teleport>
</template>
