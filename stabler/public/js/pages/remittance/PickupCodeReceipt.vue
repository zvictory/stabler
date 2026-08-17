<script setup>
/**
 * Pickup-code receipt — the one and only time the plaintext code is readable.
 *
 * The server stores `pickup_code_hash` and hands the plaintext back on the
 * registering call alone (`remittance_commands._result`); every read path in the
 * product is guarded by `assert_no_pickup_code`. So this component is the last
 * place the code exists, and losing it means the receiver cannot be paid.
 *
 * Consequences that are deliberate, not incidental:
 *   - This is a CHILD COMPONENT, not a route. A route would put the transfer id
 *     in the URL and would re-mount empty on reload; worse, any router state
 *     carrying the code would outlive the moment it was allowed to exist. The
 *     code arrives as a prop, lives in the parent's component state, and the
 *     parent drops it when `acknowledge` fires.
 *   - Nothing here writes the code to localStorage, sessionStorage, the URL, a
 *     console line, or an error message. `copyFailed` says that the copy failed
 *     and does not say what was being copied — echoing the code into a toast
 *     would put it in the DOM of every screen that toast survives on.
 *   - A REPLAY carries no code. `register_remittance` answers a reused
 *     `client_request_id` with `pickup_code: null`, because the code was shown
 *     once already. That case renders as a stated fact, never as an empty box
 *     the cashier might read as "the code is blank".
 */
import { computed, onBeforeUnmount, ref } from "vue";
import { onBeforeRouteLeave } from "vue-router";
import { t, tlang } from "../../composables/i18n.js";
import { formatMoney } from "../../composables/money.js";
import { useConfirm } from "../../composables/useConfirm.js";

const props = defineProps({
	remittanceId: { type: String, default: "" },
	// Empty means "the server did not issue one on this call" — see `replayed`.
	pickupCode: { type: String, default: "" },
	replayed: { type: Boolean, default: false },
	receiverName: { type: String, default: "" },
	receiverAmount: { type: [Number, null], default: null },
	receiveCurrency: { type: String, default: "" },
});

const emit = defineEmits(["acknowledge"]);

const acknowledged = ref(false);
const copied = ref(false);
const copyFailed = ref(false);

async function copyCode() {
	if (!props.pickupCode) return;
	copyFailed.value = false;
	try {
		await navigator.clipboard.writeText(props.pickupCode);
		copied.value = true;
		setTimeout(() => {
			copied.value = false;
		}, 2000);
	} catch {
		// No logging, no message text carrying the code: the cashier can still
		// read it off the screen, which is the point of this receipt.
		copyFailed.value = true;
	}
}

function printReceipt() {
	window.print();
}

/**
 * Leaving this component destroys the code, so leaving has to be deliberate.
 *
 * The acknowledgement checkbox used to gate one thing only: this card's own
 * button. Everything else was still one click away — the module tab strip is
 * rendered by RemittanceHome OUTSIDE `<router-view>`, so Operations, Payout or
 * any sidebar link unmounted this component and took the only copy of the code
 * with it. The cash was already taken by then, and no read path can give the
 * code back (`assert_no_pickup_code`), which leaves a refund as the only way out.
 *
 * Both exits are covered because they are different exits: `onBeforeRouteLeave`
 * catches every in-app navigation, including the `router.replace` that
 * RemittanceHome fires when the cashier switches to a Legacy company;
 * `beforeunload` catches reload and tab-close, which the router never sees.
 *
 * Deliberate, not an oversight: this ASKS rather than refusing outright. A hard
 * block would strand a cashier whose customer has already walked away, and the
 * escape it would leave them — tick the box — is the one thing they must not do
 * untruthfully. The dialog is `dismissable: false` so it cannot be waved away by
 * a click on the backdrop, and staying is the default answer.
 */
const { confirm } = useConfirm();

// At risk exactly while a code is on screen and has not been acknowledged. A
// replay carries no code, and there is nothing to lose once the box is ticked.
const codeAtRisk = computed(() => !!props.pickupCode && !acknowledged.value);

// Named rather than inlined into the guard so the decision can be executed by a
// test. This repo has no @vue/test-utils, so an inlined arrow could only ever be
// asserted as source text — and a `toContain` passes just as happily for a guard
// wired backwards.
async function mayLeave() {
	if (!codeAtRisk.value) return true;
	return await confirm({
		title: t("Leave without handing over the pickup code?"),
		body: t(
			"This code is shown once and is stored only as a digest — nothing in this system can read it back. Leaving this page destroys the only copy, and the money has already been taken: the transfer would then have to be refunded."
		),
		danger: true,
		confirmLabel: t("Leave and lose the code"),
		cancelLabel: t("Stay on the receipt"),
		dismissable: false,
	});
}

onBeforeRouteLeave(async (to, from, next) => {
	next((await mayLeave()) ? undefined : false);
});

function handleBeforeUnload(event) {
	if (!codeAtRisk.value) return;
	// The browser shows its own wording here; the string is ignored by design.
	event.preventDefault();
	event.returnValue = "";
}

window.addEventListener("beforeunload", handleBeforeUnload);

onBeforeUnmount(() => {
	window.removeEventListener("beforeunload", handleBeforeUnload);
});
</script>

<template>
	<div class="row justify-content-center">
		<div class="col-lg-6">
			<div class="card stbl-receipt">
				<div class="card-body">
					<div class="text-center mb-3">
						<span class="avatar avatar-lg bg-green-lt mb-2"><i class="ti ti-check fs-2"></i></span>
						<h3 class="card-title mb-0">{{ t("Transfer registered") }}</h3>
					</div>

					<div class="mb-3">
						<div class="form-label text-secondary">{{ t("Remittance ID") }}</div>
						<div class="fs-2 font-monospace fw-bold text-break">{{ remittanceId || "—" }}</div>
					</div>

					<!-- The code, or the reason there is none. Never a blank box. -->
					<div v-if="pickupCode" class="mb-3">
						<div class="form-label text-secondary">{{ t("Pickup code") }}</div>
						<div class="stbl-receipt-code font-monospace fw-bold">{{ pickupCode }}</div>
					</div>
					<div v-else class="alert alert-warning" role="alert">
						<template v-if="replayed">
							{{ t("This request was already registered. The pickup code was shown once at that moment and cannot be shown again — a Finance Manager has to reissue the transfer if it was lost.") }}
						</template>
						<template v-else>
							{{ t("The server did not return a pickup code for this call. Do not hand over cash against this transfer until a Finance Manager has checked it.") }}
						</template>
					</div>

					<dl class="row mb-3">
						<dt class="col-6 text-secondary">{{ t("Receiver") }}</dt>
						<dd class="col-6 text-end fw-semibold text-break">{{ receiverName || "—" }}</dd>
						<dt class="col-6 text-secondary">{{ t("Receiver gets") }}</dt>
						<dd class="col-6 text-end font-monospace fw-semibold text-success">
							{{ formatMoney(receiverAmount, receiveCurrency, tlang()) }}
						</dd>
					</dl>

					<div v-if="pickupCode" class="alert alert-important alert-warning">
						{{ t("Hand this code to the sender now. It is shown once and is stored only as a digest — nothing in this system can read it back.") }}
					</div>

					<div class="stbl-receipt-actions">
						<div v-if="pickupCode" class="btn-list mb-3">
							<button type="button" class="btn btn-outline-secondary" @click="copyCode">
								<i class="ti me-1" :class="copied ? 'ti-check' : 'ti-copy'"></i>
								{{ copied ? t("Copied") : t("Copy code") }}
							</button>
							<button type="button" class="btn btn-outline-secondary" @click="printReceipt">
								<i class="ti ti-printer me-1"></i>{{ t("Print") }}
							</button>
						</div>
						<div v-if="copyFailed" class="text-danger small mb-3">
							{{ t("Could not copy to the clipboard. Read the code off this screen instead.") }}
						</div>

						<!-- Mandatory acknowledgement. Skipped only when there is no code
						     to hand over, where asking the cashier to confirm they handed
						     one over would be asking them to confirm something untrue. -->
						<label v-if="pickupCode" class="form-check mb-3">
							<input v-model="acknowledged" class="form-check-input" type="checkbox" />
							<span class="form-check-label">
								{{ t("I handed the code to the sender or wrote it down.") }}
							</span>
						</label>

						<button
							type="button"
							class="btn btn-primary w-100"
							:disabled="!!pickupCode && !acknowledged"
							@click="emit('acknowledge')"
						>
							{{ pickupCode ? t("Done — clear the code") : t("Close") }}
						</button>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>

<style scoped>
.stbl-receipt-code {
	font-size: 2.25rem;
	letter-spacing: 0.35em;
	line-height: 1.2;
	word-break: break-all;
}

/* 40px touch targets on a phone — this screen is used standing at a counter. */
@media (max-width: 575.98px) {
	.stbl-receipt-actions .btn,
	.stbl-receipt-actions .form-check-input {
		min-height: 40px;
	}
	.stbl-receipt-code {
		font-size: 1.75rem;
		letter-spacing: 0.25em;
	}
}

@media print {
	.stbl-receipt-actions {
		display: none !important;
	}
	.stbl-receipt {
		border: none;
		box-shadow: none;
	}
}
</style>
