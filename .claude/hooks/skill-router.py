#!/usr/bin/env python3
"""
UserPromptSubmit hook — detects task intent and injects the relevant skill name
into Claude's context before it responds. Fixes unreliable auto-invocation.

Skills only match probabilistically from descriptions alone. This hook does
deterministic keyword matching and uses additionalContext to tell Claude
which skill to invoke — before it starts coding.
"""
import json
import re
import sys

data = json.load(sys.stdin)
prompt = data.get("user_input", "").lower()

# Rules: (regex pattern, skill slash-command)
# Patterns are intentionally broad to catch FR/EN variants
RULES = [
    # Agent tools
    (r"\b(add|cr[eé][eé]?r?|nouveau|new|nouvel)\b.{0,30}\b(tool|outil|agent.?tool)", "/add-agent-tool"),
    (r"\b(tool|outil)\b.{0,20}\b(agent|ollama)", "/add-agent-tool"),
    # REST routes / endpoints
    (r"\b(add|cr[eé][eé]?r?|nouveau|new)\b.{0,30}\b(route|endpoint|api|router)", "/add-route"),
    (r"\b(endpoint|route\s+rest|fastapi\s+route)", "/add-route"),
    # Labs architectures
    (r"\b(add|cr[eé][eé]?r?|nouveau|new)\b.{0,30}\b(arch|architecture|model|r[eé]seau|network|cnn|rnn|lstm|gru|transformer|vit)\b", "/add-arch"),
    (r"\b(architecture|arch)\b.{0,20}\b(labs|train)", "/add-arch"),
    # Tests
    (r"\b(test|tests|pytest|coverage|couverture|tester|run.?test)", "/test"),
    # Architecture / understanding the project
    (r"\b(o[uù]\s+est|where.?is|trouve|find|structure|carte|map|flux|flow|architecture|comment.?march|how.?work|comprendre|understand)\b", "/architecture"),
    (r"\b(quel.?fichier|which.?file|dans.?quel)", "/architecture"),
]

matched = []
seen = set()
for pattern, skill in RULES:
    if skill not in seen and re.search(pattern, prompt):
        matched.append(skill)
        seen.add(skill)

context = ""
if matched:
    skills_str = ", ".join(matched)
    context = (
        f"[Skill router] Relevant skill(s) detected: {skills_str}. "
        f"Invoke the skill before implementing — it contains the exact template and wiring steps."
    )

output: dict = {
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
    }
}
if context:
    output["hookSpecificOutput"]["additionalContext"] = context

print(json.dumps(output))
sys.exit(0)
