const { chromium } = require('playwright');

(async () => {
	console.log('Launching browser for UAT Step 5 & 6 (SO & PO Creation with Auto-Healed Warehouse)...');
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	try {
		console.log('Step 1: Logging in as director.mikas@erpstable.com...');
		await page.goto('https://mikas.erpstable.com/stabler#/', { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(2000);

		const emailInput = page.locator('input[type="email"], input[name="login_id"], input[type="text"]').first();
		if (await emailInput.count() > 0 && await emailInput.isVisible()) {
			await emailInput.fill('director.mikas@erpstable.com');
			await page.fill('input[type="password"]', 'MikasUAT2026!');
			await page.click('button[type="submit"]');
			await page.waitForTimeout(3000);
		}

		console.log('Step 2: Creating Purchase Order for Ural Components CJSC...');
		const resPO = await page.evaluate(async () => {
			const csrf = window.__STABLER__?.csrfToken || '';
			const body = new URLSearchParams();
			body.append('company', 'Mikas');
			body.append('supplier', 'Ural Components CJSC');
			body.append('deal', 'CRM-DEAL-2026-00098');
			body.append('auto_submit', '1');
			body.append('items', JSON.stringify([{
				item_code: 'UAT-BEARING-6206',
				qty: 100,
				rate: 129600
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
		console.log('Create PO Response:', JSON.stringify(resPO));

		console.log('Step 3: Creating Sales Order for UAT Mikas Rail Buyer...');
		const resSO = await page.evaluate(async () => {
			const csrf = window.__STABLER__?.csrfToken || '';
			const body = new URLSearchParams();
			body.append('company', 'Mikas');
			body.append('customer', 'UAT Mikas Rail Buyer');
			body.append('crm_deal', 'CRM-DEAL-2026-00098');
			body.append('auto_submit', '1');
			body.append('items', JSON.stringify([{
				item_code: 'UAT-BEARING-6206',
				qty: 100,
				rate: 171105.2433
			}]));

			const res = await fetch('/api/method/stabler.api.sales.create_sales_order', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/x-www-form-urlencoded',
					'X-Frappe-CSRF-Token': csrf
				},
				body: body.toString()
			});
			return await res.json();
		});
		console.log('Create SO Response:', JSON.stringify(resSO));

		console.log('\n--- STEP 5 SO & PO CREATION COMPLETE ---');
	} catch (err) {
		console.error('Fatal error in SO & PO script:', err);
	} finally {
		await browser.close();
	}
})();
