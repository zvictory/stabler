<script setup>
/**
 * EdoSubmitModal — send a submitted Sales Invoice to the Didox.uz EDO (ЭСФ).
 *
 * Flow (self-key signed in the browser, never on the server):
 *   1. On open, call stabler.api.edo.didox_prepare(invoiceName) → returns a
 *      NEW Didox Submission name plus the unsigned payload for preview.
 *   2. Show a readiness preview; warn (do not block) when seller/buyer TIN or
 *      any item IKPU code is missing — Didox rejects such envelopes.
 *   3. On "Sign & send", drive E-IMZO (CAPIWS) in the browser: list keys →
 *      load the chosen key → create an attached PKCS#7 over the payload JSON.
 *   4. call stabler.api.edo.didox_send(submissionName, signed_pkcs7) — note the
 *      FIRST arg is the SUBMISSION name from step 1, not the invoice name — then
 *      emit "sent" so the parent reloads the invoice detail.
 *
 * Emits `sent` with the submission name on success and `close` on dismiss.
 */
import { computed, ref, watch } from "vue";
import { call } from "../api/client.js";
import { t } from "../composables/i18n.js";
import * as eimzo from "../lib/eimzo.js";

const props = defineProps({
	open: { type: Boolean, required: true },
	invoiceName: { type: String, default: "" },
});

const emit = defineEmits(["close", "sent"]);

const loading = ref(false);
const submitting = ref(false);
const error = ref("");

// Kept SEPARATE from props.invoiceName on purpose: didox_prepare mints a new
// Didox Submission name, and didox_send/didox_retry key off THAT, not the SI.
const submissionName = ref("");
const payload = ref(null);

// E-IMZO key selection
const keys = ref([]);
const selectedKeyId = ref("");

const missing = computed(() => {
	const p = payload.value;
	if (!p) return [];
	const out = [];
	if (!p.seller?.tin) out.push(t("Seller TIN"));
	if (!p.buyer?.tin) out.push(t("Buyer TIN"));
	const noIkpu = (p.items || []).filter((r) => !r.ikpu_code).length;
	if (noIkpu > 0) out.push(t("IKPU code on {0} item(s)").replace("{0}", String(noIkpu)));
	return out;
});

const canSend = computed(() => Boolean(submissionName.value) && !submitting.value);

function reset() {
	error.value = "";
	submissionName.value = "";
	payload.value = null;
	keys.value = [];
	selectedKeyId.value = "";
}

watch(
	() => props.open,
	async (now) => {
		if (!now) return;
		reset();
		if (!props.invoiceName) return;
		loading.value = true;
		try {
			const res = await call("stabler.api.edo.didox_prepare", { name: props.invoiceName });
			submissionName.value = res?.name || "";
			payload.value = res?.payload || null;
		} catch (err) {
			error.value = err?.message || t("Could not prepare the document for Didox.");
		} finally {
			loading.value = false;
		}
	}
);

function close() {
	if (submitting.value) return;
	emit("close");
}

// UTF-8-safe base64 of the payload JSON so Cyrillic customer names / item names
// survive the round-trip into E-IMZO's create_pkcs7 (which expects base64 data).
function payloadBase64() {
	const json = JSON.stringify(payload.value);
	return btoa(unescape(encodeURIComponent(json)));
}

async function signAndSend() {
	if (!canSend.value) return;
	error.value = "";
	submitting.value = true;
	try {
		if (!eimzo.isAvailable || !(await eimzo.isAvailable())) {
			throw new Error(
				t("E-IMZO is not running. Start the E-IMZO desktop app and try again.")
			);
		}

		// Lazily list keys the first time; let the user pick which certificate.
		if (!keys.value.length) {
			keys.value = await eimzo.listKeys();
			if (!keys.value.length) {
				throw new Error(t("No E-IMZO keys found. Insert your key and reload E-IMZO."));
			}
			if (!selectedKeyId.value) selectedKeyId.value = keys.value[0].id;
		}

		const keyEntry = keys.value.find((k) => k.id === selectedKeyId.value) || keys.value[0];
		const keyId = await eimzo.loadKey(keyEntry);
		const signedPkcs7 = await eimzo.createPkcs7(keyId, payloadBase64());

		await call("stabler.api.edo.didox_send", {
			name: submissionName.value,
			signed_pkcs7: signedPkcs7,
		});
		emit("sent", submissionName.value);
	} catch (err) {
		error.value = err?.message || t("Signing or sending to Didox failed.");
	} finally {
		submitting.value = false;
	}
}
</script>

<template>
	<div v-if="open" class="modal-backdrop fade show" @click="close"></div>
	<div
		v-if="open"
		class="modal fade show d-block"
		tabindex="-1"
		role="dialog"
		@click.self="close"
	>
		<div class="modal-dialog modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("Send to Didox") }}</h5>
					<button type="button" class="btn-close" @click="close" :disabled="submitting"></button>
				</div>

				<div class="modal-body">
					<div v-if="loading" class="text-center py-4">
						<span class="spinner-border spinner-border-sm"></span>
					</div>

					<template v-else>
						<div v-if="error" class="alert alert-danger">{{ error }}</div>

						<div v-if="payload">
							<dl class="row mb-3 small">
								<dt class="col-5 text-muted">{{ t("Invoice") }}</dt>
								<dd class="col-7 font-monospace">{{ payload.invoice_no }}</dd>
								<dt class="col-5 text-muted">{{ t("Seller TIN") }}</dt>
								<dd class="col-7 font-monospace">{{ payload.seller?.tin || "—" }}</dd>
								<dt class="col-5 text-muted">{{ t("Buyer") }}</dt>
								<dd class="col-7">{{ payload.buyer?.customer_name || "—" }}</dd>
								<dt class="col-5 text-muted">{{ t("Buyer TIN") }}</dt>
								<dd class="col-7 font-monospace">{{ payload.buyer?.tin || "—" }}</dd>
								<dt class="col-5 text-muted">{{ t("Items") }}</dt>
								<dd class="col-7">{{ (payload.items || []).length }}</dd>
							</dl>

							<div v-if="missing.length" class="alert alert-warning small mb-3">
								<div class="fw-semibold mb-1">
									{{ t("Didox may reject this document — missing data:") }}
								</div>
								<ul class="mb-0 ps-3">
									<li v-for="m in missing" :key="m">{{ m }}</li>
								</ul>
							</div>

							<div v-if="keys.length" class="mb-2">
								<label class="form-label small text-muted">{{ t("Signing key") }}</label>
								<select v-model="selectedKeyId" class="form-select form-select-sm">
									<option v-for="k in keys" :key="k.id" :value="k.id">
										{{ k.cn || k.name }} <template v-if="k.tin">({{ k.tin }})</template>
									</option>
								</select>
							</div>

							<p class="text-muted small mb-0">
								{{ t("You will sign this document in the browser with your own E-IMZO key.") }}
							</p>
						</div>
					</template>
				</div>

				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" @click="close" :disabled="submitting">
						{{ t("Cancel") }}
					</button>
					<button
						type="button"
						class="btn btn-primary ms-auto"
						:disabled="!canSend || loading"
						@click="signAndSend"
					>
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-signature me-1"></i>{{ t("Sign & send") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
