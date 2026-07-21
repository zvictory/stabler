<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import DateInput from "../../components/DateInput.vue";
import Typeahead from "../../components/Typeahead.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();

const loading = ref(false);
const error = ref("");
const startDate = ref("");
const endDate = ref("");
const customer = ref("");
const customerName = ref("");
const product = ref("");
const productName = ref("");
const currency = ref("");
const status = ref("");

const rows = ref([]);
const totals = ref({});

const fn = (v) => {
	if (v === null || v === undefined || isNaN(v)) return "0.00";
	const localeCode = user.value?.language === "en" ? "en-US" : "ru-RU";
	return new Intl.NumberFormat(localeCode, {
		minimumFractionDigits: 2,
		maximumFractionDigits: 2,
		useGrouping: true,
	}).format(Number(v) || 0);
};

const fm = (v, ccy) => formatMoney(v, ccy || "UZS", user.value?.language || "en");

async function searchCustomers(q) {
	return call("stabler.api.sales.list_customers", { company: activeCompany.value, search: q || "", limit: 20 });
}
function pickCustomer(c) {
	customer.value = c.name;
	customerName.value = c.customer_name || c.name;
	loadReport();
}

async function searchItems(q) {
	return call("stabler.api.inventory.list_items", { search: q || "", limit: 20 });
}
function pickItem(i) {
	product.value = i.item_code || i.name;
	productName.value = i.item_name || i.name;
	loadReport();
}

async function loadReport() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const res = await call("stabler.api.reports.get_sales_detail_report", {
			company: activeCompany.value,
			start_date: startDate.value || undefined,
			end_date: endDate.value || undefined,
			customer: customer.value || undefined,
			product: product.value || undefined,
			currency: currency.value || undefined,
			status: status.value || undefined,
		});
		rows.value = res.rows || [];
		totals.value = res.totals || {};
	} catch (err) {
		error.value = err?.message || t("Failed to load sales detail report.");
	} finally {
		loading.value = false;
	}
}

function exportCsv() {
	if (!rows.value.length) return;
	const headers = [
		"Posting Date", "Invoice Number", "Customer", "Parent Customer",
		"Item Code", "Item Name", "Boxes", "Box Weight (kg)", "Total KG", "Unit Price", "Amount", "Currency"
	];
	const csvRows = [headers.join(",")];
	for (const r of rows.value) {
		csvRows.push([
			`"${r.posting_date || ""}"`,
			`"${r.invoice_number}"`,
			`"${r.customer_name || r.customer}"`,
			`"${r.parent_customer || ""}"`,
			`"${r.item_code}"`,
			`"${r.item_name}"`,
			r.boxes,
			r.box_kg,
			r.total_kg,
			r.rate,
			r.amount,
			`"${r.currency}"`,
		].join(","));
	}
	const blob = new Blob([csvRows.join("\n")], { type: "text/csv;charset=utf-8;" });
	const url = URL.createObjectURL(blob);
	const link = document.createElement("a");
	link.setAttribute("href", url);
	link.setAttribute("download", `sales_detail_report_${new Date().toISOString().slice(0, 10)}.csv`);
	document.body.appendChild(link);
	link.click();
	document.body.removeChild(link);
}

onMounted(loadReport);
watch(activeCompany, loadReport);
</script>

<template>
	<div>
		<!-- Header -->
		<div class="d-flex align-items-center mb-3">
			<button type="button" class="btn btn-outline-secondary btn-icon me-3" @click="router.push('/reports')">
				<i class="ti ti-arrow-left"></i>
			</button>
			<div>
				<h2 class="page-title mb-0">{{ t("Sales Detail Report") }}</h2>
				<div class="text-secondary small">{{ t("Line item breakdown of all sales invoices with boxes, weight, and pricing") }}</div>
			</div>
			<div class="ms-auto d-flex gap-2">
				<button type="button" class="btn btn-outline-secondary btn-sm" :disabled="loading || !rows.length" @click="exportCsv">
					<i class="ti ti-file-spreadsheet me-1"></i>{{ t("Export CSV") }}
				</button>
				<button type="button" class="btn btn-primary btn-sm" :disabled="loading" @click="loadReport">
					<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
				</button>
			</div>
		</div>

		<!-- Filter Bar -->
		<div class="card mb-3">
			<div class="card-body py-2">
				<div class="row g-2 align-items-center">
					<div class="col-md-3">
						<DateInput v-model="startDate" :placeholder="t('Start Date')" size="sm" />
					</div>
					<div class="col-md-3">
						<DateInput v-model="endDate" :placeholder="t('End Date')" size="sm" />
					</div>
					<div class="col-md-3">
						<Typeahead
							v-slot="{ item }"
							v-model="customer"
							:search="searchCustomers"
							:display="customerName"
							:placeholder="t('All customers…')"
							size="sm"
							@pick="pickCustomer"
						>
							<div class="fw-semibold small">{{ item.customer_name || item.name }}</div>
						</Typeahead>
					</div>
					<div class="col-md-3">
						<Typeahead
							v-slot="{ item }"
							v-model="product"
							:search="searchItems"
							:display="productName"
							:placeholder="t('All products…')"
							size="sm"
							@pick="pickItem"
						>
							<div class="fw-semibold small">{{ item.item_name || item.name }}</div>
						</Typeahead>
					</div>
				</div>
			</div>
		</div>

		<div v-if="error" class="alert alert-danger">{{ error }}</div>

		<!-- KPI Metric Strip -->
		<div class="row row-cards mb-3">
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Total Sales Amount") }}</div>
						<div class="h3 mb-0 font-monospace text-primary fw-bold">{{ fm(totals.total_sales) }}</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Total Weight (KG)") }}</div>
						<div class="h3 mb-0 font-monospace text-azure fw-bold">{{ fn(totals.total_kg) }} kg</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Total Boxes") }}</div>
						<div class="h3 mb-0 font-monospace text-orange fw-bold">{{ fn(totals.total_boxes) }} bx</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Line Items / Invoices") }}</div>
						<div class="h3 mb-0 font-monospace text-dark fw-bold">{{ totals.row_count || 0 }}</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Data Table -->
		<div class="card mb-3">
			<div class="table-responsive" style="max-height: 620px; overflow-y: auto;">
				<table class="table table-sm table-hover align-middle mb-0">
					<thead style="position: sticky; top: 0; z-index: 1">
						<tr>
							<th>{{ t("Date") }}</th>
							<th>{{ t("Invoice #") }}</th>
							<th>{{ t("Customer") }}</th>
							<th>{{ t("Parent Customer") }}</th>
							<th>{{ t("Item Code") }}</th>
							<th>{{ t("Item Name") }}</th>
							<th class="text-end bg-orange-lt text-orange">{{ t("Boxes") }}</th>
							<th class="text-end bg-orange-lt text-orange">{{ t("Box Weight") }}</th>
							<th class="text-end bg-orange-lt text-orange">{{ t("Total KG") }}</th>
							<th class="text-end bg-blue-lt text-blue">{{ t("Unit Price") }}</th>
							<th class="text-end bg-blue-lt text-blue">{{ t("Amount") }}</th>
							<th>{{ t("Currency") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="(r, idx) in rows" :key="idx" style="cursor: pointer" @click="router.push('/sales/invoices/' + r.invoice_number)">
							<td class="small text-nowrap">{{ formatDate(r.posting_date) }}</td>
							<td class="font-monospace fw-bold text-primary">{{ r.invoice_number }}</td>
							<td class="fw-semibold text-dark">{{ r.customer_name }}</td>
							<td>
								<span v-if="r.parent_customer" class="badge bg-secondary-lt">{{ r.parent_customer }}</span>
								<span v-else class="text-secondary">—</span>
							</td>
							<td class="font-monospace text-secondary" style="font-size: 11px;">{{ r.item_code }}</td>
							<td class="fw-semibold text-dark">{{ r.item_name }}</td>
							<td class="text-end font-monospace text-orange bg-orange-lt">{{ fn(r.boxes) }}</td>
							<td class="text-end font-monospace text-orange bg-orange-lt">{{ fn(r.box_kg) }} kg</td>
							<td class="text-end font-monospace text-orange bg-orange-lt fw-semibold">{{ fn(r.total_kg) }} kg</td>
							<td class="text-end font-monospace text-blue bg-blue-lt">{{ fn(r.rate) }}</td>
							<td class="text-end font-monospace text-blue bg-blue-lt fw-bold">{{ fn(r.amount) }}</td>
							<td class="font-monospace small"><span class="badge bg-secondary-lt">{{ r.currency }}</span></td>
						</tr>
						<tr v-if="!rows.length && !loading">
							<td colspan="12" class="text-center text-secondary py-4">{{ t("No sales detail records found.") }}</td>
						</tr>
					</tbody>
					<tfoot v-if="rows.length">
						<tr class="fw-bold bg-light">
							<td colspan="6" class="text-end">{{ t("Grand Totals") }} ({{ totals.row_count }} items)</td>
							<td class="text-end font-monospace text-orange bg-orange-lt">{{ fn(totals.total_boxes) }}</td>
							<td class="text-end font-monospace text-orange bg-orange-lt">—</td>
							<td class="text-end font-monospace text-orange bg-orange-lt">{{ fn(totals.total_kg) }} kg</td>
							<td class="text-end font-monospace text-blue bg-blue-lt">—</td>
							<td class="text-end font-monospace text-blue bg-blue-lt">{{ fm(totals.total_sales) }}</td>
							<td></td>
						</tr>
					</tfoot>
				</table>
			</div>
		</div>
	</div>
</template>
