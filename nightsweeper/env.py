"""Environment guards for the Claude lane.

Grounding §1: setting ``ANTHROPIC_API_KEY`` overrides subscription/credit
routing and bills uncapped pay-as-you-go (issue #37686: ~$1,800 in two days).
The scheduler must never let a Claude dispatch run with that key set. Both the
production Claude lane (U10) and the S1 economics spike (U1) call
``assert_no_api_key()`` before any ``claude -p`` invocation.
"""

from __future__ import annotations

import os
from typing import Optional


class ApiKeyPresentError(RuntimeError):
    """Raised when ANTHROPIC_API_KEY is set and a credit-pool run was intended."""


def assert_no_api_key(env: Optional[dict] = None) -> None:
    """Abort if ANTHROPIC_API_KEY is present.

    Guards credit-pool routing: a set key bills uncapped API spend.
    """
    source = os.environ if env is None else env
    if source.get("ANTHROPIC_API_KEY"):
        raise ApiKeyPresentError(
            "ANTHROPIC_API_KEY is set. Nightsweeper refuses to dispatch the Claude "
            "lane with it set — it overrides credit-pool routing and bills uncapped "
            "API usage. Unset it (the scheduler runs `env -u ANTHROPIC_API_KEY`)."
        )


def scrubbed_env(base: Optional[dict] = None) -> dict:
    """Return a copy of the environment with ANTHROPIC_API_KEY removed."""
    env = dict(os.environ if base is None else base)
    env.pop("ANTHROPIC_API_KEY", None)
    return env
