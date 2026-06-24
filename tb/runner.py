"""Monkey-patch entry point for Terminal-Bench with FeedbackHarness.

Usage:
    python -m tb.runner run --agent-import-path tb.agent.cognitive_agent:CognitiveAgent ...

Patches terminal_bench.Harness = FeedbackHarness before CLI import,
then invokes the Typer CLI app (same args as `tb run`).
"""
import sys

import terminal_bench
import terminal_bench.harness.harness as harness_mod

from tb.feedback_harness import FeedbackHarness

terminal_bench.Harness = FeedbackHarness
harness_mod.Harness = FeedbackHarness

from terminal_bench.cli.tb.main import app

if __name__ == "__main__":
    app()
