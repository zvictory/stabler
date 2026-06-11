<script setup>
import { computed } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { t } from "../../composables/i18n.js";
import ModuleHeader from "../../components/ModuleHeader.vue";

const route = useRoute();

const tabs = computed(() => [
	{ name: "sfa-outlets", path: "/sfa/outlets", label: t("Outlets"), icon: "ti-building-store" },
	{ name: "sfa-routes", path: "/sfa/routes", label: t("Routes"), icon: "ti-route" },
	{ name: "sfa-visits", path: "/sfa/visits", label: t("Visits"), icon: "ti-map-pin-check" },
	{ name: "sfa-field-users", path: "/sfa/field-users", label: t("Field Users"), icon: "ti-user-check" },
	{ name: "sfa-van-stock", path: "/sfa/van-stock", label: t("Van Stock"), icon: "ti-truck-loading" },
	{ name: "sfa-promos", path: "/sfa/promos", label: t("Promos"), icon: "ti-discount-2" },
	{ name: "sfa-photos", path: "/sfa/photos", label: t("Photos"), icon: "ti-camera" },
	{ name: "sfa-planograms", path: "/sfa/planograms", label: t("Planograms"), icon: "ti-layout-grid" },
	{ name: "sfa-osa", path: "/sfa/osa", label: t("OSA"), icon: "ti-checkup-list" },
	{ name: "sfa-receivables", path: "/sfa/receivables", label: t("Receivables"), icon: "ti-receipt-2" },
]);

const activeTab = computed(() => route.name);
</script>

<template>
	<ModuleHeader :title='t("Field Sales")' icon="ti-route" :tabs="tabs" :active-tab="activeTab" />

	<div class="page-body">
		<div class="container-xl">
			<router-view />
		</div>
	</div>
</template>
