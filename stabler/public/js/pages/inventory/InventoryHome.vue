<script setup>
import { computed } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";

const route = useRoute();
const tabs = [
	{ name: "inventory-items", path: "/inventory/items", label: "Items", icon: "ti-box" },
	{ name: "inventory-warehouses", path: "/inventory/warehouses", label: "Warehouses", icon: "ti-building-warehouse" },
	{ name: "inventory-entries", path: "/inventory/entries", label: "Stock Entries", icon: "ti-clipboard-list" },
	{ name: "inventory-ledger", path: "/inventory/ledger", label: "Stock Ledger", icon: "ti-list-details" },
	{ name: "inventory-alerts", path: "/inventory/alerts", label: "Low Stock", icon: "ti-alert-triangle" },
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
						<i class="ti ti-package"></i> Inventory
					</h2>
				</div>
			</div>
		</div>
	</div>

	<div class="page-body">
		<div class="container-xl">
			<ul class="nav nav-bordered mb-3">
				<li v-for="t in tabs" :key="t.name" class="nav-item">
					<router-link :to="t.path" class="nav-link" :class="{ active: activeTab === t.name }">
						<i class="ti me-1" :class="t.icon"></i>{{ t.label }}
					</router-link>
				</li>
			</ul>
			<router-view />
		</div>
	</div>
</template>
