import { afterEach, describe, expect, it, vi } from "vitest";
import { hardRedirect, normalizeAuthTransitionUrl, sanitizeStablerRedirect } from "../composables/authRedirect.js";

describe("sanitizeStablerRedirect", () => {
	it.each([
		["/dashboard", "/dashboard"],
		["/tender/my-tenders?status=open", "/tender/my-tenders?status=open"],
		["/reports", "/reports"],
	])("keeps known Stabler paths", (input, expected) => {
		expect(sanitizeStablerRedirect(input)).toBe(expected);
	});

	it.each([
		[undefined],
		[null],
		[""],
		["dashboard"],
		["//evil.example/path"],
		["https://evil.example/path"],
		["/\\evil.example/path"],
		["/app"],
		["/app/user/test@example.com"],
		["/desk"],
		["/desk/user/test@example.com"],
		["%2Fdesk%2Fuser%2Ftest%2540example.com"],
		["/%2F%2Fevil.example"],
		["/unknown-route"],
		["/dashboard/../app"],
		["/tender/../desk"],
		["/dashboard/.."],
		["/dashboard/./profile"],
		["/dashboard%2f..%2fapp"],
		["/dashboard?redirect=/app"],
		["/dashboard?redirect_to=https://evil.example"],
		["/tender/my-tenders?next=%2Fdesk%2Fuser"],
		["/%00/dashboard"],
		["/dashboard%5c..%5capp"],
	])("falls back for unsafe or unknown input %#", (input) => {
		expect(sanitizeStablerRedirect(input)).toBe("/dashboard");
	});
});

describe("hardRedirect", () => {
	const realLocation = window.location;

	afterEach(() => {
		vi.restoreAllMocks();
		Object.defineProperty(window, "location", { value: realLocation, configurable: true, writable: true });
	});

	it("uses one document navigation after an auth transition", () => {
		// The query token changes the document URL rather than only its hash, so
		// the server re-renders session boot in one deterministic navigation.
		const replace = vi.fn();
		const reload = vi.fn();
		vi.spyOn(Date, "now").mockReturnValue(1722643200000);
		Object.defineProperty(window, "location", {
			value: { replace, reload },
			configurable: true,
			writable: true,
		});

		hardRedirect("/dashboard");

		expect(replace).toHaveBeenCalledWith("/stabler?auth-transition=1722643200000#/dashboard");
		expect(reload).not.toHaveBeenCalled();
	});
});

describe("normalizeAuthTransitionUrl", () => {
	it("removes the internal transition token while preserving the hash route", () => {
		const history = { state: { source: "auth" }, replaceState: vi.fn() };

		normalizeAuthTransitionUrl(
			{ href: "http://localhost:8000/stabler?auth-transition=123#/dashboard" },
			history
		);

		expect(history.replaceState).toHaveBeenCalledWith(history.state, "", "/stabler#/dashboard");
	});

	it("preserves unrelated query parameters", () => {
		const history = { state: null, replaceState: vi.fn() };

		normalizeAuthTransitionUrl(
			{ href: "http://localhost:8000/stabler?lang=tr&auth-transition=123#/login" },
			history
		);

		expect(history.replaceState).toHaveBeenCalledWith(null, "", "/stabler?lang=tr#/login");
	});

	it("does nothing when there is no transition token", () => {
		const history = { state: null, replaceState: vi.fn() };

		normalizeAuthTransitionUrl({ href: "http://localhost:8000/stabler#/dashboard" }, history);

		expect(history.replaceState).not.toHaveBeenCalled();
	});
});
