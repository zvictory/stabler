<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import { useToast } from "../../composables/useToast.js";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";
import Typeahead from "../../components/Typeahead.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import StatusBadge from "../../components/StatusBadge.vue";
import Pagination from "../../components/Pagination.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const toast = useToast();

const search = ref("");
const status = ref("");
const loading = ref(false);
const error = ref("");
const rows = ref([]);
const total = ref(0);
const limitStart = ref(0);
const pageLength = ref(25);

const costVisible = computed(() => session.costVisible === true);
const statusOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	...["Pending", "Booked", "In Transit", "Delivered", "Cancelled"].map((s) => ({ value: s, label: t(s) })),
]);

// --- Modal ---
const modalOpen = ref(false);
const saving = ref(false);
const form = ref(blankForm());

function blankForm() {
	return {
		name: null,
		modified: null,
		transporter: "",
		transporter_name: "",
		commercial_invoice: "",
		container: "",
		booking_date: "",
		booking_reference: "",
		status: "Pending",
		pickup_date: "",
		pickup_location: "Bandar Abbas, Iran",
		delivery_date: "",
		delivery_location: "Tashkent, Uzbekistan",
		route: "",
		vehicle_number: "",
		driver_name: "",
		driver_phone: "",
		amount: null,
		currency: "USD",
		allowed_transitions: [],
	};
}

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const res = await importsApi.listFreightBookings({
			company: activeCompany.value,
			search: search.value || undefined,
			status: status.value || undefined,
			limit_start: limitStart.value,
			limit_page_length: pageLength.value,
		});
		rows.value = res.rows || [];
		total.value = res.total_count || 0;
	} catch (err) {
		error.value = err?.message || t("Failed to load freight bookings.");
	} finally {
		loading.value = false;
	}
}

function reload() {
	if (limitStart.value !== 0) limitStart.value = 0;
	else load();
}

async function searchTransporters(q) {
	return call("stabler.api.purchasing.list_suppliers", { company: activeCompany.value, search: q || "", limit: 20 });
}
function pickTransporter(item) {
	form.value.transporter = item.name;
	form.value.transporter_name = item.supplier_name || item.name;
}

function openCreate() {
	form.value = blankForm();
	modalOpen.value = true;
}
async function openEdit(name) {
	try {
		const d = await importsApi.getFreightBooking(name);
		form.value = { ...blankForm(), ...d, transporter_name: d.transporter || "" };
		modalOpen.value = true;
	} catch (err) {
		toast.error(err?.message || t("Failed to load the booking."));
	}
}
function closeModal() {
	modalOpen.value = false;
}

function buildValues() {
	const v = {
		transporter: form.value.transporter || undefined,
		commercial_invoice: form.value.commercial_invoice || undefined,
		container: form.value.container || undefined,
		booking_date: form.value.booking_date || undefined,
		booking_reference: form.value.booking_reference,
		pickup_date: form.value.pickup_date || undefined,
		pickup_location: form.value.pickup_location,
		delivery_date: form.value.delivery_date || undefined,
		delivery_location: form.value.delivery_location,
		route: form.value.route,
		vehicle_number: form.value.vehicle_number,
		driver_name: form.value.driver_name,
		driver_phone: form.value.driver_phone,
		currency: form.value.currency,
	};
	if (costVisible.value && form.value.amount !== null && form.value.amount !== "") {
		v.amount = Number(form.value.amount);
	}
	return v;
}

async function save() {
	saving.value = true;
	try {
		if (form.value.name) {
			await importsApi.updateFreightBooking({ name: form.value.name, values: buildValues(), modified: form.value.modified });
			toast.success(t("Booking saved."));
			await openEdit(form.value.name);
		} else {
			const res = await importsApi.createFreightBooking({ company: activeCompany.value, values: buildValues() });
			toast.success(t("Booking created."));
			await openEdit(res.name);
		}
		await load();
	} catch (err) {
		toast.error(err?.message || t("Save failed."));
	} finally {
		saving.value = false;
	}
}

async function changeStatus(next) {
	let reason = null;
	if (!form.value.allowed_transitions.includes(next)) {
		reason = window.prompt(t("Reason for the status correction:"));
		if (!reason) return;
	}
	try {
		await importsApi.setFreightBookingStatus(form.value.name, next, reason);
		toast.success(t("Status updated."));
		await openEdit(form.value.name);
		await load();
	} catch (err) {
		toast.error(err?.message || t("Status change failed."));
	}
}

const masked = (v) => v === null || v === undefined;

onMounted(load);
watch(status, reload);
watch(limitStart, load);
watch(pageLength, reload);
watch(activeCompany, reload);
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('Booking, transporter or vehicle… ⌘K')"
			:count="total"
			:primary-label="t('New booking')"
			primary-icon="ti-plus"
			@search="reload"
			@primary-click="openCreate"
		>
			<template #filters>
				<Select v-model="status" size="sm" :options="statusOptions" style="width: 150px" />
			</template>
		</ListToolbar>

		<div v-if="error" class="card-body"><div class="alert alert-danger m-0">{{ error }}</div></div>
		<EmptyState
			v-else-if="!loading && !rows.length"
			icon="ti-truck-delivery"
			tone="purple"
			:title="t('No freight bookings')"
			:subtitle="t('Book cross-border land freight for a commercial invoice or container.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th class="text-nowrap">{{ t("Reference") }}</th>
						<th>{{ t("Transporter") }}</th>
						<th>{{ t("Commercial Invoice") }}</th>
						<th class="text-nowrap">{{ t("Delivery") }}</th>
						<th>{{ t("Vehicle") }}</th>
						<th class="text-end">{{ t("Amount") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="6" :cols="7" />
				<tbody v-else>
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openEdit(r.name)">
						<td class="font-monospace text-primary text-nowrap">{{ r.booking_reference || r.name }}</td>
						<td>{{ r.transporter || "—" }}</td>
						<td class="font-monospace small">{{ r.commercial_invoice || "—" }}</td>
						<td class="text-nowrap">{{ formatDate(r.delivery_date) }} · {{ r.delivery_location || "—" }}</td>
						<td class="font-monospace small">{{ r.vehicle_number || "—" }}</td>
						<td class="text-end font-monospace">
							<span v-if="masked(r.amount)" class="text-secondary">•••</span>
							<span v-else>{{ formatMoney(r.amount, r.currency, user.language) }}</span>
						</td>
						<td><StatusBadge doctype="Freight Booking" :status="r.status" /></td>
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

	<!-- Create/edit modal -->
	<div v-if="modalOpen" class="modal modal-blur fade show d-block" tabindex="-1">
		<div class="modal-dialog modal-lg modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">
						{{ form.name ? (form.booking_reference || form.name) : t("New booking") }}
						<StatusBadge v-if="form.name" class="ms-2" doctype="Freight Booking" :status="form.status" />
					</h5>
					<button type="button" class="btn-close" @click="closeModal"></button>
				</div>
				<div class="modal-body">
					<div class="alert alert-secondary py-2 small">{{ t("Set exactly one of Commercial Invoice or Container.") }}</div>
					<div class="row g-3">
						<div class="col-md-4">
							<label class="form-label">{{ t("Transporter") }}</label>
							<Typeahead v-slot="{ item }" v-model="form.transporter" :search="searchTransporters" :display="form.transporter_name" :placeholder="t('Search transporter…')" open-on-focus @pick="pickTransporter">
								<div class="fw-semibold">{{ item.supplier_name || item.name }}</div>
							</Typeahead>
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Commercial Invoice") }}</label>
							<input v-model="form.commercial_invoice" type="text" class="form-control font-monospace" />
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Container") }}</label>
							<input v-model="form.container" type="text" class="form-control font-monospace" />
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Booking reference") }}</label>
							<input v-model="form.booking_reference" type="text" class="form-control" />
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Booking date") }}</label>
							<DateInput v-model="form.booking_date" />
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Vehicle number") }}</label>
							<input v-model="form.vehicle_number" type="text" class="form-control" />
						</div>
						<div class="col-md-3">
							<label class="form-label">{{ t("Pickup date") }}</label>
							<DateInput v-model="form.pickup_date" />
						</div>
						<div class="col-md-3">
							<label class="form-label">{{ t("Pickup location") }}</label>
							<input v-model="form.pickup_location" type="text" class="form-control" />
						</div>
						<div class="col-md-3">
							<label class="form-label">{{ t("Delivery date") }}</label>
							<DateInput v-model="form.delivery_date" />
						</div>
						<div class="col-md-3">
							<label class="form-label">{{ t("Delivery location") }}</label>
							<input v-model="form.delivery_location" type="text" class="form-control" />
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Driver") }}</label>
							<input v-model="form.driver_name" type="text" class="form-control" />
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Driver phone") }}</label>
							<input v-model="form.driver_phone" type="text" class="form-control" />
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Currency") }}</label>
							<input v-model="form.currency" type="text" class="form-control" />
						</div>
						<div v-if="costVisible" class="col-md-4">
							<label class="form-label">{{ t("Amount") }}</label>
							<MoneyInput v-model="form.amount" :currency="form.currency" :language="user.language" size="sm" />
						</div>
						<div class="col-12">
							<label class="form-label">{{ t("Route") }}</label>
							<textarea v-model="form.route" class="form-control" rows="2"></textarea>
						</div>
					</div>

					<!-- Status transitions (existing bookings) -->
					<div v-if="form.name && form.allowed_transitions.length" class="mt-3 d-flex gap-2 flex-wrap">
						<span class="text-secondary small align-self-center">{{ t("Move to") }}:</span>
						<button
							v-for="ns in form.allowed_transitions.filter((s) => s !== 'Cancelled')"
							:key="ns"
							type="button"
							class="btn btn-outline-primary btn-sm"
							@click="changeStatus(ns)"
						>
							{{ t(ns) }}
						</button>
						<button
							v-if="form.allowed_transitions.includes('Cancelled')"
							type="button"
							class="btn btn-outline-danger btn-sm"
							@click="changeStatus('Cancelled')"
						>
							{{ t("Cancel booking") }}
						</button>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-outline-secondary" @click="closeModal">{{ t("Close") }}</button>
					<button type="button" class="btn btn-primary" :disabled="saving" @click="save">
						<i class="ti ti-device-floppy me-1"></i>{{ t("Save") }}
					</button>
				</div>
			</div>
		</div>
	</div>
	<div v-if="modalOpen" class="modal-backdrop fade show"></div>
</template>
