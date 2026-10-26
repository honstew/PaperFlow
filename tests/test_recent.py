from __future__ import annotations

from pathlib import Path

from paperflow.core.layout import LayoutSettings
from paperflow.core.metadata import build_m4_state
from paperflow.core.project import load_project
from paperflow.core.recent import RecentProjectsStore
from paperflow.core.references import parse_references
from paperflow.core.structure import build_local_structure
from paperflow.ingest import import_document


def test_recent_store_roundtrip(tmp_path: Path) -> None:
    store = RecentProjectsStore(tmp_path / "recent-projects.json", limit=2)
    first = tmp_path / "project-a"
    second = tmp_path / "project-b"
    third = tmp_path / "project-c"
    for path in (first, second, third):
        path.mkdir()
    store.add(first, title="A", source_name="a.md", format_name="markdown")
    store.add(second, title="B", source_name="b.md", format_name="markdown")
    items = store.add(third, title="C", source_name="c.md", format_name="markdown")
    assert [item.title for item in items] == ["C", "B"]
    assert store.remove(third)[0].title == "B"


def test_load_project_reconstructs_saved_state(tmp_path: Path) -> None:
    imported = import_document(
        Path("examples/demo-paper.md"),
        projects_dir=tmp_path / "projects",
    )
    root = Path(imported.project_dir)
    structure = build_local_structure(imported.document)
    m4 = build_m4_state(imported, structure)
    references = parse_references(structure.document, structure)
    layout = LayoutSettings(columns=2)
    content = root / "content"
    content.mkdir(exist_ok=True)
    (content / "import-result.json").write_text(
        imported.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (content / "structure.json").write_text(
        structure.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (content / "m4-state.json").write_text(m4.to_json() + "\n", encoding="utf-8")
    (content / "references.json").write_text(
        references.to_json() + "\n", encoding="utf-8"
    )
    (content / "layout.json").write_text(layout.to_json() + "\n", encoding="utf-8")

    loaded = load_project(root)
    assert loaded.root == root.resolve()
    assert loaded.structure is not None
    assert loaded.m4 is not None
    assert loaded.references is not None
    assert loaded.layout is not None
    assert loaded.layout.columns == 2