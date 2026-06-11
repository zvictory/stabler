<script setup>
import { computed } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { t } from "../../composables/i18n.js";
import ModuleHeader from "../../components/ModuleHeader.vue";

const route = useRoute();
const tabs = [
	{ name: "inventory-items", path: "/inventory/items", label: t("Items"), icon: "ti-box" },
	{ name: "inventory-warehouses", path: "/inventory/warehouses", label: t("Warehouses"), icon: "ti-building-warehouse" },
	{ name: "inventory-staging", path: "/inventory/staging", label: t("Material Staging"), icon: "ti-transfer" },
	{ name: "inventory-entries", path: "/inventory/entries", label: t("Stock Entries"), icon: "ti-clipboard-list" },
	{ name: "inventory-ledger", path: "/inventory/ledger", label: t("Stock Ledger"), icon: "ti-list-details" },
	{ name: "inventory-alerts", path: "/inventory/alerts", label: t("Low Stock"), icon: "ti-alert-triangle" },
];
const activeTab = computed(() => route.name);
</script>

<template>
	<ModuleHeader :title='t("Inventory")' icon="ti-package" :tabs="tabs" :active-tab="activeTab" />

	<div class="page-body">
		<div class="container-xl">
			<router-view />
		</div>
	</div>
</template>
