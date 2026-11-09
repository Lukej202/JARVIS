
"""Test JARVIS's complete research pipeline."""

import json

from jarvis_research import conduct_research
from jarvis_research_summarizer_v2 import (
    extract_evidence,
    evaluate_evidence,
    generate_final_report,
)


def main():
    question = input("Research question: ").strip()

    # Stage 1: Plan research and collect webpages.
    report = conduct_research(question)

    print(f"\nResearch objective: {report['objective']}")
    print(f"Completed searches: {len(report['completed_queries'])}")
    print(f"Sources retrieved: {len(report['pages'])}")

    all_findings = []

    # Stage 2: Extract and evaluate evidence.
    for source_id, page in enumerate(report["pages"], 1):
        print(f"\nAnalyzing source [{source_id}]: {page['title']}")

        try:
            findings = extract_evidence(question, page, source_id)
            evaluated = evaluate_evidence(question, findings)

            all_findings.extend(evaluated)

            for finding in evaluated:
                print(f"\nClaim: {finding['claim']}")
                print(f"Verdict: {finding['verdict']}")
                print(f"Reason: {finding['reason']}")

        except Exception as exc:
            print(f"Source processing failed: {type(exc).__name__}: {exc}")

    # Stage 3: Summarize the evaluation results.
    supported = [
        finding for finding in all_findings
        if finding["verdict"] == "supported"
    ]

    rejected = [
        finding for finding in all_findings
        if finding["verdict"] != "supported"
    ]

    print("\nEVIDENCE SUMMARY")
    print(f"Total findings: {len(all_findings)}")
    print(f"Supported: {len(supported)}")
    print(f"Rejected or uncertain: {len(rejected)}")

    # Stage 4: Generate the final report.
    print("\n" + "=" * 60)
    print("JARVIS FINAL RESEARCH REPORT")
    print("=" * 60 + "\n")

    final_answer = generate_final_report(question, all_findings)

    print(final_answer)

    # Stage 5: Display actual retrieved sources.
    print("\nSOURCES")

    for index, page in enumerate(report["pages"], 1):
        print(f"[{index}] {page['title']}")
        print(f"    {page['url']}")


if __name__ == "__main__":
    main()
