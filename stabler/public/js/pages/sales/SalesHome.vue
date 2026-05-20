<script setup>
import { computed } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";

const route = useRoute();
const tabs = [
	{ name: "sales-customers", path: "/sales/customers", label: "Customers", icon: "ti-users" },
	{ name: "sales-quotations", path: "/sales/quotations", label: "Quotations", icon: "ti-file-text" },
	{ name: "sales-orders", path: "/sales/orders", label: "Sales Orders", icon: "ti-clipboard-check" },
	{ name: "sales-invoices", path: "/sales/invoices", label: "Invoices", icon: "ti-file-invoice" },
	{ name: "sales-aging", path: "/sales/aging", label: "AR Aging", icon: "ti-clock-hour-4" },
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
						<i class="ti ti-trending-up"></i> Sales
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
