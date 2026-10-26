from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Template

from paperflow.core.document import Document, Figure, ImportResult, Table
from paperflow.core.fixes import RenderOverrides
from paperflow.core.layout import LayoutSettings
from paperflow.core.metadata import M4State
from paperflow.core.references import ReferenceState, generate_bib
from paperflow.core.structure import StructureResult

TEMPLATE = r"""\documentclass[UTF8,a4paper,zihao=5{% if columns == 2 %},twocolumn{% endif %}]{ctexart}
\usepackage[margin={{ margin }}mm]{geometry}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{amsmath,amssymb}
\usepackage{hyperref}
\usepackage{caption}
\captionsetup{labelsep=space,font=small}
\usepackage[backend=biber,style=gb7714-2015]{biblatex}
\addbibresource{refs.bib}
{% raw %}\graphicspath{{../assets/figures/}}{% endraw %}
\setlength{\parindent}{2em}
\setlength{\parskip}{0.35em}
\linespread{ {{ line_spacing }} }
\hypersetup{colorlinks=false}
\pagestyle{plain}
\begin{document}
\fontsize{ {{ body_size }}pt}{ {{ (body_size * line_spacing)|round(1) }}pt}\selectfont

\begin{center}
{\fontsize{ {{ title_size }}pt}{ {{ title_size }}pt}\selectfont\heiti {{ title }}\par}
{% if authors %}
\vspace{4pt}
{\fontsize{12pt}{18pt}\selectfont\kaishu {{ authors }}\par}
{% endif %}
{% if affiliations %}
{\zihao{6} {{ affiliations }}\par}
{% endif %}
{% if corresponding %}
{\zihao{6} *通信作者：{{ corresponding }}\par}
{% endif %}
\end{center}

{% if abstract %}
\noindent{\heiti 摘要：}{{ abstract }}\par
{% endif %}
{% if keywords %}
\noindent{\heiti 关键词：}{{ keywords }}\par
{% endif %}
{% if fund %}
\noindent{\zihao{6} 基金项目：{{ fund }}\par
{% endif %}
{% if bios %}
\noindent{\zihao{6} 作者简介：{{ bios }}\par
{% endif %}

{{ body }}

{% if has_references %}
\nocite{*}
\printbibliography[title={参考文献}]
{% endif %}
\end{document}
"""


@dataclass(slots=True)
class RenderResult:
    tex_path: Path
    bib_path: Path
    warnings: list[str]
    tex: str


def render_project(
    project_dir: Path,
    imported: ImportResult,
    structure: StructureResult,
    m4: M4State,
    references: ReferenceState,
    layout: LayoutSettings,
    overrides: RenderOverrides | None = None,
) -> RenderResult:
    output = project_dir / "output"
    output.mkdir(parents=True, exist_ok=True)
    document = structure.document
    metadata = m4.metadata
    warnings: list[str] = []

    title = metadata.title.value.strip() or structure.metadata.title or document.title
    authors, corresponding, affiliations = _author_lines(metadata)
    abstract = metadata.abstract.value.strip()
    keywords = "；".join(metadata.keywords)
    fund = _fund_text(metadata)
    bios = "；".join(
        bio.text.strip()
        for bio in metadata.author_bios
        if bio.text.strip()
    )
    consumed = set(metadata.consumed_block_ids)
    body = _render_body(
        document,
        structure,
        m4,
        consumed,
        references,
        layout,
        overrides or RenderOverrides(),
        warnings,
    )

    mapping = {str(index): entry.citation_key for index, entry in enumerate(references.entries, start=1)}
    body = _apply_citations(body, mapping)

    tex = Template(TEMPLATE).render(
        columns=layout.columns,
        margin=layout.margin_mm,
        line_spacing=layout.line_spacing,
        body_size=layout.body_size_pt,
        title_size=layout.title_size_pt,
        title=escape_latex(title),
        authors=authors,
        affiliations=affiliations,
        corresponding=escape_latex(corresponding),
        abstract=escape_latex(abstract),
        keywords=escape_latex(keywords),
        fund=escape_latex(fund),
        bios=escape_latex(bios),
        body=body,
        has_references=bool(references.entries),
    )
    tex_path = output / "main.tex"
    tex_path.write_text(tex, encoding="utf-8")
    bib_path = output / "refs.bib"
    bib_path.write_text(generate_bib(references.entries), encoding="utf-8")
    return RenderResult(tex_path=tex_path, bib_path=bib_path, warnings=warnings, tex=tex)


def _author_lines(metadata) -> tuple[str, str, str]:
    if not metadata.authors:
        return "", "", ""
    author_parts = []
    corresponding = []
    for author in metadata.authors:
        name = escape_latex(author.name)
        indices = [str(index) for index in author.affiliation_indices]
        if indices:
            name += r"\textsuperscript{" + ",".join(indices) + "}"
        author_parts.append(name)
        if author.corresponding and author.email:
            corresponding.append(f"{author.name}（{author.email}）")
    affiliations = "；".join(
        f"{index + 1} {escape_latex(item.name)}"
        for index, item in enumerate(metadata.affiliations)
    )
    return "，".join(author_parts), "；".join(corresponding), affiliations


def _fund_text(metadata) -> str:
    if not metadata.fund_enabled or not metadata.funds:
        return ""
    parts = []
    for fund in metadata.funds:
        text = fund.name.strip()
        if fund.number.strip():
            text += f"（{fund.number.strip()}）"
        if fund.title.strip():
            text += f"：{fund.title.strip()}"
        parts.append(text)
    return "；".join(part for part in parts if part)


def _render_body(
    document: Document,
    structure: StructureResult,
    m4: M4State,
    consumed: set[str],
    references: ReferenceState,
    layout: LayoutSettings,
    overrides: RenderOverrides,
    warnings: list[str],
) -> str:
    figures = {figure.id: figure for figure in m4.figures}
    tables = {table.id: table for table in m4.tables}
    heading_levels = [
        block.heading_level or 1
        for block in document.blocks
        if block.kind == "heading" and block.id not in consumed
    ]
    min_heading = min(heading_levels) if heading_levels else 1
    snippets: list[str] = []

    for block in document.blocks:
        if block.id in consumed:
            continue
        kind = block.kind
        if kind in {"title", "subtitle", "author", "affiliation", "abstract", "keywords"}:
            continue
        if kind == "heading":
            if block.id in overrides.page_break_before:
                snippets.append(r"\clearpage")
            text = _clean_heading(block.text.strip())
            if text in {"参考文献", "References"}:
                continue
            if text in {"引言", "绪论"}:
                snippets.append(r"\section*{" + escape_latex(text) + "}")
                continue
            depth = max(1, (block.heading_level or min_heading) - min_heading + 1)
            command = {1: "section", 2: "subsection", 3: "subsubsection"}.get(depth, "paragraph")
            snippets.append(
                "\\" + command + "{" + escape_latex(text) + "}"
            )
        elif kind == "paragraph":
            if block.text.strip():
                snippets.append(escape_text(block.text.strip()) + "\n")
        elif kind == "list":
            snippets.append(_render_list(block.text))
        elif kind == "code":
            snippets.append("\\begin{verbatim}\n" + block.text + "\n\\end{verbatim}\n")
        elif kind == "equation":
            formula = block.text.strip()
            if _safe_formula(formula):
                snippets.append("\\[\n" + formula + "\n\\]\n")
            else:
                warnings.append(f"{block.id}：公式包含不安全命令，已按文本输出")
                snippets.append(escape_latex(formula) + "\n")
        elif kind == "figure":
            figure = figures.get(block.asset_id or "")
            if figure is not None:
                snippets.append(_render_figure(figure, layout, overrides, warnings))
        elif kind == "table":
            table = tables.get(block.asset_id or "")
            if table is not None:
                snippets.append(_render_table(table, layout, overrides, warnings))
        elif kind in {"figure_caption", "table_caption", "reference"}:
            continue
        else:
            if block.text.strip():
                snippets.append(escape_text(block.text.strip()) + "\n")

    return "\n".join(snippets)


def _clean_heading(text: str) -> str:
    text = re.sub(
        r"^\s*(?:\d+(?:\.\d+)*[.、]?\s*|第[一二三四五六七八九十百千]+[章节篇]\s*)",
        "",
        text,
    )
    return text.strip()


def _render_list(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    ordered = bool(re.match(r"^\d+[.、]", lines[0]))
    env = "enumerate" if ordered else "itemize"
    items = []
    for line in lines:
        line = re.sub(r"^(?:[•\-–]|\d+[.、])\s*", "", line)
        items.append(r"\item " + escape_text(line))
    return "\\begin{" + env + "}\n" + "\n".join(items) + "\n\\end{" + env + "}\n"


def _render_figure(
    figure: Figure,
    layout: LayoutSettings,
    overrides: RenderOverrides,
    warnings: list[str],
) -> str:
    caption = escape_latex(figure.caption or figure.label)
    label = "fig:" + figure.id
    span = overrides.figure_span.get(figure.id, figure.span_columns)
    width = overrides.figure_width.get(figure.id, figure.width_ratio)
    star = "*" if span else ""
    if not figure.path:
        warnings.append(f"{figure.label or figure.id}：图片缺失，已输出占位框")
        content = r"\fbox{\parbox{0.8\linewidth}{\centering 图片待上传： " + caption + "}}"
    else:
        name = Path(figure.path).name
        content = "\\includegraphics[width=" + f"{width:.2f}" + r"\linewidth]{" + name + "}"
    return (
        "\\begin{figure" + star + "}[htbp]\n\\centering\n"
        + content
        + "\n\\caption{" + caption + "}\n\\label{" + label + "}\n\\end{figure" + star + "}\n"
    )


def _render_table(
    table: Table,
    layout: LayoutSettings,
    overrides: RenderOverrides,
    warnings: list[str],
) -> str:
    caption = escape_latex(table.caption or table.label)
    label = "tab:" + table.id
    span = overrides.table_span.get(table.id, table.span_columns)
    rows = table.rows
    if not rows:
        warnings.append(f"{table.label or table.id}：表格没有数据，已输出占位表")
        rows = [["（表格待补充）"]]
    cols = max(len(row) for row in rows)
    colspec = "l" * max(1, cols)
    lines = ["\\begin{table" + ("*" if span else "") + "}[htbp]", "\\centering", "\\caption{" + caption + "}", "\\label{" + label + "}"]
    lines.append("\\begin{tabular}{" + colspec + "}")
    lines.append("\\toprule")
    header_rows = max(1, min(table.header_rows, len(rows)))
    for index, row in enumerate(rows):
        cells = [escape_latex(cell) for cell in row] + [""] * (cols - len(row))
        lines.append(" & ".join(cells) + r" \\")
        if index + 1 == header_rows:
            lines.append("\\midrule")
    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    lines.append("\\end{table" + ("*" if span else "") + "}")
    return "\n".join(lines) + "\n"


def _safe_formula(formula: str) -> bool:
    forbidden = ("\\input", "\\include", "\\write18", "\\catcode", "\\usepackage", "\\documentclass", "\\end{document}")
    return not any(item in formula for item in forbidden)


def _apply_citations(body: str, mapping: dict[str, str]) -> str:
    for number, key in mapping.items():
        body = body.replace(f"[{number}]", r"\cite{" + key + "}")
    return body


def escape_text(text: str) -> str:
    parts = re.split(r"(\$[^$]+\$)", text)
    result = []
    for part in parts:
        if part.startswith("$") and part.endswith("$") and len(part) > 2:
            formula = part[1:-1]
            result.append("$" + formula + "$" if _safe_formula(formula) else escape_latex(part))
        else:
            result.append(escape_latex(part))
    return "".join(result)


def escape_latex(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in str(text))