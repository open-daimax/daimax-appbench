#!/usr/bin/env python3
"""
analyze_execution.py - Analyze app generation execution for 429 errors and sub-agent count

用法:
    python3 scripts/analyze_execution.py /path/to/workspace

模块接口:
    from scripts.analyze_execution import analyze_workspace
    result = analyze_workspace("/path/to/workspace", dataset_path="/path/to/dataset")
"""

import json
import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


# 429 错误检测：正则匹配独立的 "429"（前后不能是数字或十六进制字符）
PATTERN_429 = re.compile(r'(?<![0-9a-f])429(?![0-9a-f])', re.IGNORECASE)
# 文本关键词（足够特异，不需要词边界）
ERROR_429_TEXT_KEYWORDS = ["rate limit", "too many requests", "ratelimiterror"]


def _message_has_429(content: str) -> bool:
    """判断一条消息内容是否包含 429 错误相关关键词"""
    if PATTERN_429.search(content):
        return True
    content_lower = content.lower()
    for kw in ERROR_429_TEXT_KEYWORDS:
        if kw in content_lower:
            return True
    return False


def _find_all_messages_json(sample_dir: str) -> list:
    """
    在样本目录中找到所有 messages.json 文件。
    路径模式: {sample_dir}/generated_projects/{platform}/{harness|.generator}/agent_memory/{timestamp}/messages.json
    每个 timestamp 目录代表一个子Agent会话，需全部分析。
    """
    gp_dir = os.path.join(sample_dir, "generated_projects")
    if not os.path.isdir(gp_dir):
        return []

    result = []

    for platform in os.listdir(gp_dir):
        # 兜底兼容：优先 harness/agent_memory，回退隐藏目录约定
        am_dir = os.path.join(gp_dir, platform, "harness", "agent_memory")
        if not os.path.isdir(am_dir):
            # 尝试平台目录下的隐藏子目录（旧目录约定）
            plat_dir = os.path.join(gp_dir, platform)
            found = False
            if os.path.isdir(plat_dir):
                for hidden in os.listdir(plat_dir):
                    if hidden.startswith("."):
                        candidate = os.path.join(plat_dir, hidden, "agent_memory")
                        if os.path.isdir(candidate):
                            am_dir = candidate
                            found = True
                            break
            if not found:
                continue
        for ts_dir in os.listdir(am_dir):
            ts_path = os.path.join(am_dir, ts_dir)
            if not os.path.isdir(ts_path):
                continue
            msg_file = os.path.join(ts_path, "messages.json")
            if os.path.isfile(msg_file):
                result.append(msg_file)

    return result


def _load_messages(messages_path: str) -> list:
    """加载 messages.json 文件，返回消息列表"""
    try:
        with open(messages_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, IOError, OSError):
        return []


def _count_429_errors(messages: list) -> int:
    """
    统计 429 错误次数。
    遍历每条 assistant/tool role 的 message，如果内容中包含任何 429 关键词，算一次。
    """
    count = 0
    for msg in messages:
        role = msg.get("role", "")
        if role not in ("assistant", "tool"):
            continue
        # 只检查 content 字段，避免 tool_call_id 等元数据中的随机hex干扰
        raw_content = msg.get("content", "") or ""
        if isinstance(raw_content, list):
            # content 可能是 list of parts（多模态消息）
            content = " ".join(str(part.get("text", "") if isinstance(part, dict) else part) for part in raw_content)
        else:
            content = str(raw_content)
        if _message_has_429(content):
            count += 1
    return count


def _is_code_gen_session(messages: list) -> bool:
    """
    判断单个 messages.json（即一个 Agent 会话）是否为生码会话。
    两种模式：
    1. 多模块拆分模式：user message 包含 <module_context> 标签
    2. 单Agent模式：system message 包含主生码角色标识
    """
    if not messages:
        return False

    # 方式1：user message 包含 <module_context>（多模块拆分模式）
    for msg in messages:
        if msg.get('role') == 'user':
            content = str(msg.get('content', '') or '')
            if '<module_context>' in content:
                return True

    # 方式2：system message 是主生码 Agent（单Agent模式）
    if messages[0].get('role') == 'system':
        sys_content = str(messages[0].get('content', '') or '')
        if '精通全栈 App 开发' in sys_content or '交付一个 App给用户' in sys_content:
            return True

    return False


def _find_review_report(sample_dir: str) -> str | None:
    """
    定位样本的 review_master report.json 文件。
    路径模式: {sample_dir}/generated_projects/{platform}/harness/trace/review_master/report.json
    返回第一个找到的 report.json 路径，或 None。
    """
    gp_dir = os.path.join(sample_dir, "generated_projects")
    if not os.path.isdir(gp_dir):
        return None

    for platform in os.listdir(gp_dir):
        report_path = os.path.join(
            gp_dir, platform, "harness", "trace", "review_master", "report.json"
        )
        if os.path.isfile(report_path):
            return report_path

    return None


def _parse_review_report(report_path: str) -> dict:
    """
    解析 review_master/report.json，提取 review agent 计数、429 错误计数和 issues 详情。

    Returns:
        {
            "review_count": int,
            "error_429_count": int,
            "issues_found": int,
            "issues_fixed": int,
            "issues_remaining": int,
            "issues": [{"agent": str, "type": str, "file": str, "description": str, "fixed": bool}, ...]
        }
    """
    empty = {
        "review_count": 0, "error_429_count": 0,
        "issues_found": 0, "issues_fixed": 0, "issues_remaining": 0,
        "issues": [],
    }
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError, OSError):
        return dict(empty)

    agents = data.get("agents", [])
    if not isinstance(agents, list):
        return dict(empty)

    review_count = len(agents)
    error_429_count = 0
    issues_found = 0
    issues_fixed = 0
    issues_remaining = 0
    issues = []

    for agent in agents:
        if not isinstance(agent, dict):
            continue
        error_text = agent.get("error", "") or ""
        if _message_has_429(str(error_text)):
            error_429_count += 1

        agent_name = agent.get("agent", "") or ""
        issues_found += int(agent.get("issues_found", 0) or 0)
        issues_fixed += int(agent.get("issues_fixed", 0) or 0)
        issues_remaining += int(agent.get("issues_remaining", 0) or 0)

        agent_issues = agent.get("issues", [])
        if not isinstance(agent_issues, list):
            continue
        for issue in agent_issues:
            if not isinstance(issue, dict):
                continue
            issues.append({
                "agent": agent_name,
                "type": issue.get("type", "") or "",
                "file": issue.get("file", "") or "",
                "description": issue.get("description", "") or "",
                "fixed": bool(issue.get("fixed", False)),
            })

    return {
        "review_count": review_count,
        "error_429_count": error_429_count,
        "issues_found": issues_found,
        "issues_fixed": issues_fixed,
        "issues_remaining": issues_remaining,
        "issues": issues,
    }


def _build_title_map(dataset_path: str) -> dict:
    """
    从 dataset 目录递归搜索 sample.yaml 文件，构建 sample_id → title 映射。
    """
    title_map = {}
    if not dataset_path or not os.path.isdir(dataset_path):
        return title_map

    if yaml is None:
        # 没有 PyYAML，尝试简单解析 title 字段
        for root, dirs, files in os.walk(dataset_path):
            if "sample.yaml" in files:
                filepath = os.path.join(root, "sample.yaml")
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith("title:"):
                                title = line[len("title:"):].strip().strip('"').strip("'")
                                # sample_id 取父目录名
                                sample_id = os.path.basename(root)
                                title_map[sample_id] = title
                                break
                except (IOError, OSError):
                    pass
        return title_map

    for root, dirs, files in os.walk(dataset_path):
        if "sample.yaml" in files:
            filepath = os.path.join(root, "sample.yaml")
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict):
                    sample_id = data.get("sample_id") or os.path.basename(root)
                    title = data.get("title", sample_id)
                    title_map[sample_id] = title
            except (yaml.YAMLError, IOError, OSError):
                pass

    return title_map


def analyze_workspace(workspace_path: str, dataset_path: str = None) -> dict:
    """
    分析工作区中的 messages.json 文件，统计 429 错误和子Agent个数。

    Args:
        workspace_path: 工作区根目录路径
        dataset_path: dataset 目录路径，用于获取样本中文名。默认为 bench_eval_app/dataset/

    Returns:
        分析结果字典
    """
    workspace_path = os.path.abspath(workspace_path)
    if not os.path.isdir(workspace_path):
        raise ValueError(f"工作区路径不存在: {workspace_path}")

    # 默认 dataset 路径
    if dataset_path is None:
        # 尝试常见位置
        candidates = [
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dataset"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "dataset"),
        ]
        for c in candidates:
            if os.path.isdir(c):
                dataset_path = c
                break
        if dataset_path is None:
            dataset_path = ""

    # 构建 title 映射
    title_map = _build_title_map(dataset_path)

    # 遍历工作区中的样本目录
    error_429_details = []
    sub_agent_details = []
    total_429 = 0
    affected_samples = 0
    total_samples = 0
    total_code_gen = 0
    total_review = 0
    review_issues_details = []
    review_issues_found = 0
    review_issues_fixed = 0
    review_issues_remaining = 0

    for entry in sorted(os.listdir(workspace_path)):
        sample_dir = os.path.join(workspace_path, entry)
        if not os.path.isdir(sample_dir):
            continue
        # 跳过隐藏目录和非样本目录
        if entry.startswith("."):
            continue

        # 检查是否为样本目录（含 generated_projects）
        gp_dir = os.path.join(sample_dir, "generated_projects")
        if not os.path.isdir(gp_dir):
            continue

        total_samples += 1
        sample_id = entry
        title = title_map.get(sample_id, sample_id)

        # 找到所有 messages.json（每个timestamp目录代表一个子Agent会话）
        msg_files = _find_all_messages_json(sample_dir)
        if not msg_files:
            # 没有找到 messages.json，记录零值
            error_429_details.append({"sample_id": sample_id, "title": title, "count": 0})
            sub_agent_details.append({
                "sample_id": sample_id, "title": title,
                "code_gen_count": 0, "review_count": 0
            })
            continue

        # --- 来源 A: messages.json（生码阶段 429 + 生码 Agent 计数）---
        count_429_messages = 0
        code_gen_count = 0

        for msg_file in msg_files:
            messages = _load_messages(msg_file)
            count_429_messages += _count_429_errors(messages)
            if _is_code_gen_session(messages):
                code_gen_count += 1

        # --- 来源 B: report.json（review 阶段）---
        review_count = 0
        count_429_review = 0
        report_path = _find_review_report(sample_dir)
        if report_path:
            report_info = _parse_review_report(report_path)
            review_count = report_info["review_count"]
            count_429_review = report_info["error_429_count"]
            # 汇总 review issues
            review_issues_found += report_info["issues_found"]
            review_issues_fixed += report_info["issues_fixed"]
            review_issues_remaining += report_info["issues_remaining"]
            for issue in report_info["issues"]:
                review_issues_details.append({
                    "sample_id": sample_id,
                    "title": title,
                    "agent": issue["agent"],
                    "type": issue["type"],
                    "file": issue["file"],
                    "description": issue["description"],
                    "fixed": issue["fixed"],
                })

        # 合并 429 总数
        count_429 = count_429_messages + count_429_review

        total_429 += count_429
        if count_429 > 0:
            affected_samples += 1
        error_429_details.append({"sample_id": sample_id, "title": title, "count": count_429})

        total_code_gen += code_gen_count
        total_review += review_count
        sub_agent_details.append({
            "sample_id": sample_id, "title": title,
            "code_gen_count": code_gen_count,
            "review_count": review_count
        })

    # 排序：429 按 count 降序
    error_429_details.sort(key=lambda x: x["count"], reverse=True)
    # 子Agent 按 code_gen_count + review_count 降序
    sub_agent_details.sort(
        key=lambda x: x["code_gen_count"] + x["review_count"], reverse=True
    )
    # review issues 按 sample_id 和 agent 排序
    review_issues_details.sort(key=lambda x: (x["sample_id"], x["agent"]))

    result = {
        "error_429": {
            "total_count": total_429,
            "affected_samples": affected_samples,
            "total_samples": total_samples,
            "details": error_429_details,
        },
        "sub_agents": {
            "total_code_gen": total_code_gen,
            "total_review": total_review,
            "details": sub_agent_details,
        },
        "review_issues": {
            "total_found": review_issues_found,
            "total_fixed": review_issues_fixed,
            "total_remaining": review_issues_remaining,
            "details": review_issues_details,
        },
    }

    # 写入结果到工作区
    output_path = os.path.join(os.path.abspath(workspace_path), "execution_overview.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def main():
    if len(sys.argv) < 2:
        print(f"用法: {sys.argv[0]} <workspace_path> [dataset_path]", file=sys.stderr)
        sys.exit(1)

    workspace_path = sys.argv[1]
    dataset_path = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        result = analyze_workspace(workspace_path, dataset_path)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    output_path = os.path.join(os.path.abspath(workspace_path), "execution_overview.json")
    print(f"分析完成，结果已写入: {output_path}")
    print(f"  总样本数: {result['error_429']['total_samples']}")
    print(f"  429 错误总次数: {result['error_429']['total_count']}")
    print(f"  受影响样本数: {result['error_429']['affected_samples']}")
    print(f"  生码子Agent总数: {result['sub_agents']['total_code_gen']}")
    print(f"  Review子Agent总数: {result['sub_agents']['total_review']}")


if __name__ == "__main__":
    main()
