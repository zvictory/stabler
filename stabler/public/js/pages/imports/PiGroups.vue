<script setup>
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import Typeahead from "../../components/Typeahead.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const toast = useToast();
const { confirm } = useConfirm();

const rows = ref([]);
const loading = ref(false);
const search = ref("");
const statusFilter = ref("");

const fm = (v, ccy) => formatMoney(v, ccy || "USD", user.value?.language || "en");

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		rows.value = await importsApi.listPiGroups({
			company: activeCompany.value,
			search: search.value || undefined,
		});
	} catch (err) {
		toast.error(err?.message || t("Failed to load PI groups."));
		rows.value = [];
	} finally {
		loading.value = false;
	}
}
onMounted(load);

const filteredRows = computed(() => {
	let list = rows.value || [];
	if (statusFilter.value) {
		list = list.filter((r) => r.status === statusFilter.value);
	}
	return list;
});

const summaryStats = computed(() => {
	const total = rows.value.length;
	const openCount = rows.value.filter((r) => r.status === "Open" || !r.status).length;
	const totalAgreed = rows.value.reduce((acc, r) => acc + (Number(r.agreed_total) || 0), 0);
	const totalPis = rows.value.reduce((acc, r) => acc + (Number(r.pi_count) || 0), 0);
	return { total, openCount, totalAgreed, totalPis };
});

function groupTitle(row) {
	if (!row) return "";
	return row.group_name || row.title || row.code || row.name;
}

// ---- Create / Edit Modal ----
const modalOpen = ref(false);
const saving = ref(false);
const form = ref(blankForm());

function blankForm() {
	return {
		name: "",
		code: "",
		group_name: "",
		pi_vendor: "",
		pi_vendor_name: "",
		status: "Open",
		notes: "",
		modified: "",
	};
}

function openNew() {
	form.value = blankForm();
	modalOpen.value = true;
}

function openEditFromRow(row) {
	form.value = {
		name: row.name,
		code: row.code || "",
		group_name: row.group_name || row.title || "",
		pi_vendor: row.pi_vendor || "",
		pi_vendor_name: row.pi_vendor_name || row.pi_vendor || "",
		status: row.status || "Open",
		notes: row.notes || row.remarks || "",
		modified: row.modified || "",
	};
	modalOpen.value = true;
}

async function openEdit(name) {
	loading.value = true;
	try {
		const detail = await importsApi.piGroupDetail(name);
		const g = detail.group || detail || {};
		form.value = {
			name: g.name,
			code: g.code || "",
			group_name: g.group_name || g.title || "",
			pi_vendor: g.pi_vendor || "",
			pi_vendor_name: g.pi_vendor_name || g.pi_vendor || "",
			status: g.status || "Open",
			notes: g.notes || g.remarks || "",
			modified: g.modified || "",
		};
		modalOpen.value = true;
	} catch (err) {
		toast.error(err?.message || t("Failed to load the PI group."));
	} finally {
		loading.value = false;
	}
}

function closeModal() {
	if (!saving.value) modalOpen.value = false;
}

function searchSuppliers(q) {
	return call("stabler.api.purchasing.list_suppliers", {
		company: activeCompany.value,
		search: q,
		limit: 20,
	});
}

const canSave = computed(() => {
	const f = form.value;
	if (!f) return false;
	return !!(f.group_name || f.code || "").trim();
});

async function saveGroup() {
	if (!canSave.value) return;
	saving.value = true;
	try {
		const res = await importsApi.savePiGroup(
			{
				name: form.value.name || undefined,
				code: (form.value.code || "").trim(),
				group_name: (form.value.group_name || "").trim(),
				pi_vendor: form.value.pi_vendor || undefined,
				status: form.value.status || "Open",
				notes: form.value.notes,
				modified: form.value.modified || undefined,
			},
			activeCompany.value
		);
		toast.success(t("PI Group saved successfully"));
		modalOpen.value = false;
		await load();
		if (detailOpen.value && detailGroup.value?.name === (form.value.name || res?.name)) {
			openDetail(res?.name || form.value.name);
		}
	} catch (err) {
		toast.error(err?.message || t("Could not save the PI group."));
	} finally {
		saving.value = false;
	}
}

async function deleteGroup(row) {
	const name = row.name || row;
	const title = groupTitle(row) || name;
	const ok = await confirm({
		title: t("Delete PI Group"),
		body: t("Are you sure you want to delete PI Group '{0}'? Member proformas will be unlinked, not deleted.", [title]),
		confirmLabel: t("Delete"),
		cancelLabel: t("Cancel"),
		danger: true,
	});
	if (!ok) return;
	try {
		await importsApi.deletePiGroup(name, activeCompany.value);
		toast.success(t("PI Group deleted."));
		if (detailOpen.value && detailGroup.value?.name === name) {
			closeDetail();
		}
		load();
	} catch (err) {
		toast.error(err?.message || t("Could not delete the PI group."));
	}
}

// ---- Detail Drawer / Modal ----
const detailOpen = ref(false);
const detailLoading = ref(false);
const detailGroup = ref(null);
const detailPis = ref([]);
const detailCis = ref([]);
const detailContainers = ref([]);
const detailPos = ref([]);
const detailTotals = ref({});
const activeTab = ref("pis"); // 'pis' | 'cis' | 'pos'

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	activeTab.value = "pis";
	try {
		const detail = await importsApi.piGroupDetail(name);
		detailGroup.value = detail.group || detail || null;
		detailPis.value = detail.pis || [];
		detailCis.value = detail.cis || [];
		detailContainers.value = detail.containers || [];
		detailPos.value = detail.purchase_orders || [];
		detailTotals.value = detail.totals || {
			pi_count: detailPis.value.length,
			ci_count: detailCis.value.length,
			container_count: detailContainers.value.length,
			po_count: detailPos.value.length,
			agreed_total: detailPis.value.reduce((acc, p) => acc + (Number(p.agreed_total) || 0), 0),
			docs_total: detailPis.value.reduce((acc, p) => acc + (Number(p.docs_total) || 0), 0),
			cash_difference: detailPis.value.reduce((acc, p) => acc + (Number(p.cash_difference) || 0), 0),
		};
	} catch (err) {
		toast.error(err?.message || t("Failed to load PI group details."));
		detailOpen.value = false;
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	detailOpen.value = false;
	detailGroup.value = null;
	detailPis.value = [];
	detailCis.value = [];
	detailContainers.value = [];
	detailPos.value = [];
	detailTotals.value = {};
}

function editFromDetail() {
	if (!detailGroup.value) return;
	openEditFromRow(detailGroup.value);
}

// ---- Assign PIs modal ----
const assignOpen = ref(false);
const assignLoading = ref(false);
const assignSaving = ref(false);
const assignGroup = ref(null);
const assignRows = ref([]);
const assignChecked = ref({});
const assignSearch = ref("");

async function openAssign(row) {
	assignGroup.value = row;
	assignOpen.value = true;
	assignLoading.value = true;
	assignChecked.value = {};
	assignSearch.value = "";
	try {
		const list = await importsApi.listGroupEligiblePis(row.name, activeCompany.value);
		assignRows.value = list || [];
		for (const pi of assignRows.value) {
			assignChecked.value[pi.name] = !!pi.linked;
		}
	} catch (err) {
		toast.error(err?.message || t("Failed to load eligible proformas."));
		assignRows.value = [];
	} finally {
		assignLoading.value = false;
	}
}

const filteredAssignRows = computed(() => {
	let list = assignRows.value || [];
	if (assignSearch.value.trim()) {
		const q = assignSearch.value.trim().toLowerCase();
		list = list.filter(
			(r) =>
				(r.name || "").toLowerCase().includes(q) ||
				(r.supplier_pi_ref || "").toLowerCase().includes(q) ||
				(r.supplier || "").toLowerCase().includes(q) ||
				(r.supplier_name || "").toLowerCase().includes(q)
		);
	}
	return list;
});

function openPi(name) {
	if (!name) return;
	router.push("/imports/proformas/" + name);
}
function openCi(name) {
	if (!name) return;
	router.push("/imports/commercial-invoices/" + name);
}
function openContainer(name) {
	if (!name) return;
	router.push("/imports/containers/" + name);
}
function openTruck(name) {
	if (!name) return;
	router.push("/imports/trucks/" + name);
}
function openProformasBySupplier(sup) {
	if (!sup) return;
	router.push({ path: "/imports/proformas", query: { supplier: sup } });
}
function assignFromDetail() {
	if (!detailGroup.value) return;
	openAssign(detailGroup.value);
}

function closeAssign() {
	if (!assignSaving.value) assignOpen.value = false;
}

function selectAll() {
	for (const pi of filteredAssignRows.value) assignChecked.value[pi.name] = true;
}
function clearAll() {
	for (const pi of filteredAssignRows.value) assignChecked.value[pi.name] = false;
}

const checkedCount = computed(() => Object.values(assignChecked.value).filter(Boolean).length);

async function saveAssign() {
	if (!assignGroup.value) return;
	assignSaving.value = true;
	try {
		const piNames = Object.keys(assignChecked.value).filter((k) => assignChecked.value[k]);
		await importsApi.assignPisToGroup(assignGroup.value.name, piNames, activeCompany.value);
		toast.success(t("Proformas assigned successfully"));
		assignOpen.value = false;
		await load();
		if (detailOpen.value && detailGroup.value?.name === assignGroup.value.name) {
			openDetail(assignGroup.value.name);
		}
	} catch (err) {
		toast.error(err?.message || t("Could not assign proformas."));
	} finally {
		assignSaving.value = false;
	}
}
</script>

<template>
	<div class="page-body">
		<!-- Summary Cards Header -->
		<div class="row row-cards mb-3">
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="row align-items-center">
							<div class="col-auto">
								<span class="bg-primary text-white avatar">
									<i class="ti ti-tags fs-2"></i>
								</span>
							</div>
							<div class="col">
								<div class="font-weight-medium">{{ summaryStats.total }} {{ t("Groups") }}</div>
								<div class="text-secondary small">{{ summaryStats.openCount }} {{ t("Open") }}</div>
							</div>
						</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="row align-items-center">
							<div class="col-auto">
								<span class="bg-azure text-white avatar">
									<i class="ti ti-file-invoice fs-2"></i>
								</span>
							</div>
							<div class="col">
								<div class="font-weight-medium">{{ summaryStats.totalPis }} {{ t("Associated PIs") }}</div>
								<div class="text-secondary small">{{ t("Across all groups") }}</div>
							</div>
						</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-6">
				<div class="card card-sm">
					<div class="card-body">
						<div class="row align-items-center">
							<div class="col-auto">
								<span class="bg-green text-white avatar">
									<i class="ti ti-currency-dollar fs-2"></i>
								</span>
							</div>
							<div class="col">
								<div class="font-weight-medium font-monospace">{{ fm(summaryStats.totalAgreed, "USD") }}</div>
								<div class="text-secondary small">{{ t("Total Agreed Value") }}</div>
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Main Card Table -->
		<div class="card">
			<div class="card-header d-flex align-items-center gap-2">
				<div class="card-title m-0 fw-bold">{{ t("PI Groups") }}</div>
				<div class="ms-auto d-flex align-items-center gap-2">
					<select v-model="statusFilter" class="form-select form-select-sm style-select" style="width: 130px">
						<option value="">{{ t("All Statuses") }}</option>
						<option value="Open">{{ t("Open") }}</option>
						<option value="Closed">{{ t("Closed") }}</option>
					</select>
					<button type="button" class="btn btn-primary btn-sm" @click="openNew">
						<i class="ti ti-plus me-1"></i>{{ t("New PI Group") }}
					</button>
				</div>
			</div>

			<ListToolbar v-model="search" :placeholder="t('Search by code, title or vendor…') + '  ⌘K'" :count="filteredRows.length" @search="load" />

			<div class="table-responsive">
				<table class="table table-vcenter table-hover">
					<thead>
						<tr>
							<th>{{ t("Code") }}</th>
							<th>{{ t("Group Name / Title") }}</th>
							<th>{{ t("Vendor Restriction") }}</th>
							<th>{{ t("Status") }}</th>
							<th class="text-end">{{ t("Linked PIs") }}</th>
							<th class="text-end">{{ t("Agreed Total") }}</th>
							<th class="text-end">{{ t("Actions") }}</th>
						</tr>
					</thead>
					<tbody>
						<SkeletonRows v-if="loading" :cols="7" :rows="6" />
						<tr v-for="r in filteredRows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
							<td class="font-monospace text-primary fw-bold">{{ r.code || r.name }}</td>
							<td class="fw-semibold">{{ groupTitle(r) }}</td>
							<td>
								<span v-if="r.pi_vendor" class="badge bg-secondary-lt">
									<i class="ti ti-building me-1"></i>{{ r.pi_vendor_name || r.pi_vendor }}
								</span>
								<span v-else class="text-secondary italic">{{ t("Any Vendor") }}</span>
							</td>
							<td>
								<span class="badge" :class="r.status === 'Closed' ? 'bg-secondary-lt' : 'bg-success-lt'">
									{{ r.status || "Open" }}
								</span>
							</td>
							<td class="text-end">
								<span class="badge bg-azure-lt font-monospace px-2">{{ r.pi_count || 0 }} PIs</span>
							</td>
							<td class="text-end font-monospace fw-semibold">
								{{ fm(r.agreed_total, "USD") }}
							</td>
							<td class="text-end" @click.stop>
								<div class="btn-list flex-nowrap justify-content-end">
									<button type="button" class="btn btn-outline-secondary btn-sm" :title="t('Assign PIs')" @click="openAssign(r)">
										<i class="ti ti-link me-1"></i>{{ t("Assign") }}
									</button>
									<button type="button" class="btn btn-outline-secondary btn-sm" :title="t('Edit')" @click="openEdit(r.name)">
										<i class="ti ti-edit"></i>
									</button>
									<button type="button" class="btn btn-ghost-danger btn-sm" :title="t('Delete')" @click="deleteGroup(r)">
										<i class="ti ti-trash"></i>
									</button>
								</div>
							</td>
						</tr>
					</tbody>
				</table>
				<EmptyState
					v-if="!loading && !filteredRows.length"
					icon="ti-tags"
					:title="t('No PI Groups Found')"
					:subtitle="t('Create your first PI group to organize and bundle proforma invoices together.')"
				/>
			</div>
		</div>
	</div>

	<!-- Create / Edit Modal -->
	<div v-if="modalOpen" class="modal d-block" tabindex="-1" style="background: rgba(0, 0, 0, 0.5)">
		<div class="modal-dialog modal-lg modal-dialog-centered">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ form.name ? t("Edit PI Group") : t("New PI Group") }}</h5>
					<button type="button" class="btn-close" @click="closeModal"></button>
				</div>
				<div class="modal-body">
					<div class="row g-3">
						<div class="col-md-6">
							<label class="form-label small mb-1">{{ t("Group Reference Code") }}</label>
							<input v-model="form.code" type="text" class="form-control form-control-sm" :placeholder="t('e.g. PI 3 Fair or IPG-2026-00001')" />
						</div>
						<div class="col-md-6">
							<label class="form-label small mb-1">{{ t("Group Title / Name") }} *</label>
							<input v-model="form.group_name" type="text" class="form-control form-control-sm" :placeholder="t('e.g. Fair Exports Batch 3')" />
						</div>
						<div class="col-md-6">
							<label class="form-label small mb-1">{{ t("Vendor Restriction") }}</label>
							<Typeahead
								v-model="form.pi_vendor"
								:display="form.pi_vendor ? `${form.pi_vendor_name || form.pi_vendor}` : ''"
								:search="searchSuppliers"
								:placeholder="t('Search supplier… (optional)')"
								@pick="(s) => { form.pi_vendor = s.name; form.pi_vendor_name = s.supplier_name || s.name; }"
								@clear="() => { form.pi_vendor = ''; form.pi_vendor_name = ''; }"
							/>
							<div class="form-text small text-secondary">{{ t("If set, only proforma invoices from this vendor may be assigned to this group.") }}</div>
						</div>
						<div class="col-md-6">
							<label class="form-label small mb-1">{{ t("Status") }}</label>
							<select v-model="form.status" class="form-select form-select-sm">
								<option value="Open">{{ t("Open") }}</option>
								<option value="Closed">{{ t("Closed") }}</option>
							</select>
						</div>
						<div class="col-12">
							<label class="form-label small mb-1">{{ t("Notes & Remarks") }}</label>
							<textarea v-model="form.notes" rows="3" class="form-control form-control-sm" :placeholder="t('Additional notes about this PI group…')"></textarea>
						</div>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-outline-secondary" @click="closeModal">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary" :disabled="saving || !canSave" @click="saveGroup">
						<span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-device-floppy me-1"></i>{{ t("Save PI Group") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<!-- Detail Drawer / Modal (Organized as in pi_groups_detailed_list.md) -->
	<div v-if="detailOpen" class="modal d-block" tabindex="-1" style="background: rgba(0, 0, 0, 0.5)">
		<div class="modal-dialog modal-xl modal-dialog-centered modal-dialog-scrollable">
			<div class="modal-content">
				<div class="modal-header bg-light py-3">
					<div>
						<div class="d-flex align-items-center gap-2">
							<h4 class="modal-title mb-0 font-monospace text-primary">
								{{ detailGroup?.code || detailGroup?.name }}
							</h4>
							<span class="badge" :class="detailGroup?.status === 'Closed' ? 'bg-secondary-lt' : 'bg-success-lt'">
								{{ detailGroup?.status || 'Open' }}
							</span>
						</div>
						<div v-if="detailGroup?.group_name" class="text-secondary small fw-semibold mt-0.5">
							{{ detailGroup.group_name }}
						</div>
					</div>
					<div class="ms-auto d-flex align-items-center gap-2">
						<button type="button" class="btn btn-outline-secondary btn-sm" @click="assignFromDetail">
							<i class="ti ti-link me-1"></i>{{ t("Assign PIs") }}
						</button>
						<button type="button" class="btn btn-outline-secondary btn-sm" @click="editFromDetail">
							<i class="ti ti-edit me-1"></i>{{ t("Edit Group") }}
						</button>
						<button type="button" class="btn-close" @click="closeDetail"></button>
					</div>
				</div>

				<div class="modal-body p-4">
					<div v-if="detailLoading" class="text-center text-secondary py-5">
						<div class="spinner-border text-primary mb-2"></div>
						<div>{{ t("Loading PI Group details…") }}</div>
					</div>
					<template v-else-if="detailGroup">
						<!-- Overview & Vendor Card -->
						<div class="row g-3 mb-4">
							<div class="col-md-4">
								<div class="card card-body bg-light-lt py-2 px-3">
									<div class="text-secondary small fw-semibold text-uppercase mb-1">{{ t("Vendor / Supplier") }}</div>
									<div class="fw-bold text-dark">
										<span v-if="detailGroup.pi_vendor" class="badge bg-blue-lt fs-6">
											<i class="ti ti-building me-1"></i>{{ detailGroup.pi_vendor_name || detailGroup.pi_vendor }}
										</span>
										<span v-else class="text-secondary italic">{{ t("No Vendor Restriction (Any Vendor)") }}</span>
									</div>
								</div>
							</div>
							<div class="col-md-4">
								<div class="card card-body bg-light-lt py-2 px-3">
									<div class="text-secondary small fw-semibold text-uppercase mb-1">{{ t("Created / Updated") }}</div>
									<div class="small font-monospace text-dark">
										<div>{{ t("Created") }}: {{ formatDate(detailGroup.creation) }}</div>
										<div>{{ t("Updated") }}: {{ formatDate(detailGroup.modified) }}</div>
									</div>
								</div>
							</div>
							<div class="col-md-4">
								<div class="card card-body bg-light-lt py-2 px-3">
									<div class="text-secondary small fw-semibold text-uppercase mb-1">{{ t("Notes & Remarks") }}</div>
									<div class="small text-dark">{{ detailGroup.notes || detailGroup.remarks || "—" }}</div>
								</div>
							</div>
						</div>

						<!-- KPI Totals Bar -->
						<div class="row g-2 mb-4">
							<div class="col-sm-6 col-md-3">
								<div class="card p-2 text-center border-0 bg-primary-lt">
									<div class="text-secondary small fw-semibold">{{ t("Agreed Total") }}</div>
									<div class="h3 mb-0 font-monospace text-primary fw-bold">
										{{ fm(detailTotals.agreed_total, "USD") }}
									</div>
								</div>
							</div>
							<div class="col-sm-6 col-md-3">
								<div class="card p-2 text-center border-0 bg-azure-lt">
									<div class="text-secondary small fw-semibold">{{ t("Docs Total") }}</div>
									<div class="h3 mb-0 font-monospace text-azure fw-bold">
										{{ fm(detailTotals.docs_total, "USD") }}
									</div>
								</div>
							</div>
							<div class="col-sm-6 col-md-3">
								<div class="card p-2 text-center border-0 bg-warning-lt">
									<div class="text-secondary small fw-semibold">{{ t("Cash Difference") }}</div>
									<div class="h3 mb-0 font-monospace text-warning fw-bold">
										{{ fm(detailTotals.cash_difference, "USD") }}
									</div>
								</div>
							</div>
							<div class="col-sm-6 col-md-3">
								<div class="card p-2 text-center border-0 bg-purple-lt">
									<div class="text-secondary small fw-semibold">{{ t("Associated Items") }}</div>
									<div class="h3 mb-0 font-monospace text-purple fw-bold">
										{{ detailTotals.pi_count || 0 }} PIs / {{ detailTotals.ci_count || 0 }} CIs / {{ detailTotals.container_count || 0 }} Cont.
									</div>
								</div>
							</div>
						</div>

						<!-- Tabs Header for Navigation -->
						<ul class="nav nav-tabs border-bottom mb-3">
							<li class="nav-item">
								<button
									type="button"
									class="nav-link"
									:class="{ active: activeTab === 'pis' }"
									@click="activeTab = 'pis'"
								>
									<i class="ti ti-file-invoice me-1"></i>{{ t("Proforma Invoices") }} ({{ detailPis.length }})
								</button>
							</li>
							<li class="nav-item">
								<button
									type="button"
									class="nav-link"
									:class="{ active: activeTab === 'cis' }"
									@click="activeTab = 'cis'"
								>
									<i class="ti ti-truck-delivery me-1"></i>{{ t("Commercial Invoices & Containers") }} ({{ detailCis.length }})
								</button>
							</li>
							<li class="nav-item" v-if="detailPos.length">
								<button
									type="button"
									class="nav-link"
									:class="{ active: activeTab === 'pos' }"
									@click="activeTab = 'pos'"
								>
									<i class="ti ti-shopping-cart me-1"></i>{{ t("ERPNext Purchase Orders") }} ({{ detailPos.length }})
								</button>
							</li>
						</ul>

						<!-- TAB 1: Associated Proforma Invoices (PIs) with detailed card hierarchy -->
						<div v-if="activeTab === 'pis'">
							<div v-if="!detailPis.length">
								<EmptyState
									icon="ti-file-off"
									:title="t('No Proforma Invoices Linked')"
									:subtitle="t('Click Assign PIs to link proforma invoices to this group.')"
									compact
								/>
							</div>
							<div v-else class="d-flex flex-column gap-3">
								<div v-for="pi in detailPis" :key="pi.name" class="card border">
									<div class="card-header bg-light-subtle d-flex align-items-center flex-wrap gap-2 py-2">
										<div
											class="fw-bold font-monospace text-primary fs-5 text-decoration-underline-hover"
											style="cursor: pointer"
											:title="t('Open Proforma Invoice: ') + pi.name"
											@click="openPi(pi.name)"
										>
											<i class="ti ti-file-description me-1"></i>{{ pi.supplier_pi_ref || pi.name }}
										</div>
										<span class="badge" :class="getStatusBadgeClass('Proforma Invoice', pi.status)">
											{{ pi.status }}
										</span>
										<span
											v-if="pi.supplier_name"
											class="badge bg-secondary-lt text-dark font-monospace ms-auto"
											style="cursor: pointer"
											:title="t('Filter proformas by supplier: ') + pi.supplier_name"
											@click="openProformasBySupplier(pi.supplier)"
										>
											<i class="ti ti-building me-1"></i>{{ pi.supplier_name }}
										</span>
									</div>
									<div class="card-body py-3">
										<div class="row g-3">
											<div class="col-md-3">
												<div class="text-secondary small">{{ t("PI Date") }}</div>
												<div class="fw-semibold">{{ formatDate(pi.pi_date) }}</div>
											</div>
											<div class="col-md-3">
												<div class="text-secondary small">{{ t("Currency / Incoterm") }}</div>
												<div class="fw-semibold">
													{{ pi.currency || "USD" }}
													<span v-if="pi.incoterm" class="badge bg-info-lt ms-1">{{ pi.incoterm }}</span>
												</div>
											</div>
											<div class="col-md-3">
												<div class="text-secondary small">{{ t("Ports (Loading → Discharge)") }}</div>
												<div class="small fw-semibold">
													{{ pi.port_of_loading || "N/A" }} → {{ pi.port_of_discharge || "N/A" }}
												</div>
											</div>
											<div class="col-md-3">
												<div class="text-secondary small">{{ t("Agreed Total") }}</div>
												<div class="fw-bold font-monospace text-success fs-5">
													{{ fm(pi.agreed_total, pi.currency) }}
												</div>
											</div>
										</div>

										<div class="row g-3 mt-1 pt-2 border-top">
											<div class="col-md-4">
												<span class="text-secondary small me-2">{{ t("Docs Total") }}:</span>
												<span class="font-monospace fw-semibold">{{ fm(pi.docs_total, pi.currency) }}</span>
											</div>
											<div class="col-md-4">
												<span class="text-secondary small me-2">{{ t("Cash Difference") }}:</span>
												<span class="font-monospace fw-semibold text-warning">{{ fm(pi.cash_difference, pi.currency) }}</span>
											</div>
										</div>

										<!-- Nested Linked Commercial Invoices & Containers -->
										<div v-if="pi.linked_cis && pi.linked_cis.length" class="mt-3 pt-2 border-top bg-light-lt rounded p-3">
											<div class="fw-bold small text-secondary text-uppercase mb-2">
												<i class="ti ti-truck-delivery me-1"></i>{{ t("Linked Commercial Invoices & Containers") }}
											</div>
											<div v-for="ci in pi.linked_cis" :key="ci.name" class="border rounded bg-white p-2 mb-2">
												<div class="d-flex align-items-center justify-content-between flex-wrap gap-2">
													<div
														class="fw-bold font-monospace text-dark text-decoration-underline-hover"
														style="cursor: pointer"
														:title="t('Open Commercial Invoice: ') + ci.name"
														@click="openCi(ci.name)"
													>
														<i class="ti ti-file-check me-1 text-primary"></i>CI: {{ ci.ci_number || ci.name }}
														<span class="text-secondary small font-normal ms-2">({{ formatDate(ci.ci_date) }})</span>
													</div>
													<span class="badge" :class="getStatusBadgeClass('Commercial Invoice', ci.status)">
														{{ ci.status }}
													</span>
												</div>
												<div class="small text-secondary mt-1">
													Incoterm: {{ ci.incoterm || "N/A" }} | ETD: {{ formatDate(ci.etd) }} | ETA: {{ formatDate(ci.eta) }}
												</div>
												<!-- Containers under CI -->
												<div v-if="ci.containers && ci.containers.length" class="mt-2">
													<div class="small fw-semibold text-secondary mb-1">{{ t("Containers") }}:</div>
													<div class="d-flex flex-wrap gap-1">
														<span
															v-for="cnt in ci.containers"
															:key="cnt.name"
															class="badge bg-azure-lt font-monospace py-1 px-2"
															style="cursor: pointer"
															:title="t('Open Container: ') + (cnt.container_number || cnt.name)"
															@click.stop="openContainer(cnt.name)"
														>
															<i class="ti ti-box me-1"></i>{{ cnt.container_number || cnt.name }} ({{ cnt.status }})
														</span>
													</div>
												</div>
											</div>
										</div>
									</div>
								</div>
							</div>
						</div>

						<!-- TAB 2: Commercial Invoices & Containers -->
						<div v-if="activeTab === 'cis'">
							<div v-if="!detailCis.length">
								<EmptyState
									icon="ti-truck-off"
									:title="t('No Commercial Invoices Linked')"
									:subtitle="t('Commercial invoices linked to this group will appear here.')"
									compact
								/>
							</div>
							<div v-else class="table-responsive">
								<table class="table table-vcenter">
									<thead>
										<tr>
											<th>{{ t("CI Number") }}</th>
											<th>{{ t("Date") }}</th>
											<th>{{ t("Status") }}</th>
											<th>{{ t("Supplier") }}</th>
											<th>{{ t("ETD / ETA") }}</th>
											<th>{{ t("Containers") }}</th>
											<th class="text-end">{{ t("Agreed Total") }}</th>
										</tr>
									</thead>
									<tbody>
										<tr v-for="ci in detailCis" :key="ci.name" style="cursor: pointer" @click="openCi(ci.name)">
											<td class="font-monospace fw-bold text-primary text-decoration-underline-hover">{{ ci.ci_number || ci.name }}</td>
											<td class="text-nowrap">{{ formatDate(ci.ci_date) }}</td>
											<td><span class="badge" :class="getStatusBadgeClass('Commercial Invoice', ci.status)">{{ ci.status }}</span></td>
											<td>
												<span
													class="badge bg-secondary-lt text-dark font-monospace"
													style="cursor: pointer"
													:title="ci.supplier_name || ci.supplier"
													@click.stop="openProformasBySupplier(ci.supplier)"
												>
													{{ ci.supplier_name || ci.supplier }}
												</span>
											</td>
											<td class="small font-monospace">{{ formatDate(ci.etd) }} / {{ formatDate(ci.eta) }}</td>
											<td>
												<div v-if="ci.containers && ci.containers.length" class="d-flex flex-wrap gap-1">
													<span
														v-for="cnt in ci.containers"
														:key="cnt.name"
														class="badge bg-azure-lt font-monospace"
														style="cursor: pointer"
														:title="t('Open Container: ') + (cnt.container_number || cnt.name)"
														@click.stop="openContainer(cnt.name)"
													>
														<i class="ti ti-box me-1"></i>{{ cnt.container_number || cnt.name }}
													</span>
												</div>
												<span v-else class="text-secondary small italic">{{ t("No containers") }}</span>
											</td>
											<td class="text-end font-monospace fw-semibold">{{ fm(ci.agreed_total, ci.currency) }}</td>
										</tr>
									</tbody>
								</table>
							</div>
						</div>

						<!-- TAB 3: ERPNext Purchase Orders -->
						<div v-if="activeTab === 'pos'">
							<div class="table-responsive">
								<table class="table table-vcenter">
									<thead>
										<tr>
											<th>{{ t("Purchase Order") }}</th>
											<th>{{ t("Date") }}</th>
											<th>{{ t("Supplier") }}</th>
											<th>{{ t("Status") }}</th>
											<th class="text-end">{{ t("Grand Total") }}</th>
										</tr>
									</thead>
									<tbody>
										<tr v-for="po in detailPos" :key="po.name">
											<td class="font-monospace fw-bold text-primary">{{ po.name }}</td>
											<td class="text-nowrap">{{ formatDate(po.transaction_date) }}</td>
											<td>{{ po.supplier_name || po.supplier }}</td>
											<td><span class="badge bg-info-lt">{{ po.status }}</span></td>
											<td class="text-end font-monospace fw-semibold">{{ fm(po.grand_total, po.currency) }}</td>
										</tr>
									</tbody>
								</table>
							</div>
						</div>
					</template>
				</div>

				<div class="modal-footer bg-light py-2">
					<button type="button" class="btn btn-outline-danger me-auto" @click="deleteGroup(detailGroup)">
						<i class="ti ti-trash me-1"></i>{{ t("Delete Group") }}
					</button>
					<button type="button" class="btn btn-primary" @click="closeDetail">{{ t("Close") }}</button>
				</div>
			</div>
		</div>
	</div>

	<!-- Assign PIs Modal -->
	<div v-if="assignOpen" class="modal d-block" tabindex="-1" style="background: rgba(0, 0, 0, 0.5); z-index: 1060">
		<div class="modal-dialog modal-lg modal-dialog-centered">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">
						{{ t("Assign Proforma Invoices to") }} <span class="font-monospace text-primary">{{ assignGroup?.code || assignGroup?.group_name || assignGroup?.name }}</span>
					</h5>
					<button type="button" class="btn-close" @click="closeAssign"></button>
				</div>
				<div class="modal-body">
					<div v-if="assignLoading" class="text-center text-secondary py-5">
						<div class="spinner-border text-primary mb-2"></div>
						<div>{{ t("Loading eligible proformas…") }}</div>
					</div>
					<template v-else>
						<div class="row g-2 align-items-center mb-3">
							<div class="col">
								<input v-model="assignSearch" type="search" class="form-control form-control-sm" :placeholder="t('Filter by PI ref, supplier…')" />
							</div>
							<div class="col-auto">
								<div class="btn-group btn-group-sm">
									<button type="button" class="btn btn-outline-secondary" @click="selectAll">{{ t("Select All") }}</button>
									<button type="button" class="btn btn-outline-secondary" @click="clearAll">{{ t("Clear All") }}</button>
								</div>
							</div>
							<div class="col-auto">
								<span class="badge bg-azure-lt fs-6 font-monospace">{{ checkedCount }} / {{ assignRows.length }} {{ t("Selected") }}</span>
							</div>
						</div>

						<div class="table-responsive" style="max-height: 400px; overflow-y: auto">
							<table class="table table-sm table-vcenter table-hover">
								<thead class="sticky-top bg-white border-bottom">
									<tr>
										<th style="width: 36px"></th>
										<th>{{ t("PI Ref / No.") }}</th>
										<th>{{ t("PI Date") }}</th>
										<th>{{ t("Supplier") }}</th>
										<th>{{ t("Status") }}</th>
										<th class="text-end">{{ t("Agreed Total") }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="pi in filteredAssignRows" :key="pi.name" style="cursor: pointer" @click="assignChecked[pi.name] = !assignChecked[pi.name]">
										<td @click.stop>
											<input v-model="assignChecked[pi.name]" type="checkbox" class="form-check-input" />
										</td>
										<td class="font-monospace fw-bold text-primary">{{ pi.supplier_pi_ref || pi.name }}</td>
										<td class="text-nowrap">{{ formatDate(pi.pi_date) }}</td>
										<td>{{ pi.supplier_name || pi.supplier }}</td>
										<td><span class="badge" :class="getStatusBadgeClass('Proforma Invoice', pi.status)">{{ pi.status }}</span></td>
										<td class="text-end font-monospace fw-semibold">{{ fm(pi.agreed_total, pi.currency) }}</td>
									</tr>
								</tbody>
							</table>
						</div>
						<EmptyState
							v-if="!filteredAssignRows.length"
							icon="ti-file-off"
							:title="t('No eligible proformas found')"
							:subtitle="assignGroup?.pi_vendor ? t('This group is restricted to supplier {0} — no matching unlinked PIs available.', [assignGroup.pi_vendor_name || assignGroup.pi_vendor]) : t('There are no available proformas to link.')"
							compact
						/>
					</template>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-outline-secondary" @click="closeAssign">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary" :disabled="assignSaving || assignLoading" @click="saveAssign">
						<span v-if="assignSaving" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-link me-1"></i>{{ t("Save Assignments") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
