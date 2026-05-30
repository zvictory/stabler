<script setup>
import { computed, onMounted, ref } from "vue";
import { adminApi } from "../../api/admin.js";
import { t } from "../../composables/i18n.js";
import { formatDateTime } from "../../composables/date.js";
import EmptyState from "../../components/EmptyState.vue";

const loading = ref(false);
const error = ref("");
const users = ref([]);
const roles = ref([]);
const templates = ref([]);

const search = ref("");
const roleFilter = ref("");
const enabledFilter = ref("");

const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);
const drawerError = ref("");
const drawerSaving = ref(false);

const editForm = ref({ full_name: "", enabled: 1, roles: [] });

const inviteOpen = ref(false);
const inviteSubmitting = ref(false);
const inviteError = ref("");
const inviteForm = ref({ email: "", full_name: "", template: "" });

async function load() {
	loading.value = true;
	error.value = "";
	try {
		const args = { limit: 200 };
		if (search.value) args.search = search.value;
		if (roleFilter.value) args.role = roleFilter.value;
		if (enabledFilter.value !== "") args.enabled = enabledFilter.value;
		users.value = await adminApi.listUsers(args);
	} catch (err) {
		error.value = err?.message || "Failed to load users.";
	} finally {
		loading.value = false;
	}
}

async function loadRolesAndTemplates() {
	try {
		const [r, tpl] = await Promise.all([adminApi.listRoles(1), adminApi.listRoleTemplates()]);
		roles.value = r || [];
		templates.value = tpl || [];
	} catch {
		/* non-fatal */
	}
}

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	drawerError.value = "";
	try {
		const u = await adminApi.getUser(name);
		detail.value = u;
		editForm.value = {
			full_name: u.full_name || "",
			enabled: u.enabled,
			roles: [...(u.roles || [])],
		};
	} catch (err) {
		drawerError.value = err?.message || "Failed to load user.";
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	if (drawerSaving.value) return;
	detailOpen.value = false;
	detail.value = null;
}

function toggleRole(roleName) {
	const i = editForm.value.roles.indexOf(roleName);
	if (i >= 0) editForm.value.roles.splice(i, 1);
	else editForm.value.roles.push(roleName);
}

async function saveDetail() {
	if (!detail.value) return;
	drawerSaving.value = true;
	drawerError.value = "";
	try {
		await adminApi.updateUser({
			name: detail.value.name,
			full_name: editForm.value.full_name,
			enabled: editForm.value.enabled ? 1 : 0,
			roles: editForm.value.roles,
		});
		await load();
		detailOpen.value = false;
	} catch (err) {
		drawerError.value = err?.message || "Failed to save.";
	} finally {
		drawerSaving.value = false;
	}
}

async function quickToggleEnabled(user) {
	const next = user.enabled ? 0 : 1;
	try {
		await adminApi.updateUser({ name: user.name, enabled: next });
		user.enabled = next;
	} catch (err) {
		alert(err?.message || "Failed to toggle.");
	}
}

async function applyTemplateToDetail(templateKey) {
	if (!detail.value || !templateKey) return;
	drawerSaving.value = true;
	drawerError.value = "";
	try {
		const updated = await adminApi.applyRoleTemplate(detail.value.name, templateKey);
		detail.value = updated;
		editForm.value.roles = [...(updated.roles || [])];
		await load();
	} catch (err) {
		drawerError.value = err?.message || "Failed to apply template.";
	} finally {
		drawerSaving.value = false;
	}
}

async function resetPasswordForDetail() {
	if (!detail.value) return;
	if (!confirm(t("Send password reset email to ") + detail.value.email + "?")) return;
	try {
		await adminApi.resetPassword(detail.value.name);
		alert(t("Reset email sent."));
	} catch (err) {
		alert(err?.message || "Failed to reset.");
	}
}

function openInvite() {
	inviteForm.value = { email: "", full_name: "", template: "" };
	inviteError.value = "";
	inviteOpen.value = true;
}

function closeInvite() {
	if (inviteSubmitting.value) return;
	inviteOpen.value = false;
}

async function submitInvite() {
	inviteError.value = "";
	if (!inviteForm.value.email || !inviteForm.value.full_name) {
		inviteError.value = t("Email and name are required.");
		return;
	}
	inviteSubmitting.value = true;
	try {
		await adminApi.inviteUser({
			email: inviteForm.value.email.trim(),
			full_name: inviteForm.value.full_name.trim(),
			template: inviteForm.value.template || undefined,
		});
		inviteOpen.value = false;
		await load();
	} catch (err) {
		inviteError.value = err?.message || "Failed to invite.";
	} finally {
		inviteSubmitting.value = false;
	}
}

const formatLastLogin = (ts) => formatDateTime(ts);

onMounted(() => {
	load();
	loadRolesAndTemplates();
});
</script>

<template>
	<div class="card">
		<div class="card-header">
			<div class="card-title">{{ t("Users") }}</div>
			<div class="ms-auto d-flex gap-2 align-items-end">
				<div>
					<label class="form-label small mb-1">{{ t("Search") }}</label>
					<input
						v-model="search"
						type="text"
						class="form-control form-control-sm"
						:placeholder="t('Name or email')"
						@keyup.enter="load"
					/>
				</div>
				<div>
					<label class="form-label small mb-1">{{ t("Role") }}</label>
					<select v-model="roleFilter" class="form-select form-select-sm" @change="load">
						<option value="">{{ t("Any") }}</option>
						<option v-for="r in roles" :key="r.name" :value="r.name">{{ r.name }}</option>
					</select>
				</div>
				<div>
					<label class="form-label small mb-1">{{ t("Status") }}</label>
					<select v-model="enabledFilter" class="form-select form-select-sm" @change="load">
						<option value="">{{ t("Any") }}</option>
						<option value="1">{{ t("Enabled") }}</option>
						<option value="0">{{ t("Disabled") }}</option>
					</select>
				</div>
				<button type="button" class="btn btn-sm btn-outline-primary" @click="load">
					<i class="ti ti-refresh me-1"></i>{{ t("Apply") }}
				</button>
				<button type="button" class="btn btn-sm btn-primary" @click="openInvite">
					<i class="ti ti-user-plus me-1"></i>{{ t("Invite user") }}
				</button>
			</div>
		</div>

		<div v-if="loading" class="card-body text-center py-5">
			<div class="spinner-border text-primary" role="status"></div>
		</div>
		<div v-else-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!users.length"
			icon="ti-users"
			title="No users found"
			subtitle="Adjust filters or invite a new user."
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("Name") }}</th>
						<th>{{ t("Email") }}</th>
						<th>{{ t("Roles") }}</th>
						<th>{{ t("Last login") }}</th>
						<th class="w-1">{{ t("Enabled") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="u in users" :key="u.name" style="cursor: pointer">
						<td @click="openDetail(u.name)">
							<div class="d-flex align-items-center">
								<span
									v-if="u.user_image"
									class="avatar avatar-sm me-2"
									:style="{ backgroundImage: `url('${u.user_image}')` }"
								></span>
								<span v-else class="avatar avatar-sm me-2">
									{{ (u.full_name || u.name).slice(0, 1).toUpperCase() }}
								</span>
								<div class="fw-semibold">{{ u.full_name || u.name }}</div>
							</div>
						</td>
						<td @click="openDetail(u.name)" class="text-secondary">{{ u.email }}</td>
						<td @click="openDetail(u.name)">
							<span
								v-for="r in u.roles"
								:key="r"
								class="badge bg-blue-lt me-1 mb-1"
							>
								{{ r }}
							</span>
						</td>
						<td @click="openDetail(u.name)" class="text-secondary small">
							{{ formatLastLogin(u.last_login) }}
						</td>
						<td>
							<label class="form-check form-switch m-0">
								<input
									class="form-check-input"
									type="checkbox"
									:checked="u.enabled === 1"
									@change.stop="quickToggleEnabled(u)"
								/>
							</label>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<!-- Detail drawer -->
	<div v-if="detailOpen" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div
		v-if="detailOpen"
		class="offcanvas offcanvas-end show"
		tabindex="-1"
		style="visibility: visible; width: 600px"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">
				<i class="ti ti-user me-1"></i>{{ t("User") }}
			</h5>
			<button type="button" class="btn-close" @click="closeDetail"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="drawerError" class="alert alert-danger">{{ drawerError }}</div>
			<div v-else-if="detail">
				<div class="mb-3">
					<label class="form-label small">{{ t("Email") }}</label>
					<input :value="detail.email" type="email" class="form-control" readonly />
				</div>
				<div class="mb-3">
					<label class="form-label small">{{ t("Full name") }}</label>
					<input v-model="editForm.full_name" type="text" class="form-control" />
				</div>
				<div class="mb-3">
					<label class="form-check form-switch">
						<input
							v-model="editForm.enabled"
							class="form-check-input"
							type="checkbox"
							:true-value="1"
							:false-value="0"
						/>
						<span class="form-check-label">{{ t("Enabled") }}</span>
					</label>
				</div>

				<div class="mb-3">
					<label class="form-label small">{{ t("Roles") }}</label>
					<div class="border rounded p-2" style="max-height: 220px; overflow: auto">
						<label
							v-for="r in roles"
							:key="r.name"
							class="form-check"
						>
							<input
								class="form-check-input"
								type="checkbox"
								:checked="editForm.roles.includes(r.name)"
								@change="toggleRole(r.name)"
							/>
							<span class="form-check-label">{{ r.name }}</span>
						</label>
					</div>
				</div>

				<div class="mb-3">
					<label class="form-label small">{{ t("Apply role template") }}</label>
					<div class="d-flex gap-2">
						<select
							class="form-select"
							@change="(e) => applyTemplateToDetail(e.target.value)"
						>
							<option value="">{{ t("Select template…") }}</option>
							<option v-for="tpl in templates" :key="tpl.key" :value="tpl.key">
								{{ tpl.label }}
							</option>
						</select>
					</div>
					<small class="text-secondary">{{ t("Replaces all current roles.") }}</small>
				</div>

				<div class="d-flex gap-2 mt-4">
					<button type="button" class="btn btn-outline-secondary" @click="resetPasswordForDetail">
						<i class="ti ti-mail me-1"></i>{{ t("Reset password") }}
					</button>
					<button
						type="button"
						class="btn btn-primary ms-auto"
						:disabled="drawerSaving"
						@click="saveDetail"
					>
						<span v-if="drawerSaving" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-check me-1"></i>{{ t("Save") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<!-- Invite modal -->
	<div v-if="inviteOpen" class="modal-backdrop fade show" @click="closeInvite"></div>
	<div
		v-if="inviteOpen"
		class="modal fade show d-block"
		tabindex="-1"
		role="dialog"
		aria-modal="true"
	>
		<div class="modal-dialog modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">
						<i class="ti ti-user-plus me-1"></i>{{ t("Invite user") }}
					</h5>
					<button type="button" class="btn-close" @click="closeInvite"></button>
				</div>
				<div class="modal-body">
					<div v-if="inviteError" class="alert alert-danger">{{ inviteError }}</div>
					<div class="mb-3">
						<label class="form-label small">{{ t("Email") }}</label>
						<input v-model="inviteForm.email" type="email" class="form-control" required />
					</div>
					<div class="mb-3">
						<label class="form-label small">{{ t("Full name") }}</label>
						<input v-model="inviteForm.full_name" type="text" class="form-control" required />
					</div>
					<div class="mb-3">
						<label class="form-label small">{{ t("Role template (optional)") }}</label>
						<select v-model="inviteForm.template" class="form-select">
							<option value="">{{ t("No template") }}</option>
							<option v-for="tpl in templates" :key="tpl.key" :value="tpl.key">
								{{ tpl.label }}
							</option>
						</select>
					</div>
					<p class="text-secondary small mb-0">
						{{ t("A password reset email will be sent. The account is disabled until the user sets a password.") }}
					</p>
				</div>
				<div class="modal-footer">
					<button
						type="button"
						class="btn btn-outline-secondary"
						@click="closeInvite"
						:disabled="inviteSubmitting"
					>
						{{ t("Cancel") }}
					</button>
					<button
						type="button"
						class="btn btn-primary"
						:disabled="inviteSubmitting"
						@click="submitInvite"
					>
						<span v-if="inviteSubmitting" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-send me-1"></i>{{ t("Send invite") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
