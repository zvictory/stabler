<script setup>
/**
 * WorkOrderDetail — one work order, on its own page.
 *
 * It used to be a 700px drawer sliding over the list. That is the wrong shape
 * for what people do with it: an order gets read on a tablet on the floor, its
 * link gets sent to whoever has to answer for a shortage, and its material
 * table is twelve columns wide. A URL, browser back, and the full width fix all
 * three; the drawer could fix none of them.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { materialsForUnits, stockKey } from "../../composables/materialReadiness.js";
import { halfAssigned, roleLabel } from "../../composables/workOrderRoles.js";
import { workOrderStages } from "../../composables/workOrderStages.js";
import { useOperatorOptions } from "../../composables/workOrderOperators.js";
import { useWorkOrderStatus } from "../../composables/workOrderStatus.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, formatDateTime } from "../../composables/date.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useToast } from "../../composables/useToast.js";
import Select from "../../components/Select.vue";

const route = useRoute();
const router = useRouter();
const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const { confirm } = useConfirm();
const toast = useToast();

const { operatorSelectOptions, loadOperators } = useOperatorOptions();

const formatQty = (n, uom) => {
	const v = Number(n) || 0;
	const s = v.toLocaleString(user.value?.language === "ru" ? "ru-RU" : "en-US", {
		maximumFractionDigits: 3,
	});
	return uom ? `${s} ${uom}` : s;
};

const { statusLabel, statusBadge } = useWorkOrderStatus();

// Stock for the warehouses this order draws from, so the transfer dialog can
// say what a quantity costs before it is committed. One call per warehouse.
const stock = ref({});
async function loadStock() {
	const byWarehouse = new Map();
	for (const line of detail.value?.required_items || []) {
		if (!line.source_warehouse) continue;
		if (!byWarehouse.has(line.source_warehouse)) byWarehouse.set(line.source_warehouse, new Set());
		byWarehouse.get(line.source_warehouse).add(line.item_code);
	}
	await Promise.all(
		[...byWarehouse].map(async ([warehouse, codes]) => {
			try {
				const res = await call("stabler.api.inventory.get_items_stock", {
					warehouse,
					item_codes: JSON.stringify([...codes]),
				});
				for (const [code, qty] of Object.entries(res || {})) {
					stock.value[stockKey(warehouse, code)] = qty;
				}
			} catch (err) {
				// A warehouse that will not answer leaves its items unmeasured, and
				// the dialog says so rather than guessing.
			}
		}),
	);
}

const stages = computed(() => workOrderStages(detail.value));

const detailLoading = ref(false);
const detail = ref(null);
const actionBusy = ref(false);
const actionError = ref("");
const activeTab = ref("details");
const genealogy = ref(null);

async function openDetail(name) {
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
	} catch (err) {
		actionError.value = err?.message || "Submit failed.";
	} finally {
		actionBusy.value = false;
	}
}

// Both actions ask the same question — how many units — and the browser's bare
// one-line box was the wrong place to ask it: the operator typed a number
// without seeing which materials it consumes or whether the store carries
// them; the shortage surfaced only as a failed stock entry.
// The stock figures the list column already loads answer that before the fact.
const qtyDialog = ref(null); // { mode: "transfer" | "produce", name }
const qtyValue = ref("");

function openQtyDialog(mode, name) {
	qtyDialog.value = { mode, name };
	actionError.value = "";
	qtyValue.value = String(dialogBalance.value || "");
}

// Transfer counts against what has been issued, production against what has
// been finished. One shared "remaining" would offer to re-transfer material
// already sitting in WIP.
const dialogBalance = computed(() => {
	const d = detail.value || {};
	const done =
		qtyDialog.value?.mode === "produce"
			? Number(d.produced_qty) || 0
			: Number(d.transferred_qty) || 0;
	return Math.max(0, (Number(d.qty) || 0) - done);
});

// Reads the box, not the value it opened with: retyping 4 000 as 500 has to
// move the material figures with it, or the list describes a transfer that is
// not the one about to happen — worse than no list, because it looks checked.
const dialogUnits = computed(() => {
	const n = Number(qtyValue.value);
	return Number.isFinite(n) && n > 0 ? n : dialogBalance.value;
});

const dialogMaterials = computed(() =>
	qtyDialog.value?.mode === "transfer"
		? materialsForUnits(detail.value, stock.value, dialogUnits.value)
		: [],
);

const dialogShort = computed(() => dialogMaterials.value.filter((m) => m.short).length);

async function confirmQtyDialog() {
	const { mode, name } = qtyDialog.value || {};
	if (!name) return;
	const typed = Number(qtyValue.value);
	const qty = Number.isFinite(typed) && typed > 0 ? typed : undefined;
	qtyDialog.value = null;
	actionBusy.value = true;
	actionError.value = "";
	try {
		await call("stabler.api.manufacturing.make_work_order_stock_entry", {
			work_order: name,
			purpose: mode === "produce" ? "Manufacture" : "Material Transfer for Manufacture",
			qty,
		});
		await refreshDetail();
	} catch (err) {
		actionError.value =
			err?.message || (mode === "produce" ? "Production failed." : "Transfer failed.");
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
async function openAssign() {
	assignOpen.value = true;
	selectedOperator.value = detail.value?.operator || "";
	selectedPackagingOperator.value = detail.value?.packaging_operator || "";
	const err = await loadOperators(activeCompany.value);
	if (err) actionError.value = err;
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
	} catch (err) {
		actionError.value = err?.message || "Assign failed.";
	} finally {
		assignBusy.value = false;
	}
}

onMounted(async () => {
	await openDetail(route.params.name);
	await loadStock();
});
watch(
	() => route.params.name,
	async (name) => {
		if (!name) return;
		stock.value = {};
		await openDetail(name);
		await loadStock();
	},
);
</script>

<template>
	<div>
		<div class="d-flex align-items-center justify-content-between mb-3">
			<div>
				<button type="button" class="btn btn-ghost-secondary btn-sm mb-1" @click="router.push({ name: 'manufacturing-work-orders' })">
					<i class="ti ti-arrow-left me-1"></i>{{ t("Work Orders") }}
				</button>
				<h2 class="page-title font-monospace mb-0">{{ route.params.name }}</h2>
			</div>
			<span v-if="detail?.status" class="badge" :class="statusBadge(detail.status)">{{ statusLabel(detail.status) }}</span>
		</div>

		<div class="card">
			<div class="card-body">
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
					<!-- Stage cards.
						 The obvious card here would be one per routing operation. Measured
						 on the only tenant that runs work orders: 4 211 orders, 560 BOMs,
						 zero Work Order Operation rows, zero Workstations. What these
						 orders do have is two people with two jobs and a BOM split between
						 them, so that is the decomposition the cards show. -->
					<div v-if="stages.length" class="row g-3 mb-4">
						<div v-for="s in stages" :key="s.role || 'undecided'" class="col-md-6">
							<div class="card h-100" :class="!s.role ? 'border-warning' : ''">
								<div class="card-body">
									<div class="d-flex justify-content-between align-items-start mb-2">
										<div class="fw-bold">{{ s.role ? roleLabel(s.role) : t("undecided") }}</div>
										<span v-if="s.lines" class="badge bg-secondary-lt">
											{{ t("{0} / {1} line(s) transferred", [s.transferredLines, s.lines]) }}
										</span>
									</div>

									<div v-if="s.role" class="small mb-2" :class="!s.operator && halfAssigned(detail) ? 'text-danger fw-bold' : 'text-secondary'">
										{{ s.operator || t("not assigned") }}
									</div>

									<!-- A packer on an order whose BOM gives packing nothing to do is
										 a mis-set role, and it is invisible anywhere else on this page. -->
									<div v-if="!s.lines" class="small text-warning">
										{{ t("No materials assigned to this stage.") }}
									</div>
									<ul v-else class="list-unstyled small mb-0">
										<li v-for="i in s.items" :key="i.item_code" class="d-flex justify-content-between gap-2">
											<span class="text-truncate">{{ i.item_name || i.item_code }}</span>
											<span class="font-monospace text-secondary text-nowrap">
												{{ formatQty(i.transferred_qty) }} / {{ formatQty(i.required_qty) }}
											</span>
										</li>
									</ul>

									<div v-if="s.deviation?.counted_lines" class="border-top mt-2 pt-2 small d-flex justify-content-between">
										<span class="text-secondary">{{ t("Deviation from BOM") }}</span>
										<span
											class="font-monospace"
											:class="s.deviation.cost > 0 ? 'text-danger' : s.deviation.cost < 0 ? 'text-success' : 'text-secondary'"
										>{{ formatMoney(s.deviation.cost, detail.currency, user.language) }}</span>
									</div>
								</div>
							</div>
						</div>
					</div>

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
										<th>{{ t("Responsible") }}</th>
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
										<td>
											<span v-if="it.operator_role" class="badge bg-blue-lt">{{ roleLabel(it.operator_role) }}</span>
											<span v-else class="small text-warning">{{ t("undecided") }}</span>
										</td>
									</tr>
								</tbody>
								<!-- One total per role, in money: the rows are litres, kilograms and
									 pieces at once and adding those gives a number that is wrong
									 without looking wrong. Backend decides the buckets
									 (_role_deviation) so the split is not re-derived here. -->
								<tfoot v-if="detail.role_deviation">
									<tr v-for="b in detail.role_deviation" :key="b.role || 'unassigned'">
										<td colspan="3" class="small">
											<span class="text-secondary">{{ t("Deviation from BOM") }}:</span>
											<b>{{ b.role ? roleLabel(b.role) : t("undecided") }}</b>
											<span v-if="b.pending_lines" class="text-secondary ms-2">
												{{ t("{0} line(s) not written off yet — not in this total.", [b.pending_lines]) }}
											</span>
										</td>
										<td class="text-end font-monospace" :class="b.cost > 0 ? 'text-danger' : b.cost < 0 ? 'text-success' : 'text-secondary'">
											<template v-if="b.counted_lines">{{ formatMoney(b.cost, detail.currency, user.language) }}</template>
											<span v-else class="text-secondary">—</span>
										</td>
										<td></td>
									</tr>
								</tfoot>
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
								@click="openQtyDialog('transfer', detail.name)"
							>
								<i class="ti ti-transfer me-1"></i>{{ t("Transfer materials") }}
							</button>
							<button
								v-if="detail.docstatus === 1 && ['In Process', 'Not Started'].includes(detail.status)"
								type="button"
								class="btn btn-primary"
								:disabled="actionBusy"
								@click="openQtyDialog('produce', detail.name)"
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

		<div v-if="qtyDialog" class="modal-backdrop fade show" @click="qtyDialog = null"></div>
		<div v-if="qtyDialog" class="modal fade show d-block" tabindex="-1" style="background: transparent">
			<div class="modal-dialog">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">
							{{ qtyDialog.mode === "produce" ? t("Record production") : t("Transfer materials") }}
						</h5>
						<button type="button" class="btn-close" @click="qtyDialog = null"></button>
					</div>
					<div class="modal-body">
						<div class="mb-3">
							<label class="form-label small mb-1">{{ t("Quantity") }}</label>
							<input v-model="qtyValue" type="number" min="0" step="any" class="form-control font-monospace" />
							<div class="form-hint">
								{{ t("Remaining: {0}", [formatQty(dialogBalance, detail?.uom)]) }}
							</div>
						</div>

						<!-- The list is the reason this dialog exists. Producing does not draw
							 from the store — the material is already in WIP by then — so it is
							 shown for the transfer only, where it can still change the answer. -->
						<div v-if="dialogMaterials.length" class="table-responsive">
							<table class="table table-sm mb-0">
								<thead>
									<tr>
										<th>{{ t("Item") }}</th>
										<th class="text-end">{{ t("Required") }}</th>
										<th class="text-end">{{ t("In store") }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="m in dialogMaterials" :key="m.item_code">
										<td>
											<div>{{ m.item_name }}</div>
											<div class="small text-secondary font-monospace">{{ m.item_code }}</div>
										</td>
										<td class="text-end font-monospace">{{ formatQty(m.needed) }}</td>
										<td class="text-end font-monospace" :class="m.short ? 'text-danger fw-semibold' : 'text-secondary'">
											<template v-if="m.available !== null">{{ formatQty(m.available) }}</template>
											<span v-else class="text-secondary">—</span>
										</td>
									</tr>
								</tbody>
							</table>
						</div>

						<!-- A warning, not a block. The store figure is a Bin snapshot and the
							 shelf is the authority; refusing the transfer would leave an
							 operator standing in front of material the screen says is not there. -->
						<div v-if="dialogShort" class="alert alert-warning mt-3 mb-0">
							{{ t("short {0} item(s)", [dialogShort]) }}
						</div>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-outline-secondary" @click="qtyDialog = null">
							{{ t("Cancel") }}
						</button>
						<button type="button" class="btn btn-primary" :disabled="actionBusy" @click="confirmQtyDialog">
							{{ qtyDialog.mode === "produce" ? t("Record production") : t("Transfer materials") }}
						</button>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
