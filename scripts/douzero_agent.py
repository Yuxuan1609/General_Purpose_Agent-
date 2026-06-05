"""
DouZero LLM Agent — 使用大语言模型玩斗地主

提供 DouZeroLLMAgent 类，实现与 DeepAgent 相同的 act(infoset) 接口，
通过 LLMClient 调用大语言模型进行出牌决策。

用法:
  python scripts/douzero_agent.py          # 运行示例测试
"""

import logging
import random
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.llm_client import LLMClient
from core.types import TaskObservation

logger = logging.getLogger("douzero_agent")

# ═══════════════════════════════════════════════════════════════
# Card encoding (from DouZero game.py:5-11)
# ═══════════════════════════════════════════════════════════════
ENV_CARD_TO_STR: dict[int, str] = {
    3: '3', 4: '4', 5: '5', 6: '6', 7: '7', 8: '8', 9: '9',
    10: '10', 11: 'J', 12: 'Q', 13: 'K', 14: 'A',
    17: '2', 20: 'X', 30: 'D',
}

STR_TO_ENV_CARD: dict[str, int] = {v: k for k, v in ENV_CARD_TO_STR.items()}

POSITION_CN: dict[str, str] = {
    'landlord':        '地主',
    'landlord_up':     '地主上家',
    'landlord_down':   '地主下家',
}

# ═══════════════════════════════════════════════════════════════
# Utility
# ═══════════════════════════════════════════════════════════════


def cards_to_str(cards: list[int]) -> str:
    """Convert DouZero env cards to human-readable string.

    >>> cards_to_str([3, 4, 17, 20, 30])
    '3 4 2 X D'
    """
    return ' '.join(ENV_CARD_TO_STR.get(c, str(c)) for c in cards)


def _parse_card_tokens(text: str) -> list[int]:
    """Parse a compact or spaced card string into env card integers.

    Handles multi-char tokens: "10", "17"(2), "20"(X), "30"(D).
    Case-insensitive.
    """
    text = text.upper().replace(' ', '')
    tokens: list[int] = []
    i = 0
    n = len(text)
    while i < n:
        twoch = text[i:i + 2]
        if twoch == '10':
            tokens.append(10)
            i += 2
        elif twoch == '17':
            tokens.append(17)
            i += 2
        elif twoch == '20':
            tokens.append(20)
            i += 2
        elif twoch == '30':
            tokens.append(30)
            i += 2
        elif text[i] == 'J':
            tokens.append(11)
            i += 1
        elif text[i] == 'Q':
            tokens.append(12)
            i += 1
        elif text[i] == 'K':
            tokens.append(13)
            i += 1
        elif text[i] == 'A':
            tokens.append(14)
            i += 1
        elif text[i] == '2':
            tokens.append(17)
            i += 1
        elif text[i] == 'X':
            tokens.append(20)
            i += 1
        elif text[i] == 'D':
            tokens.append(30)
            i += 1
        elif text[i].isdigit():
            tokens.append(int(text[i]))
            i += 1
        else:
            i += 1
    return tokens


# ═══════════════════════════════════════════════════════════════
# DouZeroLLMAgent
# ═══════════════════════════════════════════════════════════════

DOUDIZHU_GAME_RULES = """牌面大小：3<4<5<6<7<8<9<10<J<Q<K<A<2<小王(X)<大王(D)

牌型（必须严格按类型出牌）：
- 单张：1张牌
- 对子：2张相同牌
- 三张：3张相同牌
- 三带一：3张相同牌+1张任意牌
- 三带二：3张相同牌+1个对子
- 顺子：≥5张连续牌（3-A之间，不含2和大小王）
- 连对：≥3个连续对子（如334455）
- 飞机：≥2个连续三张，可带等量单张或对子（如33344456）
- 炸弹：4张相同牌（可管任何牌型）
- 火箭：小王+大王（XD），最大牌型，可管一切

出牌规则：
- 必须出牌型相同且更大的牌（炸弹/火箭除外）
- 可以选择"不出"（跳过本轮）
- 新一回合你是先手时可自由出牌

回复要求：只输出"不出"或牌面字符串，不要解释。"""

_SYSTEM_PROMPT_TEMPLATE = """你正在玩斗地主。你的身份是{position_cn}。

牌面大小：3<4<5<6<7<8<9<10<J<Q<K<A<2<小王(X)<大王(D)

牌型（必须严格按类型出牌）：
- 单张：1张牌
- 对子：2张相同牌
- 三张：3张相同牌
- 三带一：3张相同牌+1张任意牌
- 三带二：3张相同牌+1个对子
- 顺子：≥5张连续牌（3-A之间，不含2和大小王）
- 连对：≥3个连续对子（如334455）
- 飞机：≥2个连续三张，可带等量单张或对子（如33344456）
- 炸弹：4张相同牌（可管任何牌型）
- 火箭：小王+大王（XD），最大牌型，可管一切

出牌规则：
- 必须出牌型相同且更大的牌（炸弹/火箭除外）
- 可以选择"不出"（跳过本轮）
- 新一回合你是先手时可自由出牌

回复要求：只输出"不出"或牌面字符串，不要解释。"""


class DouZeroLLMAgent:
    """LLM-based agent implementing the DouZero DeepAgent interface."""

    def __init__(self, llm_client: LLMClient, position: str = 'landlord_up',
                 use_perfect_info: bool = False):
        self._llm = llm_client
        self.position = position
        self._position_cn = POSITION_CN.get(position, position)
        self.use_perfect_info = use_perfect_info

    # ── Main interface ─────────────────────────────────────────

    def act(self, infoset) -> list[int]:
        """Choose an action given the current InfoSet.

        Args:
            infoset: DouZero InfoSet object.

        Returns:
            A list of env card integers (e.g. [3,3,3,4]) or [] for pass.
        """
        if len(infoset.legal_actions) == 1:
            return infoset.legal_actions[0]

        system_prompt = self._build_system_prompt()
        user_prompt = self.build_prompt_test(infoset)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ]

        logger.info("--- LLM Request ---")
        logger.info("System: %s", system_prompt[:200])
        for line in user_prompt.strip().splitlines():
            logger.info("Prompt: %s", line)

        chat_kwargs: dict = {}
        if getattr(self._llm, "thinking_enabled", False):
            chat_kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

        resp = self._llm.chat(messages=messages, **chat_kwargs)
        logger.info("LLM Response: %s", resp.text)

        action = self.parse_action(resp.text, infoset.legal_actions)
        logger.info("Parsed Action: %s  (%s)", action, cards_to_str(action) if action else "不出")
        return action

    # ── Prompt builders ────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        return _SYSTEM_PROMPT_TEMPLATE.format(position_cn=self._position_cn)

    def build_prompt(self, infoset) -> dict:
        """Convert InfoSet to structured game state for the Cognitive Agent System.

        This is the raw input that the Agent system (L0.5/L1/L2/L3) will
        consume and use to construct its own LLM prompt.

        Returns:
            dict with keys:
                position:       str   - agent role
                hand:           str   - human-readable hand cards
                cards_left:     dict  - {"地主": N, "上家": N, "下家": N}
                last_move:      str   - last played move + who played it
                is_lead:        bool  - True if agent is the round leader
                legal_actions:  list[list[int]] - raw legal actions
                legal_labels:   list[str]       - human-readable labels
                played_cards:   dict  - played cards per position
                bomb_num:       int
                opponents:      dict  - opponent hand cards (only if use_perfect_info)
                history_len:    int   - number of moves so far
        """
        nc = infoset.num_cards_left_dict
        cards_left = {
            "地主":  nc.get("landlord", 0),
            "上家":  nc.get("landlord_up", 0),
            "下家":  nc.get("landlord_down", 0),
        }

        last = infoset.last_move
        if last:
            last_pid = POSITION_CN.get(infoset.last_pid, infoset.last_pid or "")
            last_str = f"{cards_to_str(last)}（由{last_pid}打出）"
        else:
            last_str = "无（你是先手）"

        legal_labels = []
        for i, act in enumerate(infoset.legal_actions, 1):
            label = f"{i}. 不出（过）" if not act else f"{i}. {cards_to_str(act)}"
            legal_labels.append(label)

        played = {}
        for pos, cards in (infoset.played_cards or {}).items():
            played[POSITION_CN.get(pos, pos)] = cards_to_str(cards) if cards else ""

        result = {
            "position":       self._position_cn,
            "position_raw":   self.position,
            "hand":           cards_to_str(infoset.player_hand_cards),
            "hand_raw":       infoset.player_hand_cards,
            "cards_left":     cards_left,
            "last_move":      last_str,
            "is_lead":        not last,
            "legal_actions":  infoset.legal_actions,
            "legal_labels":   legal_labels,
            "played_cards":   played,
            "bomb_num":       getattr(infoset, "bomb_num", 0),
            "history_len":    len(getattr(infoset, "card_play_action_seq", [])),
            "use_perfect_info": self.use_perfect_info,
        }

        if self.use_perfect_info and hasattr(infoset, "all_handcards") and infoset.all_handcards:
            opponents = {}
            for pos, cards in infoset.all_handcards.items():
                if pos != self.position:
                    opponents[POSITION_CN.get(pos, pos)] = cards_to_str(cards)
            result["opponents"] = opponents

        return result

    def build_prompt_test(self, infoset) -> str:
        """Convert InfoSet to a self-contained Chinese prompt (for standalone testing).

        This bypasses the Cognitive Agent System and directly produces a
        human-readable prompt that the LLM can act on immediately.
        """
        hand = cards_to_str(infoset.player_hand_cards)

        nc = infoset.num_cards_left_dict
        left_str = (
            f"地主{nc.get('landlord', '?')}张  "
            f"上家{nc.get('landlord_up', '?')}张  "
            f"下家{nc.get('landlord_down', '?')}张"
        )

        last = infoset.last_move
        if last:
            last_str = cards_to_str(last)
            last_pid = POSITION_CN.get(infoset.last_pid, infoset.last_pid or '')
            last_line = f"{last_str}（由{last_pid}打出）"
        else:
            last_line = '无（你是先手）'

        legal_lines: list[str] = []
        for i, act in enumerate(infoset.legal_actions, 1):
            label = f"{i}. 不出（过）" if not act else f"{i}. {cards_to_str(act)}"
            legal_lines.append(label)

        played_parts: list[str] = []
        for pos, cards in (infoset.played_cards or {}).items():
            if cards:
                played_parts.append(
                    f"{POSITION_CN.get(pos, pos)}:{cards_to_str(cards)}"
                )
        played_str = '  '.join(played_parts) if played_parts else '无'

        bomb_hint = ''
        if hasattr(infoset, 'bomb_num') and infoset.bomb_num:
            bomb_hint = f'\n已出炸弹数：{infoset.bomb_num}'

        perfect_hint = ''
        if self.use_perfect_info and hasattr(infoset, 'all_handcards') and infoset.all_handcards:
            parts = []
            for pos, cards in infoset.all_handcards.items():
                if pos != self.position:
                    parts.append(f"{POSITION_CN.get(pos, pos)}手牌：{cards_to_str(cards)}")
            if parts:
                perfect_hint = '\n对手手牌（完美信息）：\n' + '\n'.join(parts)

        return f"""=== 当前局面 ===
你的身份：{self._position_cn}
你的手牌：{hand}
剩余牌数：{left_str}
上一手：{last_line}

可选出牌：
{chr(10).join(legal_lines)}

已出牌：{played_str}{bomb_hint}{perfect_hint}
请选择（只回复数字或牌面字符串，不出则回"过"）："""

    # ── Response parsing ───────────────────────────────────────

    def parse_action(self, llm_response: str, legal_actions: list[list[int]]) -> list[int]:
        """Parse LLM text response into an action.

        Strategy (in order):
          1. Match numbered choice (e.g. "1", "选择3")
          2. Extract card tokens and match against legal actions
          3. Detect pass keywords ("过", "不出", "pass")
          4. Random legal action as fallback
        """
        text = llm_response.strip()

        # 1. Numbered choice
        match = re.search(r'(\d+)', text)
        if match:
            idx = int(match.group(1))
            if 1 <= idx <= len(legal_actions):
                return legal_actions[idx - 1]

        # 2. Parse card tokens and match
        tokens = _parse_card_tokens(text)
        if tokens:
            tokens_sorted = sorted(tokens)
            for act in legal_actions:
                if sorted(act) == tokens_sorted:
                    return act

        # 3. Pass detection
        _pass_keywords = {'pass', '过', '不出', '不要', '要不起', 'none', 'no'}
        if any(kw in text.lower() for kw in _pass_keywords):
            for act in legal_actions:
                if not act:
                    return act

        # 4. Random fallback
        return random.choice(legal_actions)


# ═══════════════════════════════════════════════════════════════
# DouZeroCognitiveAgent
# ═══════════════════════════════════════════════════════════════


class DouZeroCognitiveAgent:
    """DouZero agent that uses the Cognitive Agent architecture (Executor + LayerChain)."""

    def __init__(self, executor, position: str = 'landlord_up'):
        self._executor = executor
        self.position = position
        self._position_cn = POSITION_CN.get(position, position)

    def act(self, infoset) -> list[int]:
        if len(infoset.legal_actions) == 1:
            return infoset.legal_actions[0]

        obs = TaskObservation(
            meta=DOUDIZHU_GAME_RULES,
            state=self._build_state(infoset),
            session={"domain": "game/doudizhu", "role": self._position_cn},
        )

        result = self._executor.execute(obs)
        action_text = result["action_text"]
        action = self.parse_action(action_text, infoset.legal_actions)
        logger.info("CognitiveAgent action: %s", cards_to_str(action) if action else "pass")
        return action

    def _build_state(self, infoset) -> dict:
        hand = cards_to_str(infoset.player_hand_cards)
        nc = infoset.num_cards_left_dict
        left_str = (
            f"地主{nc.get('landlord', '?')}张  "
            f"上家{nc.get('landlord_up', '?')}张  "
            f"下家{nc.get('landlord_down', '?')}张"
        )

        last = infoset.last_move
        if last:
            last_pid = POSITION_CN.get(infoset.last_pid, infoset.last_pid or '')
            last_str = f"{cards_to_str(last)}（由{last_pid}打出）"
        else:
            last_str = '无（你是先手）'

        legal_lines = []
        for i, act in enumerate(infoset.legal_actions, 1):
            label = f"{i}. 不出（过）" if not act else f"{i}. {cards_to_str(act)}"
            legal_lines.append(label)

        current_text = (
            f"你的身份：{self._position_cn}\n"
            f"你的手牌：{hand}\n"
            f"剩余牌数：{left_str}\n"
            f"上一手：{last_str}\n\n"
            f"可选出牌：\n" + "\n".join(legal_lines)
        )

        history_lines = []
        played = infoset.played_cards or {}
        for pos, cards in played.items():
            if cards:
                history_lines.append(
                    f"{POSITION_CN.get(pos, pos)}已出: {cards_to_str(cards)}"
                )
        history_text = "\n".join(history_lines) if history_lines else ""

        return {
            "current": current_text,
            "history": history_text,
        }

    def parse_action(self, llm_response: str, legal_actions: list[list[int]]) -> list[int]:
        """Reuse DouZeroLLMAgent's parsing logic."""
        dummy = DouZeroLLMAgent.__new__(DouZeroLLMAgent)
        return DouZeroLLMAgent.parse_action(dummy, llm_response, legal_actions)


# ═══════════════════════════════════════════════════════════════
# Quick smoke test
# ═══════════════════════════════════════════════════════════════

class _MockInfoSet:
    """Minimal mock InfoSet for testing without the full DouZero environment."""

    def __init__(self):
        self.player_position = 'landlord_up'
        self.player_hand_cards = [3, 3, 4, 5, 6, 7, 8, 9, 10, 14, 14, 17, 17, 20, 20, 20, 30]
        self.num_cards_left_dict = {'landlord': 20, 'landlord_up': 17, 'landlord_down': 17}
        self.three_landlord_cards = [3, 7, 14]
        self.card_play_action_seq = [[3, 3, 3, 4], [], [5, 5, 5, 6]]
        self.other_hand_cards = []
        self.legal_actions = [
            [],
            [3, 3],
            [4, 5, 6, 7, 8],
            [14, 14],
            [17, 17],
            [20, 30],
        ]
        self.last_move = [5, 5, 5, 6]
        self.last_two_moves = [[], [5, 5, 5, 6]]
        self.last_move_dict = {'landlord': [3, 3, 3, 4], 'landlord_up': [], 'landlord_down': [5, 5, 5, 6]}
        self.played_cards = {'landlord': [3, 3, 3, 4], 'landlord_up': [], 'landlord_down': [5, 5, 5, 6]}
        self.all_handcards = {}
        self.last_pid = 'landlord_down'
        self.bomb_num = 0


if __name__ == '__main__':
    mock = _MockInfoSet()

    import json

    print("=" * 60)
    print(" [1]  build_prompt (结构化, 给 Agent 系统) ")
    print("=" * 60)
    agent_dry = DouZeroLLMAgent(llm_client=None, position='landlord_up')
    structured = agent_dry.build_prompt(mock)
    print(json.dumps(structured, ensure_ascii=False, indent=2, default=str))
    print()

    print("=" * 60)
    print(" [2]  build_prompt_test (自闭环, 直接给 LLM) ")
    print("=" * 60)
    test_prompt = agent_dry.build_prompt_test(mock)
    print(test_prompt)
    print()

    print("=" * 60)
    print(" [3]  cards_to_str ")
    print("=" * 60)
    print("  [3,4,17,20,30]  → ", cards_to_str([3, 4, 17, 20, 30]))

    print()
    print("=" * 60)
    print(" [4]  parse_action  ")
    print("=" * 60)

    legal = mock.legal_actions
    _RANDOM = object()  # sentinel meaning "any random action is fine"

    test_cases = [
        ("1",       legal[0]),      # 1 = pass (first in prompt)
        ("选择2",    legal[1]),      # 2 = 3 3
        ("过",      []),
        ("pass",    []),
        ("不出",    []),
        ("44",      _RANDOM),       # no number in range, no card match → random fallback
        ("8",       _RANDOM),       # idx 8 out of range → random fallback
        ("X D",     legal[5]),      # rocket
        ("XD",      legal[5]),
        ("x d",     legal[5]),
        ("33",      legal[1]),
        ("45678",   legal[2]),      # straight
    ]

    for raw, expected in test_cases:
        result = agent_dry.parse_action(raw, legal)
        if expected is _RANDOM:
            status = "OK"
        elif result == expected:
            status = "OK"
        else:
            status = "FAIL"
        extra = ""
        if status == "FAIL":
            extra = f"  (got {result}, expected {expected})"
        print(f"  {status:4s}  {raw:14s} → {result}{extra}")

    print()
    print("=" * 60)
    print(" [5]  Live LLM inference (if config available) ")
    print("=" * 60)

    try:
        import os
        import yaml
        from openai import OpenAI

        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip()
                if key not in os.environ:
                    os.environ[key] = val

        config_path = Path(__file__).resolve().parent.parent / "config.yaml"
        with open(config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        cfg = raw.get("main_llm", {})
        base_url = cfg.get("base_url", "https://api.deepseek.com")
        api_key = os.environ.get(cfg.get("api_key_env", "DEEPSEEK_API_KEY"), "")
        model = cfg.get("model", "deepseek-v4-flash")

        oai = OpenAI(base_url=base_url, api_key=api_key)
        llm = LLMClient(oai, model)
        if cfg.get("thinking", False):
            llm.thinking_enabled = True

        agent = DouZeroLLMAgent(llm_client=llm, position='landlord_up')
        print(f"  Model: {model}")
        print(f"  Calling act() ...")
        action = agent.act(mock)
        print(f"  → Action: {action}  ({cards_to_str(action) if action else 'pass'})")

    except Exception as e:
        print(f"  Skipped: {e}")
