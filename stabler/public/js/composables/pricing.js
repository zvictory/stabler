// The pre-discount unit price of a document line.
//
// The rate column in the sales order editor is the GROSS price: the discount is
// applied on top of it (SalesOrderLines.vue's lineAmount, and api/_pricing.py on
// the server). The saved document's `rate` is the opposite — the NET price
// ERPNext bills — and the gross is kept in `price_list_rate`.
//
// So reopening a document must map the gross back into the rate column. Loading
// the document's `rate` there instead applies the discount a second time: the
// screen shows a total the document does not have, and each save shaves the
// price again — a 4 % line becomes 4 %, then 7.84 %, then 11.5 %.
//
// `price_list_rate` is only trusted while it is the higher of the two. It is
// zero on a line that never had a list price, and it sits BELOW `rate` on the
// documents this bug already wrote (rate = full price, list rate = the
// FX-converted catalogue price). In both cases `rate` is the only honest gross.
export function grossRate(it) {
	const rate = Number(it?.rate) || 0;
	const listRate = Number(it?.price_list_rate) || 0;
	return listRate >= rate ? listRate : rate;
}
