<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { t } from "../../composables/i18n.js";
import { accountLabel } from "../../composables/accounts.js";
import { call } from "../../api/client.js";
import { kassaAdminApi } from "../../api/kassaAdmin.js";
import { adminApi } from "../../api/admin.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const toast = useToast();
const { confirm } = useConfirm();

// --- list state ---
const loading = ref(false);
const error = ref("");
const rows = ref([]);
const companies = ref([]);
const companyFilter = ref("");
const search = ref("");

const companyOptions = computed(() => [
	{ value: "", label: t("All companies") },
	...companies.value.map((c) => ({ value: c.name, label: c.name })),
]);

// --- drawer state ---
const drawerOpen = ref(false);
const isNew = ref(false);
const drawerLoading = ref(false);
const drawerError = ref("");
const drawerSaving = ref(false);
const form = ref(emptyForm());
const users = ref([]);
const accountOptions = ref([]);
const accountsLoading = ref(false);

function emptyForm() {
	return { name: "", telegram_user_id: "", user: "", company: "", enabled: 1, accounts: [] };
}

const userOptions = computed(() =>
	users.value.map((u) => ({ value: u.name, label: u.full_name ? `${u.full_name} — ${u.name}` : u.name })),
);
const companyPickerOptions = computed(() => companies.value.map((c) => ({ value: c.name, label: c.name })));

async function loadCompanies() {
	try {
		companies.value = await call("stabler.api.organization.list_companies");
	} catch (err) {
		// Non-fatal: liste yine yüklenir, sadece company filtresi/pickerı boş kalır.
		companies.value = [];
	}
}

async function load() {
	loading.value = true;
	error.value = "";
	try {
		rows.value = await kassaAdminApi.listKassirs({
			search: search.value || undefined,
			company: companyFilter.value || undefined,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load cashiers.");
	} finally {
		loading.value = false;
	}
}

async function loadUsers() {
	if (users.value.length) return;
	try {
		users.value = await adminApi.listUsers({ limit: 500 });
	} catch (err) {
		users.value = [];
	}
}

async function loadAccounts(company) {
	if (!company) {
		accountOptions.value = [];
		return;
	}
	accountsLoading.value = true;
	try {
		accountOptions.value = await call("stabler.api.money.bank_cash_accounts", { company });
	} catch (err) {
		accountOptions.value = [];
		drawerError.value = err?.message || t("Failed to load accounts.");
	} finally {
		accountsLoading.value = false;
	}
}

async function openCreate() {
	form.value = emptyForm();
	if (companyFilter.value) form.value.company = companyFilter.value;
	isNew.value = true;
	drawerError.value = "";
	drawerOpen.value = true;
	drawerLoading.value = true;
	await Promise.all([loadUsers(), loadAccounts(form.value.company)]);
	drawerLoading.value = false;
}

async function openDetail(name) {
	isNew.value = false;
	drawerError.value = "";
	drawerOpen.value = true;
	drawerLoading.value = true;
	try {
		const [doc] = await Promise.all([kassaAdminApi.getKassir(name), loadUsers()]);
		form.value = {
			name: doc.name,
			telegram_user_id: doc.telegram_user_id,
			user: doc.user || "",
			company: doc.company || "",
			enabled: Number(doc.enabled || 0),
			accounts: (doc.accounts || []).map((a) => a.account),
		};
		await loadAccounts(form.value.company);
	} catch (err) {
		drawerError.value = err?.message || t("Failed to load cashier.");
	} finally {
		drawerLoading.value = false;
	}
}

function closeDrawer() {
	if (drawerSaving.value) return;
	drawerOpen.value = false;
}

// Company değişince izinli hesap seçenekleri değişir → tazele + geçersiz seçimleri düş.
watch(
	() => form.value.company,
	async (company, prev) => {
		if (!drawerOpen.value || company === prev) return;
		await loadAccounts(company);
		const valid = new Set(accountOptions.value.map((a) => a.name));
		form.value.accounts = form.value.accounts.filter((a) => valid.has(a));
	},
);

function toggleAccount(accountName) {
	const i = form.value.accounts.indexOf(accountName);
	if (i >= 0) form.value.accounts.splice(i, 1);
	else form.value.accounts.push(accountName);
}

async function save() {
	if (isNew.value && !form.value.telegram_user_id.trim()) {
		drawerError.value = t("Telegram User ID is required.");
		return;
	}
	if (!form.value.user) {
		drawerError.value = t("User is required.");
		return;
	}
	if (!form.value.company) {
		drawerError.value = t("Company is required.");
		return;
	}
	drawerSaving.value = true;
	drawerError.value = "";
	const accounts = form.value.accounts.map((account) => ({ account }));
	try {
		if (isNew.value) {
			await kassaAdminApi.createKassir({
				telegram_user_id: form.value.telegram_user_id.trim(),
				user: form.value.user,
				company: form.value.company,
				enabled: form.value.enabled,
				accounts: JSON.stringify(accounts),
			});
			toast.success(t("Cashier created."));
		} else {
			await kassaAdminApi.updateKassir({
				name: form.value.name,
				user: form.value.user,
				company: form.value.company,
				enabled: form.value.enabled,
				accounts: JSON.stringify(accounts),
			});
			toast.success(t("Cashier updated."));
		}
		drawerOpen.value = false;
		await load();
	} catch (err) {
		drawerError.value = err?.message || t("Failed to save cashier.");
	} finally {
		drawerSaving.value = false;
	}
}

async function quickToggleEnabled(k) {
	const next = k.enabled ? 0 : 1;
	try {
		await kassaAdminApi.setKassirEnabled(k.name, next);
		k.enabled = next;
		toast.success(next ? t("Cashier enabled.") : t("Cashier disabled."));
	} catch (err) {
		toast.error(err?.message || t("Failed to update status."));
	}
}

async function removeKassir() {
	const confirmed = await confirm({
		title: t("Delete cashier?"),
		body: t("Remove Telegram access for {0}? This cannot be undone.").replace("{0}", form.value.telegram_user_id),
		danger: true,
	});
	if (!confirmed) return;
	drawerSaving.value = true;
	try {
		await kassaAdminApi.deleteKassir(form.value.name);
		toast.success(t("Cashier deleted."));
		drawerOpen.value = false;
		await load();
	} catch (err) {
		drawerError.value = err?.message || t("Failed to delete cashier.");
	} finally {
		drawerSaving.value = false;
	}
}

onMounted(async () => {
	await loadCompanies();
	await load();
});
watch(companyFilter, load);
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('Telegram ID or user…')"
			:count="rows.length"
			:total-label="t('Cashiers')"
			:total-value="String(rows.length)"
			:primary-label="t('New cashier')"
			primary-icon="ti-plus"
			@search="load"
			@primary-click="openCreate"
		>
			<template #filters>
				<Select v-model="companyFilter" size="sm" :options="companyOptions" style="width: 200px" />
			</template>
		</ListToolbar>

		<div v-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!loading && !rows.length"
			icon="ti-brand-telegram"
			accentIcon="ti-plus"
			tone="primary"
			:title="t('No cashiers yet')"
			:subtitle="t('Add a Telegram cashier to give bot access to a cash/bank account.')"
		>
			<template #actions>
				<button type="button" class="btn btn-outline-secondary btn-sm" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New cashier") }}
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th class="text-nowrap">{{ t("Telegram ID") }}</th>
						<th>{{ t("User") }}</th>
						<th>{{ t("Company") }}</th>
						<th class="text-center">{{ t("Enabled") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="5" :cols="4" />
				<tbody v-else>
					<tr v-for="k in rows" :key="k.name" style="cursor: pointer" @click="openDetail(k.name)">
						<td class="font-monospace text-primary text-nowrap">{{ k.telegram_user_id }}</td>
						<td>{{ k.user }}</td>
						<td>{{ k.company }}</td>
						<td class="text-center" @click.stop>
							<label class="form-check form-switch d-inline-flex m-0 justify-content-center">
								<input
									class="form-check-input"
									type="checkbox"
									:checked="k.enabled"
									@change="quickToggleEnabled(k)"
								/>
							</label>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<div v-if="drawerOpen" class="offcanvas-backdrop fade show" @click="closeDrawer"></div>
	<div
		v-if="drawerOpen"
		class="offcanvas offcanvas-end show"
		tabindex="-1"
		style="visibility: visible; width: 600px"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">
				<i class="ti ti-brand-telegram me-1"></i>
				{{ isNew ? t("New cashier") : form.telegram_user_id }}
			</h5>
			<button type="button" class="btn-close" @click="closeDrawer"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="drawerLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else>
				<div v-if="drawerError" class="alert alert-danger">{{ drawerError }}</div>

				<div class="mb-3">
					<label class="form-label">{{ t("Telegram User ID") }}</label>
					<input
						class="form-control"
						type="text"
						inputmode="numeric"
						v-model="form.telegram_user_id"
						:disabled="!isNew"
						:placeholder="t('Digits only, e.g. 48654899')"
					/>
					<div v-if="!isNew" class="form-hint">{{ t("Telegram ID cannot be changed after creation.") }}</div>
				</div>

				<div class="mb-3">
					<label class="form-label">{{ t("User") }}</label>
					<Select
						v-model="form.user"
						:options="userOptions"
						:placeholder="t('Select a user…')"
						:search-threshold="0"
					/>
				</div>

				<div class="mb-3">
					<label class="form-label">{{ t("Company") }}</label>
					<Select
						v-model="form.company"
						:options="companyPickerOptions"
						:placeholder="t('Select a company…')"
					/>
				</div>

				<div class="mb-3">
					<label class="form-check form-switch">
						<input
							class="form-check-input"
							type="checkbox"
							:true-value="1"
							:false-value="0"
							v-model="form.enabled"
						/>
						<span class="form-check-label">{{ t("Enabled (bot access)") }}</span>
					</label>
				</div>

				<h6 class="text-uppercase text-secondary small mb-2">{{ t("Permitted cash/bank accounts") }}</h6>
				<div v-if="accountsLoading" class="text-center py-3">
					<div class="spinner-border spinner-border-sm text-primary"></div>
				</div>
				<div v-else-if="!form.company" class="text-secondary small mb-3">
					{{ t("Select a company to choose accounts.") }}
				</div>
				<div v-else-if="!accountOptions.length" class="text-secondary small mb-3">
					{{ t("No cash/bank accounts found for this company.") }}
				</div>
				<div v-else class="border rounded p-2 mb-3" style="max-height: 260px; overflow: auto">
					<label v-for="a in accountOptions" :key="a.name" class="form-check">
						<input
							class="form-check-input"
							type="checkbox"
							:checked="form.accounts.includes(a.name)"
							@change="toggleAccount(a.name)"
						/>
						<span class="form-check-label">
							{{ accountLabel(a) }}
							<span class="text-secondary small">— {{ a.account_currency }}</span>
						</span>
					</label>
				</div>

				<div class="d-flex justify-content-between align-items-center mt-4">
					<button
						v-if="!isNew"
						type="button"
						class="btn btn-ghost-danger btn-sm"
						:disabled="drawerSaving"
						@click="removeKassir"
					>
						<i class="ti ti-trash me-1"></i>{{ t("Delete") }}
					</button>
					<span v-else></span>
					<button type="button" class="btn btn-primary" :disabled="drawerSaving" @click="save">
						<span v-if="drawerSaving" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-check me-1"></i>{{ t("Save") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
