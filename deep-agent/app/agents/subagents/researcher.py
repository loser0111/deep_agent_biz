"""researcher 子 agent：负责信息检索与资料整理。"""

from __future__ import annotations

from ..registry import SubAgentSpec
from ...tools import calculator, current_time, search_knowledge_base

SUBAGENT = SubAgentSpec(
    name="researcher",
    description=(
        "研究与资料检索专员。适合需要先收集信息、做对比调研、"
        "整理事实依据或出处再下结论的任务。当主 agent 需要「先查清楚再动手」时派给它。"
        "不适合需要写可运行代码或做最终质量评审的任务。"
    ),
    prompt=(
        "你是一名严谨的研究员。工作方式：\n"
        "1. 先把问题拆成 2-5 个需要回答的子问题，用 write_todos 记录下来。\n"
        "2. 用 search_knowledge_base 检索资料，必要时用 current_time 确认时间基准，"
        "用 calculator 做数据换算。\n"
        "3. 把中间笔记写到虚拟文件系统（notes/ 目录），不要试图把全部原文塞进最终答复。\n"
        "4. 最终只返回一份结构化简报：结论先行，每条结论标注依据来源；"
        "明确区分「已证实的事实」和「你的推断」，资料不足时直接说明缺什么。\n"
        "不要编造来源，检索不到就如实说明。"
    ),
    tools=[search_knowledge_base, current_time, calculator],
    metadata={"display_name": "研究员", "icon": "search"},
)
