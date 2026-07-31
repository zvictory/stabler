<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatMoney } from "../../composables/money.js";
import { useToast } from "../../composables/useToast.js";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import Pagination from "../../components/Pagination.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const toast = useToast();

const search = ref("");
const selectedTransporter = ref("");
const loading = ref(false);
const error = ref("");

const rows = ref([]);
// One entry per currency — the endpoint groups by it rather than summing across.
const summary = ref([]);
const transporters = ref([]);
// 0-based offset, like every other imports list — that is the model `Pagination`
// binds. The endpoint counts in pages, so `load()` converts at the call.
const limitStart = ref(0);
const pageLength = ref(25);
const totalCount = ref(0);

const costVisible = computed(() => session.costVisible === true);

// Masked money comes back as null (the three Freight Booking figures are
// permlevel 1). formatMoney would render that as 0,00 — a number the user would
// read as "nothing owed" rather than "not yours to see".
function money(value, currency) {
	if (value === null || value === undefined) return "—";
	return formatMoney(value, currency || "USD", user.value?.language);
}

const transporterOptions = computed(() => [
	{ value: "", label: t("All Transporters") },
	...transporters.value.map((tr) => ({
		value: tr.name,
		label: tr.supplier_name || tr.name,
	})),
]);

// Edit Modal
const editModalOpen = ref(false);
const saving = ref(false);
const editForm = ref({
	name: "",
	ci_number: "",
	container: "",
	transporter: "",
	transport_cost: 0,
	paid_cash: 0,
	paid_bank: 0,
	currency: "USD",
	notes: "",
});

// Search, transporter and page all fire `load()` from one watcher, so two calls
// are routinely in flight; without the token a slow first response overwrites a
// fast second and the table stops matching the filters.
let reqToken = 0;

async function load() {
	if (!activeCompany.value) return;
	const token = ++reqToken;
	loading.value = true;
	error.value = "";
	try {
		const res = await call("stabler.api.imports.transporter_dashboard", {
			company: activeCompany.value,
			search: search.value || undefined,
			transporter: selectedTransporter.value || undefined,
			page: Math.floor(limitStart.value / pageLength.value) + 1,
			page_length: pageLength.value,
		});
		if (token !== reqToken) return;

		summary.value = res.summary || [];
		rows.value = res.rows || [];
		transporters.value = res.transporters || [];
		totalCount.value = res.total_count || 0;
	} catch (err) {
		if (token !== reqToken) return;
		error.value = err?.message || t("Failed to load transporter dashboard.");
	} finally {
		if (token === reqToken) loading.value = false;
	}
}

function reload() {
	if (limitStart.value !== 0) limitStart.value = 0;
	else load();
}

function openEdit(r) {
	editForm.value = {
		name: r.name,
		ci_number: r.ci_number || r.commercial_invoice,
		container: r.container || r.vehicle_number,
		transporter: r.transporter,
		transport_cost: r.transport_cost,
		paid_cash: r.paid_cash,
		paid_bank: r.paid_bank,
		currency: r.currency || "USD",
		notes: r.notes || "",
	};
	editModalOpen.value = true;
}

async function saveEdit() {
	if (!editForm.value.name) return;
	saving.value = true;
	try {
		await call("stabler.api.imports.save_container_transport_cost", {
			company: activeCompany.value,
			name: editForm.value.name,
			transporter: editForm.value.transporter || undefined,
			transport_cost: editForm.value.transport_cost,
			currency: editForm.value.currency,
			paid_cash: editForm.value.paid_cash,
			paid_bank: editForm.value.paid_bank,
			notes: editForm.value.notes,
		});
		toast.success(t("Transport details updated successfully."));
		editModalOpen.value = false;
		load();
	} catch (err) {
		toast.error(err?.message || t("Failed to save transport cost."));
	} finally {
		saving.value = false;
	}
}

// `search` is deliberately NOT watched: ListToolbar updates the model on every
// keystroke and debounces only its `search` event, so watching the ref would fire
// one request per character. The template binds that event to reload() instead.
// Filters reset to page 1 — changing a filter while on page 3 would otherwise
// land on an empty page of a shorter result set.
watch(limitStart, () => load());
// A page-size change while on page 3 would ask for an offset the shorter paging
// no longer has; reload() rewinds to the first page.
watch(pageLength, () => reload());
watch([activeCompany, selectedTransporter], () => reload());
onMounted(() => load());
</script>

<template>
	<div class="page-body py-3">
		<div class="container-xl">
			<!-- Page Title & Header -->
			<div class="d-flex align-items-center justify-content-between mb-3">
				<div>
					<h2 class="page-title">{{ t("Transport operations desk") }}</h2>
					<div class="text-secondary small">
						{{ t("CI, transporter, truck/container, freight cost and cash/bank payments") }}
					</div>
				</div>
				<button class="btn btn-outline-secondary" :disabled="loading" @click="reload">
					<i class="ti ti-refresh me-1" :class="{ 'spin-icon': loading }"></i>
					{{ t("Refresh") }}
				</button>
			</div>

			<!-- Summary Cards — one row per currency. Freight is booked in whatever
			     currency the transporter invoices in; a single blended total would
			     be a number that is true in no currency at all. -->
			<div v-for="s in summary" :key="s.currency" class="row row-cards mb-3">
				<div class="col-sm-6 col-lg-3">
					<div class="card card-sm border-0 shadow-sm rounded-3">
						<div class="card-body">
							<div class="row align-items-center">
								<div class="col-auto">
									<span class="bg-primary text-white avatar">
										<i class="ti ti-truck-delivery fs-2"></i>
									</span>
								</div>
								<div class="col">
									<div class="font-weight-medium text-secondary text-uppercase small">
										{{ t("Total Freight Cost") }} · {{ s.currency }}
									</div>
									<div class="h3 mb-0 font-monospace stbl-amount">
										{{ money(s.total_freight_cost, s.currency) }}
									</div>
								</div>
							</div>
						</div>
					</div>
				</div>

				<div class="col-sm-6 col-lg-3">
					<div class="card card-sm border-0 shadow-sm rounded-3">
						<div class="card-body">
							<div class="row align-items-center">
								<div class="col-auto">
									<span class="bg-teal text-white avatar">
										<i class="ti ti-cash fs-2"></i>
									</span>
								</div>
								<div class="col">
									<div class="font-weight-medium text-secondary text-uppercase small">{{ t("Paid Cash (Kassa)") }}</div>
									<div class="h3 mb-0 font-monospace stbl-amount text-teal">
										{{ money(s.total_paid_cash, s.currency) }}
									</div>
								</div>
							</div>
						</div>
					</div>
				</div>

				<div class="col-sm-6 col-lg-3">
					<div class="card card-sm border-0 shadow-sm rounded-3">
						<div class="card-body">
							<div class="row align-items-center">
								<div class="col-auto">
									<span class="bg-azure text-white avatar">
										<i class="ti ti-building-bank fs-2"></i>
									</span>
								</div>
								<div class="col">
									<div class="font-weight-medium text-secondary text-uppercase small">{{ t("Paid Bank (Transfer)") }}</div>
									<div class="h3 mb-0 font-monospace stbl-amount text-azure">
										{{ money(s.total_paid_bank, s.currency) }}
									</div>
								</div>
							</div>
						</div>
					</div>
				</div>

				<div class="col-sm-6 col-lg-3">
					<div class="card card-sm border-0 shadow-sm rounded-3">
						<div class="card-body">
							<div class="row align-items-center">
								<div class="col-auto">
									<span class="bg-danger text-white avatar">
										<i class="ti ti-scale fs-2"></i>
									</span>
								</div>
								<div class="col">
									<div class="font-weight-medium text-secondary text-uppercase small">{{ t("Outstanding Balance") }}</div>
									<div class="h3 mb-0 font-monospace stbl-amount text-danger">
										{{ money(s.total_outstanding, s.currency) }}
									</div>
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>

			<!-- Data Table -->
			<div class="card border-0 shadow-sm rounded-3">
				<ListToolbar
					v-model="search"
					:placeholder="t('CI, transporter, container or vehicle… ⌘K')"
					:count="totalCount"
					@search="reload"
				>
					<template #filters>
						<Select
							v-model="selectedTransporter"
							:options="transporterOptions"
							style="min-width: 220px"
						/>
					</template>
				</ListToolbar>

				<div v-if="error" class="card-body"><div class="alert alert-danger m-0">{{ error }}</div></div>

				<div class="table-responsive">
					<table class="table table-vcenter card-table align-middle">
						<thead>
							<tr>
								<th>{{ t("CI No") }}</th>
								<th>{{ t("Transporter Vendor") }}</th>
								<th>{{ t("Container / Truck #") }}</th>
								<th class="text-end">{{ t("Transport Cost") }}</th>
								<th class="text-end">{{ t("Paid Cash") }}</th>
								<th class="text-end">{{ t("Paid Bank") }}</th>
								<th class="text-end">{{ t("Balance Due") }}</th>
								<th class="text-center">{{ t("Actions") }}</th>
							</tr>
						</thead>

						<tbody v-if="loading">
							<SkeletonRows :cols="8" :rows="5" />
						</tbody>

						<tbody v-else-if="rows.length === 0">
							<tr>
								<td colspan="8">
									<EmptyState
										:title="t('No transport records found')"
										:subtitle="t('No containers or freight bookings match your filter criteria.')"
										icon="ti ti-truck-off"
									/>
								</td>
							</tr>
						</tbody>

						<tbody v-else>
							<tr v-for="r in rows" :key="r.name">
								<td>
									<span class="fw-bold font-monospace">{{ r.ci_number || "—" }}</span>
								</td>
								<td>
									<div class="fw-semibold text-dark">{{ r.transporter_name || "—" }}</div>
									<div v-if="r.transporter && r.transporter !== r.transporter_name" class="small text-secondary font-monospace">{{ r.transporter }}</div>
								</td>
								<td>
									<div class="font-monospace text-body">{{ r.container || r.vehicle_number || "—" }}</div>
									<div v-if="r.vehicle_number && r.container" class="small text-secondary font-monospace">{{ r.vehicle_number }}</div>
								</td>
								<td class="text-end font-monospace fw-bold text-dark stbl-amount">
									{{ money(r.transport_cost, r.currency) }}
								</td>
								<td class="text-end font-monospace text-teal stbl-amount">
									{{ money(r.paid_cash, r.currency) }}
								</td>
								<td class="text-end font-monospace text-azure stbl-amount">
									{{ money(r.paid_bank, r.currency) }}
								</td>
								<td class="text-end font-monospace fw-bold stbl-amount" :class="r.balance > 0 ? 'text-danger' : 'text-success'">
									{{ money(r.balance, r.currency) }}
								</td>
								<td class="text-center">
									<!-- The endpoint refuses this write without the cost gate, so an
									     always-visible Edit would only ever open a form that throws
									     on save with figures rendered as "—". -->
									<button v-if="costVisible" class="btn btn-sm btn-ghost-secondary" @click="openEdit(r)">
										<i class="ti ti-edit me-1"></i> {{ t("Edit") }}
									</button>
								</td>
							</tr>
						</tbody>
					</table>
				</div>

				<Pagination
					v-if="!error && totalCount > 0"
					v-model:limit-start="limitStart"
					v-model:page-length="pageLength"
					:total="totalCount"
					:page-count="rows.length"
				/>
			</div>
		</div>

		<!-- Edit Modal -->
		<div v-if="editModalOpen" class="modal modal-blur fade show d-block" tabindex="-1" style="background: rgba(0,0,0,0.5)">
			<div class="modal-dialog modal-dialog-centered">
				<div class="modal-content rounded-3 shadow">
					<div class="modal-header">
						<h5 class="modal-title">{{ t("Edit Transport & Payment Details") }}</h5>
						<button type="button" class="btn-close" @click="editModalOpen = false"></button>
					</div>

					<div class="modal-body">
						<div class="mb-3">
							<label class="form-label required">{{ t("Transporter Vendor") }}</label>
							<Select
								v-model="editForm.transporter"
								:options="transporterOptions"
								class="w-100"
							/>
						</div>

						<div class="mb-3">
							<label class="form-label required">{{ t("Agreed Transport Cost") }}</label>
							<MoneyInput
								v-model="editForm.transport_cost"
								:currency="editForm.currency"
							/>
						</div>

						<div class="row g-2 mb-3">
							<div class="col-md-6">
								<label class="form-label">{{ t("Paid Cash (Kassa)") }}</label>
								<MoneyInput
									v-model="editForm.paid_cash"
									:currency="editForm.currency"
								/>
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Paid Bank (Transfer)") }}</label>
								<MoneyInput
									v-model="editForm.paid_bank"
									:currency="editForm.currency"
								/>
							</div>
						</div>

						<div class="mb-3">
							<label class="form-label">{{ t("Notes") }}</label>
							<textarea v-model="editForm.notes" class="form-control" rows="2" :placeholder="t('Add delivery notes or remarks…')"></textarea>
						</div>
					</div>

					<div class="modal-footer">
						<button type="button" class="btn btn-link link-secondary me-auto" @click="editModalOpen = false">{{ t("Cancel") }}</button>
						<button type="button" class="btn btn-primary" :disabled="saving" @click="saveEdit">
							<i class="ti ti-check me-1"></i> {{ t("Save Details") }}
						</button>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>

<style scoped>
.spin-icon {
	animation: spin 1s infinite linear;
}
@keyframes spin {
	from { transform: rotate(0deg); }
	to { transform: rotate(360deg); }
}
</style>
