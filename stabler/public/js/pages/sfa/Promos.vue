<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";

const session = useSession();
const { activeCompany, companies } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const schemeType = ref("");

const drawerOpen = ref(false);
const drawerMode = ref("create"); // "create" | "edit"
const saving = ref(false);
const loadingDetail = ref(false);
const formError = ref("");
const form = ref(emptyForm());

const SCHEME_TYPES = ["PercentOff", "BuyXGetY", "Threshold"];

const typeLabel = (s) => {
	if (s === "PercentOff") return t("Percent off");
	if (s === "BuyXGetY") return t("Buy X get Y");
	if (s === "Threshold") return t("Threshold");
	return s || "—";
};

function emptyForm() {
	return {
		name: "",
		scheme_code: "",
		scheme_name: "",
		company: "",
		scheme_type: "PercentOff",
		discount_pct: null,
		threshold_qty: null,
		free_qty: null,
		trigger_item: "",
		reward_item: "",
		valid_from: "",
		valid_to: "",
		is_active: 1,
	};
}

async function load() {
	if (!activeCompany.value) {
		rows.value = [];
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.sfa.list_promo_schemes", {
			company: activeCompany.value,
			scheme_type: schemeType.value || undefined,
		});
	} catch (e) {
		error.value = e?.message || t("Something went wrong");
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);
watch(schemeType, load);

function openCreate() {
	drawerMode.value = "create";
	form.value = emptyForm();
	form.value.company = activeCompany.value || "";
	formError.value = "";
	drawerOpen.value = true;
}

async function openEdit(name) {
	drawerMode.value = "edit";
	form.value = emptyForm();
	formError.value = "";
	drawerOpen.value = true;
	loadingDetail.value = true;
	try {
		const doc = await call("stabler.api.sfa.get_promo_scheme", { name });
		form.value = {
			name: doc.name || "",
			scheme_code: doc.scheme_code || "",
			scheme_name: doc.scheme_name || "",
			company: doc.company || "",
			scheme_type: doc.scheme_type || "PercentOff",
			discount_pct: doc.discount_pct ?? null,
			threshold_qty: doc.threshold_qty ?? null,
			free_qty: doc.free_qty ?? null,
			trigger_item: doc.trigger_item || "",
			reward_item: doc.reward_item || "",
			valid_from: doc.valid_from || "",
			valid_to: doc.valid_to || "",
			is_active: doc.is_active ? 1 : 0,
		};
	} catch (e) {
		formError.value = e?.message || t("Failed to load promo scheme.");
	} finally {
		loadingDetail.value = false;
	}
}

function closeDrawer() {
	drawerOpen.value = false;
}

const drawerTitle = computed(() =>
	drawerMode.value === "edit" ? t("Edit Promo Scheme") : t("New Promo Scheme")
);

async function submitForm() {
	formError.value = "";
	if (
		!form.value.scheme_code ||
		!form.value.scheme_name ||
		!form.value.company ||
		!form.value.scheme_type
	) {
		formError.value = t("Please fill all required fields.");
		return;
	}
	if (
		form.value.valid_from &&
		form.value.valid_to &&
		form.value.valid_to < form.value.valid_from
	) {
		formError.value = t("Valid To must be on or after Valid From.");
		return;
	}
	saving.value = true;
	try {
		const payload = {
			scheme_code: form.value.scheme_code,
			scheme_name: form.value.scheme_name,
			company: form.value.company,
			scheme_type: form.value.scheme_type,
			discount_pct: form.value.discount_pct,
			threshold_qty: form.value.threshold_qty,
			free_qty: form.value.free_qty,
			trigger_item: form.value.trigger_item || null,
			reward_item: form.value.reward_item || null,
			valid_from: form.value.valid_from || null,
			valid_to: form.value.valid_to || null,
			is_active: form.value.is_active ? 1 : 0,
		};
		if (drawerMode.value === "edit") {
			await call("stabler.api.sfa.update_promo_scheme", {
				name: form.value.name,
				payload,
			});
		} else {
			await call("stabler.api.sfa.create_promo_scheme", { payload });
		}
		drawerOpen.value = false;
		await load();
	} catch (e) {
		formError.value = e?.message || t("Failed to save promo scheme.");
	} finally {
		saving.value = false;
	}
}
</script>

<template>
	<div class="card">
		<div class="card-header d-flex flex-wrap gap-2 align-items-center">
			<h3 class="card-title mb-0">{{ t("Promo Schemes") }}</h3>
			<div class="ms-auto d-flex gap-2 align-items-center">
				<select
					v-model="schemeType"
					class="form-select form-select-sm"
					:aria-label="t('Scheme Type')"
				>
					<option value="">{{ t("All types") }}</option>
					<option value="PercentOff">{{ t("Percent off") }}</option>
					<option value="BuyXGetY">{{ t("Buy X get Y") }}</option>
					<option value="Threshold">{{ t("Threshold") }}</option>
				</select>
				<button type="button" class="btn btn-primary btn-sm" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New Scheme") }}
				</button>
			</div>
		</div>

		<div v-if="loading" class="card-body text-secondary">{{ t("Loading…") }}</div>
		<div v-else-if="error" class="card-body text-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-discount-2"
			:title="t('No promo schemes yet')"
			:description="t('Define promotions that field users can apply during visits.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("Scheme Code") }}</th>
						<th>{{ t("Scheme Name") }}</th>
						<th>{{ t("Scheme Type") }}</th>
						<th>{{ t("Valid From") }}</th>
						<th>{{ t("Valid To") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr
						v-for="r in rows"
						:key="r.name"
						style="cursor: pointer"
						@click="openEdit(r.name)"
					>
						<td>{{ r.scheme_code }}</td>
						<td>{{ r.scheme_name }}</td>
						<td>{{ typeLabel(r.scheme_type) }}</td>
						<td>{{ r.valid_from || "—" }}</td>
						<td>{{ r.valid_to || "—" }}</td>
						<td>
							<span
								class="badge"
								:class="r.is_active ? 'bg-success-lt' : 'bg-secondary-lt'"
							>
								{{ r.is_active ? t("Active") : t("Inactive") }}
							</span>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<div v-if="drawerOpen" class="offcanvas-backdrop fade show" @click="closeDrawer"></div>
	<div
		class="offcanvas offcanvas-end"
		:class="{ show: drawerOpen }"
		tabindex="-1"
		style="visibility: visible; width: 520px"
		:style="{ transform: drawerOpen ? 'translateX(0)' : 'translateX(100%)' }"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">{{ drawerTitle }}</h5>
			<button type="button" class="btn-close" @click="closeDrawer" :aria-label="t('Close')"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="loadingDetail" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<template v-else>
				<div v-if="formError" class="alert alert-danger">{{ formError }}</div>

				<div class="mb-3">
					<label class="form-label required">{{ t("Scheme Code") }}</label>
					<input
						v-model="form.scheme_code"
						type="text"
						class="form-control"
						:disabled="drawerMode === 'edit'"
					/>
				</div>

				<div class="mb-3">
					<label class="form-label required">{{ t("Scheme Name") }}</label>
					<input v-model="form.scheme_name" type="text" class="form-control" />
				</div>

				<div class="mb-3">
					<label class="form-label required">{{ t("Company") }}</label>
					<select v-model="form.company" class="form-select">
						<option value="" disabled>{{ t("Select company") }}</option>
						<option v-for="c in companies" :key="c.name" :value="c.name">
							{{ c.company_name || c.name }}
						</option>
					</select>
				</div>

				<div class="mb-3">
					<label class="form-label required">{{ t("Scheme Type") }}</label>
					<select v-model="form.scheme_type" class="form-select">
						<option v-for="st in SCHEME_TYPES" :key="st" :value="st">
							{{ typeLabel(st) }}
						</option>
					</select>
				</div>

				<div v-if="form.scheme_type === 'PercentOff'" class="mb-3">
					<label class="form-label">{{ t("Discount %") }}</label>
					<input
						v-model.number="form.discount_pct"
						type="number"
						min="0"
						max="100"
						step="0.01"
						inputmode="decimal"
						class="form-control"
					/>
				</div>

				<div
					v-if="form.scheme_type === 'BuyXGetY' || form.scheme_type === 'Threshold'"
					class="row g-2"
				>
					<div class="col-md-6 mb-3">
						<label class="form-label">{{ t("Threshold Qty") }}</label>
						<input
							v-model.number="form.threshold_qty"
							type="number"
							min="0"
							step="1"
							inputmode="decimal"
							class="form-control"
						/>
					</div>
					<div class="col-md-6 mb-3">
						<label class="form-label">{{ t("Free Qty") }}</label>
						<input
							v-model.number="form.free_qty"
							type="number"
							min="0"
							step="1"
							inputmode="decimal"
							class="form-control"
						/>
					</div>
				</div>

				<div class="row g-2">
					<div class="col-md-6 mb-3">
						<label class="form-label">{{ t("Valid From") }}</label>
						<DateInput v-model="form.valid_from" />
					</div>
					<div class="col-md-6 mb-3">
						<label class="form-label">{{ t("Valid To") }}</label>
						<DateInput v-model="form.valid_to" />
					</div>
				</div>

				<div class="form-check form-switch mb-3">
					<input
						id="promo-scheme-active"
						v-model="form.is_active"
						:true-value="1"
						:false-value="0"
						class="form-check-input"
						type="checkbox"
					/>
					<label class="form-check-label" for="promo-scheme-active">
						{{ t("Active") }}
					</label>
				</div>

				<div class="d-flex gap-2 mt-4">
					<button
						type="button"
						class="btn btn-primary"
						:disabled="saving"
						@click="submitForm"
					>
						<span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
						{{ drawerMode === "edit" ? t("Save Changes") : t("Create Scheme") }}
					</button>
					<button type="button" class="btn btn-link" @click="closeDrawer">
						{{ t("Cancel") }}
					</button>
				</div>
			</template>
		</div>
	</div>
</template>
