<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { formatDate } from "../../composables/date.js";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";

const route = useRoute();
const router = useRouter();
const session = useSession();
const { activeCompany, language } = storeToRefs(session);
const toast = useToast();

const name = computed(() => route.params.name);
const lang = computed(() => language.value || "en");

const loading = ref(false);
const saving = ref(false);
const error = ref("");
const detail = ref(null);

// Track whether payroll fields are visible (not masked)
const payrollVisible = computed(() => {
	const d = detail.value;
	if (!d) return false;
	return d.custom_base_salary !== undefined && d.custom_base_salary !== "MASKED";
});

// Years of service from the joining date — shown as a headline stat (anjan-hr style).
const tenure = computed(() => {
	const d = detail.value?.date_of_joining;
	if (!d) return "—";
	const start = new Date(d);
	if (Number.isNaN(start.getTime())) return "—";
	const now = new Date();
	let years = now.getFullYear() - start.getFullYear();
	const md = now.getMonth() - start.getMonth();
	if (md < 0 || (md === 0 && now.getDate() < start.getDate())) years--;
	return years >= 1 ? String(years) : "<1";
});

// Active tab
const activeTab = ref("profile");

// Options for pickers
const designationOptions = ref([]);
const departmentOptions = ref([]);
const optionsLoaded = ref(false);

// Form state — mirrors all editable fields
const form = ref(blankForm());

function blankForm() {
	return {
		// Profile
		employee_name: "",
		image: "",
		status: "",
		cell_number: "",
		custom_timepay_id: "",
		custom_timepay_name: "",
		// Employment
		department: "",
		designation: "",
		date_of_joining: "",
		relieving_date: "",
		company: "",
		// Compensation
		custom_base_salary: null,
		custom_shift_class: "",
		custom_region: "",
		custom_work_mode: "",
		custom_stake_coefficient: 1.0,
		custom_heavy_conditions: 0,
		custom_additional_duties: 0,
		// Allowances (parsed from JSON)
		allowance_seniority: null,
		allowance_night_per_hour: null,
		allowance_custom: [],
	};
}

function hydrateForm(d) {
	form.value.employee_name = d.employee_name || "";
	form.value.image = d.image || "";
	form.value.status = d.status || "";
	form.value.cell_number = d.cell_number || "";
	form.value.custom_timepay_id = d.custom_timepay_id || "";
	form.value.custom_timepay_name = d.custom_timepay_name || "";
	form.value.department = d.department || "";
	form.value.designation = d.designation || "";
	form.value.date_of_joining = d.date_of_joining || "";
	form.value.relieving_date = d.relieving_date || "";
	form.value.company = d.company || "";
	// Compensation (only when payroll-visible)
	if (payrollVisible.value) {
		form.value.custom_base_salary = d.custom_base_salary ?? null;
		form.value.custom_shift_class = d.custom_shift_class || "";
		form.value.custom_region = d.custom_region || "";
		form.value.custom_work_mode = d.custom_work_mode || "";
		form.value.custom_stake_coefficient =
			d.custom_stake_coefficient !== undefined ? Number(d.custom_stake_coefficient) : 1.0;
		form.value.custom_heavy_conditions = d.custom_heavy_conditions ? 1 : 0;
		form.value.custom_additional_duties = d.custom_additional_duties ? 1 : 0;
		// Allowances
		parseAllowances(d.custom_allowance_config);
	}
}

function parseAllowances(raw) {
	form.value.allowance_seniority = null;
	form.value.allowance_night_per_hour = null;
	form.value.allowance_custom = [];
	if (!raw || raw === "MASKED") return;
	try {
		const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
		if (!parsed || typeof parsed !== "object") return;
		form.value.allowance_seniority = parsed.seniority !== undefined ? Number(parsed.seniority) : null;
		if (parsed.night && parsed.night.perHour !== undefined) {
			form.value.allowance_night_per_hour = Number(parsed.night.perHour);
		}
		if (Array.isArray(parsed.custom)) {
			form.value.allowance_custom = parsed.custom.map((c) => ({
				label: c.label || "",
				amount: c.amount !== undefined ? Number(c.amount) : null,
			}));
		}
	} catch {
		// malformed JSON — ignore silently
	}
}

function serializeAllowances() {
	const obj = {};
	if (form.value.allowance_seniority !== null && form.value.allowance_seniority !== undefined) {
		obj.seniority = form.value.allowance_seniority;
	}
	if (form.value.allowance_night_per_hour !== null && form.value.allowance_night_per_hour !== undefined) {
		obj.night = { perHour: form.value.allowance_night_per_hour };
	}
	if (form.value.allowance_custom.length) {
		obj.custom = form.value.allowance_custom.map((c) => ({
			label: c.label,
			amount: c.amount,
		}));
	}
	return JSON.stringify(obj);
}

async function load() {
	loading.value = true;
	error.value = "";
	detail.value = null;
	try {
		const d = await call("stabler.api.hr.employee_detail", { name: name.value });
		detail.value = d;
		hydrateForm(d);
		await loadOptions();
	} catch (err) {
		error.value = err?.message || t("Failed to load employee.");
	} finally {
		loading.value = false;
	}
}

async function loadOptions() {
	if (optionsLoaded.value) return;
	try {
		const [d, dep] = await Promise.all([
			call("stabler.api.hr.list_designations", { limit: 200 }),
			call("stabler.api.hr.list_departments", {
				company: activeCompany.value,
				limit: 200,
			}),
		]);
		designationOptions.value = (d || []).map((r) => ({ value: r.name, label: r.name }));
		departmentOptions.value = (dep || []).map((r) => ({ value: r.name, label: r.name }));
		optionsLoaded.value = true;
	} catch {
		// non-fatal — user can still type
	}
}

async function save() {
	saving.value = true;
	error.value = "";
	try {
		const payload = {
			employee_name: form.value.employee_name,
			status: form.value.status,
			cell_number: form.value.cell_number,
			custom_timepay_id: form.value.custom_timepay_id,
			department: form.value.department,
			designation: form.value.designation,
			date_of_joining: form.value.date_of_joining,
			relieving_date: form.value.relieving_date,
			company: form.value.company,
		};
		if (payrollVisible.value) {
			payload.custom_base_salary = form.value.custom_base_salary;
			payload.custom_shift_class = form.value.custom_shift_class;
			payload.custom_region = form.value.custom_region;
			payload.custom_work_mode = form.value.custom_work_mode;
			payload.custom_stake_coefficient = form.value.custom_stake_coefficient;
			payload.custom_heavy_conditions = form.value.custom_heavy_conditions;
			payload.custom_additional_duties = form.value.custom_additional_duties;
			payload.custom_allowance_config = serializeAllowances();
		}
		await call("stabler.api.hr.update_employee", {
			name: name.value,
			payload,
		});
		toast.success(t("Employee saved."));
		await load();
	} catch (err) {
		const msg = err?.message || t("Save failed.");
		error.value = msg;
		toast.error(msg);
	} finally {
		saving.value = false;
	}
}

function goBack() {
	router.push("/hr/employees");
}

function initials(n) {
	return (n || "?").split(" ").map((p) => p[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
}

// Employee status → badge class (mirrors Employees.vue; STATUS_MAP has no "Employee" key yet)
function statusBadge(s) {
	if (s === "Active") return "bg-success-lt";
	if (s === "Inactive") return "bg-secondary-lt";
	if (s === "Suspended") return "bg-yellow-lt";
	if (s === "Left") return "bg-red-lt";
	return "bg-secondary-lt";
}

// Stake coefficient is only editable when work_mode == HALF_RATE
const stakeEnabled = computed(() => form.value.custom_work_mode === "HALF_RATE");

// If mode changes away from HALF_RATE, reset coefficient to 1.0
watch(() => form.value.custom_work_mode, (val) => {
	if (val !== "HALF_RATE") {
		form.value.custom_stake_coefficient = 1.0;
	}
});

// --- Allowance custom list helpers ---
function addCustomAllowance() {
	form.value.allowance_custom.push({ label: "", amount: null });
}
function removeCustomAllowance(idx) {
	form.value.allowance_custom.splice(idx, 1);
}

// --- Select option lists ---
const statusOptions = computed(() => [
	{ value: "Active", label: t("Active") },
	{ value: "Inactive", label: t("Inactive") },
	{ value: "Suspended", label: t("Suspended") },
	{ value: "Left", label: t("Left") },
]);

const shiftClassOptions = computed(() => [
	{ value: "", label: t("— select —") },
	{ value: "DAY", label: t("Day") },
	{ value: "NIGHT", label: t("Night") },
	{ value: "OFFICE", label: t("Office") },
	{ value: "LIGHT", label: t("Light") },
]);

const regionOptions = computed(() => [
	{ value: "", label: t("— select —") },
	{ value: "CITY", label: t("City") },
	{ value: "DISTRICT", label: t("District") },
	{ value: "FAR_DISTRICT", label: t("Far district") },
	{ value: "NO_TRAVEL", label: t("No travel") },
]);

const workModeOptions = computed(() => [
	{ value: "", label: t("— select —") },
	{ value: "SHIFT_8H", label: t("Shift 8h") },
	{ value: "SHIFT_12H", label: t("Shift 12h") },
	{ value: "HALF_RATE", label: t("Half rate") },
	{ value: "FLEXIBLE", label: t("Flexible") },
	{ value: "REMOTE", label: t("Remote") },
]);

onMounted(load);
watch(name, load);
</script>

<template>
	<div>
		<!-- Back -->
		<div class="mb-2">
			<button type="button" class="btn btn-ghost-secondary btn-sm" @click="goBack">
				<i class="ti ti-arrow-left me-1"></i>{{ t("Employees") }}
			</button>
		</div>

		<!-- Identity summary card (anjan-hr style: avatar + headline stats incl. TimePay ID) -->
		<div class="card mb-3">
			<div class="card-body d-flex flex-wrap align-items-center gap-3">
				<span v-if="detail?.image" class="avatar avatar-xl rounded" :style="{ backgroundImage: `url('${detail.image}')` }"></span>
				<span v-else class="avatar avatar-xl bg-primary-lt">{{ initials(detail?.employee_name) }}</span>
				<div class="flex-fill" style="min-width: 200px">
					<div class="d-flex align-items-center gap-2 flex-wrap">
						<h3 class="mb-0">{{ detail?.employee_name || name }}</h3>
						<span v-if="detail?.status" class="badge" :class="statusBadge(detail.status)">{{ detail.status }}</span>
					</div>
					<div class="text-secondary small mt-1">
						<i class="ti ti-briefcase me-1"></i>{{ detail?.designation || "—" }}
						<span class="mx-1">·</span>{{ detail?.department || "—" }}
					</div>
				</div>
				<div class="d-flex gap-4 text-center px-2">
					<div>
						<div class="text-uppercase text-secondary" style="font-size: 0.65rem; letter-spacing: 0.05em">{{ t("Tenure") }}</div>
						<div class="h3 mb-0">{{ tenure }}</div>
					</div>
					<div>
						<div class="text-uppercase text-secondary" style="font-size: 0.65rem; letter-spacing: 0.05em">{{ t("TimePay ID") }}</div>
						<div class="h3 mb-0 font-monospace">{{ detail?.custom_timepay_id ? "#" + detail.custom_timepay_id : "—" }}</div>
					</div>
				</div>
				<div>
					<button type="button" class="btn btn-primary" :disabled="saving || loading" @click="save">
						<i class="ti ti-device-floppy me-1"></i>{{ saving ? t("Saving…") : t("Save") }}
					</button>
				</div>
			</div>
		</div>

		<div v-if="error" class="alert alert-danger mb-3">{{ error }}</div>

		<!-- Loading skeleton -->
		<div v-if="loading" class="card p-4 text-center">
			<div class="spinner-border text-primary mx-auto"></div>
		</div>

		<div v-else-if="detail">
			<!-- Tabs -->
			<div class="card mb-3">
				<div class="card-header">
					<ul class="nav nav-tabs card-header-tabs">
						<li class="nav-item">
							<button
								type="button"
								class="nav-link"
								:class="{ active: activeTab === 'profile' }"
								@click="activeTab = 'profile'"
							>
								<i class="ti ti-user me-1"></i>{{ t("Profile") }}
							</button>
						</li>
						<li class="nav-item">
							<button
								type="button"
								class="nav-link"
								:class="{ active: activeTab === 'employment' }"
								@click="activeTab = 'employment'"
							>
								<i class="ti ti-briefcase me-1"></i>{{ t("Employment") }}
							</button>
						</li>
						<li class="nav-item">
							<button
								type="button"
								class="nav-link"
								:class="{ active: activeTab === 'compensation' }"
								@click="activeTab = 'compensation'"
							>
								<i class="ti ti-cash me-1"></i>{{ t("Compensation") }}
							</button>
						</li>
						<li class="nav-item">
							<button
								type="button"
								class="nav-link"
								:class="{ active: activeTab === 'allowances' }"
								@click="activeTab = 'allowances'"
							>
								<i class="ti ti-plus-minus me-1"></i>{{ t("Allowances") }}
							</button>
						</li>
					</ul>
				</div>
			</div>

			<!-- ── PROFILE TAB ── -->
			<div v-if="activeTab === 'profile'" class="card">
				<div class="card-header">
					<h4 class="card-title mb-0">{{ t("Profile") }}</h4>
				</div>
				<div class="card-body">
					<div class="row g-3">
						<!-- Avatar preview -->
						<div class="col-12 d-flex align-items-center gap-3 mb-1">
							<span
								v-if="form.image"
								class="avatar avatar-xl"
								:style="{ backgroundImage: `url('${form.image}')` }"
							></span>
							<span v-else class="avatar avatar-xl bg-primary-lt" style="font-size: 1.5rem;">
								{{ initials(form.employee_name) }}
							</span>
							<div class="flex-grow-1">
								<label class="form-label">{{ t("Photo URL") }}</label>
								<input
									v-model="form.image"
									type="url"
									class="form-control"
									:placeholder="t('https://…')"
								/>
								<div class="form-text">{{ t("Paste a direct image URL or leave blank to use initials.") }}</div>
							</div>
						</div>

						<div class="col-md-6">
							<label class="form-label">{{ t("Full name") }}</label>
							<input
								v-model="form.employee_name"
								type="text"
								class="form-control"
							/>
						</div>

						<div class="col-md-6">
							<label class="form-label">{{ t("Status") }}</label>
							<Select v-model="form.status" :options="statusOptions" />
						</div>

						<div class="col-md-6">
							<label class="form-label">{{ t("Phone") }}</label>
							<input
								v-model="form.cell_number"
								type="tel"
								class="form-control"
								inputmode="tel"
							/>
						</div>

						<div class="col-md-3">
							<label class="form-label">{{ t("TimePay ID") }}</label>
							<input
								v-model="form.custom_timepay_id"
								type="text"
								class="form-control font-monospace"
							/>
						</div>

						<div class="col-md-3">
							<label class="form-label">{{ t("TimePay name") }}</label>
							<div class="form-control bg-secondary-lt text-secondary" style="min-height: 2.375rem; user-select: all;">
								{{ detail.custom_timepay_name || "—" }}
							</div>
							<div class="form-text">{{ t("Read-only — from TimePay system.") }}</div>
						</div>
					</div>
				</div>
			</div>

			<!-- ── EMPLOYMENT TAB ── -->
			<div v-if="activeTab === 'employment'" class="card">
				<div class="card-header">
					<h4 class="card-title mb-0">{{ t("Employment") }}</h4>
				</div>
				<div class="card-body">
					<div class="row g-3">
						<div class="col-md-6">
							<label class="form-label">{{ t("Department") }}</label>
							<input
								v-model="form.department"
								type="text"
								class="form-control"
								list="ep-dept-list"
								:placeholder="t('Department')"
							/>
							<datalist id="ep-dept-list">
								<option v-for="d in departmentOptions" :key="d.value" :value="d.value" />
							</datalist>
						</div>

						<div class="col-md-6">
							<label class="form-label">{{ t("Designation") }}</label>
							<input
								v-model="form.designation"
								type="text"
								class="form-control"
								list="ep-desig-list"
								:placeholder="t('Designation')"
							/>
							<datalist id="ep-desig-list">
								<option v-for="d in designationOptions" :key="d.value" :value="d.value" />
							</datalist>
						</div>

						<div class="col-md-6">
							<label class="form-label">{{ t("Date of joining") }}</label>
							<DateInput v-model="form.date_of_joining" />
						</div>

						<div class="col-md-6">
							<label class="form-label">{{ t("Relieving date") }}</label>
							<DateInput v-model="form.relieving_date" />
						</div>

						<div class="col-md-6">
							<label class="form-label">{{ t("Company") }}</label>
							<input
								v-model="form.company"
								type="text"
								class="form-control"
								:placeholder="t('Company')"
							/>
						</div>

						<div class="col-12">
							<div class="datagrid mt-2">
								<div class="datagrid-item">
									<div class="datagrid-title">{{ t("Employee ID") }}</div>
									<div class="datagrid-content font-monospace">{{ detail.name }}</div>
								</div>
								<div class="datagrid-item">
									<div class="datagrid-title">{{ t("Joined") }}</div>
									<div class="datagrid-content">{{ formatDate(detail.date_of_joining) }}</div>
								</div>
								<div v-if="detail.relieving_date" class="datagrid-item">
									<div class="datagrid-title">{{ t("Relieving date") }}</div>
									<div class="datagrid-content">{{ formatDate(detail.relieving_date) }}</div>
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>

			<!-- ── COMPENSATION TAB ── -->
			<div v-if="activeTab === 'compensation'">
				<!-- Payroll access gate -->
				<div v-if="!payrollVisible" class="card">
					<div class="card-body text-center py-5">
						<i class="ti ti-lock text-secondary mb-2" style="font-size: 2.5rem;"></i>
						<p class="text-secondary mb-0">{{ t("Compensation details are hidden — payroll access required.") }}</p>
					</div>
				</div>

				<div v-else class="row g-3">
					<div class="col-12">
						<div class="card">
							<div class="card-header">
								<h4 class="card-title mb-0">{{ t("Base salary") }}</h4>
							</div>
							<div class="card-body">
								<div class="row g-3">
									<div class="col-md-6">
										<label class="form-label">{{ t("Base salary (UZS)") }}</label>
										<MoneyInput
											v-model="form.custom_base_salary"
											currency="UZS"
											:language="lang"
										/>
									</div>
								</div>
							</div>
						</div>
					</div>

					<div class="col-md-6">
						<div class="card h-100">
							<div class="card-header">
								<h4 class="card-title mb-0">{{ t("Shift & region") }}</h4>
							</div>
							<div class="card-body">
								<div class="row g-3">
									<div class="col-12">
										<label class="form-label">{{ t("Shift class") }}</label>
										<Select v-model="form.custom_shift_class" :options="shiftClassOptions" />
									</div>
									<div class="col-12">
										<label class="form-label">{{ t("Region") }}</label>
										<Select v-model="form.custom_region" :options="regionOptions" />
									</div>
								</div>
							</div>
						</div>
					</div>

					<div class="col-md-6">
						<div class="card h-100">
							<div class="card-header">
								<h4 class="card-title mb-0">{{ t("Work mode") }}</h4>
							</div>
							<div class="card-body">
								<div class="row g-3">
									<div class="col-12">
										<label class="form-label">{{ t("Work mode") }}</label>
										<Select v-model="form.custom_work_mode" :options="workModeOptions" />
									</div>
									<div class="col-12">
										<label class="form-label">
											{{ t("Stake coefficient") }}
											<span v-if="!stakeEnabled" class="text-secondary ms-1 small">{{ t("(only for half-rate)") }}</span>
										</label>
										<input
											v-model.number="form.custom_stake_coefficient"
											type="number"
											class="form-control"
											min="0.1"
											max="2.0"
											step="0.1"
											:disabled="!stakeEnabled"
										/>
									</div>
								</div>
							</div>
						</div>
					</div>

					<div class="col-12">
						<div class="card">
							<div class="card-header">
								<h4 class="card-title mb-0">{{ t("Conditions") }}</h4>
							</div>
							<div class="card-body">
								<div class="row g-3">
									<div class="col-md-6">
										<label class="form-check form-switch mb-0 d-flex align-items-center gap-2">
											<input
												v-model="form.custom_heavy_conditions"
												type="checkbox"
												class="form-check-input"
												role="switch"
												:true-value="1"
												:false-value="0"
											/>
											<span class="form-check-label">{{ t("Heavy conditions") }}</span>
										</label>
										<div class="form-text ms-5">{{ t("Employee works in heavy/hazardous conditions.") }}</div>
									</div>
									<div class="col-md-6">
										<label class="form-check form-switch mb-0 d-flex align-items-center gap-2">
											<input
												v-model="form.custom_additional_duties"
												type="checkbox"
												class="form-check-input"
												role="switch"
												:true-value="1"
												:false-value="0"
											/>
											<span class="form-check-label">{{ t("Additional duties") }}</span>
										</label>
										<div class="form-text ms-5">{{ t("Employee carries additional responsibilities.") }}</div>
									</div>
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>

			<!-- ── ALLOWANCES TAB ── -->
			<div v-if="activeTab === 'allowances'">
				<!-- Payroll access gate -->
				<div v-if="!payrollVisible" class="card">
					<div class="card-body text-center py-5">
						<i class="ti ti-lock text-secondary mb-2" style="font-size: 2.5rem;"></i>
						<p class="text-secondary mb-0">{{ t("Allowances are hidden — payroll access required.") }}</p>
					</div>
				</div>

				<div v-else class="row g-3">
					<div class="col-12">
						<div class="card">
							<div class="card-header">
								<h4 class="card-title mb-0">{{ t("Standard allowances") }}</h4>
							</div>
							<div class="card-body">
								<div class="row g-3">
									<div class="col-md-6">
										<label class="form-label">{{ t("Seniority allowance (UZS)") }}</label>
										<MoneyInput
											v-model="form.allowance_seniority"
											currency="UZS"
											:language="lang"
											:placeholder="t('0')"
										/>
									</div>
									<div class="col-md-6">
										<label class="form-label">{{ t("Night allowance per hour (UZS)") }}</label>
										<MoneyInput
											v-model="form.allowance_night_per_hour"
											currency="UZS"
											:language="lang"
											:placeholder="t('0')"
										/>
									</div>
								</div>
							</div>
						</div>
					</div>

					<div class="col-12">
						<div class="card">
							<div class="card-header d-flex align-items-center">
								<h4 class="card-title mb-0">{{ t("Custom allowances") }}</h4>
								<button
									type="button"
									class="btn btn-ghost-secondary btn-sm ms-auto"
									@click="addCustomAllowance"
								>
									<i class="ti ti-plus me-1"></i>{{ t("Add") }}
								</button>
							</div>
							<div v-if="!form.allowance_custom.length" class="card-body text-secondary py-4 text-center">
								{{ t("No custom allowances. Click Add to create one.") }}
							</div>
							<div v-else class="table-responsive">
								<table class="table table-vcenter card-table">
									<thead>
										<tr>
											<th>{{ t("Label") }}</th>
											<th class="text-end">{{ t("Amount (UZS)") }}</th>
											<th style="width: 3rem;"></th>
										</tr>
									</thead>
									<tbody>
										<tr v-for="(item, idx) in form.allowance_custom" :key="idx">
											<td>
												<input
													v-model="item.label"
													type="text"
													class="form-control form-control-sm"
													:placeholder="t('Allowance name')"
												/>
											</td>
											<td>
												<MoneyInput
													v-model="item.amount"
													currency="UZS"
													:language="lang"
													size="sm"
													:placeholder="t('0')"
												/>
											</td>
											<td>
												<button
													type="button"
													class="btn btn-ghost-danger btn-sm"
													:title="t('Remove')"
													@click="removeCustomAllowance(idx)"
												>
													<i class="ti ti-trash"></i>
												</button>
											</td>
										</tr>
									</tbody>
								</table>
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
