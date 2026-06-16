<script setup>
// Bank reconciliation. Tab 1 (Import): 1C ClientBank Exchange statement → Bank
// Transaction rows. Tab 2 (Match): rank candidate vouchers (scored) and
// reconcile through ERPNext (clearance_date), never custom GL.
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, formatDateTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { useToast } from "../../composables/useToast.js";
import Select from "../../components/Select.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const { activeCompany, language } = storeToRefs(session);
const toast = useToast();

const accounts = ref([]);
const bankAccount = ref("");
const loading = ref(false);
const busy = ref("");
const fileName = ref("");
const fileB64 = ref("");
const preview = ref(null);
const imports = ref([]);

// Phase 2 — match & reconcile.
const tab = ref("import");
const unreconciled = ref([]);
const txnLoading = ref(false);
const openTxn = ref(null); // the transaction whose suggestions are shown
const suggestions = ref([]);
const sugLoading = ref(false);

const lang = computed(() => language.value || "en");
const accountOptions = computed(() => [
	{ value: "", label: t("Select bank account…") },
	...accounts.value.map((a) => ({
		value: a.name,
		label: `${a.account_name || a.name}${a.bank_account_no ? " · " + a.bank_account_no : ""}${a.currency ? " (" + a.currency + ")" : ""}`,
	})),
]);
const selectedCurrency = computed(
	() => accounts.value.find((a) => a.name === bankAccount.value)?.currency || "UZS",
);

function money(v) {
	return formatMoney(v || 0, selectedCurrency.value, lang.value);
}

async function loadAccounts() {
	if (!activeCompany.value) return;
	try {
		accounts.value = await call(
			"stabler.integrations.bank_statement.import_api.bank_accounts_for_recon",
			{ company: activeCompany.value },
		);
	} catch (e) {
		toast.error(e?.message || String(e));
	}
}

async function loadImports() {
	try {
		imports.value = await call(
			"stabler.integrations.bank_statement.import_api.list_recent_imports",
			{ company: activeCompany.value || undefined },
		);
	} catch {
		/* non-fatal */
	}
}

function onFile(e) {
	const f = e.target.files?.[0];
	preview.value = null;
	if (!f) return;
	fileName.value = f.name;
	const reader = new FileReader();
	reader.onload = () => {
		// Strip the data: URL prefix to get pure base64 (file may be cp1251).
		fileB64.value = String(reader.result).split(",", 2)[1] || "";
	};
	reader.readAsDataURL(f);
}

async function doPreview() {
	if (!fileB64.value) {
		toast.error(t("Choose a statement file first."));
		return;
	}
	busy.value = "preview";
	try {
		preview.value = await call(
			"stabler.integrations.bank_statement.import_api.preview_statement",
			{ content_base64: fileB64.value, bank_account: bankAccount.value || undefined },
		);
	} catch (e) {
		toast.error(e?.message || String(e));
	} finally {
		busy.value = "";
	}
}

async function doImport() {
	if (!bankAccount.value) {
		toast.error(t("Select the bank account this statement belongs to."));
		return;
	}
	busy.value = "import";
	try {
		const r = await call("stabler.integrations.bank_statement.import_api.import_statement", {
			company: activeCompany.value,
			bank_account: bankAccount.value,
			content_base64: fileB64.value,
			file_name: fileName.value,
		});
		toast.success(
			t("Imported {0} of {1} lines ({2} duplicates skipped).")
				.replace("{0}", r.imported)
				.replace("{1}", r.total)
				.replace("{2}", r.duplicates),
		);
		preview.value = null;
		fileB64.value = "";
		fileName.value = "";
		await loadImports();
	} catch (e) {
		toast.error(e?.message || String(e));
	} finally {
		busy.value = "";
	}
}

// ---- Phase 2: match & reconcile ----------------------------------------- //
async function loadUnreconciled() {
	if (!bankAccount.value) {
		unreconciled.value = [];
		return;
	}
	txnLoading.value = true;
	openTxn.value = null;
	suggestions.value = [];
	try {
		const r = await call("stabler.integrations.bank_statement.reconcile_api.list_unreconciled", {
			company: activeCompany.value,
			bank_account: bankAccount.value,
			limit: 200,
		});
		unreconciled.value = r.transactions || [];
	} catch (e) {
		toast.error(e?.message || String(e));
		unreconciled.value = [];
	} finally {
		txnLoading.value = false;
	}
}

async function showSuggestions(txn) {
	if (openTxn.value?.name === txn.name) {
		openTxn.value = null;
		return;
	}
	openTxn.value = txn;
	suggestions.value = [];
	sugLoading.value = true;
	try {
		const r = await call("stabler.integrations.bank_statement.reconcile_api.suggest_matches", {
			bank_transaction: txn.name,
		});
		suggestions.value = r.candidates || [];
	} catch (e) {
		toast.error(e?.message || String(e));
	} finally {
		sugLoading.value = false;
	}
}

async function reconcileWith(txn, cand) {
	busy.value = txn.name + cand.voucher_no;
	try {
		await call("stabler.integrations.bank_statement.reconcile_api.reconcile", {
			bank_transaction: txn.name,
			payment_doctype: cand.voucher_type,
			payment_name: cand.voucher_no,
		});
		toast.success(t("Reconciled."));
		openTxn.value = null;
		await loadUnreconciled();
	} catch (e) {
		toast.error(e?.message || String(e));
	} finally {
		busy.value = "";
	}
}

const bandClass = { high: "bg-green-lt", medium: "bg-yellow-lt", low: "bg-secondary-lt" };
function txnAmount(txn) {
	return money(txn.deposit ? txn.deposit : txn.withdrawal);
}

onMounted(async () => {
	loading.value = true;
	await Promise.all([loadAccounts(), loadImports()]);
	loading.value = false;
});
</script>

<template>
	<div>
		<ul class="nav nav-tabs mb-3">
			<li class="nav-item">
				<a class="nav-link" :class="{ active: tab === 'import' }" href="#" @click.prevent="tab = 'import'">
					<i class="ti ti-database-import me-1"></i>{{ t("Import") }}
				</a>
			</li>
			<li class="nav-item">
				<a class="nav-link" :class="{ active: tab === 'match' }" href="#" @click.prevent="tab = 'match'; loadUnreconciled()">
					<i class="ti ti-arrows-left-right me-1"></i>{{ t("Match & reconcile") }}
				</a>
			</li>
		</ul>

		<div v-show="tab === 'import'">
		<div class="card mb-3">
			<div class="card-header">
				<h3 class="card-title">{{ t("Import bank statement") }}</h3>
				<div class="card-subtitle">{{ t("1C ClientBank Exchange format (.txt). Uzbek bank-client export.") }}</div>
			</div>
			<div class="card-body">
				<div class="row g-3 align-items-end">
					<div class="col-md-5">
						<label class="form-label">{{ t("Bank account") }}</label>
						<Select v-model="bankAccount" :options="accountOptions" />
					</div>
					<div class="col-md-5">
						<label class="form-label">{{ t("Statement file") }}</label>
						<input type="file" class="form-control" accept=".txt,.1c,.dat,text/plain" @change="onFile" />
					</div>
					<div class="col-md-2">
						<button class="btn btn-outline-secondary w-100" :disabled="busy === 'preview'" @click="doPreview">
							{{ t("Preview") }}
						</button>
					</div>
				</div>
			</div>
		</div>

		<!-- Preview -->
		<div v-if="preview" class="card mb-3">
			<div class="card-header">
				<h3 class="card-title">{{ t("Preview") }}</h3>
				<div class="card-actions">
					<button class="btn btn-primary" :disabled="busy === 'import' || !bankAccount" @click="doImport">
						<i class="ti ti-database-import me-1"></i>{{ t("Import {0} lines").replace("{0}", preview.count) }}
					</button>
				</div>
			</div>
			<div class="card-body py-2">
				<div class="d-flex flex-wrap gap-3 small text-secondary">
					<span><b>{{ t("Account") }}:</b> <span class="font-monospace">{{ preview.account || "—" }}</span></span>
					<span><b>{{ t("Period") }}:</b> {{ formatDate(preview.period_from) }} – {{ formatDate(preview.period_to) }}</span>
					<span><b>{{ t("Lines") }}:</b> {{ preview.count }}</span>
					<span v-if="preview.account_match === false" class="text-red">
						<i class="ti ti-alert-triangle"></i>
						{{ t("Statement account does not match the selected bank account ({0}).").replace("{0}", preview.expected_account_no || "—") }}
					</span>
					<span v-else-if="preview.account_match === true" class="text-green">
						<i class="ti ti-check"></i> {{ t("Account matches") }}
					</span>
				</div>
			</div>
			<div class="table-responsive">
				<table class="table card-table table-vcenter">
					<thead>
						<tr>
							<th>{{ t("Date") }}</th>
							<th>{{ t("Reference") }}</th>
							<th>{{ t("Counterparty") }}</th>
							<th>{{ t("Purpose") }}</th>
							<th class="text-end">{{ t("Withdrawal") }}</th>
							<th class="text-end">{{ t("Deposit") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="(r, i) in preview.rows" :key="i">
							<td>{{ formatDate(r.date) }}</td>
							<td class="font-monospace small">{{ r.reference_number }}</td>
							<td>
								<div class="small">{{ r.counterparty_name || "—" }}</div>
								<div v-if="r.counterparty_inn" class="text-secondary" style="font-size: 0.72rem">
									{{ t("TIN") }} {{ r.counterparty_inn }}
								</div>
							</td>
							<td class="small text-truncate" style="max-width: 280px">{{ r.description }}</td>
							<td class="text-end font-monospace text-red">{{ r.withdrawal ? money(r.withdrawal) : "" }}</td>
							<td class="text-end font-monospace text-green">{{ r.deposit ? money(r.deposit) : "" }}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<!-- Recent imports -->
		<div class="card">
			<div class="card-header"><h3 class="card-title">{{ t("Recent imports") }}</h3></div>
			<div class="table-responsive">
				<table class="table card-table table-vcenter">
					<thead>
						<tr>
							<th>{{ t("When") }}</th>
							<th>{{ t("Account") }}</th>
							<th>{{ t("Period") }}</th>
							<th class="text-end">{{ t("Imported") }}</th>
							<th class="text-end">{{ t("Duplicates") }}</th>
							<th>{{ t("Status") }}</th>
						</tr>
					</thead>
					<SkeletonRows v-if="loading" :rows="3" :cols="6" />
					<tbody v-else>
						<tr v-for="im in imports" :key="im.name">
							<td class="text-secondary small">{{ formatDateTime(im.creation) }}</td>
							<td class="font-monospace small">{{ im.statement_account || im.bank_account }}</td>
							<td class="small">{{ formatDate(im.period_from) }} – {{ formatDate(im.period_to) }}</td>
							<td class="text-end">{{ im.imported_rows }} / {{ im.total_rows }}</td>
							<td class="text-end text-secondary">{{ im.duplicate_rows }}</td>
							<td><span class="badge" :class="getStatusBadgeClass('Stabler Bank Import', im.status)">{{ t(im.status) }}</span></td>
						</tr>
						<tr v-if="!loading && imports.length === 0">
							<td colspan="6" class="text-center text-secondary py-4">{{ t("No statements imported yet.") }}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>
		</div><!-- /import tab -->

		<!-- Match & reconcile tab -->
		<div v-show="tab === 'match'">
			<div class="card mb-3">
				<div class="card-body">
					<div class="row g-3 align-items-end">
						<div class="col-md-6">
							<label class="form-label">{{ t("Bank account") }}</label>
							<Select v-model="bankAccount" :options="accountOptions" @update:modelValue="loadUnreconciled" />
						</div>
						<div class="col-md-3">
							<button class="btn btn-outline-secondary w-100" :disabled="!bankAccount || txnLoading" @click="loadUnreconciled">
								<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
							</button>
						</div>
					</div>
				</div>
			</div>

			<div class="card">
				<div class="card-header">
					<h3 class="card-title">{{ t("Unreconciled transactions") }}</h3>
					<div class="card-subtitle">{{ t("Click a line to see suggested matches.") }}</div>
				</div>
				<div class="table-responsive">
					<table class="table card-table table-vcenter">
						<thead>
							<tr>
								<th>{{ t("Date") }}</th>
								<th>{{ t("Reference") }}</th>
								<th>{{ t("Purpose") }}</th>
								<th class="text-end">{{ t("Amount") }}</th>
								<th></th>
							</tr>
						</thead>
						<SkeletonRows v-if="txnLoading" :rows="5" :cols="5" />
						<tbody v-else>
							<template v-for="txn in unreconciled" :key="txn.name">
								<tr style="cursor: pointer" @click="showSuggestions(txn)">
									<td>{{ formatDate(txn.date) }}</td>
									<td class="font-monospace small">{{ txn.reference_number }}</td>
									<td class="small text-truncate" style="max-width: 320px">{{ txn.description }}</td>
									<td class="text-end font-monospace" :class="txn.deposit ? 'text-green' : 'text-red'">{{ txnAmount(txn) }}</td>
									<td class="text-end">
										<i class="ti" :class="openTxn?.name === txn.name ? 'ti-chevron-up' : 'ti-chevron-down'"></i>
									</td>
								</tr>
								<tr v-if="openTxn?.name === txn.name">
									<td colspan="5" class="bg-light">
										<div v-if="sugLoading" class="text-center py-3"><div class="spinner-border spinner-border-sm"></div></div>
										<div v-else-if="suggestions.length === 0" class="text-secondary small py-2">
											{{ t("No matching vouchers found. Create a payment, or widen the date/amount window.") }}
										</div>
										<table v-else class="table-no-stripe w-100" style="font-size: 0.84rem">
											<tbody>
												<tr v-for="c in suggestions" :key="c.voucher_no">
													<td><span class="badge" :class="bandClass[c.match_band]">{{ c.match_score }}</span></td>
													<td>
														<div class="fw-medium font-monospace">{{ c.voucher_no }}</div>
														<div class="text-secondary" style="font-size: 0.72rem">{{ c.party_name }} · {{ formatDate(c.date) }}</div>
													</td>
													<td class="small text-secondary">{{ (c.match_reasons || []).join(", ") }}</td>
													<td class="text-end font-monospace">{{ money(c.amount) }}</td>
													<td class="text-end">
														<button class="btn btn-sm btn-success" :disabled="busy === txn.name + c.voucher_no" @click="reconcileWith(txn, c)">
															<i class="ti ti-check me-1"></i>{{ t("Reconcile") }}
														</button>
													</td>
												</tr>
											</tbody>
										</table>
									</td>
								</tr>
							</template>
							<tr v-if="!txnLoading && unreconciled.length === 0">
								<td colspan="5" class="text-center text-secondary py-4">
									{{ bankAccount ? t("Nothing to reconcile — all clear.") : t("Select a bank account.") }}
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
		</div><!-- /match tab -->
	</div>
</template>
