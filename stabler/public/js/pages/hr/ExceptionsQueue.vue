<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useToast } from "../../composables/useToast.js";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const { confirm } = useConfirm();
const toast = useToast();

const search = ref("");
const statusFilter = ref("Open");
const typeFilter = ref("");
const loading = ref(false);
const error = ref("");
const rows = ref([]);
const busy = ref("");

const statusOptions = computed(() => [
	{ value: "Open", label: t("Open") },
	{ value: "Resolved", label: t("Resolved") },
	{ value: "Ignored", label: t("Ignored") },
]);

const typeOptions = computed(() => [
	{ value: "", label: t("All types") },
	{ value: "Missing Entry", label: t("Missing Entry") },
	{ value: "Late Arrival", label: t("Late Arrival") },
	{ value: "Early Exit", label: t("Early Exit") },
	{ value: "Unmatched Event", label: t("Unmatched Event") },
	{ value: "Duplicate Event", label: t("Duplicate Event") },
]);

const filteredRows = computed(() => {
	const q = search.value.trim().toLowerCase();
	if (!q) return rows.value;
	return rows.value.filter((r) =>
		[r.employee, r.employee_name, r.exception_type, r.details, r.name]
			.filter(Boolean)
			.some((v) => String(v).toLowerCase().includes(q)),
	);
});

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.hr_corrections.list_exceptions", {
			company: activeCompany.value,
			status: statusFilter.value || undefined,
			exception_type: typeFilter.value || undefined,
			limit: 200,
		});
	} catch (e) {
		error.value = e?.message || String(e);
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch([activeCompany, statusFilter, typeFilter], load);

async function resolve(r) {
	const ok = await confirm({
		title: t("Resolve exception"),
		body: t("Mark this exception as resolved? This records your name against the action."),
		confirmLabel: t("Resolve"),
	});
	if (!ok) return;
	busy.value = r.name;
	try {
		await call("stabler.api.hr_corrections.resolve_exception", {
			name: r.name,
			resolution: "Resolved",
		});
		toast.success(t("Exception resolved."));
		await load();
	} catch (e) {
		toast.error(e?.message || String(e));
	} finally {
		busy.value = "";
	}
}

async function ignore(r) {
	const ok = await confirm({
		title: t("Ignore exception"),
		body: t("Mark this exception as ignored? It will no longer appear in the Open queue."),
		danger: true,
		confirmLabel: t("Ignore"),
	});
	if (!ok) return;
	busy.value = r.name;
	try {
		await call("stabler.api.hr_corrections.resolve_exception", {
			name: r.name,
			resolution: "Ignored",
		});
		toast.success(t("Exception ignored."));
		await load();
	} catch (e) {
		toast.error(e?.message || String(e));
	} finally {
		busy.value = "";
	}
}
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('Employee or exception type…') + '  ⌘K'"
			:count="filteredRows.length"
		>
			<template #filters>
				<!-- Status filter — pill buttons -->
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

				<!-- Exception type filter -->
				<select
					v-model="typeFilter"
					class="form-select form-select-sm"
					style="width: auto; min-width: 160px"
				>
					<option v-for="opt in typeOptions" :key="opt.value" :value="opt.value">
						{{ opt.label }}
					</option>
				</select>
			</template>
		</ListToolbar>

		<div v-if="error" class="alert alert-danger m-3">{{ error }}</div>

		<div class="table-responsive">
			<table class="table card-table table-vcenter">
				<thead>
					<tr>
						<th>{{ t("Employee") }}</th>
						<th>{{ t("Date") }}</th>
						<th>{{ t("Exception Type") }}</th>
						<th>{{ t("Status") }}</th>
						<th>{{ t("Details") }}</th>
						<th class="text-end"></th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="6" :cols="6" />
				<tbody v-else>
					<tr v-for="r in filteredRows" :key="r.name">
						<td>
							<div class="fw-medium">{{ r.employee_name || r.employee }}</div>
							<div class="text-secondary small font-monospace">{{ r.employee }}</div>
						</td>
						<td class="font-monospace">{{ formatDate(r.exception_date) }}</td>
						<td>{{ t(r.exception_type) }}</td>
						<td>
							<span class="badge" :class="getStatusBadgeClass('Attendance Exception', r.status)">
								{{ t(r.status) }}
							</span>
						</td>
						<td class="text-secondary small">{{ r.details || "—" }}</td>
						<td class="text-end">
							<div v-if="r.status === 'Open'" class="btn-list justify-content-end">
								<button
									class="btn btn-sm btn-outline-secondary"
									:disabled="busy === r.name"
									@click="ignore(r)"
								>
									{{ t("Ignore") }}
								</button>
								<button
									class="btn btn-sm btn-primary"
									:disabled="busy === r.name"
									@click="resolve(r)"
								>
									<i class="ti ti-check me-1"></i>{{ t("Resolve") }}
								</button>
							</div>
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<EmptyState
			v-if="!loading && filteredRows.length === 0"
			icon="ti-circle-check"
			:tone="statusFilter === 'Open' ? 'success' : 'secondary'"
			:title="statusFilter === 'Open' ? t('No open exceptions') : t('No exceptions found')"
			:subtitle="statusFilter === 'Open'
				? t('All attendance exceptions have been resolved or ignored.')
				: t('Try adjusting your filters to find exceptions.')"
		/>
	</div>
</template>
