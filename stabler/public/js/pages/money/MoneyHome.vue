<script setup>
import { computed } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { t } from "../../composables/i18n.js";

const route = useRoute();

const tabs = [
	{ name: "money-accounts", path: "/money/accounts", label: t("Chart of Accounts"), icon: "ti-list-tree" },
	{ name: "money-journals", path: "/money/journals", label: t("Journal Entries"), icon: "ti-book" },
	{ name: "money-payments", path: "/money/payments", label: t("Payments"), icon: "ti-cash" },
	{ name: "money-expenses", path: "/money/expenses", label: t("Expenses"), icon: "ti-receipt-2" },
	{ name: "money-transfers", path: "/money/transfers", label: t("Transfers"), icon: "ti-transfer" },
	{ name: "money-reports", path: "/money/reports", label: t("Reports"), icon: "ti-report-money" },
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
						<i class="ti ti-coin"></i> {{ t("Money") }}
					</h2>
				</div>
			</div>
		</div>
	</div>

	<div class="page-body">
		<div class="container-xl">
			<ul class="nav nav-bordered mb-3">
				<li v-for="tab in tabs" :key="tab.name" class="nav-item">
					<router-link
						:to="tab.path"
						class="nav-link"
						:class="{ active: activeTab === tab.name }"
					>
						<i class="ti me-1" :class="tab.icon"></i>{{ tab.label }}
					</router-link>
				</li>
			</ul>

			<router-view />
		</div>
	</div>
</template>
