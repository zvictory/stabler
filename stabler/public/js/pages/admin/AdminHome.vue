<script setup>
import { computed } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";

const route = useRoute();
const session = useSession();

const tabs = computed(() => {
	const mods = session.modules || {};
	const on = (key) => mods[key] !== false && mods[key] !== 0;
	const list = [
		{ name: "admin-users", path: "/admin/users", label: "Users", icon: "ti-users", show: true },
		{ name: "admin-roles", path: "/admin/roles", label: "Roles", icon: "ti-shield-lock", show: true },
		{ name: "admin-companies", path: "/admin/companies", label: "Companies", icon: "ti-building", show: true },
		{ name: "admin-compliance", path: "/admin/compliance", label: "Compliance", icon: "ti-shield-check", show: on("compliance") },
	];
	return list.filter((tab) => tab.show);
});

const activeTab = computed(() => route.name);
</script>

<template>
	<div class="page-header d-print-none">
		<div class="container-xl">
			<div class="row g-2 align-items-center">
				<div class="col">
					<div class="page-pretitle">{{ t("Module") }}</div>
					<h2 class="page-title d-flex align-items-center gap-2">
						<i class="ti ti-settings"></i> {{ t("Admin") }}
					</h2>
				</div>
			</div>
		</div>
	</div>

	<div class="page-body">
		<div class="container-xl">
			<ul class="nav nav-bordered mb-3">
				<li v-for="tab in tabs" :key="tab.name" class="nav-item">
					<router-link
						:to="tab.path"
						class="nav-link"
						:class="{ active: activeTab === tab.name }"
					>
						<i class="ti me-1" :class="tab.icon"></i>{{ t(tab.label) }}
					</router-link>
				</li>
			</ul>

			<router-view />
		</div>
	</div>
</template>
