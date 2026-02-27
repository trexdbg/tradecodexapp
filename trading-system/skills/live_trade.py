from __future__ import annotations


def execute_live_order(*_args, **_kwargs):
    raise RuntimeError(
        "Live trading is disabled. System is configured for dry-run execution only."
    )

