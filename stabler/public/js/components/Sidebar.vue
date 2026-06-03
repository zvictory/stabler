<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";
import { useSession } from "../stores/session.js";
import { orgApi } from "../api/organization.js";
import { call } from "../api/client.js";
import { t } from "../composables/i18n.js";
import Select from "./Select.vue";

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
		{ name: "money", path: "/money", label: t("Money"), icon: "ti-coin", show: session.canAccessModule("money") },
		{ name: "sales", path: "/sales", label: t("Sales"), icon: "ti-trending-up", show: session.canAccessModule("sales") },
		{ name: "purchasing", path: "/purchasing", label: t("Purchasing"), icon: "ti-shopping-cart", show: session.canAccessModule("purchasing") },
		{ name: "inventory", path: "/inventory", label: t("Inventory"), icon: "ti-package", show: session.canAccessModule("inventory") },
		{ name: "manufacturing", path: "/manufacturing", label: t("Manufacturing"), icon: "ti-tools", show: session.canAccessModule("manufacturing") },
		{ name: "hr", path: "/hr", label: t("People"), icon: "ti-users-group", show: session.canAccessModule("hr") },
		{ name: "sfa", path: "/sfa", label: t("Field Sales"), icon: "ti-route", show: session.canAccessModule("field_sales") },
		{ name: "marketing", path: "/marketing", label: t("Trade Marketing"), icon: "ti-target-arrow", show: session.canAccessModule("marketing") },
		{ name: "remittance", path: "/remittance", label: t("Remittance"), icon: "ti-send", show: session.canAccessModule("remittance") },
		{ name: "installment", path: "/installment", label: t("Installment"), icon: "ti-calendar-dollar", show: session.canAccessModule("installment") },
	];
	if (session.isAdmin) {
		list.push({ name: "admin", path: "/admin", label: t("Admin"), icon: "ti-settings", show: true });
	}
	return list.filter((i) => i.show);
});

const initial = computed(() =>
	(session.user?.name || session.user?.id || "U").trim().slice(0, 1).toUpperCase()
);

function onCompanyChange(value) {
	session.setCompany(value);
}

const currentLanguage = computed(() => session.user?.language || "en");

async function setLanguage(code) {
	if (code === currentLanguage.value) return;
	try {
		await orgApi.updateLanguage(code);
	} catch (e) {
		alert(e?.message || "Failed to switch language.");
		return;
	}
	// Bundle for the new language is fetched on a full reload (controller
	// injects window.__STABLER__.translations from <lang>.csv at render time).
	window.location.reload();
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
				<ul class="navbar-nav pt-lg-3">
					<li
						v-for="item in items"
						:key="item.name"
						class="nav-item"
						:class="{ active: isActive(item.path).value }"
					>
						<router-link :to="item.path" class="nav-link">
							<span class="nav-link-icon"><i class="ti" :class="item.icon"></i></span>
							<span class="nav-link-title">{{ item.label }}</span>
						</router-link>
					</li>
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

					<div class="dropup px-2 pb-2">
						<a
							href="#"
							class="d-flex align-items-center text-decoration-none text-reset p-2 rounded user-menu-trigger"
							data-bs-toggle="dropdown"
							aria-expanded="false"
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
						</a>
						<div class="dropdown-menu dropdown-menu-arrow stbl-menu stbl-menu--nocheck">
							<h6 class="dropdown-header">{{ t("Language") }}</h6>
							<a
								v-for="lng in LANGUAGES"
								:key="lng.code"
								href="#"
								class="dropdown-item stbl-menu-item d-flex justify-content-between align-items-center"
								@click.prevent="setLanguage(lng.code)"
							>
								<span>{{ lng.label }}</span>
								<i v-if="lng.code === currentLanguage" class="ti ti-check text-primary"></i>
							</a>
							<div class="dropdown-divider"></div>
							<a href="/me" class="dropdown-item stbl-menu-item">
								<i class="ti ti-user me-2"></i>{{ t("Profile") }}
							</a>
							<div class="dropdown-divider"></div>
							<button type="button" class="dropdown-item stbl-menu-item text-danger" @click="logout">
								<i class="ti ti-logout me-2"></i>{{ t("Log out") }}
							</button>
						</div>
					</div>
				</div>
			</div>
		</div>
	</aside>
</template>
