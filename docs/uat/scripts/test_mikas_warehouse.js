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

	console.log('Testing Purchase Order creation with warehouse Stores - MIKAS...');
	const resPO = await page.evaluate(async () => {
		const csrf = window.__STABLER__?.csrfToken || '';
		const body = new URLSearchParams();
		body.append('company', 'Mikas');
		body.append('supplier', 'Ural Components CJSC');
		body.append('set_warehouse', 'Stores - MIKAS');
		body.append('deal', 'CRM-DEAL-2026-00098');
		body.append('auto_submit', '1');
		body.append('items', JSON.stringify([{
			item_code: 'UAT-BEARING-6206',
			qty: 100,
			rate: 129600,
			warehouse: 'Stores - MIKAS'
		}]));

		const res = await fetch('/api/method/stabler.api.purchasing.create_purchase_order', {
			method: 'POST',
			headers: {
				'Content-Type': 'application/x-www-form-urlencoded',
				'X-Frappe-CSRF-Token': csrf
			},
			body: body.toString()
		});
		return await res.json();
	});
	console.log('PO Response with Stores - MIKAS:', JSON.stringify(resPO));

	await browser.close();
})();
