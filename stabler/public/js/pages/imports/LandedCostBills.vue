<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";
import StatusBadge from "../../components/StatusBadge.vue";
import Pagination from "../../components/Pagination.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();

const search = ref("");
const supplierFilter = ref("");
const status = ref(String(route.query.status || "").trim());
const ciFilter = ref("");
const loading = ref(false);
const error = ref("");
const rows = ref([]);
const total = ref(0);
const limitStart = ref(0);
const pageLength = ref(25);

const summaryOpen = ref(false);
const summaryLoading = ref(false);
const summaryRows = ref([]);
const summaryVisible = ref(true);

const PI_STATUSES = ["Draft", "Unpaid", "Partly Paid", "Paid", "Overdue", "Return", "Credit Note Issued"];
const statusOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	...PI_STATUSES.map((s) => ({ value: s, label: t(s) })),
]);

const CATEGORY_LABELS = {
	product: t("Product"),
	transport: t("Transport"),
	expense: t("Expense"),
	freight: t("Freight"),
};
const CATEGORY_CLASSES = {
	product: "bg-green-lt",
	transport: "bg-purple-lt",
	expense: "bg-orange-lt",
	freight: "bg-blue-lt",
};
const categoryLabel = (c) => CATEGORY_LABELS[c] || c;
const categoryClass = (c) => CATEGORY_CLASSES[c] || "bg-secondary-lt";

const masked = (v) => v === null || v === undefined;
const money = (v, cur) => (masked(v) ? "•••" : formatMoney(v, cur || "USD", user.language));

function refChips(r) {
	const chips = [];
	if (r.custom_import_container) chips.push({ icon: "ti-box", label: r.custom_import_container });
	if (r.custom_commercial_invoice) chips.push({ icon: "ti-file-invoice", label: r.custom_commercial_invoice });
	if (r.custom_import_truck) chips.push({ icon: "ti-truck", label: r.custom_import_truck });
	if (r.custom_import_expense) chips.push({ icon: "ti-receipt", label: r.custom_import_expense });
	return chips;
}

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const res = await importsApi.listLandedCostBills({
			company: activeCompany.value,
			supplier: supplierFilter.value || undefined,
			status: status.value || undefined,
			commercial_invoice: ciFilter.value || undefined,
			limit_start: limitStart.value,
			limit_page_length: pageLength.value,
		});
		rows.value = res.rows || [];
		total.value = res.total_count || 0;
	} catch (err) {
		error.value = err?.message || t("Failed to load bills.");
	} finally {
		loading.value = false;
	}
}

function reload() {
	if (limitStart.value !== 0) limitStart.value = 0;
	else load();
}

async function toggleSummary() {
	summaryOpen.value = !summaryOpen.value;
	if (summaryOpen.value && !summaryRows.value.length) {
		summaryLoading.value = true;
		try {
			const res = await importsApi.supplierLandedCostSummary(activeCompany.value);
			summaryRows.value = res.rows || [];
			summaryVisible.value = res.cost_visible !== false;
		} catch (err) {
			error.value = err?.message || t("Failed to load the supplier summary.");
		} finally {
			summaryLoading.value = false;
		}
	}
}

function openContainerLedger(name) {
	if (name) router.push("/imports/containers/" + name + "/ledger");
}

onMounted(load);
watch([status, supplierFilter, ciFilter], reload);
watch(limitStart, load);
watch(pageLength, reload);
watch(activeCompany, () => {
	summaryRows.value = [];
	reload();
});
</script>

<template>
	<div>
		<div class="card mb-3">
			<ListToolbar
				v-model="search"
				:placeholder="t('Bill or supplier… ⌘K')"
				:count="total"
				@search="() => { supplierFilter = search; reload(); }"
			>
				<template #filters>
					<div class="d-flex align-items-center gap-2">
						<Select v-model="status" size="sm" :options="statusOptions" style="width: 170px" />
						<input v-model="ciFilter" type="search" class="form-control form-control-sm" :placeholder="t('Commercial Invoice')" style="width: 170px" />
						<button type="button" class="btn btn-outline-secondary btn-sm" @click="toggleSummary">
							<i class="ti" :class="summaryOpen ? 'ti-chevron-up' : 'ti-users'"></i>
							<span class="ms-1">{{ t("By supplier") }}</span>
						</button>
					</div>
				</template>
			</ListToolbar>

			<!-- Collapsible supplier summary -->
			<div v-if="summaryOpen" class="border-top">
				<div v-if="summaryLoading" class="card-body text-secondary">{{ t("Loading…") }}</div>
				<div v-else class="table-responsive">
					<table class="table table-sm card-table">
						<thead>
							<tr>
								<th>{{ t("Supplier") }}</th>
								<th class="text-end">{{ t("Bills") }}</th>
								<th class="text-end">{{ t("Total") }}</th>
								<th class="text-end">{{ t("Outstanding") }}</th>
								<th class="text-end">{{ t("Overdue") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="s in summaryRows" :key="s.supplier">
								<td>{{ s.supplier_name }}</td>
								<td class="text-end font-monospace">{{ s.bill_count }}</td>
								<td class="text-end font-monospace">{{ money(s.total) }}</td>
								<td class="text-end font-monospace" :class="!masked(s.outstanding) && s.outstanding > 0 ? 'text-red' : ''">{{ money(s.outstanding) }}</td>
								<td class="text-end">
									<span v-if="s.overdue_count" class="badge bg-red-lt font-monospace">{{ s.overdue_count }}</span>
									<span v-else class="text-secondary">—</span>
								</td>
							</tr>
							<tr v-if="!summaryRows.length"><td colspan="5" class="text-secondary text-center py-2">{{ t("No import bills yet.") }}</td></tr>
						</tbody>
					</table>
				</div>
			</div>
		</div>

		<div class="card">
			<div v-if="error" class="card-body"><div class="alert alert-danger m-0">{{ error }}</div></div>
			<EmptyState
				v-else-if="!loading && !rows.length"
				icon="ti-receipt-off"
				tone="info"
				:title="t('No landed-cost bills')"
				:subtitle="t('No purchase invoices are linked to an import container, invoice or truck yet.')"
			/>
			<div v-else class="table-responsive">
				<table class="table table-vcenter card-table table-hover">
					<thead>
						<tr>
							<th class="text-nowrap">{{ t("Bill") }}</th>
							<th>{{ t("Supplier") }}</th>
							<th>{{ t("References") }}</th>
							<th>{{ t("Category") }}</th>
							<th class="text-end">{{ t("Total") }}</th>
							<th class="text-end">{{ t("Outstanding") }}</th>
							<th>{{ t("Status") }}</th>
							<th class="text-nowrap">{{ t("Due") }}</th>
						</tr>
					</thead>
					<SkeletonRows v-if="loading" :rows="6" :cols="8" />
					<tbody v-else>
						<tr
							v-for="r in rows"
							:key="r.name"
							:class="r.overdue ? 'table-warning' : ''"
							style="cursor: pointer"
							@click="openContainerLedger(r.custom_import_container)"
						>
							<td class="font-monospace small text-nowrap">{{ r.name }}</td>
							<td>{{ r.supplier_name }}</td>
							<td>
								<span v-for="(chip, i) in refChips(r)" :key="i" class="badge bg-secondary-lt me-1 font-monospace" :title="chip.label">
									<i class="ti" :class="chip.icon"></i>
								</span>
							</td>
							<td><span class="badge" :class="categoryClass(r.category)">{{ categoryLabel(r.category) }}</span></td>
							<td class="text-end font-monospace">{{ money(r.grand_total, r.currency) }}</td>
							<td class="text-end font-monospace" :class="!masked(r.outstanding_amount) && r.outstanding_amount > 0 ? 'text-red' : ''">{{ money(r.outstanding_amount, r.currency) }}</td>
							<td><StatusBadge doctype="Purchase Invoice" :status="r.status" /></td>
							<td class="text-nowrap small" :class="r.overdue ? 'text-red fw-bold' : ''">{{ formatDate(r.due_date) }}</td>
						</tr>
					</tbody>
				</table>
			</div>
			<Pagination
				v-if="!error && total > 0"
				v-model:limit-start="limitStart"
				v-model:page-length="pageLength"
				:total="total"
				:page-count="rows.length"
			/>
		</div>
	</div>
</template>
