import { call } from "./client.js";

export const dashboardApi = {
	summary: (company) => call("stabler.api.dashboard.summary", { company }),
	revenueTrend: (company, months = 12) =>
		call("stabler.api.dashboard.revenue_trend", { company, months }),
	recentActivity: (company, limit = 10) =>
		call("stabler.api.dashboard.recent_activity", { company, limit }),
};
