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

const fm = (v, ccy) => formatMoney(v, ccy || "", user.value.language);

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

function groupTitle(row) {
	return row.group_name || row.title || row.code;
}

// ---- Create / edit modal ----
const modalOpen = ref(false);
const saving = ref(false);
const form = ref(null);

function blankForm() {
	return {
		name: "",
		code: "",
		group_name: "",
		pi_vendor: "",
		pi_vendor_name: "",
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
		notes: row.notes || "",
		modified: row.modified || "",
	};
	modalOpen.value = true;
}

async function openEdit(name) {
	loading.value = true;
	try {
		const detail = await importsApi.piGroupDetail(name);
		const g = detail.group || {};
		form.value = {
			name: g.name,
			code: g.code || "",
			group_name: g.group_name || "",
			pi_vendor: g.pi_vendor || "",
			pi_vendor_name: g.pi_vendor_name || g.pi_vendor || "",
			notes: g.notes || "",
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
	return !!(f.code || "").trim();
});

async function saveGroup() {
	if (!canSave.value) return;
	saving.value = true;
	try {
		const res = await importsApi.savePiGroup(
			{
				name: form.value.name || undefined,
				code: form.value.code.trim(),
				group_name: form.value.group_name,
				pi_vendor: form.value.pi_vendor,
				notes: form.value.notes,
				modified: form.value.modified || undefined,
			},
			activeCompany.value,
		);
		toast.success(t("PI Group saved"));
		modalOpen.value = false;
		await load();
		// If the detail drawer for this group is open, refresh it too.
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
	const ok = await confirm({
		title: t("Delete PI Group"),
		body: t("Delete group") + " " + (groupTitle(row) || row.code) + "? " + t("This cannot be undone."),
		confirmLabel: t("Delete"),
		cancelLabel: t("Cancel"),
		danger: true,
	});
	if (!ok) return;
	try {
		await importsApi.deletePiGroup(row.name, activeCompany.value);
		toast.success(t("PI Group deleted."));
		load();
	} catch (err) {
		toast.error(err?.message || t("Could not delete the PI group."));
	}
}

// ---- Detail drawer ----
const detailOpen = ref(false);
const detailLoading = ref(false);
const detailGroup = ref(null);
const detailPis = ref([]);
const detailPiCount = ref(0);

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	try {
		const detail = await importsApi.piGroupDetail(name);
		detailGroup.value = detail.group || null;
		detailPis.value = detail.pis || [];
		detailPiCount.value = detail.pi_count ?? detailPis.value.length;
	} catch (err) {
		toast.error(err?.message || t("Failed to load the PI group."));
		detailOpen.value = false;
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	detailOpen.value = false;
	detailGroup.value = null;
	detailPis.value = [];
}

function editFromDetail() {
	if (!detailGroup.value) return;
	openEditFromRow({
		name: detailGroup.value.name,
		code: detailGroup.value.code,
		group_name: detailGroup.value.group_name,
		pi_vendor: detailGroup.value.pi_vendor,
		notes: detailGroup.value.notes,
		modified: detailGroup.value.modified,
	});
}

// ---- Assign PIs modal ----
const assignOpen = ref(false);
const assignLoading = ref(false);
const assignSaving = ref(false);
const assignGroup = ref(null);
const assignRows = ref([]);
const assignChecked = ref({});

async function openAssign(row) {
	assignGroup.value = row;
	assignOpen.value = true;
	assignLoading.value = true;
	assignChecked.value = {};
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

function assignFromDetail() {
	if (!detailGroup.value) return;
	openAssign({
		name: detailGroup.value.name,
		code: detailGroup.value.code,
		group_name: detailGroup.value.group_name,
		pi_vendor: detailGroup.value.pi_vendor,
	});
}

function closeAssign() {
	if (!assignSaving.value) assignOpen.value = false;
}

function selectAll() {
	for (const pi of assignRows.value) assignChecked.value[pi.name] = true;
}
function clearAll() {
	for (const pi of assignRows.value) assignChecked.value[pi.name] = false;
}

const checkedCount = computed(() => Object.values(assignChecked.value).filter(Boolean).length);

async function saveAssign() {
	if (!assignGroup.value) return;
	assignSaving.value = true;
	try {
		const piNames = Object.keys(assignChecked.value).filter((k) => assignChecked.value[k]);
		await importsApi.assignPisToGroup(assignGroup.value.name, piNames, activeCompany.value);
		toast.success(t("Proformas assigned"));
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
	<div class="card">
		<div class="card-header d-flex align-items-center gap-2">
			<div class="card-title m-0">{{ t("PI Groups") }}</div>
			<button type="button" class="btn btn-primary btn-sm ms-auto" @click="openNew">
				<i class="ti ti-plus me-1"></i>{{ t("New PI Group") }}
			</button>
		</div>

		<ListToolbar v-model="search" :placeholder="t('Code, name or vendor') + '  ⌘K'" :count="rows.length" @search="load" />

		<div class="table-responsive">
			<table class="table table-vcenter">
				<thead>
					<tr>
						<th>{{ t("Code") }}</th>
						<th>{{ t("Name") }}</th>
						<th>{{ t("Vendor") }}</th>
						<th class="text-end">{{ t("Linked PIs") }}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					<SkeletonRows v-if="loading" :cols="5" :rows="6" />
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
						<td class="font-monospace text-primary">{{ r.code || r.name }}</td>
						<td class="fw-semibold">{{ groupTitle(r) || "—" }}</td>
						<td>
							<span v-if="r.pi_vendor" class="badge bg-secondary-lt">{{ r.pi_vendor_name || r.pi_vendor }}</span>
							<span v-else class="text-secondary">—</span>
						</td>
						<td class="text-end">
							<span class="badge bg-azure-lt font-monospace">{{ r.pi_count || 0 }}</span>
						</td>
						<td class="text-end" @click.stop>
							<button type="button" class="btn btn-outline-secondary btn-sm me-1" :title="t('Assign PIs')" @click="openAssign(r)">
								<i class="ti ti-link"></i>
							</button>
							<button type="button" class="btn btn-outline-secondary btn-sm me-1" :title="t('Edit')" @click="openEdit(r.name)">
								<i class="ti ti-edit"></i>
							</button>
							<button type="button" class="btn btn-ghost-secondary btn-sm" :title="t('Delete')" @click="deleteGroup(r)">
								<i class="ti ti-trash"></i>
							</button>
						</td>
					</tr>
				</tbody>
			</table>
			<EmptyState v-if="!loading && !rows.length" :title="t('No PI Groups')" :subtitle="t('Create your first PI group to bundle proformas together.')" />
		</div>
	</div>

	<!-- Create / edit modal -->
	<div v-if="modalOpen" class="modal d-block" tabindex="-1" style="background: rgba(0,0,0,0.4)">
		<div class="modal-dialog modal-lg modal-dialog-centered">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ form.name ? t("Edit PI Group") : t("New PI Group") }}</h5>
					<button type="button" class="btn-close" @click="closeModal"></button>
				</div>
				<div class="modal-body">
					<div class="row g-3">
						<div class="col-md-6">
							<label class="form-label small mb-1">{{ t("Code") }} *</label>
							<input v-model="form.code" type="text" class="form-control form-control-sm" />
						</div>
						<div class="col-md-6">
							<label class="form-label small mb-1">{{ t("Name") }}</label>
							<input v-model="form.group_name" type="text" class="form-control form-control-sm" />
						</div>
						<div class="col-md-6">
							<label class="form-label small mb-1">{{ t("Vendor restriction") }}</label>
							<Typeahead
								v-model="form.pi_vendor"
								:display="form.pi_vendor ? `${form.pi_vendor_name || form.pi_vendor}` : ''"
								:search="searchSuppliers"
								:placeholder="t('Search supplier… (optional)')"
								@pick="(s) => { form.pi_vendor = s.name; form.pi_vendor_name = s.supplier_name || s.name; }"
								@clear="() => { form.pi_vendor = ''; form.pi_vendor_name = ''; }"
							/>
							<div class="form-text small">{{ t("Leave empty to allow proformas from any vendor.") }}</div>
						</div>
						<div class="col-12">
							<label class="form-label small mb-1">{{ t("Notes") }}</label>
							<textarea v-model="form.notes" rows="3" class="form-control form-control-sm"></textarea>
						</div>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-outline-secondary" @click="closeModal">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary" :disabled="saving || !canSave" @click="saveGroup">
						<span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>{{ t("Save") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<!-- Detail drawer -->
	<div v-if="detailOpen" class="modal d-block" tabindex="-1" style="background: rgba(0,0,0,0.4)">
		<div class="modal-dialog modal-lg modal-dialog-centered">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">
						<span class="font-monospace">{{ detailGroup?.code || "" }}</span>
						<span v-if="detailGroup?.group_name"> — {{ detailGroup.group_name }}</span>
					</h5>
					<button type="button" class="btn-close" @click="closeDetail"></button>
				</div>
				<div class="modal-body">
					<div v-if="detailLoading" class="text-center text-secondary py-4">
						<span class="spinner-border spinner-border-sm me-2"></span>{{ t("Loading…") }}
					</div>
					<template v-else-if="detailGroup">
						<div class="row g-3 mb-3">
							<div class="col-md-4">
								<div class="text-secondary small">{{ t("Vendor restriction") }}</div>
								<div>
									<span v-if="detailGroup.pi_vendor" class="badge bg-secondary-lt">{{ detailGroup.pi_vendor_name || detailGroup.pi_vendor }}</span>
									<span v-else class="text-secondary">{{ t("Any vendor") }}</span>
								</div>
							</div>
							<div class="col-md-4">
								<div class="text-secondary small">{{ t("Linked PIs") }}</div>
								<div class="font-monospace">{{ detailPiCount }}</div>
							</div>
							<div class="col-md-4" v-if="detailGroup.notes">
								<div class="text-secondary small">{{ t("Notes") }}</div>
								<div class="small">{{ detailGroup.notes }}</div>
							</div>
						</div>

						<div class="d-flex align-items-center justify-content-between mb-2">
							<label class="form-label small mb-0">{{ t("Linked Proforma Invoices") }}</label>
							<button type="button" class="btn btn-outline-secondary btn-sm" @click="assignFromDetail">
								<i class="ti ti-link me-1"></i>{{ t("Assign PIs") }}
							</button>
						</div>
						<div class="table-responsive">
							<table class="table table-sm table-vcenter">
								<thead>
									<tr>
										<th>{{ t("PI") }}</th>
										<th>{{ t("PI Date") }}</th>
										<th>{{ t("Supplier") }}</th>
										<th>{{ t("Status") }}</th>
										<th class="text-end">{{ t("Agreed total") }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="pi in detailPis" :key="pi.name">
										<td class="font-monospace text-primary">{{ pi.name }}</td>
										<td class="text-nowrap">{{ formatDate(pi.pi_date) }}</td>
										<td>{{ pi.supplier }}</td>
										<td><span class="badge" :class="getStatusBadgeClass('Proforma Invoice', pi.status)">{{ pi.status }}</span></td>
										<td class="text-end font-monospace">{{ fm(pi.agreed_total, pi.currency) }}</td>
									</tr>
								</tbody>
							</table>
							<EmptyState v-if="!detailPis.length" :title="t('No proformas linked yet')" :subtitle="t('Use Assign PIs to link proformas to this group.')" compact />
						</div>
					</template>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-outline-secondary" @click="editFromDetail">
						<i class="ti ti-edit me-1"></i>{{ t("Edit") }}
					</button>
					<button type="button" class="btn btn-primary" @click="closeDetail">{{ t("Close") }}</button>
				</div>
			</div>
		</div>
	</div>

	<!-- Assign PIs modal -->
	<div v-if="assignOpen" class="modal d-block" tabindex="-1" style="background: rgba(0,0,0,0.4); z-index: 1060">
		<div class="modal-dialog modal-lg modal-dialog-centered">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">
						{{ t("Assign PIs to") }} <span class="font-monospace">{{ assignGroup?.code || assignGroup?.name }}</span>
					</h5>
					<button type="button" class="btn-close" @click="closeAssign"></button>
				</div>
				<div class="modal-body">
					<div v-if="assignLoading" class="text-center text-secondary py-4">
						<span class="spinner-border spinner-border-sm me-2"></span>{{ t("Loading…") }}
					</div>
					<template v-else>
						<div class="d-flex align-items-center justify-content-between mb-2">
							<div class="small text-secondary">{{ t("Selected") }}: <strong class="font-monospace">{{ checkedCount }}</strong> / {{ assignRows.length }}</div>
							<div class="btn-list">
								<button type="button" class="btn btn-ghost-secondary btn-sm" @click="selectAll">{{ t("Select all") }}</button>
								<button type="button" class="btn btn-ghost-secondary btn-sm" @click="clearAll">{{ t("Clear all") }}</button>
							</div>
						</div>
						<div class="table-responsive" style="max-height: 420px; overflow-y: auto">
							<table class="table table-sm table-vcenter">
								<thead>
									<tr>
										<th style="width: 36px"></th>
										<th>{{ t("PI") }}</th>
										<th>{{ t("PI Date") }}</th>
										<th>{{ t("Supplier") }}</th>
										<th>{{ t("Status") }}</th>
										<th class="text-end">{{ t("Agreed total") }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="pi in assignRows" :key="pi.name">
										<td>
											<input v-model="assignChecked[pi.name]" type="checkbox" class="form-check-input" />
										</td>
										<td class="font-monospace text-primary">{{ pi.name }}</td>
										<td class="text-nowrap">{{ formatDate(pi.pi_date) }}</td>
										<td>{{ pi.supplier }}</td>
										<td><span class="badge" :class="getStatusBadgeClass('Proforma Invoice', pi.status)">{{ pi.status }}</span></td>
										<td class="text-end font-monospace">{{ fm(pi.agreed_total, pi.currency) }}</td>
									</tr>
								</tbody>
							</table>
						</div>
						<EmptyState
							v-if="!assignRows.length"
							:title="t('No eligible proformas')"
							:subtitle="assignGroup?.pi_vendor ? t('This group restricts proformas to a single vendor — none match.') : t('There are no proformas available to link yet.')"
							compact
						/>
					</template>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-outline-secondary" @click="closeAssign">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary" :disabled="assignSaving || assignLoading" @click="saveAssign">
						<span v-if="assignSaving" class="spinner-border spinner-border-sm me-1"></span>{{ t("Save") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
