from __future__ import annotations

import json

from paperflow.core.document import Document

ROLE_LIST = (
    "title, subtitle, author, affiliation, abstract, keywords, heading, "
    "paragraph, list, code, figure, figure_caption, table, table_caption, "
    "equation, reference, acknowledgement, appendix, unknown"
)

SYSTEM_PROMPT = f"""你是学术论文结构分析器。你只负责给内容块分类和提取元数据，不润色、不改写、不补写正文。

只输出一个 JSON 对象，不要输出 Markdown 代码块、解释或前后缀。

角色只能是：
{ROLE_LIST}

必须遵守：
1. blocks 必须覆盖输入中的每一个 block_id，且每个 block_id 只出现一次；不得新增、遗漏或改写 block_id。
2. heading 必须有 heading_level（1–4）；其他角色 heading_level 必须为 null。
3. 不返回正文 text，不返回图片二进制，不编造作者、单位、摘要或关键词。
4. title 只给论文题名；作者块给 author；单位块给 affiliation；摘要给 abstract；关键词给 keywords。
5. “引言”“方法”“实验”“结论”“参考文献”“致谢”“附录”等章节标题给 heading。
6. 图题给 figure_caption，表题给 table_caption；正文里的“如图1所示”仍是 paragraph。
7. 参考文献条目给 reference；算法题注给 figure_caption 或 table_caption 中更合适的一种。
8. confidence 为 0–1；拿不准时降低 confidence，并在 note 里写一句中文原因。
9. metadata.authors / keywords 是字符串数组；abstract 不含“摘要：”前缀。

返回 JSON 结构：
{{
  "metadata": {{
    "title": "论文题名",
    "authors": ["作者1", "作者2"],
    "affiliations": ["单位1"],
    "abstract": "摘要正文",
    "keywords": ["关键词1", "关键词2"],
    "language": "zh"
  }},
  "blocks": [
    {{
      "block_id": "B0001",
      "role": "title",
      "heading_level": null,
      "confidence": 0.98,
      "note": ""
    }}
  ]
}}"""


def build_user_prompt(document: Document) -> str:
    blocks = []
    for block in document.blocks:
        text = block.text.strip()
        if len(text) > 2000:
            text = text[:1997] + "..."
        blocks.append(
            {
                "block_id": block.id,
                "kind_hint": block.kind,
                "level_hint": block.heading_level,
                "text": text,
            }
        )
    payload = {
        "document": {
            "title": document.title,
            "format": document.format,
            "source": document.source_name,
            "block_count": len(document.blocks),
        },
        "blocks": blocks,
    }
    return (
        "请为下面 JSON 中的每个 block 生成结构标注。"
        "返回的 blocks 必须与输入 block_id 一一对应；不要返回正文。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )