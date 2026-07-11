<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import StatusBadge from "../../components/StatusBadge.vue";
import EmptyState from "../../components/EmptyState.vue";
import { getDocstatusLabel } from "../../composables/status.js";

const session = useSession();
const { user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
// Branch on the route param, not on any create/isNew flag, so a direct URL load
// or refresh opens the ledger populated (record-form regression class).
const containerName = computed(() => String(route.params.name || ""));
useEscapeBack(null, "/imports/containers");

const loading = ref(false);
const error = ref("");
const data = ref(null);

const header = computed(() => data.value?.header || {});
const summary = computed(() => data.value?.summary || {});
const currency = computed(() => header.value.currency || "USD");
const costVisible = computed(() => data.value?.cost_visible === true);

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
function categoryLabel(c) {
	return CATEGORY_LABELS[c] || c;
}
function categoryClass(c) {
	return CATEGORY_CLASSES[c] || "bg-secondary-lt";
}

const masked = (v) => v === null || v === undefined;
function money(v, cur) {
	if (masked(v)) return "•••";
	return formatMoney(v, cur || currency.value, user.language);
}

async function load() {
	if (!containerName.value) return;
	loading.value = true;
	error.value = "";
	try {
		data.value = await importsApi.containerCostLedger(containerName.value);
	} catch (err) {
		error.value = err?.message || t("Failed to load the cost ledger.");
	} finally {
		loading.value = false;
	}
}

function openContainer() {
	router.push("/imports/containers/" + containerName.value);
}

onMounted(load);
watch(containerName, load);
</script>

<template>
	<div>
		<div class="d-flex align-items-center mb-3">
			<button type="button" class="btn btn-ghost-secondary btn-icon me-2" @click="router.push('/imports/containers')">
				<i class="ti ti-arrow-left"></i>
			</button>
			<div>
				<h2 class="page-title mb-0">{{ t("Container cost ledger") }}</h2>
				<div class="text-secondary small font-monospace">{{ header.container_number || containerName }}</div>
			</div>
			<div class="ms-auto">
				<button type="button" class="btn btn-outline-secondary" @click="openContainer">
					<i class="ti ti-box me-1"></i>{{ t("Open container") }}
				</button>
			</div>
		</div>

		<div v-if="error" class="alert alert-danger">{{ error }}</div>
		<div v-if="loading && !data" class="text-secondary">{{ t("Loading…") }}</div>

		<template v-if="data">
			<!-- Header card -->
			<div class="card mb-3">
				<div class="card-body">
					<dl class="row mb-0">
						<dt class="col-6 col-lg-2 text-secondary">{{ t("Commercial Invoice") }}</dt>
						<dd class="col-6 col-lg-2 font-monospace">{{ header.commercial_invoice || "—" }}</dd>
						<dt class="col-6 col-lg-2 text-secondary">{{ t("Supplier") }}</dt>
						<dd class="col-6 col-lg-2">{{ header.supplier_name || header.supplier || "—" }}</dd>
						<dt class="col-6 col-lg-2 text-secondary">{{ t("Status") }}</dt>
						<dd class="col-6 col-lg-2"><StatusBadge doctype="Import Container" :status="header.status" /></dd>
						<dt class="col-6 col-lg-2 text-secondary">{{ t("Total weight (kg)") }}</dt>
						<dd class="col-6 col-lg-2 font-monospace">{{ Number(header.total_kg || 0).toFixed(0) }}</dd>
						<dt class="col-6 col-lg-2 text-secondary">{{ t("Boxes") }}</dt>
						<dd class="col-6 col-lg-2 font-monospace">{{ header.total_boxes || 0 }}</dd>
					</dl>
				</div>
			</div>

			<!-- Summary strip -->
			<div class="row row-cards mb-3">
				<div class="col-6 col-lg">
					<div class="card"><div class="card-body p-2 text-center">
						<div class="text-secondary small">{{ t("Product cost") }}</div>
						<div class="h3 mb-0 font-monospace">{{ money(summary.product_cost) }}</div>
					</div></div>
				</div>
				<div class="col-6 col-lg">
					<div class="card"><div class="card-body p-2 text-center">
						<div class="text-secondary small">{{ t("Landed total") }}</div>
						<div class="h3 mb-0 font-monospace">{{ money(summary.landed_total) }}</div>
					</div></div>
				</div>
				<div class="col-6 col-lg">
					<div class="card"><div class="card-body p-2 text-center">
						<div class="text-secondary small">{{ t("Grand total") }}</div>
						<div class="h3 mb-0 font-monospace">{{ money(summary.grand_total) }}</div>
					</div></div>
				</div>
				<div class="col-6 col-lg">
					<div class="card"><div class="card-body p-2 text-center">
						<div class="text-secondary small">{{ t("Per kg") }}</div>
						<div class="h3 mb-0 font-monospace">{{ money(summary.per_kg) }}</div>
					</div></div>
				</div>
				<div class="col-6 col-lg">
					<div class="card"><div class="card-body p-2 text-center">
						<div class="text-secondary small">{{ t("Paid") }}</div>
						<div class="h3 mb-0 font-monospace text-green">{{ money(summary.paid) }}</div>
					</div></div>
				</div>
				<div class="col-6 col-lg">
					<div class="card"><div class="card-body p-2 text-center">
						<div class="text-secondary small">{{ t("Outstanding") }}</div>
						<div class="h3 mb-0 font-monospace" :class="!masked(summary.outstanding) && summary.outstanding > 0 ? 'text-red' : ''">{{ money(summary.outstanding) }}</div>
					</div></div>
				</div>
			</div>

			<div v-if="!costVisible" class="alert alert-secondary py-2 small">
				<i class="ti ti-lock me-1"></i>{{ t("Cost figures are hidden — ask an imports manager or accountant for landed-cost visibility.") }}
			</div>

			<div class="row row-cards">
				<!-- Cost lines -->
				<div class="col-lg-6">
					<div class="card mb-3">
						<div class="card-header"><h3 class="card-title">{{ t("Cost lines") }}</h3></div>
						<div class="table-responsive">
							<table class="table table-sm card-table">
								<thead>
									<tr>
										<th>{{ t("Component") }}</th>
										<th class="text-end">{{ t("Amount") }}</th>
										<th class="text-end">{{ t("UZS") }}</th>
										<th class="text-center">{{ t("Landed") }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="(cl, i) in data.cost_lines" :key="i">
										<td class="small">
											{{ cl.cost_component }}
											<span v-if="cl.consumed" class="badge bg-blue-lt ms-1" :title="cl.lcv_ref">{{ t("Vouchered") }}</span>
										</td>
										<td class="text-end font-monospace">{{ money(cl.amount, cl.currency) }}</td>
										<td class="text-end font-monospace">
											<span v-if="masked(cl.amount_uzs)" class="text-secondary">•••</span>
											<span v-else>{{ Number(cl.amount_uzs || 0).toFixed(0) }}</span>
										</td>
										<td class="text-center">
											<i v-if="cl.include_in_landed_cost" class="ti ti-check text-success"></i>
											<span v-else class="text-secondary">—</span>
										</td>
									</tr>
									<tr v-if="!data.cost_lines.length"><td colspan="4" class="text-secondary text-center py-2">{{ t("No cost lines.") }}</td></tr>
								</tbody>
							</table>
						</div>
					</div>
				</div>

				<!-- Bills -->
				<div class="col-lg-6">
					<div class="card mb-3">
						<div class="card-header"><h3 class="card-title">{{ t("Bills") }}</h3></div>
						<div class="table-responsive">
							<table class="table table-sm card-table">
								<thead>
									<tr>
										<th>{{ t("Bill") }}</th>
										<th>{{ t("Supplier") }}</th>
										<th>{{ t("Category") }}</th>
										<th class="text-end">{{ t("Total") }}</th>
										<th class="text-end">{{ t("Outstanding") }}</th>
										<th>{{ t("Status") }}</th>
										<th class="text-nowrap">{{ t("Due") }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="b in data.bills" :key="b.name" :class="b.overdue ? 'table-warning' : ''">
										<td class="font-monospace small">{{ b.name }}</td>
										<td class="small">{{ b.supplier_name }}</td>
										<td><span class="badge" :class="categoryClass(b.category)">{{ categoryLabel(b.category) }}</span></td>
										<td class="text-end font-monospace">{{ money(b.grand_total, b.currency) }}</td>
										<td class="text-end font-monospace" :class="!masked(b.outstanding_amount) && b.outstanding_amount > 0 ? 'text-red' : ''">{{ money(b.outstanding_amount, b.currency) }}</td>
										<td><StatusBadge doctype="Purchase Invoice" :status="b.status" /></td>
										<td class="text-nowrap small" :class="b.overdue ? 'text-red fw-bold' : ''">{{ formatDate(b.due_date) }}</td>
									</tr>
									<tr v-if="!data.bills.length"><td colspan="7" class="text-secondary text-center py-2">{{ t("No linked bills yet.") }}</td></tr>
								</tbody>
							</table>
						</div>
					</div>
				</div>

				<!-- Advances + LCVs -->
				<div class="col-lg-6">
					<div class="card mb-3">
						<div class="card-header"><h3 class="card-title">{{ t("Advance payments") }}</h3></div>
						<div class="table-responsive">
							<table class="table table-sm card-table">
								<thead>
									<tr>
										<th>{{ t("Payment") }}</th>
										<th class="text-nowrap">{{ t("Date") }}</th>
										<th class="text-center">{{ t("State") }}</th>
										<th class="text-end">{{ t("Paid") }}</th>
										<th class="text-end">{{ t("Unallocated") }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="a in data.advances" :key="a.name">
										<td class="font-monospace small">{{ a.name }}</td>
										<td class="text-nowrap small">{{ formatDate(a.posting_date) }}</td>
										<td class="text-center"><span class="badge" :class="a.docstatus === 1 ? 'bg-green-lt' : 'bg-yellow-lt'">{{ getDocstatusLabel(a.docstatus) }}</span></td>
										<td class="text-end font-monospace">{{ money(a.paid_amount) }}</td>
										<td class="text-end font-monospace">{{ money(a.unallocated_amount) }}</td>
									</tr>
									<tr v-if="!data.advances.length"><td colspan="5" class="text-secondary text-center py-2">{{ t("No advance payments yet.") }}</td></tr>
								</tbody>
							</table>
						</div>
					</div>
				</div>

				<div class="col-lg-6">
					<div class="card mb-3">
						<div class="card-header"><h3 class="card-title">{{ t("Landed cost vouchers") }}</h3></div>
						<div class="table-responsive">
							<table class="table table-sm card-table">
								<thead>
									<tr>
										<th>{{ t("LCV") }}</th>
										<th>{{ t("Note") }}</th>
										<th class="text-center">{{ t("State") }}</th>
										<th class="text-end">{{ t("Total") }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="lc in data.landed_cost_vouchers" :key="lc.lcv">
										<td class="font-monospace small">{{ lc.lcv }}</td>
										<td class="small">{{ lc.note || "—" }}</td>
										<td class="text-center"><span class="badge" :class="lc.docstatus === 1 ? 'bg-green-lt' : 'bg-yellow-lt'">{{ getDocstatusLabel(lc.docstatus) }}</span></td>
										<td class="text-end font-monospace">{{ lc.total !== null ? Number(lc.total || 0).toFixed(0) : "—" }}</td>
									</tr>
									<tr v-if="!data.landed_cost_vouchers.length"><td colspan="4" class="text-secondary text-center py-2">{{ t("No vouchers yet.") }}</td></tr>
								</tbody>
							</table>
						</div>
					</div>
				</div>
			</div>

			<EmptyState
				v-if="!data.cost_lines.length && !data.bills.length && !data.advances.length"
				icon="ti-receipt-off"
				tone="secondary"
				compact
				:title="t('Nothing booked yet')"
				:subtitle="t('No cost lines, bills or advances are linked to this container.')"
			/>
		</template>
	</div>
</template>
