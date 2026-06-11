# Output Format Redesign

**Date**: 2026-06-11  
**Status**: pending

## Summary

ENV can ONLY specify stage2 notify format. When specified, L2/L3 produce separate `notify` + `response_to_query` outputs. The ENV-provided JSON schema is used as `robust_parse` salvage parameter.

## Current State

| Item | Status |
|------|--------|
| `_L1/_L2/_L3_OUTPUT` | Dict examples (not JSON schema), used only as format presence markers |
| Format flag effect | `l1_output_format in state` → triggers consolidation path (tool mode, schema=None) |
| stage2 normal mode | 5 schema points, each `_call_llm(schema=X)` → `json.loads(text)` |
| stage2 consolidation | schema=None, tool calls, JSON wrapped as `{"reply": text}` |
| `robust_parse` | Written but not integrated — `core/json_repair.py` |

## Design Rules

### R1: ENV only specifies stage2 notify format

`_L1_OUTPUT` / `_L2_OUTPUT` / `_L3_OUTPUT` become valid JSON Schema objects (`{"type": "object", "properties": {...}, "required": [...]}`) instead of loose dict examples.

```python
# Example for L2:
_L2_OUTPUT = {
    "type": "object",
    "properties": {
        "response": {
            "type": "object",
            "properties": {
                "reply": {"type": "string"},
                "cards": {"type": "array", "items": {"type": "string"}},
                "reasoning": {"type": "string"},
            },
            "required": ["reply", "reasoning"],
        },
        "notify": {
            "type": "object",
            "properties": {
                "l2_modifications": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "target": {"type": "string"},
                            "type": {"type": "string", "enum": ["update", "create", "deprecate"]},
                            "payload": {
                                "type": "object",
                                "properties": {
                                    "content": {"type": "string"},
                                    "reason": {"type": "string"},
                                    "domain": {"type": "string"},
                                },
                                "required": ["content", "reason"],
                            },
                        },
                        "required": ["target", "type"],
                    },
                },
            },
        },
    },
    "required": ["response"],
}
```

**L1 special case**: `notify` field omitted — L1 always single output, response = notify.

### R2: notify and response_to_query separation/merge

| Scenario | L1 | L2/L3 |
|----------|----|-------|
| ENV does **NOT** specify notify format | `{done, result, reasoning}` = notify = response | `{reply, cards, reasoning}` = notify = response |
| ENV **specifies** notify format | `{notify: {done, result, ...}}` (single segment, notify = response) | `{response: {reply, cards, ...}, notify: {l2_modifications: [...]}}` (two separate segments) |

### R3: notify format JSON used for robust_parse

In `_call_llm`, when `state` has `lX_output_format`:
```python
parse_schema = state.get("l2_output_format")
parsed = robust_parse(text, parse_schema)
```

When no format flag, pass the current stage schema (STAGE2_SCHEMA etc.) as salvage schema.

## Change List

| # | File | Change |
|---|------|--------|
| 1 | `core/env/learning_env.py` | Rewrite `_L1/_L2/_L3_OUTPUT` as valid JSON Schema objects |
| 2 | `core/layers/l0_5_1/manager.py` L1Agent | stage2: read `l1_output_format` → build dynamic schema (response+notify or response-only) → pass to `robust_parse` |
| 3 | `core/layers/l2/manager.py` L2Agent | stage2: same as above, notify + response separated |
| 4 | `core/layers/l3/manager.py` L3Agent | execute: same as above, notify + response separated |
| 5 | `core/layers/base.py` `_call_llm` | Integrate `robust_parse(text, schema)` |
| 6 | `core/layers/base.py` notify collection | L2/L3: extract `notify` sub-object when separated; L1: take top-level directly |

## Unchanged

- stage1 logic (unaffected by format flag)
- Consolidation path (tool mode, no JSON parsing)
- `json_repair.py` itself (only call sites change)
- `_parse_notify_layers` (consumes tool results, not LLM JSON output)
- `_parse_notify_llm` (LLM fallback for notification parsing)
