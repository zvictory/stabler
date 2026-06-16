<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useToast } from "../../composables/useToast.js";
import EmptyState from "../../components/EmptyState.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const { confirm } = useConfirm();
const toast = useToast();

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const busy = ref("");
const search = ref("");
const statusFilter = ref("Pending");
const employeeFilter = ref("");

const statusOptions = computed(() => [
	{ value: "Pending", label: t("Pending") },
	{ value: "Approved", label: t("Approved") },
	{ value: "Rejected", label: t("Rejected") },
	{ value: "Applied", label: t("Applied") },
]);

const filteredRows = computed(() => {
	const q = search.value.trim().toLowerCase();
	if (!q) return rows.value;
	return rows.value.filter((r) =>
		[r.name, r.employee, r.correction_type, r.reason, r.requested_by, r.approver]
			.filter(Boolean)
			.some((v) => String(v).toLowerCase().includes(q)),
	);
});

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.hr_corrections.list_corrections", {
			status: statusFilter.value || undefined,
			employee: employeeFilter.value || undefined,
			company: activeCompany.value,
			limit: 200,
		});
	} catch (e) {
		error.value = e?.message || String(e);
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

function isSelfMade(r) {
	// Disable approve when the row belongs to the current user (SoD — backend also enforces).
	return r.requested_by && user.value?.id && r.requested_by === user.value.id;
}

async function approve(r) {
	const ok = await confirm({
		title: t("Approve correction"),
		body: t("Approve this correction request? The change will be queued for payroll."),
		confirmLabel: t("Approve"),
	});
	if (!ok) return;

	// Prompt for optional note via a second confirm (re-use confirm as informational — note field below)
	// We keep it simple: note is empty unless the user typed one via a lightweight prompt.
	// A proper note input would require a modal; here we use window.prompt for brevity.
	// eslint-disable-next-line no-alert
	const note = window.prompt(t("Optional note (leave blank to skip):") || "") || "";

	busy.value = r.name;
	try {
		await call("stabler.api.hr_corrections.approve_correction", { name: r.name, note });
		toast.success(t("Correction approved."));
		await load();
	} catch (e) {
		toast.error(e?.message || String(e));
	} finally {
		busy.value = "";
	}
}

async function reject(r) {
	const ok = await confirm({
		title: t("Reject correction"),
		body: t("Reject this correction request? The requester will be notified."),
		danger: true,
		confirmLabel: t("Reject"),
	});
	if (!ok) return;

	// eslint-disable-next-line no-alert
	const note = window.prompt(t("Optional note (leave blank to skip):") || "") || "";

	busy.value = r.name;
	try {
		await call("stabler.api.hr_corrections.reject_correction", { name: r.name, note });
		toast.success(t("Correction rejected."));
		await load();
	} catch (e) {
		toast.error(e?.message || String(e));
	} finally {
		busy.value = "";
	}
}

watch([activeCompany, statusFilter, employeeFilter], load);
onMounted(load);
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('Employee, type or reason…') + '  ⌘K'"
			:count="filteredRows.length"
		>
			<template #filters>
				<div class="btn-group" role="group">
					<button
						v-for="opt in statusOptions"
						:key="opt.value"
						type="button"
						class="btn btn-sm"
						:class="statusFilter === opt.value ? 'btn-primary' : 'btn-outline-secondary'"
						@click="statusFilter = opt.value"
					>
						{{ opt.label }}
					</button>
				</div>
			</template>
		</ListToolbar>

		<div v-if="error" class="alert alert-danger m-3">{{ error }}</div>

		<div class="table-responsive">
			<table class="table card-table table-vcenter">
				<thead>
					<tr>
						<th>{{ t("Employee") }}</th>
						<th>{{ t("Date") }}</th>
						<th>{{ t("Type") }}</th>
						<th>{{ t("Before → Requested") }}</th>
						<th>{{ t("Reason") }}</th>
						<th>{{ t("Impact") }}</th>
						<th>{{ t("Status") }}</th>
						<th class="text-end"></th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="6" :cols="8" />
				<tbody v-else>
					<tr v-for="r in filteredRows" :key="r.name">
						<td>
							<div class="fw-medium">{{ r.employee }}</div>
							<div v-if="r.requested_by" class="small text-secondary">
								{{ t("By") }}: {{ r.requested_by }}
							</div>
						</td>
						<td class="font-monospace">{{ formatDate(r.correction_date) }}</td>
						<td>{{ r.correction_type || "—" }}</td>
						<td>
							<span class="text-secondary font-monospace">{{ r.before_value ?? "—" }}</span>
							<i class="ti ti-arrow-right mx-1 text-secondary"></i>
							<span class="font-monospace fw-medium">{{ r.requested_value ?? "—" }}</span>
						</td>
						<td class="text-secondary small" style="max-width: 220px; white-space: normal;">
							{{ r.reason || "—" }}
						</td>
						<td>
							<span
								v-if="r.payroll_impact"
								class="badge bg-yellow-lt"
								:title="t('This correction affects payroll calculations')"
							>
								{{ t("Payroll") }}
							</span>
							<span v-else class="text-secondary small">—</span>
						</td>
						<td>
							<span class="badge" :class="getStatusBadgeClass('Correction Status', r.status)">
								{{ t(r.status) }}
							</span>
						</td>
						<td class="text-end">
							<div v-if="statusFilter === 'Pending'" class="btn-list justify-content-end">
								<button
									class="btn btn-sm btn-outline-secondary"
									:disabled="busy === r.name"
									@click="reject(r)"
								>
									{{ t("Reject") }}
								</button>
								<button
									class="btn btn-sm btn-success"
									:disabled="busy === r.name || isSelfMade(r)"
									:title="isSelfMade(r) ? t('You raised this — another user must approve it.') : ''"
									@click="approve(r)"
								>
									<i class="ti ti-check me-1"></i>{{ t("Approve") }}
								</button>
							</div>
							<div v-else-if="r.reviewed_at" class="small text-secondary font-monospace">
								{{ formatDate(r.reviewed_at) }}
							</div>
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<EmptyState
			v-if="!loading && filteredRows.length === 0"
			icon="ti-writing"
			:title="t('No correction requests')"
			:subtitle="statusFilter === 'Pending'
				? t('No corrections are waiting for review.')
				: t('No corrections found for this status.')"
		/>
	</div>
</template>
