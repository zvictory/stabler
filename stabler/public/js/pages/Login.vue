<script setup>
// Login — the one screen every user meets before anything else.
//
// Migrated to the Modernist Tabler layer. The design measured out to the same
// tokens the rest of the layer already uses (Archivo + mono, #1d273b / #667382
// / #9099a6, the dark panel is --ds-ink), so no new colour system was needed.
//
// Two elements from the design are deliberately NOT here: "sign in with company
// SSO" and "forgot my password". Stabler has neither -- `reset_password` is an
// admin action that takes a username, not a self-service flow -- and a control
// that does nothing is worse than an absent one.
import { computed, nextTick, ref } from "vue";
import { useRoute } from "vue-router";
import { login } from "../api/auth.js";
import { hardRedirect, sanitizeStablerRedirect } from "../composables/authRedirect.js";
import { t } from "../composables/i18n.js";
import AuthTransitionOverlay from "../components/AuthTransitionOverlay.vue";

const route = useRoute();

const username = ref("");
const password = ref("");
const showPassword = ref(false);
const rememberMe = ref(true);

const loading = ref(false);
const transitioning = ref(false);
const error = ref("");
const errorSummary = ref(null);

const sessionExpired = route.query["session-expired"] === "1";

/* Dil seçimi. Sunucu tarafı `?lang=` parametresini beyaz listeyle okuyor
 * (www/stabler.py) ve YALNIZ giriş yapmamış kullanıcıya uyguluyor — oturum
 * açan kişinin dili kendi User kaydından gelir.
 *
 * Seçim tam sayfa yeniden yükleme gerektiriyor: çeviriler sunucuda shell'e
 * gömülüyor, istemcide bir sözlük yok. Router ile değiştirmek metni
 * değiştirmez, o yüzden bilerek hardRedirect. */
const LANGUAGES = [
	{ id: "tr", label: "TR" },
	{ id: "uz", label: "UZ" },
	{ id: "ru", label: "RU" },
	{ id: "en", label: "EN" },
];

const currentLanguage = computed(() => {
	const shell = window.__STABLER__?.user?.language || "en";
	return LANGUAGES.some((l) => l.id === shell) ? shell : "en";
});

function switchLanguage(event) {
	const next = event.target.value;
	if (next === currentLanguage.value) return;
	const url = new URL(window.location.toString());
	url.searchParams.set("lang", next);
	// Hash rotayı koru: kullanıcı login'de kalsın, redirect-to kaybolmasın.
	window.location.assign(url.toString());
}

/* Parola alanının altındaki gösterge KUVVET ÖLÇMÜYOR. Bu bir giriş formu:
 * kullanıcı zaten var olan bir parolayı yazıyor, ona "zayıf" demek anlamsız.
 * Gösterge yalnızca "yazmaya başladın" geri bildirimi veriyor. */
const typedSegments = computed(() => {
	const n = password.value.length;
	if (!n) return 0;
	return Math.min(4, Math.ceil(n / 3));
});

async function handleLogin() {
	if (!username.value.trim() || !password.value) {
		error.value = t("Please enter both username/email and password.");
		await nextTick();
		errorSummary.value?.focus();
		return;
	}

	loading.value = true;
	error.value = "";

	try {
		await login(username.value.trim(), password.value, rememberMe.value);
		transitioning.value = true;
		const target = sanitizeStablerRedirect(route.query["redirect-to"]);
		hardRedirect(target);
	} catch (err) {
		transitioning.value = false;
		error.value = err?.message || t("Invalid username or password.");
		await nextTick();
		errorSummary.value?.focus();
	} finally {
		if (!transitioning.value) loading.value = false;
	}
}

const busy = computed(() => loading.value || transitioning.value);
</script>

<template>
	<div class="login stbl-ds">
		<AuthTransitionOverlay
			v-if="transitioning"
			:title="t('Session opened')"
			:message="t('Preparing your Dashboard…')"
		/>

		<!-- Sol panel: marka ve vaat. Izgara çizgileri dekoratif, aria-hidden. -->
		<aside class="login-brand">
			<div class="login-grid" aria-hidden="true"></div>

			<header class="login-brand-head">
				<span class="login-mark" aria-hidden="true"></span>
				<span class="login-wordmark">Stabler</span>
				<span class="login-brand-sep" aria-hidden="true"></span>
				<span class="ds-label">{{ t("ERP Platform") }}</span>
			</header>

			<div class="login-pitch">
				<div class="ds-label login-modules">
					{{ t("Sales · Purchasing · Warehouse · Production · Finance") }}
				</div>
				<h1>{{ t("One business,") }}<br />{{ t("one record.") }}</h1>
				<p>
					{{ t("Orders, stock, purchasing, production and accounting run on one data model. Every number on screen has a document behind it.") }}
				</p>

				<div class="login-features">
					<div class="login-feature">
						<div class="login-feature-t">{{ t("One data model") }}</div>
						<div class="ds-label">{{ t("tied to a document") }}</div>
					</div>
					<div class="login-feature">
						<div class="login-feature-t">{{ t("Role-based access") }}</div>
						<div class="ds-label">{{ t("permission checked") }}</div>
					</div>
					<div class="login-feature">
						<div class="login-feature-t">{{ t("Audit trail") }}</div>
						<div class="ds-label">{{ t("every action recorded") }}</div>
					</div>
				</div>
			</div>

			<footer class="login-brand-foot ds-label">
				<span>Stabler ERP</span><span class="login-brand-sep" aria-hidden="true"></span><span>v0.1</span>
			</footer>
		</aside>

		<!-- Sağ panel: form -->
		<main class="login-form-col">
			<div class="login-form">
				<div class="login-eyebrow">
					<span class="ds-label">{{ t("Sign in") }}</span>
					<span class="login-rule" aria-hidden="true"></span>
				</div>

				<h2>{{ t("Sign in to your account") }}</h2>
				<p class="login-lede">{{ t("No account? Ask your system administrator for an invite.") }}</p>

				<div v-if="sessionExpired && !error" class="login-notice" data-tone="today" role="status">
					{{ t("Your session has expired. Please sign in again.") }}
				</div>

				<div
					v-if="error"
					id="login-error"
					ref="errorSummary"
					tabindex="-1"
					class="login-notice"
					data-tone="crit"
					role="alert"
				>
					{{ error }}
				</div>

				<form novalidate @submit.prevent="handleLogin">
					<div class="ds-field login-field">
						<label for="login-user">
							{{ t("Username or Email") }} <span class="ds-field-req">*</span>
						</label>
						<div class="login-input" :data-invalid="error ? 'true' : null">
							<svg class="login-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
								stroke-width="1.7" aria-hidden="true">
								<circle cx="12" cy="8" r="3.4" /><path d="M5 20c0-3.4 3.1-5.6 7-5.6s7 2.2 7 5.6" />
							</svg>
							<input
								id="login-user"
								v-model="username"
								type="text"
								:placeholder="t('name.surname or name@company.uz')"
								autocomplete="username"
								:aria-invalid="error ? 'true' : null"
								:aria-describedby="error ? 'login-error' : null"
								:disabled="busy"
							/>
						</div>
					</div>

					<div class="ds-field login-field">
						<label for="login-pass">
							{{ t("Password") }} <span class="ds-field-req">*</span>
						</label>
						<div class="login-input" :data-invalid="error ? 'true' : null">
							<svg class="login-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
								stroke-width="1.7" aria-hidden="true">
								<rect x="5" y="10.5" width="14" height="9.5" /><path d="M8.2 10.5V7.8a3.8 3.8 0 0 1 7.6 0v2.7" />
							</svg>
							<input
								id="login-pass"
								v-model="password"
								:type="showPassword ? 'text' : 'password'"
								:placeholder="t('enter password')"
								autocomplete="current-password"
								:aria-invalid="error ? 'true' : null"
								:aria-describedby="error ? 'login-error' : null"
								:disabled="busy"
							/>
							<button
								type="button"
								class="login-eye"
								:aria-label="showPassword ? t('Hide password') : t('Show password')"
								:aria-pressed="String(showPassword)"
								:disabled="busy"
								@click="showPassword = !showPassword"
							>
								<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
									<path d="M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12Z" />
									<circle cx="12" cy="12" r="2.9" />
									<path v-if="showPassword" d="M4 20 20 4" />
								</svg>
							</button>
						</div>
						<div class="login-typed" aria-hidden="true">
							<span class="login-typed-bars">
								<i v-for="i in 4" :key="i" :data-on="i <= typedSegments ? '1' : null"></i>
							</span>
							<span class="ds-mono login-typed-txt">
								{{ password.length ? t("password entered") : t("enter password") }}
							</span>
						</div>
					</div>

					<div class="login-row">
						<label class="login-remember">
							<input v-model="rememberMe" type="checkbox" :disabled="busy" />
							<span>{{ t("Remember me on this device") }}</span>
						</label>

						<span class="login-lang">
							<label class="ds-label" for="login-lang">{{ t("Language") }}</label>
							<select
								id="login-lang"
								class="ds-input login-lang-select"
								:value="currentLanguage"
								:disabled="busy"
								@change="switchLanguage"
							>
								<option v-for="l in LANGUAGES" :key="l.id" :value="l.id">{{ l.label }}</option>
							</select>
						</span>
					</div>

					<button type="submit" class="ds-btn ds-btn--primary login-submit" :disabled="loading || transitioning">
						{{ (loading || transitioning) ? t("Signing in…") : t("Sign in") }}
					</button>
				</form>

				<footer class="login-foot">
					<span class="ds-mono">Stabler Platform · v0.1</span>
				</footer>
			</div>
		</main>
	</div>
</template>

<style scoped>
/* Görsel dil stabler-modernist.css'ten. Buradakiler bu ekrana özgü
 * yerleşim ve tek kullanımlık parçalar (ızgara dokusu, göz butonu). */
.login {
	display: grid;
	grid-template-columns: 1fr 560px;
	min-height: 100vh;
	background: var(--ds-surface);
}

/* ── Sol panel ─────────────────────────────────────────────────────────── */
.login-brand {
	position: relative;
	display: flex;
	flex-direction: column;
	justify-content: space-between;
	background: var(--ds-ink);
	color: #fff;
	padding: 48px 56px;
	overflow: hidden;
}

/* Izgara dokusu tek bir tekrarlayan degrade — DOM'a yüzlerce çizgi
 * eklemekten hem ucuz hem de ekran okuyucuya görünmez. */
.login-grid {
	position: absolute;
	inset: 0;
	background-image:
		linear-gradient(to right, rgba(255, 255, 255, 0.05) 1px, transparent 1px),
		linear-gradient(to bottom, rgba(255, 255, 255, 0.05) 1px, transparent 1px);
	background-size: 56px 56px;
	background-position: 56px 0;
	pointer-events: none;
}

.login-brand-head,
.login-pitch,
.login-brand-foot {
	position: relative;
}

.login-brand-head {
	display: flex;
	align-items: center;
	gap: 14px;
}

.login-mark {
	width: 26px;
	height: 26px;
	background: var(--ds-acc);
	display: block;
	flex: none;
}

.login-wordmark {
	font-family: var(--ds-font-head);
	font-weight: 800;
	font-size: 23px;
	letter-spacing: -0.02em;
}

.login-brand-sep {
	width: 1px;
	height: 15px;
	background: rgba(255, 255, 255, 0.25);
	display: inline-block;
}

.login-brand .ds-label {
	color: rgba(255, 255, 255, 0.55);
}

.login-modules {
	color: #7aa9e0;
}

.login-pitch h1 {
	font-family: var(--ds-font-head);
	font-weight: 800;
	font-size: 60px;
	line-height: 1.0;
	letter-spacing: -0.03em;
	margin: 18px 0 0;
	color: #fff;
}

.login-pitch p {
	font-size: 16.5px;
	line-height: 1.55;
	color: rgba(255, 255, 255, 0.72);
	margin: 22px 0 0;
	max-width: 34em;
}

.login-features {
	display: grid;
	grid-template-columns: repeat(3, minmax(0, 1fr));
	gap: 1px;
	background: rgba(255, 255, 255, 0.16);
	border: 1px solid rgba(255, 255, 255, 0.16);
	margin-top: 40px;
	max-width: 540px;
}

.login-feature {
	background: var(--ds-ink);
	padding: 16px 17px 17px;
}

.login-feature-t {
	font-family: var(--ds-font-head);
	font-weight: 800;
	font-size: 15px;
	margin-bottom: 6px;
}

.login-brand-foot {
	display: flex;
	align-items: center;
	gap: 12px;
	color: rgba(255, 255, 255, 0.45);
}

/* ── Sağ panel ─────────────────────────────────────────────────────────── */
.login-form-col {
	display: flex;
	align-items: center;
	justify-content: center;
	padding: 40px 48px;
}

.login-form {
	width: 100%;
	max-width: 404px;
}

.login-eyebrow {
	display: flex;
	align-items: center;
	gap: 14px;
}

.login-rule {
	flex: 1;
	height: 1px;
	background: var(--ds-ln);
}

.login-form h2 {
	font-family: var(--ds-font-head);
	font-weight: 800;
	font-size: 31px;
	letter-spacing: -0.025em;
	margin: 24px 0 0;
	color: var(--ds-tx);
}

.login-lede {
	font-size: 14px;
	color: var(--ds-tx2);
	margin: 10px 0 0;
}

.login-notice {
	margin-top: 20px;
	padding: 11px 14px;
	font-size: 13px;
	border: 1px solid;
	border-left-width: 3px;
}

.login-notice[data-tone="crit"] {
	color: var(--ds-crit-tx);
	border-color: var(--ds-crit);
	background: var(--ds-crit-t);
}

.login-notice[data-tone="today"] {
	color: var(--ds-today-tx);
	border-color: var(--ds-today);
	background: var(--ds-today-t);
}

.login-field {
	margin-top: 22px;
}

/* İkon ve göz butonu alanın İÇİNDE; kenarlık sarmalayıcıda, girdide değil.
 * Böylece odak halkası tüm kutuyu çeviriyor. */
.login-input {
	display: flex;
	align-items: center;
	border: 1px solid var(--ds-ln2);
	background: var(--ds-surface);
}

.login-input:focus-within {
	outline: 2px solid var(--ds-acc);
	outline-offset: -2px;
}

/* A rejected login only spoke through the summary above the form. The fields it
 * refers to stayed visually untouched, so anyone not reading the summary — or
 * scrolled past it — saw nothing wrong. Mark the fields themselves too.
 * Colour is not the only channel: the inputs also carry aria-invalid and point
 * at the summary through aria-describedby, per the layer's severity rule
 * (colour + form + label, never colour alone). */
.login-input[data-invalid] {
	border-color: var(--ds-crit);
}

.login-input[data-invalid]:focus-within {
	outline-color: var(--ds-crit);
}

.login-icon {
	width: 18px;
	height: 18px;
	flex: none;
	margin: 0 10px 0 13px;
	color: var(--ds-tx3);
}

.login-input input {
	flex: 1;
	min-width: 0;
	height: 44px;
	border: 0;
	background: none;
	font: inherit;
	font-size: 15px;
	color: var(--ds-tx);
	padding: 0 4px 0 0;
}

.login-input input:focus {
	outline: none;
}

.login-input input::placeholder {
	color: var(--ds-tx3);
}

.login-eye {
	flex: none;
	width: 40px;
	height: 40px;
	display: flex;
	align-items: center;
	justify-content: center;
	border: 0;
	background: none;
	color: var(--ds-tx3);
	cursor: pointer;
}

.login-eye svg {
	width: 18px;
	height: 18px;
}

.login-eye:hover {
	color: var(--ds-tx2);
}

.login-typed {
	display: flex;
	align-items: center;
	gap: 10px;
	margin-top: 9px;
}

.login-typed-bars {
	display: flex;
	gap: 4px;
}

.login-typed-bars i {
	width: 26px;
	height: 3px;
	display: block;
	background: var(--ds-ln);
}

.login-typed-bars i[data-on="1"] {
	background: var(--ds-acc);
}

.login-typed-txt {
	font-size: 10.5px;
	color: var(--ds-tx3);
}

.login-row {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 16px;
	margin-top: 26px;
}

.login-remember {
	display: flex;
	align-items: center;
	gap: 9px;
	font-size: 14px;
	color: var(--ds-tx);
	cursor: pointer;
}

.login-remember input {
	width: 17px;
	height: 17px;
	accent-color: var(--ds-acc);
	flex: none;
}

.login-lang {
	display: flex;
	align-items: center;
	gap: 9px;
}

.login-lang-select {
	width: auto;
	min-height: 34px;
	padding: 5px 8px;
	font-size: 12px;
}

.login-submit {
	width: 100%;
	justify-content: center;
	min-height: 50px;
	font-size: 16px;
	margin-top: 24px;
}

.login-foot {
	display: flex;
	align-items: center;
	justify-content: space-between;
	margin-top: 28px;
	padding-top: 18px;
	border-top: 1px solid var(--ds-ln);
	font-size: 10.5px;
	color: var(--ds-tx3);
}

/* ── Dar ekran: marka paneli kısalır, form altına iner ─────────────────── */
@media (max-width: 992px) {
	.login {
		grid-template-columns: 1fr;
	}

	.login-brand {
		padding: 32px 28px 36px;
	}

	.login-pitch h1 {
		font-size: 38px;
	}

	.login-features {
		grid-template-columns: 1fr;
		margin-top: 26px;
	}

	.login-brand-foot {
		display: none;
	}

	.login-form-col {
		padding: 32px 28px 44px;
	}
}
</style>
