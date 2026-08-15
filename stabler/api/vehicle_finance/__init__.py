"""Vehicle Finance Center (Agreement V1) server package.

Phase 1 owns the domain layer only: the deterministic schedule builder and the
capability/module gates. Accounting posting (Phase 2) and the SPA (Phase 3)
build on top of these. The legacy engine at ``stabler.api.installment`` is
untouched; every V1 behaviour is additionally gated by
``Vehicle Finance Settings.installment_engine`` (default ``Legacy``).
"""
