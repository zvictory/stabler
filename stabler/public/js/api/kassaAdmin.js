import { call } from "./client.js";

export const kassaAdminApi = {
	listKassirs: (args = {}) => call("stabler.api.kassa_admin.list_kassirs", args),
	getKassir: (name) => call("stabler.api.kassa_admin.get_kassir", { name }),
	createKassir: (args) => call("stabler.api.kassa_admin.create_kassir", args),
	updateKassir: (args) => call("stabler.api.kassa_admin.update_kassir", args),
	setKassirEnabled: (name, enabled) =>
		call("stabler.api.kassa_admin.set_kassir_enabled", { name, enabled }),
	deleteKassir: (name) => call("stabler.api.kassa_admin.delete_kassir", { name }),
};
