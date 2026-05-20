<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const rows = ref([]);

const formatQty = (n, uom) => {
	const v = Number(n || 0);
	return `${v.toLocaleString(user.value.language || "en", { maximumFractionDigits: 3 })} ${uom || ""}`.trim();
};

const severity = (row) => {
	const projected = Number(row.projected_qty || 0);
	const reorder = Number(row.reorder_level || 0);
	if (projected <= 0) return { cls: "bg-red-lt text-red", label: "Out of stock" };
	if (reorder > 0 && projected / reorder < 0.5) return { cls: "bg-orange-lt text-orange", label: "Critical" };
	return { cls: "bg-yellow-lt text-yellow", label: "Low" };
};

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.inventory.low_stock_alerts", {
			company: activeCompany.value,
			limit: 50,
		});
	} catch (err) {
		error.value = err?.message || "Failed to load alerts.";
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);
</script>

<template>
	<div class="card">
		<div class="card-header">
			<div class="card-title d-flex align-items-center gap-2">
				<i class="ti ti-alert-triangle text-orange"></i>
				Low Stock Alerts
			</div>
			<button type="button" class="btn btn-sm btn-ghost-secondary ms-auto" @click="load">
				<i class="ti ti-refresh me-1"></i>Refresh
			</button>
		</div>
		<div v-if="loading" class="card-body text-center py-5">
			<div class="spinner-border text-primary"></div>
		</div>
		<div v-else-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-check"
			accentIcon="ti-thumb-up"
			tone="success"
			title="No low-stock items"
			subtitle="All items are above their warehouse reorder thresholds — nice work."
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th class="w-1">Status</th>
						<th>Item</th>
						<th>Warehouse</th>
						<th class="text-end">On hand</th>
						<th class="text-end">Projected</th>
						<th class="text-end">Reorder at</th>
						<th class="text-end">Reorder qty</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="`${r.item_code}::${r.warehouse}`">
						<td><span class="badge" :class="severity(r).cls">{{ severity(r).label }}</span></td>
						<td>
							<div class="fw-semibold">{{ r.item_name || r.item_code }}</div>
							<div class="small text-secondary font-monospace">{{ r.item_code }}</div>
						</td>
						<td class="small">{{ r.warehouse }}</td>
						<td class="text-end font-monospace">{{ formatQty(r.actual_qty, r.stock_uom) }}</td>
						<td
							class="text-end font-monospace fw-semibold"
							:class="Number(r.projected_qty) <= 0 ? 'text-red' : 'text-orange'"
						>
							{{ formatQty(r.projected_qty, r.stock_uom) }}
						</td>
						<td class="text-end font-monospace text-secondary">{{ formatQty(r.reorder_level, r.stock_uom) }}</td>
						<td class="text-end font-monospace text-blue">{{ formatQty(r.reorder_qty, r.stock_uom) }}</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>
