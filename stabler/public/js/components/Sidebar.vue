<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";
import { useSession } from "../stores/session.js";
import { orgApi } from "../api/organization.js";
import { t } from "../composables/i18n.js";

const LANGUAGES = [
	{ code: "en", label: "English" },
	{ code: "ru", label: "Русский" },
	{ code: "uz", label: "O‘zbekcha" },
	{ code: "uzc", label: "Ўзбекча" },
];

const route = useRoute();
const session = useSession();

const isActive = (path) => computed(() => route.path === path || route.path.startsWith(path + "/"));

const items = computed(() => {
	const mods = session.modules || {};
	// Default ON when boot/modules payload isn't loaded yet — preserves
	// pre-multi-tenant behavior until the backend lands.
	const on = (key) => mods[key] !== false && mods[key] !== 0;
	const list = [
		{ name: "dashboard", path: "/dashboard", label: t("Dashboard"), icon: "ti-home", show: true },
		{ name: "money", path: "/money", label: t("Money"), icon: "ti-coin", show: on("money") },
		{ name: "sales", path: "/sales", label: t("Sales"), icon: "ti-trending-up", show: on("sales") },
		{ name: "purchasing", path: "/purchasing", label: t("Purchasing"), icon: "ti-shopping-cart", show: on("purchasing") },
		{ name: "inventory", path: "/inventory", label: t("Inventory"), icon: "ti-package", show: on("inventory") },
		{ name: "manufacturing", path: "/manufacturing", label: t("Manufacturing"), icon: "ti-tools", show: on("manufacturing") },
		{ name: "hr", path: "/hr", label: t("People"), icon: "ti-users-group", show: on("hr") },
		{ name: "sfa", path: "/sfa", label: t("Field Sales"), icon: "ti-route", show: on("field_sales") },
		{ name: "marketing", path: "/marketing", label: t("Trade Marketing"), icon: "ti-target-arrow", show: on("marketing") },
	];
	if (session.isAdmin) {
		list.push({ name: "admin", path: "/admin", label: t("Admin"), icon: "ti-settings", show: true });
	}
	return list.filter((i) => i.show);
});

const initial = computed(() =>
	(session.user?.name || session.user?.id || "U").trim().slice(0, 1).toUpperCase()
);

function onCompanyChange(event) {
	session.setCompany(event.target.value);
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
						<select
							class="form-select form-select-sm"
							:value="session.activeCompany"
							@change="onCompanyChange"
							aria-label="Active company"
						>
							<option v-for="c in session.companies" :key="c.name" :value="c.name">
								{{ c.name }}
							</option>
						</select>
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
						<div class="dropdown-menu dropdown-menu-arrow">
							<h6 class="dropdown-header">{{ t("Language") }}</h6>
							<a
								v-for="lng in LANGUAGES"
								:key="lng.code"
								href="#"
								class="dropdown-item d-flex justify-content-between align-items-center"
								@click.prevent="setLanguage(lng.code)"
							>
								<span>{{ lng.label }}</span>
								<i v-if="lng.code === currentLanguage" class="ti ti-check text-primary"></i>
							</a>
							<div class="dropdown-divider"></div>
							<a href="/me" class="dropdown-item">
								<i class="ti ti-user me-2"></i>{{ t("Profile") }}
							</a>
							<a href="/app" class="dropdown-item">
								<i class="ti ti-external-link me-2"></i>{{ t("Open Desk") }}
							</a>
							<div class="dropdown-divider"></div>
							<a href="/api/method/logout" class="dropdown-item text-danger">
								<i class="ti ti-logout me-2"></i>{{ t("Log out") }}
							</a>
						</div>
					</div>
				</div>
			</div>
		</div>
	</aside>
</template>
