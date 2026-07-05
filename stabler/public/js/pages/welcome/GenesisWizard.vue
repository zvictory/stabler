<script setup>
// GENESIS onboarding wizard — server-driven (questions come from
// stabler.api.onboarding.wizard_schema), resumable (checkpoint saved per step),
// and frictionless (one question at a time). On completion it provisions the
// company and fires the WP-270 activation funnel, then lands the user on POS.
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { useTelemetry } from "../../composables/useTelemetry.js";
import Select from "../../components/Select.vue";

const router = useRouter();
const toast = useToast();
const { trackOnce, FUNNEL } = useTelemetry();

const loading = ref(true);
const provisioning = ref(false);
const error = ref("");
const questions = ref([]);
const answers = ref({});
const step = ref(0);

const current = computed(() => questions.value[step.value] || null);
const total = computed(() => questions.value.length);
const isLast = computed(() => step.value >= total.value - 1);
const progress = computed(() => (total.value ? Math.round(((step.value + 1) / total.value) * 100) : 0));
const canNext = computed(() => {
	const q = current.value;
	if (!q) return false;
	if (!q.required) return true;
	const v = answers.value[q.key];
	return v !== undefined && v !== null && String(v).trim() !== "";
});

function optionValue(o) { return typeof o === "object" ? o.value : o; }
function optionLabel(o) { return typeof o === "object" ? o.label : o; }

async function saveCheckpoint() {
	// Fire-and-forget checkpoint so a half-finished signup can resume; never blocks.
	try {
		await call("stabler.api.onboarding.save_wizard_state", {
			state: { ...answers.value, step: step.value },
		});
	} catch (_) {
		/* checkpoint is best-effort */
	}
}

async function next() {
	if (!canNext.value) return;
	await saveCheckpoint();
	if (isLast.value) return finish();
	step.value += 1;
}
function back() { if (step.value > 0) step.value -= 1; }

async function finish() {
	provisioning.value = true;
	error.value = "";
	try {
		const res = await call("stabler.api.onboarding.provision", { payload: answers.value });
		// Let the router guard admit us immediately (before the next boot refresh).
		try { localStorage.setItem("stabler.onboarding.completed", "1"); } catch (_) { /* private mode */ }
		// WP-270 activation funnel — signup + wizard completed (once per company).
		trackOnce(FUNNEL.SIGNUP);
		trackOnce(FUNNEL.WIZARD_DONE);
		toast.success(t("Your business is ready."));
		router.push(res?.next || "/pos");
	} catch (err) {
		error.value = err?.message || t("Setup failed. Please try again.");
	} finally {
		provisioning.value = false;
	}
}

onMounted(async () => {
	try {
		const [schema, saved] = await Promise.all([
			call("stabler.api.onboarding.wizard_schema"),
			call("stabler.api.onboarding.get_wizard_state").catch(() => ({ state: {} })),
		]);
		questions.value = schema?.questions || [];
		// Seed defaults, then overlay any resumed checkpoint.
		const seed = {};
		for (const q of questions.value) if (q.default !== undefined) seed[q.key] = q.default;
		const state = saved?.state || {};
		answers.value = { ...seed, ...state };
		if (Number.isInteger(state.step) && state.step < questions.value.length) step.value = state.step;
	} catch (err) {
		error.value = err?.message || t("Could not start setup.");
	} finally {
		loading.value = false;
	}
});
</script>

<template>
	<div class="stbl-genesis d-flex align-items-center justify-content-center py-5">
		<div class="stbl-genesis-card w-100" style="max-width: 560px">
			<div class="text-center mb-4">
				<h1 class="h3 m-0">{{ t("Welcome to Stabler") }}</h1>
				<div class="text-secondary small">{{ t("A few quick questions and you're ready to sell.") }}</div>
			</div>

			<div v-if="loading" class="text-center py-5"><span class="spinner-border text-primary"></span></div>

			<div v-else-if="provisioning" class="text-center py-5">
				<span class="spinner-border text-primary mb-2"></span>
				<div class="text-secondary">{{ t("Setting up your business…") }}</div>
			</div>

			<div v-else-if="current" class="card">
				<div class="card-body">
					<div class="progress mb-3" style="height: 4px">
						<div class="progress-bar" role="progressbar" :style="{ width: progress + '%' }"></div>
					</div>
					<div class="text-secondary small mb-1">{{ t("Step") }} {{ step + 1 }} / {{ total }}</div>

					<label class="form-label fw-medium">{{ current.label }}<span v-if="current.required" class="text-danger ms-1">*</span></label>

					<Select
						v-if="current.type === 'select'"
						v-model="answers[current.key]"
						:options="current.options"
						:value-key="null"
						:placeholder="t('— choose —')"
					>
						<template #option="{ option }">{{ optionLabel(option) }}</template>
						<template #selected="{ option }">{{ optionLabel(option) }}</template>
					</Select>
					<input
						v-else
						v-model="answers[current.key]"
						type="text"
						class="form-control"
						:placeholder="current.hint || ''"
						@keyup.enter="next"
					/>
					<div v-if="current.hint && current.type !== 'text'" class="form-hint">{{ current.hint }}</div>

					<div v-if="error" class="alert alert-danger py-2 mt-3 mb-0">{{ error }}</div>

					<div class="d-flex gap-2 mt-4">
						<button v-if="step > 0" type="button" class="btn btn-outline-secondary" @click="back">
							<i class="ti ti-arrow-left me-1"></i>{{ t("Back") }}
						</button>
						<button type="button" class="btn btn-primary ms-auto" :disabled="!canNext" @click="next">
							{{ isLast ? t("Finish setup") : t("Next") }}
							<i v-if="!isLast" class="ti ti-arrow-right ms-1"></i>
						</button>
					</div>
				</div>
			</div>

			<div v-else-if="error" class="alert alert-danger">{{ error }}</div>
		</div>
	</div>
</template>

<style scoped>
.stbl-genesis {
	min-height: 80vh;
	color: var(--stbl-text, inherit);
}
.progress-bar {
	background: var(--stbl-primary, #206bc4);
}
</style>
