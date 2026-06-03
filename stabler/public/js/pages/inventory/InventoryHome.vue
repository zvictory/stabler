<script setup>
import { computed } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { t } from "../../composables/i18n.js";

const route = useRoute();
const tabs = [
	{ name: "inventory-items", path: "/inventory/items", label: t("Items"), icon: "ti-box" },
	{ name: "inventory-warehouses", path: "/inventory/warehouses", label: t("Warehouses"), icon: "ti-building-warehouse" },
	{ name: "inventory-entries", path: "/inventory/entries", label: t("Stock Entries"), icon: "ti-clipboard-list" },
	{ name: "inventory-ledger", path: "/inventory/ledger", label: t("Stock Ledger"), icon: "ti-list-details" },
	{ name: "inventory-alerts", path: "/inventory/alerts", label: t("Low Stock"), icon: "ti-alert-triangle" },
];
const activeTab = computed(() => route.name);
</script>

<template>
	<div class="page-header d-print-none">
		<div class="container-xl">
			<div class="row g-2 align-items-center">
				<div class="col">
					<div class="page-pretitle">Module</div>
					<h2 class="page-title d-flex align-items-center gap-2">
						<i class="ti ti-package"></i> {{ t("Inventory") }}
					</h2>
				</div>
			</div>
		</div>
	</div>

	<div class="page-body">
		<div class="container-xl">
			<ul class="nav nav-bordered mb-3">
				<li v-for="tab in tabs" :key="tab.name" class="nav-item">
					<router-link :to="tab.path" class="nav-link" :class="{ active: activeTab === tab.name }">
						<i class="ti me-1" :class="tab.icon"></i>{{ tab.label }}
					</router-link>
				</li>
			</ul>
			<router-view />
		</div>
	</div>
</template>
