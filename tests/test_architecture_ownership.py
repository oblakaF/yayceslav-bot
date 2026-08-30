from pathlib import Path

import runtime_bootstrap


ROOT = Path(__file__).resolve().parents[1]


def test_conflict_fsm_is_single_production_conflict_owner():
    order = runtime_bootstrap.RUNTIME_LOAD_ORDER

    assert "conflict_fsm_runtime" in order
    assert "conflict_rage_runtime" not in order
    assert "rage_hotfix_runtime" not in order


def test_fight_layers_load_after_conflict_owner():
    order = runtime_bootstrap.RUNTIME_LOAD_ORDER

    conflict = order.index("conflict_fsm_runtime")
    routing = order.index("fight_routing_v3")
    roast = order.index("roast_engine_runtime")

    assert conflict < routing < roast


def test_bootstrap_does_not_import_legacy_conflict_runtimes():
    source = (ROOT / "runtime_bootstrap.py").read_text(encoding="utf-8")
    executable_imports = {
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
    }

    assert "import conflict_rage_runtime" not in executable_imports
    assert "import rage_hotfix_runtime" not in executable_imports


def test_architecture_ownership_document_tracks_core_runtime():
    doc = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")

    for module in (
        "conflict_fsm_runtime.py",
        "fight_routing_v3.py",
        "roast_engine.py",
        "voice2_runtime.py",
        "runtime_bootstrap.py",
    ):
        assert module in doc
