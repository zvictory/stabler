<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { halfAssigned } from "../../composables/workOrderRoles.js";
import { formatDate, formatDateTime, todayIso} from "../../composables/date.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useToast } from "../../composables/useToast.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import ManufacturingOperatorBoard from "./ManufacturingOperatorBoard.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const { confirm } = useConfirm();
const toast = useToast();

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const search = ref("");
const statusFilter = ref("");

const STATUSES = ["", "Draft", "Not Started", "In Process", "Completed", "Stopped", "Closed", "Cancelled"];

const statusOptions = computed(() =>
	STATUSES.map((s) => ({ value: s, label: s || t("All statuses") }))
);

const formatQty = (n, uom) => {
	const v = Number(n || 0);
	return `${v.toLocaleString(user.value.language || "en", { maximumFractionDigits: 3 })} ${uom || ""}`.trim();
};

const statusBadge = (s) => {
	switch (s) {
		case "Completed":
			return "bg-success-lt";
		case "In Process":
			return "bg-blue-lt";
		case "Not Started":
		case "Draft":
			return "bg-yellow-lt";
		case "Stopped":
		case "Cancelled":
			return "bg-secondary-lt";
		case "Closed":
			return "bg-purple-lt";
		default:
			return "bg-secondary-lt";
	}
};

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.manufacturing.list_work_orders", {
			company: activeCompany.value,
			search: search.value,
			status: statusFilter.value || undefined,
			limit: 100,
		});
	} catch (err) {
		error.value = err?.message || "Failed to load work orders.";
	} finally {
		loading.value = false;
	}
}

let searchTimer = null;
function onSearchInput() {
	clearTimeout(searchTimer);
	searchTimer = setTimeout(load, 250);
}

onMounted(load);
watch(activeCompany, load);
watch(statusFilter, load);

// ----- Detail drawer -----
const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);
const actionBusy = ref(false);
const actionError = ref("");
const activeTab = ref("details");
const genealogy = ref(null);

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	genealogy.value = null;
	actionError.value = "";
	activeTab.value = "details";
	try {
		detail.value = await call("stabler.api.manufacturing.work_order_detail", { name });
	} catch (err) {
		detail.value = { error: err?.message || "Failed to load." };
	} finally {
		detailLoading.value = false;
	}
	try {
		genealogy.value = await call("stabler.api.manufacturing.wo_genealogy", { work_order: name });
	} catch (err) {
		genealogy.value = null;
	}
}
function closeDetail() {
	detailOpen.value = false;
	detail.value = null;
}

async function refreshDetail() {
	if (detail.value?.name) {
		await openDetail(detail.value.name);
	}
}

async function doSubmit(name) {
	const ok = await confirm({
		title: t("Submit Work Order"),
		body: t("Submit and release this Work Order?"),
		confirmLabel: t("Submit"),
		cancelLabel: t("Cancel"),
	});
	if (!ok) return;
	actionBusy.value = true;
	actionError.value = "";
	try {
		await call("stabler.api.manufacturing.submit_work_order", { name });
		toast.success(t("Work Order submitted and released."));
		await refreshDetail();
		await load();
	} catch (err) {
		actionError.value = err?.message || "Submit failed.";
	} finally {
		actionBusy.value = false;
	}
}

async function transferMaterials(name) {
	const qty = prompt(t("Transfer how many units of materials? Leave blank for full."));
	if (qty === null) return;
	actionBusy.value = true;
	actionError.value = "";
	try {
		await call("stabler.api.manufacturing.make_work_order_stock_entry", {
			work_order: name,
			purpose: "Material Transfer for Manufacture",
			qty: qty || undefined,
		});
		await refreshDetail();
		await load();
	} catch (err) {
		actionError.value = err?.message || "Transfer failed.";
	} finally {
		actionBusy.value = false;
	}
}

async function recordProduction(name) {
	const qty = prompt(t("Produce how many units? Leave blank for full balance."));
	if (qty === null) return;
	actionBusy.value = true;
	actionError.value = "";
	try {
		await call("stabler.api.manufacturing.make_work_order_stock_entry", {
			work_order: name,
			purpose: "Manufacture",
			qty: qty || undefined,
		});
		await refreshDetail();
		await load();
	} catch (err) {
		actionError.value = err?.message || "Production failed.";
	} finally {
		actionBusy.value = false;
	}
}

async function stop(name) {
	const ok = await confirm({
		title: t("Stop Work Order"),
		body: t("Stop this Work Order? You can resume it later."),
		confirmLabel: t("Stop"),
		cancelLabel: t("Cancel"),
		danger: true,
	});
	if (!ok) return;
	actionBusy.value = true;
	actionError.value = "";
	try {
		await call("stabler.api.manufacturing.stop_work_order", { name });
		toast.success(t("Work Order stopped."));
		await refreshDetail();
		await load();
	} catch (err) {
		actionError.value = err?.message || "Stop failed.";
	} finally {
		actionBusy.value = false;
	}
}

async function resume(name) {
	const ok = await confirm({
		title: t("Resume Work Order"),
		body: t("Resume this Work Order?"),
		confirmLabel: t("Resume"),
		cancelLabel: t("Cancel"),
	});
	if (!ok) return;
	actionBusy.value = true;
	actionError.value = "";
	try {
		await call("stabler.api.manufacturing.resume_work_order", { name });
		toast.success(t("Work Order resumed."));
		await refreshDetail();
		await load();
	} catch (err) {
		actionError.value = err?.message || "Resume failed.";
	} finally {
		actionBusy.value = false;
	}
}

async function close(name) {
	const ok = await confirm({
		title: t("Close Work Order"),
		body: t("Close this Work Order? This finalizes it."),
		confirmLabel: t("Close"),
		cancelLabel: t("Cancel"),
	});
	if (!ok) return;
	actionBusy.value = true;
	actionError.value = "";
	try {
		await call("stabler.api.manufacturing.close_work_order", { name });
		toast.success(t("Work Order closed."));
		await refreshDetail();
		await load();
	} catch (err) {
		actionError.value = err?.message || "Close failed.";
	} finally {
		actionBusy.value = false;
	}
}

// ----- Assign operators (manager only) -----
// An order is poured by one person and packed by another, so both roles are
// edited together and sent in one call: swapping the two would otherwise pass
// through a state where one name holds both roles, which the backend refuses.
const assignOpen = ref(false);
const assignBusy = ref(false);
const selectedOperator = ref("");
const selectedPackagingOperator = ref("");
const operatorList = ref([]);

const operatorSelectOptions = computed(() => [
	{ value: "", label: `— ${t("Remove operator")} —` },
	...operatorList.value.map((u) => ({ value: u.name, label: u.full_name || u.name })),
]);

async function openAssign() {
	assignOpen.value = true;
	selectedOperator.value = detail.value?.operator || "";
	selectedPackagingOperator.value = detail.value?.packaging_operator || "";
	if (!operatorList.value.length) {
		try {
			operatorList.value = await call("stabler.api.manufacturing.list_operators", {
				company: activeCompany.value,
			});
		} catch (err) {
			actionError.value = err?.message || "Failed to load operators.";
		}
	}
}

async function confirmAssign(name) {
	assignBusy.value = true;
	try {
		await call("stabler.api.manufacturing.assign_work_order_operator", {
			name,
			operator: selectedOperator.value || "",
			packaging_operator: selectedPackagingOperator.value || "",
		});
		assignOpen.value = false;
		await refreshDetail();
		await load();
	} catch (err) {
		actionError.value = err?.message || "Assign failed.";
	} finally {
		assignBusy.value = false;
	}
}

// ----- Create modal -----
const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");
const itemOptions = ref([]);
const bomOptions = ref([]);
const warehouseOptions = ref([]);
const optionsLoaded = ref(false);

function blankWO() {
	return {
		production_item: "",
		bom_no: "",
		qty: 1,
		planned_start_date: todayIso(),
		fg_warehouse: "",
		wip_warehouse: "",
		source_warehouse: "",
		operator: "",
		packaging_operator: "",
	};
}
const form = ref(blankWO());

// BOM preview: components scaled to the WO qty, shown read-only in the modal.
const bomPreview = ref(null);
const bomPreviewLoading = ref(false);

function fmtQty(v) {
	const n = Number(v) || 0;
	return (Number.isInteger(n) ? n : Number(n.toFixed(3))).toLocaleString("ru-RU");
}

async function loadBomPreview() {
	const bom = form.value.bom_no;
	if (!bom) {
		bomPreview.value = null;
		return;
	}
	bomPreviewLoading.value = true;
	try {
		bomPreview.value = await call("stabler.api.manufacturing.bom_materials", {
			company: activeCompany.value,
			bom_no: bom,
			qty: form.value.qty || 1,
		});
	} catch (err) {
		bomPreview.value = null;
		submitError.value = err?.message || "Failed to load BOM materials.";
	} finally {
		bomPreviewLoading.value = false;
	}
}

watch(
	() => [form.value.bom_no, form.value.qty],
	() => {
		if (createOpen.value) loadBomPreview();
	},
);

const bomSelectOptions = computed(() => [
	{ value: "" },
	...bomOptions.value.map((b) => ({
		value: b.name,
		name: b.name,
		is_default: b.is_default,
		docstatus: b.docstatus,
	})),
]);

async function loadOptions() {
	if (optionsLoaded.value) return;
	try {
		const [items, whs, ops] = await Promise.all([
			call("stabler.api.manufacturing.manufacturable_items", {
				company: activeCompany.value,
				limit: 500,
			}),
			call("stabler.api.inventory.list_warehouses", { company: activeCompany.value }),
			operatorList.value.length
				? Promise.resolve(operatorList.value)
				: call("stabler.api.manufacturing.list_operators", { company: activeCompany.value }),
		]);
		itemOptions.value = items || [];
		warehouseOptions.value = (whs || []).filter((w) => !w.is_group);
		operatorList.value = ops || [];
		optionsLoaded.value = true;
	} catch (err) {
		submitError.value = err?.message || "Failed to load options.";
	}
}

async function onProductionItemChange() {
	form.value.bom_no = "";
	if (!form.value.production_item) {
		bomOptions.value = [];
		return;
	}
	try {
		bomOptions.value = await call("stabler.api.manufacturing.list_boms", {
			company: activeCompany.value,
			item: form.value.production_item,
			limit: 50,
		});
		const def = bomOptions.value.find((b) => b.is_default && b.docstatus === 1);
		if (def) form.value.bom_no = def.name;
	} catch (err) {
		submitError.value = err?.message || "Failed to load BOMs.";
	}
}

function openCreate() {
	form.value = blankWO();
	bomOptions.value = [];
	bomPreview.value = null;
	submitError.value = "";
	createOpen.value = true;
	loadOptions();
}
function closeCreate() {
	createOpen.value = false;
}

async function saveWO(submitAfter) {
	submitError.value = "";
	if (!form.value.production_item) {
		submitError.value = t("Pick a finished-good item.");
		return;
	}
	if (Number(form.value.qty) <= 0) {
		submitError.value = t("Quantity must be positive.");
		return;
	}
	submitting.value = true;
	try {
		const res = await call("stabler.api.manufacturing.create_work_order", {
			company: activeCompany.value,
			production_item: form.value.production_item,
			bom_no: form.value.bom_no || undefined,
			qty: form.value.qty,
			planned_start_date: form.value.planned_start_date || undefined,
			fg_warehouse: form.value.fg_warehouse || undefined,
			wip_warehouse: form.value.wip_warehouse || undefined,
			source_warehouse: form.value.source_warehouse || undefined,
			operator: form.value.operator || undefined,
			packaging_operator: form.value.packaging_operator || undefined,
			submit: submitAfter ? 1 : 0,
		});
		closeCreate();
		await load();
		if (res?.name) openDetail(res.name);
	} catch (err) {
		submitError.value = err?.message || "Save failed.";
	} finally {
		submitting.value = false;
	}
}
</script>

<template>
	<!-- Operator view: simplified board (server already filters to own WOs) -->
	<ManufacturingOperatorBoard v-if="!session.isMfgManager" />

	<!-- Manager view: full table + create + detail drawer -->
	<template v-else>
		<div class="card mb-3">
			<div class="card-body">
				<div class="row g-2 align-items-center">
					<div class="col-md-5">
						<div class="input-icon">
							<span class="input-icon-addon"><i class="ti ti-search"></i></span>
							<input
								v-model="search"
								@input="onSearchInput"
								type="search"
								class="form-control"
								:placeholder="t('Search work orders…')"
							/>
						</div>
					</div>
					<div class="col-md-3">
						<Select v-model="statusFilter" :options="statusOptions" />
					</div>
					<div class="col-md-4 d-flex justify-content-md-end gap-2">
						<button type="button" class="btn btn-ghost-secondary" @click="load">
							<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
						</button>
						<button type="button" class="btn btn-primary" @click="openCreate">
							<i class="ti ti-plus me-1"></i>{{ t("New Work Order") }}
						</button>
					</div>
				</div>
			</div>
		</div>

		<div v-if="error" class="alert alert-danger">{{ error }}</div>

		<EmptyState
			v-if="!loading && !error && !rows.length"
			icon="ti-tool"
			accentIcon="ti-plus"
			tone="primary"
			:title="t('No work orders')"
			:subtitle="t('Create a Work Order to plan and track production runs against a BOM.')"
		/>

		<div v-else-if="loading" class="card-body text-center py-5">
			<div class="spinner-border text-primary"></div>
		</div>

		<div v-else class="card">
			<div class="table-responsive">
				<table class="table table-vcenter card-table table-hover">
					<thead>
						<tr>
							<th>{{ t("Work Order") }}</th>
							<th>{{ t("Finished good") }}</th>
							<th>{{ t("Operator") }}</th>
							<th class="text-end">{{ t("Planned") }}</th>
							<th class="text-end">{{ t("Transferred") }}</th>
							<th class="text-end">{{ t("Produced") }}</th>
							<th>{{ t("Status") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="r in rows" :key="r.name" class="cursor-pointer" @click="openDetail(r.name)">
							<td>
								<div class="font-monospace small">{{ r.name }}</div>
								<div class="small text-secondary">{{ formatDateTime(r.planned_start_date) }}</div>
							</td>
							<td>
								<div class="fw-semibold">{{ r.item_name || r.production_item }}</div>
								<div class="small text-secondary font-monospace">{{ r.production_item }}</div>
							</td>
							<!-- Both roles, labelled. A half-assigned order stops at the transfer,
								 so the empty half is red and says so: a grey "—" reads as "no data
								 here", which is the one thing it is not. -->
							<td class="small text-secondary">
								<div>
									<span class="text-muted">{{ t("Production operator") }}:</span>
									<span v-if="r.operator">{{ r.operator }}</span>
									<span v-else :class="halfAssigned(r) ? 'text-danger fw-bold' : 'text-muted'">
										{{ halfAssigned(r) ? t("not assigned") : "—" }}
									</span>
								</div>
								<div>
									<span class="text-muted">{{ t("Packaging operator") }}:</span>
									<span v-if="r.packaging_operator">{{ r.packaging_operator }}</span>
									<span v-else :class="halfAssigned(r) ? 'text-danger fw-bold' : 'text-muted'">
										{{ halfAssigned(r) ? t("not assigned") : "—" }}
									</span>
								</div>
							</td>
							<td class="text-end font-monospace">{{ formatQty(r.qty) }}</td>
							<td class="text-end font-monospace text-secondary">{{ formatQty(r.transferred_qty) }}</td>
							<td class="text-end font-monospace text-blue">{{ formatQty(r.produced_qty) }}</td>
							<td><span class="badge" :class="statusBadge(r.status)">{{ r.status }}</span></td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<!-- Detail drawer -->
		<div v-if="detailOpen" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
		<div v-if="detailOpen" class="offcanvas offcanvas-end show" tabindex="-1" style="visibility: visible; width: 700px">
			<div class="offcanvas-header">
				<h5 class="offcanvas-title">
					<span v-if="detail?.name" class="font-monospace small">{{ detail.name }}</span>
					<span v-else>{{ t("Work Order") }}</span>
				</h5>
				<button type="button" class="btn-close" @click="closeDetail"></button>
			</div>
			<div class="offcanvas-body">
				<div v-if="detailLoading" class="text-center py-5">
					<div class="spinner-border text-primary"></div>
				</div>
				<div v-else-if="detail?.error" class="alert alert-danger">{{ detail.error }}</div>
				<template v-else-if="detail">
					<div v-if="actionError" class="alert alert-danger">{{ actionError }}</div>

					<!-- Tab Navigation -->
					<ul class="nav nav-tabs mb-3">
						<li class="nav-item">
							<button
								type="button"
								class="nav-link"
								:class="{ active: activeTab === 'details' }"
								@click="activeTab = 'details'"
							>
								{{ t("Details") }}
							</button>
						</li>
						<li class="nav-item">
							<button
								type="button"
								class="nav-link"
								:class="{ active: activeTab === 'timeline' }"
								@click="activeTab = 'timeline'"
							>
								{{ t("Badge Timeline") }}
							</button>
						</li>
					</ul>

					<div v-if="activeTab === 'details'">
						<div class="mb-3">
							<div class="text-secondary small">{{ t("Finished good") }}</div>
							<div class="fw-semibold">{{ detail.item_name || detail.production_item }}</div>
							<div class="small text-secondary font-monospace">{{ detail.bom_no }}</div>
						</div>

						<!-- Operator assignment (manager only) -->
						<div class="mb-3">
							<div class="d-flex align-items-start gap-2">
								<div class="flex-grow-1">
									<div class="text-secondary small">{{ t("Production operator") }}</div>
									<div class="small" :class="{ 'text-danger fw-bold': !detail.operator && halfAssigned(detail) }">
										{{ detail.operator || (halfAssigned(detail) ? t("not assigned") : "—") }}
									</div>
									<div class="text-secondary small mt-2">{{ t("Packaging operator") }}</div>
									<div class="small" :class="{ 'text-danger fw-bold': !detail.packaging_operator && halfAssigned(detail) }">
										{{ detail.packaging_operator || (halfAssigned(detail) ? t("not assigned") : "—") }}
									</div>
									<div v-if="halfAssigned(detail)" class="alert alert-danger py-1 px-2 small mt-2 mb-0">
										{{ t("Materials cannot be transferred until both operator roles are assigned.") }}
									</div>
								</div>
								<button
									type="button"
									class="btn btn-sm btn-outline-secondary"
									:disabled="actionBusy"
									@click="openAssign()"
								>
									{{ t("Assign operators") }}
								</button>
							</div>
							<div v-if="assignOpen" class="mt-2">
								<label class="form-label small mb-1">{{ t("Production operator") }}</label>
								<Select v-model="selectedOperator" :options="operatorSelectOptions" />
								<label class="form-label small mb-1 mt-2">{{ t("Packaging operator") }}</label>
								<Select v-model="selectedPackagingOperator" :options="operatorSelectOptions" />
								<div class="d-flex gap-2 mt-2">
									<button
										type="button"
										class="btn btn-sm btn-primary"
										:disabled="assignBusy"
										@click="confirmAssign(detail.name)"
									>
										{{ t("Save") }}
									</button>
									<button
										type="button"
										class="btn btn-sm btn-ghost-secondary"
										@click="assignOpen = false"
									>
										{{ t("Cancel") }}
									</button>
								</div>
							</div>
						</div>

						<!-- Batch & genealogy (Faz 4a) -->
						<div v-if="detail.batch_no || (genealogy && genealogy.consumed && genealogy.consumed.length)" class="mb-3 border rounded p-2">
							<div class="d-flex align-items-center justify-content-between">
								<div class="text-secondary small"><i class="ti ti-versions me-1"></i>{{ t("Batch / lot") }}</div>
								<span v-if="detail.batch_no" class="badge bg-blue-lt text-blue font-monospace">{{ detail.batch_no }}</span>
							</div>
							<div v-if="detail.batch_mfg_date || detail.batch_expiry" class="small text-secondary mt-1">
								<span v-if="detail.batch_mfg_date">{{ t("Batch manufacture date") }}: {{ formatDate(detail.batch_mfg_date) }}</span>
								<span v-if="detail.batch_expiry" class="ms-2">{{ t("Batch expiry") }}: {{ formatDate(detail.batch_expiry) }}</span>
							</div>
							<div v-if="genealogy && genealogy.consumed && genealogy.consumed.length" class="mt-2">
								<div class="text-secondary small mb-1">{{ t("Consumed materials") }}</div>
								<div class="table-responsive">
									<table class="table table-sm mb-0">
										<thead>
											<tr>
												<th>{{ t("Material") }}</th>
												<th class="text-end">{{ t("Quantity") }}</th>
												<th>{{ t("Source warehouse") }}</th>
											</tr>
										</thead>
										<tbody>
											<tr v-for="(c, i) in genealogy.consumed" :key="i">
												<td>{{ c.item_name || c.item_code }}</td>
												<td class="text-end font-monospace text-nowrap">{{ formatQty(c.qty) }} {{ c.uom }}</td>
												<td class="small text-secondary">{{ c.warehouse }}</td>
											</tr>
										</tbody>
									</table>
								</div>
							</div>
						</div>

						<div class="row g-2 mb-3">
							<div class="col-4">
								<div class="text-secondary small">{{ t("Planned") }}</div>
								<div class="font-monospace">{{ formatQty(detail.qty) }}</div>
							</div>
							<div class="col-4">
								<div class="text-secondary small">{{ t("Transferred") }}</div>
								<div class="font-monospace">{{ formatQty(detail.transferred_qty) }}</div>
							</div>
							<div class="col-4">
								<div class="text-secondary small">{{ t("Produced") }}</div>
								<div class="font-monospace fw-semibold text-blue">{{ formatQty(detail.produced_qty) }}</div>
							</div>
						</div>

						<div class="row g-2 mb-3">
							<div class="col-6">
								<div class="text-secondary small">{{ t("Source warehouse") }}</div>
								<div class="small">{{ detail.source_warehouse || "—" }}</div>
							</div>
							<div class="col-6">
								<div class="text-secondary small">{{ t("Finished-goods warehouse") }}</div>
								<div class="small">{{ detail.fg_warehouse || "—" }}</div>
							</div>
						</div>

						<h6 class="text-uppercase small text-secondary mt-3 mb-2">{{ t("Required materials") }}</h6>
						<div class="table-responsive">
							<table class="table table-sm table-vcenter">
								<thead>
									<tr>
										<th>{{ t("Item") }}</th>
										<th class="text-end">{{ t("Required") }}</th>
										<th class="text-end">{{ t("Transferred") }}</th>
										<th class="text-end">{{ t("Consumed") }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="(it, i) in detail.required_items" :key="i">
										<td>
											<div class="fw-semibold">{{ it.item_name || it.item_code }}</div>
											<div class="small text-secondary font-monospace">{{ it.item_code }}</div>
										</td>
										<td class="text-end font-monospace">{{ formatQty(it.required_qty) }}</td>
										<td class="text-end font-monospace text-secondary">{{ formatQty(it.transferred_qty) }}</td>
										<td class="text-end font-monospace text-blue">{{ formatQty(it.consumed_qty) }}</td>
									</tr>
								</tbody>
							</table>
						</div>

						<div class="mt-3 d-flex flex-wrap gap-2">
							<button
								v-if="detail.docstatus === 0"
								type="button"
								class="btn btn-success"
								:disabled="actionBusy"
								@click="doSubmit(detail.name)"
							>
								<i class="ti ti-check me-1"></i>{{ t("Submit") }}
							</button>
							<button
								v-if="detail.docstatus === 1 && detail.status === 'Not Started'"
								type="button"
								class="btn btn-outline-primary"
								:disabled="actionBusy"
								@click="transferMaterials(detail.name)"
							>
								<i class="ti ti-transfer me-1"></i>{{ t("Transfer materials") }}
							</button>
							<button
								v-if="detail.docstatus === 1 && ['In Process', 'Not Started'].includes(detail.status)"
								type="button"
								class="btn btn-primary"
								:disabled="actionBusy"
								@click="recordProduction(detail.name)"
							>
								<i class="ti ti-package me-1"></i>{{ t("Record production") }}
							</button>
							<button
								v-if="detail.docstatus === 1 && ['In Process', 'Not Started'].includes(detail.status)"
								type="button"
								class="btn btn-outline-warning"
								:disabled="actionBusy"
								@click="stop(detail.name)"
							>
								<i class="ti ti-player-stop me-1"></i>{{ t("Stop") }}
							</button>
							<button
								v-if="detail.docstatus === 1 && detail.status === 'Stopped'"
								type="button"
								class="btn btn-outline-primary"
								:disabled="actionBusy"
								@click="resume(detail.name)"
							>
								<i class="ti ti-player-play me-1"></i>{{ t("Resume") }}
							</button>
							<button
								v-if="detail.docstatus === 1 && detail.status === 'Completed'"
								type="button"
								class="btn btn-outline-secondary"
								:disabled="actionBusy"
								@click="close(detail.name)"
							>
								<i class="ti ti-lock me-1"></i>{{ t("Close") }}
							</button>
						</div>
					</div>

					<!-- Badge Timeline Tab -->
					<div v-if="activeTab === 'timeline'">
						<div v-if="!detail.timeline || !detail.timeline.length" class="text-secondary text-center py-4">
							{{ t("No activity recorded yet.") }}
						</div>
						<div v-else class="list-group list-group-transparent">
							<div v-for="item in detail.timeline" :key="item.name" class="list-group-item d-flex align-items-start gap-3 py-3 border-0 border-bottom">
								<span class="avatar avatar-sm bg-blue-lt flex-shrink-0">
									<i class="ti ti-user fs-3"></i>
								</span>
								<div class="flex-grow-1 min-w-0">
									<div class="d-flex justify-content-between align-items-center mb-1">
										<span class="font-monospace text-secondary small">{{ formatDateTime(item.creation) }}</span>
										<span class="badge bg-secondary-lt small font-monospace">{{ item.comment_by || item.owner }}</span>
									</div>
									<div class="text-body text-wrap font-sans-serif" style="word-break: break-word;">
										{{ item.content }}
									</div>
								</div>
							</div>
						</div>
					</div>
				</template>
			</div>
		</div>

		<!-- Create modal -->
		<div v-if="createOpen" class="modal-backdrop fade show" @click="closeCreate"></div>
		<div v-if="createOpen" class="modal fade show d-block" tabindex="-1" style="background: transparent">
			<div class="modal-dialog modal-lg">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">{{ t("New Work Order") }}</h5>
						<button type="button" class="btn-close" @click="closeCreate"></button>
					</div>
					<div class="modal-body">
						<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>

						<div class="row g-2 mb-3">
							<div class="col-md-7">
								<label class="form-label">{{ t("Finished good") }}</label>
								<Select
									v-model="form.production_item"
									:options="itemOptions"
									value-key="item_code"
									placeholder="—"
									@change="onProductionItemChange"
								>
									<template #option="{ option }">
										{{ option.item_name }} ({{ option.item_code }})
									</template>
									<template #selected="{ option }">
										{{ option.item_name }} ({{ option.item_code }})
									</template>
								</Select>
								<div v-if="!itemOptions.length && optionsLoaded" class="form-hint text-warning">
									{{ t("No items with submitted active BOMs yet — create one first.") }}
								</div>
							</div>
							<div class="col-md-5">
								<label class="form-label">{{ t("BOM") }}</label>
								<Select
									v-model="form.bom_no"
									:options="bomSelectOptions"
									:disabled="!bomOptions.length"
								>
									<template #option="{ option }">
										<template v-if="option.value === ''">{{ t("Default") }}</template>
										<template v-else>{{ option.name }}{{ option.is_default ? " · default" : "" }}{{ option.docstatus !== 1 ? " (draft)" : "" }}</template>
									</template>
									<template #selected="{ option }">
										<template v-if="option.value === ''">{{ t("Default") }}</template>
										<template v-else>{{ option.name }}{{ option.is_default ? " · default" : "" }}{{ option.docstatus !== 1 ? " (draft)" : "" }}</template>
									</template>
								</Select>
							</div>
						</div>

						<div class="row g-2 mb-3">
							<div class="col-md-4">
								<label class="form-label">{{ t("Quantity") }}</label>
								<input v-model.number="form.qty" type="number" min="0.001" step="0.001" inputmode="decimal" class="form-control" />
							</div>
							<div class="col-md-4">
								<label class="form-label">{{ t("Planned start") }}</label>
								<DateInput v-model="form.planned_start_date" />
							</div>
							<div class="col-md-4">
								<label class="form-label">{{ t("Production operator") }}</label>
								<Select v-model="form.operator" :options="operatorList" value-key="name" placeholder="—">
									<template #option="{ option }">{{ option.full_name || option.name }}</template>
									<template #selected="{ option }">{{ option.full_name || option.name }}</template>
								</Select>
							</div>
							<div class="col-md-4">
								<label class="form-label">{{ t("Packaging operator") }}</label>
								<Select v-model="form.packaging_operator" :options="operatorList" value-key="name" placeholder="—">
									<template #option="{ option }">{{ option.full_name || option.name }}</template>
									<template #selected="{ option }">{{ option.full_name || option.name }}</template>
								</Select>
							</div>
						</div>

						<!-- BOM materials preview: scaled to the WO qty, read-only -->
						<div v-if="form.bom_no" class="mb-3">
							<label class="form-label mb-1">
								{{ t("BOM materials") }}
								<span class="text-secondary fw-normal">· {{ fmtQty(form.qty) }} {{ bomPreview && bomPreview.uom ? bomPreview.uom : "" }}</span>
							</label>
							<div v-if="bomPreviewLoading" class="text-secondary small py-2">{{ t("Loading…") }}</div>
							<div v-else-if="bomPreview && bomPreview.items.length" class="table-responsive border rounded">
								<table class="table table-sm align-middle mb-0">
									<thead>
										<tr>
											<th>{{ t("Material") }}</th>
											<th class="text-end">{{ t("Quantity") }}</th>
										</tr>
									</thead>
									<tbody>
										<tr v-for="(it, i) in bomPreview.items" :key="i">
											<td>
												{{ it.item_name || it.item_code }}
												<div class="text-secondary small">{{ it.item_code }}</div>
											</td>
											<td class="text-end font-monospace text-nowrap">{{ fmtQty(it.qty) }} {{ it.uom }}</td>
										</tr>
									</tbody>
								</table>
							</div>
							<div v-else-if="bomPreview" class="text-secondary small py-2">{{ t("This BOM has no materials.") }}</div>
						</div>

						<div class="row g-2 mb-3">
							<div class="col-md-4">
								<label class="form-label">{{ t("Source warehouse") }}</label>
								<Select
									v-model="form.source_warehouse"
									:options="warehouseOptions"
									value-key="name"
									label-key="name"
									placeholder="—"
								/>
							</div>
							<div class="col-md-4">
								<label class="form-label">{{ t("WIP warehouse") }}</label>
								<Select
									v-model="form.wip_warehouse"
									:options="warehouseOptions"
									value-key="name"
									label-key="name"
									placeholder="—"
								/>
							</div>
							<div class="col-md-4">
								<label class="form-label">{{ t("Finished-goods warehouse") }}</label>
								<Select
									v-model="form.fg_warehouse"
									:options="warehouseOptions"
									value-key="name"
									label-key="name"
									placeholder="—"
								/>
							</div>
						</div>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-link link-secondary" @click="closeCreate">{{ t("Cancel") }}</button>
						<button type="button" class="btn btn-outline-primary" :disabled="submitting" @click="saveWO(false)">
							<i class="ti ti-device-floppy me-1"></i>{{ t("Save as draft") }}
						</button>
						<button type="button" class="btn btn-primary" :disabled="submitting" @click="saveWO(true)">
							<i class="ti ti-check me-1"></i>{{ t("Save and submit") }}
						</button>
					</div>
				</div>
			</div>
		</div>
	</template>
</template>

<style scoped>
.cursor-pointer {
	cursor: pointer;
}
</style>
