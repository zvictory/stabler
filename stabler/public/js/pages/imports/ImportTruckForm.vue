<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import Typeahead from "../../components/Typeahead.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import StatusBadge from "../../components/StatusBadge.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();
const { confirm } = useConfirm();
useEscapeBack(null, "/imports/trucks");

const docName = computed(() => (route.params.name ? String(route.params.name) : null));
const isCreate = computed(() => !docName.value);

const loading = ref(false);
const saving = ref(false);
const error = ref("");
const form = ref(blankForm());

const costVisible = computed(() =>
	isCreate.value ? session.costVisible === true : form.value.cost_visible === true
);
const canRollback = computed(() =>
	(session.roles || []).some((r) => ["Imports Manager", "System Manager", "Stabler Admin"].includes(r))
);

const currencies = ref([]);
const currencyOptions = computed(() => currencies.value.map((c) => ({ value: c.name, label: c.name })));
const payStatusOptions = [
	{ value: "Unpaid", label: t("Unpaid") },
	{ value: "Partially Paid", label: t("Partially Paid") },
	{ value: "Paid", label: t("Paid") },
];

const PIPELINE = [
	"PENDING", "DEPARTED_IRAN", "AT_BORDER", "CROSSED_BORDER", "IN_TRANSIT",
	"ARRIVED", "UNLOADING", "GRN_CREATED", "COMPLETED",
];
const rollbackTarget = computed(() => {
	const idx = PIPELINE.indexOf(form.value.status);
	return idx > 0 ? PIPELINE[idx - 1] : null;
});

function blankForm() {
	return {
		name: null,
		modified: null,
		cost_visible: false,
		truck_number: "",
		commercial_invoice: "",
		trucking_company: "",
		trucking_company_name: "",
		driver_name: "",
		driver_phone: "",
		destination_warehouse: "",
		status: "PENDING",
		departure_date: "",
		border_crossing_date: "",
		estimated_arrival: "",
		actual_arrival: "",
		target_temp_min: -22,
		target_temp_max: -18,
		total_boxes: 0,
		total_kg: 0,
		transport_cost: null,
		transport_currency: "USD",
		transport_payment_status: "Unpaid",
		transport_purchase_invoice: null,
		allowed_transitions: [],
	};
}

async function searchSuppliers(q) {
	return call("stabler.api.purchasing.list_suppliers", { company: activeCompany.value, search: q || "", limit: 20 });
}
function pickCarrier(item) {
	form.value.trucking_company = item.name;
	form.value.trucking_company_name = item.supplier_name || item.name;
}
const warehouses = ref([]);
async function searchWarehouses(q) {
	const needle = (q || "").toLowerCase();
	return warehouses.value
		.filter((w) => !w.is_group && !w.disabled)
		.filter((w) => !needle || (w.warehouse_name || w.name).toLowerCase().includes(needle) || w.name.toLowerCase().includes(needle))
		.slice(0, 20);
}
function pickWarehouse(item) {
	form.value.destination_warehouse = item.name;
}

async function loadDoc() {
	if (isCreate.value) {
		form.value = blankForm();
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		const d = await importsApi.getImportTruck(docName.value);
		form.value = { ...blankForm(), ...d, trucking_company_name: d.trucking_company || "" };
	} catch (err) {
		error.value = err?.message || t("Failed to load the truck.");
	} finally {
		loading.value = false;
	}
}

async function loadRefData() {
	try {
		currencies.value = await call("stabler.api.sales.list_currencies", {});
	} catch (_) {
		currencies.value = [{ name: "USD" }, { name: "EUR" }, { name: "UZS" }];
	}
	if (activeCompany.value) {
		try {
			warehouses.value = await call("stabler.api.inventory.list_warehouses", { company: activeCompany.value });
		} catch (_) {
			warehouses.value = [];
		}
	}
}

function buildValues() {
	const v = {
		truck_number: form.value.truck_number,
		commercial_invoice: form.value.commercial_invoice || undefined,
		trucking_company: form.value.trucking_company || undefined,
		driver_name: form.value.driver_name,
		driver_phone: form.value.driver_phone,
		destination_warehouse: form.value.destination_warehouse || undefined,
		departure_date: form.value.departure_date || undefined,
		border_crossing_date: form.value.border_crossing_date || undefined,
		estimated_arrival: form.value.estimated_arrival || undefined,
		actual_arrival: form.value.actual_arrival || undefined,
		target_temp_min: Number(form.value.target_temp_min),
		target_temp_max: Number(form.value.target_temp_max),
		total_boxes: Number(form.value.total_boxes || 0),
		total_kg: Number(form.value.total_kg || 0),
		transport_currency: form.value.transport_currency,
		transport_payment_status: form.value.transport_payment_status,
	};
	if (costVisible.value && form.value.transport_cost !== null && form.value.transport_cost !== "") {
		v.transport_cost = Number(form.value.transport_cost);
	}
	return v;
}

async function save() {
	if (!form.value.truck_number) {
		toast.error(t("A truck number is required."));
		return;
	}
	saving.value = true;
	try {
		if (isCreate.value) {
			const res = await importsApi.createImportTruck({ company: activeCompany.value, values: buildValues() });
			toast.success(t("Truck created."));
			router.replace("/imports/trucks/" + res.name);
		} else {
			await importsApi.updateImportTruck({ name: docName.value, values: buildValues(), modified: form.value.modified });
			toast.success(t("Truck saved."));
			await loadDoc();
		}
	} catch (err) {
		toast.error(err?.message || t("Save failed."));
	} finally {
		saving.value = false;
	}
}

async function advanceStatus(nextStatus) {
	const backward = !form.value.allowed_transitions.includes(nextStatus);
	let reason = null;
	if (backward) {
		if (!canRollback.value) return;
		reason = window.prompt(t("Reason for the status correction:"));
		if (!reason) return;
	} else {
		const ok = await confirm({
			title: t("Change status"),
			body: t("Move this truck to {status}?", { status: t(nextStatus) }),
			confirmLabel: t("Confirm"),
		});
		if (!ok) return;
	}
	try {
		await importsApi.setTruckStatus(docName.value, nextStatus, reason);
		toast.success(t("Status updated."));
		await loadDoc();
	} catch (err) {
		toast.error(err?.message || t("Status change failed."));
	}
}

onMounted(() => {
	loadRefData();
	loadDoc();
});
watch(docName, loadDoc);
</script>

<template>
	<div>
		<div class="d-flex align-items-center mb-3">
			<button type="button" class="btn btn-ghost-secondary btn-icon me-2" @click="router.push('/imports/trucks')">
				<i class="ti ti-arrow-left"></i>
			</button>
			<div>
				<h2 class="page-title mb-0">{{ isCreate ? t("New truck") : (form.truck_number || form.name) }}</h2>
				<div v-if="!isCreate" class="text-secondary small">
					<StatusBadge doctype="Import Truck" :status="form.status" />
				</div>
			</div>
			<div class="ms-auto">
				<button type="button" class="btn btn-primary" :disabled="saving" @click="save">
					<i class="ti ti-device-floppy me-1"></i>{{ t("Save") }}
				</button>
			</div>
		</div>

		<div v-if="error" class="alert alert-danger">{{ error }}</div>

		<!-- Status action bar -->
		<div v-if="!isCreate" class="card mb-3">
			<div class="card-body d-flex align-items-center flex-wrap gap-2">
				<span class="text-secondary small">{{ t("Status") }}:</span>
				<StatusBadge doctype="Import Truck" :status="form.status" />
				<div class="ms-auto d-flex gap-2 flex-wrap">
					<button
						v-for="ns in form.allowed_transitions.filter((s) => s !== 'Cancelled')"
						:key="ns"
						type="button"
						class="btn btn-outline-primary btn-sm"
						@click="advanceStatus(ns)"
					>
						<i class="ti ti-arrow-right me-1"></i>{{ t(ns) }}
					</button>
					<button
						v-if="form.allowed_transitions.includes('Cancelled')"
						type="button"
						class="btn btn-outline-danger btn-sm"
						@click="advanceStatus('Cancelled')"
					>
						{{ t("Cancel") }}
					</button>
					<button
						v-if="canRollback && rollbackTarget"
						type="button"
						class="btn btn-ghost-secondary btn-sm"
						@click="advanceStatus(rollbackTarget)"
					>
						<i class="ti ti-arrow-back-up me-1"></i>{{ t("Roll back") }}
					</button>
				</div>
			</div>
		</div>

		<!-- Identity + driver -->
		<div class="card mb-3">
			<div class="card-header"><h3 class="card-title">{{ t("Truck & driver") }}</h3></div>
			<div class="card-body">
				<div class="row g-3">
					<div class="col-md-3">
						<label class="form-label required">{{ t("Truck number") }}</label>
						<input v-model="form.truck_number" type="text" class="form-control" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Commercial Invoice") }}</label>
						<input v-model="form.commercial_invoice" type="text" class="form-control font-monospace" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Carrier") }}</label>
						<Typeahead
							v-slot="{ item }"
							v-model="form.trucking_company"
							:search="searchSuppliers"
							:display="form.trucking_company_name"
							:placeholder="t('Search carrier…')"
							open-on-focus
							@pick="pickCarrier"
						>
							<div class="fw-semibold">{{ item.supplier_name || item.name }}</div>
						</Typeahead>
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Destination warehouse") }}</label>
						<Typeahead
							v-slot="{ item }"
							v-model="form.destination_warehouse"
							:search="searchWarehouses"
							:display="form.destination_warehouse"
							:placeholder="t('Search warehouse…')"
							open-on-focus
							@pick="pickWarehouse"
						>
							<div class="fw-semibold">{{ item.warehouse_name || item.name }}</div>
						</Typeahead>
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Driver") }}</label>
						<input v-model="form.driver_name" type="text" class="form-control" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Driver phone") }}</label>
						<input v-model="form.driver_phone" type="text" class="form-control" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Total boxes") }}</label>
						<input v-model.number="form.total_boxes" type="number" class="form-control" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Total weight (kg)") }}</label>
						<input v-model.number="form.total_kg" type="number" class="form-control" />
					</div>
				</div>
			</div>
		</div>

		<!-- Dates + cold chain -->
		<div class="card mb-3">
			<div class="card-header"><h3 class="card-title">{{ t("Route & cold chain") }}</h3></div>
			<div class="card-body">
				<div class="row g-3">
					<div class="col-md-3"><label class="form-label">{{ t("Departure") }}</label><DateInput v-model="form.departure_date" /></div>
					<div class="col-md-3"><label class="form-label">{{ t("Border crossing") }}</label><DateInput v-model="form.border_crossing_date" /></div>
					<div class="col-md-3"><label class="form-label">{{ t("Estimated arrival") }}</label><DateInput v-model="form.estimated_arrival" /></div>
					<div class="col-md-3"><label class="form-label">{{ t("Actual arrival") }}</label><DateInput v-model="form.actual_arrival" /></div>
					<div class="col-md-3"><label class="form-label">{{ t("Target temp min (°C)") }}</label><input v-model.number="form.target_temp_min" type="number" class="form-control" /></div>
					<div class="col-md-3"><label class="form-label">{{ t("Target temp max (°C)") }}</label><input v-model.number="form.target_temp_max" type="number" class="form-control" /></div>
				</div>
			</div>
		</div>

		<!-- Transport (cost gated) -->
		<div class="card mb-3">
			<div class="card-header"><h3 class="card-title">{{ t("Transport") }}</h3></div>
			<div class="card-body">
				<div class="row g-3">
					<div class="col-md-3">
						<label class="form-label">{{ t("Payment status") }}</label>
						<Select v-model="form.transport_payment_status" :options="payStatusOptions" />
					</div>
					<template v-if="costVisible">
						<div class="col-md-3">
							<label class="form-label">{{ t("Transport cost") }}</label>
							<MoneyInput v-model="form.transport_cost" :currency="form.transport_currency" :language="user.language" size="sm" />
						</div>
						<div class="col-md-3">
							<label class="form-label">{{ t("Currency") }}</label>
							<Select v-model="form.transport_currency" :options="currencyOptions" :placeholder="t('Currency')" />
						</div>
					</template>
					<div v-if="!isCreate" class="col-md-3">
						<label class="form-label">{{ t("Transport PI") }}</label>
						<input :value="form.transport_purchase_invoice || '—'" type="text" class="form-control font-monospace" readonly />
					</div>
				</div>
				<div v-if="!costVisible" class="text-secondary small mt-2">
					<i class="ti ti-lock me-1"></i>{{ t("Transport cost is hidden for your role.") }}
				</div>
			</div>
		</div>
	</div>
</template>
