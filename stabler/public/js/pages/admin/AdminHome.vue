<script setup>
import { computed } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";
import ModuleHeader from "../../components/ModuleHeader.vue";

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
	<ModuleHeader :title='t("Admin")' icon="ti-settings" :tabs="tabs" :active-tab="activeTab" />

	<div class="page-body">
		<div class="container-xl">
			<router-view />
		</div>
	</div>
</template>
