<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";
import { formatDateTime } from "../../composables/date.js";
import EmptyState from "../../components/EmptyState.vue";
import {
	listRepairRequests,
	getRepairRequest,
	createRepairRequest,
	updateRepairStatus,
} from "../../api/marketing_equipment.js";

const session = useSession();
const { activeCompany } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const rows = ref([]);

const detailOpen = ref(false);
const detailLoading = ref(false);
const detailError = ref("");
const detail = ref(null);
const acting = ref(false);

const createOpen = ref(false);
const createSaving = ref(false);
const createError = ref("");
const createForm = ref(defaultCreateForm());

function defaultCreateForm() {
	return { equipment: "", issue: "", photo_url: "" };
}

const statusBadge = (s) => {
	switch (s) {
		case "Open":
			return "bg-danger-lt";
		case "InProgress":
			return "bg-warning-lt";
		case "Resolved":
			return "bg-success-lt";
		case "Cancelled":
			return "bg-secondary-lt";
		default:
			return "bg-secondary-lt";
	}
};

const issuePreview = (s) => {
	if (!s) return "—";
	return s.length > 60 ? `${s.slice(0, 60)}…` : s;
};

const nextStatuses = computed(() => {
	const cur = detail.value?.status;
	if (cur === "Open") return [{ to: "InProgress", label: t("Start Work") }];
	if (cur === "InProgress") return [{ to: "Resolved", label: t("Mark Resolved") }];
	return [];
});

const canCancel = computed(() => {
	const cur = detail.value?.status;
	return cur && cur !== "Resolved" && cur !== "Cancelled";
});

async function load() {
	loading.value = true;
	error.value = "";
	try {
		rows.value = await listRepairRequests({});
	} catch (e) {
		error.value = e?.message || t("Something went wrong");
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detailError.value = "";
	detail.value = null;
	try {
		detail.value = await getRepairRequest(name);
	} catch (e) {
		detailError.value = e?.message || t("Failed to load.");
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	if (acting.value) return;
	detailOpen.value = false;
	detail.value = null;
}

async function changeStatus(status) {
	if (!detail.value || acting.value) return;
	acting.value = true;
	try {
		const updated = await updateRepairStatus(detail.value.name, status);
		detail.value = updated;
		await load();
	} catch (e) {
		detailError.value = e?.message || t("Failed to update status.");
	} finally {
		acting.value = false;
	}
}

function openCreate() {
	createForm.value = defaultCreateForm();
	createError.value = "";
	createOpen.value = true;
}

function closeCreate() {
	if (createSaving.value) return;
	createOpen.value = false;
}

async function submitCreate() {
	createError.value = "";
	if (!createForm.value.equipment || !createForm.value.issue) {
		createError.value = t("Equipment and Issue are required.");
		return;
	}
	createSaving.value = true;
	try {
		await createRepairRequest({
			equipment: createForm.value.equipment,
			issue: createForm.value.issue,
			photo_url: createForm.value.photo_url || undefined,
		});
		createOpen.value = false;
		await load();
	} catch (e) {
		createError.value = e?.message || t("Failed to create.");
	} finally {
		createSaving.value = false;
	}
}
</script>

<template>
	<div class="card">
		<div class="card-header d-flex flex-wrap gap-2 align-items-center">
			<h3 class="card-title mb-0">{{ t("Repair Requests") }}</h3>
			<div class="ms-auto">
				<button class="btn btn-primary btn-sm" @click="openCreate">
					{{ t("Report Issue") }}
				</button>
			</div>
		</div>

		<div v-if="loading" class="card-body text-secondary">{{ t("Loading…") }}</div>
		<div v-else-if="error" class="card-body text-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-tool"
			:title="t('No repair requests')"
			:description="t('Submit a request to track equipment service tickets.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("Reference") }}</th>
						<th>{{ t("Equipment") }}</th>
						<th>{{ t("Reported By") }}</th>
						<th>{{ t("Reported At") }}</th>
						<th>{{ t("Status") }}</th>
						<th>{{ t("Issue") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr
						v-for="r in rows"
						:key="r.name"
						style="cursor: pointer"
						@click="openDetail(r.name)"
					>
						<td>{{ r.name }}</td>
						<td>{{ r.equipment }}</td>
						<td>{{ r.reported_by }}</td>
						<td>{{ formatDateTime(r.reported_at) }}</td>
						<td>
							<span class="badge" :class="statusBadge(r.status)">
								{{ t(r.status) }}
							</span>
						</td>
						<td class="text-secondary">{{ issuePreview(r.issue) }}</td>
					</tr>
				</tbody>
			</table>
		</div>

		<!-- Detail drawer -->
		<div
			v-if="detailOpen"
			class="offcanvas offcanvas-end show"
			style="visibility: visible; width: 480px"
			tabindex="-1"
		>
			<div class="offcanvas-header">
				<h2 class="offcanvas-title">{{ detail?.name || t("Repair Request") }}</h2>
				<button
					type="button"
					class="btn-close"
					:disabled="acting"
					@click="closeDetail"
				/>
			</div>
			<div class="offcanvas-body">
				<div v-if="detailLoading" class="text-secondary">{{ t("Loading…") }}</div>
				<div v-else-if="detailError" class="alert alert-danger">
					{{ detailError }}
				</div>
				<template v-else-if="detail">
					<dl class="row mb-3">
						<dt class="col-5">{{ t("Equipment") }}</dt>
						<dd class="col-7">{{ detail.equipment }}</dd>
						<dt class="col-5">{{ t("Reported By") }}</dt>
						<dd class="col-7">{{ detail.reported_by }}</dd>
						<dt class="col-5">{{ t("Reported At") }}</dt>
						<dd class="col-7">{{ formatDateTime(detail.reported_at) }}</dd>
						<dt class="col-5">{{ t("Status") }}</dt>
						<dd class="col-7">
							<span class="badge" :class="statusBadge(detail.status)">
								{{ t(detail.status) }}
							</span>
						</dd>
						<dt class="col-5">{{ t("Assigned Technician") }}</dt>
						<dd class="col-7">{{ detail.assigned_technician || "—" }}</dd>
						<dt v-if="detail.resolved_at" class="col-5">{{ t("Resolved At") }}</dt>
						<dd v-if="detail.resolved_at" class="col-7">{{ formatDateTime(detail.resolved_at) }}</dd>
					</dl>

					<div class="mb-3">
						<div class="text-secondary small mb-1">{{ t("Issue") }}</div>
						<div class="border rounded p-2" style="white-space: pre-wrap">
							{{ detail.issue }}
						</div>
					</div>

					<div v-if="detail.photo_url" class="mb-3">
						<div class="text-secondary small mb-1">{{ t("Photo") }}</div>
						<a :href="detail.photo_url" target="_blank" rel="noopener">
							<img
								:src="detail.photo_url"
								alt=""
								class="img-fluid rounded border"
								style="max-height: 240px"
							/>
						</a>
					</div>
				</template>
			</div>
			<div
				v-if="detail"
				class="offcanvas-footer p-3 border-top d-flex flex-wrap gap-2 justify-content-end"
			>
				<button
					v-for="step in nextStatuses"
					:key="step.to"
					type="button"
					class="btn btn-primary btn-sm"
					:disabled="acting"
					@click="changeStatus(step.to)"
				>
					{{ step.label }}
				</button>
				<button
					v-if="canCancel"
					type="button"
					class="btn btn-outline-danger btn-sm"
					:disabled="acting"
					@click="changeStatus('Cancelled')"
				>
					{{ t("Cancel Request") }}
				</button>
				<button
					type="button"
					class="btn btn-link btn-sm"
					:disabled="acting"
					@click="closeDetail"
				>
					{{ t("Close") }}
				</button>
			</div>
		</div>
		<div
			v-if="detailOpen"
			class="offcanvas-backdrop fade show"
			@click="closeDetail"
		/>

		<!-- Create drawer -->
		<div
			v-if="createOpen"
			class="offcanvas offcanvas-end show"
			style="visibility: visible; width: 480px"
			tabindex="-1"
		>
			<div class="offcanvas-header">
				<h2 class="offcanvas-title">{{ t("Report Issue") }}</h2>
				<button
					type="button"
					class="btn-close"
					:disabled="createSaving"
					@click="closeCreate"
				/>
			</div>
			<div class="offcanvas-body">
				<div v-if="createError" class="alert alert-danger">{{ createError }}</div>
				<div class="mb-3">
					<label class="form-label required">{{ t("Equipment") }}</label>
					<input
						v-model="createForm.equipment"
						type="text"
						class="form-control"
						:placeholder="t('Asset Tag')"
					/>
				</div>
				<div class="mb-3">
					<label class="form-label required">{{ t("Issue") }}</label>
					<textarea
						v-model="createForm.issue"
						class="form-control"
						rows="4"
						:placeholder="t('Describe the problem…')"
					/>
				</div>
				<div class="mb-3">
					<label class="form-label">{{ t("Photo URL") }}</label>
					<input
						v-model="createForm.photo_url"
						type="text"
						class="form-control"
						placeholder="/files/..."
					/>
				</div>
			</div>
			<div class="offcanvas-footer p-3 border-top d-flex justify-content-end gap-2">
				<button
					type="button"
					class="btn btn-link"
					:disabled="createSaving"
					@click="closeCreate"
				>
					{{ t("Cancel") }}
				</button>
				<button
					type="button"
					class="btn btn-primary"
					:disabled="createSaving"
					@click="submitCreate"
				>
					{{ createSaving ? t("Saving…") : t("Submit") }}
				</button>
			</div>
		</div>
		<div
			v-if="createOpen"
			class="offcanvas-backdrop fade show"
			@click="closeCreate"
		/>
	</div>
</template>
