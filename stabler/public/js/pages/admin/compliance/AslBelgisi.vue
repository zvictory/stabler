<script setup>
import { computed, onMounted, ref } from "vue";
import { call } from "../../../api/client.js";
import { t } from "../../../composables/i18n.js";
import { formatDateTime } from "../../../composables/date.js";

const stockEntries = ref([]);
const loading = ref(false);
const error = ref("");

const selectedEntry = ref(null);
const rows = ref([]);
const rowsLoading = ref(false);
const scanCode = ref("");
const activeRow = ref(null);
const scanning = ref(false);
const toast = ref(null);

function progressBadge(scanned, required) {
	if (!required) return "bg-secondary";
	if (scanned >= required) return "bg-success";
	if (scanned === 0) return "bg-danger";
	return "bg-warning";
}

async function loadEntries() {
	loading.value = true;
	error.value = "";
	try {
		const data = await call("stabler.api.compliance.list_asl_stock_entries", { limit: 100 });
		stockEntries.value = Array.isArray(data) ? data : [];
	} catch (e) {
		error.value = e?.message || String(e);
	} finally {
		loading.value = false;
	}
}

async function openEntry(name) {
	selectedEntry.value = name;
	rowsLoading.value = true;
	rows.value = [];
	activeRow.value = null;
	scanCode.value = "";
	toast.value = null;
	try {
		rows.value = await call("stabler.api.compliance.get_asl_stock_entry_rows", {
			stock_entry: name,
		});
	} catch (e) {
		error.value = e?.message || String(e);
	} finally {
		rowsLoading.value = false;
	}
}

function closeEntry() {
	selectedEntry.value = null;
	rows.value = [];
	activeRow.value = null;
	scanCode.value = "";
	toast.value = null;
}

function selectRow(row) {
	activeRow.value = row;
	scanCode.value = row.asl_belgisi_code || "";
	toast.value = null;
}

async function submitScan() {
	if (!activeRow.value || !scanCode.value.trim()) return;
	scanning.value = true;
	toast.value = null;
	try {
		const result = await call("stabler.api.compliance.scan_asl_code", {
			parent: selectedEntry.value,
			row_name: activeRow.value.row_name,
			code: scanCode.value.trim(),
		});
		toast.value = result;
		if (result.ok) {
			activeRow.value.asl_belgisi_code = scanCode.value.trim();
			await loadEntries();
		}
	} catch (e) {
		toast.value = { ok: false, message: e?.message || String(e) };
	} finally {
		scanning.value = false;
	}
}

const scannedCount = computed(
	() => rows.value.filter((r) => (r.asl_belgisi_code || "").length > 0).length,
);

onMounted(loadEntries);
</script>

<template>
	<div class="card">
		<div class="card-header d-flex align-items-center gap-3">
			<h3 class="card-title mb-0">{{ t("Asl Belgisi — Stock Entries pending scan") }}</h3>
			<button type="button" class="btn btn-sm btn-outline-secondary ms-auto" @click="loadEntries">
				<i class="ti ti-refresh me-1"></i>{{ t("Reload") }}
			</button>
		</div>
		<div class="card-body">
			<div v-if="error" class="alert alert-danger">{{ error }}</div>
			<div v-if="loading && !stockEntries.length" class="text-secondary">{{ t("Loading…") }}</div>
			<div v-else-if="!stockEntries.length" class="text-secondary">
				{{ t("No Stock Entries with Asl Belgisi items found.") }}
			</div>
			<div v-else class="table-responsive">
				<table class="table table-vcenter table-hover">
					<thead>
						<tr>
							<th>{{ t("Stock Entry") }}</th>
							<th>{{ t("Type") }}</th>
							<th>{{ t("Posting Date") }}</th>
							<th class="text-end">{{ t("Scanned / Required") }}</th>
							<th>{{ t("Status") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="entry in stockEntries"
							:key="entry.stock_entry"
							style="cursor: pointer"
							@click="openEntry(entry.stock_entry)"
						>
							<td>{{ entry.stock_entry }}</td>
							<td>{{ entry.stock_entry_type }}</td>
							<td>{{ formatDateTime(entry.posting_date) }}</td>
							<td class="text-end">{{ entry.scanned }} / {{ entry.required }}</td>
							<td>
								<span :class="['badge', progressBadge(entry.scanned, entry.required)]">
									{{ entry.scanned >= entry.required ? t("Complete") : t("Pending") }}
								</span>
							</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<div v-if="selectedEntry" class="offcanvas offcanvas-end show" style="visibility: visible; width: 560px" tabindex="-1">
			<div class="offcanvas-header">
				<h5 class="offcanvas-title">{{ selectedEntry }}</h5>
				<button type="button" class="btn-close" @click="closeEntry"></button>
			</div>
			<div class="offcanvas-body">
				<div v-if="rowsLoading" class="text-secondary">{{ t("Loading…") }}</div>
				<template v-else>
					<div class="mb-3 text-secondary">
						{{ t("Scanned") }}: {{ scannedCount }} / {{ rows.length }}
					</div>
					<table class="table table-vcenter table-sm">
						<thead>
							<tr>
								<th>{{ t("Item") }}</th>
								<th class="text-end">{{ t("Qty") }}</th>
								<th>{{ t("Asl Belgisi Code") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr
								v-for="row in rows"
								:key="row.row_name"
								style="cursor: pointer"
								:class="{ 'table-active': activeRow && activeRow.row_name === row.row_name }"
								@click="selectRow(row)"
							>
								<td>
									<div>{{ row.item_code }}</div>
									<small class="text-secondary">{{ row.item_name }}</small>
								</td>
								<td class="text-end">{{ row.qty }}</td>
								<td>
									<small v-if="row.asl_belgisi_code" class="text-success">
										{{ row.asl_belgisi_code }}
									</small>
									<small v-else class="text-secondary">—</small>
								</td>
							</tr>
						</tbody>
					</table>
					<div v-if="activeRow" class="mt-3">
						<label class="form-label">{{ t("Scan code for") }} {{ activeRow.item_code }}</label>
						<div class="input-group">
							<input
								v-model="scanCode"
								type="text"
								class="form-control"
								:placeholder="t('Scan or type code')"
								@keyup.enter="submitScan"
							/>
							<button type="button" class="btn btn-primary" :disabled="scanning" @click="submitScan">
								{{ scanning ? t("Scanning…") : t("Submit") }}
							</button>
						</div>
						<div
							v-if="toast"
							:class="['alert', 'mt-3', toast.ok ? 'alert-success' : 'alert-danger']"
						>
							{{ toast.message }}
						</div>
					</div>
				</template>
			</div>
		</div>
	</div>
</template>
