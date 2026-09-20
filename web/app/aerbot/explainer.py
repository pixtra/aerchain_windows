"""Answer synthesis — the real-model agent output, rendered to markdown.

The narrative is produced by the model from real tool outputs (agent.run),
never templated. render_markdown only wraps the model's structured answer for
display, so numbers pass through untouched.
"""
from __future__ import annotations

from . import agent


def render_markdown(ans: dict) -> str:
    lines = [f"### {ans['title']}", "", ans["narrative"]]
    table = ans.get("table") or []
    if table:
        keys = list(table[0].keys())
        head = " | ".join(str(k).replace("_", " ").title() for k in keys)
        lines.append(f"\n| {head} |")
        lines.append(f"|{'---|' * len(keys)}")
        for row in table:
            cells = [" " + str(row.get(k, "")) for k in keys]
            lines.append("|" + "|".join(cells) + "|")
    for label, key in (("Assumptions", "assumptions"),
                       ("What this excludes / could not determine", "exclusions"),
                       ("Uncertainty surfaced", "uncertainties")):
        items = ans.get(key) or []
        if items:
            lines.append(f"\n**{label}**\n" + "".join(f"\n- {i}" for i in items))
    ev = ans.get("evidence") or []
    if ev:
        lines.append("\n**Evidence traced**\n" + "".join(
            f"\n- {e['source_file']} ({e.get('location', '')}) {e.get('confidence', '')}"
            for e in ev))
    return "\n".join(lines)


def answer(question: str, chat_fn=None, history: list[dict] | None = None) -> dict:
    ans = agent.run(question, chat_fn=chat_fn, history=history)
    ans["markdown"] = render_markdown(ans)
    return ans