from __future__ import annotations

from .base import DomainPack, SimpleDomain, ToolContext
from .book import BookDomain

_PACKS: dict[str, DomainPack] = {}


def register(pack: DomainPack) -> None:
    _PACKS[pack.id] = pack


def get_domain(domain_id: str = "book") -> DomainPack:
    if domain_id not in _PACKS:
        raise KeyError(f"未注册的域包：{domain_id}")
    return _PACKS[domain_id]


def list_domains() -> list[dict[str, str]]:
    return [
        {"id": pack.id, "name": pack.name, "description": pack.description}
        for pack in _PACKS.values()
    ]


def default_domain_id() -> str:
    return next(iter(_PACKS))


register(BookDomain())

__all__ = [
    "DomainPack",
    "SimpleDomain",
    "ToolContext",
    "get_domain",
    "list_domains",
    "register",
    "default_domain_id",
]
