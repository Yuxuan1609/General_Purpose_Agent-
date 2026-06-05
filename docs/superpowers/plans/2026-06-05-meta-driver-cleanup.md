# MetaDriver 旧反射代码清理计划

## 背景

Phase 2.3 清理了旧 ReflectionAgent/ReflectCoordinator 系统，但 `core/meta_driver.py` 中仍残留旧反射触发基础设施。

## 删除清单

### core/meta_driver.py 中删除

| 符号 | 原因 |
|------|------|
| `TriggerType` (Enum) | 仅 `ReflectionTrigger` 使用 |
| `ReflectionTrigger` | 旧触发评估器，无活跃调用者 |
| `DEFAULT_TRIGGERS` | 4 个旧触发器集合 |
| `_check_stagnation` / `_check_task_failure` | 仅 DEFAULT_TRIGGERS 使用 |
| `TASK_COMPLETED_LLM_PROMPT` / `DOMAIN_SHIFT_LLM_PROMPT` | 仅 DEFAULT_TRIGGERS 使用 |
| `ReflectionResult` | 旧反射产出，无活跃调用者 |
| `MetaDriver.evaluate_triggers()` | 无活跃调用者（仅测试） |
| `MetaDriver.run_reflection()` / `_llm_reflection()` | 无活跃调用者 |
| `MetaDriver._summarize_messages()` | 仅 `_llm_reflection` 使用 |
| `MetaDriver.reset_turn_state()` | 无活跃调用者 |
| `MetaDriver.track_progress()` | 无活跃调用者 |
| `MetaDriver.task_decompose_trigger()` | 空 stub |

### MetaDriver.__init__ 修改

- 移除 `triggers` 参数，保留 `validation_rules`, `auxiliary_llm`, `max_rules`, `max_rule_length`
- 移除 `self.triggers`, `self._turn_state`

### 受影响的调用者 (均需移除 `DEFAULT_TRIGGERS` 导入和参数)

| 文件 | 变更 |
|------|------|
| `scripts/run_leduc_cognitive.py` | 移除 `DEFAULT_TRIGGERS` import + 参数 |
| `scripts/run_learning_dryrun.py` | 同上 |
| `scripts/run_douzero_llm.py` | 同上 |
| `scripts/smoke_test_managers.py` | 同上 |
| `tests/test_meta_driver.py` | 移除 `TestReflectionTrigger` 类 + 相关 fixture/test |
| `tests/test_layers.py` | 移除 `DEFAULT_TRIGGERS` import + 参数 |
| `tests/test_integration_cognitive.py` | 同上 |

### 保留不变

- `ValidationRule` + `DEFAULT_VALIDATORS`
- `MetaDriver.validate_l1_change()` / `filter_dangerous()` / `check_completion()`
- `L1ProposalProxy`

## 验证

```bash
pytest tests/ -v
```
