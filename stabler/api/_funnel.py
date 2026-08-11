"""Tender pipeline funnel — pure classification and aggregation.

Frappe-free, so the rule that turns raw deal facts into pipeline stages can be
tested exhaustively without a site.

THE ONE RULE THAT MAKES THE NUMBERS HONEST
------------------------------------------
A deal is counted in exactly ONE stage. Without a precedence order, a deal
that has quotations AND a submitted bid would appear in two boxes and the
dashboard would overstate the pipeline. Precedence (highest wins):

    result (won/lost) > submitted > priced > sourcing > go > seen

This mirrors the business order the screens teach: sourcing before pricing,
pricing before the bid, the bid before the result.
"""

from __future__ import annotations

#: Pipeline stages, in business order. Position = how far the deal has come.
ORDER = ["seen", "go", "sourcing", "priced", "submitted", "won"]

#: Post-win operational stages in business order. Position = how far fulfillment has come.
POST_WIN_ORDER = ["po_created", "customs", "transit", "delivered", "invoiced", "done"]

#: Funnel rungs — "reached at least this stage". `lost` deals still reached
#: `submitted`, so the funnel never undercounts participation.
FUNNEL_STEPS = ["seen", "go", "sourcing", "submitted", "won"]

#: Direktörün chevron şeridinin yürüdüğü AÇIK fazlar. `won`/`lost` burada yok:
#: onlar faz değil sonuç, ve soldan sağa "ne kadar ilerledi" diye okunan bir
#: şeride konulmaları kaybı ilerleme gibi gösterirdi.
PIPELINE_PHASES = ["seen", "go", "sourcing", "priced", "submitted"]

#: Pre-win pipeline stages including lost
PIPELINE_STAGES = frozenset(ORDER) | {"lost"}

#: Her geçerli aşama (pre-win + post-win + lost).
STAGES = frozenset(ORDER) | frozenset(POST_WIN_ORDER) | {"lost"}


def classify(facts: dict) -> str:
	"""Map one deal's facts to its single pipeline stage.

	``facts``: {"go_no_go", "result", "submitted", "has_pricing", "sq_count"}.
	Unknown/malformed values degrade toward the earliest stage rather than
	inventing progress.
	"""
	result = str(facts.get("result") or "")
	if result in ("won", "lost"):
		return result
	if facts.get("submitted"):
		return "submitted"
	if facts.get("has_pricing"):
		return "priced"
	if int(facts.get("sq_count") or 0) > 0:
		return "sourcing"
	if str(facts.get("go_no_go") or "") == "go":
		return "go"
	return "seen"


def classify_post_win(facts: dict) -> str:
	"""Map a won deal's operational facts to its post-win execution stage.

	``facts``: {
		"has_invoice": bool,
		"delivered": bool,
		"in_transit": bool,
		"has_customs": bool,
		"has_po": bool,
	}
	"""
	if facts.get("has_invoice") and facts.get("delivered"):
		return "done"
	if facts.get("has_invoice"):
		return "invoiced"
	if facts.get("delivered"):
		return "delivered"
	if facts.get("in_transit"):
		return "transit"
	if facts.get("has_customs"):
		return "customs"
	if facts.get("has_po"):
		return "po_created"
	return "won"


def rank(stage: str) -> int:
	"""How far a deal REACHED, for funnel counting.

	`lost` reached `submitted` — it participated all the way to the bid — but
	it did NOT reach `won`. Ranking lost like won would make the funnel's last
	rung larger than the number of wins, which is a lie with a chart on it.
	"""
	if stage == "lost":
		return ORDER.index("submitted")
	try:
		return ORDER.index(stage)
	except ValueError:
		return 0


def summarise(rows: list[dict]) -> dict:
	"""Aggregate classified deals into stage counts, funnel and KPIs.

	``rows``: [{"stage", "urgent"(bool), "in_window"(bool)}]. Stage boxes count
	every open deal regardless of the window (an open tender is open); won/lost
	and the funnel respect the reporting window, so the win-rate is a period
	statement, not an all-time blur.
	"""
	stages = {k: 0 for k in [*ORDER, "lost"]}
	reached = {k: 0 for k in FUNNEL_STEPS}
	urgent = won = lost = 0

	for r in rows:
		stage = r.get("stage") or "seen"
		in_window = bool(r.get("in_window", True))
		terminal = stage in ("won", "lost")

		if terminal:
			if in_window:
				stages[stage] += 1
				if stage == "won":
					won += 1
				else:
					lost += 1
		else:
			stages[stage] += 1
			if r.get("urgent"):
				urgent += 1

		if in_window:
			pos = rank(stage)
			for step in FUNNEL_STEPS:
				if pos >= ORDER.index(step):
					reached[step] += 1

	resolved = won + lost
	open_pipeline = sum(stages[k] for k in ("seen", "go", "sourcing", "priced", "submitted"))
	return {
		"stages": stages,
		"funnel": [{"key": k, "n": reached[k]} for k in FUNNEL_STEPS],
		"kpi": {
			"open_pipeline": open_pipeline,
			"urgent": urgent,
			"won": won,
			"lost": lost,
			"resolved": resolved,
			"win_rate": round(won / resolved * 100, 1) if resolved else None,
		},
	}


def pipeline(stages: dict, quote_ready: dict) -> list[dict]:
	"""Bir satır per açık faz: kaç lot orada duruyor, kaçının teklif seti tam.

	`full` sayısı `n`'in ALT KÜMESİ olmak zorunda — şerit "4 lottan 2'sinin
	teklif seti tam" diye okunuyor ve payda o fazdaki lot sayısı. Çağıranın
	yanlış kova için hazır-sayısı geçirmesi bu yüzden burada kırpılıyor: 6/4
	yazan bir çubuk %150 dolar ve sessizce yalan söyler.
	"""
	rows = []
	for key in PIPELINE_PHASES:
		n = int(stages.get(key) or 0)
		rows.append({"key": key, "n": n, "full": min(int(quote_ready.get(key) or 0), n)})
	return rows


#: Sales Order board stages folded into three execution buckets + done.
#: The board's seven columns are operational detail; the funnel needs the story.
SO_BUCKETS = {
	"New": "contract",
	"Procurement": "procurement",
	"Delivery": "delivery",
	"Acceptance": "delivery",
	"Invoicing": "delivery",
	"Paid": "done",
	"Closed": "done",
}


def bucket_so(stage: str) -> str:
	"""Fold a board stage into its execution bucket; unknown stages count as
	`contract` — a submitted SO that fits no bucket is still a live contract,
	and hiding it would silently shrink the "serving" number."""
	return SO_BUCKETS.get(str(stage or ""), "contract")


def summarise_so(stages: list[str]) -> dict:
	out = {"contract": 0, "procurement": 0, "delivery": 0, "done": 0}
	for s in stages:
		out[bucket_so(s)] += 1
	out["active"] = out["contract"] + out["procurement"] + out["delivery"]
	return out
