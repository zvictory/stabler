const { chromium } = require('playwright');

(async () => {
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext();
	const page = await context.newPage();

	await page.goto('https://mikas.erpstable.com/stabler#/', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2000);

	const emailInput = page.locator('input[type="email"], input[name="login_id"], input[type="text"]').first();
	if (await emailInput.count() > 0 && await emailInput.isVisible()) {
		await emailInput.fill('director.mikas@erpstable.com');
		await page.fill('input[type="password"]', 'MikasUAT2026!');
		await page.click('button[type="submit"]');
		await page.waitForTimeout(3000);
	}

	const resCreateWH = await page.evaluate(async () => {
		const csrf = window.__STABLER__?.csrfToken || '';
		const body = new URLSearchParams();
		body.append('doc', JSON.stringify({
			doctype: 'Warehouse',
			warehouse_name: 'Stores',
			company: 'Mikas'
		}));

		const res = await fetch('/api/method/frappe.client.insert', {
			method: 'POST',
			headers: {
				'Content-Type': 'application/x-www-form-urlencoded',
				'X-Frappe-CSRF-Token': csrf
			},
			body: body.toString()
		});
		return await res.json();
	});

	console.log('Create WH Response:', JSON.stringify(resCreateWH));

	await browser.close();
})();
