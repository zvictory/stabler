<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";
import { t } from "../../composables/i18n.js";
import ModuleHeader from "../../components/ModuleHeader.vue";

const route = useRoute();
const activeTab = computed(() => route.name);

const tabs = [
	{ name: "service-dashboard", path: "/service/dashboard", label: t("Dashboard"), icon: "ti-layout-dashboard" },
	{ name: "service-tickets", path: "/service/tickets", label: t("Tickets"), icon: "ti-ticket" },
	{ name: "service-calendar", path: "/service/calendar", label: t("Calendar"), icon: "ti-calendar" },
	{ name: "service-equipment", path: "/service/equipment", label: t("Equipment"), icon: "ti-fridge" },
	{ name: "service-map", path: "/service/map", label: t("Map"), icon: "ti-map-2" },
];
</script>

<template>
	<ModuleHeader :title='t("Service")' icon="ti-tool" :tabs="tabs" :active-tab="activeTab" />

	<div class="page-body">
		<div class="container-xl">
			<router-view />
		</div>
	</div>
</template>
