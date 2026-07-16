<script setup>
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, todayIso } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { useToast } from "../../composables/useToast.js";
import Typeahead from "../../components/Typeahead.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const toast = useToast();

const rows = ref([]);
const loading = ref(false);
const search = ref("");
const statusFilter = ref("");

const STATUSES = [
	{ value: "", label: t("All statuses") },
	{ value: "DRAFT", label: "DRAFT" },
	{ value: "CONFIRMED", label: "CONFIRMED" },
	{ value: "SUPERSEDED_BY_CI", label: "SUPERSEDED_BY_CI" },
	{ value: "CANCELLED", label: "CANCELLED" },
];

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		rows.value = await call("stabler.api.imports.list_proformas", {
			company: activeCompany.value,
			status: statusFilter.value || undefined,
			search: search.value || undefined,
			limit: 200,
		});
	} catch (err) {
		toast.error(err?.message || t("Failed to load proformas."));
		rows.value = [];
	} finally {
		loading.value = false;
	}
}
onMounted(load);

const fm = (v, ccy) => formatMoney(v, ccy || "", user.value.language);

// ---- Create / edit modal ----
const modalOpen = ref(false);
const saving = ref(false);
const form = ref(null);

function blankForm() {
	return {
		name: "",
		supplier: "",
		supplier_name: "",
		pi_date: todayIso(),
		supplier_pi_ref: "",
		currency: "",
		agreed_total: 0,
		advance_pct: 70,
		bank_agreed: 0,
		cash_agreed: 0,
		status: "DRAFT",
		remarks: "",
	};
}

function openNew() {
	form.value = blankForm();
	modalOpen.value = true;
}
async function openEdit(row) {
	form.value = { ...blankForm(), ...row, supplier_name: row.supplier_name || row.supplier };
	modalOpen.value = true;
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

// Live earmark check mirrors the controller (bank + cash == agreed_total).
const earmarkOk = computed(() => {
	const f = form.value;
	if (!f) return true;
	const a = Number(f.agreed_total) || 0;
	const b = Number(f.bank_agreed) || 0;
	const c = Number(f.cash_agreed) || 0;
	if (a === 0 && b === 0 && c === 0) return true;
	return Math.abs(b + c - a) <= 0.5;
});

async function saveProforma() {
	if (!form.value.supplier) {
		toast.error(t("Supplier is required."));
		return;
	}
	if (!earmarkOk.value) {
		toast.error(t("Bank Agreed + Cash Agreed must equal Agreed Total."));
		return;
	}
	saving.value = true;
	try {
		await call("stabler.api.imports.save_proforma", {
			payload: { ...form.value, company: activeCompany.value },
		});
		toast.success(t("Proforma saved"));
		modalOpen.value = false;
		load();
	} catch (err) {
		toast.error(err?.message || t("Could not save the proforma."));
	} finally {
		saving.value = false;
	}
}

// ---- Supersede with a Commercial Invoice ----
const supersedeFor = ref(null); // row being superseded
const supersedeCi = ref("");
const superseding = ref(false);

function openSupersede(row) {
	supersedeFor.value = row;
	supersedeCi.value = "";
}
function searchCIs(q) {
	return call("stabler.api.imports.list_commercial_invoices", {
		company: activeCompany.value,
		search: q,
		limit: 20,
	});
}
async function doSupersede() {
	if (!supersedeCi.value) return;
	superseding.value = true;
	try {
		await call("stabler.api.imports.link_proforma_to_ci", {
			proforma: supersedeFor.value.name,
			commercial_invoice: supersedeCi.value,
			company: activeCompany.value,
		});
		toast.success(t("Proforma linked to Commercial Invoice"));
		supersedeFor.value = null;
		load();
	} catch (err) {
		toast.error(err?.message || t("Could not link the proforma."));
	} finally {
		superseding.value = false;
	}
}

const canSupersede = (row) => ["DRAFT", "CONFIRMED"].includes(row.status);
</script>

<template>
	<div class="card">
		<div class="card-header d-flex align-items-center gap-2">
			<div class="card-title m-0">{{ t("Proforma Invoices") }}</div>
			<button type="button" class="btn btn-primary btn-sm ms-auto" @click="openNew">
				<i class="ti ti-plus me-1"></i>{{ t("New Proforma") }}
			</button>
		</div>

		<ListToolbar v-model="search" :placeholder="t('PI no or supplier') + '  ⌘K'" :count="rows.length" @search="load">
			<template #filters>
				<Select v-model="statusFilter" size="sm" style="width: 180px" :options="STATUSES" value-key="value" label-key="label" @change="load" />
			</template>
		</ListToolbar>

		<div class="table-responsive">
			<table class="table table-vcenter">
				<thead>
					<tr>
						<th>{{ t("PI") }}</th>
						<th>{{ t("Supplier") }}</th>
						<th class="text-nowrap">{{ t("PI Date") }}</th>
						<th class="text-end">{{ t("Agreed total") }}</th>
						<th class="text-end">{{ t("Bank Agreed") }}</th>
						<th class="text-end">{{ t("Cash Agreed") }}</th>
						<th>{{ t("Status") }}</th>
						<th>{{ t("Commercial Invoice") }}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					<SkeletonRows v-if="loading" :cols="9" :rows="6" />
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openEdit(r)">
						<td class="font-monospace text-primary">{{ r.name }}</td>
						<td>{{ r.supplier_name || r.supplier }}</td>
						<td class="text-nowrap">{{ r.pi_date ? formatDate(r.pi_date) : "—" }}</td>
						<td class="text-end font-monospace">{{ fm(r.agreed_total, r.currency) }}</td>
						<td class="text-end font-monospace">{{ fm(r.bank_agreed, r.currency) }}</td>
						<td class="text-end font-monospace">{{ fm(r.cash_agreed, r.currency) }}</td>
						<td><span class="badge" :class="getStatusBadgeClass('Proforma Invoice', r.status)">{{ r.status }}</span></td>
						<td class="font-monospace text-secondary small">{{ r.commercial_invoice || "—" }}</td>
						<td class="text-end" @click.stop>
							<button v-if="canSupersede(r)" type="button" class="btn btn-outline-secondary btn-sm" @click="openSupersede(r)">
								<i class="ti ti-link me-1"></i>{{ t("Link CI") }}
							</button>
						</td>
					</tr>
				</tbody>
			</table>
			<EmptyState v-if="!loading && !rows.length" :title="t('No proformas yet')" :subtitle="t('Create your first proforma invoice.')" />
		</div>
	</div>

	<!-- Create / edit modal -->
	<div v-if="modalOpen" class="modal d-block" tabindex="-1" style="background: rgba(0,0,0,0.4)">
		<div class="modal-dialog modal-lg modal-dialog-centered">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ form.name ? t("Edit Proforma") : t("New Proforma") }}</h5>
					<button type="button" class="btn-close" @click="closeModal"></button>
				</div>
				<div class="modal-body">
					<div class="row g-3">
						<div class="col-md-6">
							<label class="form-label small mb-1">{{ t("Supplier") }} *</label>
							<Typeahead
								v-model="form.supplier"
								:display="form.supplier ? `${form.supplier_name || form.supplier}` : ''"
								:search="searchSuppliers"
								:placeholder="t('Search supplier…')"
								@pick="(s) => { form.supplier = s.name; form.supplier_name = s.supplier_name || s.name; }"
								@clear="() => { form.supplier = ''; form.supplier_name = ''; }"
							/>
						</div>
						<div class="col-md-3"><label class="form-label small mb-1">{{ t("PI Date") }}</label><DateInput v-model="form.pi_date" size="sm" /></div>
						<div class="col-md-3"><label class="form-label small mb-1">{{ t("Supplier PI No.") }}</label><input v-model="form.supplier_pi_ref" type="text" class="form-control form-control-sm"></div>

						<div class="col-md-4"><label class="form-label small mb-1">{{ t("Agreed total") }}</label><MoneyInput v-model="form.agreed_total" :currency="form.currency" :language="user.language" size="sm" /></div>
						<div class="col-md-4"><label class="form-label small mb-1">{{ t("Bank Agreed") }}</label><MoneyInput v-model="form.bank_agreed" :currency="form.currency" :language="user.language" size="sm" /></div>
						<div class="col-md-4"><label class="form-label small mb-1">{{ t("Cash Agreed") }}</label><MoneyInput v-model="form.cash_agreed" :currency="form.currency" :language="user.language" size="sm" /></div>
						<div class="col-12">
							<div v-if="!earmarkOk" class="alert alert-warning py-1 px-2 mb-0 small">
								{{ t("Bank Agreed + Cash Agreed must equal Agreed Total.") }}
							</div>
						</div>

						<div class="col-md-4"><label class="form-label small mb-1">{{ t("Advance %") }}</label><input v-model.number="form.advance_pct" type="number" step="1" class="form-control form-control-sm"></div>
						<div class="col-md-4"><label class="form-label small mb-1">{{ t("Status") }}</label>
							<select v-model="form.status" class="form-select form-select-sm">
								<option value="DRAFT">DRAFT</option>
								<option value="CONFIRMED">CONFIRMED</option>
								<option value="CANCELLED">CANCELLED</option>
							</select>
						</div>
						<div class="col-12"><label class="form-label small mb-1">{{ t("Remarks") }}</label><textarea v-model="form.remarks" rows="2" class="form-control form-control-sm"></textarea></div>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-outline-secondary" @click="closeModal">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary" :disabled="saving || !earmarkOk" @click="saveProforma">
						<span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>{{ t("Save") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<!-- Supersede modal -->
	<div v-if="supersedeFor" class="modal d-block" tabindex="-1" style="background: rgba(0,0,0,0.4)">
		<div class="modal-dialog modal-dialog-centered">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("Link to Commercial Invoice") }}</h5>
					<button type="button" class="btn-close" @click="supersedeFor = null"></button>
				</div>
				<div class="modal-body">
					<p class="text-secondary small">{{ t("Superseding proforma") }} <strong>{{ supersedeFor.name }}</strong>.</p>
					<label class="form-label small mb-1">{{ t("Commercial Invoice") }}</label>
					<Typeahead
						v-model="supersedeCi"
						:search="searchCIs"
						:placeholder="t('Search commercial invoice…')"
						@pick="(ci) => { supersedeCi = ci.name; }"
						@clear="() => { supersedeCi = ''; }"
					>
						<template #option="{ item }">
							<div class="fw-semibold small">{{ item.ci_number || item.name }}</div>
							<div class="text-secondary" style="font-size:0.75rem">{{ item.supplier_name }}</div>
						</template>
					</Typeahead>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-outline-secondary" @click="supersedeFor = null">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary" :disabled="superseding || !supersedeCi" @click="doSupersede">
						<span v-if="superseding" class="spinner-border spinner-border-sm me-1"></span>{{ t("Link") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
