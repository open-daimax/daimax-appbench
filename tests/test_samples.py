"""Tests for benchmark sample loading."""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock

import yaml
import pytest

from evalapp.benchset.samples.store import SampleStore
from evalapp.evaluation.exec_plan.store import ExecPlanStore
from evalapp.evaluation.runner.evaluator import Evaluator


def test_sample_store_loads_from_index():
    with tempfile.TemporaryDirectory() as tmpdir:
        samples_dir = Path(tmpdir) / "dataset" / "eval_samples_v1"
        samples_dir.mkdir(parents=True)

        (samples_dir / "index.yaml").write_text(yaml.dump({
            "files": [{"file": "simple_samples.yaml"}],
        }))
        (samples_dir / "simple_samples.yaml").write_text(yaml.dump({
            "samples": [
                {
                    "sample_id": "S001",
                    "requirement": "实现一个计算器应用",
                    "platforms": ["android", "ios"],
                    "app_type": "工具",
                    "complexity": "simple",
                    "core_functions": ["四则运算"],
                }
            ],
        }, allow_unicode=True))

        store = SampleStore(samples_dir)
        items = store.list_all()

        assert len(items) == 1
        assert items[0].sample_id == "S001"
        assert items[0].platforms == ["android", "ios"]
        assert items[0].to_eval_prompt().id == "S001"
        # For new structure, test_cases_dir is samples_dir root
        assert store.test_cases_dir == samples_dir


def test_sample_store_filter_by_platform():
    with tempfile.TemporaryDirectory() as tmpdir:
        samples_dir = Path(tmpdir) / "dataset" / "eval_samples_v1"
        samples_dir.mkdir(parents=True)

        (samples_dir / "simple_samples.yaml").write_text(yaml.dump({
            "samples": [
                {
                    "sample_id": "S001",
                    "requirement": "实现一个计算器应用",
                    "platforms": ["android"],
                },
                {
                    "sample_id": "S002",
                    "requirement": "实现一个记事本应用",
                    "platforms": ["ios"],
                },
            ],
        }, allow_unicode=True))

        store = SampleStore(samples_dir)

        android_samples = store.filter(platform="android")
        ios_samples = store.filter(platform="ios")

        assert [sample.sample_id for sample in android_samples] == ["S001"]
        assert [sample.sample_id for sample in ios_samples] == ["S002"]


def test_exec_plan_store_loads_plan():
    """Test execution plan loading."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        
        # Create dataset structure
        dataset_dir = project_root / "dataset" / "games"
        dataset_dir.mkdir(parents=True)
        
        # Create index.yaml
        (dataset_dir / "index.yaml").write_text(yaml.dump({
            "version": "1.0",
            "name": "游戏样本集",
            "samples_index": [
                {"dir": "HappyMatch", "sample_id": "HappyMatch", "title": "开心消消乐"}
            ]
        }, allow_unicode=True))
        
        # Create sample directory and sample.yaml
        sample_dir = dataset_dir / "HappyMatch"
        sample_dir.mkdir()
        (sample_dir / "sample.yaml").write_text(yaml.dump({
            "sample_id": "HappyMatch",
            "requirement": "实现一个消消乐游戏",
            "platforms": ["android", "ios", "miniprogram"],
            "app_type": "游戏",
        }, allow_unicode=True))
        
        # Create execution plan
        exec_plan_dir = project_root / "exec_plan"
        exec_plan_dir.mkdir()
        exec_plan_file = exec_plan_dir / "test_plan.yaml"
        exec_plan_file.write_text(yaml.dump({
            "version": "1.0",
            "name": "测试计划",
            "description": "测试执行计划",
            "datasets": ["dataset/games"],
            "tasks": [
                {"order": 1, "sample_id": "HappyMatch", "platform": "android"},
                {"order": 2, "sample_id": "HappyMatch", "platform": "ios"},
            ]
        }, allow_unicode=True))
        
        # Load execution plan
        plan_store = ExecPlanStore(exec_plan_file, project_root)
        
        # Verify plan loaded correctly
        assert plan_store.plan_name == "测试计划"
        assert len(plan_store.list_datasets()) == 1
        assert plan_store.list_datasets()[0] == "dataset/games"
        
        # Verify tasks
        tasks = plan_store.get_tasks()
        assert len(tasks) == 2
        assert tasks[0]["sample_id"] == "HappyMatch"
        assert tasks[0]["platform"] == "android"
        
        # Verify sample lookup
        sample = plan_store.get_sample("HappyMatch")
        assert sample is not None
        assert sample.sample_id == "HappyMatch"


def test_exec_plan_store_cross_dataset():
    """Test execution plan with multiple datasets."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        
        # Create games dataset
        games_dir = project_root / "dataset" / "games"
        games_dir.mkdir(parents=True)
        (games_dir / "index.yaml").write_text(yaml.dump({
            "samples_index": [
                {"dir": "HappyMatch", "sample_id": "HappyMatch", "title": "开心消消乐"}
            ]
        }))
        (games_dir / "HappyMatch" / "sample.yaml").parent.mkdir(parents=True)
        (games_dir / "HappyMatch" / "sample.yaml").write_text(yaml.dump({
            "sample_id": "HappyMatch",
            "requirement": "实现一个消消乐游戏",
            "platforms": ["android"],
        }))
        
        # Create tools dataset
        tools_dir = project_root / "dataset" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "index.yaml").write_text(yaml.dump({
            "samples_index": [
                {"dir": "Weather", "sample_id": "Weather", "title": "天气"}
            ]
        }))
        (tools_dir / "Weather" / "sample.yaml").parent.mkdir(parents=True)
        (tools_dir / "Weather" / "sample.yaml").write_text(yaml.dump({
            "sample_id": "Weather",
            "requirement": "实现一个天气应用",
            "platforms": ["android"],
        }))
        
        # Create cross-dataset execution plan
        exec_plan_file = project_root / "exec_plan.yaml"
        exec_plan_file.write_text(yaml.dump({
            "version": "1.0",
            "name": "跨样本集测试",
            "datasets": ["dataset/games", "dataset/tools"],
            "tasks": [
                {"order": 1, "sample_id": "HappyMatch", "platform": "android"},
                {"order": 2, "sample_id": "Weather", "platform": "android"},
            ]
        }))
        
        # Load and verify
        plan_store = ExecPlanStore(exec_plan_file, project_root)
        tasks = plan_store.get_tasks()
        assert len(tasks) == 2
        
        # Verify samples from different datasets
        sample1 = plan_store.get_sample("HappyMatch")
        sample2 = plan_store.get_sample("Weather")
        assert sample1 is not None
        assert sample2 is not None
        assert sample1.sample_id == "HappyMatch"
        assert sample2.sample_id == "Weather"


def test_exec_plan_store_invalid_sample():
    """Test execution plan validation with invalid sample_id."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        
        # Create minimal dataset
        dataset_dir = project_root / "dataset" / "games"
        dataset_dir.mkdir(parents=True)
        (dataset_dir / "index.yaml").write_text(yaml.dump({
            "samples_index": [
                {"dir": "HappyMatch", "sample_id": "HappyMatch", "title": "开心消消乐"}
            ]
        }))
        (dataset_dir / "HappyMatch" / "sample.yaml").parent.mkdir(parents=True)
        (dataset_dir / "HappyMatch" / "sample.yaml").write_text(yaml.dump({
            "sample_id": "HappyMatch",
            "requirement": "实现一个消消乐游戏",
            "platforms": ["android"],
        }))
        
        # Create execution plan with invalid sample_id
        exec_plan_file = project_root / "exec_plan.yaml"
        exec_plan_file.write_text(yaml.dump({
            "version": "1.0",
            "name": "无效计划",
            "datasets": ["dataset/games"],
            "tasks": [
                {"order": 1, "sample_id": "NonExistent", "platform": "android"},
            ]
        }))
        
        # Should raise ValueError
        with pytest.raises(ValueError, match="NonExistent"):
            ExecPlanStore(exec_plan_file, project_root)


def test_filter_test_cases_by_end_case():
    """Test filtering test cases by end_case."""
    # Create mock test cases
    tc1 = Mock()
    tc1.id = "TC001"
    tc1.name = "Test Case 1"
    
    tc2 = Mock()
    tc2.id = "TC002"
    tc2.name = "Test Case 2"
    
    tc3 = Mock()
    tc3.id = "TC003"
    tc3.name = "Test Case 3"
    
    tc4 = Mock()
    tc4.id = "TC004"
    tc4.name = "Test Case 4"
    
    test_cases = [tc1, tc2, tc3, tc4]
    
    # Test filtering to TC002
    filtered = Evaluator._filter_test_cases_by_end_case(test_cases, "TC002")
    assert len(filtered) == 2
    assert filtered[0].id == "TC001"
    assert filtered[1].id == "TC002"
    
    # Test filtering to TC003
    filtered = Evaluator._filter_test_cases_by_end_case(test_cases, "TC003")
    assert len(filtered) == 3
    assert filtered[2].id == "TC003"
    
    # Test filtering to TC001
    filtered = Evaluator._filter_test_cases_by_end_case(test_cases, "TC001")
    assert len(filtered) == 1
    assert filtered[0].id == "TC001"
    
    # Test filtering to non-existent case (should return all with warning)
    filtered = Evaluator._filter_test_cases_by_end_case(test_cases, "TC999")
    assert len(filtered) == 4  # Returns all


def test_exec_plan_with_end_case():
    """Test execution plan with end_case field."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        
        # Create dataset structure
        dataset_dir = project_root / "dataset" / "games"
        dataset_dir.mkdir(parents=True)
        
        # Create index.yaml
        (dataset_dir / "index.yaml").write_text(yaml.dump({
            "version": "1.0",
            "name": "游戏样本集",
            "samples_index": [
                {"dir": "HappyMatch", "sample_id": "HappyMatch", "title": "开心消消乐"}
            ]
        }, allow_unicode=True))
        
        # Create sample directory and sample.yaml
        sample_dir = dataset_dir / "HappyMatch"
        sample_dir.mkdir()
        (sample_dir / "sample.yaml").write_text(yaml.dump({
            "sample_id": "HappyMatch",
            "requirement": "实现一个消消乐游戏",
            "platforms": ["android", "ios", "miniprogram"],
            "app_type": "游戏",
        }, allow_unicode=True))
        
        # Create execution plan with end_case
        exec_plan_dir = project_root / "exec_plan"
        exec_plan_dir.mkdir()
        exec_plan_file = exec_plan_dir / "test_plan.yaml"
        exec_plan_file.write_text(yaml.dump({
            "version": "1.0",
            "name": "快速验证计划",
            "description": "测试执行计划",
            "datasets": ["dataset/games"],
            "tasks": [
                {"order": 1, "sample_id": "HappyMatch", "platform": "android", "end_case": "TC003"},
                {"order": 2, "sample_id": "HappyMatch", "platform": "ios"},  # No end_case
            ]
        }, allow_unicode=True))
        
        # Load execution plan
        plan_store = ExecPlanStore(exec_plan_file, project_root)
        
        # Verify tasks include end_case
        tasks = plan_store.get_tasks()
        assert len(tasks) == 2
        assert tasks[0]["end_case"] == "TC003"
        assert "end_case" not in tasks[1] or tasks[1].get("end_case") is None


def test_nature_samples_bottom_tab_limit_and_cases():
    """自然观察样本底部导航应限制为 5 个入口，测试用例同步使用新导航语义。"""
    project_root = Path(__file__).resolve().parent.parent
    samples = {
        "AquariumManager": {
            "tabs": {"我的鱼缸", "水质监测", "生物档案", "投喂计划", "社区鱼市"},
            "settings_entry": "我的鱼缸-设置入口",
        },
        "PlantDiary": {
            "tabs": {"我的花园", "养护日志", "浇水提醒", "社区", "百科"},
            "settings_entry": "我的花园-设置入口",
        },
        "ReptileCare": {
            "tabs": {"我的爬宠", "饲养记录", "喂食日历", "健康档案", "社区求助"},
            "settings_entry": "我的爬宠-设置入口",
        },
    }

    for sample_id, expected in samples.items():
        sample_path = project_root / "dataset" / "V2" / "nature" / sample_id / "sample.yaml"
        test_cases_path = sample_path.parent / "test_cases" / "test_cases_default.json"

        sample_data = yaml.safe_load(sample_path.read_text(encoding="utf-8"))
        tab_entries = {
            page.get("entry_from", "").removeprefix("底部Tab-")
            for page in sample_data.get("pages", [])
            if page.get("entry_from", "").startswith("底部Tab-")
        }

        assert tab_entries == expected["tabs"]
        assert len(tab_entries) == 5

        settings_page = next(page for page in sample_data["pages"] if page["name"] == "设置")
        assert settings_page["level"] == "L2"
        assert settings_page["entry_from"] == expected["settings_entry"]

        test_cases_data = json.loads(test_cases_path.read_text(encoding="utf-8"))
        test_case_text = json.dumps(test_cases_data, ensure_ascii=False)
        assert "TC_NAV_01" not in {tc["id"] for tc in test_cases_data["test_cases"]}
        assert "底部Tab-设置" not in test_case_text
        assert "设置Tab" not in test_case_text
        assert "6个Tab" not in test_case_text
        assert "氨氞" not in test_case_text
