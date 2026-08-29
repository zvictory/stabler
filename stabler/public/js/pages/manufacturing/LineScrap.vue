<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDateTime, todayIso } from "../../composables/date.js";
import { getStatusBadgeClass, getDocstatusLabel } from "../../composables/status.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";

// The twin of LineStops.vue, one question later: that screen records why the
// line was not running, this one records what did not survive it.
//
// Measured on anjan 2026-08-27: the floor already moves scrap through the stock
// ledger by hand — 25 Stock Entries, 35 037 units, into two scrap warehouses,
// with the reason surviving only as a free-text Uzbek paragraph in `remarks`.
// So this screen does not invent a flow; it gives the existing one a reason code
// and a keyboard. `log_line_scrap` writes the record AND a draft Material
// Transfer, which accounting submits in the Desk exactly as they do today.
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
// The `wo_scrap_options` answer for the order currently in the form, or null
// while nothing has been asked or the answer has not arrived.
const scrapOptions = ref(null);

const fromDate = ref(addDays(todayIso(), -6));
const toDate = ref(todayIso());
const lineFilter = ref("");

const form = ref(blankForm());

function blankForm() {
	return { line: "", work_order: "", item_code: "", qty: "", reason: "", note: "" };
}

function addDays(iso, n) {
	const d = new Date(`${iso}T00:00:00`);
	d.setDate(d.getDate() + n);
	const pad = (x) => String(x).padStart(2, "0");
	return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// What this screen may do next, in one word, from the one endpoint that knows.
//
// "unconfigured" is the state every tenant is in today: `scrap_warehouse` is
// unset everywhere, and `get_scrap_warehouse` throws rather than carrying on
// without it — deliberately, because a record without its draft is
// indistinguishable later from one whose draft somebody deleted. That throw
// reaches a shop-floor terminal as a server error in front of the one person who
// cannot fix it, so the screen asks first and says who can.
//
// The order of the two refusals matches the server's: `validate` reads the
// warehouse BEFORE it checks the quantity, so "your site was never set up" is
// never dressed up as "your number is wrong".
function scrapReadiness(options) {
	if (!options) return "unknown";
	if (!options.scrap_warehouse) return "unconfigured";
	const items = options.items || [];
	if (!items.some((i) => Number(i.available) > 0)) return "nothing-in-wip";
	return "ready";
}

// `log_line_scrap` returns the draft's name as well as the record's, for one
// stated reason: the operator has to be told that a stock document now exists in
// somebody else's queue. Dropping it turns a two-party handover into a silent
// one — the operator believes the loss is filed and done, and the transfer sits
// unsubmitted until somebody happens to look.
function recordedNotice(out) {
	if (!out || !out.stock_entry) return t("Loss recorded.");
	return t("Loss recorded. Stock transfer {0} is now waiting for accounting to submit it.", [
		out.stock_entry,
	]);
}

const readiness = computed(() => scrapReadiness(scrapOptions.value));

const reasonOptions = computed(() =>
	reasons.value.map((r) => ({ value: r.name, label: t(r.reason) }))
);
const lineOptions = computed(() => lines.value.map((l) => ({ value: l.name, label: l.name })));
const lineFilterOptions = computed(() => [
	{ value: "", label: t("All lines") },
	...lineOptions.value,
]);
const orderOptions = computed(() =>
	orders.value.map((o) => ({
		value: o.name,
		label: `${o.name} · ${o.item_name || o.production_item}`,
	}))
);

// Only what is actually standing in WIP on this order. An item with nothing left
// is refused by `validate_scrap` ("has nothing in WIP on this order to scrap"),
// and a picker whose entries are a coin toss is one the operator stops trusting
// after the first refusal. The ceiling travels with the label for the same
// reason — the server knows it, so the operator should too.
const itemOptions = computed(() =>
	(scrapOptions.value?.items || [])
		.filter((i) => Number(i.available) > 0)
		.map((i) => ({
			value: i.item_code,
			label: `${i.item_name || i.item_code} · ${i.available} ${i.uom || ""}`.trim(),
		}))
);

const reasonLabel = (name) => {
	const hit = reasons.value.find((r) => r.name === name);
	return hit ? t(hit.reason) : name;
};

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.manufacturing.list_line_scrap", {
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
			// The Loss half of the catalogue, never the whole of it: filing "Waiting
			// for material" as the reason 30 kg went in the bin is a row that reads
			// as data and is not. The server refuses it too (`_assert_loss_reason`).
			call("stabler.api.manufacturing.list_stop_reasons", {
				company: activeCompany.value,
				kind: "Loss",
			}),
			call("stabler.api.manufacturing.list_work_order_lines", { company: activeCompany.value }),
		]);
	} catch (e) {
		error.value = e?.message || String(e);
	}
}

// The orders on this line, so the loss can name one without anybody typing an
// order id. Unlike a stop, the order is required: lost material came out of a
// specific WIP warehouse that a specific order carried it to.
async function loadOrders() {
	orders.value = [];
	form.value.work_order = "";
	if (!activeCompany.value || !form.value.line) return;
	try {
		orders.value = await call("stabler.api.manufacturing.list_work_orders", {
			company: activeCompany.value,
			line: form.value.line,
			limit: 100,
		});
	} catch {
		orders.value = [];
	}
}

async function loadScrapOptions() {
	scrapOptions.value = null;
	form.value.item_code = "";
	if (!form.value.work_order) return;
	try {
		scrapOptions.value = await call("stabler.api.manufacturing.wo_scrap_options", {
			work_order: form.value.work_order,
		});
	} catch (e) {
		// Unlike the order list, this one is fatal to the form: without it there is
		// no item list, no ceiling and no answer about the scrap warehouse, and
		// every one of those is a refusal the operator would otherwise meet after
		// typing rather than before.
		formError.value = e?.message || String(e);
	}
}

async function save() {
	formError.value = "";
	notice.value = "";
	saving.value = true;
	try {
		const out = await call("stabler.api.manufacturing.log_line_scrap", {
			company: activeCompany.value,
			work_order: form.value.work_order,
			item_code: form.value.item_code,
			qty: Number(form.value.qty),
			reason: form.value.reason,
			note: form.value.note || undefined,
		});
		notice.value = recordedNotice(out);
		const line = form.value.line;
		form.value = { ...blankForm(), line };
		scrapOptions.value = null;
		await loadOrders();
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
watch(() => form.value.line, loadOrders);
watch(() => form.value.work_order, loadScrapOptions);
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
					<h3 class="card-title">{{ t("Record a loss") }}</h3>
				</div>
				<div class="card-body">
					<div class="mb-2">
						<label class="form-label">{{ t("Line") }}</label>
						<Select v-model="form.line" :options="lineOptions" :placeholder="t('Pick a line')" />
					</div>
					<div class="mb-2">
						<label class="form-label">{{ t("Work Order") }}</label>
						<Select
							v-model="form.work_order"
							:options="orderOptions"
							:placeholder="t('Pick the order the material was on')"
						/>
					</div>

					<!-- Not an error toast: on every tenant today this is the state, and
						 the operator who meets it cannot fix it. So it names the document
						 to change and the role that may change it, and it says so before
						 anything has been typed. No Desk link — the SPA never sends
						 anybody to /app. -->
					<div v-if="readiness === 'unconfigured'" class="alert alert-warning">
						<div class="fw-bold mb-1">
							<i class="ti ti-settings-exclamation me-1"></i>{{ t("Scrap is not set up on this site yet") }}
						</div>
						<p class="mb-0">
							{{
								t(
									"Nothing can be recorded until a scrap warehouse is named in Stabler Manufacturing Settings. Ask a manufacturing manager to name one — the loss has to have somewhere to move to, or the record and the stock ledger would disagree."
								)
							}}
						</p>
					</div>

					<div v-else-if="readiness === 'nothing-in-wip'" class="alert alert-info">
						{{ t("This order has nothing standing in WIP to scrap.") }}
					</div>

					<template v-else-if="readiness === 'ready'">
						<div class="mb-2">
							<label class="form-label">{{ t("Item") }}</label>
							<Select
								v-model="form.item_code"
								:options="itemOptions"
								:placeholder="t('Pick what was lost')"
							/>
						</div>
						<div class="mb-2">
							<label class="form-label">{{ t("Quantity") }}</label>
							<input v-model="form.qty" type="number" step="any" min="0" class="form-control font-monospace" />
						</div>
						<div class="mb-2">
							<label class="form-label">{{ t("Reason") }}</label>
							<Select
								v-model="form.reason"
								:options="reasonOptions"
								:placeholder="t('Pick a reason')"
							/>
						</div>
						<div class="mb-3">
							<label class="form-label">{{ t("Note") }}</label>
							<textarea v-model="form.note" class="form-control" rows="2"></textarea>
						</div>
					</template>

					<div v-else class="text-secondary small mb-3">
						{{ t("Pick a line and a Work Order to record a loss against.") }}
					</div>

					<div v-if="formError" class="alert alert-danger py-2">{{ formError }}</div>
					<div v-if="notice" class="alert alert-success py-2">{{ notice }}</div>
					<button
						type="button"
						class="btn btn-primary w-100"
						:disabled="saving || readiness !== 'ready' || !form.work_order || !form.item_code || !form.reason || !(Number(form.qty) > 0)"
						@click="save"
					>
						{{ saving ? t("Saving") : t("Record the loss") }}
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
						<!-- A count, and nothing summed. The rows carry different items in
							 different UOMs, so one total across them is a number that looks
							 like a measurement and is not. -->
						{{ t("{0} losses", [rows.length]) }}
					</div>
				</div>
			</div>

			<div v-if="error" class="alert alert-danger">{{ error }}</div>

			<div class="card">
				<div class="table-responsive">
					<table class="table table-vcenter card-table">
						<thead>
							<tr>
								<th>{{ t("When") }}</th>
								<th>{{ t("Item") }}</th>
								<th class="text-end">{{ t("Quantity") }}</th>
								<th>{{ t("Reason") }}</th>
								<th>{{ t("Stock transfer") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="row in rows" :key="row.name">
								<td>
									{{ formatDateTime(row.creation) }}
									<span class="d-block text-secondary small">{{ row.work_order }}</span>
								</td>
								<td class="text-truncate">{{ row.item_code }}</td>
								<td class="text-end font-monospace">{{ row.qty }} {{ row.uom }}</td>
								<td>
									{{ reasonLabel(row.reason) }}
									<span v-if="row.note" class="d-block text-secondary small">{{ row.note }}</span>
								</td>
								<td>
									<!-- Read live from the Stock Entry, never mirrored: accounting
										 submits or cancels these in the Desk, which is the entire
										 life of the document. -->
									<span
										v-if="row.stock_entry"
										class="badge"
										:class="getStatusBadgeClass('Stock Entry', row.stock_entry_docstatus)"
									>
										{{ getDocstatusLabel(row.stock_entry_docstatus) }}
									</span>
									<span v-else class="text-secondary small">—</span>
								</td>
							</tr>
						</tbody>
					</table>
				</div>
				<div v-if="loading" class="card-footer text-secondary small">{{ t("Loading") }}</div>
				<div v-else-if="!rows.length" class="card-body">
					<EmptyState
						icon="ti ti-trash"
						:title="t('No losses recorded in this window')"
						:description="
							t(
								'Scrap on this floor has only ever been filed by hand, with the reason buried in a stock entry remark. The first one with a reason code goes in on the left.'
							)
						"
					/>
				</div>
			</div>
		</div>
	</div>
</template>
