"""Config-driven adapter registry.

Backends and sources register by name; the night build instantiates them from
config. Adding a V2 lane/source is a class + a ``@register_*`` decorator + a
config entry — the dispatcher never changes (the seam proof, origin core
interface).
"""

from __future__ import annotations

from typing import Callable

from .adapters.backend import BackendAdapter
from .adapters.backlog import BacklogSource

BACKENDS: dict = {}
SOURCES: dict = {}


class RegistryError(ValueError):
    """Raised when config names an adapter that is not registered."""


def register_backend(name: str) -> Callable:
    def deco(cls):
        BACKENDS[name] = cls
        cls.name = name
        return cls

    return deco


def register_source(name: str) -> Callable:
    def deco(cls):
        SOURCES[name] = cls
        cls.name = name
        return cls

    return deco


def register_builtins() -> None:
    """Import the V1 adapters so their decorators register them."""
    from .backends import claude_headless, local  # noqa: F401
    from .sources import github_issues, todo_scan  # noqa: F401


def build_backends(config) -> list:
    out = []
    for bcfg in config.backends:
        if bcfg.name not in BACKENDS:
            raise RegistryError(
                f"unknown backend '{bcfg.name}' (registered: {sorted(BACKENDS)})"
            )
        out.append(BACKENDS[bcfg.name](bcfg))
    return out


def build_sources(config) -> list:
    out = []
    for scfg in config.sources:
        if scfg.name not in SOURCES:
            raise RegistryError(
                f"unknown source '{scfg.name}' (registered: {sorted(SOURCES)})"
            )
        out.append(SOURCES[scfg.name](scfg))
    return out
