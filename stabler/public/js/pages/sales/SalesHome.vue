<script setup>
import { computed } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { t } from "../../composables/i18n.js";
import ModuleHeader from "../../components/ModuleHeader.vue";

const route = useRoute();
const tabs = [
	{ name: "sales-customers", path: "/sales/customers", label: t("Customers"), icon: "ti-users" },
	{ name: "sales-quotations", path: "/sales/quotations", label: t("Quotations"), icon: "ti-file-description" },
	{ name: "sales-orders", path: "/sales/orders", label: t("Sales Orders"), icon: "ti-clipboard-check" },
	{ name: "sales-invoices", path: "/sales/invoices", label: t("Invoices"), icon: "ti-file-invoice" },
	{ name: "sales-aging", path: "/sales/aging", label: t("AR Aging"), icon: "ti-clock-hour-4" },
	{ name: "sales-reserved-stock", path: "/sales/reserved-stock", label: t("Reserved Stock"), icon: "ti-lock" },
	{ name: "sales-reports", path: "/reports", label: t("Reports"), icon: "ti-chart-bar" },
];
const activeTab = computed(() => route.name);
</script>

<template>
	<ModuleHeader :title='t("Sales")' icon="ti-trending-up" :tabs="tabs" :active-tab="activeTab" />

	<div class="page-body">
		<div class="container-xl">
			<router-view />
		</div>
	</div>
</template>
