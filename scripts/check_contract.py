#!/usr/bin/env python3
"""Checks that the frontend and the backend still agree. Needs only Python (pydantic is imported from the backend).

    python scripts/check_contract.py

It verifies, without starting any server:
  1. every API call in frontend/lib/api.ts has a matching FastAPI route (same method and path),
  2. every TypeScript interface in frontend/lib/types.ts has exactly the fields of the Pydantic model with the same name,
  3. the string unions (statuses, stages) match the Pydantic Literals,
  4. multipart form field names match,
  5. the frontend contains no old or hard-coded API paths (/api/v1, /fastapi, /backend, localhost URLs),
  6. every environment variable read by backend/app/config.py is documented in backend/.env.example.
Exit code 0 means everything matches.
"""

from __future__ import annotations

import ast
import re
import sys
import typing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

# TypeScript interface -> Pydantic model name when they differ.
MODEL_ALIASES = {"ConfigOption": None, "ErrorBody": "ErrorResponse"}
UNIONS = {
    "ScrapeStatus": "ScrapeStatus", "JobStatus": "JobStatus", "ScrapeStage": "ScrapeStage", "AdStatus": "AdStatus", "AdStage": "AdStage",
    "CreationMode": "CreationMode", "CreativeMode": "CreativeMode", "SegmentKind": "SegmentKind",
}
FORBIDDEN = (r"/api/v1", r"/fastapi", r"/backend\b", r"localhost:\d+", r"127\.0\.0\.1", r"https?://(?!www\.w3\.org)")


def backend_routes() -> set[tuple[str, str]]:
    """(METHOD, path) for every route declared in backend/app/api/routes.py, read with ast (FastAPI is not needed)."""
    tree = ast.parse((BACKEND / "app/api/routes.py").read_text(encoding="utf-8"))
    prefix = ""
    prefixes: dict[str, str] = {}
    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = node.value.value
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and getattr(node.value.func, "id", "") == "APIRouter":
            name = node.targets[0].id  # type: ignore[union-attr]
            prefix = ""
            for kw in node.value.keywords:
                if kw.arg == "prefix":
                    prefix = kw.value.value if isinstance(kw.value, ast.Constant) else constants.get(getattr(kw.value, "id", ""), "")
            prefixes[name] = prefix
    routes: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and isinstance(dec.func.value, ast.Name):
                    router, method = dec.func.value.id, dec.func.attr.upper()
                    if router in prefixes and method in {"GET", "POST", "PUT", "PATCH", "DELETE"} and dec.args and isinstance(dec.args[0], ast.Constant):
                        routes.add((method, prefixes[router] + dec.args[0].value))
    return routes


def route_form_fields() -> set[str]:
    """Names of multipart form parameters (Form / File) in routes.py."""
    tree = ast.parse((BACKEND / "app/api/routes.py").read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args.args + node.args.kwonlyargs
            defaults = [None] * (len(node.args.args) - len(node.args.defaults)) + list(node.args.defaults) + list(node.args.kw_defaults)
            for arg, default in zip(args, defaults):
                if isinstance(default, ast.Call) and getattr(default.func, "id", "") in {"Form", "File"}:
                    names.add(arg.arg)
    return names


def frontend_calls() -> tuple[set[tuple[str, str]], set[str]]:
    """((METHOD, path) calls, form field names) found in frontend/lib/api.ts."""
    text = (FRONTEND / "lib/api.ts").read_text(encoding="utf-8")
    calls: set[tuple[str, str]] = set()
    for match in re.finditer(r'(?P<before>[^\n]{0,60})(?P<quote>["`])(?P<path>/api/[^"`]*)(?P=quote)(?P<after>[^\n]{0,160})', text):
        path = re.sub(r"\$\{[^}]*\}", "{param}", match.group("path"))
        path = path.split("?")[0].rstrip("/")
        context = match.group("before") + match.group("after")
        method = "POST" if ("postJson" in match.group("before") or 'method: "POST"' in context) else "GET"
        calls.add((method, path))
    forms = set(re.findall(r'\.append\("([^"]+)"', text))
    return calls, forms


def normalise_route(path: str) -> str:
    """Turn /api/jobs/{job_id} into /api/jobs/{param}."""
    return re.sub(r"\{[^}]+\}", "{param}", path)


def ts_interfaces() -> dict[str, set[str]]:
    """Interface name -> field names from frontend/lib/types.ts."""
    text = (FRONTEND / "lib/types.ts").read_text(encoding="utf-8")
    result: dict[str, set[str]] = {}
    for match in re.finditer(r"export interface (\w+)[^{]*\{(.*?)\n\}", text, re.S):
        result[match.group(1)] = set(re.findall(r"^\s{2}(\w+)\??:", match.group(2), re.M))
    return result


def ts_unions() -> dict[str, set[str]]:
    """Union alias name -> string literal members (aliases that mention other unions are expanded)."""
    text = (FRONTEND / "lib/types.ts").read_text(encoding="utf-8")
    bodies = {m.group(1): m.group(2) for m in re.finditer(r"export type (\w+) =\s*(.*?);", text, re.S)}
    result: dict[str, set[str]] = {}

    def expand(name: str, seen: frozenset[str] = frozenset()) -> set[str]:
        """Literals of one alias, following references to other aliases."""
        body = bodies[name]
        values = set(re.findall(r'"([a-z_0-9]+)"', body))
        for word in re.findall(r"\b([A-Z]\w+)\b", body):
            if word in bodies and word not in seen and word != name:
                values |= expand(word, seen | {name})
        return values

    for name in bodies:
        result[name] = expand(name)
    return result


def env_names_in_config() -> set[str]:
    """Environment variable names read by backend/app/config.py (g("NAME", ...))."""
    text = (BACKEND / "app/config.py").read_text(encoding="utf-8")
    return set(re.findall(r'\bg\("([A-Z][A-Z0-9_]+)"', text))


def env_names_documented() -> set[str]:
    """Variable names in backend/.env.example, commented or not."""
    path = BACKEND / ".env.example"
    if not path.exists():
        return set()
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", path.read_text(encoding="utf-8"), re.M))


def forbidden_in_frontend() -> list[str]:
    """Old or hard-coded API addresses in the frontend source."""
    problems: list[str] = []
    for folder in ("app", "components", "lib"):
        for path in (FRONTEND / folder).rglob("*"):
            if path.suffix not in {".ts", ".tsx", ".css"} or not path.is_file():
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("//")[0] if "http" not in line.split("//")[0] else line
                for pattern in FORBIDDEN:
                    if re.search(pattern, code):
                        problems.append(f"{path.relative_to(ROOT)}:{number}: forbidden pattern {pattern!r}: {line.strip()[:100]}")
    return problems


def run() -> list[str]:
    """Run every check and return the list of problems (empty means OK)."""
    problems: list[str] = []
    sys.path.insert(0, str(BACKEND))
    from app import schemas  # noqa: E402  (imported late so the path above is in place)

    routes = {(m, normalise_route(p)) for m, p in backend_routes()}
    calls, forms = frontend_calls()
    if not routes:
        problems.append("no routes found in backend/app/api/routes.py")
    for method, path in sorted(calls):
        if (method, path) not in routes:
            problems.append(f"frontend calls {method} {path} but the backend has no such route")
    for needed in ("kind", "files"):
        if needed in route_form_fields() and needed not in forms:
            problems.append(f"backend expects form field '{needed}' but frontend/lib/api.ts never sends it")
    for sent in forms:
        if sent not in route_form_fields():
            problems.append(f"frontend sends form field '{sent}' that the backend upload route does not read")

    interfaces = ts_interfaces()
    for name, fields in sorted(interfaces.items()):
        model_name = MODEL_ALIASES.get(name, name) if name in MODEL_ALIASES else name
        if model_name is None:
            continue
        model = getattr(schemas, model_name, None)
        if model is None:
            problems.append(f"TypeScript interface {name} has no Pydantic model {model_name}")
            continue
        model_fields = set(model.model_fields)
        if fields - model_fields:
            problems.append(f"{name}: fields only in TypeScript: {sorted(fields - model_fields)}")
        if model_fields - fields:
            problems.append(f"{name}: fields only in the backend model: {sorted(model_fields - fields)}")
    unions = ts_unions()
    for ts_name, py_name in UNIONS.items():
        py_values = set(typing.get_args(getattr(schemas, py_name)))
        if unions.get(ts_name) != py_values:
            problems.append(f"{ts_name}: TypeScript has {sorted(unions.get(ts_name, set()))}, backend has {sorted(py_values)}")

    for line in forbidden_in_frontend():
        problems.append(line)
    api_text = (FRONTEND / "lib/api.ts").read_text(encoding="utf-8")
    if "NEXT_PUBLIC_API_BASE_URL" not in api_text:
        problems.append("frontend/lib/api.ts must read NEXT_PUBLIC_API_BASE_URL")
    env_example = FRONTEND / ".env.example"
    if not env_example.exists() or "NEXT_PUBLIC_API_BASE_URL" not in env_example.read_text(encoding="utf-8"):
        problems.append("frontend/.env.example must document NEXT_PUBLIC_API_BASE_URL")
    missing_env = sorted(env_names_in_config() - env_names_documented())
    if missing_env:
        problems.append(f"backend/.env.example does not mention: {missing_env}")
    return problems


def main() -> int:
    """Print the result and return the exit code."""
    problems = run()
    routes = backend_routes()
    calls, _ = frontend_calls()
    print(f"backend routes: {len(routes)}   frontend calls: {len(calls)}")
    if problems:
        print("\nPROBLEMS")
        for problem in problems:
            print(" -", problem)
        return 1
    print("OK: frontend and backend agree (routes, fields, enums, form fields, env, no old paths).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
