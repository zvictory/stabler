<script setup>
import { onMounted, ref } from "vue";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";

const toast = useToast();

const loading = ref(true);
const saving = ref(false);
const error = ref("");

const credential = ref({
	enabled: 0,
	api_base: "",
	origin: "",
	has_access_token: false,
	access_expires_at: null,
	has_refresh_token: false,
	refresh_expires_at: null,
});

// New token inputs — empty means "don't change"
const newAccessToken = ref("");
const newRefreshToken = ref("");

async function load() {
	loading.value = true;
	error.value = "";
	try {
		credential.value = await call("stabler.api.timepay_admin.get_timepay_credential");
	} catch (e) {
		error.value = e?.message || String(e);
	} finally {
		loading.value = false;
	}
}

async function save() {
	saving.value = true;
	error.value = "";
	try {
		await call("stabler.api.timepay_admin.save_timepay_credential", {
			payload: JSON.stringify({
				enabled: credential.value.enabled,
				api_base: credential.value.api_base,
				origin: credential.value.origin,
				access_token: newAccessToken.value.trim(),
				refresh_token: newRefreshToken.value.trim(),
			}),
		});
		toast.success(t("TimePay credentials saved."));
		newAccessToken.value = "";
		newRefreshToken.value = "";
		await load();
	} catch (e) {
		error.value = e?.message || String(e);
	} finally {
		saving.value = false;
	}
}

function fmtExpiry(ts) {
	if (!ts) return t("Unknown");
	const d = new Date(ts * 1000);
	return d.toLocaleString();
}

onMounted(load);
</script>

<template>
	<div v-if="loading" class="py-5 text-center">
		<div class="spinner-border text-primary" role="status"></div>
	</div>

	<div v-else class="row g-3" style="max-width: 640px">
		<div v-if="error" class="col-12">
			<div class="alert alert-danger">{{ error }}</div>
		</div>

		<!-- Enable toggle -->
		<div class="col-12">
			<div class="card">
				<div class="card-body">
					<div class="d-flex align-items-center gap-3">
						<label class="form-check form-switch mb-0">
							<input
								v-model="credential.enabled"
								class="form-check-input"
								type="checkbox"
								:true-value="1"
								:false-value="0"
							/>
						</label>
						<div>
							<div class="fw-semibold">{{ t("Enable TimePay sync") }}</div>
							<div class="text-secondary small">{{ t("Nightly attendance sync and processing will run when enabled.") }}</div>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Token status -->
		<div class="col-12">
			<div class="card">
				<div class="card-header">
					<h4 class="card-title">{{ t("Token status") }}</h4>
				</div>
				<div class="card-body">
					<div class="row g-2">
						<div class="col-6">
							<div class="small text-secondary mb-1">{{ t("Access token") }}</div>
							<span v-if="credential.has_access_token" class="badge bg-green-lt text-green">
								<i class="ti ti-check me-1"></i>{{ t("Set") }}
							</span>
							<span v-else class="badge bg-red-lt text-red">
								<i class="ti ti-x me-1"></i>{{ t("Not set") }}
							</span>
							<div v-if="credential.has_access_token && credential.access_expires_at" class="text-secondary small mt-1">
								{{ t("Expires") }}: {{ fmtExpiry(credential.access_expires_at) }}
							</div>
						</div>
						<div class="col-6">
							<div class="small text-secondary mb-1">{{ t("Refresh token") }}</div>
							<span v-if="credential.has_refresh_token" class="badge bg-green-lt text-green">
								<i class="ti ti-check me-1"></i>{{ t("Set") }}
							</span>
							<span v-else class="badge bg-red-lt text-red">
								<i class="ti ti-x me-1"></i>{{ t("Not set") }}
							</span>
							<div v-if="credential.has_refresh_token && credential.refresh_expires_at" class="text-secondary small mt-1">
								{{ t("Expires") }}: {{ fmtExpiry(credential.refresh_expires_at) }}
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Paste new tokens -->
		<div class="col-12">
			<div class="card">
				<div class="card-header">
					<h4 class="card-title">{{ t("Update tokens") }}</h4>
					<div class="card-subtitle">{{ t("Leave blank to keep the existing token.") }}</div>
				</div>
				<div class="card-body">
					<div class="mb-3">
						<label class="form-label">{{ t("Access token (JWT)") }}</label>
						<textarea
							v-model="newAccessToken"
							class="form-control font-monospace"
							rows="3"
							style="font-size: 11px; resize: vertical"
							:placeholder="credential.has_access_token ? t('Paste new token to replace…') : t('Paste access token JWT…')"
						></textarea>
					</div>
					<div>
						<label class="form-label">{{ t("Refresh token (JWT)") }}</label>
						<textarea
							v-model="newRefreshToken"
							class="form-control font-monospace"
							rows="3"
							style="font-size: 11px; resize: vertical"
							:placeholder="credential.has_refresh_token ? t('Paste new token to replace…') : t('Paste refresh token JWT…')"
						></textarea>
					</div>
				</div>
			</div>
		</div>

		<!-- Advanced -->
		<div class="col-12">
			<details>
				<summary class="text-secondary small" style="cursor: pointer">{{ t("Advanced (API endpoints)") }}</summary>
				<div class="card mt-2">
					<div class="card-body">
						<div class="mb-3">
							<label class="form-label small">{{ t("API base URL") }}</label>
							<input v-model="credential.api_base" type="text" class="form-control form-control-sm" placeholder="https://api.app.time-pay.uz" />
						</div>
						<div>
							<label class="form-label small">{{ t("Origin") }}</label>
							<input v-model="credential.origin" type="text" class="form-control form-control-sm" placeholder="https://app.time-pay.uz" />
						</div>
					</div>
				</div>
			</details>
		</div>

		<!-- Save -->
		<div class="col-12">
			<button type="button" class="btn btn-primary" :disabled="saving" @click="save">
				<span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
				{{ t("Save") }}
			</button>
		</div>
	</div>
</template>
