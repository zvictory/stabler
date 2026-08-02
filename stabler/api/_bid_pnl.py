"""Pure contract P&L calculation module for tender bid pricing (Frappe-free)."""

from __future__ import annotations

_BID_DEFAULTS = {
	"mode": "margin",  # "margin" (target margin -> bid) | "price" (bid -> margin)
	"margin_pct": 20.0,  # Profit / net revenue, %
	"vat_pct": 12.0,  # VAT
	"exchange_pct": 0.15,  # Exchange commission (on gross bid)
	"profit_tax_pct": 15.0,  # Income tax
	"dividend_tax_pct": 5.0,  # Dividend tax
}


def _num(v, default: float = 0.0) -> float:
	try:
		return float(v) if v not in (None, "") else default
	except (TypeError, ValueError):
		return default


def compute_bid_pnl(p: dict) -> dict:
	"""Full contract P&L waterfall (mirrors the customer's cost sheet).

	Two directions:
	  mode="margin" -> back-solve the gross bid price from a target margin.
	  mode="price"  -> forward-compute the resulting margin from a given bid.
	Costs split into above-the-line (before Profit, taxable) and below-the-line
	(after dividends - reduce Остаток only, e.g. office, extra certification).
	"""
	p = p or {}
	landed_goods = _num(p.get("landed_goods"))
	above_other = [
		{"label": str(x.get("label") or ""), "amount": _num(x.get("amount"))}
		for x in (p.get("above_other") or [])
		if isinstance(x, dict)
	]
	below_other = [
		{"label": str(x.get("label") or ""), "amount": _num(x.get("amount"))}
		for x in (p.get("below_other") or [])
		if isinstance(x, dict)
	]
	vat_f = _num(p.get("vat_pct", _BID_DEFAULTS["vat_pct"])) / 100.0
	exch_f = _num(p.get("exchange_pct", _BID_DEFAULTS["exchange_pct"])) / 100.0
	ptax_f = _num(p.get("profit_tax_pct", _BID_DEFAULTS["profit_tax_pct"])) / 100.0
	dtax_f = _num(p.get("dividend_tax_pct", _BID_DEFAULTS["dividend_tax_pct"])) / 100.0

	above_excl = landed_goods + sum(x["amount"] for x in above_other)  # excludes exchange commission
	mode = p.get("mode") or "margin"

	if mode == "margin":
		m = _num(p.get("margin_pct", _BID_DEFAULTS["margin_pct"])) / 100.0
		denom = (1.0 - m) - (1.0 + vat_f) * exch_f
		net_rev = above_excl / denom if denom > 0 else 0.0
		gross = net_rev * (1.0 + vat_f)
	else:
		gross = _num(p.get("bid_price"))
		net_rev = gross / (1.0 + vat_f) if (1.0 + vat_f) else 0.0

	vat = gross - net_rev
	exchange = gross * exch_f
	above_total = above_excl + exchange
	profit = net_rev - above_total
	profit_tax = max(profit, 0.0) * ptax_f
	net_profit = profit - profit_tax
	dividend_tax = max(net_profit, 0.0) * dtax_f
	dividends = net_profit - dividend_tax
	below_total = sum(x["amount"] for x in below_other)
	ostatok = dividends - below_total

	return {
		"mode": mode,
		"bid_price": round(gross, 2),
		"vat": round(vat, 2),
		"net_revenue": round(net_rev, 2),
		"exchange_fee": round(exchange, 2),
		"landed_goods": round(landed_goods, 2),
		"above_other": above_other,
		"above_total": round(above_total, 2),
		"profit": round(profit, 2),
		"profit_tax": round(profit_tax, 2),
		"net_profit": round(net_profit, 2),
		"dividend_tax": round(dividend_tax, 2),
		"dividends": round(dividends, 2),
		"below_other": below_other,
		"below_total": round(below_total, 2),
		"ostatok": round(ostatok, 2),
		"margin_on_revenue_pct": round(profit / net_rev * 100, 2) if net_rev else 0.0,
		"markup_on_cost_pct": round(profit / above_total * 100, 2) if above_total else 0.0,
	}
