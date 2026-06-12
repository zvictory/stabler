<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { call } from "../../api/client.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useSession } from "../../stores/session.js";
import CalendarMonth from "../../components/CalendarMonth.vue";
import Typeahead from "../../components/Typeahead.vue";

const session = useSession();
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const events = ref([]);
const meta = ref({ service_people: [] });
const customerDisplay = ref("");
const filters = ref({
	service_person: "",
	customer: "",
});
const detail = ref(null);
const rescheduleDate = ref("");
const actionError = ref("");

const company = computed(() => session.activeCompany);
const language = computed(() => session.user?.language || "en");

function currentMonthKey() {
	const now = new Date();
	return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

const month = ref(currentMonthKey());

const serviceEvents = computed(() =>
	events.value.map((event) => ({
		...event,
		showAmount: false,
	}))
);

const selectedDayEvents = computed(() => {
	if (!detail.value) return [];
	return serviceEvents.value.filter((event) => event.date === detail.value.date);
});

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
	loadEvents();
}

function clearCustomer() {
	filters.value.customer = "";
	customerDisplay.value = "";
	loadEvents();
}

async function loadMeta() {
	if (!company.value) return;
	meta.value = await call("stabler.api.service.ticket_board_meta", { company: company.value });
}

async function loadEvents() {
	if (!company.value) return;
	loading.value = true;
	error.value = "";
	try {
		events.value = await call("stabler.api.service.calendar_feed", {
			company: company.value,
			month: month.value,
			service_person: filters.value.service_person || undefined,
			customer: filters.value.customer || undefined,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load service calendar.");
	} finally {
		loading.value = false;
	}
}

async function refreshAll() {
	await loadMeta();
	await loadEvents();
}

function openDetail(event) {
	detail.value = event;
	rescheduleDate.value = event.date;
	actionError.value = "";
}

function closeDetail() {
	if (saving.value) return;
	detail.value = null;
	actionError.value = "";
}

async function reschedule() {
	if (!detail.value || detail.value.kind !== "planned") return;
	saving.value = true;
	actionError.value = "";
	try {
		await call("stabler.api.service.reschedule_detail", {
			name: detail.value.contractId,
			date: rescheduleDate.value,
		});
		await loadEvents();
		detail.value = null;
	} catch (err) {
		actionError.value = err?.message || t("Failed to reschedule visit.");
	} finally {
		saving.value = false;
	}
}

watch(month, loadEvents);
watch(company, refreshAll);
onMounted(refreshAll);
</script>

<template>
	<div class="card mb-3">
		<div class="card-body">
			<div class="row g-2 align-items-end">
				<div class="col-md-4">
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
				<div class="col-md-4">
					<label class="form-label">{{ t("Service person") }}</label>
					<select v-model="filters.service_person" class="form-select" @change="loadEvents">
						<option value="">{{ t("All service people") }}</option>
						<option v-for="person in meta.service_people" :key="person.name" :value="person.name">
							{{ person.sales_person_name || person.name }}
						</option>
					</select>
				</div>
				<div class="col-md-4 d-flex justify-content-md-end">
					<button type="button" class="btn btn-outline-secondary" :disabled="loading" @click="refreshAll">
						<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
					</button>
				</div>
			</div>
			<div v-if="error" class="alert alert-danger mt-3 mb-0">{{ error }}</div>
		</div>
	</div>

	<div v-if="loading" class="text-center py-5">
		<div class="spinner-border text-primary"></div>
	</div>
	<div v-else class="card">
		<div class="card-body p-2">
			<CalendarMonth
				:month="month"
				:events="serviceEvents"
				:currency="session.currency"
				:language="language"
				@update:month="(nextMonth) => (month = nextMonth)"
				@select="openDetail"
			/>
		</div>
	</div>

	<div v-if="detail" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div v-if="detail" class="offcanvas offcanvas-end show" tabindex="-1" style="visibility: visible; width: 560px">
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">
				<i class="ti ti-calendar-event me-1"></i>{{ detail.kind === "planned" ? t("Planned service") : t("Completed visit") }}
			</h5>
			<button type="button" class="btn-close" @click="closeDetail"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="actionError" class="alert alert-danger">{{ actionError }}</div>
			<dl class="row mb-3">
				<dt class="col-5 text-secondary">{{ t("Date") }}</dt>
				<dd class="col-7">{{ formatDate(detail.date) }}</dd>
				<dt class="col-5 text-secondary">{{ t("Customer") }}</dt>
				<dd class="col-7">{{ detail.customer_name || detail.customer || "—" }}</dd>
				<dt class="col-5 text-secondary">{{ t("Service person") }}</dt>
				<dd class="col-7">{{ detail.service_person || "—" }}</dd>
				<dt class="col-5 text-secondary">{{ t("Status") }}</dt>
				<dd class="col-7">{{ detail.completion_status || "—" }}</dd>
				<dt class="col-5 text-secondary">{{ detail.kind === "planned" ? t("Schedule") : t("Visit") }}</dt>
				<dd class="col-7 font-monospace">{{ detail.schedule || detail.visit || detail.contractId }}</dd>
				<dt v-if="detail.item_code || detail.item_name" class="col-5 text-secondary">{{ t("Item") }}</dt>
				<dd v-if="detail.item_code || detail.item_name" class="col-7">{{ detail.item_name || detail.item_code }}</dd>
				<dt v-if="detail.serial_no" class="col-5 text-secondary">{{ t("Serial No") }}</dt>
				<dd v-if="detail.serial_no" class="col-7 font-monospace">{{ detail.serial_no }}</dd>
			</dl>

			<form v-if="detail.kind === 'planned'" class="border rounded p-3 mb-3" @submit.prevent="reschedule">
				<label class="form-label">{{ t("Reschedule") }}</label>
				<div class="input-group">
					<input v-model="rescheduleDate" type="date" class="form-control" :disabled="saving" required />
					<button type="submit" class="btn btn-primary" :disabled="saving || !rescheduleDate">
						<span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
						{{ t("Save") }}
					</button>
				</div>
			</form>

			<div class="fw-semibold small mb-2">{{ t("Same day") }}</div>
			<div class="list-group list-group-flush border rounded">
				<button
					v-for="event in selectedDayEvents"
					:key="event.kind + event.contractId"
					type="button"
					class="list-group-item list-group-item-action"
					@click="openDetail(event)"
				>
					<div class="d-flex justify-content-between gap-2">
						<span>{{ event.label }}</span>
						<span class="badge" :class="event.kind === 'planned' ? 'bg-blue-lt' : 'bg-green-lt'">
							{{ event.kind === "planned" ? t("Planned") : t("Done") }}
						</span>
					</div>
				</button>
			</div>
		</div>
	</div>
</template>
