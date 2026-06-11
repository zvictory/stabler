<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);

const formatQty = (n, uom) => {
	const v = Number(n || 0);
	return `${v.toLocaleString(session.user?.language || "en", { maximumFractionDigits: 3 })} ${uom || ""}`.trim();
};

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const search = ref("");

// ----- Load Work Orders -----
async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		// Fetch submitted and in-process work orders
		const allWos = await call("stabler.api.manufacturing.list_work_orders", {
			company: activeCompany.value,
			limit: 150,
		});
		// Filter by docstatus === 1 (Submitted) and status in ('Submitted', 'In Process')
		rows.value = (allWos || []).filter(
			(r) => r.docstatus === 1 && ["Submitted", "In Process", "Not Started"].includes(r.status)
		);
	} catch (err) {
		error.value = err?.message || t("Failed to load staging queue.");
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);

// ----- Filtered Rows -----
const filteredRows = computed(() => {
	const query = search.value.trim().toLowerCase();
	if (!query) return rows.value;
	return rows.value.filter(
		(r) =>
			(r.name || "").toLowerCase().includes(query) ||
			(r.production_item || "").toLowerCase().includes(query) ||
			(r.item_name || "").toLowerCase().includes(query) ||
			(r.wip_warehouse || "").toLowerCase().includes(query)
	);
});

// ----- Drawer / Details State -----
const drawerOpen = ref(false);
const drawerLoading = ref(false);
const detail = ref(null);
const actionBusy = ref(false);
const actionError = ref("");
const actionSuccess = ref("");

async function openDrawer(name) {
	drawerOpen.value = true;
	drawerLoading.value = true;
	detail.value = null;
	actionError.value = "";
	actionSuccess.value = "";
	try {
		detail.value = await call("stabler.api.manufacturing.work_order_detail", { name });
	} catch (err) {
		detail.value = { error: err?.message || t("Failed to load details.") };
	} finally {
		drawerLoading.value = false;
	}
}

function closeDrawer() {
	drawerOpen.value = false;
	detail.value = null;
}

// ----- Transfer Action -----
async function executeTransfer() {
	const row = detail.value;
	if (!row) return;
	
	if (!confirm(t("Execute material transfer for this Work Order? This will move required raw materials to the WIP warehouse."))) {
		return;
	}

	actionBusy.value = true;
	actionError.value = "";
	actionSuccess.value = "";
	try {
		await call("stabler.api.manufacturing.make_work_order_stock_entry", {
			work_order: row.name,
			purpose: "Material Transfer for Manufacture",
		});
		actionSuccess.value = t("Materials transferred successfully!");
		await load();
		// Reload detail to update transferred quantities
		detail.value = await call("stabler.api.manufacturing.work_order_detail", { name: row.name });
	} catch (err) {
		actionError.value = err?.message || t("Transfer failed.");
	} finally {
		actionBusy.value = false;
	}
}

// Check if there are items left to transfer
const needsStaging = (row) => {
	if (!row.required_items) return false;
	return row.required_items.some((it) => (Number(it.required_qty) || 0) > (Number(it.transferred_qty) || 0));
};

const statusBadge = (s) => {
	switch (s) {
		case "In Process":
			return "bg-blue-lt";
		case "Not Started":
		case "Submitted":
			return "bg-yellow-lt";
		default:
			return "bg-secondary-lt";
	}
};
</script>

<template>
	<div>
		<div class="card mb-3">
			<div class="card-body">
				<div class="row g-2 align-items-center">
					<div class="col-md-6">
						<div class="input-icon">
							<span class="input-icon-addon"><i class="ti ti-search"></i></span>
							<input
								v-model="search"
								type="search"
								class="form-control"
								:placeholder="t('Search by Work Order, Item, or Warehouse…')"
							/>
						</div>
					</div>
					<div class="col-md-6 d-flex justify-content-md-end gap-2">
						<button type="button" class="btn btn-ghost-secondary" @click="load" :disabled="loading">
							<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
						</button>
					</div>
				</div>
			</div>
		</div>

		<div v-if="error" class="alert alert-danger">{{ error }}</div>

		<div v-if="loading && !rows.length" class="text-center py-5">
			<div class="spinner-border text-primary"></div>
		</div>

		<EmptyState
			v-else-if="!error && !filteredRows.length"
			icon="ti-transfer"
			tone="secondary"
			:title="t('No materials to stage')"
			:subtitle="t('All current production runs are fully staged or inactive.')"
		/>

		<div v-else class="card">
			<div class="table-responsive">
				<table class="table table-vcenter card-table table-hover">
					<thead>
						<tr>
							<th>{{ t("Work Order") }}</th>
							<th>{{ t("Finished Good") }}</th>
							<th>{{ t("WIP Warehouse") }}</th>
							<th>{{ t("Operator") }}</th>
							<th>{{ t("Status") }}</th>
							<th class="text-end">{{ t("Action") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="r in filteredRows" :key="r.name" class="cursor-pointer" @click="openDrawer(r.name)">
							<td>
								<div class="font-monospace small fw-bold text-dark">{{ r.name }}</div>
							</td>
							<td>
								<div class="fw-semibold">{{ r.item_name || r.production_item }}</div>
								<div class="small text-secondary font-monospace">{{ r.production_item }}</div>
							</td>
							<td>
								<div class="small text-secondary">{{ r.wip_warehouse || "—" }}</div>
							</td>
							<td class="small text-secondary">{{ r.operator || "—" }}</td>
							<td><span class="badge" :class="statusBadge(r.status)">{{ r.status }}</span></td>
							<td class="text-end" @click.stop>
								<button
									type="button"
									class="btn btn-sm btn-primary"
									@click="openDrawer(r.name)"
								>
									<i class="ti ti-transfer me-1"></i>{{ t("Stage Materials") }}
								</button>
							</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<!-- Material Staging Drawer -->
		<div v-if="drawerOpen" class="offcanvas-backdrop fade show" @click="closeDrawer"></div>
		<div v-if="drawerOpen" class="offcanvas offcanvas-end show" tabindex="-1" style="visibility: visible; width: 680px;">
			<div class="offcanvas-header bg-light">
				<h5 class="offcanvas-title fw-bold">
					{{ t("Stage Materials") }} — <span class="font-monospace text-primary">{{ detail?.name }}</span>
				</h5>
				<button type="button" class="btn-close" @click="closeDrawer"></button>
			</div>
			<div class="offcanvas-body">
				<div v-if="drawerLoading" class="text-center py-5">
					<div class="spinner-border text-primary"></div>
				</div>
				<div v-else-if="detail?.error" class="alert alert-danger">{{ detail.error }}</div>
				<template v-else-if="detail">
					<div v-if="actionError" class="alert alert-danger border-0 shadow-sm mb-3">{{ actionError }}</div>
					<div v-if="actionSuccess" class="alert alert-success border-0 shadow-sm mb-3">{{ actionSuccess }}</div>

					<div class="row g-3 mb-4">
						<div class="col-md-6">
							<div class="text-secondary small">{{ t("Production Item") }}</div>
							<div class="fw-bold fs-4 text-dark">{{ detail.item_name || detail.production_item }}</div>
							<div class="small text-muted font-monospace">{{ detail.production_item }}</div>
						</div>
						<div class="col-md-6 text-md-end">
							<div class="text-secondary small">{{ t("Target WIP Warehouse") }}</div>
							<div class="fw-bold text-dark fs-4">{{ detail.wip_warehouse || "—" }}</div>
						</div>
					</div>

					<div class="row g-2 mb-4 bg-light p-3 rounded">
						<div class="col-4 text-center">
							<div class="text-secondary small">{{ t("Planned Qty") }}</div>
							<div class="fw-bold fs-4">{{ formatQty(detail.qty) }}</div>
						</div>
						<div class="col-4 text-center border-start">
							<div class="text-secondary small">{{ t("Transferred Qty") }}</div>
							<div class="fw-bold fs-4 text-blue">{{ formatQty(detail.transferred_qty) }}</div>
						</div>
						<div class="col-4 text-center border-start">
							<div class="text-secondary small">{{ t("Produced Qty") }}</div>
							<div class="fw-bold fs-4 text-success">{{ formatQty(detail.produced_qty) }}</div>
						</div>
					</div>

					<h6 class="text-uppercase small text-secondary fw-bold mb-3">{{ t("Required Items to Transfer") }}</h6>
					<div class="table-responsive mb-4">
						<table class="table table-sm table-vcenter">
							<thead>
								<tr>
									<th>{{ t("Item") }}</th>
									<th class="text-end">{{ t("Total Required") }}</th>
									<th class="text-end">{{ t("Already Transferred") }}</th>
									<th class="text-end text-primary">{{ t("Remaining Staging") }}</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="(it, i) in detail.required_items" :key="i">
									<td>
										<div class="fw-semibold text-dark">{{ it.item_name || it.item_code }}</div>
										<div class="small text-secondary font-monospace">{{ it.item_code }}</div>
									</td>
									<td class="text-end font-monospace">{{ formatQty(it.required_qty) }}</td>
									<td class="text-end font-monospace text-secondary">{{ formatQty(it.transferred_qty) }}</td>
									<td class="text-end font-monospace text-primary fw-bold">
										{{ formatQty(Math.max(0, (Number(it.required_qty) || 0) - (Number(it.transferred_qty) || 0))) }}
									</td>
								</tr>
							</tbody>
						</table>
					</div>

					<!-- Staging Action Buttons -->
					<div class="d-flex justify-content-end gap-2 mt-4 pt-3 border-top">
						<button type="button" class="btn btn-link link-secondary" @click="closeDrawer">
							{{ t("Close") }}
						</button>
						<button
							type="button"
							class="btn btn-primary px-4"
							:disabled="actionBusy || !needsStaging(detail)"
							@click="executeTransfer"
						>
							<i class="ti ti-transfer me-1"></i>
							<span v-if="!needsStaging(detail)">{{ t("Fully Staged") }}</span>
							<span v-else>{{ t("Transfer to WIP Warehouse") }}</span>
						</button>
					</div>
				</template>
			</div>
		</div>
	</div>
</template>
