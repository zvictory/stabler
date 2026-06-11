<script setup>
import { computed } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { t } from "../../composables/i18n.js";
import ModuleHeader from "../../components/ModuleHeader.vue";

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
	<ModuleHeader :title='t("Money")' icon="ti-coin" :tabs="tabs" :active-tab="activeTab" />

	<div class="page-body">
		<div class="container-xl">
			<router-view />
		</div>
	</div>
</template>
