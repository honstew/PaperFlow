from __future__ import annotations

import pytest

from paperflow.llm.ai_prompts import COMPILE_FIX_SYSTEM_PROMPT
from paperflow.llm.compile_ai import (
    CompileAIError,
    CompilePatch,
    apply_compile_patches,
)


def test_compile_fix_prompt_is_minimal_and_safe() -> None:
    assert "最小" in COMPILE_FIX_SYSTEM_PROMPT
    assert "search" in COMPILE_FIX_SYSTEM_PROMPT
    assert "\\write18" in COMPILE_FIX_SYSTEM_PROMPT
    assert "不重写论文内容" in COMPILE_FIX_SYSTEM_PROMPT


def test_apply_compile_patches_requires_unique_search() -> None:
    tex = "A\nB\nA\n"
    patch = CompilePatch(search="A", replace="C", reason="test")
    with pytest.raises(CompileAIError, match="不唯一"):
        apply_compile_patches(tex, [patch])


def test_apply_compile_patches_rejects_external_commands() -> None:
    tex = "hello\n"
    patch = CompilePatch(search="hello", replace="\\input{x}", reason="bad")
    with pytest.raises(CompileAIError, match="不允许"):
        apply_compile_patches(tex, [patch])


def test_apply_compile_patches_replaces_unique_fragment() -> None:
    tex = "\\documentclass{ctexart}\n\\begin{document}\nHello\n\\end{document}\n"
    patch = CompilePatch(
        search="Hello",
        replace="Hello, world",
        reason="修复缺失文本",
    )
    result, applied = apply_compile_patches(tex, [patch])
    assert "Hello, world" in result
    assert applied == ["修复缺失文本"]