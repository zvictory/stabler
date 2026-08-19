<script setup>
import { computed, onMounted, ref } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import ModuleHeader from "../../components/ModuleHeader.vue";
import { useSession } from "../../stores/session.js";

const route = useRoute();
const session = useSession();

// Effective ERPNext back-dating freeze for this user — shown as a thin banner so
// people know up-front why old-dated postings are blocked, and where to change it.
const backdating = ref(null);
onMounted(async () => {
	try {
		if (!session.activeCompany) return;
		backdating.value = await call("stabler.api.money.get_backdating_status", { company: session.activeCompany });
	} catch {
		backdating.value = null;
	}
});
const freezeDate = computed(() => {
	const b = backdating.value;
	if (!b || !b.active) return null;
	const dates = [b.stock_earliest_date, b.acc_earliest_date].filter(Boolean);
	return dates.length ? dates.sort().reverse()[0] : null;
});

// The payment calendar is a separate module: it appears only where the tenant
// switched it on, so the tab list is computed rather than constant.
const tabs = computed(() => [
	{ name: "money-accounts", path: "/money/accounts", label: t("Chart of Accounts"), icon: "ti-list-tree" },
	{ name: "money-journals", path: "/money/journals", label: t("Journal Entries"), icon: "ti-book" },
	{ name: "money-payments", path: "/money/payments", label: t("Payments"), icon: "ti-cash" },
	{ name: "money-expenses", path: "/money/expenses", label: t("Expenses"), icon: "ti-receipt-2" },
	{ name: "money-transfers", path: "/money/transfers", label: t("Transfers"), icon: "ti-transfer" },
	{ name: "money-reports", path: "/money/reports", label: t("Reports"), icon: "ti-report-money" },
	{ name: "money-approvals", path: "/money/approvals", label: t("Approvals"), icon: "ti-checklist" },
	{ name: "money-reconcile", path: "/money/reconcile", label: t("Reconcile"), icon: "ti-arrows-left-right" },
	...(session.canAccessModule("payment_calendar")
		? [{ name: "money-payment-calendar", path: "/money/calendar", label: t("Payment Calendar"), icon: "ti-calendar-dollar" }]
		: []),
]);

const activeTab = computed(() => route.name);
</script>

<template>
	<ModuleHeader :title='t("Money")' icon="ti-coin" :tabs="tabs" :active-tab="activeTab" />

	<div class="page-body">
		<div class="container-xl">
			<div v-if="freezeDate" class="alert alert-warning py-2 px-3 mb-3 d-flex align-items-center" role="alert">
				<i class="ti ti-calendar-lock me-2"></i>
				<span class="flex-fill">
					{{ t("Backdated postings are frozen before {0}.").replace("{0}", formatDate(freezeDate)) }}
				</span>
				<RouterLink to="/admin/posting-window" class="small text-reset text-decoration-underline ms-2">
					{{ t("Change") }}
				</RouterLink>
			</div>
			<router-view />
		</div>
	</div>
</template>
