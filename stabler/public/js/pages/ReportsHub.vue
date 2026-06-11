<script setup>
import { computed, ref } from "vue";
import { useSession } from "../stores/session.js";
import { t } from "../composables/i18n.js";

const session = useSession();
const search = ref("");
const selectedCategory = ref("all");

const groups = computed(() => [
	{
		key: "financial",
		label: t("Financial"),
		icon: "ti-report-money",
		module: "money",
		reports: [
			{
				title: t("Financial Statements"),
				description: t("Profit and Loss, Balance Sheet, Trial Balance, and Cash Flow."),
				path: "/money/reports",
				icon: "ti-file-analytics",
				badge: t("ERPNext"),
			},
			{
				title: t("Account Ledger"),
				description: t("Opening balance, period movement, and running balance by account."),
				path: "/money/accounts",
				icon: "ti-list-details",
				badge: t("Ledger"),
			},
		],
	},
	{
		key: "sales",
		label: t("Sales"),
		icon: "ti-trending-up",
		module: "sales",
		reports: [
			{
				title: t("Sales Performance"),
				description: t("Customer, item, trend, and salesperson reports from submitted invoices."),
				path: "/sales/reports",
				icon: "ti-chart-bar",
				badge: t("Sales"),
			},
			{
				title: t("AR Aging"),
				description: t("Customer receivables grouped by aging buckets."),
				path: "/sales/aging",
				icon: "ti-clock-hour-4",
				badge: t("Receivables"),
			},
			{
				title: t("Reserved Stock"),
				description: t("Sales reservations and stock committed to orders."),
				path: "/sales/reserved-stock",
				icon: "ti-lock",
				badge: t("Inventory"),
			},
		],
	},
	{
		key: "purchasing",
		label: t("Purchasing"),
		icon: "ti-shopping-cart",
		module: "purchasing",
		reports: [
			{
				title: t("AP Aging"),
				description: t("Supplier payables grouped by aging buckets."),
				path: "/purchasing/aging",
				icon: "ti-calendar-dollar",
				badge: t("Payables"),
			},
		],
	},
	{
		key: "inventory",
		label: t("Inventory"),
		icon: "ti-package",
		module: "inventory",
		reports: [
			{
				title: t("Stock Ledger"),
				description: t("Item movement, voucher trace, quantities, and stock value."),
				path: "/inventory/ledger",
				icon: "ti-list-details",
				badge: t("Stock"),
			},
			{
				title: t("Low Stock Alerts"),
				description: t("Items below replenishment thresholds."),
				path: "/inventory/alerts",
				icon: "ti-alert-triangle",
				badge: t("Alerts"),
			},
		],
	},
	{
		key: "people",
		label: t("People"),
		icon: "ti-users-group",
		module: "hr",
		reports: [
			{
				title: t("Attendance"),
				description: t("Daily attendance records and employee presence checks."),
				path: "/hr/attendance",
				icon: "ti-calendar-check",
				badge: t("HR"),
			},
			{
				title: t("Payroll"),
				description: t("Salary and payroll summaries."),
				path: "/hr/payroll",
				icon: "ti-cash",
				badge: t("HR"),
			},
		],
	},
	{
		key: "field_sales",
		label: t("Field Sales"),
		icon: "ti-route",
		module: "field_sales",
		reports: [
			{
				title: t("Field Receivables"),
				description: t("Outstanding customer balances for field teams."),
				path: "/sfa/receivables",
				icon: "ti-receipt-2",
				badge: t("SFA"),
			},
			{
				title: t("Photo Reports"),
				description: t("Visit photos and outlet execution evidence."),
				path: "/sfa/photos",
				icon: "ti-camera",
				badge: t("SFA"),
			},
			{
				title: t("OSA Audits"),
				description: t("On-shelf availability checks from field visits."),
				path: "/sfa/osa",
				icon: "ti-checkup-list",
				badge: t("SFA"),
			},
		],
	},
	{
		key: "marketing",
		label: t("Trade Marketing"),
		icon: "ti-target-arrow",
		module: "marketing",
		reports: [
			{
				title: t("Campaign ROI"),
				description: t("Promotion spend and uplift analysis."),
				path: "/marketing/roi",
				icon: "ti-chart-line",
				badge: t("Marketing"),
			},
			{
				title: t("Claims"),
				description: t("Trade marketing claims and settlement tracking."),
				path: "/marketing/claims",
				icon: "ti-file-dollar",
				badge: t("Marketing"),
			},
		],
	},
	{
		key: "installment",
		label: t("Installment"),
		icon: "ti-calendar-dollar",
		module: "installment",
		reports: [
			{
				title: t("Installment Calendar"),
				description: t("Scheduled installment collections and outstanding balances."),
				path: "/installment/calendar",
				icon: "ti-calendar-stats",
				badge: t("Installment"),
			},
		],
	},
]);

const matchesSearch = (report, group) => {
	const q = search.value.trim().toLowerCase();
	if (!q) return true;
	return [report.title, report.description, group.label, report.badge]
		.join(" ")
		.toLowerCase()
		.includes(q);
};

// Categories with their search-filtered reports and access flags.
const filteredGroups = computed(() =>
	groups.value
		.map((group) => ({
			...group,
			allowed: session.canAccessModule(group.module),
			reports: group.reports.filter((report) => matchesSearch(report, group)),
		}))
		.filter((group) => group.reports.length)
);

// Sections shown in the main pane (respects the selected category).
const visibleGroups = computed(() =>
	filteredGroups.value.filter(
		(group) => selectedCategory.value === "all" || group.key === selectedCategory.value
	)
);

const allReports = computed(() =>
	groups.value.flatMap((group) =>
		group.reports.map((report) => ({
			...report,
			allowed: session.canAccessModule(group.module),
		}))
	)
);

const totalCount = computed(() =>
	filteredGroups.value.reduce((sum, group) => sum + group.reports.length, 0)
);

const availableCount = computed(() => allReports.value.filter((report) => report.allowed).length);

function selectCategory(key) {
	selectedCategory.value = key;
}
</script>

<template>
	<div class="page-header d-print-none">
		<div class="container-xl">
			<div class="row g-2 align-items-center">
				<div class="col">
					<div class="page-pretitle">{{ t("Workspace") }}</div>
					<h2 class="page-title d-flex align-items-center gap-2">
						<i class="ti ti-report-analytics"></i> {{ t("Reports") }}
					</h2>
				</div>
				<div class="col-auto">
					<span class="badge bg-blue-lt">
						{{ availableCount }} / {{ allReports.length }} {{ t("available") }}
					</span>
				</div>
			</div>
		</div>
	</div>

	<div class="page-body">
		<div class="container-xl">
			<div class="row g-3">
				<!-- Category rail -->
				<div class="col-12 col-lg-3">
					<div class="card reports-category-rail">
						<div class="card-header py-2">
							<h3 class="card-title">{{ t("Categories") }}</h3>
						</div>
						<div class="list-group list-group-flush">
							<button
								type="button"
								class="list-group-item list-group-item-action d-flex align-items-center gap-2"
								:class="{ active: selectedCategory === 'all' }"
								@click="selectCategory('all')"
							>
								<i class="ti ti-layout-grid"></i>
								<span class="flex-fill text-start">{{ t("All Reports") }}</span>
								<span class="badge bg-secondary-lt">{{ totalCount }}</span>
							</button>
							<button
								v-for="group in filteredGroups"
								:key="group.key"
								type="button"
								class="list-group-item list-group-item-action d-flex align-items-center gap-2"
								:class="{ active: selectedCategory === group.key }"
								@click="selectCategory(group.key)"
							>
								<i class="ti" :class="group.icon"></i>
								<span class="flex-fill text-start text-truncate">{{ group.label }}</span>
								<span class="badge bg-secondary-lt">{{ group.reports.length }}</span>
							</button>
						</div>
					</div>
				</div>

				<!-- Report sections -->
				<div class="col-12 col-lg-9">
					<div class="input-icon mb-3">
						<span class="input-icon-addon"><i class="ti ti-search"></i></span>
						<input
							v-model="search"
							type="search"
							class="form-control"
							:placeholder="t('Search reports')"
						/>
					</div>

					<div v-for="group in visibleGroups" :key="group.key" class="card mb-3">
						<div class="card-header py-2">
							<span class="avatar avatar-sm bg-blue-lt text-blue me-2">
								<i class="ti" :class="group.icon"></i>
							</span>
							<h3 class="card-title mb-0">{{ group.label }}</h3>
							<span v-if="!group.allowed" class="badge bg-secondary-lt ms-auto">
								{{ t("No access") }}
							</span>
						</div>
						<div class="list-group list-group-flush">
							<template v-for="report in group.reports" :key="report.path">
								<router-link
									v-if="group.allowed"
									:to="report.path"
									class="list-group-item list-group-item-action d-flex align-items-center gap-3"
								>
									<span class="avatar bg-blue-lt text-blue">
										<i class="ti" :class="report.icon"></i>
									</span>
									<div class="min-w-0 flex-fill">
										<div class="fw-medium text-truncate">{{ report.title }}</div>
										<div class="text-secondary small">{{ report.description }}</div>
									</div>
									<span class="badge bg-secondary-lt d-none d-md-inline">{{ report.badge }}</span>
									<i class="ti ti-chevron-right text-secondary"></i>
								</router-link>
								<div
									v-else
									class="list-group-item d-flex align-items-center gap-3 opacity-50"
								>
									<span class="avatar bg-secondary-lt text-secondary">
										<i class="ti" :class="report.icon"></i>
									</span>
									<div class="min-w-0 flex-fill">
										<div class="fw-medium text-truncate">{{ report.title }}</div>
										<div class="text-secondary small">{{ report.description }}</div>
									</div>
									<span class="badge bg-secondary-lt">{{ t("No access") }}</span>
								</div>
							</template>
						</div>
					</div>

					<div v-if="!visibleGroups.length" class="empty">
						<div class="empty-icon"><i class="ti ti-search"></i></div>
						<p class="empty-title">{{ t("No reports found") }}</p>
						<p class="empty-subtitle text-secondary">{{ t("Try another search term.") }}</p>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>

<style scoped>
@media (min-width: 992px) {
	.reports-category-rail {
		position: sticky;
		top: 1rem;
	}
}
</style>
