<script setup>
import { onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { useConfirm } from "../../composables/useConfirm.js";
import EmptyState from "../../components/EmptyState.vue";

const router = useRouter();
const session = useSession();
const { activeCompany } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const processes = ref([]);
const total = ref(0);
const search = ref("");
const creating = ref(false);

const { confirm } = useConfirm();

async function fetchProcesses() {
	loading.value = true;
	error.value = "";
	try {
		const res = await call("stabler.api.bpm.list_processes", {
			search: search.value,
			company: activeCompany.value || "",
			page_length: 50,
			start: 0,
		});
		processes.value = res.processes || [];
		total.value = res.total || 0;
	} catch (err) {
		error.value = err?.message || t("Failed to load processes.");
	} finally {
		loading.value = false;
	}
}

async function newProcess() {
	creating.value = true;
	try {
		const res = await call("stabler.api.bpm.save_process", {
			data: JSON.stringify({
				process_name: t("Untitled Process"),
				company: activeCompany.value || "",
				status: "Draft",
				diagram: JSON.stringify({ lanes: [], nodes: [], edges: [] }),
			}),
		});
		router.push({ name: "bpm-editor", params: { name: res.name } });
	} catch (err) {
		error.value = err?.message || t("Failed to save process.");
	} finally {
		creating.value = false;
	}
}

async function deleteProcess(proc) {
	const ok = await confirm({
		title: t("Delete process?"),
		body: t("Delete this process?"),
		danger: true,
	});
	if (!ok) return;
	try {
		await call("stabler.api.bpm.delete_process", { name: proc.name });
		fetchProcesses();
	} catch (err) {
		error.value = err?.message || t("Failed to save process.");
	}
}

function openProcess(proc) {
	router.push({ name: "bpm-editor", params: { name: proc.name } });
}


onMounted(fetchProcesses);
watch(activeCompany, fetchProcesses);
</script>

<template>
	<div class="d-flex gap-2 align-items-center flex-wrap mb-3">
		<div class="input-group input-group-sm" style="max-width: 280px">
			<span class="input-group-text"><i class="ti ti-search"></i></span>
			<input
				v-model="search"
				type="text"
				class="form-control"
				:placeholder="t('Search processes…')"
				@keyup.enter="fetchProcesses"
			/>
		</div>
		<button type="button" class="btn btn-sm btn-outline-secondary" :disabled="loading" @click="fetchProcesses">
			<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
		</button>
		<button type="button" class="btn btn-sm btn-primary ms-auto" :disabled="creating" @click="newProcess">
			<span v-if="creating" class="spinner-border spinner-border-sm me-1"></span>
			<i v-else class="ti ti-plus me-1"></i>{{ t("New Process") }}
		</button>
	</div>

	<div v-if="error" class="alert alert-danger">{{ error }}</div>

	<div v-if="loading" class="text-center py-5">
		<div class="spinner-border text-primary" role="status"></div>
	</div>
	<template v-else>
		<EmptyState
			v-if="!processes.length"
			icon="ti-sitemap"
			:title="t('No processes')"
			:description="t('Create your first process to model business workflows.')"
		/>
		<div v-else class="card">
			<div class="table-responsive">
				<table class="table table-sm table-vcenter card-table">
					<thead>
						<tr>
							<th>{{ t("Process Name") }}</th>
							<th>{{ t("Company") }}</th>
							<th>{{ t("Status") }}</th>
							<th>{{ t("Modified") }}</th>
							<th style="width: 48px"></th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="proc in processes"
							:key="proc.name"
							style="cursor: pointer"
							@click="openProcess(proc)"
						>
							<td class="fw-semibold">{{ proc.process_name }}</td>
							<td class="small text-secondary">{{ proc.company }}</td>
							<td>
								<span class="badge" :class="getStatusBadgeClass('Stabler Process', proc.status)">
									{{ proc.status }}
								</span>
							</td>
							<td class="small text-secondary text-nowrap">{{ formatDate(proc.modified) }}</td>
							<td>
								<button
									type="button"
									class="btn btn-ghost-danger btn-icon btn-sm"
									:title="t('Delete')"
									@click.stop="deleteProcess(proc)"
								>
									<i class="ti ti-trash"></i>
								</button>
							</td>
						</tr>
					</tbody>
				</table>
			</div>
			<div class="card-footer text-secondary small">
				{{ t("Showing") }} {{ processes.length }} / {{ total }}
			</div>
		</div>
	</template>
</template>
