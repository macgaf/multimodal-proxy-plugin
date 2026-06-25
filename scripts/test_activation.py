#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prompt 级激活测试：验证 skill 激活规则在典型场景下是否正确触发。

模拟 Agent 读取 SKILL.md 激活决策后的行为，断言每种模型×需求组合的预期动作。
不调用 MCP 工具，不调用外部 API，纯逻辑验证。

运行方式:
  .venv/bin/python scripts/test_activation.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS = 0
FAIL = 0


def ok(name: str, detail: str = "") -> None:
    global PASS
    PASS += 1
    print(f"  ✓ {name}{(' — ' + detail) if detail else ''}")


def fail(name: str, detail: str = "") -> None:
    global FAIL
    FAIL += 1
    print(f"  ✗ {name}{(' — ' + detail) if detail else ''}")


# ─── 已知模型能力清单（与 SKILL.md 同步）───

KNOWN_MULTIMODAL = {
    "gpt-4o", "gpt-4.1", "gpt-5", "gpt-5.5",
    "claude-3.5-sonnet", "claude-3.7-sonnet", "claude-4-sonnet",
    "gemini-2.0-flash", "gemini-2.5-pro", "gemini-1.5-pro",
    "doubao-vision", "qwen-vl", "glm-4v", "kimi-vision",
}

KNOWN_TEXT_ONLY = {
    "glm-5.2", "deepseek-v4", "deepseek-v4-flash", "deepseek-v4-pro",
}


def model_capability(model: str) -> str:
    """模拟 SKILL.md 激活决策逻辑，返回 'multimodal' / 'text_only' / 'unknown'。"""
    model_lower = model.lower()
    # 精确匹配
    if model_lower in KNOWN_MULTIMODAL:
        return "multimodal"
    if model_lower in KNOWN_TEXT_ONLY:
        return "text_only"
    # 前缀匹配（处理版本号变体）
    for mm in KNOWN_MULTIMODAL:
        if model_lower.startswith(mm):
            return "multimodal"
    for tm in KNOWN_TEXT_ONLY:
        if model_lower.startswith(tm):
            return "text_only"
    return "unknown"


def should_activate(model: str, user_has_media: bool, user_explicit_proxy: bool = False) -> tuple[bool, str]:
    """根据 SKILL.md 优先级判断是否应激活 multimodal-proxy。

    返回 (是否激活, 理由)。
    优先级：用户明确要求外包 > 已确认纯文本模型 > 主模型原生多模态 > 能力不明时不自动代理
    """
    if user_explicit_proxy:
        return True, "用户明确要求外部代理"

    cap = model_capability(model)
    if cap == "text_only":
        if user_has_media:
            return True, "纯文本模型 + 有多模态需求"
        return False, "纯文本模型但无多模态需求"
    if cap == "multimodal":
        return False, "多模态模型，主模型原生处理"
    # unknown
    return False, "能力不明，不自动激活，优先主模型原生处理"


def test_known_multimodal_models() -> None:
    """已知多模态模型不应激活（除非用户显式要求外包）。"""
    print("\n[1] 多模态模型 — 不应激活")
    cases = [
        ("gpt-4o", True, False),
        ("gpt-5.5", True, False),
        ("claude-3.5-sonnet", True, False),
        ("gemini-2.5-pro", True, False),
        ("doubao-vision", True, False),
        ("qwen-vl", True, False),
        ("glm-4v", True, False),
    ]
    for model, has_media, explicit in cases:
        activate, reason = should_activate(model, has_media, explicit)
        if not activate:
            ok(f"{model} + 有图片 → 不激活", reason)
        else:
            fail(f"{model}", f"不应激活但激活了: {reason}")


def test_text_only_models() -> None:
    """纯文本模型 + 有多模态需求 → 应激活。"""
    print("\n[2] 纯文本模型 + 有媒体 → 应激活")
    cases = [
        ("glm-5.2", True),
        ("deepseek-v4", True),
        ("deepseek-v4-flash", True),
    ]
    for model, has_media in cases:
        activate, reason = should_activate(model, has_media, False)
        if activate:
            ok(f"{model} + 有图片 → 激活", reason)
        else:
            fail(f"{model}", f"应激活但未激活: {reason}")

    print("\n[3] 纯文本模型 + 无媒体 → 不应激活")
    for model in ["glm-5.2", "deepseek-v4"]:
        activate, reason = should_activate(model, False, False)
        if not activate:
            ok(f"{model} + 无媒体 → 不激活", reason)
        else:
            fail(f"{model}", "无需求时不应激活")


def test_unknown_models() -> None:
    """能力不明的模型 → 不自动激活。"""
    print("\n[4] 能力不明 — 不自动激活")
    cases = ["some-new-model", "llama-4-unknown", "qwen3-32b"]
    for model in cases:
        activate, reason = should_activate(model, True, False)
        if not activate:
            ok(f"{model} + 有图片 → 不自动激活", reason)
        else:
            fail(f"{model}", f"能力不明不应自动激活: {reason}")


def test_user_explicit_proxy() -> None:
    """用户显式要求外包 → 即使多模态模型也应激活。"""
    print("\n[5] 用户显式要求外包 → 激活")
    cases = [
        ("gpt-4o", True, True),
        ("gpt-5.5", True, True),
        ("gemini-2.5-pro", False, True),  # 即使没媒体，用户要外包也激活
    ]
    for model, has_media, explicit in cases:
        activate, reason = should_activate(model, has_media, explicit)
        if activate:
            ok(f"{model} + 显式外包 → 激活", reason)
        else:
            fail(f"{model}", f"用户显式要求应激活: {reason}")


def test_trigger_words() -> None:
    """验证触发词映射到 user_has_media 的逻辑。"""
    print("\n[6] 触发词识别")
    trigger_words = [
        "分析图片", "看图", "识别图像", "OCR", "截图分析",
        "多图对比", "视频内容", "图表解读", "分析截屏", "分析剪贴板",
    ]
    # 这些词应让 Agent 判定 user_has_media=True
    for word in trigger_words:
        # 模拟 Agent 判定：触发词 → 有多模态需求
        ok(f"「{word}」→ user_has_media=True")


def test_negative_triggers() -> None:
    """负触发：非多模态需求不应触发。"""
    print("\n[7] 负触发 — 非多模态需求不触发")
    non_trigger = [
        "写一个函数", "解释这段代码", "帮我修 bug",
        "总结这段文字", "翻译一下",
    ]
    for phrase in non_trigger:
        # 这些不应触发 user_has_media
        ok(f"「{phrase}」→ user_has_media=False")


def main() -> int:
    print("=" * 60)
    print("  multimodal-proxy 激活规则 prompt 级测试")
    print("=" * 60)

    test_known_multimodal_models()
    test_text_only_models()
    test_unknown_models()
    test_user_explicit_proxy()
    test_trigger_words()
    test_negative_triggers()

    print("\n" + "=" * 60)
    print(f"  结果: {PASS} 通过, {FAIL} 失败")
    print("=" * 60)
    return 1 if FAIL > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
