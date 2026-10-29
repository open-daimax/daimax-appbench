# QuickCheck：应用快速评测

QuickCheck 是本次在既有开源评测框架上新增的首屏评测能力。完整评测、数据集、E2E 编排与原报告能力已经公开；旧 tag 或发布包未必包含新增快评。当前实现随本仓发布，运行不访问或依赖内部代码仓。

## 运行方式

```bash
pip install -e '.[quickcheck]'
python -m playwright install chromium
cp evalapp.yaml.example evalapp.yaml
# 配置 quickcheck.model.name/base_url，或启动后在本机页面配置模型。
export QUICKCHECK_API_KEY='自己的模型密钥'
evalapp quickcheck --url 'https://example.com'
evalapp quickcheck-ui --port 8766
# 等价的仓库启动脚本：
./scripts/start-quickcheck.sh
```

Linux 首次运行使用 `python -m playwright install --with-deps chromium` 安装浏览器与系统库。内置 HTML 已随包交付，运行页面不需要 Node.js；修改源码后用 `QUICKCHECK_BUILD_UI=1 ./scripts/start-quickcheck.sh` 重新构建。

本机模型配置页可填写模型名、兼容视觉接口、API Key、temperature、max_tokens 和服务商支持的 enable_thinking。留空凭据保留原值；读取接口不回显密钥。`QUICKCHECK_API_KEY` 环境变量优先于 YAML；设置了该环境变量时，页面保存的密钥不会覆盖环境变量。模型配置保存在被忽略的 evalapp.yaml，只对新任务生效。共享入口不开放模型管理。

### 模型可自由选择

QuickCheck 不限定模型或服务商：可在 YAML 或本机页面填写模型名、API 地址与密钥，接入支持视觉输入和所需 JSON 响应协议的兼容服务。推荐先使用 **`qwen3.8-flash`**，在我们的样例中效果、速度与成本较均衡。

参考体验为 **约30秒/次、约1.3分钱（¥0.013）/次**。这是项目提供的样例与成本估算，不是固定报价或速度承诺；页面复杂度、模型响应、缓存、token 用量、补全次数与服务商实际计费都会影响结果。

## 支持的质量子指标

模型只判断证据与完成度，代码按确定性规则计分。默认主观质量大项为视觉40%、信息30%、适配30%；下表的子项比例属于各自大项内部权重。

| 大项 | 子指标 | 内部权重 | 检查内容举例 |
|---|---|---:|---|
| 视觉与体验设计 | 构图布局 | 25% | 主体是否突出，区域主次、比例与空间组织是否服务任务 |
| 视觉与体验设计 | 字体排版 | 15% | 字号/字重层级、阅读节奏、可读性与任务匹配；常规字体本身不是缺陷 |
| 视觉与体验设计 | 配色与素材 | 20% | 配色主辅关系、视觉强调、素材统一性、主体细节与完成度 |
| 视觉与体验设计 | 控件细节 | 15% | 控件尺寸、图标标签、对齐和当前可见状态；不推断未测悬停/交互 |
| 视觉与体验设计 | 创意与场景表现 | 25% | 主题、具体图像、空间构图、材质光影与任务表达的整体贡献；不按证据条数累加 |
| 信息表达 | 用途与任务效率 | 30% | 用途和核心入口是否直接可见，页面是否服务主要任务 |
| 信息表达 | 信息组织 | 40% | 分组、优先级、标签与冗余信息带来的理解成本 |
| 信息表达 | 操作指引 | 30% | 下一步操作、必要上下文和导航是否清楚 |
| 设备适配 | 手机适配 | 50% | 窄屏结构、控件安排、主体取景与阅读范围 |
| 设备适配 | 桌面适配 | 50% | 宽屏比例、核心内容可读性、入口组织与空间安排；留白/居中本身不是缺陷 |

浏览器另外记录页面打开、重复观察确认的白屏/持续加载、未捕获脚本异常、请求与关键资源故障，以及视口溢出/控件裁切。运行检查用于扣减总分；技术几何问题归对应设备，避免换个维度重复扣分。这些记录不等同于完整功能测试或 WCAG 无障碍验收。

可见内容检查覆盖明确色情、现实赌博推广、毒品推广。普通游戏、虚拟币、教育/医疗等正常内容不自动当作违规；只依据已见证据，未知不当作通过，也不声称全站或法律合规。

默认：质量基分 = 视觉×40% + 信息×30% + 适配×30%；综合分 = max(0, 基分 − (100−运行分)×20%)。确认内容红线或页面无法打开按规则归零。实际权重、档位、扣分和上限以每次封存的 policy.json 为准。

非创意项取有依据的完成度评级与明确缺陷评分的较低值，再扣相应设备技术损失，不重复叠加同一问题。创意按整体贡献评级。基本合格60、较好70、优秀85、非常好95；没有写问题不自动给高分，证据不足保留未知。

## 真实示例

README 中 A/B/C 三例均来自真实历史结果，统一使用 qwen3.8-flash 与 hierarchical-v8.1；仅匿名化项目名、标识与链接，保留原分数、评分依据、截图和记录耗时。截图使用当前页面重现既有记录，没有重新调用模型，也没有修改历史评审。

| 示例 | 综合分 | 观察重点 |
|---|---:|---|
| A · 较低分 | 48.0 | 首屏引导页的呈现与双端适配不足；不据此断言计算器功能失败 |
| B · 中等分 | 62.6 | 信息和移动端相对清晰，桌面布局仍有改进空间 |
| C · 相对较高分 | 72.2 | 场景视觉表达更充分，仍不等于85分优秀档位或完整功能通过 |

匿名化记录与文件指纹见 [示例来源](images/quickcheck-examples.json)。示例用于解释报告，不是跨模型/跨版本排行，也不保证未来同样速度。实时耗时含排队、采集、模型主请求、必要补全与保存，接口服务与缓存状态也会变化。

## 执行、证据和产物

流程为排队 → 页面就绪采集 → 一次主评审 → 协议归一化 → 必要时一次白名单缺项补全 → 规则计分 → 保存。默认总预算120秒包含本地排队，模型并发上限5。缺项补全冻结已有判断，不修改结论来凑完整分数。

默认 `workspace_root/quickcheck`（workspace_root 默认 ~/eval_app_factory），可用 --output 覆盖：

```text
quickcheck/
  cases/          # URL 与业务标签
  snapshots/      # 截图、观察、技术事实及封存指纹
  policies/       # 去凭据的策略、模型参数与实现哈希
  runs/           # 每次请求、模型原文、补全审计、计分账本和 result.json
  experiments/    # 显式创建的运行对比
```

业务结果读取 `runs/<evaluation_id>/result.json`；截图通过结果的 snapshot_id 关联到 snapshots，而不是简单拼接 run 目录。失败/中断可能只产生部分文件，不应将缺失分数当作0。

当前仍能读取旧工作目录中采用 cases/snapshots/policies/runs 的记录；早期平铺 qc_* 布局和已移除的 legacy/defect 评分模式不再支持。原始工作区不自动迁移或删除。

复用快照重新评审会再次调用模型（snapshot_rejudge），不能标记为离线回放。`evalapp.quickcheck.replay_record(...)` 才是复用已有判断的离线重计分，不打开页面、不调用模型；会产生新 run，并保留原真实评测耗时。

Python 调用：

```python
from evalapp.config import get_config
from evalapp.commands.quickcheck import settings_from_config
from evalapp.quickcheck import evaluate_async

config = get_config()
result = await evaluate_async(
    'https://example.com',
    settings=settings_from_config(config),
    output_dir=config.quickcheck_workspace_path,
)
```

这里只评价采集时已见内容，不证明未操作功能、后台逻辑或全站状态。快评与完整评测采用不同评分口径，不直接横比总分。

## 后续维护

快评引擎、UI、协议和核心测试由独立模块同步；`evalapp/commands/quickcheck.py` 只做本框架配置与 CLI 适配。后续优先修改独立模块并提交，再运行 scripts/sync-quickcheck.py；不要在生成核心中维护第二套算法。具体步骤见 [同步维护说明](QuickCheck-Maintenance.md)。
