import { call } from "./client.js";

export const listPromoPlans = (args = {}) =>
	call("stabler.api.marketing.list_promo_plans", args);

export const getPromoPlan = (name) =>
	call("stabler.api.marketing.get_promo_plan", { name });

export const createPromoPlan = (payload) =>
	call("stabler.api.marketing.create_promo_plan", { payload });

export const updatePromoPlan = (name, payload) =>
	call("stabler.api.marketing.update_promo_plan", { name, payload });

export const updatePromoPlanStatus = (name, status) =>
	call("stabler.api.marketing.update_promo_plan_status", { name, status });

export const listRoiSnapshots = (args = {}) =>
	call("stabler.api.marketing.list_roi_snapshots", args);

export const listClaims = (args = {}) =>
	call("stabler.api.marketing.list_claims", args);

export const getClaim = (name) =>
	call("stabler.api.marketing.get_claim", { name });

export const submitClaim = (args) =>
	call("stabler.api.marketing.submit_claim", args);

export const reviewClaim = (name, decision, reviewer_notes = null) =>
	call("stabler.api.marketing.review_claim", { name, decision, reviewer_notes });

export const settleClaim = (name) =>
	call("stabler.api.marketing.settle_claim", { name });
