<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDateTime, todayIso } from "../../composables/date.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";

// Measured on anjan 2026-08-28: 0 Downtime Entry rows against 3757 Manufacture
// entries. Nothing has ever been recorded about why a line stopped, and
// ERPNext's own doctype cannot record it here — its three required fields want
// a Workstation (0 exist), an Employee carrying a user_id (0 of 439 do), and a
// reason from a seven-option machine-shop Select.
//
// So this screen writes `Stabler Line Stop`, keyed on `wip_warehouse` like the
// shift log and the plan board.
const session = useSession();
const { activeCompany } = storeToRefs(session);

const loading = ref(false);
const saving = ref(false);
const error = ref("");
const formError = ref("");
const notice = ref("");
const rows = ref([]);
const reasons = ref([]);
const lines = ref([]);
const orders = ref([]);

const fromDate = ref(addDays(todayIso(), -6));
const toDate = ref(todayIso());
const lineFilter = ref("");

const form = ref(blankForm());

function blankForm() {
	return { day: todayIso(), from: "", to: "", line: "", reason: "", work_order: "", note: "" };
}

function addDays(iso, n) {
	const d = new Date(`${iso}T00:00:00`);
	d.setDate(d.getDate() + n);
	const pad = (x) => String(x).padStart(2, "0");
	return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// A shift lead says "today, 23:40 to 00:10", not "the 28th to the 29th". So the
// form takes one day and two clock times, and a `to` that reads earlier than
// `from` means the stop crossed midnight — the night shift runs here, orders are
// opened as late as 23:00. A genuine typo (09:00 to 08:00) becomes a 23-hour
// stop and is refused by the 12-hour rule on the server, which is the right
// place for it: the same refusal then covers a Desk write.
function stopWindow(day, from, to) {
	if (!day || !from || !to) return null;
	const endDay = to <= from ? addDays(day, 1) : day;
	return { from_time: `${day} ${from}:00`, to_time: `${endDay} ${to}:00` };
}

const reasonOptions = computed(() =>
	reasons.value.map((r) => ({ value: r.name, label: t(r.reason) }))
);
const lineOptions = computed(() => lines.value.map((l) => ({ value: l.name, label: l.name })));
const lineFilterOptions = computed(() => [
	{ value: "", label: t("All lines") },
	...lineOptions.value,
]);

const totalMinutes = computed(() => rows.value.reduce((sum, r) => sum + Number(r.minutes || 0), 0));

const reasonLabel = (name) => {
	const hit = reasons.value.find((r) => r.name === name);
	return hit ? t(hit.reason) : name;
};

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.manufacturing.list_line_stops", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			line: lineFilter.value || undefined,
		});
	} catch (e) {
		error.value = e?.message || String(e);
	} finally {
		loading.value = false;
	}
}

async function loadPickers() {
	if (!activeCompany.value) return;
	try {
		[reasons.value, lines.value] = await Promise.all([
			call("stabler.api.manufacturing.list_stop_reasons", {
				company: activeCompany.value,
				kind: "Downtime",
			}),
			call("stabler.api.manufacturing.list_work_order_lines", { company: activeCompany.value }),
		]);
	} catch (e) {
		error.value = e?.message || String(e);
	}
}

// The orders that were on this line that day, so the stop can name one without
// anybody typing an order id. A stop between orders keeps an empty box.
async function loadOrders() {
	orders.value = [];
	form.value.work_order = "";
	if (!activeCompany.value || !form.value.line || !form.value.day) return;
	try {
		orders.value = await call("stabler.api.manufacturing.list_work_orders", {
			company: activeCompany.value,
			line: form.value.line,
			from_date: form.value.day,
			to_date: form.value.day,
			limit: 100,
		});
	} catch {
		// A missing order list must not block recording the stop.
		orders.value = [];
	}
}

const orderOptions = computed(() => [
	{ value: "", label: t("No order — the line was between jobs") },
	...orders.value.map((o) => ({
		value: o.name,
		label: `${o.name} · ${o.item_name || o.production_item}`,
	})),
]);

async function save() {
	formError.value = "";
	notice.value = "";
	const window = stopWindow(form.value.day, form.value.from, form.value.to);
	if (!window) {
		formError.value = t("Fill in the day and both times.");
		return;
	}
	if (!form.value.line || !form.value.reason) {
		formError.value = t("Pick the line and the reason.");
		return;
	}
	saving.value = true;
	try {
		const out = await call("stabler.api.manufacturing.log_line_stop", {
			company: activeCompany.value,
			line: form.value.line,
			reason: form.value.reason,
			work_order: form.value.work_order || undefined,
			note: form.value.note || undefined,
			...window,
		});
		notice.value = t("Recorded: {0} minutes").replace("{0}", out.minutes);
		form.value = blankForm();
		orders.value = [];
		await load();
	} catch (e) {
		formError.value = e?.message || String(e);
	} finally {
		saving.value = false;
	}
}

watch(activeCompany, () => {
	loadPickers();
	load();
});
watch([fromDate, toDate, lineFilter], load);
watch([() => form.value.line, () => form.value.day], loadOrders);
onMounted(() => {
	loadPickers();
	load();
});
</script>

<template>
	<div class="row g-3">
		<div class="col-12 col-lg-5">
			<div class="card">
				<div class="card-header">
					<h3 class="card-title">{{ t("Record a stop") }}</h3>
				</div>
				<div class="card-body">
					<div class="mb-2">
						<label class="form-label">{{ t("Line") }}</label>
						<Select v-model="form.line" :options="lineOptions" :placeholder="t('Pick a line')" />
					</div>
					<div class="row g-2 mb-2">
						<div class="col-12 col-sm-6">
							<label class="form-label">{{ t("Day") }}</label>
							<DateInput v-model="form.day" />
						</div>
						<div class="col-6 col-sm-3">
							<label class="form-label">{{ t("From") }}</label>
							<input v-model="form.from" type="time" class="form-control" />
						</div>
						<div class="col-6 col-sm-3">
							<label class="form-label">{{ t("To") }}</label>
							<input v-model="form.to" type="time" class="form-control" />
						</div>
					</div>
					<p class="form-hint mb-2">
						{{ t("An end time earlier than the start means the stop ran past midnight.") }}
					</p>
					<div class="mb-2">
						<label class="form-label">{{ t("Reason") }}</label>
						<Select
							v-model="form.reason"
							:options="reasonOptions"
							:placeholder="t('Pick a reason')"
						/>
					</div>
					<div class="mb-2">
						<label class="form-label">{{ t("Work Order") }}</label>
						<Select v-model="form.work_order" :options="orderOptions" />
					</div>
					<div class="mb-3">
						<label class="form-label">{{ t("Note") }}</label>
						<textarea v-model="form.note" class="form-control" rows="2"></textarea>
					</div>
					<div v-if="formError" class="alert alert-danger py-2">{{ formError }}</div>
					<div v-if="notice" class="alert alert-success py-2">{{ notice }}</div>
					<button type="button" class="btn btn-primary w-100" :disabled="saving" @click="save">
						{{ saving ? t("Saving") : t("Record the stop") }}
					</button>
				</div>
			</div>
		</div>

		<div class="col-12 col-lg-7">
			<div class="card mb-3">
				<div class="card-body d-flex flex-wrap gap-2 align-items-end">
					<div style="width: 10rem">
						<label class="form-label">{{ t("From") }}</label>
						<DateInput v-model="fromDate" />
					</div>
					<div style="width: 10rem">
						<label class="form-label">{{ t("To") }}</label>
						<DateInput v-model="toDate" />
					</div>
					<div style="min-width: 12rem">
						<label class="form-label">{{ t("Line") }}</label>
						<Select v-model="lineFilter" :options="lineFilterOptions" />
					</div>
					<div class="ms-auto text-secondary small">
						<!-- Count and summed minutes only. A "% of shift lost" figure would
						     need a shift length nothing on this site records, and a
						     percentage is read as a measurement and acted on. -->
						{{ t("{0} stops").replace("{0}", rows.length) }} ·
						{{ t("{0} minutes").replace("{0}", Math.round(totalMinutes)) }}
					</div>
				</div>
			</div>

			<div class="card">
				<div class="table-responsive">
					<table class="table table-vcenter card-table">
						<thead>
							<tr>
								<th>{{ t("From") }}</th>
								<th>{{ t("Line") }}</th>
								<th>{{ t("Reason") }}</th>
								<th class="text-end">{{ t("Minutes") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="row in rows" :key="row.name">
								<td>{{ formatDateTime(row.from_time) }}</td>
								<td class="text-truncate">{{ row.line }}</td>
								<td>
									{{ reasonLabel(row.reason) }}
									<span v-if="row.note" class="d-block text-secondary small">{{ row.note }}</span>
								</td>
								<td class="text-end font-monospace">{{ row.minutes }}</td>
							</tr>
						</tbody>
					</table>
				</div>
				<div v-if="loading" class="card-footer text-secondary small">{{ t("Loading") }}</div>
				<div v-else-if="!rows.length" class="card-body">
					<EmptyState
						icon="ti ti-player-pause"
						:title="t('No stops recorded in this window')"
						:description="
							t(
								'Nothing on this floor has ever been recorded as a stop. The first one goes in on the left.'
							)
						"
					/>
				</div>
			</div>
		</div>
	</div>
</template>
