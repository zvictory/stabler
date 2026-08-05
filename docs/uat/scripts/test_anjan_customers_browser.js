const { chromium } = require('playwright');

(async () => {
	console.log('Testing debug_sales_perm API on anjan.erpstable.com...');
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext();
	const page = await context.newPage();

	await page.request.post('https://anjan.erpstable.com/api/method/login', {
		data: {
			usr: 'qdavron025@gmail.com',
			pwd: 'AnjanUAT2026!'
		}
	});

	const debugResp = await page.request.get('https://anjan.erpstable.com/api/method/stabler.api.sales.debug_sales_perm');
	console.log('debug_sales_perm response:', await debugResp.text());

	const custResp = await page.request.get('https://anjan.erpstable.com/api/method/stabler.api.sales.list_customers_with_balances?company=ANJAN');
	console.log('list_customers_with_balances status:', custResp.status());
	console.log('list_customers_with_balances snippet:', (await custResp.text()).substring(0, 300));

	await browser.close();
})();
