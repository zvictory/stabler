<script setup>
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const toast = useToast();
const { confirm } = useConfirm();

const tab = ref("holidays");

// ── Holidays ─────────────────────────────────────────────────────────────────
const lists = ref([]);
const selectedList = ref("");
const listDetail = ref(null);
const defaultList = ref(null);
const loadingH = ref(false);
const newHoliday = ref({ holiday_date: "", description: "", weekly_off: false });

async function loadLists() {
	loadingH.value = true;
	try {
		const r = await call("stabler.api.hr_calendar.list_holiday_lists", { company: activeCompany.value });
		lists.value = r?.lists || [];
		defaultList.value = r?.default || null;
		if (!selectedList.value && lists.value.length) {
			selectedList.value = defaultList.value || lists.value[0].name;
		}
		if (selectedList.value) await loadDetail();
	} finally {
		loadingH.value = false;
	}
}
async function loadDetail() {
	if (!selectedList.value) return;
	listDetail.value = await call("stabler.api.hr_calendar.holiday_list_detail", { name: selectedList.value });
}
async function addHoliday() {
	if (!newHoliday.value.holiday_date) {
		toast.error(t("Pick a date."));
		return;
	}
	try {
		const r = await call("stabler.api.hr_calendar.add_holiday", {
			holiday_list: selectedList.value,
			holiday_date: newHoliday.value.holiday_date,
			description: newHoliday.value.description,
			weekly_off: newHoliday.value.weekly_off ? 1 : 0,
		});
		if (!r.added) toast.info(t("That date is already a holiday."));
		else toast.success(t("Holiday added."));
		newHoliday.value = { holiday_date: "", description: "", weekly_off: false };
		await loadDetail();
	} catch (err) {
		toast.error(err?.message || t("Could not add holiday."));
	}
}
async function removeHoliday(h) {
	const ok = await confirm({ title: t("Remove holiday?"), body: formatDate(h.holiday_date), danger: true, confirmLabel: t("Remove") });
	if (!ok) return;
	await call("stabler.api.hr_calendar.remove_holiday", { holiday_list: selectedList.value, holiday_date: h.holiday_date });
	await loadDetail();
}
async function setDefault() {
	await call("stabler.api.hr_calendar.set_company_holiday_list", { company: activeCompany.value, holiday_list: selectedList.value });
	toast.success(t("Set as company default."));
	await loadLists();
}
const isDefault = computed(() => selectedList.value && selectedList.value === defaultList.value);

// ── Payroll periods ──────────────────────────────────────────────────────────
const periods = ref([]);
const supported = ref(true);
const loadingP = ref(false);
const editPeriod = ref(null); // {name?, start_date, end_date}

async function loadPeriods() {
	loadingP.value = true;
	try {
		const r = await call("stabler.api.hr_calendar.list_payroll_periods", { company: activeCompany.value });
		periods.value = r?.periods || [];
		supported.value = r?.supported !== false;
	} finally {
		loadingP.value = false;
	}
}
function newPeriod() {
	editPeriod.value = { name: "", start_date: "", end_date: "" };
}
async function savePeriod() {
	const p = editPeriod.value;
	if (!p.start_date || !p.end_date) {
		toast.error(t("Pick start and end dates."));
		return;
	}
	try {
		await call("stabler.api.hr_calendar.upsert_payroll_period", {
			company: activeCompany.value, name: p.name || "", start_date: p.start_date, end_date: p.end_date,
		});
		toast.success(t("Saved."));
		editPeriod.value = null;
		await loadPeriods();
	} catch (err) {
		toast.error(err?.message || t("Could not save period."));
	}
}

onMounted(() => {
	loadLists();
	loadPeriods();
});
</script>

<template>
	<div class="container-xl py-3">
		<h2 class="mb-3">{{ t("Holidays & periods") }}</h2>
		<ul class="nav nav-tabs mb-3">
			<li class="nav-item">
				<button class="nav-link" :class="{ active: tab === 'holidays' }" @click="tab = 'holidays'">
					<i class="ti ti-calendar-event me-1"></i>{{ t("Holidays") }}
				</button>
			</li>
			<li class="nav-item">
				<button class="nav-link" :class="{ active: tab === 'periods' }" @click="tab = 'periods'">
					<i class="ti ti-calendar-stats me-1"></i>{{ t("Payroll periods") }}
				</button>
			</li>
		</ul>

		<!-- HOLIDAYS -->
		<div v-if="tab === 'holidays'" class="row g-3">
			<div class="col-12 col-lg-4">
				<div class="card">
					<div class="card-header"><h4 class="card-title mb-0">{{ t("Holiday list") }}</h4></div>
					<div class="card-body">
						<select v-model="selectedList" class="form-select mb-2" @change="loadDetail">
							<option v-for="l in lists" :key="l.name" :value="l.name">
								{{ l.holiday_list_name || l.name }}{{ l.is_default ? " ★" : "" }}
							</option>
						</select>
						<div v-if="isDefault" class="text-success small"><i class="ti ti-star-filled me-1"></i>{{ t("Company default") }}</div>
						<button v-else-if="selectedList" type="button" class="btn btn-outline-secondary btn-sm" @click="setDefault">
							<i class="ti ti-star me-1"></i>{{ t("Set as company default") }}
						</button>
					</div>
				</div>
				<div class="card mt-3">
					<div class="card-header"><h4 class="card-title mb-0">{{ t("Add holiday") }}</h4></div>
					<div class="card-body vstack gap-2">
						<DateInput v-model="newHoliday.holiday_date" />
						<input v-model="newHoliday.description" class="form-control" :placeholder="t('Description')" />
						<label class="form-check">
							<input v-model="newHoliday.weekly_off" type="checkbox" class="form-check-input" />
							<span class="form-check-label">{{ t("Weekly off") }}</span>
						</label>
						<button type="button" class="btn btn-primary" :disabled="!selectedList" @click="addHoliday">
							<i class="ti ti-plus me-1"></i>{{ t("Add") }}
						</button>
					</div>
				</div>
			</div>
			<div class="col-12 col-lg-8">
				<div class="card">
					<div class="card-header">
						<h4 class="card-title mb-0">{{ t("Holidays") }}</h4>
						<span v-if="listDetail" class="card-subtitle ms-auto">{{ listDetail.holidays.length }}</span>
					</div>
					<div class="card-body p-0">
						<div v-if="loadingH" class="text-center py-4"><span class="spinner-border text-primary"></span></div>
						<EmptyState v-else-if="!listDetail || !listDetail.holidays.length" :title="t('No holidays yet.')" />
						<table v-else class="table card-table">
							<thead><tr><th>{{ t("Date") }}</th><th>{{ t("Description") }}</th><th>{{ t("Weekly off") }}</th><th></th></tr></thead>
							<tbody>
								<tr v-for="h in listDetail.holidays" :key="h.holiday_date + h.description">
									<td>{{ formatDate(h.holiday_date) }}</td>
									<td>{{ h.description }}</td>
									<td><span v-if="h.weekly_off" class="badge bg-secondary-lt">{{ t("Weekly off") }}</span></td>
									<td class="text-end">
										<button type="button" class="btn btn-ghost-danger btn-sm" @click="removeHoliday(h)"><i class="ti ti-trash"></i></button>
									</td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>
			</div>
		</div>

		<!-- PAYROLL PERIODS -->
		<div v-else class="row g-3">
			<div class="col-12">
				<div v-if="!supported" class="alert alert-info">{{ t("Payroll Period is not available on this site.") }}</div>
				<div v-else class="card">
					<div class="card-header">
						<h4 class="card-title mb-0">{{ t("Payroll periods") }}</h4>
						<button type="button" class="btn btn-primary btn-sm ms-auto" @click="newPeriod">
							<i class="ti ti-plus me-1"></i>{{ t("New period") }}
						</button>
					</div>
					<div class="card-body p-0">
						<div v-if="loadingP" class="text-center py-4"><span class="spinner-border text-primary"></span></div>
						<EmptyState v-else-if="!periods.length" :title="t('No payroll periods yet.')" />
						<table v-else class="table card-table">
							<thead><tr><th>{{ t("Name") }}</th><th>{{ t("Start") }}</th><th>{{ t("End") }}</th><th></th></tr></thead>
							<tbody>
								<tr v-for="p in periods" :key="p.name">
									<td>{{ p.name }}</td>
									<td>{{ formatDate(p.start_date) }}</td>
									<td>{{ formatDate(p.end_date) }}</td>
									<td class="text-end">
										<button type="button" class="btn btn-ghost-secondary btn-sm" @click="editPeriod = { name: p.name, start_date: p.start_date, end_date: p.end_date }">
											<i class="ti ti-edit"></i>
										</button>
									</td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>

				<div v-if="editPeriod" class="card mt-3">
					<div class="card-header"><h4 class="card-title mb-0">{{ editPeriod.name ? t("Edit period") : t("New period") }}</h4></div>
					<div class="card-body">
						<div class="row g-2 align-items-end">
							<div class="col-auto"><label class="form-label">{{ t("Start") }}</label><DateInput v-model="editPeriod.start_date" /></div>
							<div class="col-auto"><label class="form-label">{{ t("End") }}</label><DateInput v-model="editPeriod.end_date" /></div>
							<div class="col-auto">
								<button type="button" class="btn btn-primary" @click="savePeriod"><i class="ti ti-check me-1"></i>{{ t("Save") }}</button>
								<button type="button" class="btn btn-link link-secondary" @click="editPeriod = null">{{ t("Cancel") }}</button>
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
