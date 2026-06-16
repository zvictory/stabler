<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDateTime, todayIso} from "../../composables/date.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";

const router = useRouter();
const session = useSession();
const { activeCompany } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const search = ref("");
const statusFilter = ref("");

const statusFilterOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	{ value: "Active", label: t("Active") },
	{ value: "Inactive", label: t("Inactive") },
	{ value: "Suspended", label: t("Suspended") },
	{ value: "Left", label: t("Left") },
]);

const genderOptions = computed(() => [
	{ value: "Male", label: t("Male") },
	{ value: "Female", label: t("Female") },
	{ value: "Other", label: t("Other") },
]);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.hr.list_employees", {
			company: activeCompany.value,
			search: search.value,
			status: statusFilter.value,
			limit: 200,
		});
	} catch (err) {
		error.value = err?.message || "Failed to load employees.";
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

// ----- Profile navigation -----
function openProfile(name) {
	router.push(`/hr/employees/${name}`);
}

// ----- Detail drawer (kept for compatibility but now superseded by profile page) -----
const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);

async function openDetail(name) {
	openProfile(name);
}
function closeDetail() {
	detailOpen.value = false;
	detail.value = null;
}

// ----- Create modal -----
const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");
const designationOptions = ref([]);
const departmentOptions = ref([]);
const optionsLoaded = ref(false);

function blankEmp() {
	return {
		first_name: "",
		last_name: "",
		gender: "",
		date_of_birth: "",
		date_of_joining: todayIso(),
		designation: "",
		department: "",
		cell_number: "",
		user_id: "",
	};
}
const form = ref(blankEmp());

async function loadOptions() {
	if (optionsLoaded.value) return;
	try {
		const [d, dep] = await Promise.all([
			call("stabler.api.hr.list_designations", { limit: 200 }),
			call("stabler.api.hr.list_departments", { company: activeCompany.value, limit: 200 }),
		]);
		designationOptions.value = d;
		departmentOptions.value = dep;
		optionsLoaded.value = true;
	} catch (err) {
		submitError.value = err?.message || "Failed to load options.";
	}
}

function openCreate() {
	form.value = blankEmp();
	submitError.value = "";
	createOpen.value = true;
	loadOptions();
}
function closeCreate() {
	createOpen.value = false;
}

async function saveEmp() {
	submitError.value = "";
	if (!form.value.first_name) {
		submitError.value = t("First name is required.");
		return;
	}
	if (!form.value.gender) {
		submitError.value = t("Gender is required.");
		return;
	}
	if (!form.value.date_of_birth) {
		submitError.value = t("Date of birth is required.");
		return;
	}
	submitting.value = true;
	try {
		const res = await call("stabler.api.hr.create_employee", {
			company: activeCompany.value,
			...form.value,
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

function statusBadge(s) {
	if (s === "Active") return "bg-success-lt";
	if (s === "Inactive") return "bg-secondary-lt";
	if (s === "Suspended") return "bg-yellow-lt";
	if (s === "Left") return "bg-red-lt";
	return "bg-secondary-lt";
}

function initials(name) {
	return (name || "?").split(" ").map((p) => p[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
}
</script>

<template>
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
							:placeholder="t('Search employees…')"
						/>
					</div>
				</div>
				<div class="col-md-3">
					<Select v-model="statusFilter" :options="statusFilterOptions" />
				</div>
				<div class="col-md-4 d-flex justify-content-md-end gap-2">
					<button type="button" class="btn btn-ghost-secondary" @click="load">
						<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
					</button>
					<button type="button" class="btn btn-primary" @click="openCreate">
						<i class="ti ti-user-plus me-1"></i>{{ t("New employee") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<div v-if="error" class="alert alert-danger">{{ error }}</div>

	<EmptyState
		v-if="!loading && !error && !rows.length"
		icon="ti-users"
		accentIcon="ti-user-plus"
		tone="primary"
		:title="t('No employees yet')"
		:subtitle="t('Add your first employee to start tracking attendance, leave and payroll.')"
	/>

	<div v-else-if="loading" class="card-body text-center py-5">
		<div class="spinner-border text-primary"></div>
	</div>

	<div v-else class="card">
		<div class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("Employee") }}</th>
						<th>{{ t("Designation") }}</th>
						<th>{{ t("Department") }}</th>
						<th>{{ t("Contact") }}</th>
						<th>{{ t("Status") }}</th>
						<th style="width: 4rem;"></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name" class="cursor-pointer" @click="openProfile(r.name)">
						<td>
							<div class="d-flex align-items-center gap-2">
								<span v-if="r.image" class="avatar avatar-sm" :style="{ backgroundImage: `url('${r.image}')` }"></span>
								<span v-else class="avatar avatar-sm bg-primary-lt">{{ initials(r.employee_name) }}</span>
								<div>
									<div class="fw-semibold">{{ r.employee_name }}</div>
									<div class="small text-secondary font-monospace">{{ r.name }}</div>
								</div>
							</div>
						</td>
						<td>{{ r.designation || "—" }}</td>
						<td>{{ r.department || "—" }}</td>
						<td>
							<div v-if="r.cell_number" class="small">{{ r.cell_number }}</div>
							<div v-if="r.user_id" class="small text-secondary">{{ r.user_id }}</div>
						</td>
						<td>
							<span class="badge" :class="statusBadge(r.status)">{{ r.status }}</span>
						</td>
						<td @click.stop>
							<button
								type="button"
								class="btn btn-ghost-secondary btn-sm"
								:title="t('Edit')"
								@click="openProfile(r.name)"
							>
								<i class="ti ti-edit"></i>
							</button>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<!-- Detail drawer -->
	<div v-if="detailOpen" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div v-if="detailOpen" class="offcanvas offcanvas-end show" tabindex="-1" style="visibility: visible; width: 520px">
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">
				<span v-if="detail?.name" class="font-monospace small">{{ detail.name }}</span>
				<span v-else>{{ t("Employee") }}</span>
			</h5>
			<button type="button" class="btn-close" @click="closeDetail"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="detail?.error" class="alert alert-danger">{{ detail.error }}</div>
			<div v-else-if="detail">
				<div class="d-flex align-items-center gap-3 mb-3">
					<span v-if="detail.image" class="avatar avatar-lg" :style="{ backgroundImage: `url('${detail.image}')` }"></span>
					<span v-else class="avatar avatar-lg bg-primary-lt">{{ initials(detail.employee_name) }}</span>
					<div>
						<div class="h3 m-0">{{ detail.employee_name }}</div>
						<div class="text-secondary">{{ detail.designation || "—" }}</div>
						<span class="badge mt-1" :class="statusBadge(detail.status)">{{ detail.status }}</span>
					</div>
				</div>
				<div class="datagrid">
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Department") }}</div>
						<div class="datagrid-content">{{ detail.department || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Date of joining") }}</div>
						<div class="datagrid-content">{{ formatDateTime(detail.date_of_joining) || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Date of birth") }}</div>
						<div class="datagrid-content">{{ formatDateTime(detail.date_of_birth) || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Gender") }}</div>
						<div class="datagrid-content">{{ detail.gender || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Phone") }}</div>
						<div class="datagrid-content">{{ detail.cell_number || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("User") }}</div>
						<div class="datagrid-content">{{ detail.user_id || "—" }}</div>
					</div>
					<div v-if="detail.personal_email" class="datagrid-item">
						<div class="datagrid-title">{{ t("Personal email") }}</div>
						<div class="datagrid-content">{{ detail.personal_email }}</div>
					</div>
					<div v-if="detail.company_email" class="datagrid-item">
						<div class="datagrid-title">{{ t("Company email") }}</div>
						<div class="datagrid-content">{{ detail.company_email }}</div>
					</div>
				</div>
			</div>
		</div>
	</div>

	<!-- Create modal -->
	<div v-if="createOpen" class="modal-backdrop fade show"></div>
	<div v-if="createOpen" class="modal modal-blur fade show d-block" tabindex="-1">
		<div class="modal-dialog modal-lg">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("New employee") }}</h5>
					<button type="button" class="btn-close" @click="closeCreate"></button>
				</div>
				<div class="modal-body">
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>
					<div class="row g-3">
						<div class="col-md-6">
							<label class="form-label">{{ t("First name") }} *</label>
							<input v-model="form.first_name" type="text" class="form-control" />
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Last name") }}</label>
							<input v-model="form.last_name" type="text" class="form-control" />
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Gender") }} *</label>
							<Select v-model="form.gender" :options="genderOptions" :placeholder="t('Select gender')" />
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Date of birth") }} *</label>
							<DateInput v-model="form.date_of_birth" />
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Date of joining") }}</label>
							<DateInput v-model="form.date_of_joining" />
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Designation") }}</label>
							<input v-model="form.designation" list="hr-designation-list" class="form-control" />
							<datalist id="hr-designation-list">
								<option v-for="d in designationOptions" :key="d.name" :value="d.name" />
							</datalist>
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Department") }}</label>
							<input v-model="form.department" list="hr-department-list" class="form-control" />
							<datalist id="hr-department-list">
								<option v-for="d in departmentOptions" :key="d.name" :value="d.name" />
							</datalist>
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Phone") }}</label>
							<input v-model="form.cell_number" type="tel" class="form-control" inputmode="tel" />
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("User account") }}</label>
							<input v-model="form.user_id" type="email" class="form-control" placeholder="user@example.com" />
						</div>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" @click="closeCreate">
						{{ t("Cancel") }}
					</button>
					<button type="button" class="btn btn-primary" :disabled="submitting" @click="saveEmp">
						<i class="ti ti-device-floppy me-1"></i>{{ t("Save") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
