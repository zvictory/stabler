<script setup>
import { computed } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { t } from "../../composables/i18n.js";

const route = useRoute();
const tabs = [
	{ name: "sales-customers", path: "/sales/customers", label: t("Customers"), icon: "ti-users" },
	{ name: "sales-quotations", path: "/sales/quotations", label: t("Quotations"), icon: "ti-file-text" },
	{ name: "sales-orders", path: "/sales/orders", label: t("Sales Orders"), icon: "ti-clipboard-check" },
	{ name: "sales-invoices", path: "/sales/invoices", label: t("Invoices"), icon: "ti-file-invoice" },
	{ name: "sales-aging", path: "/sales/aging", label: t("AR Aging"), icon: "ti-clock-hour-4" },
	{ name: "sales-reserved-stock", path: "/sales/reserved-stock", label: t("Reserved Stock"), icon: "ti-lock" },
	{ name: "sales-reports", path: "/sales/reports", label: t("Reports"), icon: "ti-chart-bar" },
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
						<i class="ti ti-trending-up"></i> {{ t("Sales") }}
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
