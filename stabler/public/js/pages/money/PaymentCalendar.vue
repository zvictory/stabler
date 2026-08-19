<!--
Payment Calendar — everyone writes their own plan; an authorised reader sees the sum.

The page is three things side by side: the month grid, the form that fills it, and
(for a Payment Plan Manager) the totals nobody else may read. Nothing here posts a
payment — a row is a forecast, money still leaves through Payments / Kassa /
Journal, and a plan is closed by hand.
-->

<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { call } from "../../api/client.js";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import {
	KIND_OPTIONS,
	KIND_EXTRA,
	CONFIDENCE_OPTIONS,
	REPEAT_OPTIONS,
	directionOf,
	monthBounds,
	currentMonth,
	calendarEvents,
	monthSummary,
} from "../../composables/paymentPlan.js";
import { accountLabel } from "../../composables/accounts.js";
import CalendarMonth from "../../components/CalendarMonth.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const company = computed(() => session.activeCompany);
const language = computed(() => session.user?.language || "en");
const baseCurrency = computed(() => session.currency);
const isManager = computed(
	() => session.isAdmin || (session.roles || []).includes("Payment Plan Manager"),
);

const month = ref(currentMonth());
const scope = ref("mine"); // "mine" | "all" — only a manager may leave "mine"
const loading = ref(false);
const error = ref("");
const entries = ref([]);
const days = ref([]);
const totals = ref(null);

const summary = computed(() => monthSummary(days.value));
const events = computed(() => calendarEvents(entries.value));

// A manager viewing "my plan" is filtered to themselves; everyone else always is,
// and the server enforces that regardless of what this sends.
const ownerParam = computed(() =>
	isManager.value && scope.value === "all" ? null : session.user?.id || null,
);

async function load() {
	if (!company.value) return;
	loading.value = true;
	error.value = "";
	const { from, to } = monthBounds(month.value);
	try {
		const args = { company: company.value, from_date: from, to_date: to, owner_user: ownerParam.value };
		const [rows, buckets] = await Promise.all([
			call("stabler.api.payment_plan.payment_plan_list", args),
			call("stabler.api.payment_plan.payment_plan_calendar", args),
		]);
		entries.value = rows || [];
		days.value = buckets || [];
		totals.value = isManager.value
			? await call("stabler.api.payment_plan.payment_plan_totals", {
					company: company.value,
					from_date: from,
					to_date: to,
				})
			: null;
	} catch (err) {
		error.value = err?.message || t("Failed to load the payment calendar.");
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch([company, month, scope], load);

// ── The form ─────────────────────────────────────────────────────────────────
const blank = () => ({
	name: null,
	kind: "Vendor Payment",
	due_date: `${monthBounds(month.value).from.slice(0, 8)}${String(new Date().getDate()).padStart(2, "0")}`,
	party_type: "",
	party: "",
	reference_doctype: "",
	reference_name: "",
	expense_account: "",
	item_code: "",
	qty: null,
	rate: null,
	currency: baseCurrency.value,
	amount: null,
	exchange_rate: 1,
	confidence: "Expected",
	status: "Planned",
	realized_on: "",
	note: "",
	repeat: "Once",
	repeat_count: 1,
});

const form = ref(blank());
const saving = ref(false);
const formError = ref("");
const extraField = computed(() => KIND_EXTRA[form.value.kind] || "");
const isEdit = computed(() => Boolean(form.value.name));

// Options for the dynamic second field, loaded only for the kind that needs them.
const documentTypes = ref([]);
const documentOptions = ref([]);
const accountOptions = ref([]);
const itemOptions = ref([]);

async function loadDocumentTypes() {
	if (documentTypes.value.length || !company.value) return;
	documentTypes.value = await call("stabler.api.payment_plan.payment_plan_reference_doctypes", {
		company: company.value,
	});
}

async function loadDocuments() {
	documentOptions.value = form.value.reference_doctype
		? await call("stabler.api.payment_plan.payment_plan_document_options", {
				company: company.value,
				reference_doctype: form.value.reference_doctype,
			})
		: [];
}

async function loadExtras() {
	if (!company.value) return;
	if (extraField.value === "document") {
		await loadDocumentTypes();
		await loadDocuments();
	} else if (extraField.value === "account" && !accountOptions.value.length) {
		accountOptions.value = await call("stabler.api.payment_plan.payment_plan_account_options", {
			company: company.value,
		});
	} else if (extraField.value === "item" && !itemOptions.value.length) {
		itemOptions.value = await call("stabler.api.payment_plan.payment_plan_item_options", {
			company: company.value,
		});
	}
}
watch([extraField, company], loadExtras, { immediate: true });

/** Picking the document is what makes the form smart: amount, date and party
 *  come off the real record instead of being retyped. */
function onDocumentPicked() {
	const doc = documentOptions.value.find((d) => d.name === form.value.reference_name);
	if (!doc) return;
	form.value.party_type = doc.party_type;
	form.value.party = doc.party;
	form.value.currency = doc.currency || form.value.currency;
	if (doc.amount) form.value.amount = doc.amount;
	if (doc.due_date) form.value.due_date = String(doc.due_date).slice(0, 10);
}

const baseEquivalent = computed(() => {
	const amount = Number(form.value.amount) || 0;
	const rate = Number(form.value.exchange_rate) || 1;
	return amount * rate;
});
const needsRate = computed(() => form.value.currency && form.value.currency !== baseCurrency.value);

function edit(row) {
	form.value = { ...blank(), ...row, due_date: String(row.due_date || "").slice(0, 10) };
	formError.value = "";
}

function openDay(date) {
	form.value = { ...blank(), due_date: date };
	formError.value = "";
}

async function save() {
	saving.value = true;
	formError.value = "";
	const { name, repeat, repeat_count, ...payload } = form.value;
	try {
		await call("stabler.api.payment_plan.save_payment_plan_entry", {
			company: company.value,
			name,
			payload,
			repeat,
			repeat_count,
		});
		form.value = blank();
		await load();
	} catch (err) {
		formError.value = err?.message || t("Failed to save the plan.");
	} finally {
		saving.value = false;
	}
}

async function remove() {
	if (!form.value.name) return;
	saving.value = true;
	formError.value = "";
	try {
		await call("stabler.api.payment_plan.delete_payment_plan_entry", {
			company: company.value,
			name: form.value.name,
		});
		form.value = blank();
		await load();
	} catch (err) {
		formError.value = err?.message || t("Failed to delete the plan.");
	} finally {
		saving.value = false;
	}
}

function kindLabel(value) {
	return KIND_OPTIONS.find((k) => k.value === value)?.label() || value;
}
</script>

<template>
	<div class="mb-3 d-flex flex-wrap align-items-center gap-2">
		<div>
			<h2 class="h3 mb-0">{{ t("Payment Calendar") }}</h2>
			<div class="text-secondary small">
				{{ t("Everyone enters their own plan. The calendar shows the days it lands on.") }}
			</div>
		</div>
		<div v-if="isManager" class="btn-group btn-group-sm ms-auto" role="group">
			<button
				type="button"
				class="btn"
				:class="scope === 'mine' ? 'btn-primary' : 'btn-outline-secondary'"
				@click="scope = 'mine'"
			>
				{{ t("My plan") }}
			</button>
			<button
				type="button"
				class="btn"
				:class="scope === 'all' ? 'btn-primary' : 'btn-outline-secondary'"
				@click="scope = 'all'"
			>
				{{ t("Whole company") }}
			</button>
		</div>
	</div>

	<div v-if="error" class="alert alert-danger py-2 px-3">{{ error }}</div>

	<!-- The month at a glance, in the base currency every row is summed into. -->
	<div class="row g-2 mb-3">
		<div class="col-6 col-lg-3">
			<div class="card"><div class="card-body py-2 px-3">
				<div class="text-secondary small">{{ t("Incoming") }}</div>
				<div class="h3 mb-0 font-monospace text-teal">{{ formatMoney(summary.inflow, baseCurrency) }}</div>
			</div></div>
		</div>
		<div class="col-6 col-lg-3">
			<div class="card"><div class="card-body py-2 px-3">
				<div class="text-secondary small">{{ t("Outgoing") }}</div>
				<div class="h3 mb-0 font-monospace text-orange">{{ formatMoney(summary.outflow, baseCurrency) }}</div>
			</div></div>
		</div>
		<div class="col-6 col-lg-3">
			<div class="card"><div class="card-body py-2 px-3">
				<div class="text-secondary small">{{ t("Net") }}</div>
				<div class="h3 mb-0 font-monospace" :class="summary.net < 0 ? 'text-danger' : ''">
					{{ formatMoney(summary.net, baseCurrency) }}
				</div>
			</div></div>
		</div>
		<div class="col-6 col-lg-3">
			<div class="card"><div class="card-body py-2 px-3">
				<div class="text-secondary small">{{ t("Heaviest day") }}</div>
				<div class="h3 mb-0">{{ summary.heaviest ? formatDate(summary.heaviest) : "—" }}</div>
			</div></div>
		</div>
	</div>

	<div class="row g-3">
		<div class="col-12 col-xl-7">
			<div class="card">
				<div class="card-header py-2">
					<h3 class="card-title mb-0">{{ t("Month") }}</h3>
					<span class="ms-auto text-secondary small">{{ t("Click a day to plan on it") }}</span>
				</div>
				<div class="card-body">
					<CalendarMonth
						v-model:month="month"
						:events="events"
						:currency="baseCurrency"
						:language="language"
						:empty-text='t("Nothing planned this month yet.")'
						@select="edit($event.entry)"
						@select-day="openDay"
					/>
					<div class="d-flex flex-wrap gap-3 mt-2 small text-secondary">
						<span><span class="legend-dot legend-dot--in"></span> {{ t("Incoming") }}</span>
						<span><span class="legend-dot legend-dot--out"></span> {{ t("Outgoing") }}</span>
						<span><span class="legend-dot legend-dot--done"></span> {{ t("Realized") }}</span>
					</div>
				</div>
			</div>

			<div v-if="isManager && totals" class="card mt-3">
				<div class="card-header py-2">
					<h3 class="card-title mb-0">{{ t("Totals by planner") }}</h3>
					<span class="ms-auto text-secondary small">{{ t("Visible to authorised roles only") }}</span>
				</div>
				<div class="table-responsive">
					<table class="table table-sm mb-0">
						<thead>
							<tr>
								<th>{{ t("Planned by") }}</th>
								<th class="text-end">{{ t("Rows") }}</th>
								<th class="text-end">{{ t("Incoming") }}</th>
								<th class="text-end">{{ t("Outgoing") }}</th>
								<th class="text-end">{{ t("Net") }}</th>
							</tr>
						</thead>
						<SkeletonRows v-if="loading" :rows="3" :cols="5" />
						<tbody v-else>
							<tr v-for="row in totals.by_planner" :key="row.owner_user">
								<td>{{ row.owner_user }}</td>
								<td class="text-end">{{ row.entries }}</td>
								<td class="text-end font-monospace">{{ formatMoney(row.inflow, baseCurrency) }}</td>
								<td class="text-end font-monospace">{{ formatMoney(row.outflow, baseCurrency) }}</td>
								<td class="text-end font-monospace" :class="row.inflow - row.outflow < 0 ? 'text-danger' : ''">
									{{ formatMoney(row.inflow - row.outflow, baseCurrency) }}
								</td>
							</tr>
						</tbody>
						<tfoot>
							<tr class="fw-semibold">
								<td>{{ t("Total") }}</td>
								<td></td>
								<td class="text-end font-monospace">{{ formatMoney(totals.inflow, baseCurrency) }}</td>
								<td class="text-end font-monospace">{{ formatMoney(totals.outflow, baseCurrency) }}</td>
								<td class="text-end font-monospace">{{ formatMoney(totals.net, baseCurrency) }}</td>
							</tr>
						</tfoot>
					</table>
				</div>
			</div>
		</div>

		<!-- The form. One primary button; everything else neutral. -->
		<div class="col-12 col-xl-5">
			<div class="card">
				<div class="card-header py-2">
					<h3 class="card-title mb-0">{{ isEdit ? t("Edit planned payment") : t("New planned payment") }}</h3>
					<span class="ms-auto text-secondary small">{{ formatDate(form.due_date) }}</span>
				</div>
				<div class="card-body">
					<div v-if="formError" class="alert alert-danger py-2 px-3">{{ formError }}</div>

					<label class="form-label">{{ t("What for") }}</label>
					<div class="d-flex flex-wrap gap-1 mb-3">
						<button
							v-for="kind in KIND_OPTIONS"
							:key="kind.value"
							type="button"
							class="btn btn-sm"
							:class="form.kind === kind.value ? 'btn-outline-primary active' : 'btn-outline-secondary'"
							@click="form.kind = kind.value"
						>
							<i class="ti" :class="kind.icon"></i>
							{{ kind.label() }}
						</button>
					</div>

					<div v-if="extraField === 'document'" class="mb-3">
						<label class="form-label">{{ t("Document") }}</label>
						<div class="row g-2">
							<div class="col-5">
								<select v-model="form.reference_doctype" class="form-select" @change="loadDocuments">
									<option value="">{{ t("None") }}</option>
									<option v-for="dt in documentTypes" :key="dt" :value="dt">{{ t(dt) }}</option>
								</select>
							</div>
							<div class="col-7">
								<select v-model="form.reference_name" class="form-select" @change="onDocumentPicked">
									<option value="">{{ t("Select") }}</option>
									<option v-for="doc in documentOptions" :key="doc.name" :value="doc.name">
										{{ doc.name }} — {{ formatMoney(doc.amount, doc.currency) }}
									</option>
								</select>
							</div>
						</div>
						<div class="form-hint">{{ t("The amount and date are read from the document.") }}</div>
					</div>

					<div v-else-if="extraField === 'account'" class="mb-3">
						<label class="form-label">{{ t("Expense account") }}</label>
						<select v-model="form.expense_account" class="form-select">
							<option value="">{{ t("None") }}</option>
							<option v-for="acc in accountOptions" :key="acc.name" :value="acc.name">
								{{ acc.account_number ? acc.account_number + " · " : "" }}{{ accountLabel(acc) }}
							</option>
						</select>
					</div>

					<div v-else-if="extraField === 'item'" class="mb-3">
						<label class="form-label">{{ t("Item") }}</label>
						<select v-model="form.item_code" class="form-select">
							<option value="">{{ t("None") }}</option>
							<option v-for="item in itemOptions" :key="item.name" :value="item.name">
								{{ item.item_name || item.name }}
							</option>
						</select>
					</div>

					<div class="row g-2 mb-3">
						<div class="col-7">
							<label class="form-label">{{ t("Amount") }}</label>
							<MoneyInput v-model="form.amount" :currency="form.currency" :language="language" hide-currency />
						</div>
						<div class="col-5">
							<label class="form-label">{{ t("Currency") }}</label>
							<input v-model="form.currency" class="form-control" />
						</div>
					</div>

					<div v-if="needsRate" class="mb-3">
						<label class="form-label">{{ t("Exchange rate") }}</label>
						<MoneyInput v-model="form.exchange_rate" :language="language" hide-currency />
						<div class="form-hint font-monospace">= {{ formatMoney(baseEquivalent, baseCurrency) }}</div>
					</div>

					<div class="row g-2 mb-3">
						<div class="col-6">
							<label class="form-label">{{ t("Due date") }}</label>
							<DateInput v-model="form.due_date" />
						</div>
						<div class="col-6">
							<label class="form-label">{{ t("Repeat") }}</label>
							<select
								class="form-select"
								:disabled="isEdit"
								@change="
									form.repeat = REPEAT_OPTIONS[$event.target.selectedIndex].value;
									form.repeat_count = REPEAT_OPTIONS[$event.target.selectedIndex].count;
								"
							>
								<option v-for="(opt, i) in REPEAT_OPTIONS" :key="i">{{ opt.label() }}</option>
							</select>
						</div>
					</div>

					<div class="mb-3">
						<label class="form-label">{{ t("Confidence") }}</label>
						<select v-model="form.confidence" class="form-select">
							<option v-for="opt in CONFIDENCE_OPTIONS" :key="opt.value" :value="opt.value">
								{{ opt.label() }}
							</option>
						</select>
						<div class="form-hint">
							{{ t("A tentative receipt does not pay a committed salary — the three are summed apart.") }}
						</div>
					</div>

					<div class="row g-2 mb-3">
						<div class="col-6">
							<label class="form-label">{{ t("Status") }}</label>
							<select v-model="form.status" class="form-select">
								<option value="Planned">{{ t("Planned") }}</option>
								<option value="Realized">{{ t("Realized") }}</option>
								<option value="Cancelled">{{ t("Cancelled") }}</option>
							</select>
						</div>
						<div v-if="form.status === 'Realized'" class="col-6">
							<label class="form-label">{{ t("Realized on") }}</label>
							<DateInput v-model="form.realized_on" />
						</div>
					</div>
					<div class="form-hint mb-3">
						{{ t("This screen does not pay anything. Money leaves through Payments, Kassa or Journal; a row is closed here by hand.") }}
					</div>

					<div class="mb-3">
						<label class="form-label">{{ t("Note") }}</label>
						<textarea v-model="form.note" class="form-control" rows="2"></textarea>
					</div>

					<div class="d-flex gap-2">
						<button
							v-if="isEdit"
							type="button"
							class="btn btn-outline-danger"
							:disabled="saving"
							@click="remove"
						>
							{{ t("Delete") }}
						</button>
						<button type="button" class="btn btn-ghost-secondary ms-auto" @click="form = blank()">
							{{ t("Cancel") }}
						</button>
						<button type="button" class="btn btn-primary" :disabled="saving" @click="save">
							{{ isEdit ? t("Save") : t("Add to plan") }}
						</button>
					</div>
				</div>
			</div>

			<div class="text-secondary small mt-2">
				{{ t("Direction") }}: <strong>{{ directionOf(form.kind) === "In" ? t("Incoming") : t("Outgoing") }}</strong>
				· {{ kindLabel(form.kind) }}
			</div>
		</div>
	</div>
</template>

<style scoped>
.legend-dot {
	display: inline-block;
	width: 10px;
	height: 10px;
	border-radius: 3px;
	margin-right: 4px;
}
.legend-dot--in {
	background: var(--tblr-teal, #0ca678);
}
.legend-dot--out {
	background: var(--tblr-orange, #f76707);
}
.legend-dot--done {
	background: var(--tblr-success, #2fb344);
}
</style>
