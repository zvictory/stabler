<script setup>
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { importsApi } from "../../api/imports.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";

const props = defineProps({
	commercialInvoice: { type: String, required: true },
	packingSummary: { type: Object, required: true },
	grn: { type: Object, default: null },
	loading: { type: Boolean, default: false },
});
const emit = defineEmits(["reload"]);
const router = useRouter();
const toast = useToast();
const busy = ref(false);
const actionError = ref("");

const statusClass = computed(() => {
	if (props.packingSummary.status === "Ready") return "bg-success-lt text-success";
	if (props.packingSummary.status === "Mismatch") return "bg-warning-lt text-warning";
	return "bg-secondary-lt text-secondary";
});

const formatKg = (value) =>
	new Intl.NumberFormat(undefined, {
		minimumFractionDigits: 2,
		maximumFractionDigits: 2,
	}).format(Number(value) || 0);

function openGrn(name) {
	return router.push(`/imports/grn-checklists/${encodeURIComponent(name)}`);
}

async function createOrOpenGrn() {
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
	if (!props.grn?.name || props.grn.expected_snapshot_locked) return;
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
					v-if="grn && !grn.expected_snapshot_locked"
					type="button"
					class="btn btn-outline-primary btn-sm"
					:disabled="busy || loading"
					@click="refreshExpected"
				>
					<span v-if="busy" class="spinner-border spinner-border-sm me-1"></span>
					{{ t("Refresh expected quantities") }}
				</button>
				<button
					type="button"
					class="btn btn-primary btn-sm"
					:disabled="busy || loading"
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
			<div v-if="packingSummary.status === 'Incomplete'" class="alert alert-warning">
				{{ t("Complete every container packing list before port-transfer readiness.") }}
			</div>
			<div v-else-if="packingSummary.status === 'Mismatch'" class="alert alert-warning">
				{{ t("Resolve CI versus packed quantity differences before port-transfer readiness.") }}
			</div>
			<div v-else-if="packingSummary.status === 'Ready'" class="alert alert-success">
				{{ t("Packing quantities are reconciled and ready for port transfer.") }}
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
