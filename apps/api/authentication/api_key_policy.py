"""API key scope admission uses reviewed programmatic operation bindings only."""

import re

from apps.api.access_registry import REGISTRY

from .context import auth_error

OPERATION_SCOPES = {
    "validation.rules.load_rules_template": "api.read",
    "validation.rules.get_rules_templates": "api.read",
    "validation.passport": "api.compute",
    "validation.regularity": "api.compute",
    "validation.rules.validate_with_rules": "api.compute",
    "upload.file.load": "api.write",
    "upload.db.load": "api.database",
    "upload.db.probe": "api.database",
    "modeling.backtest": "api.compute",
    "modeling.candidates": "api.compute",
    "modeling.diagnostics": "api.compute",
    "modeling.train.placeholder": "api.compute",
    "modeling.tune": "api.compute",
}
# Global in-memory PATCH rules override has no Account boundary yet (AUTH-11).
# No durable key can delegate that operation or an unknown/non-programmatic path.


def admit_request(request, evidence):
    path = request.url.path
    method = request.method.upper()
    matches = []
    for key, binding in REGISTRY.bindings.items():
        if not key.startswith("api:") or not binding.programmatic_api:
            continue
        _, verb, template = key.split(":", 2)
        if verb != method:
            continue
        pattern = re.sub(r"\\\{[^}]+\\\}", r"[^/]+", re.escape(template))
        if re.fullmatch(pattern, path):
            matches.append(binding.operation_id)
    if len(matches) != 1:
        auth_error(403, "api_scope_denied")
    required = OPERATION_SCOPES.get(matches[0])
    if required is None or required not in evidence.scopes:
        auth_error(403, "api_scope_denied")
