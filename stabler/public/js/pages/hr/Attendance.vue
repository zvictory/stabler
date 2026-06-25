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
import AttendanceMatrix from "../../components/AttendanceMatrix.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const router = useRouter();

const view = ref("grid"); // "grid" (month matrix) | "summary"
const gridSearch = ref("");

// ── Attendance edit-lock window (admin) + banner ─────────────────────────────
const matrixRef = ref(null);
const lockDate = ref(null);
const lockOpen = ref(false);
const lockDays = ref(0);
const lockSaving = ref(false);
const lockError = ref("");
const isAdmin = computed(() => session.isAdmin);

function onMatrixMeta(m) {
	lockDate.value = m?.edit_lock_date || null;
}
async function loadLockSetting() {
	if (!isAdmin.value) return;
	try {
		const r = await call("stabler.api.admin.get_attendance_lock_setting");
		lockDays.value = Number(r?.attendance_edit_lock_days || 0);
	} catch {
		/* non-fatal */
	}
}
async function saveLock() {
	lockSaving.value = true;
	lockError.value = "";
	try {
		await call("stabler.api.admin.set_attendance_lock_setting", { days: lockDays.value || 0 });
		lockOpen.value = false;
		matrixRef.value?.reload();
	} catch (err) {
		lockError.value = err?.message || t("Failed to save.");
	} finally {
		lockSaving.value = false;
	}
}
onMounted(loadLockSetting);

const today = () => todayIso();

// ----- Period (YYYY-MM) — last 12 months -----
function ym(d) {
	return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
const period = ref(ym(new Date()));
const periodLabel = computed(() => {
	const [y, m] = period.value.split("-").map(Number);
	return new Date(y, m - 1, 1).toLocaleDateString("en", { year: "numeric", month: "long" });
});
const isCurrentOrFuture = computed(() => period.value >= ym(new Date()));
function shiftPeriod(delta) {
	const [y, m] = period.value.split("-").map(Number);
	period.value = ym(new Date(y, m - 1 + delta, 1));
}

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
	<div class="d-flex flex-wrap align-items-center gap-2 mb-3">
		<div class="btn-group" role="group">
			<button type="button" class="btn btn-outline-secondary" @click="shiftPeriod(-1)"><i class="ti ti-chevron-left"></i></button>
			<span class="btn btn-outline-secondary disabled text-dark" style="min-width: 150px">{{ periodLabel }}</span>
			<button type="button" class="btn btn-outline-secondary" :disabled="isCurrentOrFuture" @click="shiftPeriod(1)"><i class="ti ti-chevron-right"></i></button>
		</div>
		<div style="min-width: 180px">
			<Select v-model="departmentFilter" :options="departmentOptions" value-key="name" label-key="department_name" size="sm" />
		</div>
		<div class="input-icon" style="max-width: 200px">
			<span class="input-icon-addon"><i class="ti ti-search"></i></span>
			<input v-model="gridSearch" class="form-control form-control-sm" :placeholder="t('Search name… ⌘K')" />
		</div>
		<div class="ms-auto d-flex align-items-center gap-2">
			<div class="btn-group" role="group">
				<input id="att-grid" v-model="view" type="radio" class="btn-check" value="grid" />
				<label class="btn btn-outline-primary btn-sm" for="att-grid" :title="t('Month grid')"><i class="ti ti-table"></i></label>
				<input id="att-sum" v-model="view" type="radio" class="btn-check" value="summary" />
				<label class="btn btn-outline-primary btn-sm" for="att-sum" :title="t('Summary')"><i class="ti ti-list"></i></label>
			</div>
			<button type="button" class="btn btn-primary btn-sm" @click="openMark">
				<i class="ti ti-checkbox me-1"></i>{{ t("Mark") }}
			</button>
		</div>
	</div>

	<template v-if="view === 'grid'">
		<div v-if="lockDate || isAdmin" class="alert alert-warning d-flex align-items-center gap-2 py-2 mb-2">
			<i class="ti ti-lock"></i>
			<div class="small">
				<template v-if="lockDate">
					{{ t("Attendance on/before") }} <b>{{ lockDate }}</b> {{ t("is locked from edits.") }}
				</template>
				<template v-else>{{ t("Attendance edits are open — no hard lock set.") }}</template>
			</div>
			<button v-if="isAdmin" type="button" class="btn btn-sm btn-ghost-secondary ms-auto" @click="lockOpen = !lockOpen">
				<i class="ti ti-settings me-1"></i>{{ t("Lock window") }}
			</button>
		</div>

		<div v-if="isAdmin && lockOpen" class="card mb-3">
			<div class="card-body d-flex align-items-end gap-2 flex-wrap py-2">
				<div>
					<label class="form-label small mb-1">{{ t("Lock attendance older than (days)") }}</label>
					<input v-model.number="lockDays" type="number" min="0" class="form-control" style="width: 150px" />
				</div>
				<button type="button" class="btn btn-primary" :disabled="lockSaving" @click="saveLock">
					<span v-if="lockSaving" class="spinner-border spinner-border-sm me-1"></span>{{ t("Save") }}
				</button>
				<span class="small text-secondary">{{ t("0 = no hard lock; past edits still ask for confirmation.") }}</span>
				<span v-if="lockError" class="small text-danger">{{ lockError }}</span>
			</div>
		</div>

		<AttendanceMatrix
			ref="matrixRef"
			:company="activeCompany"
			:period="period"
			:department="departmentFilter"
			:search="gridSearch"
			@meta="onMatrixMeta"
		/>
	</template>

	<div v-else-if="error" class="alert alert-danger">{{ error }}</div>

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
