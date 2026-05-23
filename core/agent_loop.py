from __future__ import annotations
import json
import logging
from core.task import Task, TaskResult

logger = logging.getLogger(__name__)


class AgentLoop:
    def __init__(self, llm_client, tool_registry, layers, max_iterations: int = 50):
        self.llm = llm_client
        self.tools = tool_registry
        self.layers = layers
        self.max_iterations = max_iterations

    def run(self, task: Task) -> tuple[list, TaskResult]:
        """Execute phase only. Returns (messages_log, raw_result)."""
        messages = []
        iteration = 0
        self.layers.meta.reset_turn_state()

        system_prompt = self._build_system_prompt(task)
        messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": task.description})

        raw_result = TaskResult()

        while iteration < self.max_iterations:
            iteration += 1

            context_block = self.layers.build_context(task)
            if context_block:
                messages[-1]["content"] += "\n\n" + context_block

            try:
                response = self._call_llm(messages)
            except Exception as e:
                logger.warning("LLM call failed (iteration %s): %s", iteration, e)
                continue

            if response.has_tool_calls:
                filtered = self.layers.filter_tool_calls(response.tool_calls)

                assistant_msg = {
                    "role": "assistant",
                    "content": response.text or "",
                    "tool_calls": [
                        {
                            "id": f"call_{i}",
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": getattr(tc.function, 'arguments', '{}'),
                            }
                        }
                        for i, tc in enumerate(filtered)
                    ]
                }
                messages.append(assistant_msg)

                tool_results = []
                for i, tc in enumerate(filtered):
                    try:
                        args = json.loads(getattr(tc.function, 'arguments', '{}'))
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    raw_result_text = self.tools.dispatch(tc.function.name, args)
                    messages.append({
                        "role": "tool",
                        "name": tc.function.name,
                        "content": raw_result_text,
                        "tool_call_id": f"call_{i}",
                    })
                    tool_results.append((tc.function.name, raw_result_text))

                self.layers.on_tool_results(task, tool_results)
            else:
                messages.append({"role": "assistant", "content": response.text or ""})
                verdict = self.layers.check_completion(task, messages)
                if verdict == "done":
                    break

        raw_result.iterations_used = iteration
        raw_result.final_response = messages[-1].get("content", "") if messages else ""
        return messages, raw_result

    def reflect(self, task: Task, messages: list, raw_result: TaskResult) -> TaskResult:
        """Reflect & Learn phase. Calls post_task on layers."""
        result = self.layers.post_task(task, messages)
        result.iterations_used = raw_result.iterations_used
        result.final_response = raw_result.final_response
        result.eval_result = raw_result.eval_result
        result.eval_score = raw_result.eval_score
        result.success = raw_result.success or result.success
        return result

    def execute_and_reflect(self, task: Task) -> TaskResult:
        """Convenience: run + reflect in one call for backward compat."""
        messages, raw_result = self.run(task)
        return self.reflect(task, messages, raw_result)

    def _call_llm(self, messages):
        resp = self.llm.chat(
            messages=messages,
            tools=self.tools.schemas if hasattr(self.tools, 'schemas') else None,
        )
        if not hasattr(resp, 'has_tool_calls'):
            resp.has_tool_calls = False
            resp.text = str(resp)
        return resp

    def _build_system_prompt(self, task: Task) -> str:
        parts = [
            "You are a cognitive AI agent with a layered learning architecture. "
            "You can use tools to interact with your environment and create "
            "skills from successful patterns.",
            f"Current domain: {task.domain.path}",
        ]
        if hasattr(self.layers, 'l1') and self.layers.l1:
            rules = self.layers.l1.all_rules()
            if rules:
                parts.append(
                    "[Behavioral Principles — Your Philosophy]\n" +
                    "\n".join(f"- {r.content}" for r in rules) +
                    "\n\nThese principles guide your behavior. You may propose "
                    "additions or modifications through reflection after tasks."
                )
        parts.append(
            "Available tools: skills_list, skill_view, skill_manage, todo, terminal. "
            "Use skills_list() to see what skills are available. "
            "Use skill_view('skill-name') to load a skill's full content before using it."
        )
        return "\n\n".join(parts)
