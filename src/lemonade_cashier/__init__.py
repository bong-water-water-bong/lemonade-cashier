"""Lemonade Cashier — a local-first cashier assistant.

The public surface is intentionally small. Most callers want either the
CLI entrypoint (`python -m lemonade_cashier.cli`) or the `Supervisor`
class from :mod:`lemonade_cashier.agents.supervisor`.
"""

from __future__ import annotations

__version__ = "1.5.0"
__all__ = ["__version__"]
