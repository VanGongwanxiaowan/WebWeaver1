#!/usr/bin/env python3
"""完整工作流测试脚本。

直接使用CLI运行一个简单的研究查询，然后验证：
1. 大纲评估文件路径是否正确
2. 引用与EvidenceBank的绑定
3. 写作阶段的上下文修剪
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from dotenv import load_dotenv

# 加载.env文件
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

from webweaver.config import load_settings
from webweaver.orchestrator.runner import run_research_stream
from webweaver.utils.citations import extract_citation_ids


def main():
    """运行完整测试。"""
    print("=" * 70)
    print("WebWeaver 完整工作流测试")
    print("=" * 70)

    # 测试1: 验证大纲评估文件路径
    print("\n[测试1] 验证大纲评估文件路径...")
    repo_root = Path(__file__).parent
    prompt_path = repo_root / "docs" / "paper" / "PromptOutlineJudgement.md"
    criteria_path = repo_root / "docs" / "paper" / "judgementcriteria.md"

    if not prompt_path.exists():
        print(f"❌ 大纲评估模板不存在: {prompt_path}")
        return
    if not criteria_path.exists():
        print(f"❌ 评估准则文件不存在: {criteria_path}")
        return

    print(f"✓ 大纲评估模板: {prompt_path}")
    print(f"✓ 评估准则文件: {criteria_path}")

    # 测试2: 运行完整工作流
    print("\n[测试2] 运行完整工作流（这可能需要几分钟）...")
    print("-" * 70)

    settings = load_settings()
    query = "What are the key features of Python 3.12?"

    print(f"查询: {query}")
    print(f"使用模型: {settings.openai_model}")
    print(f"搜索提供商: {settings.search_provider}")
    print()

    # 收集所有事件
    events = []
    try:
        for event in run_research_stream(query=query, settings=settings):
            events.append(event)
            # 实时输出关键事件
            if event.content_type.value == "planner_step":
                step = event.data.get("step", "?")
                max_steps = event.data.get("max_steps", "?")
                print(f"  Planner步骤: {step}/{max_steps}")
            elif event.content_type.value == "planner_terminate":
                print(f"  Planner终止: {event.data}")
            elif event.content_type.value == "outline_updated":
                version = event.data.get("version", "?")
                print(f"  大纲更新: v{version}")
            elif event.content_type.value == "writer_section_start":
                title = event.data.get("title", "?")
                print(f"  开始写作章节: {title}")
            elif event.content_type.value == "report_done":
                print(f"  报告完成!")
    except Exception as e:
        print(f"\n❌ 工作流执行失败: {e}")
        import traceback
        traceback.print_exc()
        return

    # 找到run目录
    report_done_events = [e for e in events if e.content_type.value == "report_done"]
    if not report_done_events:
        print("\n❌ 未找到report_done事件")
        return

    run_root = Path(report_done_events[0].data["run_root"])
    outline_path = run_root / "outline.md"
    report_path = run_root / "report.md"
    evidence_bank_path = run_root / "evidence_bank"
    judgement_path = run_root / "outline_judgement.json"

    print("\n" + "=" * 70)
    print("[测试3] 验证输出文件...")
    print("-" * 70)

    # 验证文件存在
    checks = {
        "大纲文件": outline_path,
        "报告文件": report_path,
        "证据库目录": evidence_bank_path,
    }
    for name, path in checks.items():
        if path.exists():
            print(f"✓ {name}: {path}")
        else:
            print(f"❌ {name}不存在: {path}")

    # 测试4: 验证引用绑定
    print("\n" + "=" * 70)
    print("[测试4] 验证引用与EvidenceBank的绑定...")
    print("-" * 70)

    if outline_path.exists():
        outline_text = outline_path.read_text(encoding="utf-8")
        citation_ids_in_outline = extract_citation_ids(outline_text)
        print(f"大纲中的引用ID ({len(citation_ids_in_outline)}个): {citation_ids_in_outline[:10]}...")

        # 加载EvidenceBank
        from webweaver.memory.evidence_bank import EvidenceBank

        evidence_bank = EvidenceBank(evidence_bank_path)
        all_evidences = evidence_bank.list_all()
        evidence_ids_in_bank = {ev.evidence_id for ev in all_evidences}
        print(f"EvidenceBank中的ID ({len(evidence_ids_in_bank)}个): {sorted(list(evidence_ids_in_bank))[:10]}...")

        # 验证引用ID是否在EvidenceBank中
        if citation_ids_in_outline:
            missing_ids = [cid for cid in citation_ids_in_outline if cid not in evidence_ids_in_bank]
            if missing_ids:
                print(f"⚠️  警告: 大纲中引用了不存在的ID ({len(missing_ids)}个): {missing_ids[:5]}...")
            else:
                print(f"✓ 所有大纲引用ID都在EvidenceBank中存在")

    # 测试5: 验证大纲评估结果
    print("\n" + "=" * 70)
    print("[测试5] 验证大纲评估结果...")
    print("-" * 70)

    if judgement_path.exists():
        judgement_data = json.loads(judgement_path.read_text(encoding="utf-8"))
        results = judgement_data.get("results", {})
        print(f"✓ 大纲评估结果已生成 ({len(results)}个评估维度)")
        for criterion, result in results.items():
            rating = result.get("rating", "?")
            print(f"  - {criterion}: {rating}/10")
    else:
        print(f"⚠️  警告: 大纲评估结果文件不存在: {judgement_path}")

    # 测试6: 验证报告中的引用
    print("\n" + "=" * 70)
    print("[测试6] 验证报告中的引用格式...")
    print("-" * 70)

    if report_path.exists():
        report_text = report_path.read_text(encoding="utf-8")
        # 查找类似 [^ev_0001] 的引用
        footnote_refs = re.findall(r"\[\^([^\]]+)\]", report_text)
        unique_refs = set(footnote_refs)
        print(f"报告中的脚注引用 ({len(unique_refs)}个唯一): {sorted(list(unique_refs))[:10]}...")

        if unique_refs:
            # 验证脚注引用是否在EvidenceBank中
            if outline_path.exists():
                from webweaver.memory.evidence_bank import EvidenceBank

                evidence_bank = EvidenceBank(evidence_bank_path)
                all_evidences = evidence_bank.list_all()
                evidence_ids_in_bank = {ev.evidence_id for ev in all_evidences}
                valid_refs = [ref for ref in unique_refs if ref in evidence_ids_in_bank]
                print(f"✓ 报告中的 {len(valid_refs)}/{len(unique_refs)} 个引用是有效的")

    # 测试7: 验证上下文修剪
    print("\n" + "=" * 70)
    print("[测试7] 验证写作阶段的上下文修剪...")
    print("-" * 70)

    writer_retrieve_events = [
        e for e in events if e.content_type.value == "writer_retrieve_results"
    ]
    print(f"Writer检索事件数: {len(writer_retrieve_events)}")

    if len(writer_retrieve_events) >= 2:
        # 检查不同检索事件中的evidence_id
        all_retrieved_ids = []
        for evt in writer_retrieve_events:
            ids = evt.data.get("evidence_ids", [])
            all_retrieved_ids.extend(ids)

        unique_retrieved = set(all_retrieved_ids)
        print(f"总共检索到的唯一evidence数: {len(unique_retrieved)}")
        print(f"检索事件中evidence_id示例: {list(unique_retrieved)[:5]}...")

        # 检查是否有空检索（可能触发了占位符）
        empty_retrieves = [
            e for e in writer_retrieve_events if e.data.get("count", 0) == 0
        ]
        if empty_retrieves:
            print(f"✓ 检测到 {len(empty_retrieves)} 次空检索（可能触发了占位符）")
        else:
            print("ℹ️  未检测到空检索事件（可能所有检索都有结果）")

    print("\n" + "=" * 70)
    print("✓ 所有测试完成！")
    print("=" * 70)
    print(f"\n输出目录: {run_root}")
    print(f"  - 大纲: {outline_path}")
    print(f"  - 报告: {report_path}")
    print(f"  - 评估: {judgement_path if judgement_path.exists() else 'N/A'}")


if __name__ == "__main__":
    main()

