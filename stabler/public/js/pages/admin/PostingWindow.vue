<script setup>
import { onMounted, ref } from "vue";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import DateInput from "../../components/DateInput.vue";

const toast = useToast();
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const roles = ref([]);
const form = ref({
	stock_frozen_upto_days: 0,
	stock_frozen_upto: "",
	stock_backdated_role: "",
	acc_frozen_upto: "",
	frozen_accounts_modifier: "",
	allow_stale: 0,
	stale_days: 0,
});

async function load() {
	loading.value = true;
	error.value = "";
	try {
		const [w, r] = await Promise.all([
			call("stabler.api.admin.get_posting_window_settings"),
			call("stabler.api.admin.list_roles", { stabler_only: 0 }),
		]);
		form.value = {
			stock_frozen_upto_days: Number(w.stock_frozen_upto_days || 0),
			stock_frozen_upto: w.stock_frozen_upto || "",
			stock_backdated_role: w.stock_backdated_role || "",
			acc_frozen_upto: w.acc_frozen_upto || "",
			frozen_accounts_modifier: w.frozen_accounts_modifier || "",
			allow_stale: Number(w.allow_stale || 0),
			stale_days: Number(w.stale_days || 0),
		};
		roles.value = (r || []).map((x) => x.name);
	} catch (e) {
		error.value = e?.message || String(e);
	} finally {
		loading.value = false;
	}
}

async function save() {
	saving.value = true;
	try {
		const w = await call("stabler.api.admin.set_posting_window_settings", { payload: { ...form.value } });
		form.value.stock_frozen_upto_days = Number(w.stock_frozen_upto_days || 0);
		toast.success(t("Posting window saved."));
	} catch (e) {
		toast.error(e?.message || t("Save failed."));
	} finally {
		saving.value = false;
	}
}

onMounted(load);
</script>

<template>
	<div class="container-xl py-3" style="max-width: 820px">
		<div class="alert alert-info" role="alert">
			<i class="ti ti-info-circle me-1"></i>
			{{ t("These are ERPNext's back-dating guards — the reason it blocks creating or editing transactions older than a set window. They protect closed periods; relax them only deliberately.") }}
		</div>

		<div v-if="error" class="alert alert-danger">{{ error }}</div>

		<div class="card mb-3">
			<div class="card-header"><h3 class="card-title"><i class="ti ti-package me-2"></i>{{ t("Stock transactions") }}</h3></div>
			<div class="card-body">
				<div class="row g-3">
					<div class="col-md-4">
						<label class="form-label">{{ t("Freeze older than (days)") }}</label>
						<input type="number" min="0" class="form-control" v-model.number="form.stock_frozen_upto_days" />
						<small class="form-hint">{{ t("Rolling window. 0 = no freeze. This is usually the one set to 49.") }}</small>
					</div>
					<div class="col-md-4">
						<label class="form-label">{{ t("Frozen up to (date)") }}</label>
						<DateInput v-model="form.stock_frozen_upto" />
						<small class="form-hint">{{ t("Fixed cut-off. Optional.") }}</small>
					</div>
					<div class="col-md-4">
						<label class="form-label">{{ t("Override role") }}</label>
						<select class="form-select" v-model="form.stock_backdated_role">
							<option value="">{{ t("— none —") }}</option>
							<option v-for="r in roles" :key="r" :value="r">{{ r }}</option>
						</select>
						<small class="form-hint">{{ t("This role may create/edit back-dated stock entries.") }}</small>
					</div>
				</div>
			</div>
		</div>

		<div class="card mb-3">
			<div class="card-header"><h3 class="card-title"><i class="ti ti-lock me-2"></i>{{ t("Accounting entries") }}</h3></div>
			<div class="card-body">
				<div class="row g-3">
					<div class="col-md-6">
						<label class="form-label">{{ t("Accounts frozen up to (date)") }}</label>
						<DateInput v-model="form.acc_frozen_upto" />
						<small class="form-hint">{{ t("Entries on/before this date are frozen.") }}</small>
					</div>
					<div class="col-md-6">
						<label class="form-label">{{ t("Frozen accounts modifier role") }}</label>
						<select class="form-select" v-model="form.frozen_accounts_modifier">
							<option value="">{{ t("— none —") }}</option>
							<option v-for="r in roles" :key="r" :value="r">{{ r }}</option>
						</select>
						<small class="form-hint">{{ t("This role may edit frozen accounting entries.") }}</small>
					</div>
				</div>
			</div>
		</div>

		<div class="card mb-3">
			<div class="card-header"><h3 class="card-title"><i class="ti ti-currency-dollar me-2"></i>{{ t("Exchange rate staleness") }}</h3></div>
			<div class="card-body">
				<div class="row g-3 align-items-end">
					<div class="col-md-6">
						<label class="form-check form-switch">
							<input class="form-check-input" type="checkbox" :checked="form.allow_stale === 1"
								@change="form.allow_stale = $event.target.checked ? 1 : 0" />
							<span class="form-check-label">{{ t("Allow stale exchange rates") }}</span>
						</label>
						<small class="form-hint d-block">{{ t("If off, a back-dated multi-currency document needs a rate within the days below.") }}</small>
					</div>
					<div class="col-md-6">
						<label class="form-label">{{ t("Stale days") }}</label>
						<input type="number" min="0" class="form-control" v-model.number="form.stale_days" :disabled="form.allow_stale === 1" />
					</div>
				</div>
			</div>
		</div>

		<div class="d-flex justify-content-end">
			<button class="btn btn-primary" :disabled="saving || loading" @click="save">
				<span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>{{ saving ? t("Saving…") : t("Save") }}
			</button>
		</div>
	</div>
</template>
