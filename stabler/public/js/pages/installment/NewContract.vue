<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { call } from "../../api/client.js";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, todayIso} from "../../composables/date.js";
import DateInput from "../../components/DateInput.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import Typeahead from "../../components/Typeahead.vue";

const router = useRouter();
const session = useSession();
const company = computed(() => session.activeCompany);

const side = ref("sell"); // "sell" | "buy"

const form = ref({
	party: null,
	partyLabel: "",
	car_item: null,
	carLabel: "",
	cost: null,
	markup: null,
	dp_percent: 20,
	term_months: 12,
	start_date: todayIso(),
	remarks: "",
});

const submitting = ref(false);
const submitError = ref("");

// ── Party search ──────────────────────────────────────────────────────────────
async function searchParty(q) {
	if (!company.value) return [];
	try {
		const sell = side.value === "sell";
		const doctype = sell ? "Customer" : "Supplier";
		const nameField = sell ? "customer_name" : "supplier_name";
		const rows = await call("frappe.client.get_list", {
			doctype,
			or_filters: q ? [["name", "like", `%${q}%`], [nameField, "like", `%${q}%`]] : undefined,
			fields: ["name", nameField],
			limit: 20,
			order_by: `${nameField} asc`,
		});
		return rows || [];
	} catch {
		return [];
	}
}

function onPartyPick(item) {
	form.value.party = item.name;
	form.value.partyLabel = item.customer_name || item.supplier_name || item.name;
}

function onPartyClear() {
	form.value.party = null;
	form.value.partyLabel = "";
}

// ── Car search ────────────────────────────────────────────────────────────────
async function searchCar(q) {
	if (!company.value) return [];
	try {
		const rows = await call("stabler.api.installment.list_cars", {
			company: company.value,
			search: q,
		});
		return rows || [];
	} catch {
		return [];
	}
}

const carStockHint = ref("");

function onCarPick(item) {
	form.value.car_item = item.name;
	form.value.carLabel = item.item_name || item.name;
	const qty = Number(item.actual_qty || 0);
	const val = Number(item.valuation_rate || 0);
	carStockHint.value =
		`${t("On hand")}: ${qty} ${item.stock_uom || ""}` +
		(val ? ` · ${t("valuation")} ${formatMoney(val, currency.value)}` : "");
	// Auto-fill cost from valuation when the field is still empty.
	if (val && (!form.value.cost || Number(form.value.cost) === 0)) form.value.cost = val;
}

function onCarClear() {
	form.value.car_item = null;
	form.value.carLabel = "";
	carStockHint.value = "";
}

// ── Quick-add a new stock item ───────────────────────────────────────────────
const quickAdd = ref({ open: false, item_name: "", opening_qty: null, rate: null, saving: false, error: "" });
function openQuickAdd() {
	quickAdd.value = { open: true, item_name: "", opening_qty: null, rate: null, saving: false, error: "" };
}
async function submitQuickAdd() {
	const qa = quickAdd.value;
	if (!qa.item_name || !qa.item_name.trim()) { qa.error = t("Item name is required."); return; }
	qa.saving = true; qa.error = "";
	try {
		const res = await call("stabler.api.installment.quick_create_item", {
			company: company.value,
			item_name: qa.item_name.trim(),
			opening_qty: qa.opening_qty || 0,
			rate: qa.rate || 0,
		});
		onCarPick({
			name: res.name,
			item_name: res.item_name,
			actual_qty: res.actual_qty,
			valuation_rate: res.valuation_rate,
			stock_uom: res.stock_uom,
		});
		quickAdd.value.open = false;
	} catch (err) {
		qa.error = err?.message || t("Failed to create item.");
	} finally {
		qa.saving = false;
	}
}

// Reset party when side changes
watch(side, () => {
	form.value.party = null;
	form.value.partyLabel = "";
});

// ── Live preview (mirrors _build_schedule in installment.py) ─────────────────
const preview = computed(() => {
	const cost = parseFloat(form.value.cost) || 0;
	const markup = parseFloat(form.value.markup) || 0;
	const dp = parseFloat(form.value.dp_percent) || 0;
	const n = parseInt(form.value.term_months) || 0;
	if (cost <= 0 || n < 1) return null;

	const round2 = (x) => Math.round(x * 100) / 100;
	const total = round2(cost + markup);
	const downpay = round2(total * dp / 100);
	const financed = round2(total - downpay);
	const baseInst = round2(financed / n);

	// Build rows
	const rows = [];
	const start = form.value.start_date;
	rows.push({ due_date: start, payment_amount: downpay, description: t("Downpayment") });
	for (let i = 1; i <= n; i++) {
		const d = addMonths(start, i);
		rows.push({ due_date: d, payment_amount: baseInst, description: `${t("Installment")} ${i}/${n}` });
	}
	// Absorb residual in last row
	const currentSum = round2(rows.reduce((s, r) => s + r.payment_amount, 0));
	const residual = round2(total - currentSum);
	rows[rows.length - 1].payment_amount = round2(rows[rows.length - 1].payment_amount + residual);

	return { total, downpay, financed, baseInst, rows };
});

// TZ-safe month addition — compose as padded strings, never parse ISO
function addMonths(isoDate, n) {
	const [y, m, d] = isoDate.split("-").map(Number);
	let newM = m + n;
	let newY = y + Math.floor((newM - 1) / 12);
	newM = ((newM - 1) % 12) + 1;
	const pad = (x) => String(x).padStart(2, "0");
	return `${newY}-${pad(newM)}-${pad(d)}`;
}

const currency = computed(() => session.currency);

// ── Submit ────────────────────────────────────────────────────────────────────
async function submit() {
	submitError.value = "";
	if (!form.value.party) {
		submitError.value = side.value === "sell" ? t("Customer is required.") : t("Supplier is required.");
		return;
	}
	if (!form.value.car_item) {
		submitError.value = t("Car item is required.");
		return;
	}
	if (!form.value.cost || parseFloat(form.value.cost) <= 0) {
		submitError.value = t("Cost must be positive.");
		return;
	}
	submitting.value = true;
	try {
		const endpoint =
			side.value === "sell"
				? "stabler.api.installment.create_sell_contract"
				: "stabler.api.installment.create_buy_contract";
		const partyParam = side.value === "sell" ? { customer: form.value.party } : { supplier: form.value.party };
		await call(endpoint, {
			company: company.value,
			...partyParam,
			car_item: form.value.car_item,
			cost: form.value.cost,
			markup: form.value.markup || 0,
			dp_percent: form.value.dp_percent,
			term_months: form.value.term_months,
			start_date: form.value.start_date,
			remarks: form.value.remarks || null,
			submit: 0,
		});
		await router.push("/installment/contracts");
	} catch (err) {
		submitError.value = err?.message || t("Failed to create contract.");
	} finally {
		submitting.value = false;
	}
}
</script>

<template>
	<div class="row g-3">
		<!-- Form -->
		<div class="col-lg-6">
			<div class="card">
				<div class="card-header">
					<div class="card-title">{{ t("New Murabaha Contract") }}</div>
					<!-- Sell / Buy segmented control -->
					<div class="ms-auto btn-group" role="group">
						<input id="side-sell" v-model="side" type="radio" class="btn-check" value="sell" />
						<label class="btn btn-outline-primary btn-sm" for="side-sell">
							<i class="ti ti-trending-up me-1"></i>{{ t("Sell") }}
						</label>
						<input id="side-buy" v-model="side" type="radio" class="btn-check" value="buy" />
						<label class="btn btn-outline-primary btn-sm" for="side-buy">
							<i class="ti ti-shopping-cart me-1"></i>{{ t("Buy") }}
						</label>
					</div>
				</div>
				<div class="card-body">
					<div v-if="submitError" class="alert alert-danger mb-3">{{ submitError }}</div>

					<div class="row g-3">
						<!-- Party -->
						<div class="col-12">
							<label class="form-label">
								{{ side === "sell" ? t("Customer") : t("Supplier") }}
							</label>
							<Typeahead
								v-model="form.party"
								:search="searchParty"
								:display="form.partyLabel"
								:open-on-focus="true"
								:placeholder="side === 'sell' ? t('Search customers…') : t('Search suppliers…')"
								@pick="onPartyPick"
								@clear="onPartyClear"
							>
								<template #option="{ item }">
									<div class="fw-semibold small">{{ item.customer_name || item.supplier_name || item.name }}</div>
									<div v-if="item.customer_name || item.supplier_name" class="text-secondary" style="font-size:.75rem">{{ item.name }}</div>
								</template>
							</Typeahead>
						</div>

						<!-- Car item -->
						<div class="col-12">
							<label class="form-label d-flex align-items-center">
								{{ t("Item") }}
								<button type="button" class="btn btn-ghost-primary btn-sm ms-auto py-0" @click="openQuickAdd">
									<i class="ti ti-plus me-1"></i>{{ t("Add to stock") }}
								</button>
							</label>
							<Typeahead
								v-model="form.car_item"
								:search="searchCar"
								:display="form.carLabel"
								:open-on-focus="true"
								:placeholder="t('Search stock items…')"
								@pick="onCarPick"
								@clear="onCarClear"
							>
								<template #option="{ item }">
									<div class="d-flex justify-content-between align-items-center">
										<div>
											<div class="fw-semibold small">{{ item.item_name || item.name }}</div>
											<div class="text-secondary" style="font-size:.75rem">{{ item.name }}</div>
										</div>
										<span
											class="badge ms-2"
											:class="Number(item.actual_qty) > 0 ? 'bg-green-lt' : 'bg-secondary-lt'"
										>{{ t("Stock") }}: {{ Number(item.actual_qty || 0) }} {{ item.stock_uom || "" }}</span>
									</div>
								</template>
							</Typeahead>
							<div v-if="form.car_item && carStockHint" class="form-hint mt-1">
								<i class="ti ti-package me-1"></i>{{ carStockHint }}
							</div>
						</div>

						<!-- Cost + Markup -->
						<div class="col-md-6">
							<label class="form-label">{{ t("Cost") }}</label>
							<MoneyInput v-model="form.cost" :currency="currency" />
						</div>
						<div class="col-md-6">
							<label class="form-label">
								{{ side === "sell" ? t("Sell markup") : t("Buy markup") }}
							</label>
							<MoneyInput v-model="form.markup" :currency="currency" />
						</div>

						<!-- DP % + Term -->
						<div class="col-md-6">
							<label class="form-label">{{ t("Downpayment %") }}</label>
							<input
								v-model.number="form.dp_percent"
								type="number"
								min="0"
								max="100"
								step="1"
								class="form-control"
							/>
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Term (months)") }}</label>
							<input
								v-model.number="form.term_months"
								type="number"
								min="1"
								max="360"
								step="1"
								class="form-control"
							/>
						</div>

						<!-- Start date -->
						<div class="col-md-6">
							<label class="form-label">{{ t("First payment date") }}</label>
							<DateInput v-model="form.start_date" />
						</div>

						<!-- Remarks -->
						<div class="col-12">
							<label class="form-label">{{ t("Remarks") }}</label>
							<input v-model="form.remarks" type="text" class="form-control" />
						</div>
					</div>

					<div class="mt-4 d-flex justify-content-end">
						<button
							type="button"
							class="btn btn-primary"
							:disabled="submitting"
							@click="submit"
						>
							<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
							<i v-else class="ti ti-check me-1"></i>{{ t("Create contract") }}
						</button>
					</div>
				</div>
			</div>
		</div>

		<!-- Quick-add item to stock -->
		<div v-if="quickAdd.open" class="offcanvas-backdrop fade show" @click="quickAdd.open = false"></div>
		<div v-if="quickAdd.open" class="offcanvas offcanvas-end show" tabindex="-1" style="visibility: visible; width: 440px">
			<div class="offcanvas-header">
				<h5 class="offcanvas-title"><i class="ti ti-package me-1"></i>{{ t("Add item to stock") }}</h5>
				<button type="button" class="btn-close" @click="quickAdd.open = false"></button>
			</div>
			<div class="offcanvas-body">
				<div v-if="quickAdd.error" class="alert alert-danger">{{ quickAdd.error }}</div>
				<div class="mb-3">
					<label class="form-label">{{ t("Item name") }}</label>
					<input v-model="quickAdd.item_name" type="text" class="form-control" :placeholder="t('e.g. Chevrolet Cobalt 2024')" />
				</div>
				<div class="row g-3">
					<div class="col-6">
						<label class="form-label">{{ t("Opening qty") }}</label>
						<input v-model.number="quickAdd.opening_qty" type="number" min="0" step="any" class="form-control font-monospace text-end" />
					</div>
					<div class="col-6">
						<label class="form-label">{{ t("Unit cost") }}</label>
						<MoneyInput v-model="quickAdd.rate" :currency="currency" />
					</div>
				</div>
				<p class="form-hint mt-2">{{ t("Creates a stock item; if qty and cost are given, an opening stock receipt is posted.") }}</p>
				<div class="d-flex justify-content-end gap-2 mt-3">
					<button type="button" class="btn btn-outline-secondary" @click="quickAdd.open = false">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary" :disabled="quickAdd.saving" @click="submitQuickAdd">
						<span v-if="quickAdd.saving" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-check me-1"></i>{{ t("Create & select") }}
					</button>
				</div>
			</div>
		</div>

		<!-- Live preview -->
		<div class="col-lg-6">
			<div class="card">
				<div class="card-header">
					<div class="card-title">{{ t("Schedule preview") }}</div>
				</div>
				<div class="card-body p-0">
					<div v-if="!preview" class="p-4 text-secondary small">
						{{ t("Enter cost and term to see the payment schedule.") }}
					</div>
					<template v-else>
						<!-- Summary -->
						<div class="p-3 border-bottom">
							<dl class="row mb-0 g-1">
								<dt class="col-7 text-secondary">{{ t("Total (cost + markup)") }}</dt>
								<dd class="col-5 text-end font-monospace fw-semibold">
									{{ formatMoney(preview.total, currency) }}
								</dd>
								<dt class="col-7 text-secondary">{{ t("Downpayment") }}</dt>
								<dd class="col-5 text-end font-monospace">
									{{ formatMoney(preview.downpay, currency) }}
								</dd>
								<dt class="col-7 text-secondary">{{ t("Financed") }}</dt>
								<dd class="col-5 text-end font-monospace">
									{{ formatMoney(preview.financed, currency) }}
								</dd>
								<dt class="col-7 text-secondary">{{ t("Monthly installment") }}</dt>
								<dd class="col-5 text-end font-monospace text-primary fw-semibold">
									{{ formatMoney(preview.baseInst, currency) }}
								</dd>
							</dl>
						</div>
						<!-- Schedule rows -->
						<div style="max-height: 320px; overflow: auto">
							<table class="table table-sm table-vcenter mb-0">
								<thead>
									<tr>
										<th>#</th>
										<th>{{ t("Due date") }}</th>
										<th class="text-end">{{ t("Amount") }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="(row, idx) in preview.rows" :key="idx">
										<td class="text-secondary small">{{ idx }}</td>
										<td>{{ formatDate(row.due_date) }}</td>
										<td class="text-end font-monospace">
											{{ formatMoney(row.payment_amount, currency) }}
										</td>
									</tr>
								</tbody>
							</table>
						</div>
						<div class="p-2 border-top text-secondary small">
							{{ t("No interest — fixed Murabaha markup. Sum equals total exactly.") }}
						</div>
					</template>
				</div>
			</div>
		</div>
	</div>
</template>
