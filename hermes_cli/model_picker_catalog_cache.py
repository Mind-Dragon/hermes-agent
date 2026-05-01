"""Non-blocking cache for /model picker provider catalogs.

The picker and slash-completion paths must be responsive.  Live provider
catalog discovery is allowed in a background refresh, but never in a keypress
handler.  This module keeps a small process+disk cache and lets callers render
stale rows while a daemon thread refreshes the catalog.
"""

from __future__ import annotations

import contextlib
import copy
import fcntl
import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

CACHE_SCHEMA_VERSION = 1
DEFAULT_STALE_AFTER_SECONDS = 6 * 60 * 60
DEFAULT_USABLE_FOR_SECONDS = 7 * 24 * 60 * 60

ProviderRows = list[dict[str, Any]]
RefreshFn = Callable[[], ProviderRows | tuple[ProviderRows, str]]

_SECRET_KEY_PARTS = ("token", "secret", "password", "credential")
_RAW_SECRET_FIELDS = {"api_key", "authorization", "bearer", "bearer_token"}
_ENV_REFERENCE_SUFFIXES = ("_env", "_env_var", "_env_vars")
_AUTH_VOLATILE_FIELDS = {
    "access_token",
    "api_key",
    "last_error_code",
    "last_error_message",
    "last_error_reason",
    "last_error_reset_at",
    "last_status",
    "last_status_at",
    "password",
    "refresh_token",
    "request_count",
    "secret",
    "token",
    "updated_at",
}


def _value_hash(value: Any) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now() -> float:
    return time.time()


def _default_cache_path() -> Path:
    return get_hermes_home() / "cache" / "model_picker_catalog.json"


def _scrub_for_fingerprint(value: Any) -> Any:
    """Return a stable, non-secret representation for fingerprinting."""

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key in sorted(value):
            key_str = str(key)
            lowered = key_str.lower()
            item = value[key]
            if lowered.endswith(_ENV_REFERENCE_SUFFIXES):
                if isinstance(item, (list, tuple)):
                    out[key_str] = [
                        {"name": str(env_name or ""), "value_hash": _value_hash(os.environ.get(str(env_name or ""), ""))}
                        for env_name in item
                    ]
                else:
                    env_name = str(item or "")
                    out[key_str] = {
                        "name": env_name,
                        "value_hash": _value_hash(os.environ.get(env_name, "")),
                    }
            elif lowered in _RAW_SECRET_FIELDS or any(part in lowered for part in _SECRET_KEY_PARTS):
                out[key_str] = {
                    "present": bool(str(item or "").strip()),
                    "value_hash": _value_hash(item),
                }
            else:
                out[key_str] = _scrub_for_fingerprint(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_scrub_for_fingerprint(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _stable_auth_for_fingerprint(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _stable_auth_for_fingerprint(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key).lower() not in _AUTH_VOLATILE_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [_stable_auth_for_fingerprint(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _file_state(path: Path) -> dict[str, Any] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return {"mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)}


def _auth_state_fingerprint() -> dict[str, Any]:
    """Return non-secret auth/env state that influences provider visibility."""

    env_names: set[str] = set()
    try:
        from hermes_cli.auth import PROVIDER_REGISTRY

        for cfg in PROVIDER_REGISTRY.values():
            for name in getattr(cfg, "api_key_env_vars", ()) or ():
                if name:
                    env_names.add(str(name))
            base_env = getattr(cfg, "base_url_env_var", "") or ""
            if base_env:
                env_names.add(str(base_env))
    except Exception:
        pass

    env_names.update({
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_TOKEN",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENROUTER_API_KEY",
        "NOUS_API_KEY",
        "KIMI_API_KEY",
        "DEEPSEEK_API_KEY",
    })

    auth_store: dict[str, Any] = {}
    auth_path = get_hermes_home() / "auth.json"
    try:
        auth_payload = json.loads(auth_path.read_text(encoding="utf-8"))
        auth_store = _stable_auth_for_fingerprint(auth_payload)
    except Exception:
        auth_store = {}

    external_files: dict[str, dict[str, Any]] = {}
    for label, path in {
        "aws_config": Path.home() / ".aws" / "config",
        "aws_credentials": Path.home() / ".aws" / "credentials",
        "codex_auth": Path.home() / ".codex" / "auth.json",
        "gcloud_adc": Path.home() / ".config" / "gcloud" / "application_default_credentials.json",
        "github_hosts": Path.home() / ".config" / "gh" / "hosts.yml",
    }.items():
        state = _file_state(path)
        if state is not None:
            external_files[label] = state

    return {
        "env": {name: _value_hash(os.environ.get(name, "")) for name in sorted(env_names)},
        "external_files": external_files,
        "hermes_auth": auth_store,
    }


def model_picker_catalog_fingerprint(
    *,
    current_provider: str = "",
    current_base_url: str = "",
    current_model: str = "",
    user_providers: dict | None = None,
    custom_providers: list | None = None,
    max_models: int = 50,
) -> str:
    """Build a cache key for the current model-picker catalog context."""

    payload = {
        "schema": CACHE_SCHEMA_VERSION,
        "current_base_url": str(current_base_url or "").strip().rstrip("/"),
        "user_providers": _scrub_for_fingerprint(user_providers or {}),
        "custom_providers": _scrub_for_fingerprint(custom_providers or []),
        "auth_state": _auth_state_fingerprint(),
        "max_models": int(max_models or 0),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ModelPickerCatalogCache:
    """Small disk-backed cache with background refresh coalescing."""

    def __init__(
        self,
        cache_path: Path | str | None = None,
        *,
        stale_after_seconds: int | float = DEFAULT_STALE_AFTER_SECONDS,
        usable_for_seconds: int | float = DEFAULT_USABLE_FOR_SECONDS,
    ) -> None:
        self.cache_path = Path(cache_path) if cache_path is not None else _default_cache_path()
        self.stale_after_seconds = float(stale_after_seconds)
        self.usable_for_seconds = float(usable_for_seconds)
        self._lock = threading.RLock()
        self._loaded = False
        self._entries: dict[str, dict[str, Any]] = {}
        self._refresh_threads: dict[str, threading.Thread] = {}
        self._disk_mtime_ns: int | None = None

    def _cache_mtime_ns(self) -> int | None:
        try:
            return int(self.cache_path.stat().st_mtime_ns)
        except OSError:
            return None

    @contextlib.contextmanager
    def _file_lock(self):
        lock_path = self.cache_path.with_suffix(self.cache_path.suffix + ".lock")
        handle = None
        locked = False
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = lock_path.open("a", encoding="utf-8")
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            locked = True
        except Exception:
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
            handle = None
        try:
            yield
        finally:
            if handle is not None:
                try:
                    if locked:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                finally:
                    handle.close()

    def _read_disk_entries(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except Exception as exc:
            logger.debug("Failed to read model picker catalog cache: %s", exc)
            return {}
        if not isinstance(data, dict) or data.get("schema") != CACHE_SCHEMA_VERSION:
            return {}
        entries = data.get("entries")
        return entries if isinstance(entries, dict) else {}

    def _load_locked(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._entries = self._read_disk_entries()
        self._disk_mtime_ns = self._cache_mtime_ns()

    def _reload_if_changed_locked(self) -> None:
        current_mtime = self._cache_mtime_ns()
        if not self._loaded or current_mtime != self._disk_mtime_ns:
            self._entries = self._read_disk_entries()
            self._disk_mtime_ns = current_mtime
            self._loaded = True

    def _save_locked(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"schema": CACHE_SCHEMA_VERSION, "entries": self._entries}
            tmp = self.cache_path.with_name(
                f"{self.cache_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self.cache_path)
            self._disk_mtime_ns = self._cache_mtime_ns()
        except Exception as exc:
            logger.debug("Failed to write model picker catalog cache: %s", exc)

    def store(self, fingerprint: str, providers: ProviderRows, *, fetched_at: float | None = None) -> None:
        rows = copy.deepcopy(providers or [])
        key = str(fingerprint)
        with self._lock:
            self._load_locked()
            entry = {
                "fetched_at": float(fetched_at if fetched_at is not None else _now()),
                "providers": rows,
            }
            # Merge against the latest on-disk snapshot before writing. Multiple
            # CLI/TUI processes can warm different fingerprints concurrently;
            # rewriting only this process's stale in-memory snapshot would drop
            # entries written by siblings.
            with self._file_lock():
                entries = self._read_disk_entries()
                entries[key] = entry
                self._entries = entries
                self._save_locked()

    def _entry_locked(self, fingerprint: str) -> dict[str, Any] | None:
        self._reload_if_changed_locked()
        entry = self._entries.get(str(fingerprint))
        if not isinstance(entry, dict):
            return None
        providers = entry.get("providers")
        fetched_at = entry.get("fetched_at")
        if not isinstance(providers, list) or not isinstance(fetched_at, (int, float)):
            return None
        return entry

    def get_cached(self, fingerprint: str, *, allow_stale: bool = True) -> ProviderRows | None:
        with self._lock:
            entry = self._entry_locked(fingerprint)
            if entry is None:
                return None
            age = max(0.0, _now() - float(entry["fetched_at"]))
            if age > self.usable_for_seconds:
                return None
            if not allow_stale and age > self.stale_after_seconds:
                return None
            return copy.deepcopy(entry["providers"])

    def is_stale(self, fingerprint: str) -> bool:
        with self._lock:
            entry = self._entry_locked(fingerprint)
            if entry is None:
                return True
            return max(0.0, _now() - float(entry["fetched_at"])) > self.stale_after_seconds

    def has_entry(self, fingerprint: str) -> bool:
        with self._lock:
            return self._entry_locked(fingerprint) is not None
    def is_refreshing(self, fingerprint: str) -> bool:
        key = str(fingerprint)
        with self._lock:
            thread = self._refresh_threads.get(key)
            return bool(thread and thread.is_alive())

    def _refresh_result(self, fingerprint: str, result: Any) -> tuple[str, ProviderRows]:
        if isinstance(result, tuple) and len(result) == 2:
            rows, store_fingerprint = result
            return str(store_fingerprint or fingerprint), copy.deepcopy(rows or [])
        return str(fingerprint), copy.deepcopy(result or [])

    def schedule_refresh(self, fingerprint: str, refresh_fn: RefreshFn) -> threading.Thread:
        key = str(fingerprint)
        with self._lock:
            existing = self._refresh_threads.get(key)
            if existing and existing.is_alive():
                return existing

            def _run() -> None:
                try:
                    result = refresh_fn()
                    store_key, providers = self._refresh_result(key, result)
                    if isinstance(providers, list):
                        self.store(store_key, providers)
                except Exception as exc:
                    logger.debug("Model picker catalog refresh failed: %s", exc)
                finally:
                    with self._lock:
                        current = self._refresh_threads.get(key)
                        if current is threading.current_thread():
                            self._refresh_threads.pop(key, None)

            thread = threading.Thread(
                target=_run,
                name="model-picker-catalog-refresh",
                daemon=True,
            )
            self._refresh_threads[key] = thread
            thread.start()
            return thread

    def wait_for_refresh(self, fingerprint: str, *, timeout: float | None = None) -> None:
        with self._lock:
            thread = self._refresh_threads.get(str(fingerprint))
        if thread:
            thread.join(timeout=timeout)

    def get_or_refresh(
        self,
        fingerprint: str,
        refresh_fn: RefreshFn,
        *,
        background: bool = True,
    ) -> ProviderRows:
        cached = self.get_cached(fingerprint, allow_stale=True)
        if cached is not None:
            if self.is_stale(fingerprint):
                self.schedule_refresh(fingerprint, refresh_fn)
            return cached
        if background:
            self.schedule_refresh(fingerprint, refresh_fn)
            return []
        result = refresh_fn()
        store_key, providers = self._refresh_result(fingerprint, result)
        self.store(store_key, providers)
        return copy.deepcopy(providers)


_DEFAULT_CACHE = ModelPickerCatalogCache()


def _default_context() -> dict[str, Any]:
    try:
        from hermes_cli.config import get_compatible_custom_providers, load_config

        cfg = load_config()
    except Exception:
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}

    model_cfg = cfg.get("model")
    if isinstance(model_cfg, dict):
        current_model = model_cfg.get("default", model_cfg.get("name", "")) or ""
        current_provider = model_cfg.get("provider", "") or ""
        current_base_url = model_cfg.get("base_url", "") or ""
    else:
        current_model = str(model_cfg or "")
        current_provider = ""
        current_base_url = ""

    try:
        custom_providers = get_compatible_custom_providers(cfg) if isinstance(cfg, dict) else []
    except Exception:
        custom_providers = cfg.get("custom_providers", []) if isinstance(cfg, dict) else []

    return {
        "current_provider": current_provider,
        "current_base_url": current_base_url,
        "current_model": current_model,
        "user_providers": cfg.get("providers") if isinstance(cfg.get("providers"), dict) else {},
        "custom_providers": custom_providers if isinstance(custom_providers, list) else [],
    }


def _resolve_context(
    *,
    current_provider: str = "",
    current_base_url: str = "",
    current_model: str = "",
    user_providers: dict | None = None,
    custom_providers: list | None = None,
) -> dict[str, Any]:
    if user_providers is not None or custom_providers is not None or current_provider or current_base_url or current_model:
        return {
            "current_provider": current_provider,
            "current_base_url": current_base_url,
            "current_model": current_model,
            "user_providers": user_providers or {},
            "custom_providers": custom_providers or [],
        }
    return _default_context()


def _context_and_fingerprint(
    *,
    current_provider: str = "",
    current_base_url: str = "",
    current_model: str = "",
    user_providers: dict | None = None,
    custom_providers: list | None = None,
    max_models: int = 50,
) -> tuple[dict[str, Any], str]:
    ctx = _resolve_context(
        current_provider=current_provider,
        current_base_url=current_base_url,
        current_model=current_model,
        user_providers=user_providers,
        custom_providers=custom_providers,
    )
    fingerprint = model_picker_catalog_fingerprint(max_models=max_models, **ctx)
    return ctx, fingerprint


def get_model_picker_catalog_status(
    *,
    current_provider: str = "",
    current_base_url: str = "",
    current_model: str = "",
    user_providers: dict | None = None,
    custom_providers: list | None = None,
    max_models: int = 50,
) -> dict[str, Any]:
    """Return cache status metadata for callers that need empty-vs-warming UX."""

    _ctx, fingerprint = _context_and_fingerprint(
        current_provider=current_provider,
        current_base_url=current_base_url,
        current_model=current_model,
        user_providers=user_providers,
        custom_providers=custom_providers,
        max_models=max_models,
    )
    return {
        "fingerprint": fingerprint,
        "cached": _DEFAULT_CACHE.has_entry(fingerprint),
        "refreshing": _DEFAULT_CACHE.is_refreshing(fingerprint),
    }


def _decorate_provider_rows(
    rows: ProviderRows,
    *,
    current_provider: str = "",
) -> ProviderRows:
    decorated = copy.deepcopy(rows or [])
    selected = str(current_provider or "").strip().lower()
    if not selected:
        return decorated
    for row in decorated:
        if isinstance(row, dict):
            row["is_current"] = str(row.get("slug") or "").strip().lower() == selected
    return decorated


def get_model_picker_providers_cached(
    *,
    current_provider: str = "",
    current_base_url: str = "",
    current_model: str = "",
    user_providers: dict | None = None,
    custom_providers: list | None = None,
    max_models: int = 50,
    background: bool = True,
) -> ProviderRows:
    """Return cached picker rows and refresh stale/missing catalogs in background."""

    ctx, fingerprint = _context_and_fingerprint(
        current_provider=current_provider,
        current_base_url=current_base_url,
        current_model=current_model,
        user_providers=user_providers,
        custom_providers=custom_providers,
        max_models=max_models,
    )
    def _refresh() -> tuple[ProviderRows, str]:
        from hermes_cli.model_switch import list_authenticated_providers

        rows = list_authenticated_providers(
            current_provider=ctx["current_provider"],
            current_base_url=ctx["current_base_url"],
            current_model=ctx["current_model"],
            user_providers=ctx["user_providers"],
            custom_providers=ctx["custom_providers"],
            max_models=max_models,
        )
        _, refreshed_fingerprint = _context_and_fingerprint(
            current_provider=ctx["current_provider"],
            current_base_url=ctx["current_base_url"],
            current_model=ctx["current_model"],
            user_providers=ctx["user_providers"],
            custom_providers=ctx["custom_providers"],
            max_models=max_models,
        )
        return rows, refreshed_fingerprint

    rows = _DEFAULT_CACHE.get_or_refresh(fingerprint, _refresh, background=background)
    return _decorate_provider_rows(rows, current_provider=ctx["current_provider"])


def prime_model_picker_catalog_cache(
    *,
    current_provider: str = "",
    current_base_url: str = "",
    current_model: str = "",
    user_providers: dict | None = None,
    custom_providers: list | None = None,
    max_models: int = 50,
) -> None:
    """Start a background refresh for the current picker context."""

    get_model_picker_providers_cached(
        current_provider=current_provider,
        current_base_url=current_base_url,
        current_model=current_model,
        user_providers=user_providers,
        custom_providers=custom_providers,
        max_models=max_models,
        background=True,
    )
