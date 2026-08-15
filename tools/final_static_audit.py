from __future__ import annotations

import ast
import json
from pathlib import Path

APP_FILES = [
    "bot.py",
    "personality.py",
    "intent.py",
    "humor_engine.py",
    "style_engine.py",
    "voice_packs.py",
    "voice_runtime.py",
    "historical_packs.py",
    "social_engine.py",
    "aggression_engine.py",
    "reaction_engine.py",
    "passive_engine.py",
    "daily_title_engine.py",
    "state_engine.py",
    "title_pools.py",
]


def imported_and_used(path: str):
    source = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: dict[str, tuple[str, int]] = {}
    used: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                imported[local] = (alias.name, node.lineno)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                imported[local] = (f"{node.module}.{alias.name}", node.lineno)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.add(node.id)

    return {
        local: {"source": origin, "line": line}
        for local, (origin, line) in imported.items()
        if local not in used
    }


def module_mutable_candidates(path: str):
    source = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    candidates = []

    def mutable_expr(value: ast.AST | None) -> bool:
        if value is None:
            return False
        if isinstance(value, (ast.Dict, ast.List, ast.Set)):
            return True
        if isinstance(value, ast.Call):
            if isinstance(value.func, ast.Name):
                return value.func.id in {"dict", "list", "set", "defaultdict", "deque"}
            if isinstance(value.func, ast.Attribute):
                return value.func.attr in {"dict", "list", "set", "defaultdict", "deque"}
        return False

    for node in tree.body:
        name = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            value = node.value
        if name and mutable_expr(value):
            candidates.append({"name": name, "line": node.lineno})
    return candidates


def update_based_ask_gemini_missing_context():
    source = Path("bot.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    missing = []

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.stack = []
        def visit_FunctionDef(self, node):
            self.stack.append(node)
            self.generic_visit(node)
            self.stack.pop()
        def visit_AsyncFunctionDef(self, node):
            self.stack.append(node)
            self.generic_visit(node)
            self.stack.pop()
        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id == "ask_gemini" and self.stack:
                fn = self.stack[-1]
                args = list(fn.args.posonlyargs) + list(fn.args.args) + list(fn.args.kwonlyargs)
                if "update" in {a.arg for a in args}:
                    kws = {kw.arg for kw in node.keywords if kw.arg}
                    absent = sorted({"chat_id", "chat_type", "user_id"} - kws)
                    if absent:
                        missing.append({"function": fn.name, "line": node.lineno, "missing": absent})
            self.generic_visit(node)
    Visitor().visit(tree)
    return missing


def hard_invariants():
    bot = Path("bot.py").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    style = Path("style_engine.py").read_text(encoding="utf-8")

    hard_start = bot.index("async def hard_mode_listener(")
    hard_end = bot.index("async def enforce_rate_limit(", hard_start)
    hard_block = bot[hard_start:hard_end]

    picker_start = bot.index("def pick_new_title(")
    picker_end = bot.index("\nasync def maybe_assign_daily_title", picker_start)
    picker_block = bot[picker_start:picker_end]

    import_start = bot.index("from personality import (")
    import_end = bot.index("\n)", import_start)
    personality_import = bot[import_start:import_end]

    failures = []
    if update_based_ask_gemini_missing_context():
        failures.append("update-based ask_gemini call missing identity context")
    if "random.choice(HARD_RANDOM_REPLIES)" in hard_block:
        failures.append("legacy uncontextual hard random reply fallback remains")
    if "JOKE_TITLES" in picker_block:
        failures.append("flat JOKE_TITLES picker still active")
    if "title_pools.pick_title" not in picker_block:
        failures.append("two-stage V2 title picker is not active")
    if "build_system_instruction" in personality_import:
        failures.append("unused V1 build_system_instruction import remains")
    if "gemini-3.1-flash-lite" in readme:
        failures.append("README still names old Gemini model")
    if 'MODEL_NAME = "gemini-3.6-flash"' not in bot:
        failures.append("bot current Gemini model changed unexpectedly")
    if "record=(chat_id is not None)" not in bot:
        failures.append("stateless length path is not disabling history recording")
    if "_gemini_hit_max_tokens" not in bot or "request_token_budget" not in bot:
        failures.append("adaptive MAX_TOKENS retry missing")
    if "_LENGTH_HISTORY[chat_id]\n        if record" not in style:
        failures.append("style_engine still creates persistent history in stateless path")
    return failures


def main():
    failures = hard_invariants()
    report = {
        "hard_failures": failures,
        "ask_gemini_missing_context": update_based_ask_gemini_missing_context(),
        "unused_imports": {
            path: imported_and_used(path)
            for path in APP_FILES
            if Path(path).exists()
        },
        "module_mutable_candidates": {
            path: module_mutable_candidates(path)
            for path in APP_FILES
            if Path(path).exists()
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if failures:
        raise SystemExit("Hard static audit invariants failed")


if __name__ == "__main__":
    main()
