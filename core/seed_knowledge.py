"""Seed knowledge — populate initial L2 cards and L3 skills."""
import logging

from core.task import Domain

logger = logging.getLogger(__name__)


def seed_knowledge(fk, phil, sl=None):
    """Seed L2 knowledge cards + L3 skills. L1 rules are managed via l1_rules.json."""

    # L2 knowledge cards — Leduc
    if _count_domain(fk, "game/leduc") == 0:
        _seed_leduc_cards(fk)

    # L2 knowledge cards — DouDizhu
    if _count_domain(fk, "game/doudizhu") == 0:
        _seed_doudizhu_cards(fk)

    # L3 skills
    if sl is not None:
        _seed_l3_skills(sl)

    logger.info("Seeded: L1 rules=%d L2 cards=%d L3 skills=%d",
                len(phil.all_rules()), len(fk.cards),
                len(sl.list_all()) if sl else 0)


def _count_domain(fk, domain_path: str) -> int:
    return sum(1 for c in fk.cards if c.domain.path.startswith(domain_path))


def _seed_leduc_cards(fk):
    cards = [
        ("持有K（最大牌）时翻牌前激进加注。对手Call说明对手有Q或J并赌公共牌。"
         "max 2 raises per round，尽量打满加注次数。", "game/leduc", 0.8),
        ("公共牌与手牌配对时全力加注。翻牌后加注额4筹码。对手未配对时大概率fold。"
         "如对手仍call，说明对手可能也有高牌或已成对。", "game/leduc", 0.85),
        ("翻牌后未成对且手牌为J时，若对手加注应考虑fold。公共牌即使是K，"
         "对手可能已配对或持有更高单张。fold损失已有投入但避免更大损失。", "game/leduc", 0.7),
    ]
    for content, domain, conf in cards:
        fk.add_card(content=content, domain=Domain(domain, "specific"),
                    confidence=conf, source="seed")


def _seed_doudizhu_cards(fk):
    cards = [
        ("作为地主上家，核心职责是顶牌——用较大的单张或对子卡住地主的小牌，"
         "给下家创造跑牌机会。不要只顾自己出完。出单张时尽量出≥10的牌迫使地主消耗大牌。",
         "game/doudizhu", 0.8),
        ("炸弹(4张相同)可管任何牌型，火箭(XD)最大。农民保留炸弹到残局压制地主；"
         "地主尽早用炸弹确立牌权。追踪已出炸弹数判断剩余威胁。",
         "game/doudizhu", 0.85),
    ]
    for content, domain, conf in cards:
        fk.add_card(content=content, domain=Domain(domain, "specific"),
                    confidence=conf, source="seed")


def _seed_l3_skills(sl):
    existing = [s.name for s in sl.list_all()]

    if "leduc-preflop-raise" not in existing:
        sl.create_skill(
            name="leduc-preflop-raise",
            content=LEDUC_PREFLOP_RAISE_SKILL,
            domain=Domain("game/leduc", "specific"),
            created_by="seed",
        )

    if "leduc-postflop-pair" not in existing:
        sl.create_skill(
            name="leduc-postflop-pair",
            content=LEDUC_POSTFLOP_PAIR_SKILL,
            domain=Domain("game/leduc", "specific"),
            created_by="seed",
        )

    if "doudizhu-top-card" not in existing:
        sl.create_skill(
            name="doudizhu-top-card",
            content=DOUDIZHU_TOP_CARD_SKILL,
            domain=Domain("game/doudizhu", "specific"),
            created_by="seed",
        )


LEDUC_PREFLOP_RAISE_SKILL = """---
name: leduc-preflop-raise
domain: game/leduc
---

# Leduc Hold'em Pre-flop Raise Strategy

## When to apply
- You hold K (highest card)
- Opponent has called or raised
- Pre-flop round (before public card revealed)

## Strategy
1. If you hold K, raise aggressively (up to 2 raises per round limit)
2. If opponent re-raises and you hold K, call or re-raise (K is always best pre-flop)
3. If you hold Q, call moderately; raise only against passive opponents
4. If you hold J, call or fold depending on opponent aggression

## Post-flop consideration
- If public card pairs your hand, bet/raise
- If public card is higher than your hand, consider folding to aggression
"""

LEDUC_POSTFLOP_PAIR_SKILL = """---
name: leduc-postflop-pair
domain: game/leduc
---

# Leduc Hold'em Post-flop Paired Strategy

## When to apply
- Public card is dealt
- Your hand card matches the public card (you have a pair)

## Strategy
1. Always bet or raise when paired (you have the best possible non-pair hand)
2. Raise amount: 4 chips in post-flop
3. If opponent re-raises, re-raise again (pair beats any non-pair hand)
4. If opponent calls your raise, they likely also have a pair or are bluffing

## When you are NOT paired
- If public card is higher than your hand, be cautious
- If public card is lower than your hand, moderate betting
- If opponent shows strength, consider folding
"""

DOUDIZHU_TOP_CARD_SKILL = """---
name: doudizhu-top-card
domain: game/doudizhu
---

# Dou Dizhu Top Card Strategy (Landlord's Previous Player)

## Role
As the player before the landlord (地主上家), your primary duty is to block the
landlord's small cards using larger singles or pairs.

## Strategy
1. Play singles ≥10 to force landlord to consume high cards
2. Don't focus on emptying your own hand
3. Create opportunities for your partner (landlord's next player) to run
4. Save bombs for late-game suppression

## Card Strength Reference
- Cards: 3 < 4 < ... < 10 < J < Q < K < A < 2 < X < D
- Bomb (4 of a kind): beats any non-bomb hand
- Rocket (X+D): the ultimate hand
"""
