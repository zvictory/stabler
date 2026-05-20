import { call } from "./client.js";

export const adminApi = {
	listUsers: (args = {}) => call("stabler.api.admin.list_users", args),
	getUser: (name) => call("stabler.api.admin.get_user", { name }),
	updateUser: (args) => call("stabler.api.admin.update_user", args),
	inviteUser: (args) => call("stabler.api.admin.invite_user", args),
	resetPassword: (name) => call("stabler.api.admin.reset_password", { name }),
	listRoles: (stabler_only = 1) => call("stabler.api.admin.list_roles", { stabler_only }),
	getRole: (name) => call("stabler.api.admin.get_role", { name }),
	applyRoleTemplate: (user, template) =>
		call("stabler.api.admin.apply_role_template", { user, template }),
	listRoleTemplates: () => call("stabler.api.admin.list_role_templates"),
};
