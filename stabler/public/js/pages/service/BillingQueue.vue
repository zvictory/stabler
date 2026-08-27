<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { call } from "../../api/client.js";
import { formatDate, todayIso} from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";
import { useSession } from "../../stores/session.js";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import Typeahead from "../../components/Typeahead.vue";
import { useBackdateGuard } from "../../composables/backdate.js";

const { canBackdate, minPostingDate } = useBackdateGuard();

const session = useSession();
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const actionError = ref("");
const success = ref("");
const visits = ref([]);
const warehouses = ref([]);
const selected = ref(null);
const action = ref("invoice");
const form = ref({
	posting_date: todayIso(),
	warehouse: "",
	items: [],
});

const company = computed(() => session.activeCompany);
const currency = computed(() => session.currency || "USD");
const user = computed(() => session.user || { language: "en" });
const actionTitle = computed(() => (action.value === "invoice" ? t("Create Sales Invoice") : t("Create Material Issue")));
const total = computed(() =>
	form.value.items.reduce((sum, line) => sum + Number(line.qty || 0) * Number(line.rate || 0), 0)
);

function blankLine() {
	return {
		item_code: "",
		item_name: "",
		qty: 1,
		uom: "",
		rate: 0,
		warehouse: "",
	};
}

async function loadVisits() {
	if (!company.value) return;
	loading.value = true;
	error.value = "";
	try {
		visits.value = await call("stabler.api.service.unbilled_visits", {
			company: company.value,
			limit: 200,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load unbilled visits.");
	} finally {
		loading.value = false;
	}
}

async function loadWarehouses() {
	if (!company.value) return;
	try {
		warehouses.value = await call("stabler.api.inventory.list_stock_warehouses", { company: company.value });
		if (!form.value.warehouse) form.value.warehouse = warehouses.value[0]?.name || "";
	} catch {
		warehouses.value = [];
	}
}

async function refreshAll() {
	await Promise.all([loadVisits(), loadWarehouses()]);
}

function openAction(visit, nextAction) {
	selected.value = visit;
	action.value = nextAction;
	actionError.value = "";
	success.value = "";
	form.value = {
		posting_date: todayIso(),
		warehouse: form.value.warehouse || warehouses.value[0]?.name || "",
		items: [blankLine()],
	};
}

function closeAction() {
	if (saving.value) return;
	selected.value = null;
	actionError.value = "";
}

async function searchItems(search) {
	return call("stabler.api.inventory.list_items", {
		search,
		limit: 10,
	});
}

function pickItem(line, item) {
	line.item_code = item.item_code || item.name;
	line.item_name = item.item_name || line.item_code;
	line.uom = item.stock_uom || "";
	line.rate = Number(action.value === "invoice" ? item.standard_rate || 0 : item.valuation_rate || item.standard_rate || 0);
	if (!line.warehouse) line.warehouse = form.value.warehouse;
}

function clearItem(line) {
	line.item_code = "";
	line.item_name = "";
	line.uom = "";
	line.rate = 0;
}

function addLine() {
	form.value.items.push(blankLine());
}

function removeLine(index) {
	if (form.value.items.length === 1) {
		form.value.items = [blankLine()];
		return;
	}
	form.value.items.splice(index, 1);
}

function normalizedItems() {
	return form.value.items
		.filter((line) => line.item_code && Number(line.qty || 0) > 0)
		.map((line) => {
			const base = {
				item_code: line.item_code,
				qty: Number(line.qty || 0),
				uom: line.uom || undefined,
				warehouse: line.warehouse || undefined,
			};
			return action.value === "invoice"
				? { ...base, rate: Number(line.rate || 0) }
				: { ...base, basic_rate: Number(line.rate || 0) };
		});
}

async function submitAction() {
	if (!selected.value) return;
	const items = normalizedItems();
	if (!items.length) {
		actionError.value = t("Add at least one item with a positive quantity.");
		return;
	}
	if (action.value === "stock_issue" && !form.value.warehouse) {
		actionError.value = t("Select a source warehouse.");
		return;
	}
	saving.value = true;
	actionError.value = "";
	success.value = "";
	try {
		const method =
			action.value === "invoice"
				? "stabler.api.service.create_invoice_from_visit"
				: "stabler.api.service.create_material_issue_from_visit";
		const args =
			action.value === "invoice"
				? {
						visit: selected.value.name,
						posting_date: form.value.posting_date,
						items,
						submit: 0,
					}
				: {
						visit: selected.value.name,
						posting_date: form.value.posting_date,
						warehouse: form.value.warehouse,
						items,
						submit: 1,
					};
		const created = await call(method, args);
		success.value =
			action.value === "invoice"
				? t("Draft Sales Invoice created: {0}").replace("{0}", created.name)
				: t("Material Issue submitted: {0}").replace("{0}", created.name);
		selected.value = null;
		await loadVisits();
	} catch (err) {
		actionError.value = err?.message || t("Failed to create billing document.");
	} finally {
		saving.value = false;
	}
}

watch(company, refreshAll);
onMounted(refreshAll);
</script>

<template>
	<div class="d-flex align-items-center justify-content-between mb-3">
		<div>
			<h2 class="page-title mb-1">{{ t("Service Billing") }}</h2>
			<div class="text-secondary">{{ t("Submitted visits waiting for invoice or parts issue.") }}</div>
		</div>
		<button type="button" class="btn btn-outline-secondary" :disabled="loading" @click="refreshAll">
			<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
		</button>
	</div>

	<div v-if="error" class="alert alert-danger">{{ error }}</div>
	<div v-if="success" class="alert alert-success">{{ success }}</div>

	<div v-if="loading" class="text-center py-5">
		<div class="spinner-border text-primary"></div>
	</div>
	<EmptyState v-else-if="!visits.length" icon="ti-receipt-off" :title="t('No unbilled service visits')" />
	<div v-else class="table-responsive">
		<table class="table table-vcenter">
			<thead>
				<tr>
					<th>{{ t("Visit") }}</th>
					<th>{{ t("Date") }}</th>
					<th>{{ t("Customer") }}</th>
					<th>{{ t("Issue") }}</th>
					<th>{{ t("Completion") }}</th>
					<th class="text-end">{{ t("Action") }}</th>
				</tr>
			</thead>
			<tbody>
				<tr v-for="visit in visits" :key="visit.name">
					<td class="font-monospace">{{ visit.name }}</td>
					<td>{{ visit.mntc_date ? formatDate(visit.mntc_date) : "—" }}</td>
					<td>
						<div class="fw-semibold">{{ visit.customer_name || visit.customer }}</div>
						<div class="small text-secondary font-monospace">{{ visit.customer }}</div>
					</td>
					<td>
						<div>{{ visit.subject || visit.custom_issue }}</div>
						<div class="small text-secondary">{{ visit.issue_type || "—" }}</div>
					</td>
					<td>{{ visit.completion_status || "—" }}</td>
					<td class="text-end">
						<div class="btn-list justify-content-end">
							<button type="button" class="btn btn-sm btn-primary" @click="openAction(visit, 'invoice')">
								<i class="ti ti-file-invoice me-1"></i>{{ t("Invoice") }}
							</button>
							<button type="button" class="btn btn-sm btn-outline-secondary" @click="openAction(visit, 'stock_issue')">
								<i class="ti ti-package-export me-1"></i>{{ t("Parts Issue") }}
							</button>
						</div>
					</td>
				</tr>
			</tbody>
		</table>
	</div>

	<div v-if="selected" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="closeAction">
		<div class="modal-dialog modal-xl modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<div>
						<h5 class="modal-title">{{ actionTitle }}</h5>
						<div class="small text-secondary">{{ selected.name }} · {{ selected.customer_name || selected.customer }}</div>
					</div>
					<button type="button" class="btn-close" :disabled="saving" @click="closeAction"></button>
				</div>
				<div class="modal-body">
					<div v-if="actionError" class="alert alert-danger">{{ actionError }}</div>
					<div class="row g-3 mb-3">
						<div class="col-md-3">
							<label class="form-label">{{ t("Posting date") }}</label>
							<DateInput v-model="form.posting_date" :disabled="saving" :min="minPostingDate" />
							<div v-if="!canBackdate" class="form-hint">
								{{ t("Only an administrator can post to an earlier date.") }}
							</div>
						</div>
						<div v-if="action === 'stock_issue'" class="col-md-5">
							<label class="form-label required">{{ t("Source warehouse") }}</label>
							<select v-model="form.warehouse" class="form-select" :disabled="saving" required>
								<option value="">{{ t("Select warehouse") }}</option>
								<option v-for="warehouse in warehouses" :key="warehouse.name" :value="warehouse.name">
									{{ warehouse.warehouse_name || warehouse.name }}
								</option>
							</select>
						</div>
						<div class="col-md-4 ms-auto text-md-end">
							<label class="form-label">{{ t("Current total") }}</label>
							<div class="h3 mb-0 font-monospace">{{ formatMoney(total, currency, user.language) }}</div>
						</div>
					</div>

					<div class="table-responsive">
						<table class="table table-sm table-vcenter">
							<thead>
								<tr>
									<th style="min-width: 260px">{{ t("Item") }}</th>
									<th style="width: 110px">{{ t("Qty") }}</th>
									<th style="width: 90px">{{ t("UOM") }}</th>
									<th style="min-width: 180px">{{ action === "invoice" ? t("Rate") : t("Basic rate") }}</th>
									<th style="min-width: 220px">{{ t("Warehouse") }}</th>
									<th class="text-end" style="width: 140px">{{ t("Amount") }}</th>
									<th style="width: 44px"></th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="(line, index) in form.items" :key="index">
									<td>
										<Typeahead
											:model-value="line.item_code"
											:search="searchItems"
											:display="line.item_name || line.item_code"
											:placeholder="t('Search item...')"
											:no-results-text="t('No items match')"
											size="sm"
											menu-min-width="280px"
											:disabled="saving"
											@pick="(item) => pickItem(line, item)"
											@clear="clearItem(line)"
										>
											<template #option="{ item }">
												<div class="fw-semibold small">{{ item.item_name || item.name }}</div>
												<div class="small text-secondary font-monospace">
													{{ item.item_code || item.name }} · {{ item.stock_uom || "—" }}
												</div>
											</template>
										</Typeahead>
									</td>
									<td>
										<input
											v-model.number="line.qty"
											type="number"
											step="any"
											inputmode="decimal"
											class="form-control form-control-sm font-monospace text-end"
											:disabled="saving"
										/>
									</td>
									<td><input v-model.trim="line.uom" class="form-control form-control-sm" :disabled="saving" /></td>
									<td>
										<MoneyInput v-model="line.rate" :currency="currency" :language="user.language" size="sm" :disabled="saving" />
									</td>
									<td>
										<select v-model="line.warehouse" class="form-select form-select-sm" :disabled="saving">
											<option value="">{{ action === "invoice" ? t("No stock update") : t("Use source warehouse") }}</option>
											<option v-for="warehouse in warehouses" :key="warehouse.name" :value="warehouse.name">
												{{ warehouse.warehouse_name || warehouse.name }}
											</option>
										</select>
									</td>
									<td class="text-end font-monospace">
										{{ formatMoney(Number(line.qty || 0) * Number(line.rate || 0), currency, user.language) }}
									</td>
									<td>
										<button type="button" class="btn btn-icon btn-sm btn-ghost-danger" :disabled="saving" @click="removeLine(index)">
											<i class="ti ti-trash"></i>
										</button>
									</td>
								</tr>
							</tbody>
						</table>
					</div>
					<button type="button" class="btn btn-outline-primary" :disabled="saving" @click="addLine">
						<i class="ti ti-plus me-1"></i>{{ t("Add item") }}
					</button>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-outline-secondary" :disabled="saving" @click="closeAction">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary" :disabled="saving" @click="submitAction">
						<span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
						{{ actionTitle }}
					</button>
				</div>
			</div>
		</div>
	</div>
	<div v-if="selected" class="modal-backdrop fade show"></div>
</template>
