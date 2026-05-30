<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDateTime } from "../../composables/date.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);

const today = () => new Date().toISOString().slice(0, 10);
const firstOfMonth = () => {
	const d = new Date();
	return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10);
};

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const fromDate = ref(firstOfMonth());
const toDate = ref(today());
const statusFilter = ref("");
const employeeFilter = ref("");

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.hr.list_attendance", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			employee: employeeFilter.value,
			status: statusFilter.value,
			limit: 500,
		});
	} catch (err) {
		error.value = err?.message || "Failed to load attendance.";
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch([activeCompany, fromDate, toDate, statusFilter, employeeFilter], load);

// ----- Mark attendance modal -----
const markOpen = ref(false);
const submitting = ref(false);
const markError = ref("");
const employeeOptions = ref([]);
const empsLoaded = ref(false);

function blankMark() {
	return {
		employee: "",
		attendance_date: today(),
		status: "Present",
		in_time: "",
		out_time: "",
	};
}
const form = ref(blankMark());

async function loadEmployees() {
	if (empsLoaded.value) return;
	try {
		employeeOptions.value = await call("stabler.api.hr.list_employees", {
			company: activeCompany.value,
			status: "Active",
			limit: 500,
		});
		empsLoaded.value = true;
	} catch (err) {
		markError.value = err?.message || "Failed to load employees.";
	}
}

function openMark() {
	form.value = blankMark();
	markError.value = "";
	markOpen.value = true;
	loadEmployees();
}
function closeMark() {
	markOpen.value = false;
}

async function save() {
	markError.value = "";
	if (!form.value.employee) {
		markError.value = t("Pick an employee.");
		return;
	}
	submitting.value = true;
	try {
		const payload = {
			company: activeCompany.value,
			employee: form.value.employee,
			attendance_date: form.value.attendance_date,
			status: form.value.status,
			submit: 1,
		};
		if (form.value.in_time) payload.in_time = `${form.value.attendance_date} ${form.value.in_time}:00`;
		if (form.value.out_time) payload.out_time = `${form.value.attendance_date} ${form.value.out_time}:00`;
		await call("stabler.api.hr.mark_attendance", payload);
		closeMark();
		await load();
	} catch (err) {
		markError.value = err?.message || "Failed to mark attendance.";
	} finally {
		submitting.value = false;
	}
}

function statusBadge(s) {
	if (s === "Present") return "bg-success-lt";
	if (s === "Absent") return "bg-red-lt";
	if (s === "On Leave") return "bg-azure-lt";
	if (s === "Half Day") return "bg-yellow-lt";
	if (s === "Work From Home") return "bg-purple-lt";
	return "bg-secondary-lt";
}

function fmtTime(t) {
	if (!t) return "—";
	const s = String(t);
	const m = s.match(/(\d{2}):(\d{2})/);
	return m ? `${m[1]}:${m[2]}` : s;
}
</script>

<template>
	<div class="card mb-3">
		<div class="card-body">
			<div class="row g-2 align-items-end">
				<div class="col-md-2">
					<label class="form-label small">{{ t("From") }}</label>
					<DateInput v-model="fromDate" />
				</div>
				<div class="col-md-2">
					<label class="form-label small">{{ t("To") }}</label>
					<DateInput v-model="toDate" />
				</div>
				<div class="col-md-3">
					<label class="form-label small">{{ t("Status") }}</label>
					<select v-model="statusFilter" class="form-select">
						<option value="">{{ t("All statuses") }}</option>
						<option value="Present">{{ t("Present") }}</option>
						<option value="Absent">{{ t("Absent") }}</option>
						<option value="On Leave">{{ t("On Leave") }}</option>
						<option value="Half Day">{{ t("Half Day") }}</option>
						<option value="Work From Home">{{ t("Work From Home") }}</option>
					</select>
				</div>
				<div class="col-md-5 d-flex justify-content-md-end gap-2">
					<button type="button" class="btn btn-ghost-secondary" @click="load">
						<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
					</button>
					<button type="button" class="btn btn-primary" @click="openMark">
						<i class="ti ti-checkbox me-1"></i>{{ t("Mark attendance") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<div v-if="error" class="alert alert-danger">{{ error }}</div>

	<EmptyState
		v-if="!loading && !error && !rows.length"
		icon="ti-calendar-event"
		accentIcon="ti-checkbox"
		tone="primary"
		:title="t('No attendance records')"
		:subtitle="t('Mark daily attendance to start building reports.')"
	/>

	<div v-else-if="loading" class="card-body text-center py-5">
		<div class="spinner-border text-primary"></div>
	</div>

	<div v-else class="card">
		<div class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th>{{ t("Date") }}</th>
						<th>{{ t("Employee") }}</th>
						<th>{{ t("Status") }}</th>
						<th>{{ t("In") }}</th>
						<th>{{ t("Out") }}</th>
						<th class="text-end">{{ t("Hours") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name">
						<td class="font-monospace">{{ formatDateTime(r.attendance_date) }}</td>
						<td>
							<div class="fw-semibold">{{ r.employee_name }}</div>
							<div class="small text-secondary font-monospace">{{ r.employee }}</div>
						</td>
						<td><span class="badge" :class="statusBadge(r.status)">{{ r.status }}</span></td>
						<td class="font-monospace">{{ fmtTime(r.in_time) }}</td>
						<td class="font-monospace">{{ fmtTime(r.out_time) }}</td>
						<td class="text-end font-monospace">{{ r.working_hours ? Number(r.working_hours).toFixed(2) : "—" }}</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<!-- Mark modal -->
	<div v-if="markOpen" class="modal-backdrop fade show"></div>
	<div v-if="markOpen" class="modal modal-blur fade show d-block" tabindex="-1">
		<div class="modal-dialog">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("Mark attendance") }}</h5>
					<button type="button" class="btn-close" @click="closeMark"></button>
				</div>
				<div class="modal-body">
					<div v-if="markError" class="alert alert-danger">{{ markError }}</div>
					<div class="mb-3">
						<label class="form-label">{{ t("Employee") }} *</label>
						<select v-model="form.employee" class="form-select">
							<option value="">—</option>
							<option v-for="e in employeeOptions" :key="e.name" :value="e.name">
								{{ e.employee_name }} ({{ e.name }})
							</option>
						</select>
					</div>
					<div class="row g-2">
						<div class="col-md-6">
							<label class="form-label">{{ t("Date") }}</label>
							<DateInput v-model="form.attendance_date" />
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Status") }}</label>
							<select v-model="form.status" class="form-select">
								<option value="Present">{{ t("Present") }}</option>
								<option value="Absent">{{ t("Absent") }}</option>
								<option value="On Leave">{{ t("On Leave") }}</option>
								<option value="Half Day">{{ t("Half Day") }}</option>
								<option value="Work From Home">{{ t("Work From Home") }}</option>
							</select>
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("In time") }}</label>
							<input v-model="form.in_time" type="time" class="form-control" />
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Out time") }}</label>
							<input v-model="form.out_time" type="time" class="form-control" />
						</div>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" @click="closeMark">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary" :disabled="submitting" @click="save">
						<i class="ti ti-checkbox me-1"></i>{{ t("Mark and submit") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
