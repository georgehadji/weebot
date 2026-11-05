"""Resolve secret references in the environment once, at startup (H19).

An entry point calls :func:`install_secret_sources` right after ``load_dotenv``. A variable
whose whole value is ``<scheme>://...`` for a known scheme is replaced, in memory, by the value
its source returns; nothing is written back to ``.env``. A reference that cannot be resolved
is removed from the environment, so the key is absent and the program says so rather than
sending the literal ``op://...`` string to a provider (fail closed). Values with an unknown
scheme, such as ``https://...`` URLs, are left alone.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, MutableMapping

from weebot.application.ports.secret_source_port import SecretSourceError, SecretSourcePort
from weebot.config.secret_accessor import SecretAccessor
from weebot.core.secret_provenance import SecretProvenance, provenance
from weebot.infrastructure.secrets.sources import BitwardenSource, EnvSource, OnePasswordSource

logger = logging.getLogger(__name__)

_REF = re.compile(r"^([a-z][a-z0-9+.-]*)://\S+$")


def default_sources(environ: MutableMapping[str, str]) -> list[SecretSourcePort]:
    return [EnvSource(environ), OnePasswordSource(), BitwardenSource()]


def resolve_env_refs(
    environ: MutableMapping[str, str],
    sources: Iterable[SecretSourcePort],
    report: SecretProvenance,
) -> None:
    by_scheme = {s.scheme: s for s in sources}
    for key, raw in list(environ.items()):
        ref = raw.strip()
        match = _REF.match(ref)
        source = by_scheme.get(match.group(1)) if match else None
        if source is None:
            continue
        try:
            secret = source.resolve(ref)
            failure = f"{source.name} has no value for that reference"
        except SecretSourceError as exc:
            secret, failure = None, str(exc)
        if secret is None:
            del environ[key]
            report.failed[key] = failure
            logger.error("secret %s could not be resolved (%s); it is unset", key, failure)
        else:
            environ[key] = secret.value
            report.resolved[key] = secret.source
            logger.info("secret %s resolved from %s", key, secret.source)


def install_secret_sources() -> None:
    """Resolve the references in the process environment. Safe to call twice: a resolved
    value no longer looks like a reference."""
    environ = SecretAccessor.process_environ()
    resolve_env_refs(environ, default_sources(environ), provenance())
