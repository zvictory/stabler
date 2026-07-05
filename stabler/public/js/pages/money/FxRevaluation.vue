<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, todayIso } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { getStatusBadgeClass, getDocstatusLabel } from "../../composables/status.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useToast } from "../../composables/useToast.js";
import EmptyState from "../../components/EmptyState.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import DateInput from "../../components/DateInput.vue";
import { useEscapeBack } from "../../composables/useEscapeBack.js";

const session = useSession();
useEscapeBack(() => { if (detailOpen.value) { closeDetail(); return true; } return false; }, "/money"); // ESC → close open pane, else back
const { activeCompany, language } = storeToRefs(session);
const { confirm } = useConfirm();
const toast = useToast();

const lang = computed(() => language.value || "en");

// ── List state ───────────────────────────────────────────────────────────────
const loading = ref(false);
const error = ref("");
const search = ref("");
const rows = ref([]);
const fromDate = ref("");
const toDate = ref("");

// ── Detail drawer ────────────────────────────────────────────────────────────
const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);

// ── New-revaluation panel ────────────────────────────────────────────────────
const newPanelOpen = ref(false);
const newDate = ref(todayIso());
const previewLoading = ref(false);
const previewError = ref("");
const preview = ref(null);          // { accounts, base_currency, posting_date }
const submitting = ref(false);

// ── Helpers ──────────────────────────────────────────────────────────────────
const filteredRows = computed(() => {
	const q = search.value.trim().toLowerCase();
	if (!q) return rows.value;
	return rows.value.filter((r) =>
		[r.name, r.company, r.posting_date]
			.filter(Boolean)
			.some((v) => String(v).toLowerCase().includes(q)),
	);
});

// Net gain/loss from preview accounts
const netDelta = computed(() => {
	if (!preview.value?.accounts?.length) return 0;
	return preview.value.accounts.reduce((sum, a) => sum + (a.delta || 0), 0);
});

const netBaseCurrency = computed(() => preview.value?.base_currency || "");

// ── Load list ────────────────────────────────────────────────────────────────
async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const res = await call("stabler.api.fx_revaluation.list_fx_revaluations", {
			company: activeCompany.value,
			from_date: fromDate.value || undefined,
			to_date: toDate.value || undefined,
			limit: 200,
		});
		rows.value = Array.isArray(res) ? res : [];
	} catch (e) {
		error.value = e?.message || String(e);
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

// ── Open detail drawer ───────────────────────────────────────────────────────
async function openDetail(r) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	try {
		const res = await call("stabler.api.fx_revaluation.get_fx_revaluation", {
			name: r.name,
		});
		detail.value = res;
	} catch (e) {
		detail.value = { _error: e?.message || String(e) };
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	detailOpen.value = false;
	detail.value = null;
}

// ── New-revaluation panel ────────────────────────────────────────────────────
function openNewPanel() {
	newDate.value = todayIso();
	preview.value = null;
	previewError.value = "";
	newPanelOpen.value = true;
	loadPreview();
}

function closeNewPanel() {
	newPanelOpen.value = false;
	preview.value = null;
	previewError.value = "";
}

async function loadPreview() {
	if (!activeCompany.value) return;
	previewLoading.value = true;
	previewError.value = "";
	preview.value = null;
	try {
		const res = await call("stabler.api.fx_revaluation.list_fx_accounts", {
			company: activeCompany.value,
			posting_date: newDate.value || undefined,
		});
		preview.value = res;
	} catch (e) {
		previewError.value = e?.message || String(e);
	} finally {
		previewLoading.value = false;
	}
}

watch(newDate, () => {
	if (newPanelOpen.value) loadPreview();
});

async function createRevaluation(doSubmit) {
	const verb = doSubmit ? t("create and submit") : t("save as draft");
	const ok = await confirm({
		title: doSubmit ? t("Submit Revaluation") : t("Save Draft Revaluation"),
		body: t("This will {0} an Exchange Rate Revaluation for {1} on {2}. ERPNext will post the GL entries on submit.")
			.replace("{0}", verb)
			.replace("{1}", activeCompany.value)
			.replace("{2}", formatDate(newDate.value)),
		danger: false,
		confirmLabel: doSubmit ? t("Submit") : t("Save draft"),
	});
	if (!ok) return;

	submitting.value = true;
	try {
		const res = await call("stabler.api.fx_revaluation.create_fx_revaluation", {
			company: activeCompany.value,
			posting_date: newDate.value || undefined,
			submit: doSubmit ? 1 : 0,
		});
		toast.success(
			doSubmit
				? t("Revaluation submitted: {0}").replace("{0}", res.name)
				: t("Revaluation saved as draft: {0}").replace("{0}", res.name),
		);
		closeNewPanel();
		await load();
	} catch (e) {
		toast.error(e?.message || String(e));
	} finally {
		submitting.value = false;
	}
}

// ── Auto-apply filters ───────────────────────────────────────────────────────
watch(activeCompany, load);
watch(fromDate, load);
watch(toDate, load);
onMounted(load);
</script>

<template>
	<div class="card">
		<!-- List toolbar -->
		<ListToolbar
			v-model="search"
			:placeholder="t('Document or company…') + '  ⌘K'"
			:count="filteredRows.length"
			:primary-label="t('New Revaluation')"
			primary-icon="ti-plus"
			@primary-click="openNewPanel"
		>
			<template #filters>
				<div class="d-flex align-items-center gap-2 flex-wrap">
					<DateInput
						v-model="fromDate"
						size="sm"
						:placeholder="t('From date')"
						style="width: 160px"
					/>
					<DateInput
						v-model="toDate"
						size="sm"
						:placeholder="t('To date')"
						style="width: 160px"
					/>
				</div>
			</template>
		</ListToolbar>

		<div v-if="error" class="alert alert-danger m-3">{{ error }}</div>

		<!-- List table -->
		<div class="table-responsive">
			<table class="table card-table table-vcenter">
				<thead>
					<tr>
						<th>{{ t("Document") }}</th>
						<th>{{ t("Company") }}</th>
						<th>{{ t("Posting date") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="6" :cols="4" />
				<tbody v-else>
					<tr
						v-for="r in filteredRows"
						:key="r.name"
						style="cursor: pointer"
						@click="openDetail(r)"
					>
						<td class="fw-medium font-monospace">{{ r.name }}</td>
						<td>{{ r.company }}</td>
						<td>{{ formatDate(r.posting_date) }}</td>
						<td>
							<span class="badge" :class="getStatusBadgeClass('docstatus', r.docstatus)">
								{{ getDocstatusLabel(r.docstatus) }}
							</span>
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<EmptyState
			v-if="!loading && filteredRows.length === 0"
			icon="ti-currency-exchange"
			accent-icon="ti-plus"
			tone="primary"
			:title="t('No revaluations yet')"
			:subtitle="t('Click New Revaluation to preview unrealised FX deltas and post an Exchange Rate Revaluation.')"
		>
			<template #actions>
				<button class="btn btn-primary" @click="openNewPanel">
					<i class="ti ti-plus me-1"></i>{{ t("New Revaluation") }}
				</button>
			</template>
		</EmptyState>
	</div>

	<!-- ── Detail drawer ──────────────────────────────────────────────────── -->
	<div v-if="detailOpen" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div
		v-if="detailOpen"
		class="offcanvas offcanvas-end show"
		tabindex="-1"
		style="visibility: visible; width: 640px"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">
				<i class="ti ti-currency-exchange me-1"></i>{{ t("Exchange Rate Revaluation") }}
			</h5>
			<button type="button" class="btn-close" @click="closeDetail"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="detail?._error" class="alert alert-danger">{{ detail._error }}</div>
			<div v-else-if="detail">
				<!-- Header datagrid -->
				<div class="datagrid mb-4">
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Document") }}</div>
						<div class="datagrid-content font-monospace">{{ detail.name }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Company") }}</div>
						<div class="datagrid-content">{{ detail.company }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Posting date") }}</div>
						<div class="datagrid-content">{{ formatDate(detail.posting_date) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Status") }}</div>
						<div class="datagrid-content">
							<span class="badge" :class="getStatusBadgeClass('docstatus', detail.docstatus)">
								{{ getDocstatusLabel(detail.docstatus) }}
							</span>
						</div>
					</div>
				</div>

				<!-- Account rows child table -->
				<h6 class="text-uppercase text-secondary small mb-2">{{ t("Accounts") }}</h6>
				<div class="table-responsive">
					<table class="table table-sm table-vcenter">
						<thead>
							<tr>
								<th>{{ t("Account") }}</th>
								<th class="text-end">{{ t("Currency") }}</th>
								<th class="text-end">{{ t("Balance") }}</th>
								<th class="text-end">{{ t("New rate") }}</th>
								<th class="text-end">{{ t("Gain / Loss") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(a, i) in detail.accounts || []" :key="i">
								<td class="text-break small">{{ a.account }}</td>
								<td class="text-end font-monospace">{{ a.account_currency }}</td>
								<td class="text-end font-monospace">
									{{ formatMoney(a.balance_in_account_currency ?? a.balance_in_account_ccy, a.account_currency, lang) }}
								</td>
								<td class="text-end font-monospace small">
									{{ (a.new_exchange_rate ?? a.new_rate ?? 0).toFixed(6) }}
								</td>
								<td
									class="text-end font-monospace"
									:class="(a.gain_loss_amount ?? a.gain_loss ?? 0) >= 0 ? 'text-success' : 'text-danger'"
								>
									{{ formatMoney(a.gain_loss_amount ?? a.gain_loss ?? 0, detail.company_currency || netBaseCurrency, lang) }}
								</td>
							</tr>
							<tr v-if="!(detail.accounts || []).length">
								<td colspan="5" class="text-center text-secondary py-3">{{ t("No account rows") }}</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
		</div>
	</div>

	<!-- ── New Revaluation panel ──────────────────────────────────────────── -->
	<div v-if="newPanelOpen" class="offcanvas-backdrop fade show" @click="closeNewPanel"></div>
	<div
		v-if="newPanelOpen"
		class="offcanvas offcanvas-end show"
		tabindex="-1"
		style="visibility: visible; width: 720px"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">
				<i class="ti ti-currency-exchange me-1"></i>{{ t("New Exchange Rate Revaluation") }}
			</h5>
			<button type="button" class="btn-close" @click="closeNewPanel"></button>
		</div>
		<div class="offcanvas-body d-flex flex-column gap-3">
			<!-- Date picker row -->
			<div class="row g-2 align-items-end">
				<div class="col-auto">
					<label class="form-label mb-1">{{ t("Revaluation date") }}</label>
					<DateInput v-model="newDate" size="sm" style="width: 180px" />
				</div>
				<div class="col-auto">
					<button
						class="btn btn-sm btn-outline-secondary"
						:disabled="previewLoading"
						@click="loadPreview"
					>
						<i class="ti ti-refresh me-1"></i>{{ t("Refresh preview") }}
					</button>
				</div>
			</div>

			<!-- Preview content -->
			<div v-if="previewLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
				<div class="text-secondary small mt-2">{{ t("Loading FX account balances…") }}</div>
			</div>
			<div v-else-if="previewError" class="alert alert-danger">{{ previewError }}</div>
			<div v-else-if="preview">
				<h6 class="text-uppercase text-secondary small mb-2">
					{{ t("FX accounts as of {0}").replace("{0}", formatDate(preview.posting_date)) }}
				</h6>
				<div class="table-responsive">
					<table class="table table-sm table-vcenter">
						<thead>
							<tr>
								<th>{{ t("Account") }}</th>
								<th class="text-end">{{ t("Currency") }}</th>
								<th class="text-end">{{ t("Balance") }}</th>
								<th class="text-end">{{ t("Book rate") }}</th>
								<th class="text-end">{{ t("New rate") }}</th>
								<th class="text-end">{{ t("Rate diff") }}</th>
								<th class="text-end">{{ t("Delta") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(a, i) in preview.accounts" :key="i">
								<td class="text-break small">{{ a.account }}</td>
								<td class="text-end font-monospace">{{ a.account_currency }}</td>
								<td class="text-end font-monospace">
									{{ formatMoney(a.balance_in_account_ccy, a.account_currency, lang) }}
								</td>
								<td class="text-end font-monospace small">{{ (a.book_rate || 0).toFixed(6) }}</td>
								<td class="text-end font-monospace small">{{ (a.new_rate || 0).toFixed(6) }}</td>
								<td
									class="text-end font-monospace small"
									:class="(a.rate_diff || 0) >= 0 ? 'text-success' : 'text-danger'"
								>
									{{ (a.rate_diff || 0).toFixed(6) }}
								</td>
								<td
									class="text-end font-monospace fw-medium"
									:class="(a.delta || 0) >= 0 ? 'text-success' : 'text-danger'"
								>
									{{ formatMoney(a.delta, preview.base_currency, lang) }}
								</td>
							</tr>
							<tr v-if="!preview.accounts.length">
								<td colspan="7" class="text-center text-secondary py-3">
									{{ t("No foreign-currency account balances found for this date.") }}
								</td>
							</tr>
						</tbody>
						<!-- Net summary footer -->
						<tfoot v-if="preview.accounts.length">
							<tr class="fw-semibold border-top">
								<td colspan="6" class="text-end text-secondary small">
									{{ t("Net unrealised gain / loss") }}
								</td>
								<td
									class="text-end font-monospace"
									:class="netDelta >= 0 ? 'text-success' : 'text-danger'"
								>
									{{ formatMoney(netDelta, netBaseCurrency, lang) }}
								</td>
							</tr>
						</tfoot>
					</table>
				</div>
			</div>
			<div v-else>
				<EmptyState
					icon="ti-currency-exchange"
					tone="secondary"
					:compact="true"
					:title="t('No preview loaded')"
					:subtitle="t('Select a date and click Refresh preview.')"
				/>
			</div>
		</div>

		<!-- Offcanvas footer actions — max one .btn-primary -->
		<div class="offcanvas-footer p-3 border-top d-flex justify-content-end gap-2">
			<button
				class="btn btn-outline-secondary"
				:disabled="submitting"
				@click="closeNewPanel"
			>
				{{ t("Cancel") }}
			</button>
			<button
				class="btn btn-outline-secondary"
				:disabled="submitting || previewLoading || !preview?.accounts?.length"
				@click="createRevaluation(false)"
			>
				<i class="ti ti-device-floppy me-1"></i>{{ t("Save draft") }}
			</button>
			<button
				class="btn btn-primary"
				:disabled="submitting || previewLoading || !preview?.accounts?.length"
				@click="createRevaluation(true)"
			>
				<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
				<i v-else class="ti ti-check me-1"></i>{{ t("Submit") }}
			</button>
		</div>
	</div>
</template>
