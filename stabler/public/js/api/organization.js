import { call } from "./client.js";

export const orgApi = {
	listCompanies: () => call("stabler.api.organization.list_companies"),
	switchCompany: (company) => call("stabler.api.organization.switch_company", { company }),
	updateLanguage: (language) => call("stabler.api.organization.update_language", { language }),
	boot: () => call("stabler.api.organization.boot"),
	getCompanyModules: (company) =>
		call("stabler.api.organization.get_company_modules", { company }),
	updateCompanyModules: (args) =>
		call("stabler.api.organization.update_company_modules", args),
	setUserAllowedCompanies: (user, companies) =>
		call("stabler.api.organization.set_user_allowed_companies", { user, companies }),
};
