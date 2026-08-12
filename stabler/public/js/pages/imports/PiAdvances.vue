<script setup>
import { ref, onMounted, computed, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { useToast } from "../../composables/useToast.js";
import ListToolbar from "../../components/ListToolbar.vue";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import Select from "../../components/Select.vue";
import PiAdvanceLedger from "../../components/PiAdvanceLedger.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const toast = useToast();

const rows = ref([]);
const loading = ref(false);
const loadError = ref("");
const search = ref("");
const scopeFilter = ref("open");
const supplierFilter = ref("");

// The backend cuts the *filtered* rows at this count. Hitting it means the list
// is incomplete — and because it orders newest-first, the rows dropped are the
// oldest, i.e. the advances that have sat unconsumed the longest. Say so.
const LIST_LIMIT = 200;
const truncated = computed(() => rows.value.length >= LIST_LIMIT);

const SCOPES = [
	{ value: "open", label: t("Open advances") },
	{ value: "all", label: t("All") },
];

const suppliers = ref([]);
const supplierOptions = computed(() => [
	{ value: "", label: t("All suppliers") },
	...suppliers.value.map((s) => ({ value: s.name, label: s.supplier_name || s.name })),
]);

async function loadSuppliers() {
	if (!activeCompany.value) return;
	try {
		suppliers.value = await call("stabler.api.imports.import_suppliers", {
			company: activeCompany.value,
		});
	} catch (_err) {
		suppliers.value = [];
	}
}

const expanded = ref(new Set());

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	loadError.value = "";
	try {
		rows.value = await call("stabler.api.imports.list_pi_advances", {
			company: activeCompany.value,
			scope: scopeFilter.value,
			supplier: supplierFilter.value || undefined,
			search: search.value || undefined,
			limit: LIST_LIMIT,
		});
	} catch (err) {
		// A permission error must never look like "this company has no advances".
		// Keep the thrown reason on screen, not only in a toast that fades.
		loadError.value = err?.message || t("Failed to load PI advances.");
		toast.error(loadError.value);
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

onMounted(() => {
	loadSuppliers();
	load();
});

// setCompany() mutates activeCompany in place without navigating, so without
// this the table keeps showing the previous company's advance balances.
watch(activeCompany, () => {
	supplierFilter.value = "";
	loadSuppliers();
	load();
});

const fm = (v, ccy) => formatMoney(v, ccy || "", user.value.language);

function toggleRow(name) {
	if (expanded.value.has(name)) {
		expanded.value.delete(name);
	} else {
		expanded.value.add(name);
	}
}
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('PI no or supplier') + ' ⌘K'"
			:count="rows.length"
			@search="load"
		>
			<template #filters>
				<Select
					v-model="supplierFilter"
					size="sm"
					style="width: 200px"
					:options="supplierOptions"
					value-key="value"
					label-key="label"
					@change="load"
				/>
				<Select
					v-model="scopeFilter"
					size="sm"
					style="width: 180px"
					:options="SCOPES"
					value-key="value"
					label-key="label"
					@change="load"
				/>
			</template>
		</ListToolbar>

		<div class="table-responsive">
			<table class="table table-vcenter table-hover">
				<thead>
					<tr>
						<th style="width: 1%"></th>
						<th>{{ t("PI") }}</th>
						<th>{{ t("Supplier") }}</th>
						<th class="text-nowrap">{{ t("Date") }}</th>
						<th>{{ t("Status") }}</th>
						<th class="text-end text-nowrap">{{ t("PI Total Cost") }}</th>
						<th class="text-end text-nowrap">{{ t("Advance %") }}</th>
						<th class="text-end text-nowrap">{{ t("Advance Paid") }}</th>
						<th class="text-end text-nowrap">{{ t("Pending Approval") }}</th>
						<th class="text-end text-nowrap">{{ t("Allocated") }}</th>
						<th class="text-end text-nowrap">{{ t("Reserved") }}</th>
						<th class="text-end text-nowrap">{{ t("Free Advance Balance") }}</th>
						<th class="text-end text-nowrap">{{ t("Remaining PI Cost") }}</th>
					</tr>
				</thead>
				<tbody>
					<SkeletonRows v-if="loading" :cols="13" :rows="6" />
					<template v-for="r in rows" :key="r.proforma_invoice">
						<tr
							style="cursor: pointer"
							:aria-expanded="expanded.has(r.proforma_invoice)"
							@click="toggleRow(r.proforma_invoice)"
						>
							<td class="text-muted">
								<i
									class="ti"
									:class="expanded.has(r.proforma_invoice) ? 'ti-chevron-down' : 'ti-chevron-right'"
								></i>
							</td>
							<td class="font-monospace text-nowrap">
								<router-link :to="'/imports/proformas/' + r.proforma_invoice" @click.stop>
									{{ r.supplier_pi_ref || r.proforma_invoice }}
								</router-link>
							</td>
							<td class="text-nowrap">{{ r.supplier_name || r.supplier }}</td>
							<td class="text-nowrap font-monospace">
								{{ r.pi_date ? formatDate(r.pi_date) : "—" }}
							</td>
							<td>
								<span class="badge" :class="getStatusBadgeClass('Proforma Invoice', r.status)">{{
									r.status
								}}</span>
							</td>
							<td class="text-end font-monospace">{{ fm(r.summary.pi_total_cost, r.currency) }}</td>
							<td class="text-end font-monospace">{{ r.summary.advance_percentage }}%</td>
							<td class="text-end font-monospace">{{ fm(r.summary.advance_paid, r.currency) }}</td>
							<td class="text-end font-monospace">
								{{ fm(r.summary.advance_pending_approval, r.currency) }}
							</td>
							<td class="text-end font-monospace">
								{{ fm(r.summary.advance_allocated, r.currency) }}
							</td>
							<td class="text-end font-monospace">
								{{ fm(r.summary.advance_reserved, r.currency) }}
							</td>
							<td class="text-end font-monospace fw-bold">
								{{ fm(r.summary.advance_available, r.currency) }}
							</td>
							<td class="text-end font-monospace">
								{{ fm(r.summary.remaining_pi_cost, r.currency) }}
							</td>
						</tr>
						<tr v-if="expanded.has(r.proforma_invoice)">
							<td colspan="13" class="p-0 border-bottom-0 bg-light">
								<PiAdvanceLedger :ledger="r" />
							</td>
						</tr>
					</template>
				</tbody>
			</table>
			<EmptyState
				v-if="!loading && loadError"
				icon="ti-lock"
				tone="danger"
				:title="t('Cannot show PI advances')"
				:subtitle="loadError"
			/>
			<EmptyState
				v-else-if="!loading && !rows.length"
				icon="ti-cash"
				:title="t('No PI advances found.')"
			/>
			<div v-if="!loading && truncated" class="alert alert-warning m-3 mb-0 py-2">
				{{
					t("Showing the first {count} advances — narrow the filter to see the rest.", {
						count: LIST_LIMIT,
					})
				}}
			</div>
		</div>
	</div>
</template>
