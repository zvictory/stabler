<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDate, formatDateTime } from "../../composables/date.js";
import { useSession } from "../../stores/session.js";
import EmptyState from "../../components/EmptyState.vue";
import Typeahead from "../../components/Typeahead.vue";

const session = useSession();
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const tickets = ref([]);
const meta = ref({ statuses: [], tech_states: [], issue_types: [], priorities: [], technicians: [], service_people: [] });
const filters = ref({ issue_type: "", technician: "", customer: "" });
const customerDisplay = ref("");
const drawerOpen = ref(false);
const selected = ref(null);
const detailLoading = ref(false);
const createOpen = ref(false);
const draggingName = ref("");
const form = ref({
	customer: "",
	customer_display: "",
	subject: "",
	issue_type: "",
	priority: "",
	serial_no: "",
	description: "",
});
const closeVisitForm = ref({
	work_done: "",
	completion_status: "Fully Completed",
	service_person: "",
});

const company = computed(() => session.activeCompany);
const statuses = computed(() => meta.value.statuses?.length ? meta.value.statuses : ["Open", "Assigned", "In Progress", "On Hold", "Resolved", "Closed", "Cancelled"]);
const technicians = computed(() => meta.value.technicians || []);
const servicePeople = computed(() => meta.value.service_people || []);
const canCloseVisit = computed(() => Boolean(selected.value && !selected.value.maintenance_visit));

const grouped = computed(() => {
	const buckets = Object.fromEntries(statuses.value.map((status) => [status, []]));
	for (const ticket of tickets.value) {
		const status = buckets[ticket.status] ? ticket.status : statuses.value[0];
		buckets[status].push(ticket);
	}
	return buckets;
});

function assigneeLabel(ticket) {
	return ticket.assignees?.[0] || t("Unassigned");
}

function priorityClass(priority) {
	if (priority === "Urgent" || priority === "High") return "text-danger";
	if (priority === "Medium") return "text-warning";
	return "text-secondary";
}

function slaCountdown(resolutionBy) {
	if (!resolutionBy) return null;
	const ms = new Date(resolutionBy) - new Date();
	const h = Math.round(ms / 3_600_000);
	const d = Math.round(ms / 86_400_000);
	if (h < 0) return `${Math.abs(h) < 24 ? Math.abs(h) + "h" : Math.abs(d) + "d"} ${t("overdue")}`;
	return h < 24 ? `${h}h ${t("left")}` : `${d}d ${t("left")}`;
}

async function searchCustomers(search) {
	return call("stabler.api.sales.list_customers", {
		company: company.value,
		search,
		limit: 20,
	});
}

function pickFilterCustomer(customer) {
	filters.value.customer = customer.name;
	customerDisplay.value = customer.customer_name ? `${customer.customer_name} · ${customer.name}` : customer.name;
	loadTickets();
}

function clearFilterCustomer() {
	filters.value.customer = "";
	customerDisplay.value = "";
	loadTickets();
}

function pickFormCustomer(customer) {
	form.value.customer = customer.name;
	form.value.customer_display = customer.customer_name ? `${customer.customer_name} · ${customer.name}` : customer.name;
}

function clearFormCustomer() {
	form.value.customer = "";
	form.value.customer_display = "";
}

async function loadMeta() {
	meta.value = await call("stabler.api.service.ticket_board_meta", { company: company.value });
	if (!form.value.issue_type) form.value.issue_type = meta.value.issue_types?.[0] || "";
	if (!form.value.priority) form.value.priority = meta.value.priorities?.[0] || "";
	if (!closeVisitForm.value.service_person) {
		closeVisitForm.value.service_person = meta.value.service_people?.[0]?.name || "";
	}
}

async function loadTickets() {
	loading.value = true;
	error.value = "";
	try {
		tickets.value = await call("stabler.api.service.list_tickets", {
			company: company.value,
			issue_type: filters.value.issue_type || undefined,
			technician: filters.value.technician || undefined,
			customer: filters.value.customer || undefined,
			limit: 200,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load service tickets.");
	} finally {
		loading.value = false;
	}
}

async function refreshAll() {
	await loadMeta();
	await loadTickets();
}

async function openDetail(ticket) {
	selected.value = ticket;
	drawerOpen.value = true;
	detailLoading.value = true;
	try {
		selected.value = await call("stabler.api.service.ticket_detail", { name: ticket.name });
		resetCloseVisitForm();
	} catch (err) {
		error.value = err?.message || t("Failed to load ticket.");
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	if (saving.value) return;
	drawerOpen.value = false;
	selected.value = null;
}

async function setStatus(status, techState = "") {
	if (!selected.value) return;
	saving.value = true;
	try {
		selected.value = await call("stabler.api.service.update_ticket_status", {
			name: selected.value.name,
			status,
			tech_state: techState,
		});
		await loadTickets();
	} catch (err) {
		error.value = err?.message || t("Failed to update status.");
	} finally {
		saving.value = false;
	}
}

async function assignTicket(user) {
	if (!selected.value || !user) return;
	saving.value = true;
	try {
		selected.value = await call("stabler.api.service.assign_ticket", {
			name: selected.value.name,
			user,
		});
		await loadTickets();
	} catch (err) {
		error.value = err?.message || t("Failed to assign ticket.");
	} finally {
		saving.value = false;
	}
}

function resetCloseVisitForm() {
	closeVisitForm.value = {
		work_done: "",
		completion_status: "Fully Completed",
		service_person: closeVisitForm.value.service_person || servicePeople.value[0]?.name || "",
	};
}

async function closeVisit() {
	if (!selected.value || selected.value.maintenance_visit) return;
	saving.value = true;
	error.value = "";
	try {
		const purpose = {
			service_person: closeVisitForm.value.service_person,
			work_done: closeVisitForm.value.work_done,
			serial_no: selected.value.serial_no || undefined,
			description: selected.value.subject,
		};
		await call("stabler.api.service.create_visit_from_ticket", {
			ticket: selected.value.name,
			work_done: closeVisitForm.value.work_done,
			completion_status: closeVisitForm.value.completion_status,
			serial_purposes: [purpose],
			feedback: closeVisitForm.value.work_done,
		});
		await loadTickets();
		selected.value = await call("stabler.api.service.ticket_detail", { name: selected.value.name });
		resetCloseVisitForm();
	} catch (err) {
		error.value = err?.message || t("Failed to close visit.");
	} finally {
		saving.value = false;
	}
}

async function createTicket() {
	saving.value = true;
	error.value = "";
	try {
		const ticket = await call("stabler.api.service.create_ticket", {
			company: company.value,
			customer: form.value.customer,
			subject: form.value.subject,
			issue_type: form.value.issue_type,
			priority: form.value.priority,
			serial_no: form.value.serial_no || undefined,
			description: form.value.description || undefined,
		});
		createOpen.value = false;
		form.value = {
			customer: "",
			customer_display: "",
			subject: "",
			issue_type: meta.value.issue_types?.[0] || "",
			priority: meta.value.priorities?.[0] || "",
			serial_no: "",
			description: "",
		};
		await loadTickets();
		openDetail(ticket);
	} catch (err) {
		error.value = err?.message || t("Failed to create ticket.");
	} finally {
		saving.value = false;
	}
}

function onDragStart(ticket) {
	draggingName.value = ticket.name;
}

async function onDrop(status) {
	const name = draggingName.value;
	draggingName.value = "";
	if (!name) return;
	const ticket = tickets.value.find((row) => row.name === name);
	if (!ticket || ticket.status === status) return;
	saving.value = true;
	try {
		const updated = await call("stabler.api.service.update_ticket_status", { name, status });
		tickets.value = tickets.value.map((row) => (row.name === name ? updated : row));
	} catch (err) {
		error.value = err?.message || t("Failed to move ticket.");
		await loadTickets();
	} finally {
		saving.value = false;
	}
}

watch(company, refreshAll);
onMounted(refreshAll);
</script>

<template>
	<div class="card mb-3">
		<div class="card-body">
			<div class="row g-2 align-items-end">
				<div class="col-md-3">
					<label class="form-label">{{ t("Issue type") }}</label>
					<select v-model="filters.issue_type" class="form-select" @change="loadTickets">
						<option value="">{{ t("All types") }}</option>
						<option v-for="kind in meta.issue_types" :key="kind" :value="kind">{{ kind }}</option>
					</select>
				</div>
				<div class="col-md-3">
					<label class="form-label">{{ t("Technician") }}</label>
					<select v-model="filters.technician" class="form-select" @change="loadTickets">
						<option value="">{{ t("All technicians") }}</option>
						<option v-for="tech in technicians" :key="tech.name" :value="tech.name">
							{{ tech.full_name || tech.name }}
						</option>
					</select>
				</div>
				<div class="col-md-4">
					<label class="form-label">{{ t("Customer") }}</label>
					<Typeahead
						v-model="filters.customer"
						:display="customerDisplay"
						:search="searchCustomers"
						:placeholder="t('Search customer')"
						open-on-focus
						@pick="pickFilterCustomer"
						@clear="clearFilterCustomer"
					>
						<template #option="{ item }">
							<div class="fw-semibold">{{ item.customer_name || item.name }}</div>
							<div class="small text-secondary">{{ item.name }}</div>
						</template>
					</Typeahead>
				</div>
				<div class="col-md-2 d-flex gap-2 justify-content-md-end">
					<button type="button" class="btn btn-outline-secondary" @click="refreshAll">
						<i class="ti ti-refresh"></i>
					</button>
					<button type="button" class="btn btn-primary" @click="createOpen = true">
						<i class="ti ti-plus me-1"></i>{{ t("New Ticket") }}
					</button>
				</div>
			</div>
			<div v-if="error" class="alert alert-danger mt-3 mb-0">{{ error }}</div>
		</div>
	</div>

	<div v-if="loading" class="text-center py-5">
		<div class="spinner-border text-primary"></div>
	</div>
	<EmptyState v-else-if="!tickets.length" icon="ti-ticket-off" :title="t('No service tickets')" />
	<div v-else class="service-board">
		<section
			v-for="status in statuses"
			:key="status"
			class="service-column"
			@dragover.prevent
			@drop="onDrop(status)"
		>
			<div class="d-flex align-items-center justify-content-between mb-2">
				<div class="fw-semibold">{{ status }}</div>
				<span class="badge bg-secondary-lt">{{ grouped[status]?.length || 0 }}</span>
			</div>
			<button
				v-for="ticket in grouped[status]"
				:key="ticket.name"
				type="button"
				class="service-ticket"
				draggable="true"
				@dragstart="onDragStart(ticket)"
				@click="openDetail(ticket)"
			>
				<div class="d-flex align-items-start justify-content-between gap-2">
					<div class="fw-semibold text-truncate">{{ ticket.subject }}</div>
					<span class="badge bg-blue-lt">{{ ticket.issue_type || t("Issue") }}</span>
				</div>
				<div class="small text-secondary text-truncate mt-1">
					<i class="ti ti-building me-1"></i>{{ ticket.customer_name || ticket.customer || "—" }}
				</div>
				<div class="d-flex align-items-center justify-content-between small mt-2">
					<span :class="priorityClass(ticket.priority)">
						<i class="ti ti-flag me-1"></i>{{ ticket.priority || t("Normal") }}
					</span>
					<span class="text-secondary text-truncate">
						<i class="ti ti-user-check me-1"></i>{{ assigneeLabel(ticket) }}
					</span>
				</div>
				<div class="d-flex align-items-center justify-content-between small text-secondary mt-2">
					<span class="text-truncate">
						<i class="ti ti-barcode me-1"></i>{{ ticket.serial_no || t("No serial") }}
					</span>
					<span v-if="ticket.sla_failed" class="badge bg-danger-lt">{{ slaCountdown(ticket.resolution_by) }}</span>
					<span v-else-if="ticket.resolution_by" class="badge bg-green-lt">{{ slaCountdown(ticket.resolution_by) }}</span>
				</div>
			</button>
		</section>
	</div>

	<div v-if="drawerOpen || createOpen" class="offcanvas-backdrop fade show" @click="createOpen ? (createOpen = false) : closeDetail()"></div>

	<div v-if="drawerOpen" class="offcanvas offcanvas-end show" tabindex="-1" style="visibility: visible; width: 560px">
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">
				<i class="ti ti-ticket me-1"></i>{{ selected?.name }}
			</h5>
			<button type="button" class="btn-close" @click="closeDetail"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="selected" class="vstack gap-3">
				<div>
					<div class="text-secondary small">{{ selected.issue_type }}</div>
					<h3 class="mb-1">{{ selected.subject }}</h3>
					<div class="text-secondary">{{ selected.customer_name || selected.customer }}</div>
				</div>
				<div class="row g-2">
					<div class="col-6">
						<label class="form-label">{{ t("Status") }}</label>
						<select class="form-select" :value="selected.status" :disabled="saving" @change="setStatus($event.target.value, selected.tech_state)">
							<option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
						</select>
					</div>
					<div class="col-6">
						<label class="form-label">{{ t("Technician state") }}</label>
						<select class="form-select" :value="selected.tech_state || ''" :disabled="saving" @change="setStatus('In Progress', $event.target.value)">
							<option value="">{{ t("None") }}</option>
							<option v-for="state in meta.tech_states" :key="state" :value="state">{{ state }}</option>
						</select>
					</div>
					<div class="col-12">
						<label class="form-label">{{ t("Assign technician") }}</label>
						<select class="form-select" :disabled="saving" @change="assignTicket($event.target.value)">
							<option value="">{{ selected.assignees?.[0] || t("Select technician") }}</option>
							<option v-for="tech in technicians" :key="tech.name" :value="tech.name">
								{{ tech.full_name || tech.name }}
							</option>
						</select>
					</div>
				</div>
				<div class="list-group list-group-flush border rounded">
					<div class="list-group-item d-flex justify-content-between">
						<span class="text-secondary">{{ t("Priority") }}</span>
						<span>{{ selected.priority || "—" }}</span>
					</div>
					<div class="list-group-item d-flex justify-content-between">
						<span class="text-secondary">{{ t("Serial No") }}</span>
						<span>{{ selected.serial_no || "—" }}</span>
					</div>
					<div class="list-group-item d-flex justify-content-between">
						<span class="text-secondary">{{ t("Opened") }}</span>
						<span>{{ selected.opening_date ? formatDate(selected.opening_date) : "—" }}</span>
					</div>
					<div class="list-group-item d-flex justify-content-between">
						<span class="text-secondary">{{ t("Maintenance Visit") }}</span>
						<span>{{ selected.maintenance_visit || "—" }}</span>
					</div>
				</div>
				<div v-if="selected.description">
					<label class="form-label">{{ t("Description") }}</label>
					<div class="border rounded p-3 bg-body-tertiary" v-html="selected.description"></div>
				</div>
				<form v-if="canCloseVisit" class="border rounded p-3 vstack gap-3" @submit.prevent="closeVisit">
					<div class="d-flex align-items-center justify-content-between">
						<div class="fw-semibold">{{ t("Close visit") }}</div>
						<span class="badge bg-green-lt">{{ t("Creates Maintenance Visit") }}</span>
					</div>
					<div>
						<label class="form-label">{{ t("Service person") }}</label>
						<select v-model="closeVisitForm.service_person" class="form-select" :disabled="saving" required>
							<option value="">{{ t("Select service person") }}</option>
							<option v-for="person in servicePeople" :key="person.name" :value="person.name">
								{{ person.sales_person_name || person.name }}
							</option>
						</select>
					</div>
					<div>
						<label class="form-label">{{ t("Completion") }}</label>
						<select v-model="closeVisitForm.completion_status" class="form-select" :disabled="saving">
							<option value="Fully Completed">{{ t("Fully Completed") }}</option>
							<option value="Partially Completed">{{ t("Partially Completed") }}</option>
						</select>
					</div>
					<div>
						<label class="form-label">{{ t("Work done") }}</label>
						<textarea v-model.trim="closeVisitForm.work_done" class="form-control" rows="3" :disabled="saving" required></textarea>
					</div>
					<div class="d-flex justify-content-end">
						<button
							type="submit"
							class="btn btn-success"
							:disabled="saving || !closeVisitForm.service_person || !closeVisitForm.work_done"
						>
							<span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
							{{ t("Close Visit") }}
						</button>
					</div>
				</form>
				<div v-else-if="selected.maintenance_visit" class="alert alert-success mb-0">
					<i class="ti ti-circle-check me-1"></i>{{ t("Visit closed") }} · {{ selected.maintenance_visit }}
				</div>
				<div>
					<label class="form-label">{{ t("Comments") }}</label>
					<div v-if="!selected.comments?.length" class="text-secondary small">{{ t("No comments yet.") }}</div>
					<div v-for="comment in selected.comments" :key="comment.name" class="border rounded p-2 mb-2">
						<div class="small text-secondary">{{ comment.owner }} · {{ formatDateTime(comment.creation) }}</div>
						<div v-html="comment.content"></div>
					</div>
				</div>
				<div>
					<label class="form-label">{{ t("Files") }}</label>
					<div v-if="!selected.files?.length" class="text-secondary small">{{ t("No files attached.") }}</div>
					<div v-for="file in selected.files" :key="file.name" class="d-flex align-items-center gap-2 small mb-1">
						<i class="ti ti-paperclip text-secondary"></i>
						<span>{{ file.file_name }}</span>
					</div>
				</div>
			</div>
		</div>
	</div>

	<div v-if="createOpen" class="offcanvas offcanvas-end show" tabindex="-1" style="visibility: visible; width: 560px">
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">
				<i class="ti ti-plus me-1"></i>{{ t("New Service Ticket") }}
			</h5>
			<button type="button" class="btn-close" @click="createOpen = false"></button>
		</div>
		<div class="offcanvas-body">
			<form class="vstack gap-3" @submit.prevent="createTicket">
				<div>
					<label class="form-label">{{ t("Customer") }}</label>
					<Typeahead
						v-model="form.customer"
						:display="form.customer_display"
						:search="searchCustomers"
						:placeholder="t('Search customer')"
						open-on-focus
						@pick="pickFormCustomer"
						@clear="clearFormCustomer"
					>
						<template #option="{ item }">
							<div class="fw-semibold">{{ item.customer_name || item.name }}</div>
							<div class="small text-secondary">{{ item.name }}</div>
						</template>
					</Typeahead>
				</div>
				<div>
					<label class="form-label">{{ t("Subject") }}</label>
					<input v-model.trim="form.subject" class="form-control" required />
				</div>
				<div class="row g-2">
					<div class="col-6">
						<label class="form-label">{{ t("Issue type") }}</label>
						<select v-model="form.issue_type" class="form-select" required>
							<option v-for="kind in meta.issue_types" :key="kind" :value="kind">{{ kind }}</option>
						</select>
					</div>
					<div class="col-6">
						<label class="form-label">{{ t("Priority") }}</label>
						<select v-model="form.priority" class="form-select">
							<option v-for="priority in meta.priorities" :key="priority" :value="priority">{{ priority }}</option>
						</select>
					</div>
				</div>
				<div>
					<label class="form-label">{{ t("Serial No") }}</label>
					<input v-model.trim="form.serial_no" class="form-control" />
				</div>
				<div>
					<label class="form-label">{{ t("Description") }}</label>
					<textarea v-model.trim="form.description" class="form-control" rows="4"></textarea>
				</div>
				<div class="d-flex justify-content-end gap-2">
					<button type="button" class="btn btn-outline-secondary" :disabled="saving" @click="createOpen = false">{{ t("Cancel") }}</button>
					<button type="submit" class="btn btn-primary" :disabled="saving || !form.customer || !form.subject || !form.issue_type">
						<span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
						{{ t("Create Ticket") }}
					</button>
				</div>
			</form>
		</div>
	</div>
</template>

<style scoped>
.service-board {
	display: grid;
	grid-auto-columns: minmax(260px, 1fr);
	grid-auto-flow: column;
	gap: 1rem;
	overflow-x: auto;
	padding-bottom: 0.25rem;
}

.service-column {
	background: var(--tblr-bg-surface-secondary);
	border: 1px solid var(--tblr-border-color);
	border-radius: var(--tblr-border-radius);
	min-height: 520px;
	padding: 0.75rem;
}

.service-ticket {
	background: var(--tblr-bg-surface);
	border: 1px solid var(--tblr-border-color);
	border-radius: var(--tblr-border-radius);
	box-shadow: var(--tblr-box-shadow-sm);
	color: inherit;
	display: block;
	margin-bottom: 0.75rem;
	padding: 0.75rem;
	text-align: left;
	width: 100%;
}

.service-ticket:hover {
	border-color: var(--tblr-primary);
}
</style>
