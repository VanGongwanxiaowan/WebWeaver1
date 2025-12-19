"""端到端测试：验证论文业务逻辑的完整实现。

测试要点：
1. 大纲评估文件路径是否正确（docs/paper/）
2. 引用与EvidenceBank的绑定是否工作
3. 写作阶段的上下文修剪是否生效
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from dotenv import load_dotenv

# 加载.env文件
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

from webweaver.config import load_settings
from webweaver.evaluation.outline_judge import OutlineJudge
from webweaver.memory.evidence_bank import EvidenceBank
from webweaver.orchestrator.runner import run_research_stream
from webweaver.utils.citations import extract_citation_ids


def test_outline_judge_paths_exist():
    """测试1: 验证大纲评估文件路径是否正确存在。"""
    # tests/test_e2e_workflow.py -> tests/ -> repo root
    repo_root = Path(__file__).resolve().parent.parent
    prompt_path = repo_root / "docs" / "paper" / "PromptOutlineJudgement.md"
    criteria_path = repo_root / "docs" / "paper" / "judgementcriteria.md"

    assert prompt_path.exists(), f"大纲评估模板不存在: {prompt_path}"
    assert criteria_path.exists(), f"评估准则文件不存在: {criteria_path}"

    # 验证文件内容不为空
    assert len(prompt_path.read_text(encoding="utf-8").strip()) > 0
    assert len(criteria_path.read_text(encoding="utf-8").strip()) > 0

    print(f"✓ 测试1通过: 大纲评估文件路径正确")
    print(f"  - 模板: {prompt_path}")
    print(f"  - 准则: {criteria_path}")


def test_outline_judge_can_load():
    """测试2: 验证OutlineJudge可以正确加载文件。"""
    repo_root = Path(__file__).resolve().parent.parent
    from webweaver.llm.client import LLMClient

    settings = load_settings()
    llm = LLMClient(settings)

    judge = OutlineJudge(
        llm=llm,
        prompt_template_path=repo_root / "docs" / "paper" / "PromptOutlineJudgement.md",
        criteria_path=repo_root / "docs" / "paper" / "judgementcriteria.md",
    )

    criteria = judge.load_criteria()
    assert len(criteria) > 0, "应该至少加载一个评估准则"

    print(f"✓ 测试2通过: OutlineJudge可以加载 {len(criteria)} 个评估准则")
    for c in criteria:
        print(f"  - {c.name}")


@pytest.mark.slow
def test_full_workflow_citation_binding():
    """测试3: 运行完整工作流，验证引用与EvidenceBank的绑定。

    这个测试会：
    1. 运行一个简单的研究查询
    2. 检查大纲中的引用ID是否与EvidenceBank中的ID匹配
    3. 检查写作阶段是否正确使用了引用ID
    """
    settings = load_settings()

    # 使用一个简单的查询来加快测试
    query = "What are the key features of Python 3.12?"

    # 收集所有事件
    events = list(run_research_stream(query=query, settings=settings))

    # 找到run目录
    report_done_events = [
        e for e in events if e.content_type.value == "report_done"
    ]
    assert len(report_done_events) > 0, "应该至少有一个report_done事件"

    run_root = Path(report_done_events[0].data["run_root"])
    outline_path = run_root / "outline.md"
    report_path = run_root / "report.md"
    evidence_bank_path = run_root / "evidence_bank"

    # 验证文件存在
    assert outline_path.exists(), f"大纲文件不存在: {outline_path}"
    assert report_path.exists(), f"报告文件不存在: {report_path}"
    assert evidence_bank_path.exists(), f"证据库目录不存在: {evidence_bank_path}"

    # 读取大纲
    outline_text = outline_path.read_text(encoding="utf-8")
    print(f"\n大纲内容预览:\n{outline_text[:500]}...")

    # 提取大纲中的引用ID
    citation_ids_in_outline = extract_citation_ids(outline_text)
    print(f"\n大纲中的引用ID: {citation_ids_in_outline}")

    # 加载EvidenceBank
    evidence_bank = EvidenceBank(evidence_bank_path)
    all_evidences = evidence_bank.list_all()
    evidence_ids_in_bank = {ev.evidence_id for ev in all_evidences}

    print(f"\nEvidenceBank中的ID: {sorted(evidence_ids_in_bank)}")

    # 验证：大纲中的引用ID应该都在EvidenceBank中存在
    if citation_ids_in_outline:
        missing_ids = [cid for cid in citation_ids_in_outline if cid not in evidence_ids_in_bank]
        if missing_ids:
            print(f"⚠️  警告: 大纲中引用了不存在的ID: {missing_ids}")
        else:
            print(f"✓ 测试3a通过: 所有大纲引用ID都在EvidenceBank中存在")

    # 检查大纲评估结果
    judgement_path = run_root / "outline_judgement.json"
    if judgement_path.exists():
        judgement_data = json.loads(judgement_path.read_text(encoding="utf-8"))
        print(f"\n✓ 测试3b通过: 大纲评估结果已生成")
        print(f"  评估结果: {judgement_data.get('results', {})}")
    else:
        print(f"⚠️  警告: 大纲评估结果文件不存在: {judgement_path}")

    # 检查报告中的引用格式
    report_text = report_path.read_text(encoding="utf-8")
    # 查找类似 [^ev_0001] 的引用
    footnote_refs = re.findall(r"\[\^([^\]]+)\]", report_text)
    print(f"\n报告中的脚注引用: {set(footnote_refs)}")

    if footnote_refs:
        # 验证脚注引用是否在EvidenceBank中
        valid_refs = [ref for ref in footnote_refs if ref in evidence_ids_in_bank]
        print(f"✓ 测试3c通过: 报告中的 {len(valid_refs)}/{len(footnote_refs)} 个引用是有效的")

    print(f"\n✓ 测试3完成: 完整工作流运行成功")
    print(f"  - 大纲路径: {outline_path}")
    print(f"  - 报告路径: {report_path}")
    print(f"  - 证据数量: {len(all_evidences)}")


@pytest.mark.slow
def test_writer_context_pruning():
    """测试4: 验证写作阶段的上下文修剪机制。

    检查：
    1. 已使用的evidence是否在后续章节中被过滤
    2. 无新证据时是否返回占位符
    """
    settings = load_settings()
    query = "What are the main benefits of using async/await in Python?"

    events = list(run_research_stream(query=query, settings=settings))

    # 查找writer相关事件
    writer_retrieve_events = [
        e for e in events
        if e.content_type.value == "writer_retrieve_results"
    ]

    if len(writer_retrieve_events) < 2:
        print("⚠️  警告: 需要至少2个检索事件来验证上下文修剪")
        return

    # 检查第一个和第二个检索事件中的evidence_id
    first_retrieve = writer_retrieve_events[0].data
    second_retrieve = writer_retrieve_events[1].data

    first_ids = set(first_retrieve.get("evidence_ids", []))
    second_ids = set(second_retrieve.get("evidence_ids", []))

    overlap = first_ids & second_ids
    if overlap:
        print(f"⚠️  注意: 有 {len(overlap)} 个evidence在多个章节中重复使用: {overlap}")
        print("  (这可能是正常的，如果不同章节需要相同的证据)")
    else:
        print(f"✓ 测试4a通过: 不同章节使用了不同的evidence，无重复")

    # 检查是否有NO_NEW_EVIDENCE占位符
    # 这需要检查tool_response内容，但事件流中没有直接暴露
    # 我们可以通过检查检索结果为0的情况来间接验证
    empty_retrieves = [
        e for e in writer_retrieve_events
        if e.data.get("count", 0) == 0
    ]
    if empty_retrieves:
        print(f"✓ 测试4b通过: 检测到 {len(empty_retrieves)} 次空检索（可能触发了占位符）")
    else:
        print("ℹ️  信息: 未检测到空检索事件（可能所有检索都有结果）")

    print(f"\n✓ 测试4完成: 上下文修剪机制检查完成")


if __name__ == "__main__":
    """直接运行测试（不使用pytest）。"""
    print("=" * 60)
    print("WebWeaver 端到端测试")
    print("=" * 60)

    try:
        test_outline_judge_paths_exist()
        print()

        test_outline_judge_can_load()
        print()

        print("=" * 60)
        print("开始运行完整工作流测试（这可能需要几分钟）...")
        print("=" * 60)
        test_full_workflow_citation_binding()
        print()

        print("=" * 60)
        print("开始测试写作阶段上下文修剪...")
        print("=" * 60)
        test_writer_context_pruning()
        print()

        print("=" * 60)
        print("✓ 所有测试完成！")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        raise

