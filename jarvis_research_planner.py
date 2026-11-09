
"""Generate bounded research plans using local Ollama."""

import json
import os
from urllib.request import Request, urlopen

OLLAMA_API = os.getenv("OLLAMA_API", "http://localhost:11434")
MODEL_NAME = os.getenv("JARVIS_MODEL", "qwen3:4b")


def plan_research(question: str) -> dict:
    """Return a validated research plan or a safe fallback."""
    question = question.strip()
    if not 2 <= len(question) <= 220:
        raise ValueError("Research question must be 2–220 characters.")

    fallback = {"objective": question, "queries": [question]}

    system = (
        "You are JARVIS's research planner. "
        "Break the user's research question into up to 3 focused "
        "web search queries that together address the question. "
        "Return only a JSON object with keys 'objective' and 'queries'. "
        "'objective' must be a short string. "
        "'queries' must be an array of 1 to 3 search strings. "
        "Do not answer the question or include explanations."
    )

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }

    try:
        req = Request(
            OLLAMA_API.rstrip("/") + "/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=60) as response:
            result = json.load(response)

        content = result["message"]["content"]
        plan = json.loads(content)

        objective = plan.get("objective")
        queries = plan.get("queries")

        if not isinstance(objective, str) or not objective.strip():
            return fallback
        if not isinstance(queries, list):
            return fallback

        cleaned = []
        for query in queries[:3]:
            if isinstance(query, str) and 2 <= len(query.strip()) <= 220:
                cleaned.append(query.strip())

        if not cleaned:
            return fallback

        return {
            "objective": objective.strip()[:220],
            "queries": cleaned,
        }

    except (KeyError, ValueError, TypeError, OSError):
        return fallback


if __name__ == "__main__":
    question = input("Research question: ")
    print(json.dumps(plan_research(question), indent=2))

