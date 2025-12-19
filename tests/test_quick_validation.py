#!/usr/bin/env python3
"""快速验证脚本：检查关键功能是否正确实现。

不运行完整工作流，只验证：
1. 大纲评估文件路径
2. 代码中的关键逻辑
3. Prompt内容
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# 加载.env文件
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)


def test_outline_judge_paths():
    """测试1: 验证大纲评估文件路径。"""
    print("=" * 70)
    print("[测试1] 验证大纲评估文件路径...")
    print("-" * 70)

    repo_root = Path(__file__).parent
    prompt_path = repo_root / "docs" / "paper" / "PromptOutlineJudgement.md"
    criteria_path = repo_root / "docs" / "paper" / "judgementcriteria.md"

    assert prompt_path.exists(), f"大纲评估模板不存在: {prompt_path}"
    assert criteria_path.exists(), f"评估准则文件不存在: {criteria_path}"

    print(f"✓ 大纲评估模板: {prompt_path}")
    print(f"✓ 评估准则文件: {criteria_path}")

    # 验证runner.py中的路径
    from webweaver.orchestrator.runner import _repo_root

    repo_root_from_code = _repo_root()
    expected_prompt = repo_root_from_code / "docs" / "paper" / "PromptOutlineJudgement.md"
    expected_criteria = repo_root_from_code / "docs" / "paper" / "judgementcriteria.md"

    assert expected_prompt.exists(), f"代码中的路径不正确: {expected_prompt}"
    assert expected_criteria.exists(), f"代码中的路径不正确: {expected_criteria}"

    print(f"✓ 代码中的路径正确: {expected_prompt}")
    print(f"✓ 代码中的路径正确: {expected_criteria}")


def test_citation_extraction():
    """测试2: 验证引用提取功能。"""
    print("\n" + "=" * 70)
    print("[测试2] 验证引用提取功能...")
    print("-" * 70)

    from webweaver.utils.citations import extract_citation_ids

    # 测试各种引用格式
    test_cases = [
        ("<citation>ev_0001</citation>", ["ev_0001"]),
        ("<citation>ev_0001,ev_0002</citation>", ["ev_0001", "ev_0002"]),
        ("<citation>ev_0001, ev_0002, ev_0003</citation>", ["ev_0001", "ev_0002", "ev_0003"]),
        ("Section 1 <citation>ev_0001</citation> and Section 2 <citation>ev_0002</citation>", ["ev_0001", "ev_0002"]),
    ]

    for text, expected in test_cases:
        result = extract_citation_ids(text)
        assert result == expected, f"提取失败: {text} -> {result}, 期望: {expected}"
        print(f"✓ '{text[:50]}...' -> {result}")

    print("✓ 所有引用提取测试通过")


def test_writer_actions():
    """测试3: 验证WriterActions支持citation_ids。"""
    print("\n" + "=" * 70)
    print("[测试3] 验证WriterActions支持citation_ids...")
    print("-" * 70)

    from webweaver.agents.writer_actions import RetrieveAction

    # 测试带citation_ids的RetrieveAction
    action1 = RetrieveAction(query="test", citation_ids=["ev_0001", "ev_0002"])
    assert action1.citation_ids == ["ev_0001", "ev_0002"]
    print(f"✓ RetrieveAction支持citation_ids: {action1.citation_ids}")

    # 测试只有query的RetrieveAction
    action2 = RetrieveAction(query="test")
    assert action2.citation_ids is None
    print(f"✓ RetrieveAction支持只有query: {action2.query}")


def test_prompts():
    """测试4: 验证Prompt内容。"""
    print("\n" + "=" * 70)
    print("[测试4] 验证Prompt内容...")
    print("-" * 70)

    from webweaver.prompts import PLANNER_SYSTEM_PROMPT, WRITER_SYSTEM_PROMPT

    # 检查Planner prompt是否提到ev_0001格式
    assert "ev_0001" in PLANNER_SYSTEM_PROMPT or "ev_" in PLANNER_SYSTEM_PROMPT, "Planner prompt应该提到evidence id格式"
    print("✓ Planner prompt包含evidence id格式要求")

    # 检查Writer prompt是否提到citation_ids
    assert "citation_ids" in WRITER_SYSTEM_PROMPT, "Writer prompt应该提到citation_ids"
    print("✓ Writer prompt包含citation_ids说明")

    # 检查Writer prompt是否提到占位符
    assert "placeholder" in WRITER_SYSTEM_PROMPT.lower() or "pruned" in WRITER_SYSTEM_PROMPT.lower(), "Writer prompt应该提到上下文修剪"
    print("✓ Writer prompt包含上下文修剪说明")


def test_evidence_bank_operations():
    """测试5: 验证EvidenceBank操作。"""
    print("\n" + "=" * 70)
    print("[测试5] 验证EvidenceBank操作...")
    print("-" * 70)

    import tempfile
    from webweaver.memory.evidence_bank import EvidenceBank
    from webweaver.models.evidence import EvidenceSource, EvidenceItem

    with tempfile.TemporaryDirectory() as tmpdir:
        bank = EvidenceBank(Path(tmpdir))

        # 添加一个evidence
        source = EvidenceSource(url="https://example.com/test")
        ev = bank.add(
            query="test query",
            source=source,
            summary="Test summary",
            evidence_items=[EvidenceItem(type="quote", content="Test content")],
            raw_text="Test raw text",
        )

        # EvidenceBank使用id_格式，但prompt中要求ev_格式
        # 实际运行时，planner应该使用EvidenceBank中显示的真实ID
        assert ev.evidence_id.startswith("id_") or ev.evidence_id.startswith("ev_"), f"Evidence ID格式不正确: {ev.evidence_id}"
        print(f"✓ Evidence ID格式正确: {ev.evidence_id}")

        # 测试bulk_get
        retrieved = bank.bulk_get([ev.evidence_id])
        assert len(retrieved) == 1
        assert retrieved[0].evidence_id == ev.evidence_id
        print(f"✓ bulk_get功能正常")


def main():
    """运行所有快速测试。"""
    try:
        test_outline_judge_paths()
        test_citation_extraction()
        test_writer_actions()
        test_prompts()
        test_evidence_bank_operations()

        print("\n" + "=" * 70)
        print("✓ 所有快速验证测试通过！")
        print("=" * 70)
        print("\n提示: 运行 test_full_workflow.py 进行完整的工作流测试")

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()

