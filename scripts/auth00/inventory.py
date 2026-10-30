"""AUTH-00 source inventory. Stdlib only; never imports or starts the application.

Unsupported registration forms, missing reviews and snapshot drift are errors.
This is a review gate, NOT a runtime authorization engine.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
DEST = Path('docs/auth00')
VERBS = {'get', 'post', 'put', 'patch', 'delete', 'options', 'head', 'trace', 'api_route', 'websocket'}
GUARD_WORDS = ('auth', 'principal', 'subject', 'session', 'scope', 'capabil', 'access', 'permission')
WIDGETS = {'button', 'download_button', 'file_uploader', 'form_submit_button', 'data_editor', 'text_input', 'text_area', 'selectbox', 'multiselect', 'radio', 'checkbox', 'number_input', 'slider', 'date_input', 'time_input', 'toggle'}


def tree(root, path):
    return ast.parse((root / path).read_text(encoding='utf-8-sig'), filename=str(path))


def expr(node):
    return ast.unparse(node)


def literal(node, what):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError) as exc:
        raise ValueError(f'Nonliteral {what}: {expr(node)}') from exc


def kw(call, name, default=None):
    for item in call.keywords:
        if item.arg == name:
            return item.value
        if item.arg is None:
            raise ValueError('Expanded route kwargs require explicit collector support')
    return default


def deps(nodes):
    result = set()
    for node in nodes:
        if node is None:
            continue
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and expr(call.func).split('.')[-1] in {'Depends', 'Security'} and call.args:
                result.add(expr(call.args[0]))
    return sorted(result)


def join(*parts):
    result = '/'.join(str(p).strip('/') for p in parts if p)
    suffix = '/' if parts and str(parts[-1]).endswith('/') and result else ''
    return '/' + result + suffix if result else '/'


def unique(entries):
    ids = [e['id'] for e in entries]
    duplicates = [k for k, n in Counter(ids).items() if n > 1]
    if duplicates:
        raise ValueError(f'Duplicate entry points: {duplicates}')
    return sorted(entries, key=lambda e: e['id'])


def api_routes(root):
    """Resolve literal APIRouter mounts, nested routers and local register(r) factories."""
    routers, records, includes, apps = {}, {}, {}, []
    for path in sorted((root / 'apps/api').rglob('*.py')):
        if path.name.startswith('test_'):
            continue
        rel = path.relative_to(root).as_posix()
        module = rel[:-3].replace('/', '.')
        t = tree(root, rel)
        imports = {}
        for n in t.body:
            if isinstance(n, ast.ImportFrom) and n.module:
                for a in n.names:
                    imports[a.asname or a.name] = n.module + '.' + a.name
            elif isinstance(n, ast.Import):
                for a in n.names:
                    imports[a.asname or a.name] = a.name

        def resolve(node):
            name = expr(node)
            base, *tail = name.split('.')
            return '.'.join([imports.get(base, module + '.' + base)] + tail)

        local = {}
        for n in t.body:
            if not isinstance(n, (ast.Assign, ast.AnnAssign)) or not isinstance(n.value, ast.Call):
                continue
            ctor = expr(n.value.func).split('.')[-1]
            if ctor not in {'FastAPI', 'APIRouter'}:
                continue
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            if len(targets) != 1 or not isinstance(targets[0], ast.Name):
                raise ValueError(f'Unsupported router assignment: {rel}:{n.lineno}')
            name = targets[0].id
            ref = module + '.' + name
            prefix_node = kw(n.value, 'prefix')
            prefix = literal(prefix_node, 'router prefix') if prefix_node else ''
            local[name] = ref
            routers[ref] = {'prefix': prefix, 'dependencies': deps([kw(n.value, 'dependencies')]), 'source': rel, 'line': n.lineno}
            records[ref], includes[ref] = [], []
            if ctor == 'FastAPI':
                apps.append((ref, n.value))

        factories = {n.name: n for n in t.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        bindings = []
        decorator_calls = set()
        for n in t.body:
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name) and n.value.func.id in factories:
                fn = factories[n.value.func.id]
                for param, arg in zip(fn.args.args, n.value.args):
                    if expr(arg) in local:
                        bindings.append((fn.name, param.arg, local[expr(arg)]))

        def visit_functions(body, parent=None):
            for fn in body:
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for d in fn.decorator_list:
                    if not isinstance(d, ast.Call) or not isinstance(d.func, ast.Attribute) or d.func.attr not in VERBS:
                        continue
                    receiver = expr(d.func.value)
                    decorator_calls.add(id(d))
                    owners = [local[receiver]] if receiver in local else [ref for factory, param, ref in bindings if factory == parent and param == receiver]
                    if not owners:
                        raise ValueError(f'Unresolved route receiver {rel}:{d.lineno}: {receiver}')
                    if not d.args:
                        raise ValueError(f'Missing literal path {rel}:{d.lineno}')
                    path_value = literal(d.args[0], 'route path')
                    if not isinstance(path_value, str):
                        raise ValueError('Route path must be a string')
                    methods = [d.func.attr.upper()]
                    if d.func.attr == 'api_route':
                        m = kw(d, 'methods')
                        if m is None:
                            raise ValueError('api_route must declare methods explicitly')
                        methods = literal(m, 'route methods')
                    if not isinstance(methods, (list, tuple, set)) or not methods or any(not isinstance(method, str) or method.upper() not in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'TRACE', 'WEBSOCKET'} for method in methods):
                        raise ValueError('Explicit supported route methods are required')
                    calls = sorted({expr(c.func) for c in ast.walk(fn) if isinstance(c, ast.Call) and any(word in expr(c.func).lower() for word in GUARD_WORDS)})
                    for owner in owners:
                        for method in methods:
                            record = {'kind': 'api', 'method': method.upper(), 'path': path_value, 'operation': module + ':' + (parent + '.' if parent else '') + fn.name,
                                      'evidence': [{'source': rel, 'line': d.lineno, 'symbol': fn.name}],
                                      'dependencies': deps([fn.args, d]), 'direct_guard_mentions': calls}
                            records[owner].append(record)
                visit_functions(fn.body, fn.name)

        visit_functions(t.body)
        for n in ast.walk(t):
            if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
                continue
            receiver = expr(n.func.value)
            if receiver not in local:
                continue
            if n.func.attr in VERBS and id(n) not in decorator_calls:
                raise ValueError(f'Functional route registration requires review: {rel}:{n.lineno}')
            if n.func.attr in {'add_api_route', 'add_route', 'mount', 'websocket_route', 'route'}:
                raise ValueError(f'Unsupported registration form {rel}:{n.lineno}: {n.func.attr}')
            if n.func.attr == 'include_router':
                prefix_node = kw(n, 'prefix')
                prefix = literal(prefix_node, 'mount prefix') if prefix_node else ''
                includes[local[receiver]].append((resolve(n.args[0]), prefix, deps([kw(n, 'dependencies')]), {'source': rel, 'line': n.lineno, 'symbol': 'include_router'}))

    if len(apps) != 1:
        raise ValueError(f'Expected one reviewed FastAPI root, found {len(apps)}')
    output, reached = [], set()

    def mount(ref, prefix='', inherited=(), chain=(), ancestors=()):
        if ref in ancestors or ref not in routers:
            raise ValueError(f'Unresolved or cyclic router mount: {ref}')
        reached.add(ref)
        meta = routers[ref]
        prefix = join(prefix, meta['prefix']).rstrip('/')
        inherited = sorted(set(inherited) | set(meta['dependencies']))
        for raw in records[ref]:
            r = dict(raw)
            r['path'] = join(prefix, raw['path'])
            r['id'] = f"api:{r['method']}:{r['path']}"
            r['dependencies'] = sorted(set(inherited) | set(raw['dependencies']))
            r['evidence'] = raw['evidence'] + list(chain)
            output.append(r)
        for child, extra, ds, site in includes[ref]:
            mount(child, join(prefix, extra), list(inherited) + ds, tuple(chain) + (site,), tuple(ancestors) + (ref,))

    mount(apps[0][0])
    unmounted = [ref for ref in records if records[ref] and ref not in reached]
    if unmounted:
        raise ValueError(f'Unmounted route definitions require review: {unmounted}')
    # Explicit framework-generated metadata endpoints, including HEAD.
    ref, ctor = apps[0]
    meta = routers[ref]
    defaults = [('openapi_url', '/openapi.json'), ('docs_url', '/docs'), ('redoc_url', '/redoc'), ('swagger_ui_oauth2_redirect_url', '/docs/oauth2-redirect')]
    options = {key: literal(kw(ctor, key), key) if kw(ctor, key) is not None else fallback for key, fallback in defaults}
    for setting, fallback in defaults:
        if not options['openapi_url'] or (setting == 'swagger_ui_oauth2_redirect_url' and not options['docs_url']):
            continue
        value = kw(ctor, setting)
        path = literal(value, setting) if value is not None else fallback
        if path is None:
            continue
        for method in ['GET', 'HEAD']:
            output.append({'id': f'api:{method}:{path}', 'kind': 'framework', 'method': method, 'path': path, 'operation': 'fastapi:' + setting, 'dependencies': [], 'direct_guard_mentions': [], 'evidence': [{'source': meta['source'], 'line': meta['line'], 'symbol': 'FastAPI defaults: ' + setting}]})
    return unique(output)


def check_entry_roots(root):
    """Reject new service roots using the runtime constructors in this project."""
    ignored = {'node_modules', 'dist', '.next', '.git', '__pycache__', 'tests', '__tests__'}
    for directory, dirs, files in os.walk(root / 'apps'):
        dirs[:] = [name for name in dirs if name not in ignored]
        for name in files:
            path = Path(directory) / name
            rel = path.relative_to(root).as_posix()
            if name.startswith('test_') or '.test.' in name:
                continue
            if path.suffix == '.py' and not rel.startswith('apps/api/'):
                for n in ast.walk(tree(root, rel)):
                    if isinstance(n, ast.Call) and expr(n.func).split('.')[-1] in {'FastAPI', 'APIRouter', 'Starlette', 'Flask'}:
                        raise ValueError('New Python service root requires review: ' + rel)
            if path.suffix in {'.ts', '.tsx', '.js', '.mjs'} and rel != 'apps/print-renderer/src/server.ts':
                if re.search(r'\bcreateServer\s*\(', path.read_text(encoding='utf-8')):
                    raise ValueError('New HTTP service root requires review: ' + rel)


def discovery(root):
    check_entry_roots(root)
    entries = api_routes(root)
    server = root / 'apps/print-renderer/src/server.ts'
    if server.exists():
        text = server.read_text(encoding='utf-8')
        pattern = r'req\.method\s*===\s*"([A-Z]+)"\s*&&\s*url\s*===\s*"([^"\n]+)"'
        matches = list(re.finditer(pattern, text))
        if len(matches) != len(re.findall(r'req\.method\s*===', text)):
            raise ValueError('Renderer route syntax changed; explicit review required')
        for m in matches:
            method, path = m.groups()
            entries.append({'id': f'renderer:{method}:{path}', 'kind': 'renderer', 'method': method, 'path': path, 'operation': 'renderer:' + path, 'evidence': [{'source': 'apps/print-renderer/src/server.ts', 'line': text[:m.start()].count('\n') + 1, 'symbol': 'createRendererServer'}]})
    for shell in ['embedded', 'standalone']:
        app = root / f'apps/{shell}/app'
        if not app.exists():
            continue
        for page in sorted(app.rglob('page.tsx')):
            rel = page.relative_to(root).as_posix()
            route = '/' + page.parent.relative_to(app).as_posix().replace('.', '').strip('/')
            text = page.read_text(encoding='utf-8')
            entries.append({'id': f'page:{shell}:{route}', 'kind': 'page', 'method': 'GET', 'path': route, 'operation': f'ui:{shell}:{route}', 'redirects': re.findall(r'\bredirect\(["\x27]([^"\x27]+)', text), 'evidence': [{'source': rel, 'line': 1, 'symbol': 'Page'}]})
        for route in sorted(app.rglob('route.*')):
            raise ValueError(f'New Next route handler requires collector support: {route.relative_to(root)}')
        for base in [root / f'apps/{shell}', root / f'apps/{shell}/src']:
            for name in ['middleware.ts', 'middleware.js']:
                if (base / name).exists():
                    raise ValueError('New middleware requires explicit review: ' + str(base / name))
        config = root / f'apps/{shell}/next.config.mjs'
        text = config.read_text(encoding='utf-8')
        pairs = re.findall(r'source:\s*"([^"\n]+)"\s*,\s*destination:\s*`([^`]+)`', text)
        if not pairs:
            raise ValueError(f'Proxy rewrite requires review: {config}')
        for source, destination in pairs:
            entries.append({'id': f'proxy:{shell}:{source}', 'kind': 'proxy', 'method': '*', 'path': source, 'operation': 'proxy:' + shell, 'destination_template': destination, 'evidence': [{'source': config.relative_to(root).as_posix(), 'line': text[:text.index('source:')].count('\n') + 1, 'symbol': 'rewrites'}]})
        for asset in sorted((root / f'apps/{shell}/public').rglob('*')):
            if asset.is_file():
                route = '/' + asset.relative_to(root / f'apps/{shell}/public').as_posix()
                entries.append({'id': f'asset:{shell}:{route}', 'kind': 'static_asset', 'method': 'GET', 'path': route, 'operation': 'public.asset', 'asset_file': asset.relative_to(root).as_posix(), 'evidence': [{'source': config.relative_to(root).as_posix(), 'line': 1, 'symbol': 'Next public directory'}]})
    legacy = root / 'app.py'
    if legacy.exists():
        for n in ast.walk(tree(root, 'app.py')):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in WIDGETS:
                label = expr(n.args[0]) if n.args else '(label via kwargs)'
                entries.append({'id': f'legacy:app.py:{n.lineno}:{n.func.attr}', 'kind': 'legacy_widget', 'method': 'RERUN', 'path': 'Streamlit session', 'operation': f'legacy:{n.func.attr}', 'label_expression': label, 'evidence': [{'source': 'app.py', 'line': n.lineno, 'symbol': n.func.attr}]})
    task_file = root / 'packages/ui/lib/task-stops.ts'
    if task_file.exists():
        text = task_file.read_text(encoding='utf-8')
        for m in re.finditer(r'href:\s*"(/tasks/[^"\n]+)"', text):
            route = m.group(1)
            entries.append({'id': 'task_alias:' + route, 'kind': 'task_alias', 'method': 'NAVIGATE', 'path': route, 'operation': 'application:' + route.rsplit('/', 1)[-1], 'evidence': [{'source': 'packages/ui/lib/task-stops.ts', 'line': text[:m.start()].count('\n') + 1, 'symbol': 'TASK_UNITS href'}]})
    # Inventory real thread starts, including render timeout threads. Logical
    # worker execution/cleanup and storage boundaries are separately reviewed.
    for path in sorted((root / 'apps/api').rglob('*.py')):
        if path.name.startswith('test_'):
            continue
        rel = path.relative_to(root).as_posix()
        for n in ast.walk(tree(root, rel)):
            if isinstance(n, ast.Call) and expr(n.func) in {'threading.Thread', 'Thread', 'ThreadPoolExecutor', 'ProcessPoolExecutor'}:
                target = kw(n, 'target')
                name = expr(target) if target else 'executor'
                entries.append({'id': f'worker:{rel}:{n.lineno}', 'kind': 'worker', 'method': 'DISPATCH', 'path': name, 'operation': rel + ':' + name, 'evidence': [{'source': rel, 'line': n.lineno, 'symbol': name}]})
    return unique(entries)


def review_catalog(root):
    path = root / DEST / 'policy_review.json'
    if not path.is_file():
        raise ValueError('Missing explicit AUTH-00 policy review catalogue')
    return json.loads(path.read_text(encoding='utf-8'))


def build(root=ROOT):
    root = Path(root)
    raw = discovery(root)
    review = review_catalog(root)
    raw = [{**e, 'discovery': 'automatic'} for e in raw]
    for e in review.get('extra_surfaces', []):
        if e['kind'] not in {'worker', 'storage', 'internal_operation', 'transport', 'legacy_authority'} or e['id'].startswith(('api:', 'renderer:', 'page:', 'proxy:', 'asset:')):
            raise ValueError('Manual extras cannot invent HTTP/page routes: ' + e['id'])
        raw.append({**e, 'discovery': 'manual-reviewed'})
    raw = unique(raw)
    bindings = review['entries']
    if set(bindings) != {x['id'] for x in raw}:
        raise ValueError('Unclassified or removed entries: ' + repr(sorted(set(bindings) ^ {x['id'] for x in raw})))
    policies = review['policies']
    threat_path = root / DEST / 'threat_model.md'
    threats = set(re.findall(r'^### (T\d+) —', threat_path.read_text(encoding='utf-8'), re.M)) if threat_path.is_file() else set()
    plan_path = root / 'spec_auth_architecture.md'
    task_ids = set(re.findall(r'\bAUTH-(?:\d{2}|CERT)\b', plan_path.read_text(encoding='utf-8'))) if plan_path.is_file() else set()
    for key, policy in policies.items():
        if not all(policy.get(k) for k in ['observed', 'target']):
            raise ValueError('Missing observed/target policy: ' + key)
        if not set(policy['threats']) <= threats:
            raise ValueError('Unknown threat reference in policy ' + key)
        if task_ids and not set(policy['follow_up']) <= task_ids:
            raise ValueError('Unknown AUTH task reference in policy ' + key)
    semantic_keys = {'policy', 'stage', 'stage_namespace', 'resource', 'effects', 'canonical_operation', 'admission', 'threats'}
    for e in raw:
        binding = bindings[e['id']]
        if set(binding) - semantic_keys:
            raise ValueError('Review cannot overwrite discovered source fields: ' + e['id'])
        if not set(binding.get('threats', [])) <= threats:
            raise ValueError('Unknown threat reference for ' + e['id'])
        if binding['policy'] not in policies:
            raise ValueError('Unknown policy for ' + e['id'])
        e.update(binding)
        if not all(e.get(k) for k in ['operation', 'evidence', 'stage', 'stage_namespace', 'resource', 'effects', 'canonical_operation', 'admission']):
            raise ValueError('Incomplete operation review for ' + e['id'])
        for ev in e['evidence']:
            source = root / ev['source']
            if not source.is_file() or ev['line'] < 1 or ev['line'] > len(source.read_text(encoding='utf-8').splitlines()):
                raise ValueError('Invalid source evidence for ' + e['id'])
    source_files = {ev['source'] for e in raw for ev in e['evidence']}
    source_files.update(e['asset_file'] for e in raw if 'asset_file' in e)
    source_files.update(review['reviewed_sources'])
    # Freeze the full reviewed Python API surface as well as its declarations:
    # changing a guard body or adding an unseen entry module also causes drift.
    source_files.update(p.relative_to(root).as_posix() for p in (root / 'apps/api').rglob('*.py') if not p.name.startswith('test_'))
    def source_digest(path):
        data = (root / path).read_bytes()
        if Path(path).suffix in {'.py', '.ts', '.tsx', '.js', '.mjs', '.md', '.json', '.yml', '.yaml'}:
            data = data.replace(b'\r\n', b'\n')
        return hashlib.sha256(data).hexdigest()
    fingerprints = {p: source_digest(p) for p in sorted(source_files)}
    return {'schema_version': 'auth00.inventory/1', 'baseline': review['baseline'], 'scope': review['scope'],
            'counts': dict(sorted(Counter(e['kind'] for e in raw).items())), 'policies': policies,
            'source_fingerprints': fingerprints, 'entries': raw}


def json_text(report):
    return json.dumps(report, ensure_ascii=False, indent=2) + '\n'


def markdown(report):
    lines = ['# AUTH-00 — route/operation inventory', '',
             'База: `' + report['baseline'] + '`. Автоматически собранные входы + явная policy review.', '',
             '**Observed — текущее поведение. Target — требования следующих AUTH-задач, не реализованные guards.**', '',
             'Проверка: `python3 scripts/auth00/inventory.py --check`. Обновление после review: `--write`.', '',
             'Источник истины и подробные evidence/dependencies/effects: [inventory.json](inventory.json).',
             'Модель угроз: [threat_model.md](threat_model.md). Процесс и границы: [design.md](design.md).', '',
             '| Вид | Число |', '|---|---:|']
    lines += [f'| {k} | {v} |' for k, v in report['counts'].items()]
    lines += ['', '## Классификации', '', '| Policy | Observed | Target | Follow-up |', '|---|---|---|---|']
    def cell(v):
        return str(v).replace('|', '\\|').replace('\n', ' ')
    for key, p in sorted(report['policies'].items()):
        lines.append('| ' + ' | '.join(map(cell, [key, p['observed'], p['target'], ', '.join(p['follow_up'])])) + ' |')
    for kind in report['counts']:
        lines += ['', '## ' + kind, '', '| ID / метод и путь | Operation / stage | Policy / resource | Источник |', '|---|---|---|---|']
        for e in report['entries']:
            if e['kind'] != kind:
                continue
            ev = e['evidence'][0]
            lines.append('| ' + ' | '.join(map(cell, [e['id'], e['operation'] + ' / ' + e['stage_namespace'] + ':' + e['stage'], e['policy'] + ' / ' + e['resource'], ev['source'] + ':' + str(ev['line'])])) + ' |')
    return '\n'.join(lines) + '\n'


def check(root=ROOT, candidate=None):
    root = Path(root)
    actual = build(root)
    if candidate is not None and candidate != actual:
        raise ValueError('Candidate inventory differs from independently rediscovered sources/review')
    for name, text in [('inventory.json', json_text(actual)), ('inventory.md', markdown(actual))]:
        path = root / DEST / name
        if not path.is_file() or path.read_text(encoding='utf-8') != text:
            raise ValueError('Inventory drift: ' + str(DEST / name))
    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true')
    action.add_argument('--write', action='store_true')
    action.add_argument('--discover', action='store_true')
    args = parser.parse_args()
    if args.discover:
        print(json_text({'entries': discovery(ROOT)}), end='')
        return
    report = build(ROOT)
    if args.write:
        for name, text in [('inventory.json', json_text(report)), ('inventory.md', markdown(report))]:
            (ROOT / DEST / name).write_text(text, encoding='utf-8')
    else:
        check(ROOT, report)
    print(json.dumps({'status': 'ok', 'counts': report['counts'], 'entries': len(report['entries'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
