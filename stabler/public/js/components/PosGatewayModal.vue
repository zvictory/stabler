<script setup>
// Dynamic-QR checkout modal for the Uzbek online gateways (Payme / Click /
// Uzum Bank). The cart total is already locked into a POS Payment Session by
// the backend; this modal renders the QR, polls the session, and resolves once
// the provider webhook confirms payment. No Frappe Desk involved.
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { call } from "../api/client.js";
import { formatMoney } from "../composables/money.js";
import { t } from "../composables/i18n.js";

const props = defineProps({
	open: { type: Boolean, default: false },
	payload: { type: Object, default: null },
	language: { type: String, default: "en" },
});

const emit = defineEmits(["paid", "close"]);

const status = ref("Pending");
const invoice = ref(null);
const errorMsg = ref("");
const polling = ref(false);
const secondsLeft = ref(null);

let pollTimer = null;
let tickTimer = null;

const provider = computed(() => props.payload?.provider || "");
const amount = computed(() => Number(props.payload?.amount || 0));
const currency = computed(() => props.payload?.currency || "UZS");
const qrSvg = computed(() => props.payload?.qr_svg || "");
const checkoutUrl = computed(() => props.payload?.checkout_url || "");
const isPending = computed(() => status.value === "Pending");
const isPaid = computed(() => status.value === "Paid");

const statusLabel = computed(() => {
	switch (status.value) {
		case "Paid":
			return t("Payment received");
		case "Cancelled":
			return t("Payment cancelled");
		case "Expired":
			return t("QR code expired");
		case "Failed":
			return t("Payment failed");
		default:
			return t("Waiting for payment…");
	}
});

function stopTimers() {
	clearInterval(pollTimer);
	clearInterval(tickTimer);
	pollTimer = null;
	tickTimer = null;
	polling.value = false;
}

async function poll() {
	if (!props.payload?.session) return;
	try {
		const res = await call("stabler.api.pos.pos_gateway_status", {
			session: props.payload.session,
		});
		status.value = res.status;
		invoice.value = res.sales_invoice || null;
		if (res.status !== "Pending") {
			stopTimers();
			if (res.status === "Paid") {
				// brief beat so the cashier sees the success state
				setTimeout(() => emit("paid", { name: res.sales_invoice }), 900);
			}
		}
	} catch (err) {
		errorMsg.value = err?.message || t("Could not check payment status.");
	}
}

function tick() {
	if (!props.payload?.expires_at) {
		secondsLeft.value = null;
		return;
	}
	const end = new Date(props.payload.expires_at.replace(" ", "T")).getTime();
	secondsLeft.value = Math.max(0, Math.round((end - Date.now()) / 1000));
}

function start() {
	stopTimers();
	status.value = "Pending";
	invoice.value = null;
	errorMsg.value = "";
	polling.value = true;
	tick();
	poll();
	pollTimer = setInterval(poll, 2500);
	tickTimer = setInterval(tick, 1000);
}

async function cancel() {
	stopTimers();
	if (props.payload?.session && isPending.value) {
		try {
			await call("stabler.api.pos.pos_gateway_cancel", { session: props.payload.session });
		} catch {
			// best-effort; closing anyway
		}
	}
	emit("close");
}

function done() {
	stopTimers();
	emit("close");
}

const countdownLabel = computed(() => {
	if (secondsLeft.value == null) return "";
	const m = Math.floor(secondsLeft.value / 60);
	const s = String(secondsLeft.value % 60).padStart(2, "0");
	return `${m}:${s}`;
});

watch(
	() => props.open,
	(open) => {
		if (open && props.payload) start();
		else stopTimers();
	}
);

onBeforeUnmount(stopTimers);
</script>

<template>
	<div v-if="open" class="ice-qr-backdrop" @click.self="cancel">
		<div class="ice-qr-card card" role="dialog" aria-modal="true">
			<header class="ice-qr-head">
				<div>
					<div class="ice-qr-kicker">{{ t("Online payment") }}</div>
					<h3 class="ice-qr-provider">{{ provider }}</h3>
				</div>
				<strong class="ice-qr-amount">{{ formatMoney(amount, currency, language) }}</strong>
			</header>

			<div class="ice-qr-body">
				<div v-if="isPending" class="ice-qr-figure">
					<img v-if="qrSvg" :src="qrSvg" :alt="t('Scan to pay')" class="ice-qr-img" />
					<div v-else class="ice-qr-fallback">
						<i class="ti ti-qrcode"></i>
						<span>{{ t("QR unavailable — open the link below") }}</span>
					</div>
					<a
						v-if="checkoutUrl"
						:href="checkoutUrl"
						target="_blank"
						rel="noopener"
						class="ice-qr-link"
					>{{ t("Open payment link") }}</a>
				</div>

				<div v-else class="ice-qr-result" :class="`ice-qr-result--${status.toLowerCase()}`">
					<i :class="isPaid ? 'ti ti-circle-check' : 'ti ti-alert-circle'"></i>
				</div>

				<div class="ice-qr-status" :class="{ 'is-paid': isPaid }">
					<span v-if="isPending" class="spinner-border spinner-border-sm"></span>
					<span>{{ statusLabel }}</span>
				</div>
				<div v-if="isPending && countdownLabel" class="ice-qr-countdown">
					{{ t("Expires in") }} {{ countdownLabel }}
				</div>
				<div v-if="isPaid && invoice" class="ice-qr-invoice">{{ invoice }}</div>
				<div v-if="errorMsg" class="alert alert-danger mt-2 mb-0">{{ errorMsg }}</div>
			</div>

			<footer class="ice-qr-foot">
				<button v-if="isPending" type="button" class="btn btn-outline-secondary w-100" @click="cancel">
					{{ t("Cancel payment") }}
				</button>
				<button v-else-if="isPaid" type="button" class="btn btn-primary w-100" @click="done">
					{{ t("Done") }}
				</button>
				<button v-else type="button" class="btn btn-outline-secondary w-100" @click="done">
					{{ t("Close") }}
				</button>
			</footer>
		</div>
	</div>
</template>

<style scoped>
.ice-qr-backdrop {
	position: fixed;
	inset: 0;
	z-index: 1080;
	display: grid;
	place-items: center;
	background: rgba(15, 23, 42, 0.55);
	padding: 1rem;
}

.ice-qr-card {
	width: min(420px, 100%);
	display: grid;
	gap: 0;
	background: var(--tblr-card-bg, #ffffff);
	border-color: var(--tblr-border-color, #dadfe5);
}

.ice-qr-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 1rem;
	padding: 1rem 1.25rem;
	border-bottom: 1px solid var(--tblr-border-color, #dadfe5);
}

.ice-qr-kicker {
	color: var(--tblr-secondary, #667382);
	font-size: 0.68rem;
	font-weight: 700;
	letter-spacing: 0.08em;
	text-transform: uppercase;
}

.ice-qr-provider {
	margin: 0.15rem 0 0;
	font-size: 1.25rem;
	font-weight: 900;
}

.ice-qr-amount {
	font-size: 1.35rem;
	font-weight: 900;
	font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
}

.ice-qr-body {
	display: grid;
	justify-items: center;
	gap: 0.75rem;
	padding: 1.5rem 1.25rem;
}

.ice-qr-figure {
	display: grid;
	justify-items: center;
	gap: 0.65rem;
}

.ice-qr-img {
	width: 240px;
	height: 240px;
	border: 1px solid var(--tblr-border-color, #dadfe5);
	border-radius: var(--tblr-border-radius, 4px);
	background: #ffffff;
	padding: 0.5rem;
}

.ice-qr-fallback {
	display: grid;
	justify-items: center;
	gap: 0.5rem;
	width: 240px;
	height: 240px;
	place-content: center;
	border: 1px dashed var(--tblr-border-color, #dadfe5);
	border-radius: var(--tblr-border-radius, 4px);
	color: var(--tblr-secondary, #667382);
	text-align: center;
	padding: 1rem;
}

.ice-qr-fallback i {
	font-size: 2.5rem;
}

.ice-qr-link {
	font-weight: 700;
}

.ice-qr-result {
	display: grid;
	place-items: center;
	width: 240px;
	height: 240px;
}

.ice-qr-result i {
	font-size: 6rem;
}

.ice-qr-result--paid i {
	color: var(--tblr-success, #2fb344);
}

.ice-qr-result--cancelled i,
.ice-qr-result--failed i,
.ice-qr-result--expired i {
	color: var(--tblr-danger, #d63939);
}

.ice-qr-status {
	display: flex;
	align-items: center;
	gap: 0.5rem;
	font-weight: 800;
	color: var(--tblr-secondary, #667382);
}

.ice-qr-status.is-paid {
	color: var(--tblr-success, #2fb344);
}

.ice-qr-countdown {
	color: var(--tblr-secondary, #667382);
	font-size: 0.85rem;
	font-weight: 700;
}

.ice-qr-invoice {
	font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
	font-weight: 800;
}

.ice-qr-foot {
	padding: 1rem 1.25rem;
	border-top: 1px solid var(--tblr-border-color, #dadfe5);
}
</style>
