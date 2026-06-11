<script setup>
import { computed } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { t } from "../../composables/i18n.js";

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
	<div class="page-header d-print-none">
		<div class="container-xl">
			<div class="row g-2 align-items-center">
				<div class="col">
					<div class="page-pretitle">Module</div>
					<h2 class="page-title d-flex align-items-center gap-2">
						<i class="ti ti-shopping-cart"></i> {{ t("Purchasing") }}
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
