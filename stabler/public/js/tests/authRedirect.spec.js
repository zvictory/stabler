import { afterEach, describe, expect, it, vi } from "vitest";
import { hardRedirect, sanitizeStablerRedirect } from "../composables/authRedirect.js";

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
		Object.defineProperty(window, "location", { value: realLocation, configurable: true, writable: true });
	});

	it("replaces the hash AND forces a document reload", () => {
		// A hash-only replace never reloads the document, which leaves
		// window.__STABLER__ (user, csrf) stale after login/logout — the exact
		// regression that broke both flows. Both calls are load-bearing.
		const replace = vi.fn();
		const reload = vi.fn();
		Object.defineProperty(window, "location", {
			value: { replace, reload },
			configurable: true,
			writable: true,
		});

		hardRedirect("/dashboard");

		expect(replace).toHaveBeenCalledWith("/stabler#/dashboard");
		expect(reload).toHaveBeenCalledTimes(1);
	});
});

