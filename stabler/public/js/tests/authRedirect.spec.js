import { describe, expect, it } from "vitest";
import { sanitizeStablerRedirect } from "../composables/authRedirect.js";

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

