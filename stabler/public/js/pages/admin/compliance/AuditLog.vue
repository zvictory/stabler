<script setup>
// Global audit feed: recent "who changed what" across financial documents.
// Reviewers/admins only (server-gated). Click a row to open its full timeline.
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { call } from "../../../api/client.js";
import { formatDateTime } from "../../../composables/date.js";
import { t } from "../../../composables/i18n.js";
import { useSession } from "../../../stores/session.js";
import DateInput from "../../../components/DateInput.vue";
import Select from "../../../components/Select.vue";
import SkeletonRows from "../../../components/SkeletonRows.vue";
import AuditTrail from "../../../components/AuditTrail.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);

const rows = ref([]);
const loading = ref(false);
const error = ref("");
const doctypeFilter = ref("");
const doctypeOptions = ref([]);
const monthAgo = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
const today = new Date().toISOString().slice(0, 10);
const fromDate = ref(monthAgo);
const toDate = ref(today);

const drawer = ref({ open: false, doctype: "", name: "" });

const TYPE_BADGE = {
	create: "bg-blue-lt",
	edit: "bg-secondary-lt",
	submit: "bg-green-lt",
	cancel: "bg-red-lt",
	comment: "bg-azure-lt",
	approval_requested: "bg-yellow-lt",
	approved: "bg-green-lt",
	rejected: "bg-red-lt",
};

const dtOptions = computed(() => [
	{ value: "", label: t("All documents") },
	...doctypeOptions.value.map((d) => ({ value: d, label: t(d) })),
]);

async function loadMeta() {
	try {
		const m = await call("stabler.api.audit.audit_meta");
		doctypeOptions.value = m.doctypes || [];
	} catch (e) {
		/* non-fatal */
	}
}

async function load() {
	loading.value = true;
	error.value = "";
	try {
		const res = await call("stabler.api.audit.recent_activity", {
			company: activeCompany.value || undefined,
			doctype: doctypeFilter.value || undefined,
			from_date: fromDate.value || undefined,
			to_date: toDate.value || undefined,
			limit: 200,
		});
		rows.value = res.events || [];
	} catch (e) {
		error.value = e?.message || String(e);
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

function openTrail(r) {
	drawer.value = { open: true, doctype: r.doctype, name: r.name };
}

onMounted(async () => {
	await loadMeta();
	await load();
});
</script>

<template>
	<div>
		<div class="d-flex flex-wrap align-items-end gap-2 mb-3">
			<div>
				<label class="form-label small mb-1">{{ t("Document type") }}</label>
				<Select v-model="doctypeFilter" :options="dtOptions" style="width: 200px" @update:modelValue="load" />
			</div>
			<div>
				<label class="form-label small mb-1">{{ t("From") }}</label>
				<DateInput v-model="fromDate" size="sm" style="width: 120px" @update:modelValue="load" />
			</div>
			<div>
				<label class="form-label small mb-1">{{ t("To") }}</label>
				<DateInput v-model="toDate" size="sm" style="width: 120px" @update:modelValue="load" />
			</div>
			<button class="btn btn-sm btn-outline-secondary ms-auto" :disabled="loading" @click="load">
				<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
			</button>
		</div>

		<div v-if="error" class="alert alert-danger">{{ error }}</div>

		<div class="table-responsive">
			<table class="table card-table table-vcenter">
				<thead>
					<tr>
						<th>{{ t("When") }}</th>
						<th>{{ t("Action") }}</th>
						<th>{{ t("Document") }}</th>
						<th>{{ t("User") }}</th>
						<th></th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="8" :cols="5" />
				<tbody v-else>
					<tr v-for="(r, i) in rows" :key="i" style="cursor: pointer" @click="openTrail(r)">
						<td class="text-secondary small">{{ formatDateTime(r.timestamp) }}</td>
						<td><span class="badge" :class="TYPE_BADGE[r.type] || 'bg-secondary-lt'">{{ r.summary }}</span></td>
						<td>
							<div class="small">{{ t(r.doctype) }}</div>
							<div class="font-monospace text-secondary" style="font-size: 0.72rem">{{ r.name }}</div>
						</td>
						<td class="small">{{ r.user_name || r.user }}</td>
						<td class="text-end"><i class="ti ti-history text-secondary"></i></td>
					</tr>
					<tr v-if="rows.length === 0">
						<td colspan="5" class="text-center text-secondary py-5">
							{{ t("No recorded activity in this period.") }}
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<AuditTrail
			:open="drawer.open"
			:doctype="drawer.doctype"
			:name="drawer.name"
			@close="drawer.open = false"
		/>
	</div>
</template>
