"""Domain modules: per-domain physics injected into the generic pipeline."""

from app.domains.registry import DomainModule, get_domain_module

__all__ = ["DomainModule", "get_domain_module"]
