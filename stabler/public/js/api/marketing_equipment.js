import { call } from "./client.js";

export const listEquipment = (args = {}) =>
	call("stabler.api.marketing_equipment.list_equipment", args);

export const getEquipment = (name) =>
	call("stabler.api.marketing_equipment.get_equipment", { name });

export const createEquipment = (payload) =>
	call("stabler.api.marketing_equipment.create_equipment", { payload });

export const updateEquipmentStatus = (name, status) =>
	call("stabler.api.marketing_equipment.update_equipment_status", { name, status });

export const listRepairRequests = (args = {}) =>
	call("stabler.api.marketing_equipment.list_repair_requests", args);

export const getRepairRequest = (name) =>
	call("stabler.api.marketing_equipment.get_repair_request", { name });

export const createRepairRequest = (args) =>
	call("stabler.api.marketing_equipment.create_repair_request", args);

export const updateRepairStatus = (name, status, assigned_technician = null) =>
	call("stabler.api.marketing_equipment.update_repair_status", {
		name,
		status,
		assigned_technician,
	});
