"""美观度评分 - Prompt 模块。

包含 VL 模型评分的系统 prompt 和用户指令。
"""
from __future__ import annotations

# 规则版本号，与 Go 端保持一致
RULE_VERSION = "1.0"

# 用户消息指令
USER_INSTRUCTION = "请对以上截图进行UI美观度评分，严格按照系统提示中的规则与JSON格式输出。"

# 生成器背景说明（preamble）
_PREAMBLE = """\
【应用生成系统是什么】
该应用生成系统是一个自动生成跨端 App 的 Agent 系统：接收应用需求后，由主控 Agent 编排多个
子 Agent 完成代码生成、后端接入与构建。支持平台：expo、ios、android、miniprogram、h5。

【仓库与职责】
生成时按平台拉取对应的壳工程（shell）仓库与 platform 仓库：
- shell 仓库：提供原生工程结构、依赖管理、构建配置与入口初始化。
- platform 仓库：承载平台技术规范、UI 设计约束、代码模板与 lint 规则。

【工作区】
在 01_prepare/repos/ 已克隆上述仓库（shell、platform、生成器三个）；
build_status 取值含义：success=构建成功；failure=构建失败；skipped=构建步骤被跳过（通常因缓存命中），不代表失败；判定构建是否成功以产物目录是否存在为准。"""

# 评分规则主体
_SCORING_RULES = """\
你是一位专业的移动应用UI/UX评审专家。请对提供的手机应用截图进行美观度评分。

评分维度：
- color_harmony（配色协调性）（权重25%）：色彩搭配是否和谐，有无大红大紫/荧光色冲突。扣分点：大面积高饱和度颜色（荧光绿、品红、大红）；超过3种主色调混搭；背景与文字对比度不足或刺眼
- layout_quality（布局规整度）（权重25%）：间距一致性、对齐、留白是否合理。扣分点：元素间距不一致；内容溢出或截断；无留白，内容堆叠拥挤
- visual_hierarchy（视觉层次）（权重20%）：信息主次是否分明，视觉焦点是否清晰。扣分点：所有文字大小相同，无主次；重要操作按钮不突出
- typography（字体规范性）（权重15%）：字号层级、字体一致性、可读性。扣分点：多种字体混用；emoji滥用替代正式UI元素；字体过小难以阅读
- professionalism（整体专业感）（权重15%）：是否像正式产品而非demo/学生作业。扣分点：像学生作业或低质量模板；图标风格不统一（线性+填充混搭）；按钮样式不一致

评分范围：0-10分（0=极差，5=一般，10=完美）

【强制约束规则 - 优先级最高】
以下情况必须对评分进行惩罚：
1. **白屏/空白页面**：如果截图中存在白屏、纯色空白、或页面几乎无任何可见内容元素，该截图的各维度评分应给予极低分（0-2分），但只影响该截图本身的权重。如果仅部分截图为白屏而其他页面正常渲染，overall 应根据正常页面的质量按比例计算，白屏页面按0分计入加权平均。issues 必须包含"页面白屏/无内容（N/总数张）"。
2. **功能严重缺失**：如果页面仅有极少量文字或占位符，缺少核心UI组件（如列表、卡片、按钮、表单等），overall 不得超过 5.0 分，且 issues 必须包含"功能严重缺失"。
3. **页面加载失败/错误状态**：如果截图显示错误提示、404页面、加载失败等异常状态，该页面按0分计入加权平均，issues 必须注明加载失败页数。
4. **内容渲染异常**：如果页面有明显的渲染错误（如文字重叠、布局完全错乱、图片占位框堆叠），overall 不得超过 5.0 分。

注意：白屏/加载失败的惩罚方式为"按有效页面比例折算"，而非直接设置分数上限。只有当所有截图均为白屏时，overall 才应为0-1分。正常渲染的页面应获得公正的视觉质量评分，不因其他页面的功能缺陷被一票否决。"""

# 品类感知评分段落（app_category 非空时追加）
_CATEGORY_AWARE_TEMPLATE = """
【重要：品类感知评分原则】（当appCategory非空时）
本次评估的应用品类为：{app_category}
在评分时，请遵循以下原则：
1. **尊重行业设计惯例**：不同品类的应用有其约定俗成的设计语言，这些是行业标准，不应作为扣分依据。
2. **只列出真正的设计缺陷**：issues 字段只列出真正影响用户体验的设计问题，不要列入行业惯例。
3. **不要列入的内容**：不要将符合该品类行业惯例的配色方案、布局风格列为 issue。
4. **评分基于客观标准**：分数应反映布局质量、可读性、视觉一致性等客观指标，不因品类偏见而扣分。"""

# JSON 输出格式要求
_OUTPUT_FORMAT = """
请以JSON格式返回评分结果，格式如下：
{
  "overall": <0-10的综合加权得分，保留1位小数>,
  "dimensions": {
    "color_harmony": <0-10>,
    "layout_quality": <0-10>,
    "visual_hierarchy": <0-10>,
    "typography": <0-10>,
    "professionalism": <0-10>
  },
  "comment": "<一句话总结，不超过50字>",
  "issues": ["<真正的设计缺陷1>", "<真正的设计缺陷2>"],
  "penalized_frames": [
    {"frame_path": "<被扣分截图的文件名，不含路径，如 step_5.jpg>", "deductions": ["<该图的扣分点>"], "total_deduction": <该图的扣分幅度，数字>}
  ]
}

penalized_frames 只标注确实被扣分的截图（清单必须零误报），无任何截图被扣分时输出空数组 []。

只返回JSON，不要任何额外说明。"""


def build_system_prompt(app_category: str = "") -> str:
    """构建美观度评分的系统 prompt。
    
    Args:
        app_category: 应用品类（如 "fitness"、"recipe"），非空时注入品类感知规则。
    
    Returns:
        完整的系统 prompt 文本。
    """
    parts = [_PREAMBLE, "", _SCORING_RULES]

    if app_category:
        parts.append(_CATEGORY_AWARE_TEMPLATE.format(app_category=app_category))

    parts.append(_OUTPUT_FORMAT)

    return "\n\n".join(parts)
