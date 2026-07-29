<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatDate, formatDateTime, todayIso } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useConfirm } from "../../composables/useConfirm.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);

const { confirm } = useConfirm();

// ---------------------------------------------------------------------------
// Status color mapping: CRM color strings → Tabler badge classes
// ---------------------------------------------------------------------------
const COLOR_CLASS = {
	green: "bg-green-lt",
	blue: "bg-blue-lt",
	red: "bg-red-lt",
	orange: "bg-orange-lt",
	yellow: "bg-yellow-lt",
	purple: "bg-purple-lt",
	pink: "bg-pink-lt",
	gray: "bg-secondary-lt",
	teal: "bg-teal-lt",
	cyan: "bg-azure-lt",
};

function statusClass(color) {
	return COLOR_CLASS[(color || "").toLowerCase()] || "bg-secondary-lt";
}

// ---------------------------------------------------------------------------
// Metadata (statuses, sources, industries)
// ---------------------------------------------------------------------------
const meta = ref({ lead_statuses: [], sources: [], industries: [] });

async function loadMeta() {
	try {
		const res = await call("stabler.api.crm.crm_meta", { company: activeCompany.value });
		meta.value = res;
	} catch (_) {
		// Non-fatal: list still usable, just without filter options.
	}
}

const statusOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	...meta.value.lead_statuses.map((s) => ({ value: s.name, label: s.name })),
]);

const statusByName = computed(() => Object.fromEntries(meta.value.lead_statuses.map((s) => [s.name, s])));

// ---------------------------------------------------------------------------
// List state
// ---------------------------------------------------------------------------
const loading = ref(false);
const error = ref("");
const leads = ref([]);
const total = ref(0);

const search = ref("");
const filterStatus = ref("");
const PAGE_SIZE = 50;

async function fetchLeads() {
	loading.value = true;
	error.value = "";
	try {
		const res = await call("stabler.api.crm.list_leads", {
			company: activeCompany.value,
			search: search.value,
			status: filterStatus.value,
			page_length: PAGE_SIZE,
			start: 0,
		});
		leads.value = res.leads || [];
		total.value = res.total || 0;
	} catch (err) {
		error.value = err?.message || t("Failed to load leads.");
	} finally {
		loading.value = false;
	}
}

// ---------------------------------------------------------------------------
// Offcanvas form
// ---------------------------------------------------------------------------
const drawerOpen = ref(false);
const editingLead = ref(null); // null = new, object = edit
const form = ref({});
const submitting = ref(false);
const submitError = ref("");
const deleting = ref(false);

function blankForm() {
	return {
		first_name: "",
		last_name: "",
		email: "",
		mobile_no: "",
		organization: "",
		status: meta.value.lead_statuses[0]?.name || "",
		lead_owner: "",
		source: "",
		job_title: "",
		custom_manzil: "",
		custom_sana: todayIso(),
		custom_izoh: "",
	};
}

function openNew() {
	editingLead.value = null;
	form.value = blankForm();
	submitError.value = "";
	drawerOpen.value = true;
}

async function openEdit(lead) {
	editingLead.value = lead;
	submitError.value = "";
	drawerOpen.value = true;
	// Load full doc to get all fields.
	try {
		const doc = await call("stabler.api.crm.get_lead", { name: lead.name, company: activeCompany.value });
		form.value = {
			name: doc.name,
			first_name: doc.first_name || "",
			last_name: doc.last_name || "",
			email: doc.email || "",
			mobile_no: doc.mobile_no || "",
			organization: doc.organization || "",
			status: doc.status || "",
			lead_owner: doc.lead_owner || "",
			source: doc.source || "",
			job_title: doc.job_title || "",
			custom_manzil: doc.custom_manzil || "",
			custom_sana: doc.custom_sana || todayIso(),
			custom_izoh: doc.custom_izoh || "",
		};
	} catch (err) {
		submitError.value = err?.message || t("Failed to load lead.");
	}
}

function closeDrawer() {
	drawerOpen.value = false;
	editingLead.value = null;
}

async function submitForm() {
	submitting.value = true;
	submitError.value = "";
	try {
		await call("stabler.api.crm.save_lead", { data: JSON.stringify(form.value), company: activeCompany.value });
		closeDrawer();
		fetchLeads();
	} catch (err) {
		submitError.value = err?.message || t("Failed to save lead.");
	} finally {
		submitting.value = false;
	}
}

async function deleteLead() {
	if (!editingLead.value) return;
	const ok = await confirm({
		title: t("Delete lead?"),
		body: t("Delete this lead?"),
		danger: true,
	});
	if (!ok) return;
	deleting.value = true;
	try {
		await call("stabler.api.crm.delete_lead", { name: editingLead.value.name, company: activeCompany.value });
		closeDrawer();
		fetchLeads();
	} catch (err) {
		submitError.value = err?.message || t("Failed to delete lead.");
	} finally {
		deleting.value = false;
	}
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
onMounted(() => {
	loadMeta();
	fetchLeads();
});
watch(activeCompany, fetchLeads);
</script>

<template>
	<!-- Filter bar -->
	<div class="d-flex gap-2 align-items-center flex-wrap mb-3">
		<div class="input-group input-group-sm" style="max-width: 280px">
			<span class="input-group-text"><i class="ti ti-search"></i></span>
			<input
				v-model="search"
				type="text"
				class="form-control"
				:placeholder="t('Search leads…')"
				@keyup.enter="fetchLeads"
			/>
		</div>
		<select v-model="filterStatus" class="form-select form-select-sm" style="max-width: 180px" @change="fetchLeads">
			<option v-for="opt in statusOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
		</select>
		<button type="button" class="btn btn-sm btn-outline-secondary" :disabled="loading" @click="fetchLeads">
			<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
		</button>
		<button type="button" class="btn btn-sm btn-primary ms-auto" @click="openNew">
			<i class="ti ti-plus me-1"></i>{{ t("New Lead") }}
		</button>
	</div>

	<div v-if="loading" class="text-center py-5">
		<div class="spinner-border text-primary" role="status"></div>
	</div>
	<div v-else-if="error" class="alert alert-danger">{{ error }}</div>
	<template v-else>
		<EmptyState
			v-if="!leads.length"
			icon="ti-user-plus"
			:title="t('No leads')"
			:description="t('Create your first lead or adjust the search filters.')"
		/>
		<div v-else class="card">
			<div class="table-responsive">
				<table class="table table-sm table-vcenter card-table">
					<thead>
						<tr>
							<th>{{ t("Name") }}</th>
							<th>{{ t("Organization") }}</th>
							<th>{{ t("Email") }}</th>
							<th>{{ t("Phone") }}</th>
							<th>{{ t("Status") }}</th>
							<th>{{ t("Owner") }}</th>
							<th>{{ t("Modified") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="lead in leads"
							:key="lead.name"
							style="cursor: pointer"
							@click="openEdit(lead)"
						>
							<td class="fw-semibold">{{ lead.lead_name || `${lead.first_name} ${lead.last_name}`.trim() || lead.name }}</td>
							<td>{{ lead.organization || "—" }}</td>
							<td class="small">{{ lead.email || "—" }}</td>
							<td class="small">{{ lead.mobile_no || "—" }}</td>
							<td>
								<span
									v-if="lead.status"
									class="badge"
									:class="statusClass(statusByName[lead.status]?.color)"
								>{{ lead.status }}</span>
								<span v-else class="text-secondary">—</span>
							</td>
							<td class="small text-secondary">{{ lead.lead_owner || "—" }}</td>
							<td class="small text-secondary text-nowrap">{{ formatDate(lead.modified) }}</td>
						</tr>
					</tbody>
				</table>
			</div>
			<div class="card-footer text-secondary small">
				{{ t("Showing") }} {{ leads.length }} / {{ total }}
			</div>
		</div>
	</template>

	<!-- Offcanvas create/edit -->
	<div v-if="drawerOpen" class="offcanvas-backdrop fade show" @click="closeDrawer"></div>
	<div
		class="offcanvas offcanvas-end"
		:class="{ show: drawerOpen }"
		tabindex="-1"
		style="visibility: visible; width: 480px"
		:style="{ transform: drawerOpen ? 'translateX(0)' : 'translateX(100%)' }"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">{{ editingLead ? t("Edit Lead") : t("New Lead") }}</h5>
			<button type="button" class="btn-close" :aria-label="t('Close')" @click="closeDrawer"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="submitError" class="alert alert-danger mb-3">{{ submitError }}</div>
			<form @submit.prevent="submitForm">
				<div class="row g-3">
					<div class="col-6">
						<label class="form-label">{{ t("First Name") }} <span class="text-danger">*</span></label>
						<input v-model="form.first_name" type="text" class="form-control" required />
					</div>
					<div class="col-6">
						<label class="form-label">{{ t("Last Name") }}</label>
						<input v-model="form.last_name" type="text" class="form-control" />
					</div>
					<div class="col-12">
						<label class="form-label">{{ t("Organization") }}</label>
						<input v-model="form.organization" type="text" class="form-control" />
					</div>
					<div class="col-12">
						<label class="form-label">{{ t("Job Title") }}</label>
						<input v-model="form.job_title" type="text" class="form-control" />
					</div>
					<div class="col-12">
						<label class="form-label">{{ t("Email") }}</label>
						<input v-model="form.email" type="email" class="form-control" />
					</div>
					<div class="col-12">
						<label class="form-label">{{ t("Phone") }}</label>
						<input v-model="form.mobile_no" type="text" class="form-control" />
					</div>
					<div class="col-12">
						<label class="form-label">{{ t("Status") }}</label>
						<select v-model="form.status" class="form-select">
							<option value="">—</option>
							<option v-for="s in meta.lead_statuses" :key="s.name" :value="s.name">{{ s.name }}</option>
						</select>
					</div>
					<div class="col-12">
						<label class="form-label">{{ t("Source") }}</label>
						<select v-model="form.source" class="form-select">
							<option value="">—</option>
							<option v-for="src in meta.sources" :key="src" :value="src">{{ src }}</option>
						</select>
					</div>
					<div class="col-12">
						<label class="form-label">{{ t("Lead Owner") }}</label>
						<input v-model="form.lead_owner" type="text" class="form-control" :placeholder="t('Email or user ID')" />
					</div>
					<div class="col-12">
						<label class="form-label">{{ t("Manzil") }}</label>
						<input v-model="form.custom_manzil" type="text" class="form-control" />
					</div>
					<div class="col-12">
						<label class="form-label">{{ t("Sana") }}</label>
						<DateInput v-model="form.custom_sana" />
					</div>
					<div class="col-12">
						<label class="form-label">{{ t("Izoh") }}</label>
						<textarea v-model="form.custom_izoh" class="form-control" rows="3"></textarea>
					</div>
				</div>

				<div class="mt-4 d-flex gap-2">
					<button type="submit" class="btn btn-primary" :disabled="submitting">
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Save") }}
					</button>
					<button type="button" class="btn btn-outline-secondary" @click="closeDrawer">{{ t("Cancel") }}</button>
					<button
						v-if="editingLead"
						type="button"
						class="btn btn-outline-danger ms-auto"
						:disabled="deleting"
						@click="deleteLead"
					>
						<span v-if="deleting" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Delete") }}
					</button>
				</div>
			</form>
		</div>
	</div>
</template>
