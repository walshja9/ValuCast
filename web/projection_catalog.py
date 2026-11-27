"""Named projection-source registry. Lets ValuCast value Steamer or Marcel
through the same engine. Default stays Steamer so current behavior is intact.
No UI — this is the seam a later spec exposes."""
from __future__ import annotations

from web.projection_store import ProjectionStore


class ProjectionCatalog:
    def __init__(self, sources: dict[str, str], default: str = "steamer") -> None:
        self._sources = dict(sources)
        self._default = default if default in self._sources else next(iter(self._sources))
        self._cache: dict[str, ProjectionStore] = {}

    @property
    def default(self) -> str:
        return self._default

    @property
    def names(self) -> list[str]:
        return list(self._sources)

    def store_for(self, source: str | None = None) -> ProjectionStore:
        name = source or self._default
        if name not in self._sources:
            raise KeyError(f"Unknown projection source: {name!r}")
        if name not in self._cache:
            self._cache[name] = ProjectionStore(self._sources[name])
        return self._cache[name]
