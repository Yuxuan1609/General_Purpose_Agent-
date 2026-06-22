"""Domain registry setter — sets module-level DomainRegistry for downward tools."""
import logging

logger = logging.getLogger(__name__)

_registry = None


def set_domain_registry(reg) -> None:
    global _registry
    _registry = reg
