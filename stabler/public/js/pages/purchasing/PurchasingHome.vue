<script setup>
import { computed } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { t } from "../../composables/i18n.js";
import ModuleHeader from "../../components/ModuleHeader.vue";

const route = useRoute();
const tabs = [
	{ name: "purchasing-suppliers", path: "/purchasing/suppliers", label: t("Suppliers"), icon: "ti-truck-delivery" },
	{ name: "purchasing-orders", path: "/purchasing/orders", label: t("Orders"), icon: "ti-clipboard-list" },
	{ name: "purchasing-receipts", path: "/purchasing/receipts", label: t("Receipts"), icon: "ti-package-import" },
	{ name: "purchasing-invoices", path: "/purchasing/invoices", label: t("Invoices"), icon: "ti-receipt" },
	{ name: "purchasing-aging", path: "/purchasing/aging", label: t("AP Aging"), icon: "ti-clock-hour-4" },
];
const activeTab = computed(() => route.name);
</script>

<template>
	<ModuleHeader :title='t("Purchasing")' icon="ti-shopping-cart" :tabs="tabs" :active-tab="activeTab" />

	<div class="page-body">
		<div class="container-xl">
			<router-view />
		</div>
	</div>
</template>
