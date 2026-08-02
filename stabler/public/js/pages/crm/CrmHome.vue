<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";
import ModuleHeader from "../../components/ModuleHeader.vue";

const route = useRoute();
const session = useSession();

const isManager = computed(() => {
	const roles = session.roles || [];
	return roles.some((r) =>
		["System Manager", "Sales Manager", "CRM Specialist", "Administrator"].includes(r)
	);
});

const tabs = computed(() => {
	const list = [
		{ name: "crm-leads", path: "/crm/leads", label: t("Leads"), icon: "ti-user-plus" },
		{ name: "crm-deals", path: "/crm/deals", label: t("Deals"), icon: "ti-briefcase" },
	];
	if (isManager.value) {
		list.push({
			name: "crm-cockpit",
			path: "/crm/cockpit",
			label: t("Cockpit"),
			icon: "ti-dashboard",
		});
	}
	return list;
});

const activeTab = computed(() => route.name);
</script>

<template>
	<ModuleHeader :title='t("CRM")' icon="ti-address-book" :tabs="tabs" :active-tab="activeTab" />

	<div class="page-body">
		<div class="container-xl">
			<router-view />
		</div>
	</div>
</template>
