<script setup>
import { ref, computed } from "vue";
import { useRouter, useRoute } from "vue-router";
import { useSession } from "../stores/session.js";
import { call } from "../api/client.js";
import { t } from "../composables/i18n.js";

const router = useRouter();
const route = useRoute();
const session = useSession();

const username = ref("");
const password = ref("");
const showPassword = ref(false);
const rememberMe = ref(true);

const loading = ref(false);
const error = ref("");

async function handleLogin() {
	if (!username.value.trim() || !password.value) {
		error.value = t("Please enter both username/email and password.");
		return;
	}

	loading.value = true;
	error.value = "";

	try {
		const params = new URLSearchParams();
		params.append("usr", username.value.trim());
		params.append("pwd", password.value);

		const response = await fetch("/api/method/login", {
			method: "POST",
			credentials: "same-origin",
			headers: {
				Accept: "application/json",
				"Content-Type": "application/x-www-form-urlencoded",
			},
			body: params.toString(),
		});

		const res = await response.json();

		if (response.ok && res.message === "Logged In") {
			const redirectTo = route.query["redirect-to"] || "/dashboard";
			const targetHash = redirectTo.startsWith("/") ? redirectTo : "/" + redirectTo;
			window.location.href = `/stabler#${targetHash}`;
			window.location.reload();
		} else {
			let msg = res.message || t("Invalid username or password.");
			if (res._server_messages) {
				try {
					const parsed = JSON.parse(res._server_messages);
					if (Array.isArray(parsed) && parsed.length > 0) {
						const item = typeof parsed[0] === "string" ? JSON.parse(parsed[0]) : parsed[0];
						msg = item.message || msg;
					}
				} catch (_) {}
			}
			error.value = msg;
		}
	} catch (err) {
		error.value = err?.message || t("Invalid username or password.");
	} finally {
		loading.value = false;
	}
}
</script>

<template>
	<div class="login-wrapper">
		<!-- Dynamic Dark Slate Gradient Background Overlay -->
		<div class="bg-glow bg-glow-1"></div>
		<div class="bg-glow bg-glow-2"></div>

		<div class="login-container">
			<!-- Glassmorphism Main Card -->
			<div class="login-card">
				<!-- Brand Header -->
				<div class="brand-section">
					<div class="brand-badge">
						<i class="ti ti-scale text-primary fs-1"></i>
					</div>
					<h1 class="brand-title">Stabler</h1>
					<p class="brand-subtitle">{{ t("Financial operations, simplified") }}</p>
				</div>

				<!-- Alert Error Message -->
				<div v-if="error" class="alert alert-danger shadow-sm border-0 d-flex align-items-center gap-2 mb-4" role="alert">
					<i class="ti ti-alert-circle fs-3 text-danger flex-shrink-0"></i>
					<div class="small fw-medium">{{ error }}</div>
				</div>

				<!-- Login Form -->
				<form @submit.prevent="handleLogin">
					<div class="form-group mb-3">
						<label class="form-label required">{{ t("Username or Email") }}</label>
						<div class="input-icon-wrapper">
							<i class="ti ti-user input-icon"></i>
							<input
								v-model="username"
								type="text"
								class="form-control custom-input"
								:placeholder="t('enter username or email…')"
								autocomplete="username"
								required
								:disabled="loading"
							/>
						</div>
					</div>

					<div class="form-group mb-4">
						<div class="d-flex justify-content-between align-items-center mb-1">
							<label class="form-label required m-0">{{ t("Password") }}</label>
						</div>
						<div class="input-icon-wrapper">
							<i class="ti ti-lock input-icon"></i>
							<input
								v-model="password"
								:type="showPassword ? 'text' : 'password'"
								class="form-control custom-input pe-5"
								:placeholder="t('••••••••')"
								autocomplete="current-password"
								required
								:disabled="loading"
							/>
							<button
								type="button"
								class="btn-toggle-eye"
								tabindex="-1"
								@click="showPassword = !showPassword"
							>
								<i :class="showPassword ? 'ti ti-eye-off' : 'ti ti-eye'"></i>
							</button>
						</div>
					</div>

					<div class="d-flex align-items-center justify-content-between mb-4">
						<label class="form-check custom-checkbox m-0">
							<input v-model="rememberMe" type="checkbox" class="form-check-input" />
							<span class="form-check-label text-secondary small fw-medium">{{ t("Remember me") }}</span>
						</label>
					</div>

					<button type="submit" class="btn btn-primary btn-submit w-100" :disabled="loading">
						<span v-if="loading" class="spinner-border spinner-border-sm me-2" role="status"></span>
						<span v-else><i class="ti ti-login me-1"></i></span>
						{{ loading ? t("Signing in…") : t("Sign In to Stabler") }}
					</button>
				</form>

				<div class="login-footer text-center mt-4 pt-3 border-top border-slate">
					<span class="small text-muted font-monospace">Stabler Platform · v0.1</span>
				</div>
			</div>
		</div>
	</div>
</template>

<style scoped>
.login-wrapper {
	min-height: 100vh;
	width: 100%;
	background: #0f172a; /* Deep Slate Background */
	display: flex;
	align-items: center;
	justify-content: center;
	padding: 20px;
	position: relative;
	overflow: hidden;
	font-family: 'Inter', system-ui, -apple-system, sans-serif;
}

/* Ambient Background Glows */
.bg-glow {
	position: absolute;
	border-radius: 50%;
	filter: blur(100px);
	opacity: 0.25;
	pointer-events: none;
}
.bg-glow-1 {
	top: -10%;
	left: -10%;
	width: 500px;
	height: 500px;
	background: radial-gradient(circle, #2563eb 0%, transparent 70%);
}
.bg-glow-2 {
	bottom: -10%;
	right: -10%;
	width: 600px;
	height: 600px;
	background: radial-gradient(circle, #10b981 0%, transparent 70%);
}

.login-container {
	width: 100%;
	max-width: 440px;
	z-index: 10;
}

/* Glassmorphism Card Styling */
.login-card {
	background: rgba(30, 41, 59, 0.75);
	backdrop-filter: blur(16px);
	-webkit-backdrop-filter: blur(16px);
	border: 1px solid rgba(255, 255, 255, 0.1);
	border-radius: 24px;
	padding: 40px 36px;
	box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
}

/* Brand Section */
.brand-section {
	text-align: center;
	margin-bottom: 28px;
}
.brand-badge {
	width: 64px;
	height: 64px;
	background: linear-gradient(135deg, rgba(37, 99, 235, 0.2), rgba(16, 185, 129, 0.2));
	border: 1px solid rgba(147, 197, 253, 0.3);
	border-radius: 18px;
	display: flex;
	align-items: center;
	justify-content: center;
	margin: 0 auto 16px;
	box-shadow: 0 8px 16px rgba(0, 0, 0, 0.2);
}
.brand-title {
	font-size: 28px;
	font-weight: 800;
	color: #ffffff;
	letter-spacing: -0.02em;
	margin-bottom: 4px;
}
.brand-subtitle {
	font-size: 13px;
	color: #94a3b8;
	font-weight: 500;
}

/* Input Fields & Icons */
.form-label {
	font-size: 12px;
	font-weight: 700;
	text-transform: uppercase;
	color: #cbd5e1;
	letter-spacing: 0.04em;
	margin-bottom: 6px;
}

.input-icon-wrapper {
	position: relative;
	display: flex;
	align-items: center;
}

.input-icon {
	position: absolute;
	left: 14px;
	color: #64748b;
	font-size: 18px;
	pointer-events: none;
}

.custom-input {
	background: rgba(15, 23, 42, 0.6) !important;
	border: 1px solid rgba(255, 255, 255, 0.12) !important;
	border-radius: 12px !important;
	color: #ffffff !important;
	padding: 12px 14px 12px 42px !important;
	font-size: 14px !important;
	transition: all 0.2s ease !important;
}

.custom-input:focus {
	border-color: #3b82f6 !important;
	box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.2) !important;
	background: rgba(15, 23, 42, 0.85) !important;
}

.custom-input::placeholder {
	color: #64748b;
}

.btn-toggle-eye {
	position: absolute;
	right: 12px;
	background: transparent;
	border: none;
	color: #94a3b8;
	font-size: 18px;
	cursor: pointer;
	padding: 4px;
	display: flex;
	align-items: center;
	justify-content: center;
	transition: color 0.2s;
}
.btn-toggle-eye:hover {
	color: #ffffff;
}

.custom-checkbox .form-check-input {
	background-color: rgba(15, 23, 42, 0.6);
	border-color: rgba(255, 255, 255, 0.2);
	border-radius: 4px;
}
.custom-checkbox .form-check-input:checked {
	background-color: #2563eb;
	border-color: #2563eb;
}

/* Submit Button */
.btn-submit {
	background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
	border: none;
	border-radius: 12px;
	padding: 14px;
	font-size: 15px;
	font-weight: 700;
	color: #ffffff;
	letter-spacing: 0.02em;
	box-shadow: 0 4px 14px rgba(37, 99, 235, 0.4);
	transition: all 0.2s ease;
}
.btn-submit:hover:not(:disabled) {
	background: linear-gradient(135deg, #1d4ed8 0%, #1e40af 100%);
	box-shadow: 0 6px 20px rgba(37, 99, 235, 0.6);
	transform: translateY(-1px);
}

.border-slate {
	border-color: rgba(255, 255, 255, 0.08) !important;
}
</style>
