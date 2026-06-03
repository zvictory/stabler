<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { call } from "../../api/client.js";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";
import { formatMoney } from "../../composables/money.js";
import DateInput from "../../components/DateInput.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import Select from "../../components/Select.vue";

const router = useRouter();
const session = useSession();

const CURRENCIES = ["USD", "EUR", "USDT"];

const loading = ref(false);
const error = ref("");
const submitting = ref(false);
const submitError = ref("");

const cashAccounts = ref([]);
const payoutAccounts = ref([]);
const commissionAccounts = ref([]);
const corridors = ref([]);

const step = ref(1);

const form = ref({
	posting_date: new Date().toISOString().slice(0, 10),
	from_city: "",
	to_city: "",
	send_currency: "USD",
	receive_currency: "USD",
	exchange_rate: null,
	amount: null,
	commission_percent: null,
	commission_mode: "exclusive",
	cash_in_account: "",
	payout_account: "",
	commission_account: "",
	sender_name: "",
	receiver_name: "",
	memo: "",
});

const company = computed(() => session.activeCompany);

// ── Corridor helpers ──────────────────────────────────────────────────────────
const fromCities = computed(() => [...new Set(corridors.value.map((c) => c.from_city))]);

const toCities = computed(() =>
	corridors.value.filter((c) => c.from_city === form.value.from_city).map((c) => c.to_city),
);

const selectedCorridor = computed(() =>
	corridors.value.find(
		(c) => c.from_city === form.value.from_city && c.to_city === form.value.to_city,
	),
);

// When departure city changes, reset destination if it's no longer valid.
// Auto-pick when there's exactly one option.
watch(
	() => form.value.from_city,
	() => {
		const valid = toCities.value;
		if (!valid.includes(form.value.to_city)) {
			form.value.to_city = valid.length === 1 ? valid[0] : "";
		}
	},
);

// ── Derived ───────────────────────────────────────────────────────────────────
const isCrossCurrency = computed(() => form.value.send_currency !== form.value.receive_currency);

const round2 = (x) => Math.round(x * 100) / 100;

// Commission fee auto-computed from %, mirroring remittance.py rounding exactly.
const commissionFee = computed(() => {
	const amt = parseFloat(form.value.amount) || 0;
	const pct = parseFloat(form.value.commission_percent) || 0;
	if (amt <= 0) return 0;
	const rate = pct / 100;
	if (form.value.commission_mode === "inclusive") {
		// Sender gives `amt` gross; back out the principal then take the remainder.
		return round2(amt - round2(amt / (1 + rate)));
	}
	return round2(amt * rate);
});

const preview = computed(() => {
	const amt = parseFloat(form.value.amount) || 0;
	const comm = commissionFee.value;
	if (amt <= 0) return null;
	if (form.value.commission_mode === "inclusive") {
		return {
			senderPays: amt,
			receiverGets: round2(amt - comm),
			commissionKept: comm,
		};
	}
	return {
		senderPays: round2(amt + comm),
		receiverGets: amt,
		commissionKept: comm,
	};
});

// ── Step navigation guards ────────────────────────────────────────────────────
const step1Valid = computed(() => {
	if (isCrossCurrency.value && !(parseFloat(form.value.exchange_rate) > 0)) return false;
	return true;
});

const step2Valid = computed(() => {
	return parseFloat(form.value.amount) > 0 && (parseFloat(form.value.commission_percent) || 0) >= 0;
});

function goStep(n) {
	// Only allow jumping back to a completed step
	if (n < step.value) step.value = n;
}

function nextStep() {
	step.value += 1;
}

function prevStep() {
	step.value -= 1;
}

// ── Data fetch ────────────────────────────────────────────────────────────────
async function load() {
	if (!company.value) return;
	loading.value = true;
	error.value = "";
	try {
		const [accts, corr] = await Promise.all([
			call("stabler.api.remittance.remittance_accounts", { company: company.value }),
			call("stabler.api.remittance.list_corridors"),
		]);
		cashAccounts.value = accts.cash_accounts || [];
		payoutAccounts.value = accts.payout_accounts || [];
		commissionAccounts.value = accts.commission_accounts || [];
		corridors.value = corr || [];
	} catch (err) {
		error.value = err?.message || t("Failed to load accounts.");
	} finally {
		loading.value = false;
	}
}

// ── Submit ────────────────────────────────────────────────────────────────────
async function submit() {
	submitError.value = "";
	if (!form.value.cash_in_account || !form.value.payout_account || !form.value.commission_account) {
		submitError.value = t("All three accounts are required.");
		return;
	}
	if (!form.value.amount || parseFloat(form.value.amount) <= 0) {
		submitError.value = t("Amount must be positive.");
		return;
	}
	submitting.value = true;
	try {
		await call("stabler.api.remittance.create_remittance", {
			company: company.value,
			posting_date: form.value.posting_date,
			cash_in_account: form.value.cash_in_account,
			payout_account: form.value.payout_account,
			commission_account: form.value.commission_account,
			send_currency: form.value.send_currency,
			receive_currency: form.value.receive_currency,
			amount: form.value.amount,
			commission_percent: form.value.commission_percent || 0,
			commission_mode: form.value.commission_mode,
			exchange_rate: isCrossCurrency.value ? form.value.exchange_rate : null,
			corridor: selectedCorridor.value?.label || null,
			sender_name: form.value.sender_name || null,
			receiver_name: form.value.receiver_name || null,
			memo: form.value.memo || null,
			submit: 1,
		});
		await router.push("/remittance/transfers");
	} catch (err) {
		submitError.value = err?.message || t("Failed to create transfer.");
	} finally {
		submitting.value = false;
	}
}

onMounted(load);
</script>

<template>
	<div v-if="loading" class="text-center py-5">
		<div class="spinner-border text-primary" role="status"></div>
	</div>
	<div v-else-if="error" class="alert alert-danger">{{ error }}</div>
	<div v-else class="row justify-content-center">
		<div class="col-lg-8">
			<!-- Step indicator -->
			<ul class="steps steps-counter mb-4">
				<li class="step-item" :class="{ active: step === 1 }" style="cursor: pointer" @click="goStep(1)">
					{{ t("Direction") }}
				</li>
				<li class="step-item" :class="{ active: step === 2 }" style="cursor: pointer" @click="goStep(2)">
					{{ t("Amount") }}
				</li>
				<li class="step-item" :class="{ active: step === 3 }">
					{{ t("Accounts") }}
				</li>
			</ul>

			<div class="card">
				<div class="card-body">
					<div v-if="submitError" class="alert alert-danger mb-3">{{ submitError }}</div>

					<!-- ── Step 1: Direction ────────────────────────────────────── -->
					<div v-if="step === 1" class="row g-3">
						<div class="col-md-6">
							<label class="form-label">{{ t("From") }}</label>
							<Select v-model="form.from_city" :options="fromCities" :placeholder="t('Select city…')" />
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("To") }}</label>
							<Select v-model="form.to_city" :options="toCities" :placeholder="t('Select city…')" :disabled="!form.from_city" />
						</div>

						<div class="col-md-6">
							<label class="form-label">{{ t("Send currency") }}</label>
							<Select v-model="form.send_currency" :options="CURRENCIES" />
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Receive currency") }}</label>
							<Select v-model="form.receive_currency" :options="CURRENCIES" />
						</div>

						<div v-if="isCrossCurrency" class="col-12">
							<label class="form-label">
								{{ t("Exchange rate") }}
								<span class="text-secondary small ms-1">
									(1 {{ form.send_currency }} = ? {{ form.receive_currency }})
								</span>
							</label>
							<MoneyInput v-model="form.exchange_rate" :currency="form.send_currency" />
						</div>

						<div class="col-md-6">
							<label class="form-label">{{ t("Date") }}</label>
							<DateInput v-model="form.posting_date" />
						</div>

						<div class="col-12 d-flex justify-content-end mt-2">
							<button
								type="button"
								class="btn btn-primary"
								:disabled="!step1Valid"
								@click="nextStep"
							>
								{{ t("Next") }} <i class="ti ti-arrow-right ms-1"></i>
							</button>
						</div>
					</div>

					<!-- ── Step 2: Amount ───────────────────────────────────────── -->
					<div v-if="step === 2" class="row g-3">
						<div class="col-md-7">
							<label class="form-label">{{ t("Amount") }} ({{ form.send_currency }})</label>
							<MoneyInput v-model="form.amount" :currency="form.send_currency" />
						</div>

						<div class="col-md-5">
							<label class="form-label">{{ t("Commission %") }}</label>
							<div class="input-group">
								<input
									v-model.number="form.commission_percent"
									type="number"
									inputmode="decimal"
									min="0"
									step="0.1"
									class="form-control"
									placeholder="0"
								/>
								<span class="input-group-text">%</span>
							</div>
						</div>

						<div class="col-12">
							<label class="form-label">{{ t("Commission mode") }}</label>
							<div class="btn-group" role="group">
								<input
									id="mode-exclusive"
									v-model="form.commission_mode"
									type="radio"
									class="btn-check"
									value="exclusive"
								/>
								<label class="btn btn-outline-secondary btn-sm" for="mode-exclusive">
									{{ t("Exclusive") }}
								</label>
								<input
									id="mode-inclusive"
									v-model="form.commission_mode"
									type="radio"
									class="btn-check"
									value="inclusive"
								/>
								<label class="btn btn-outline-secondary btn-sm" for="mode-inclusive">
									{{ t("Inclusive") }}
								</label>
							</div>
							<div class="form-text text-secondary">
								<template v-if="form.commission_mode === 'inclusive'">
									{{ t("Inclusive: commission deducted from amount — receiver gets less.") }}
								</template>
								<template v-else>
									{{ t("Exclusive: commission added on top — sender pays more.") }}
								</template>
							</div>
						</div>

						<!-- Inline preview -->
						<div v-if="preview" class="col-12">
							<div class="card bg-light border-0">
								<div class="card-body py-2 px-3">
									<dl class="row mb-0 g-1">
										<dt class="col-7 text-secondary small">{{ t("Commission fee") }}</dt>
										<dd class="col-5 text-end font-monospace small text-primary">
											{{ formatMoney(preview.commissionKept, form.send_currency) }}
										</dd>
										<dt class="col-7 text-secondary small">{{ t("Sender pays") }}</dt>
										<dd class="col-5 text-end font-monospace small fw-semibold">
											{{ formatMoney(preview.senderPays, form.send_currency) }}
										</dd>
										<dt class="col-7 text-secondary small">{{ t("Receiver gets") }}</dt>
										<dd class="col-5 text-end font-monospace small text-success fw-semibold">
											{{ formatMoney(preview.receiverGets, form.receive_currency) }}
										</dd>
									</dl>
								</div>
							</div>
						</div>

						<div class="col-12 d-flex justify-content-between mt-2">
							<button type="button" class="btn btn-outline-secondary" @click="prevStep">
								<i class="ti ti-arrow-left me-1"></i>{{ t("Back") }}
							</button>
							<button
								type="button"
								class="btn btn-primary"
								:disabled="!step2Valid"
								@click="nextStep"
							>
								{{ t("Next") }} <i class="ti ti-arrow-right ms-1"></i>
							</button>
						</div>
					</div>

					<!-- ── Step 3: Accounts ─────────────────────────────────────── -->
					<div v-if="step === 3" class="row g-3">
						<div class="col-12">
							<label class="form-label">{{ t("Cash-in account") }}</label>
							<Select
								v-model="form.cash_in_account"
								:options="cashAccounts"
								value-key="name"
								label-key="name"
								:placeholder="t('Select account…')"
							/>
						</div>
						<div class="col-12">
							<label class="form-label">{{ t("Payout account") }}</label>
							<Select
								v-model="form.payout_account"
								:options="payoutAccounts"
								value-key="name"
								label-key="name"
								:placeholder="t('Select account…')"
							/>
						</div>
						<div class="col-12">
							<label class="form-label">{{ t("Commission income account") }}</label>
							<Select
								v-model="form.commission_account"
								:options="commissionAccounts"
								value-key="name"
								label-key="name"
								:placeholder="t('Select account…')"
							/>
						</div>

						<div class="col-md-6">
							<label class="form-label">{{ t("Sender name") }}</label>
							<input v-model="form.sender_name" type="text" class="form-control" />
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Receiver name") }}</label>
							<input v-model="form.receiver_name" type="text" class="form-control" />
						</div>
						<div class="col-12">
							<label class="form-label">{{ t("Memo") }}</label>
							<input v-model="form.memo" type="text" class="form-control" />
						</div>

						<!-- Final preview summary -->
						<div v-if="preview" class="col-12">
							<div class="card bg-light border-0">
								<div class="card-body py-2 px-3">
									<div class="small fw-semibold text-secondary mb-1">
										{{ selectedCorridor ? `${selectedCorridor.from_city} → ${selectedCorridor.to_city}` : "" }}
									</div>
									<dl class="row mb-0 g-1">
										<dt class="col-7 text-secondary small">{{ t("Commission fee") }}</dt>
										<dd class="col-5 text-end font-monospace small text-primary">
											{{ formatMoney(preview.commissionKept, form.send_currency) }}
											<span class="text-muted">({{ form.commission_percent }}%)</span>
										</dd>
										<dt class="col-7 text-secondary small">{{ t("Sender pays") }}</dt>
										<dd class="col-5 text-end font-monospace small fw-semibold">
											{{ formatMoney(preview.senderPays, form.send_currency) }}
										</dd>
										<dt class="col-7 text-secondary small">{{ t("Receiver gets") }}</dt>
										<dd class="col-5 text-end font-monospace small text-success fw-semibold">
											{{ formatMoney(preview.receiverGets, form.receive_currency) }}
										</dd>
									</dl>
								</div>
							</div>
						</div>

						<div class="col-12 d-flex justify-content-between mt-2">
							<button type="button" class="btn btn-outline-secondary" @click="prevStep">
								<i class="ti ti-arrow-left me-1"></i>{{ t("Back") }}
							</button>
							<button
								type="button"
								class="btn btn-primary"
								:disabled="submitting"
								@click="submit"
							>
								<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
								<i v-else class="ti ti-check me-1"></i>{{ t("Post transfer") }}
							</button>
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
