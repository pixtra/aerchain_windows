"""Aerchain AerBot — real-model tool-calling agent over the Decision-Ready layer.

The model decides intent, chooses tools, and writes the answer; the tools (in
tools.py) and the serialization (domain_serialize.py) are deterministic, so the
model can only quote exact computed values. No regex intent guessing, no
template narratives.
"""

from . import tools
from .agent import run, status
from .explainer import answer, render_markdown
from .llm import ModelNotConfigured

__all__ = ["tools", "run", "status", "answer", "render_markdown",
           "ModelNotConfigured"]