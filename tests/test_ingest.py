from __future__ import annotations

from pathlib import Path

import pytest

from paperflow.ingest import import_document
from paperflow.ingest.importer import IngestError


def test_markdown_import_preserves_blocks_and_assets(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "fig1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    md = source / "paper.md"
    md.write_text(
        "# 基于深度学习的论文自动排版方法研究\n\n"
        "张三，李四\n\n"
        "摘要：本文研究 **自动排版** 和 $x^2$。\n\n"
        "关键词：自动排版；深度学习；XeLaTeX\n\n"
        "## 1 引言\n\n"
        "本文研究流程如图1所示。\n\n"
        "![图1 研究流程图](fig1.png)\n\n"
        "表1 不同方法的性能比较\n\n"
        "| 方法 | 准确率/% |\n"
        "|---|---|\n"
        "| 基线 | 90.1 |\n"
        "| 本文 | 93.5 |\n\n"
        "## 2 方法\n\n"
        "```python\nprint(1)\n```\n\n"
        "1. 第一步\n2. 第二步\n\n"
        "$$\nE = mc^2\n$$\n\n"
        "## 参考文献\n\n"
        "[1] 张三. 论文排版[J]. 2026.\n",
        encoding="utf-8",
    )

    result = import_document(md, projects_dir=tmp_path / "projects")
    document = result.document

    assert document.title == "基于深度学习的论文自动排版方法研究"
    assert document.format == "markdown"
    assert result.summary.block_count == len(document.blocks)
    assert len({block.id for block in document.blocks}) == len(document.blocks)
    assert any(block.kind == "heading" for block in document.blocks)
    assert any(block.kind == "abstract" for block in document.blocks)
    assert any(block.kind == "table" for block in document.blocks)
    assert any(block.kind == "equation" for block in document.blocks)
    assert document.figures[0].label == "图1"
    assert document.figures[0].caption == "研究流程图"
    assert document.figures[0].status == "ready"
    assert document.tables[0].rows[0] == ["方法", "准确率/%"]
    assert document.tables[0].rows[1] == ["基线", "90.1"]
    assert (Path(result.project_dir) / document.figures[0].path).is_file()
    assert (Path(result.project_dir) / "content" / "manuscript.json").is_file()
    assert (Path(result.project_dir) / "source" / "paper.md").is_file()
    assert not document.warnings


def test_markdown_remote_and_missing_images_are_warned(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    md = source / "images.md"
    md.write_text(
        "# 测试\n\n"
        "![图1 远程](https://example.com/fig1.png)\n\n"
        "![图2 缺失](missing.png)\n\n"
        "![图3 越界](../outside.png)\n",
        encoding="utf-8",
    )

    result = import_document(md, projects_dir=tmp_path / "projects")
    figures = {figure.label: figure for figure in result.document.figures}

    assert figures["图1"].status == "remote"
    assert figures["图2"].status == "missing"
    assert figures["图3"].status == "missing"
    codes = {warning.code for warning in result.document.warnings}
    assert "image_issue" in codes


def test_markdown_table_without_caption_is_flagged(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    md = source / "table.md"
    md.write_text(
        "# 测试\n\n| A | B |\n|---|---|\n| 1 | 2 |\n",
        encoding="utf-8",
    )

    result = import_document(md, projects_dir=tmp_path / "projects")
    assert result.document.tables[0].label == "表1"
    assert result.document.tables[0].rows == [["A", "B"], ["1", "2"]]
    assert any(warning.code == "table_missing_caption" for warning in result.document.warnings)


def test_txt_gb18030_and_tsv_table(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    txt = source / "paper.txt"
    txt.write_text(
        "基于深度学习的论文自动排版方法研究\n\n"
        "张三，李四\n\n"
        "摘要：本文研究自动排版。\n\n"
        "关键词：自动排版；深度学习\n\n"
        "1 引言\n\n"
        "本文研究流程如图1所示。\n\n"
        "图1 研究流程图\n\n"
        "表1 性能比较\n\n"
        "方法\t准确率\n基线\t90.1\n本文\t93.5\n\n"
        "2 方法\n\n"
        "2.1 数据\n\n"
        "实验数据来自公开数据集。\n\n"
        "参考文献\n\n"
        "[1] 张三. 论文排版[J]. 2026.\n",
        encoding="gb18030",
    )

    result = import_document(txt, projects_dir=tmp_path / "projects")
    document = result.document

    assert document.format == "txt"
    assert document.encoding == "gb18030"
    assert document.title == "基于深度学习的论文自动排版方法研究"
    assert document.figures[0].status == "missing"
    assert document.tables[0].rows[0] == ["方法", "准确率"]
    assert document.tables[0].rows[2] == ["本文", "93.5"]
    assert any(warning.code == "missing_figure" for warning in document.warnings)


def test_rejects_unsupported_and_empty_files(tmp_path: Path) -> None:
    docx = tmp_path / "paper.docx"
    docx.write_bytes(b"not a docx")
    with pytest.raises(IngestError, match="仅支持"):
        import_document(docx, projects_dir=tmp_path / "projects")

    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    with pytest.raises(IngestError, match="为空"):
        import_document(empty, projects_dir=tmp_path / "projects")