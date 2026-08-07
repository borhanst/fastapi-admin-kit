"""AI backend abstraction and registry.

Each AI backend (Pydantic AI today, LangChain later) implements
:class:`AIBackend` and registers an instance via :func:`register_backend`.
Agent configs select a backend through ``AIAgentConfig.backend``;
:func:`resolve_backend` maps that value to a concrete backend, honouring the
``"auto"`` fallback to the first available backend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from fastapi_admin_kit.ai.config import AIBackendName

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastapi_admin_kit.ai.agent import AIAgent
    from fastapi_admin_kit.ai.config import AIAgentConfig
    from fastapi_admin_kit.ai.deps import AdminDeps
    from fastapi_admin_kit.ai.usage import AIUsageWriter


class AIBackend(ABC):
    """Interface implemented by every AI backend.

    Backends are discovered via the process-wide registry populated by
    :func:`register_backend`. :class:`PydanticAIBackend` is the reference
    implementation shipped in this package.
    """

    #: Stable identifier used in ``AIAgentConfig.backend`` (e.g. ``"pydantic_ai"``).
    name: str

    @abstractmethod
    def create_agent(
        self,
        config: AIAgentConfig,
        *,
        deps_factory: Callable[..., Awaitable[AdminDeps]],
        usage_writer: AIUsageWriter,
    ) -> AIAgent:
        """Build a concrete :class:`~fastapi_admin_kit.ai.agent.AIAgent` from a config."""
        ...

    def get_streaming_adapter(self, agent: AIAgent) -> type | None:
        """Return the backend's UI streaming adapter for an agent.

        Consumed by ``/ai/chat/stream`` to dispatch response streaming.
        Returns ``None`` if the backend handles streaming itself without an adapter.
        """
        return None

    @abstractmethod
    def is_available(self) -> bool:
        """Whether the backend's runtime dependency is installed."""
        ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_BACKENDS: dict[str, AIBackend] = {}


def register_backend(backend: AIBackend) -> None:
    """Register a backend instance keyed by ``backend.name``."""
    _BACKENDS[backend.name] = backend


def get_backend(name: str) -> AIBackend | None:
    """Look up a registered backend by name, or ``None`` if absent."""
    return _BACKENDS.get(name)


def get_default_backend() -> AIBackend | None:
    """First registered backend that reports :meth:`AIBackend.is_available`.

    Returned in registration order, so the first available backend wins.
    """
    for backend in _BACKENDS.values():
        if backend.is_available():
            return backend
    return None


def resolve_backend(name: AIBackendName = "auto") -> AIBackend:
    """Resolve an ``AIAgentConfig.backend`` value to a concrete backend.

    ``"auto"`` resolves to the first available backend. A named backend must be
    registered and available, otherwise an informative :class:`RuntimeError` is
    raised.
    """
    if name == "auto":
        backend = get_default_backend()
        if backend is None:
            raise RuntimeError(
                "No AI backend is available. Install one, e.g. "
                "`pip install 'fastapi-admin-kit[ai]'`."
            )
        return backend

    backend = get_backend(name)
    if backend is None:
        raise RuntimeError(
            f"AI backend '{name}' is not registered. Registered backends: {sorted(_BACKENDS)}"
        )
    if not backend.is_available():
        raise RuntimeError(
            f"AI backend '{name}' is not available: its runtime dependency is not installed."
        )
    return backend


# Register the built-in Pydantic AI backend (registers on import).
from fastapi_admin_kit.ai.backends.pydantic_ai_backend import (  # noqa: E402,F401
    PydanticAIBackend,
)

__all__ = [
    "AIBackend",
    "get_backend",
    "get_default_backend",
    "register_backend",
    "resolve_backend",
]
