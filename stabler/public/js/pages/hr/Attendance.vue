<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { todayIso } from "../../composables/date.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const router = useRouter();

const today = () => todayIso();

// ----- Period (YYYY-MM) — last 12 months -----
function ym(d) {
	return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
const periodOptions = computed(() => {
	const now = new Date();
	const out = [];
	for (let i = 0; i < 12; i++) {
		const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
		out.push({ value: ym(d), label: d.toLocaleDateString("en", { year: "numeric", month: "long" }) });
	}
	return out;
});
const period = ref(ym(new Date()));

// ----- Department filter -----
const departments = ref([]);
const departmentFilter = ref("");
const departmentOptions = computed(() => [
	{ name: "", department_name: t("All departments") },
	...departments.value.map((d) => ({ name: d.name, department_name: d.department_name || d.name })),
]);

const loading = ref(false);
const error = ref("");
const rows = ref([]);

const visibleRows = computed(() =>
	departmentFilter.value ? rows.value.filter((r) => r.department === departmentFilter.value) : rows.value,
);

function shortName(n) {
	// strip the trailing " - <company abbr>" ERPNext appends to dept/designation names
	return n ? String(n).replace(/\s+-\s+\S+$/, "") : "—";
}

function disciplinePct(r) {
	return r.discipline == null ? null : Number(r.discipline) * 100;
}
function disciplineBadge(r) {
	if (r.discipline == null) return "bg-secondary-lt";
	if (r.discipline >= 0.95) return "bg-success-lt";
	if (r.discipline >= 0.85) return "bg-warning-lt";
	return "bg-danger-lt";
}

function openEmployee(r) {
	if (r.employee) router.push(`/hr/employees/${encodeURIComponent(r.employee)}`);
}

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const res = await call("stabler.api.hr_payroll.list_payroll_summaries", {
			company: activeCompany.value,
			payroll_period: period.value,
			limit: 500,
		});
		rows.value = res?.summaries || [];
	} catch (err) {
		error.value = err?.message || t("Failed to load attendance.");
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

async function loadDepartments() {
	if (!activeCompany.value) return;
	try {
		departments.value = await call("stabler.api.hr.list_departments", { company: activeCompany.value, limit: 200 });
	} catch {
		departments.value = [];
	}
}

onMounted(() => {
	loadDepartments();
	load();
});
watch([activeCompany, period], () => {
	loadDepartments();
	load();
});

// ----- Mark attendance modal (preserved) -----
const markOpen = ref(false);
const submitting = ref(false);
const markError = ref("");
const employeeOptions = ref([]);
const empsLoaded = ref(false);

const markStatusOptions = computed(() => [
	{ value: "Present", label: t("Present") },
	{ value: "Absent", label: t("Absent") },
	{ value: "On Leave", label: t("On Leave") },
	{ value: "Half Day", label: t("Half Day") },
	{ value: "Work From Home", label: t("Work From Home") },
]);

function blankMark() {
	return { employee: "", attendance_date: today(), status: "Present", in_time: "", out_time: "" };
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
</script>

<template>
	<div class="card mb-3">
		<div class="card-body">
			<div class="row g-2 align-items-end">
				<div class="col-12 col-md-3">
					<label class="form-label small">{{ t("Period") }}</label>
					<Select v-model="period" :options="periodOptions" value-key="value" label-key="label" />
				</div>
				<div class="col-12 col-md-4">
					<label class="form-label small">{{ t("Department") }}</label>
					<Select v-model="departmentFilter" :options="departmentOptions" value-key="name" label-key="department_name" />
				</div>
				<div class="col-12 col-md-5 d-flex justify-content-md-end gap-2">
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
		v-else-if="!loading && !visibleRows.length"
		icon="ti-calendar-event"
		accentIcon="ti-checkbox"
		tone="primary"
		:title="t('No attendance records')"
		:subtitle="t('Sync TimePay attendance and generate the period summary to populate this table.')"
	/>

	<div v-else class="card">
		<div class="card-header">
			<h3 class="card-title m-0">{{ t("Attendance summary") }}</h3>
		</div>
		<div class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("Employee") }}</th>
						<th>{{ t("Department") }}</th>
						<th>{{ t("Position") }}</th>
						<th class="text-end">{{ t("Present") }}</th>
						<th class="text-end">{{ t("Late") }}</th>
						<th class="text-end">{{ t("Absent") }}</th>
						<th class="text-end">{{ t("Overtime") }}</th>
						<th class="text-end">{{ t("Discipline") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="8" :cols="8" />
				<tbody v-else>
					<tr
						v-for="r in visibleRows"
						:key="r.name"
						style="cursor: pointer"
						@click="openEmployee(r)"
					>
						<td>
							<div class="fw-semibold">{{ r.employee_name }}</div>
							<div class="small text-secondary font-monospace">{{ r.employee }}</div>
						</td>
						<td class="small text-secondary">{{ shortName(r.department) }}</td>
						<td class="small text-secondary">{{ shortName(r.designation) }}</td>
						<td class="text-end font-monospace">{{ r.present_days ?? "—" }}</td>
						<td class="text-end font-monospace text-warning">{{ r.late_count ?? "—" }}</td>
						<td class="text-end font-monospace text-danger">{{ r.absent_days ?? "—" }}</td>
						<td class="text-end font-monospace text-secondary">
							{{ r.overtime_minutes ? (Number(r.overtime_minutes) / 60).toFixed(1) + " h" : "—" }}
						</td>
						<td class="text-end">
							<span v-if="disciplinePct(r) != null" class="badge" :class="disciplineBadge(r)">
								{{ disciplinePct(r).toFixed(1) }}%
							</span>
							<span v-else class="text-secondary">—</span>
						</td>
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
						<Select
							v-model="form.employee"
							:options="employeeOptions"
							value-key="name"
							:placeholder="t('Pick an employee')"
						>
							<template #option="{ option }">{{ option.employee_name }} ({{ option.name }})</template>
							<template #selected="{ option }">{{ option.employee_name }} ({{ option.name }})</template>
						</Select>
					</div>
					<div class="row g-2">
						<div class="col-md-6">
							<label class="form-label">{{ t("Date") }}</label>
							<DateInput v-model="form.attendance_date" />
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Status") }}</label>
							<Select v-model="form.status" :options="markStatusOptions" />
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
