<script setup>
import { computed } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";

const route = useRoute();

const tabs = [
	{ name: "money-accounts", path: "/money/accounts", label: "Chart of Accounts", icon: "ti-list-tree" },
	{ name: "money-journals", path: "/money/journals", label: "Journal Entries", icon: "ti-book" },
	{ name: "money-payments", path: "/money/payments", label: "Payments", icon: "ti-cash" },
	{ name: "money-expenses", path: "/money/expenses", label: "Expenses", icon: "ti-receipt-2" },
	{ name: "money-transfers", path: "/money/transfers", label: "Transfers", icon: "ti-transfer" },
	{ name: "money-reports", path: "/money/reports", label: "Reports", icon: "ti-report-money" },
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
						<i class="ti ti-coin"></i> Money
					</h2>
				</div>
			</div>
		</div>
	</div>

	<div class="page-body">
		<div class="container-xl">
			<ul class="nav nav-bordered mb-3">
				<li v-for="t in tabs" :key="t.name" class="nav-item">
					<router-link
						:to="t.path"
						class="nav-link"
						:class="{ active: activeTab === t.name }"
					>
						<i class="ti me-1" :class="t.icon"></i>{{ t.label }}
					</router-link>
				</li>
			</ul>

			<router-view />
		</div>
	</div>
</template>
