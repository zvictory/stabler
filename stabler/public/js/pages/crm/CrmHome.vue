<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";
import { t } from "../../composables/i18n.js";
import ModuleHeader from "../../components/ModuleHeader.vue";

const route = useRoute();
const tabs = [
	{ name: "crm-leads", path: "/crm/leads", label: t("Leads"), icon: "ti-user-plus" },
	{ name: "crm-deals", path: "/crm/deals", label: t("Deals"), icon: "ti-briefcase" },
];
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
