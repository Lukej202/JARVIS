
"""Coordinate multi-query research through JARVIS's Chrome bridge."""

import json

from jarvis_research_planner import plan_research
from jarvis_extension_bridge import enqueue_research

MAX_QUERIES = 3
MAX_TOTAL_PAGES = 3
JOB_TIMEOUT = 60


def conduct_research(question: str) -> dict:
    """Plan searches, collect webpage evidence, and return a report."""

    plan = plan_research(question)
    queries = plan["queries"][:MAX_QUERIES]

    pages = []
    errors = []
    seen_urls = set()
    stopped = False
    completed_queries = []

    for query in queries:
        if stopped or len(pages) >= MAX_TOTAL_PAGES:
            break

        try:
            result = enqueue_research(
                query,
                max_pages=1,
                timeout=JOB_TIMEOUT,
            )
        except (RuntimeError, TimeoutError, ValueError, OSError) as exc:
            errors.append(f"{query}: {type(exc).__name__}: {exc}")
            # If the extension disconnects, do not launch more jobs.
            if "not connected" in str(exc).lower():
                break
            continue

        completed_queries.append(query)

        for page in result.get("pages", []):
            if not isinstance(page, dict):
                continue

            url = page.get("url", "")
            if not isinstance(url, str) or url in seen_urls:
                continue

            if not page.get("preview"):
                continue

            seen_urls.add(url)
            pages.append(page)

            if len(pages) >= MAX_TOTAL_PAGES:
                break

        errors.extend(str(e)[:220] for e in result.get("errors", [])[:3])

        if result.get("stopped"):
            stopped = True
            break

    return {
        "query": question,
        "objective": plan["objective"],
        "search_queries": queries,
        "completed_queries": completed_queries,
        "pages": pages,
        "errors": errors,
        "stopped": stopped,
    }



if __name__ == "__main__":
    import os
    from jarvis_research_summarizer import summarize_research

    question = input("Research question: ").strip()
    report = conduct_research(question)

    print("\nRESEARCH PLAN")
    print(json.dumps({
        "objective": report["objective"],
        "search_queries": report["search_queries"],
        "completed_queries": report["completed_queries"],
        "errors": report["errors"],
    }, indent=2, ensure_ascii=False))

    if report["pages"]:
        print("\nJARVIS RESEARCH REPORT\n")

        answer = summarize_research(
            report,
            model=os.getenv("JARVIS_MODEL", "qwen3:4b"),
            ollama_api=os.getenv("OLLAMA_API", "http://localhost:11434"),
        )

        print(answer)

        print("\nSOURCES")
        for i, page in enumerate(report["pages"], 1):
            print(f"[{i}] {page['title']} — {page['url']}")
    else:
        print("\nNo readable source pages were retrieved.")

