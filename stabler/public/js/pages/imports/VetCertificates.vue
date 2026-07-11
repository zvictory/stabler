<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import { useToast } from "../../composables/useToast.js";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";
import StatusBadge from "../../components/StatusBadge.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const toast = useToast();

const search = ref("");
const status = ref("Pending");
const loading = ref(false);
const error = ref("");
const rows = ref([]);

const STATUSES = ["Pending", "Approved", "Rejected", "Expired"];
const statusOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	...STATUSES.map((s) => ({ value: s, label: t(s) })),
]);

// Server enforces; this only decides whether to render the inline actions.
const canReview = computed(() =>
	(session.roles || []).some((r) =>
		["Imports Manager", "System Manager", "Stabler Admin", "Imports User", "Stabler Declarant"].includes(r)
	)
);

const filtered = computed(() => {
	const needle = search.value.toLowerCase();
	if (!needle) return rows.value;
	return rows.value.filter(
		(r) =>
			(r.certificate_number || "").toLowerCase().includes(needle) ||
			(r.commercial_invoice || "").toLowerCase().includes(needle) ||
			(r.issuing_authority || "").toLowerCase().includes(needle)
	);
});

function daysToExpiry(expiry) {
	if (!expiry) return null;
	const d = new Date(expiry + "T00:00:00");
	const now = new Date();
	now.setHours(0, 0, 0, 0);
	return Math.round((d - now) / 86400000);
}
function expiringSoon(r) {
	if (r.status !== "Approved" && r.status !== "Pending") return false;
	const dl = daysToExpiry(r.expiry_date);
	return dl !== null && dl <= 14;
}

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await importsApi.listVetCertificates({
			company: activeCompany.value,
			status: status.value || undefined,
			limit_page_length: 200,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load veterinary certificates.");
	} finally {
		loading.value = false;
	}
}

async function approve(r) {
	try {
		await importsApi.setVetCertificateStatus(r.name, "Approved", null);
		toast.success(t("Certificate approved."));
		await load();
	} catch (err) {
		toast.error(err?.message || t("Could not approve the certificate."));
	}
}
async function reject(r) {
	const reason = window.prompt(t("Reason for rejection:"));
	if (!reason) return;
	try {
		await importsApi.setVetCertificateStatus(r.name, "Rejected", reason);
		toast.success(t("Certificate rejected."));
		await load();
	} catch (err) {
		toast.error(err?.message || t("Could not reject the certificate."));
	}
}

onMounted(load);
watch(status, load);
watch(activeCompany, load);
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('Certificate, CI or authority… ⌘K')"
			:count="filtered.length"
		>
			<template #filters>
				<Select v-model="status" size="sm" :options="statusOptions" style="width: 160px" />
			</template>
		</ListToolbar>

		<div v-if="error" class="card-body"><div class="alert alert-danger m-0">{{ error }}</div></div>
		<EmptyState
			v-else-if="!loading && !filtered.length"
			icon="ti-vaccine"
			tone="success"
			:title="t('No veterinary certificates')"
			:subtitle="t('Certificates appear here as they are registered against imports.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th class="text-nowrap">{{ t("Certificate") }}</th>
						<th>{{ t("Commercial Invoice") }}</th>
						<th>{{ t("Authority") }}</th>
						<th class="text-nowrap">{{ t("Issued") }}</th>
						<th class="text-nowrap">{{ t("Expiry") }}</th>
						<th>{{ t("Status") }}</th>
						<th class="text-end"></th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="6" :cols="7" />
				<tbody v-else>
					<tr v-for="r in filtered" :key="r.name">
						<td class="font-monospace text-primary text-nowrap">{{ r.certificate_number || r.name }}</td>
						<td class="font-monospace small">{{ r.commercial_invoice || "—" }}</td>
						<td class="small">{{ r.issuing_authority || "—" }}</td>
						<td class="text-nowrap">{{ formatDate(r.issue_date) }}</td>
						<td class="text-nowrap">
							{{ formatDate(r.expiry_date) }}
							<span v-if="expiringSoon(r)" class="badge bg-orange-lt ms-1" :title="t('Expiring soon')">
								<i class="ti ti-clock-exclamation"></i>
							</span>
						</td>
						<td><StatusBadge doctype="Vet Certificate" :status="r.status" /></td>
						<td class="text-end">
							<div v-if="canReview && r.status === 'Pending'" class="btn-group">
								<button type="button" class="btn btn-sm btn-outline-success" @click="approve(r)">{{ t("Approve") }}</button>
								<button type="button" class="btn btn-sm btn-outline-danger" @click="reject(r)">{{ t("Reject") }}</button>
							</div>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>
