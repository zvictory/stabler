<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useToast } from "../../composables/useToast.js";
import { formatDateTime } from "../../composables/date.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);

const { confirm } = useConfirm();
const toast = useToast();

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const statusFilter = ref("");

const statusFilterOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	{ value: "Open", label: t("Open") },
	{ value: "Approved", label: t("Approved") },
	{ value: "Rejected", label: t("Rejected") },
	{ value: "Cancelled", label: t("Cancelled") },
]);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.hr.list_leave_applications", {
			company: activeCompany.value,
			status: statusFilter.value,
			limit: 200,
		});
	} catch (err) {
		error.value = err?.message || "Failed to load leave applications.";
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch([activeCompany, statusFilter], load);

async function approve(name, status) {
	const verb = status === "Approved" ? t("Approve this leave request?") : t("Reject this leave request?");
	const ok = await confirm({
		title: status === "Approved" ? t("Approve Leave?") : t("Reject Leave?"),
		body: verb,
		danger: status === "Rejected",
	});
	if (!ok) return;
	try {
		await call("stabler.api.hr.approve_leave", { name, status });
		toast.success(status === "Approved" ? t("Leave request approved.") : t("Leave request rejected."));
		await load();
	} catch (err) {
		toast.error(err?.message || t("Action failed."));
	}
}

// ----- Create modal -----
const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");
const employeeOptions = ref([]);
const leaveTypeOptions = ref([]);
const optionsLoaded = ref(false);

function blankReq() {
	return {
		employee: "",
		leave_type: "",
		from_date: new Date().toISOString().slice(0, 10),
		to_date: new Date().toISOString().slice(0, 10),
		description: "",
	};
}
const form = ref(blankReq());

async function loadOptions() {
	if (optionsLoaded.value) return;
	try {
		const [emp, lt] = await Promise.all([
			call("stabler.api.hr.list_employees", {
				company: activeCompany.value,
				status: "Active",
				limit: 500,
			}),
			call("stabler.api.hr.list_leave_types", { limit: 100 }),
		]);
		employeeOptions.value = emp;
		leaveTypeOptions.value = lt;
		optionsLoaded.value = true;
	} catch (err) {
		submitError.value = err?.message || "Failed to load options.";
	}
}

function openCreate() {
	form.value = blankReq();
	submitError.value = "";
	createOpen.value = true;
	loadOptions();
}
function closeCreate() {
	createOpen.value = false;
}

async function saveReq(approveAfter) {
	submitError.value = "";
	if (!form.value.employee) {
		submitError.value = t("Pick an employee.");
		return;
	}
	if (!form.value.leave_type) {
		submitError.value = t("Pick a leave type.");
		return;
	}
	submitting.value = true;
	try {
		await call("stabler.api.hr.create_leave_application", {
			company: activeCompany.value,
			...form.value,
			submit: approveAfter ? 1 : 0,
		});
		closeCreate();
		await load();
	} catch (err) {
		submitError.value = err?.message || "Save failed.";
	} finally {
		submitting.value = false;
	}
}

function statusBadge(s) {
	if (s === "Approved") return "bg-success-lt";
	if (s === "Rejected") return "bg-red-lt";
	if (s === "Cancelled") return "bg-secondary-lt";
	return "bg-yellow-lt";
}
</script>

<template>
	<div class="card mb-3">
		<div class="card-body">
			<div class="row g-2 align-items-end">
				<div class="col-md-4">
					<label class="form-label small">{{ t("Status") }}</label>
					<Select v-model="statusFilter" :options="statusFilterOptions" />
				</div>
				<div class="col-md-8 d-flex justify-content-md-end gap-2">
					<button type="button" class="btn btn-ghost-secondary" @click="load">
						<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
					</button>
					<button type="button" class="btn btn-primary" @click="openCreate">
						<i class="ti ti-plus me-1"></i>{{ t("New leave request") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<div v-if="error" class="alert alert-danger">{{ error }}</div>

	<EmptyState
		v-if="!loading && !error && !rows.length"
		icon="ti-beach"
		accentIcon="ti-plus"
		tone="primary"
		:title="t('No leave requests')"
		:subtitle="t('Submit a leave request on behalf of an employee.')"
	/>

	<div v-else-if="loading" class="card-body text-center py-5">
		<div class="spinner-border text-primary"></div>
	</div>

	<div v-else class="card">
		<div class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th>{{ t("Request") }}</th>
						<th>{{ t("Employee") }}</th>
						<th>{{ t("Leave type") }}</th>
						<th>{{ t("Dates") }}</th>
						<th class="text-end">{{ t("Days") }}</th>
						<th>{{ t("Status") }}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name">
						<td class="font-monospace small">{{ r.name }}</td>
						<td>
							<div class="fw-semibold">{{ r.employee_name }}</div>
							<div class="small text-secondary font-monospace">{{ r.employee }}</div>
						</td>
						<td>{{ r.leave_type }}</td>
						<td class="font-monospace small">{{ formatDateTime(r.from_date) }} → {{ formatDateTime(r.to_date) }}</td>
						<td class="text-end font-monospace">{{ Number(r.total_leave_days || 0).toFixed(1) }}</td>
						<td><span class="badge" :class="statusBadge(r.status)">{{ r.status }}</span></td>
						<td class="text-end">
							<div v-if="r.status === 'Open' && r.docstatus === 0" class="btn-group btn-group-sm">
								<button class="btn btn-success" @click="approve(r.name, 'Approved')">
									<i class="ti ti-check"></i>
								</button>
								<button class="btn btn-outline-danger" @click="approve(r.name, 'Rejected')">
									<i class="ti ti-x"></i>
								</button>
							</div>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<!-- Create modal -->
	<div v-if="createOpen" class="modal-backdrop fade show"></div>
	<div v-if="createOpen" class="modal modal-blur fade show d-block" tabindex="-1">
		<div class="modal-dialog modal-lg">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("New leave request") }}</h5>
					<button type="button" class="btn-close" @click="closeCreate"></button>
				</div>
				<div class="modal-body">
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>
					<div class="row g-3">
						<div class="col-md-6">
							<label class="form-label">{{ t("Employee") }} *</label>
							<Select
								v-model="form.employee"
								:options="employeeOptions"
								value-key="name"
								label-key="employee_name"
								:placeholder="t('Pick an employee')"
							/>
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Leave type") }} *</label>
							<Select
								v-model="form.leave_type"
								:options="leaveTypeOptions"
								value-key="name"
								label-key="name"
								:placeholder="t('Pick a leave type')"
							/>
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("From") }}</label>
							<DateInput v-model="form.from_date" />
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("To") }}</label>
							<DateInput v-model="form.to_date" />
						</div>
						<div class="col-12">
							<label class="form-label">{{ t("Reason") }}</label>
							<textarea v-model="form.description" rows="3" class="form-control"></textarea>
						</div>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" @click="closeCreate">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-outline-primary" :disabled="submitting" @click="saveReq(false)">
						{{ t("Save as draft") }}
					</button>
					<button type="button" class="btn btn-primary" :disabled="submitting" @click="saveReq(true)">
						<i class="ti ti-check me-1"></i>{{ t("Approve and submit") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
