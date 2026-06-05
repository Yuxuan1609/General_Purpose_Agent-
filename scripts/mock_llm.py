"""Mock LLM client for fast dry-run testing. Returns pre-canned responses
matching each layer's expected JSON schema for learning tasks.

Usage: set LLM_MODE=mock via env or pass llm_mode="mock" to build_llm_client.
"""
from __future__ import annotations
import json
from unittest.mock import MagicMock
from core.llm_client import LLMClient, LLMResponse


class MockLLMClient(LLMClient):
    """LLM client that returns canned responses instead of making API calls.

    Matches the JSON schemas used by L1/L2/L3 Agents for learning tasks.
    Automatically detects which stage is being called based on the system prompt
    and returns an appropriate pre-canned response.
    """

    def __init__(self):
        super().__init__(MockLLMClient, "mock")
        self.model = "mock"

    def chat(self, messages: list, tools: list | None = None,
             json_mode: bool = False, **kwargs) -> LLMResponse:
        system = ""
        user = ""
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content", "")
            elif m.get("role") == "user":
                user = m.get("content", "")
        combined = system + " " + user
        text = self._canned(combined)
        return LLMResponse(text=text, tool_calls=[])

    def _canned(self, prompt: str) -> str:
        """Detect which stage is being called and return matching response."""
        pl = prompt.lower()

        # LLM1: preprocessing (raw -> LearningUnits)
        if "learning data preprocessor" in pl:
            return json.dumps(_MOCK_LLM1_UNITS, ensure_ascii=False)

        # L1 Stage2: learning task (check BEFORE game — schema has l1_modifications)
        if "l1 层的认知 agent" in pl and "l1_modifications" in pl:
            return json.dumps(_MOCK_L1_LEARN, ensure_ascii=False)

        # L1 Stage2: game decision (no l1_modifications)
        if "l1 层的认知 agent" in pl or ("认知 agent" in pl and "做出最终决策" in pl):
            return json.dumps(_MOCK_L1_GAME, ensure_ascii=False)

        # L1 Stage1: domain node selection
        if "领域节点" in prompt:
            return json.dumps(_MOCK_L1_STAGE1, ensure_ascii=False)

        # L2 Stage3: learning task (check BEFORE game)
        if "最终知识整合" in prompt and "l2_modifications" in pl:
            return json.dumps(_MOCK_L2_LEARN, ensure_ascii=False)

        # L2 Stage3: game decision
        if "最终知识整合" in prompt:
            return json.dumps(_MOCK_L2_GAME, ensure_ascii=False)

        # L2 Stage2: card filter
        if "知识筛选" in prompt:
            return json.dumps(_MOCK_L2_STAGE2, ensure_ascii=False)

        # L3: learning task
        if "l3 层的认知 agent" in pl and "l3_modifications" in pl:
            return json.dumps(_MOCK_L3_LEARN, ensure_ascii=False)

        # L3: game decision
        if "l3 层的认知 agent" in pl or "使用技能执行" in prompt:
            return json.dumps(_MOCK_L3_GAME, ensure_ascii=False)

        # Executor fallback
        return json.dumps({"result": "raise", "done": True, "reasoning": "mock"})


# ── Canned responses ────────────────────────────────────────────────────

_MOCK_LLM1_UNITS = [
    {"idx": 0, "summary": "翻牌前持有Q♠，基于胜率call", "l1_reasoning": "持有中等牌Q♠，期望值为正", "l2_reasoning": "K最大牌时应激进加注", "l3_reasoning": ""},
    {"idx": 1, "summary": "翻牌后未成对，check控制底池", "l1_reasoning": "先手持有中等牌宜check", "l2_reasoning": "未成对J时对手加注应fold", "l3_reasoning": ""},
    {"idx": 2, "summary": "翻牌后fold避免损失", "l1_reasoning": "胜率不足25%，底池赔率不够", "l2_reasoning": "未成对Q时fold", "l3_reasoning": ""},
    {"idx": 3, "summary": "翻牌前持有K♠，加注最大化收益", "l1_reasoning": "持有最大牌K♠，激进加注", "l2_reasoning": "K翻牌前激进加注", "l3_reasoning": "leduc-preflop-raise技能" + "匹配"},
    {"idx": 4, "summary": "翻牌后K♠高牌，加注获取价值", "l1_reasoning": "K high强牌，加注迫使弱牌弃牌", "l2_reasoning": "翻牌后K未成对应加注", "l3_reasoning": ""},
]

_MOCK_L1_STAGE1 = {
    "query": "分析翻牌后持有K且未成对时的最佳行动策略",
    "domain_nodes": [
        {"name": "game/leduc", "score": 1.0, "reason": "Leduc Hold'em game domain"},
        {"name": "learning/reflect", "score": 0.8, "reason": "may need learning domain knowledge"},
    ],
}

_MOCK_L1_GAME = {
    "done": True,
    "result": "raise",
    "reasoning": "持有K♠为最大牌，根据概率期望加注收益更高",
    "rules_used": ["l1_602ae3"],
}

_MOCK_L1_LEARN = {
    "done": True,
    "result": "学习完成：建议新增L1规则",
    "reasoning": "分析执行记录发现翻牌后持有K时缺少明确策略指导。建议新增2条L1规则。",
    "rules_used": ["l1_602ae3"],
    "l1_modifications": [
        {
            "target": "l1/postflop-k-raise",
            "type": "create",
            "payload": {
                "content": "翻牌后持有K（最大牌）且公共牌未成对时，应加注以迫使较弱牌弃牌并获取价值。加注额建议4筹码。对手示弱时打满加注次数，对手反加时重新评估手牌强度。",
                "reason": "记录显示翻牌后K高牌加注期望收益为正；当前L1规则未覆盖此场景",
            },
        },
    ],
}

_MOCK_L2_STAGE2 = {
    "cards": [
        "[game/leduc] 持有K（最大牌）时翻牌前激进加注。对手Call说明对手有Q或J并赌公共牌。max 2 raises per round，尽量打满加注次数。",
        "[game/leduc] 公共牌与手牌配对时全力加注。翻牌后加注额4筹码。对手未配对时大概率fold。",
        "[game/leduc] 翻牌后未成对且手牌为J时，若对手加注应考虑fold。",
    ],
    "call_l3": True,
    "l3_task": "翻牌后持有K且未成对时的加注操作流程",
    "reasoning": "筛选的卡片均与当前决策相关。需要L3提供具体操作流程以完善策略。",
}

_MOCK_L2_LEARN = {
    "reply": "分析完成：需要补充翻牌后K未成对的策略卡片",
    "reasoning": "现有L2卡片覆盖翻牌前加注、成对加注、弱牌fold，但缺少翻牌后持有K未成对时的具体指导。建议新增卡片补充此场景。",
    "l2_modifications": [
        {
            "target": "l2/postflop-k-unpaired-raise",
            "type": "create",
            "payload": {
                "content": "翻牌后持有K且公共牌低于K未成对时，应加注以隔离弱牌并获取价值。对手call可能持有Q或K可继续加注；对手raise则需评估是否已成对。",
                "domain": "game/leduc",
                "confidence": 0.75,
                "reason": "多局记录显示此策略正EV；当前L2卡片无此场景覆盖",
            },
        },
    ],
}

_MOCK_L2_STAGE2 = {
    "cards": [
        "[game/leduc] 持有K（最大牌）时翻牌前激进加注。对手Call说明对手有Q或J并赌公共牌。max 2 raises per round，尽量打满加注次数。",
        "[game/leduc] 公共牌与手牌配对时全力加注。翻牌后加注额4筹码。对手未配对时大概率fold。",
        "[game/leduc] 翻牌后未成对且手牌为J时，若对手加注应考虑fold。",
    ],
    "call_l3": True,
    "l3_task": "翻牌后持有K且未成对时的加注策略",
    "reasoning": "筛选的卡片均与当前决策相关。需要L3提供具体技能内容以完善策略。",
}

_MOCK_L2_GAME = {
    "reply": "建议raise。持有K♠为最大牌，根据知识卡片应激进加注。",
    "reasoning": "K最大牌，翻牌前加注是正EV决策。对手call说明可能有Q或J。",
}

_MOCK_L2_LEARN = {
    "reply": "分析完成：需要补充翻牌后K未成对的策略卡片",
    "reasoning": "现有L2卡片覆盖翻牌前加注、成对加注、弱牌fold，但缺少翻牌后持有K未成对时的具体指导。建议新增卡片补充此场景。",
    "l2_modifications": [
        {
            "target": "l2/postflop-k-unpaired-raise",
            "type": "create",
            "payload": {
                "content": "翻牌后持有K且公共牌低于K未成对时，应加注以隔离弱牌并获取价值。对手call可能持有Q或K可继续加注；对手raise则需评估是否已成对。",
                "domain": "game/leduc",
                "confidence": 0.75,
                "reason": "多局记录显示此策略正EV；当前L2卡片无此场景覆盖",
            },
        },
    ],
}

_MOCK_L3_GAME = {
    "skills_used": ["leduc-preflop-raise"],
    "result": "执行翻牌前加注策略：持有K时raise",
    "reasoning": "leduc-preflop-raise技能匹配当前局面，K→raise决策正确",
}

_MOCK_L3_LEARN = {
    "skills_used": ["learning-reflect-analyze"],
    "result": "技能分析完成：现有技能足够覆盖当前学习场景",
    "reasoning": "learning-reflect-analyze已覆盖对局分析和策略改进场景。游戏技能leduc-preflop-raise和leduc-postflop-pair内容合适，无需修改。",
    "l3_modifications": [],
}
