<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { importsApi } from "../../api/imports.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";

const props = defineProps({
	commercialInvoice: { type: String, required: true },
	packingSummary: { type: Object, required: true },
	grn: { type: Object, default: null },
	loading: { type: Boolean, default: false },
});
const emit = defineEmits(["reload"]);
const router = useRouter();
const toast = useToast();
const { confirm } = useConfirm();
const busy = ref(false);
const actionError = ref("");

// ---- shared sea lifecycle -------------------------------------------------
// The invoice owns the voyage; every container keeps its own hand-maintained
// copy of the same status. They drift silently, so show the gap here instead
// of letting two screens each look authoritative.
const sea = ref(null);
const syncing = ref(false);

async function loadSea() {
	sea.value = null;
	if (!props.commercialInvoice) return;
	try {
		sea.value = await call("stabler.api.imports.ci_sea_lifecycle", {
			commercial_invoice: props.commercialInvoice,
		});
	} catch (_err) {
		sea.value = null;
	}
}

const seaDrifted = computed(() => !!sea.value && !sea.value.in_sync);
const seaAhead = computed(() => (sea.value ? sea.value.ahead : 0));

async function syncContainers() {
	const plan = await call("stabler.api.imports.sync_containers_to_ci", {
		commercial_invoice: props.commercialInvoice,
		dry_run: 1,
	});
	if (!plan.planned.length) {
		toast.info(t("No container is behind the invoice."));
		return;
	}
	const ok = await confirm({
		title: t("Advance containers to the invoice status"),
		body: t("{count} container(s) will move to {status}.")
			.replace("{count}", plan.planned.length)
			.replace("{status}", t(plan.ci_status)),
		confirmLabel: t("Confirm"),
	});
	if (!ok) return;
	syncing.value = true;
	try {
		const res = await call("stabler.api.imports.sync_containers_to_ci", {
			commercial_invoice: props.commercialInvoice,
			dry_run: 0,
		});
		if (res.failed.length) {
			toast.error(
				t("{count} container(s) could not be advanced.").replace("{count}", res.failed.length)
			);
		} else {
			toast.success(t("Containers advanced."));
		}
		await loadSea();
		emit("reload");
	} catch (err) {
		toast.error(err?.message || t("Containers could not be advanced."));
	} finally {
		syncing.value = false;
	}
}

onMounted(loadSea);
watch(() => props.commercialInvoice, loadSea);

const statusClass = computed(() => {
	if (props.packingSummary.status === "Ready") return "bg-success-lt text-success";
	if (props.packingSummary.status === "Mismatch") return "bg-warning-lt text-warning";
	return "bg-secondary-lt text-secondary";
});
const canRefreshExpected = computed(
	() =>
		Boolean(props.grn?.name) &&
		Number(props.grn.docstatus) === 0 &&
		!props.grn.expected_snapshot_locked
);

const formatKg = (value) =>
	new Intl.NumberFormat(undefined, {
		minimumFractionDigits: 2,
		maximumFractionDigits: 2,
	}).format(Number(value) || 0);

function openGrn(name) {
	return router.push(`/imports/grn-checklists/${encodeURIComponent(name)}`);
}

async function createOrOpenGrn() {
	if (!props.commercialInvoice) {
		actionError.value = t("Commercial invoice is unavailable. Reload and try again.");
		toast.error(actionError.value);
		return;
	}
	if (props.grn?.name) return openGrn(props.grn.name);
	actionError.value = "";
	busy.value = true;
	try {
		const result = await importsApi.createGrnForCi(props.commercialInvoice);
		emit("reload");
		return openGrn(result.name);
	} catch (error) {
		actionError.value = error?.message || t("Could not create the GRN.");
		toast.error(actionError.value);
	} finally {
		busy.value = false;
	}
}

async function refreshExpected() {
	if (!canRefreshExpected.value) return;
	actionError.value = "";
	busy.value = true;
	try {
		await importsApi.refreshGrnExpectedQuantities(props.grn.name);
		toast.success(t("Expected quantities refreshed from container packing lists."));
		emit("reload");
	} catch (error) {
		actionError.value = error?.message || t("Could not refresh expected quantities.");
		toast.error(actionError.value);
	} finally {
		busy.value = false;
	}
}
</script>

<template>
	<div class="card mb-3">
		<div class="card-header d-flex align-items-center flex-wrap gap-2">
			<h3 class="card-title mb-0">
				<i class="ti ti-package me-2"></i>{{ t("Logistics readiness") }}
			</h3>
			<span class="badge" :class="statusClass">{{ t(packingSummary.status) }}</span>
			<span v-if="grn?.expected_snapshot_locked" class="badge bg-secondary-lt text-secondary">
				<i class="ti ti-lock me-1"></i>{{ t("Expected quantities locked") }}
			</span>
			<div class="ms-auto d-flex gap-2 flex-wrap">
				<button
					v-if="canRefreshExpected"
					type="button"
					class="btn btn-outline-primary btn-sm"
					:disabled="busy || loading || !commercialInvoice"
					@click="refreshExpected"
				>
					<span v-if="busy" class="spinner-border spinner-border-sm me-1"></span>
					{{ t("Refresh expected quantities") }}
				</button>
				<button
					type="button"
					class="btn btn-primary btn-sm"
					:disabled="busy || loading || !commercialInvoice"
					@click="createOrOpenGrn"
				>
					<span v-if="busy && !grn" class="spinner-border spinner-border-sm me-1"></span>
					<i v-else class="ti me-1" :class="grn ? 'ti-external-link' : 'ti-plus'"></i>
					{{ grn ? t("Open GRN") : t("Create GRN") }}
				</button>
			</div>
		</div>

		<div v-if="loading" class="card-body text-center text-secondary py-4">
			<span class="spinner-border spinner-border-sm me-2"></span>{{ t("Loading logistics readiness…") }}
		</div>
		<div v-else class="card-body">
			<div v-if="actionError" class="alert alert-danger mb-3" role="alert">{{ actionError }}</div>
			<p class="text-secondary mb-3">
				{{ t("{ready} of {total} containers have packing-list rows.", {
					ready: packingSummary.containers_with_items,
					total: packingSummary.container_count,
				}) }}
			</p>
			<div v-if="seaDrifted" class="alert alert-warning">
				<div class="d-flex align-items-start flex-wrap gap-2">
					<div class="flex-fill">
						<div class="fw-semibold">
							<i class="ti ti-ship me-1"></i>{{ t("Containers do not match the invoice voyage status.") }}
						</div>
						<div class="small mt-1">
							{{ t("Invoice") }}: <span class="fw-semibold">{{ t(sea.ci_status) }}</span>
							· {{ t("{count} behind", { count: sea.behind }) }}
							<span v-if="seaAhead"> · {{ t("{count} ahead", { count: seaAhead }) }}</span>
						</div>
						<ul class="small mb-0 mt-1 ps-3">
							<li v-for="r in sea.rows.filter((x) => x.state === 'behind' || x.state === 'ahead')" :key="r.name">
								<span class="font-monospace">{{ r.container_number || r.name }}</span>
								— {{ t(r.status) }}
								<span v-if="r.state === 'ahead'" class="text-danger">({{ t("ahead of the invoice") }})</span>
							</li>
						</ul>
					</div>
					<button
						v-if="sea.behind"
						type="button"
						class="btn btn-outline-primary btn-sm"
						:disabled="syncing"
						@click="syncContainers"
					>
						<span v-if="syncing" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Advance containers") }}
					</button>
				</div>
				<div v-if="seaAhead" class="small text-secondary mt-2">
					{{ t("A container ahead of its invoice is not corrected automatically — fix it on the container.") }}
				</div>
			</div>

			<div v-if="packingSummary.status === 'Incomplete'" class="alert alert-warning">
				{{ t("Complete every container packing list before port-transfer readiness.") }}
			</div>
			<div v-else-if="packingSummary.status === 'Mismatch'" class="alert alert-warning">
				{{ t("Resolve CI versus packed quantity differences before port-transfer readiness.") }}
			</div>
			<div v-else-if="packingSummary.status === 'Ready'" class="alert alert-success">
				{{ t("Packing quantities are reconciled and ready for port transfer.") }}
			</div>
			<div v-else-if="packingSummary.status === 'Unavailable'" class="alert alert-warning">
				{{ t("Packing readiness could not be calculated — you may not have access to every container on this invoice.") }}
			</div>
			<div v-if="grn?.expected_snapshot_locked" class="text-secondary small mb-3">
				{{ t("The GRN expected snapshot is locked because receiving has started.") }}
			</div>

			<div class="table-responsive">
				<table class="table table-vcenter mb-0">
					<thead>
						<tr>
							<th>{{ t("Item") }}</th>
							<th class="text-end">{{ t("CI kg") }}</th>
							<th class="text-end">{{ t("Packed kg") }}</th>
							<th class="text-end">{{ t("Difference kg") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="row in packingSummary.reconciliation" :key="row.item_code">
							<td class="font-monospace fw-semibold">{{ row.item_code }}</td>
							<td class="text-end font-monospace">{{ formatKg(row.ci_kg) }}</td>
							<td class="text-end font-monospace">{{ formatKg(row.packed_kg) }}</td>
							<td
								class="text-end font-monospace fw-semibold"
								:class="row.matches ? 'text-success' : 'text-danger'"
							>
								{{ formatKg(row.difference_kg) }}
							</td>
						</tr>
						<tr v-if="!packingSummary.reconciliation.length">
							<td colspan="4" class="text-secondary text-center py-3">
								{{ t("No packing-list items yet.") }}
							</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>
	</div>
</template>
