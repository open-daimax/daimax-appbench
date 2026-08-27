"""重新聚合指定工作区的 scores_summary.json。

用法:
    python scripts/reaggregate_scores_summary.py <workspace_path>

会调用 report_aggregator.aggregate_report() 并将结果写入 report/scores_summary.json，
打印 before/after 的 mean_functionality_completeness 值。
"""
import json
import sys
from pathlib import Path

# 确保 evalapp 可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evalapp.services.report_aggregator import aggregate_report
from evalapp.workspace.report_data import write_scores_summary


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/reaggregate_scores_summary.py <workspace_path>")
        sys.exit(1)

    workspace_dir = Path(sys.argv[1]).resolve()
    if not workspace_dir.is_dir():
        print(f"错误: 工作区目录不存在: {workspace_dir}")
        sys.exit(1)

    # === 读取旧的 scores_summary.json ===
    old_summary_path = workspace_dir / "report" / "scores_summary.json"
    old_mean_fc = None
    if old_summary_path.exists():
        old_data = json.loads(old_summary_path.read_text(encoding="utf-8"))
        tls = old_data.get("top_level_summary", {})
        old_mean_fc = tls.get("mean_functionality_completeness")
        # 也检查 per_platform
        per_plat = tls.get("per_platform", {})
        for pn, pv in per_plat.items():
            if "mean_functionality_completeness" in pv:
                old_mean_fc = pv["mean_functionality_completeness"]
                break
        print(f"[BEFORE] mean_functionality_completeness = {old_mean_fc}")
    else:
        print("[BEFORE] scores_summary.json 不存在")

    # === 运行聚合 ===
    print(f"\n正在聚合工作区: {workspace_dir}")
    report_data = aggregate_report(workspace_dir)
    if report_data is None:
        print("错误: aggregate_report 返回 None，工作区中无有效样本数据")
        sys.exit(1)

    # === 构建 scores_summary 结构（与 ReportService.write_scores_summary 一致） ===
    # 收集 seen_samples
    seen_samples = {}
    for sr in report_data.get("sample_results", []):
        sid = sr["sample_id"]
        plat = sr["platform"]
        if sid not in seen_samples:
            seen_samples[sid] = {"sample_id": sid, "platforms": [], "scores_path": f"{sid}/scores.json"}
        if plat not in seen_samples[sid]["platforms"]:
            seen_samples[sid]["platforms"].append(plat)

    # 合并 excluded_samples
    all_samples = dict(seen_samples)
    excluded_samples = report_data.get("excluded_samples", [])
    for exc in excluded_samples:
        sid = exc.get("sample_id")
        if not sid or sid in all_samples:
            continue
        plat_raw = exc.get("platform", "")
        platforms = [p.strip() for p in str(plat_raw).split(",") if p.strip()]
        all_samples[sid] = {
            "sample_id": sid,
            "platforms": platforms,
            "scores_path": f"{sid}/scores.json",
            "excluded": True,
        }

    scores_summary = {
        "meta": report_data.get("meta", {}),
        "summary": report_data.get("summary", {}),
        "top_level_summary": report_data.get("top_level_summary", {}),
        "cross_platform_comparison": report_data.get("cross_platform_comparison", {}),
        "samples": list(all_samples.values()),
    }
    if excluded_samples:
        scores_summary["excluded_samples"] = excluded_samples
    scores_summary["schema_version"] = "2.0"

    # === 写入 ===
    write_scores_summary(workspace_dir, scores_summary)
    print(f"已写入: {workspace_dir / 'report' / 'scores_summary.json'}")

    # === 读取新值验证 ===
    new_data = json.loads((workspace_dir / "report" / "scores_summary.json").read_text(encoding="utf-8"))
    new_tls = new_data.get("top_level_summary", {})
    new_mean_fc = new_tls.get("mean_functionality_completeness")
    per_plat = new_tls.get("per_platform", {})
    for pn, pv in per_plat.items():
        if "mean_functionality_completeness" in pv:
            new_mean_fc = pv["mean_functionality_completeness"]
            break

    print(f"\n[AFTER] mean_functionality_completeness = {new_mean_fc}")
    print(f"\n{'='*50}")
    print(f"  BEFORE: {old_mean_fc}")
    print(f"  AFTER:  {new_mean_fc}")
    if old_mean_fc is not None and new_mean_fc is not None:
        diff = new_mean_fc - old_mean_fc
        print(f"  DIFF:   {diff:+.1f}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
