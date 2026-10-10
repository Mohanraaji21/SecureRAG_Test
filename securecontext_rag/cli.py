"""
Standalone CLI for the Phase 1 AI core -- runs entirely without the
Phase 2 FastAPI layer. Usage:

    python cli.py scan /path/to/repo --repo-name my-org/my-repo

Writes the resulting ScanRun (findings + verdicts) as JSON to stdout, or
to --out if given. This is also how Phase 2 will invoke the core: import
`TriagePipeline` directly rather than shelling out to this script, but
this CLI is useful for local testing and for the eval harness.
"""

from __future__ import annotations

import argparse
import json
import sys

from core.adjudication.ollama_client import DEFAULT_MODEL, DEFAULT_OLLAMA_URL, OllamaClient
from core.calibration.temperature_scaling import TemperatureScaler
from core.pipeline import TriagePipeline
from core.retrieval.faiss_index import KnowledgeIndex, SentenceTransformerEmbedder
from core.retrieval.kb_builder import load_from_json


def build_pipeline(model: str, ollama_url: str) -> TriagePipeline:
    items = load_from_json()
    embedder = SentenceTransformerEmbedder()
    index = KnowledgeIndex.build(items, embedder)
    llm_client = OllamaClient(base_url=ollama_url, model=model)
    return TriagePipeline(knowledge_index=index, llm_client=llm_client, calibrator=TemperatureScaler())


def main() -> None:
    parser = argparse.ArgumentParser(description="SecureContext-RAG AI core CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_parser = sub.add_parser("scan", help="Run Semgrep + adjudication on a repo")
    scan_parser.add_argument("repo_path")
    scan_parser.add_argument("--repo-name", required=True)
    scan_parser.add_argument("--pr-number", type=int, default=None)
    scan_parser.add_argument("--semgrep-config", default="auto")
    scan_parser.add_argument("--model", default=DEFAULT_MODEL)
    scan_parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    scan_parser.add_argument("--out", default=None, help="Output JSON path (default: stdout)")

    args = parser.parse_args()

    if args.command == "scan":
        pipeline = build_pipeline(args.model, args.ollama_url)
        scan_run = pipeline.run_on_repo(
            args.repo_path,
            repo_name=args.repo_name,
            pr_number=args.pr_number,
            semgrep_config=args.semgrep_config,
        )
        output = scan_run.model_dump_json(indent=2)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(output)
        else:
            print(output)


if __name__ == "__main__":
    sys.exit(main() or 0)
