<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import KpiCard from "../../components/KpiCard.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();

const loading = ref(false);
const error = ref("");
const kpi = ref(null);

// The 9 logistics statuses, in pipeline order, for the mini-board chips.
const PIPELINE = [
	"BOOKED",
	"STUFFED",
	"GATE_IN",
	"ON_BOARD",
	"IN_TRANSIT",
	"DISCHARGED",
	"AVAILABLE",
	"ARRIVED_AT_IRAN",
	"DELIVERED_TO_UZBEKISTAN",
];

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		kpi.value = await importsApi.home(activeCompany.value);
	} catch (err) {
		error.value = err?.message || t("Failed to load the imports dashboard.");
	} finally {
		loading.value = false;
	}
}

function daysBadge(days) {
	if (days === null || days === undefined) return "bg-secondary-lt";
	if (days <= 3) return "bg-red-lt";
	if (days <= 7) return "bg-yellow-lt";
	return "bg-green-lt";
}

function openCi(name) {
	router.push("/imports/commercial-invoices/" + name);
}

function openCiList(status) {
	router.push({ path: "/imports/commercial-invoices", query: status ? { status } : {} });
}

function openGrnVariance() {
	router.push({ path: "/imports/grn-checklists", query: { variance: "CRITICAL" } });
}
function openVetQueue() {
	router.push("/imports/vet-certificates");
}
function openCustomsQueue() {
	router.push({ path: "/imports/customs", query: { status: "Submitted" } });
}
function openBills() {
	router.push("/imports/bills");
}
function openOrders(status) {
	router.push({ path: "/imports/orders", query: status ? { status } : {} });
}

// Pending landed-cost bills KPI sub-label: outstanding is masked (null) for
// users lacking cost visibility → show the neutral bullet placeholder.
const pendingBillsHint = computed(() => {
	if (!kpi.value) return "";
	const o = kpi.value.pending_bills_outstanding;
	if (o === null || o === undefined) return t("•••");
	return t("{amount} outstanding", { amount: formatMoney(o, "", user.value.language) });
});

onMounted(load);
watch(activeCompany, load);
</script>

<template>
	<div>
		<div v-if="error" class="alert alert-danger">{{ error }}</div>

		<!-- KPI cards -->
		<div class="row row-cards mb-3">
			<div class="col-sm-6 col-lg">
				<KpiCard
					:label="t('Open commercial invoices')"
					:value="String(kpi ? kpi.open_ci_count : 0)"
					icon="ti-file-invoice"
					tone="primary"
					:loading="loading"
				/>
			</div>
			<div class="col-sm-6 col-lg">
				<KpiCard
					:label="t('Containers in transit')"
					:value="String(kpi ? (kpi.containers_by_status.IN_TRANSIT || 0) : 0)"
					icon="ti-box"
					tone="info"
					:loading="loading"
				/>
			</div>
			<div class="col-sm-6 col-lg">
				<KpiCard
					:label="t('Trucks on the road')"
					:value="String(kpi ? kpi.trucks_in_transit : 0)"
					icon="ti-truck"
					tone="purple"
					:loading="loading"
				/>
			</div>
			<div class="col-sm-6 col-lg" style="cursor: pointer" @click="openGrnVariance">
				<KpiCard
					:label="t('GRNs with variance')"
					:value="String(kpi ? kpi.grns_variance : 0)"
					icon="ti-alert-triangle"
					:tone="kpi && kpi.grns_variance ? 'danger' : 'secondary'"
					:loading="loading"
				/>
			</div>
			<div class="col-sm-6 col-lg">
				<KpiCard
					:label="t('Payments due ≤7 days')"
					:value="String(kpi ? kpi.payments_due_count : 0)"
					icon="ti-cash"
					:tone="kpi && kpi.payments_due_count ? 'warning' : 'secondary'"
					:loading="loading"
				/>
			</div>
			<div class="col-sm-6 col-lg" style="cursor: pointer" @click="openBills">
				<KpiCard
					:label="t('Pending landed-cost bills')"
					:value="String(kpi ? kpi.pending_bills_count : 0)"
					:hint="pendingBillsHint"
					icon="ti-file-dollar"
					:tone="kpi && kpi.pending_bills_count ? 'danger' : 'secondary'"
					:loading="loading"
				/>
			</div>
		</div>

		<div class="row row-cards">
			<!-- Payments due -->
			<div class="col-lg-7">
				<div class="card">
					<div class="card-header">
						<h3 class="card-title">{{ t("Payments due") }}</h3>
						<div class="card-subtitle">{{ t("70% balance due 7 days before Iran arrival") }}</div>
					</div>
					<div class="table-responsive">
						<table class="table table-vcenter card-table">
							<thead>
								<tr>
									<th>{{ t("Commercial Invoice") }}</th>
									<th>{{ t("Supplier") }}</th>
									<th class="text-nowrap">{{ t("Transit ETA") }}</th>
									<th class="text-end">{{ t("Days left") }}</th>
								</tr>
							</thead>
							<SkeletonRows v-if="loading" :rows="4" :cols="4" />
							<tbody v-else-if="kpi && kpi.payments_due.length">
								<tr
									v-for="r in kpi.payments_due"
									:key="r.name"
									style="cursor: pointer"
									@click="openCi(r.name)"
								>
									<td class="font-monospace text-primary text-nowrap">{{ r.ci_number || r.name }}</td>
									<td>{{ r.supplier_name }}</td>
									<td class="text-nowrap">{{ formatDate(r.eta_transit_port) }}</td>
									<td class="text-end">
										<span class="badge" :class="daysBadge(r.days_left)">
											{{ r.days_left === null ? "—" : r.days_left }}
										</span>
									</td>
								</tr>
							</tbody>
						</table>
					</div>
					<EmptyState
						v-if="!loading && kpi && !kpi.payments_due.length"
						icon="ti-cash"
						tone="success"
						:title="t('No payments due')"
						:subtitle="t('No commercial invoices reach their transit ETA in the next 7 days.')"
					/>
				</div>
			</div>

			<!-- Pipeline mini-board -->
			<div class="col-lg-5">
				<div class="card">
					<div class="card-header">
						<h3 class="card-title">{{ t("Pipeline") }}</h3>
					</div>
					<div class="card-body">
						<div class="d-flex flex-wrap gap-2">
							<button
								v-for="s in PIPELINE"
								:key="s"
								type="button"
								class="btn btn-outline-secondary btn-sm d-flex align-items-center gap-2"
								@click="openCiList(s)"
							>
								<span>{{ t(s) }}</span>
								<span class="badge bg-secondary-lt font-monospace">{{ kpi ? (kpi.ci_by_status[s] || 0) : 0 }}</span>
							</button>
						</div>
						<button type="button" class="btn btn-link p-0 hr-text w-100 text-decoration-none" @click="openOrders()">{{ t("Import orders") }}</button>
						<button type="button" class="btn btn-link p-0 d-flex justify-content-between small w-100 text-decoration-none" @click="openOrders('ADVANCE_PAID')">
							<span class="text-secondary">{{ t("Orders with advance") }}</span>
							<strong class="font-monospace">{{ kpi ? kpi.import_orders_count : 0 }}</strong>
						</button>
						<div class="d-flex justify-content-between small mt-1">
							<span class="text-secondary">{{ t("Advance paid") }}</span>
							<strong class="font-monospace">
								{{ formatMoney(kpi ? kpi.advance_paid_total : 0, "", user.language) }}
							</strong>
						</div>
						<button type="button" class="btn btn-link p-0 d-flex justify-content-between small mt-1 w-100 text-decoration-none" @click="openVetQueue">
							<span class="text-secondary">{{ t("Pending vet certificates") }}</span>
							<strong class="font-monospace" :class="kpi && kpi.pending_vet_certs ? 'text-warning' : ''">{{ kpi ? kpi.pending_vet_certs : 0 }}</strong>
						</button>
						<button type="button" class="btn btn-link p-0 d-flex justify-content-between small mt-1 w-100 text-decoration-none" @click="openCustomsQueue">
							<span class="text-secondary">{{ t("Customs declarations pending") }}</span>
							<strong class="font-monospace" :class="kpi && kpi.gtds_pending ? 'text-warning' : ''">{{ kpi ? kpi.gtds_pending : 0 }}</strong>
						</button>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
