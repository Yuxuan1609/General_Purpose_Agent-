"""Robust JSON parse with multi-tier fallback and schema-aware repair."""
import json
import re
import logging

logger = logging.getLogger(__name__)

_MAX_REPAIR_DEPTH = 20


def robust_parse(text: str, schema: dict | None = None) -> dict:
    """Parse potentially malformed LLM JSON output with multi-tier recovery.

    Args:
        text: Raw LLM output string.
        schema: Optional expected schema dict (like STAGE1_SCHEMA).
                When provided, enables field-level regex extraction as last resort.

    Returns:
        Parsed dict. On total failure returns {"_raw": text}.
    """
    if not text or not isinstance(text, str):
        return {"_raw": str(text) if text else ""}

    text = text.strip()

    # ── Tier 0: direct parse ──
    parsed = _try_json_loads(text)
    if isinstance(parsed, dict):
        return parsed

    # ── Tier 1: extract JSON from markdown/comment wrappers ──
    extracted = _extract_json_block(text)
    if extracted:
        parsed = _try_json_loads(extracted)
        if isinstance(parsed, dict):
            return parsed

    # ── Tier 2: bracket-level repair ──
    repaired = _bracket_repair(text)
    if repaired:
        parsed = _try_json_loads(repaired)
        if isinstance(parsed, dict):
            logger.debug("JSON repaired via bracket fix")
            return parsed

    # ── Tier 3: syntax-level repair (trailing commas, quotes) ──
    cleaned = _syntax_repair(text)
    if cleaned:
        parsed = _try_json_loads(cleaned)
        if isinstance(parsed, dict):
            logger.debug("JSON repaired via syntax fix")
            return parsed

    # ── Tier 4: schema-aware field extraction ──
    if schema:
        salvaged = _schema_salvage(text, schema)
        if salvaged:
            logger.debug("JSON salvaged via schema extraction")
            return salvaged

    # ── Total failure ──
    logger.debug("JSON parse failed after all tiers, returning raw")
    return {"_raw": text}


def _try_json_loads(text: str):
    """Safe json.loads, returns None on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _extract_json_block(text: str) -> str | None:
    """Extract JSON from markdown fences or surrounding text noise."""
    # Strip ```json ... ``` fences
    m = re.search(r'```(?:json)?\s*(.+?)\s*```', text, re.DOTALL)
    if m:
        return m.group(1).strip()

    # Find outermost { } or [ ] pair
    for opener, closer in [('{', '}'), ('[', ']')]:
        start = text.find(opener)
        if start < 0:
            continue
        depth = 0
        end = -1
        for i in range(start, len(text)):
            ch = text[i]
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end > start:
            return text[start:end + 1]

    return None


def _bracket_repair(text: str) -> str | None:
    """Try to fix unbalanced brackets/braces."""
    extracted = _extract_json_block(text)
    if not extracted:
        extracted = text

    stripped = extracted.strip()

    # Missing closing brackets at end
    for try_close in ('}]"', '}]', '}"', ']', '}', '"]', '"}', ']', '}'):
        candidate = stripped + try_close
        if _try_json_loads(candidate):
            return candidate

    # Missing opening bracket at start
    for try_open in ('{"', '{', '['):
        candidate = try_open + stripped
        if _try_json_loads(candidate):
            return candidate

    # Count bracket mismatch and add missing ones
    counts = {'{': 0, '[': 0}
    for ch in stripped:
        if ch == '{':
            counts['{'] += 1
        elif ch == '}':
            counts['{'] -= 1
        elif ch == '[':
            counts['['] += 1
        elif ch == ']':
            counts['['] -= 1

    if counts['{'] > 0 or counts['['] > 0:
        suffix = '}' * max(0, counts['{']) + ']' * max(0, counts['['])
        candidate = stripped + suffix
        if _try_json_loads(candidate):
            return candidate

    if counts['{'] < 0:
        candidate = '{' * abs(counts['{']) + stripped
        if _try_json_loads(candidate):
            return candidate

    return None


def _syntax_repair(text: str) -> str | None:
    """Fix common JSON syntax errors: trailing commas, single quotes, unquoted keys."""
    extracted = _extract_json_block(text)
    if not extracted:
        extracted = text
    s = extracted.strip()

    # Remove trailing commas before } or ]
    s = re.sub(r',\s*([}\]])', r'\1', s)

    # Try converting single-quoted strings to double-quoted
    # Only if the text has single quotes and no double quotes in keys
    if "'" in s:
        s_single_fixed = _fix_single_quotes(s)
        if s_single_fixed != s and _try_json_loads(s_single_fixed):
            return s_single_fixed

    # Try adding quotes around unquoted keys
    s_keys = _fix_unquoted_keys(s)
    if s_keys != s and _try_json_loads(s_keys):
        return s_keys

    if _try_json_loads(s):
        return s

    return None


def _fix_single_quotes(text: str) -> str:
    """Convert single-quoted JSON to double-quoted, handling escaped quotes."""
    # Replace ' with " but not inside already double-quoted strings
    result = []
    in_double = False
    in_single = False
    escaped = False
    for ch in text:
        if escaped:
            result.append(ch)
            escaped = False
            continue
        if ch == '\\':
            result.append(ch)
            escaped = True
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            result.append(ch)
        elif ch == "'" and not in_double:
            in_single = not in_single
            result.append('"')
        else:
            result.append(ch)
    return ''.join(result)


def _fix_unquoted_keys(text: str) -> str:
    """Add double quotes around unquoted JSON object keys."""
    # Match word-like keys followed by : outside strings
    return re.sub(
        r'(?<!\\)(?:^|,)\s*(\w+)\s*:',
        lambda m: m.group(0).replace(m.group(1), f'"{m.group(1)}"'),
        text,
    )


def _schema_salvage(text: str, schema: dict) -> dict | None:
    """Use schema field names to extract values from broken JSON via regex."""
    result = {}

    # Extract top-level keys from schema
    schema_keys = list(schema.keys()) if isinstance(schema, dict) else []

    # Try to extract each key's value using the key name as anchor
    for key in schema_keys:
        val = _extract_field(text, key)
        if val is not None:
            result[key] = val

    if not result:
        return None

    # If we got at least one field, supplement with raw text
    result.setdefault("_raw", text)
    return result


def _extract_field(text: str, key: str):
    """Extract a single field value from broken JSON using the key name."""
    # Pattern: "key": value  where value can be string, number, boolean, array, object
    # Try string value first (most common) — colon required for JSON-like text
    m = re.search(
        rf'["\']?{re.escape(key)}["\']?\s*:\s*"((?:[^"\\]|\\.)*)"',
        text, re.DOTALL,
    )
    if m:
        return m.group(1)

    # Weak pattern: key followed by quoted string (colon optional)
    # Only used as fallback when strict pattern fails
    m = re.search(
        rf'\b{re.escape(key)}\b.*?"((?:[^"\\]|\\.)*)"',
        text, re.DOTALL,
    )
    if m and len(m.group(1).strip()) > 0:
        return m.group(1)

    # Try number value
    m = re.search(
        rf'["\']?{re.escape(key)}["\']?\s*:\s*(-?\d+\.?\d*)',
        text,
    )
    if m:
        val = m.group(1)
        return float(val) if '.' in val else int(val)

    # Try boolean
    m = re.search(
        rf'["\']?{re.escape(key)}["\']?\s*:\s*(true|false)',
        text, re.IGNORECASE,
    )
    if m:
        return m.group(1).lower() == 'true'

    # Try null
    m = re.search(
        rf'["\']?{re.escape(key)}["\']?\s*:\s*(null|None)',
        text, re.IGNORECASE,
    )
    if m:
        return None

    return None
