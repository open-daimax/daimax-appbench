"""Tests for test case store save/load round-trip."""

import json
import logging
import tempfile
from pathlib import Path


from evalapp.benchset.testcases.models import TestCase, TestDesignOutput
from evalapp.benchset.testcases.store import TestCaseStore


def test_save_and_load_round_trip(tmp_path, monkeypatch):
    """Save test cases then load them back, verify data integrity."""
    # Isolate project root so a real TC_LAUNCH template from the repo
    # cannot sneak into the loaded cases.
    monkeypatch.setattr(
        "evalapp.benchset.testcases.store.get_project_root", lambda: tmp_path
    )
    store = TestCaseStore(tmp_path)

    cases = [
        TestCase(
            id="tc_1",
            name="Verify clock display",
            description="Check that the clock face shows current time",
            steps=["Open app", "Look at clock face"],
            expected_result="Clock shows current time",
            priority="high",
        ),
        TestCase(
            id="tc_2",
            name="Add alarm",
            description="Add a new alarm via the + button",
            steps=["Tap + button", "Set time", "Confirm"],
            expected_result="New alarm appears in list",
        ),
    ]

    design_output = TestDesignOutput(
        prompt_id="alarm_clock",
        platform="ios",
        test_cases=cases,
        raw_output="some raw output",
    )

    # Save
    saved_path = store.save(design_output)
    assert saved_path.exists()

    # Load
    loaded = store.load("alarm_clock", "ios")
    assert len(loaded) == 2
    assert loaded[0].id == "tc_1"
    assert loaded[0].name == "Verify clock display"
    assert loaded[0].steps == ["Open app", "Look at clock face"]
    assert loaded[0].priority == "P0"  # "high" normalized to "P0"
    assert loaded[1].id == "tc_2"
    assert loaded[1].steps == ["Tap + button", "Set time", "Confirm"]


def test_exists():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TestCaseStore(Path(tmpdir))
        assert store.exists("foo", "ios") is False

        store.save(TestDesignOutput(
            prompt_id="foo", platform="ios",
            test_cases=[TestCase(id="1", name="t", description="d")],
        ))
        assert store.exists("foo", "ios") is True
        assert store.exists("foo", "android") is False


def test_load_nonexistent(tmp_path, monkeypatch):
    # Isolate project root so the V2→V1 fallback cannot inject a real
    # TC_LAUNCH template from the repository, keeping the assertion stable.
    monkeypatch.setattr(
        "evalapp.benchset.testcases.store.get_project_root", lambda: tmp_path
    )
    store = TestCaseStore(tmp_path)
    assert store.load("missing", "ios") == []


def test_list_all():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TestCaseStore(Path(tmpdir))

        for prompt_id, platform in [("a", "ios"), ("a", "android"), ("b", "ios")]:
            store.save(TestDesignOutput(
                prompt_id=prompt_id, platform=platform,
                test_cases=[TestCase(id="1", name="t", description="d")],
            ))

        items = store.list_all()
        assert len(items) == 3
        assert items[0]["prompt_id"] == "a"
        assert items[0]["platform"] == "android"
        assert items[0]["count"] == 1


# ---------------------------------------------------------------------------
# TC_LAUNCH template injection (修复一)
# ---------------------------------------------------------------------------


def _write_tc_launch_template(common_dir: Path) -> None:
    """Write a minimal TC_LAUNCH template into *common_dir*."""
    common_dir.mkdir(parents=True, exist_ok=True)
    template = {
        "tc_launch": {
            "id": "TC_LAUNCH",
            "name": "应用启动验证",
            "steps": [
                "启动应用 -> 预期: 应用正常启动，无白屏或崩溃",
                "观察首页内容 -> 预期: 显示主界面核心内容",
            ],
            "expected_result": "应用成功启动并展示主页面内容",
            "priority": "P0",
            "category": "launch_check",
        }
    }
    (common_dir / "tc_launch_template.json").write_text(
        json.dumps(template, ensure_ascii=False), encoding="utf-8"
    )


def test_inject_tc_launch_resolves_v2_template(tmp_path, monkeypatch):
    """a) V2 样本目录下应从对应版本目录注入 TC_LAUNCH，且位于用例首位。"""
    # 模拟 dataset/V2 布局：样本目录在 V2/<category>/ 下，模板在 V2/common/
    monkeypatch.setattr(
        "evalapp.benchset.testcases.store.get_project_root", lambda: tmp_path
    )
    _write_tc_launch_template(tmp_path / "dataset" / "V2" / "common")
    sample_dir = tmp_path / "dataset" / "V2" / "games"
    sample_dir.mkdir(parents=True)

    store = TestCaseStore(sample_dir)
    # 没有用例文件 → load 最终走到 _inject_tc_launch([])
    loaded = store.load("missing_prompt", "ios")

    assert len(loaded) == 1
    assert loaded[0].id == "TC_LAUNCH"
    assert loaded[0].priority == "P0"
    assert loaded[0].category == "launch_check"


def test_inject_tc_launch_missing_logs_warning(tmp_path, monkeypatch, caplog):
    """b) 模板缺失时应降级返回原用例并记录含路径的 warning 日志。"""
    monkeypatch.setattr(
        "evalapp.benchset.testcases.store.get_project_root", lambda: tmp_path
    )
    # 不创建任何 dataset 目录 → 任何路径都找不到模板
    store = TestCaseStore(tmp_path)

    with caplog.at_level(logging.WARNING, logger="evalapp.benchset.testcases.store"):
        loaded = store.load("missing", "ios")

    assert loaded == []
    assert "TC_LAUNCH template not found" in caplog.text
    # 日志需含尝试过的具体路径，便于定位
    assert "tc_launch_template.json" in caplog.text
    assert "Tried paths" in caplog.text


# ---------------------------------------------------------------------------
# TC_LAUNCH version correctness & early-return (修复三 a/b)
# ---------------------------------------------------------------------------


def test_inject_tc_launch_resolves_v1_not_v2(tmp_path, monkeypatch):
    """a) V1 样本目录解析出 V1/common 模板而非 V2/common（版本正确性，防串台）。

    同时创建 V1 和 V2 两个版本的模板且内容各异，验证 V1 样本只拿到
    V1 的模板——向上查找到 V1/common 即命中，不会穿越到 V2/common。
    """
    monkeypatch.setattr(
        "evalapp.benchset.testcases.store.get_project_root", lambda: tmp_path
    )
    # V2 模板（不应被 V1 样本命中）
    _write_tc_launch_template(tmp_path / "dataset" / "V2" / "common")
    # V1 模板，使用独特标记以便区分
    v1_common = tmp_path / "dataset" / "V1" / "common"
    v1_common.mkdir(parents=True, exist_ok=True)
    v1_template = {
        "tc_launch": {
            "id": "TC_LAUNCH",
            "name": "V1启动验证",
            "steps": ["启动应用 -> 预期: 正常启动"],
            "expected_result": "应用成功启动",
            "priority": "P0",
            "category": "launch_check_v1",
        }
    }
    (v1_common / "tc_launch_template.json").write_text(
        json.dumps(v1_template, ensure_ascii=False), encoding="utf-8"
    )
    # V1 样本目录
    sample_dir = tmp_path / "dataset" / "V1" / "games"
    sample_dir.mkdir(parents=True)

    store = TestCaseStore(sample_dir)
    loaded = store.load("missing_prompt", "ios")

    assert len(loaded) == 1
    assert loaded[0].id == "TC_LAUNCH"
    # 验证用的是 V1 模板，而非 V2（V2 模板的 name 是「应用启动验证」）
    assert loaded[0].name == "V1启动验证"
    assert loaded[0].category == "launch_check_v1"


def test_load_does_not_reinject_hardcoded_tc_launch(tmp_path, monkeypatch, caplog):
    """b) 样本 JSON 已硬编码 TC_LAUNCH 时 load 不重复注入且模板文件不被读取。

    57 个 V2 样本都走这条早返回路径却无直接测试。验证：
    - 不重复注入（用例数不变）
    - 不触发模板解析（故意不创建模板文件，确认无 "template not found" warning）
    """
    monkeypatch.setattr(
        "evalapp.benchset.testcases.store.get_project_root", lambda: tmp_path
    )
    # 故意不创建任何模板文件——若早返回路径生效，模板解析不会被调用
    sample_dir = tmp_path / "samples"
    sample_dir.mkdir(parents=True)
    tc_dir = sample_dir / "my_sample" / "test_cases"
    tc_dir.mkdir(parents=True)
    # 硬编码 TC_LAUNCH + 一个普通用例
    data = {
        "test_cases": [
            {
                "id": "TC_LAUNCH",
                "name": "硬编码启动检查",
                "description": "应用启动验证",
                "steps": ["启动应用"],
                "expected_result": "正常启动",
                "priority": "P0",
            },
            {
                "id": "TC001",
                "name": "功能验证",
                "description": "核心功能",
                "steps": ["操作"],
                "expected_result": "成功",
            },
        ]
    }
    (tc_dir / "test_cases_default.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )

    with caplog.at_level(logging.WARNING, logger="evalapp.benchset.testcases.store"):
        loaded = TestCaseStore(sample_dir).load("my_sample", "default")

    # 不重复注入：仍为 2 条用例
    assert len(loaded) == 2
    # TC_LAUNCH 保留为硬编码版本（未被模板覆盖）
    assert loaded[0].id == "TC_LAUNCH"
    assert loaded[0].name == "硬编码启动检查"
    # 无模板查找 warning（说明早返回未触发模板解析）
    assert "TC_LAUNCH template not found" not in caplog.text
