<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { call } from "../../api/client.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useSession } from "../../stores/session.js";
import EmptyState from "../../components/EmptyState.vue";
import Typeahead from "../../components/Typeahead.vue";

const session = useSession();
const loading = ref(false);
const error = ref("");
const visits = ref([]);
const meta = ref({ issue_types: [], service_people: [] });
const filters = ref({
	from_date: "",
	to_date: "",
	customer: "",
	service_person: "",
	issue_type: "",
	billing_status: "",
});
const customerDisplay = ref("");

const company = computed(() => session.activeCompany);

function statusLabel(docstatus) {
	if (Number(docstatus) === 1) return t("Submitted");
	if (Number(docstatus) === 2) return t("Cancelled");
	return t("Draft");
}

function statusClass(docstatus) {
	if (Number(docstatus) === 1) return "bg-green-lt";
	if (Number(docstatus) === 2) return "bg-danger-lt";
	return "bg-secondary-lt";
}

function billingLabel(visit) {
	if (visit.custom_sales_invoice) return visit.custom_sales_invoice;
	if (visit.custom_stock_entry) return visit.custom_stock_entry;
	return t("Unbilled");
}

function billingClass(visit) {
	if (visit.custom_sales_invoice) return "bg-blue-lt";
	if (visit.custom_stock_entry) return "bg-purple-lt";
	return "bg-warning-lt";
}

async function searchCustomers(search) {
	return call("stabler.api.sales.list_customers", {
		company: company.value,
		search,
		limit: 20,
	});
}

function pickCustomer(customer) {
	filters.value.customer = customer.name;
	customerDisplay.value = customer.customer_name ? `${customer.customer_name} · ${customer.name}` : customer.name;
	loadVisits();
}

function clearCustomer() {
	filters.value.customer = "";
	customerDisplay.value = "";
	loadVisits();
}

async function loadMeta() {
	if (!company.value) return;
	meta.value = await call("stabler.api.service.ticket_board_meta", { company: company.value });
}

async function loadVisits() {
	if (!company.value) return;
	loading.value = true;
	error.value = "";
	try {
		visits.value = await call("stabler.api.service.list_visits", {
			company: company.value,
			from_date: filters.value.from_date || undefined,
			to_date: filters.value.to_date || undefined,
			customer: filters.value.customer || undefined,
			service_person: filters.value.service_person || undefined,
			issue_type: filters.value.issue_type || undefined,
			billing_status: filters.value.billing_status || undefined,
			limit: 200,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load service visits.");
	} finally {
		loading.value = false;
	}
}

async function refreshAll() {
	await loadMeta();
	await loadVisits();
}

watch(company, refreshAll);
onMounted(refreshAll);
</script>

<template>
	<div class="card mb-3">
		<div class="card-body">
			<div class="row g-2 align-items-end">
				<div class="col-md-2">
					<label class="form-label">{{ t("From") }}</label>
					<input v-model="filters.from_date" type="date" class="form-control" @change="loadVisits" />
				</div>
				<div class="col-md-2">
					<label class="form-label">{{ t("To") }}</label>
					<input v-model="filters.to_date" type="date" class="form-control" @change="loadVisits" />
				</div>
				<div class="col-md-3">
					<label class="form-label">{{ t("Customer") }}</label>
					<Typeahead
						v-model="filters.customer"
						:display="customerDisplay"
						:search="searchCustomers"
						:placeholder="t('Search customer')"
						open-on-focus
						@pick="pickCustomer"
						@clear="clearCustomer"
					>
						<template #option="{ item }">
							<div class="fw-semibold">{{ item.customer_name || item.name }}</div>
							<div class="small text-secondary">{{ item.name }}</div>
						</template>
					</Typeahead>
				</div>
				<div class="col-md-2">
					<label class="form-label">{{ t("Service person") }}</label>
					<select v-model="filters.service_person" class="form-select" @change="loadVisits">
						<option value="">{{ t("All") }}</option>
						<option v-for="person in meta.service_people" :key="person.name" :value="person.name">
							{{ person.sales_person_name || person.name }}
						</option>
					</select>
				</div>
				<div class="col-md-2">
					<label class="form-label">{{ t("Billing") }}</label>
					<select v-model="filters.billing_status" class="form-select" @change="loadVisits">
						<option value="">{{ t("All") }}</option>
						<option value="open">{{ t("Draft") }}</option>
						<option value="unbilled">{{ t("Unbilled") }}</option>
						<option value="invoiced">{{ t("Invoiced") }}</option>
						<option value="stock_issued">{{ t("Stock issued") }}</option>
					</select>
				</div>
				<div class="col-md-1 d-flex justify-content-end">
					<button type="button" class="btn btn-outline-secondary" :disabled="loading" @click="refreshAll">
						<i class="ti ti-refresh"></i>
					</button>
				</div>
				<div class="col-md-3">
					<label class="form-label">{{ t("Issue type") }}</label>
					<select v-model="filters.issue_type" class="form-select" @change="loadVisits">
						<option value="">{{ t("All types") }}</option>
						<option v-for="kind in meta.issue_types" :key="kind" :value="kind">{{ kind }}</option>
					</select>
				</div>
			</div>
			<div v-if="error" class="alert alert-danger mt-3 mb-0">{{ error }}</div>
		</div>
	</div>

	<div v-if="loading" class="text-center py-5">
		<div class="spinner-border text-primary"></div>
	</div>
	<EmptyState v-else-if="!visits.length" icon="ti-clipboard-off" :title="t('No service visits')" />
	<div v-else class="table-responsive">
		<table class="table table-vcenter">
			<thead>
				<tr>
					<th>{{ t("Visit") }}</th>
					<th>{{ t("Date") }}</th>
					<th>{{ t("Customer") }}</th>
					<th>{{ t("Issue") }}</th>
					<th>{{ t("Service person") }}</th>
					<th>{{ t("Status") }}</th>
					<th>{{ t("Billing") }}</th>
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
						<div>{{ visit.subject || visit.custom_issue || "—" }}</div>
						<div class="small text-secondary">{{ visit.issue_type || "—" }}</div>
					</td>
					<td>{{ visit.service_people || "—" }}</td>
					<td>
						<span class="badge" :class="statusClass(visit.docstatus)">
							{{ statusLabel(visit.docstatus) }}
						</span>
					</td>
					<td>
						<span class="badge" :class="billingClass(visit)">
							{{ billingLabel(visit) }}
						</span>
					</td>
				</tr>
			</tbody>
		</table>
	</div>
</template>
