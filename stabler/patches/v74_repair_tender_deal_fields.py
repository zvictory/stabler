"""Replay tender CRM Deal fields for sites where v27 ran before CRM existed."""

from stabler.patches.v27_tender_deal_fields import execute as create_tender_deal_fields


def execute():
	create_tender_deal_fields()
