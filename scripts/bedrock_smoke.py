"""Bounded live Converse smoke; no provider writes and no credential output."""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from donewise_harness.contracts import TOOL_SPECS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="donewise")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--models",
        nargs="+",
        default=[
            "us.openai.gpt-5.6-terra",
            "us.amazon.nova-pro-v1:0",
            "us.anthropic.claude-sonnet-4-6",
            "openai.gpt-oss-120b-1:0",
        ],
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; preserve previous evidence")
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    if session.client("sts").get_caller_identity()["Account"] != "027018013541":
        raise RuntimeError("Refusing to use an account other than DoneWise")
    client = session.client(
        "bedrock-runtime",
        config=Config(
            connect_timeout=10,
            read_timeout=120,
            retries={"total_max_attempts": 1},
        ),
    )
    tools = [
        {
            "toolSpec": {
                "name": spec.name,
                "description": spec.description,
                "inputSchema": {"json": spec.input_model.model_json_schema()},
            }
        }
        for spec in TOOL_SPECS
    ]
    rows = []
    for model in args.models:
        for kind in ("text", "tools"):
            request = {
                "modelId": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "text": (
                                    "Reply with the single word OK"
                                    if kind == "text"
                                    else "Call receipts_recap with {} for saved receipts. "
                                    "Do not call write or approval tools."
                                )
                            }
                        ],
                    }
                ],
                "inferenceConfig": {"maxTokens": 1200},
            }
            if kind == "tools":
                request["toolConfig"] = {"tools": tools}
            row = {"model": model, "kind": kind, "parameters": request["inferenceConfig"]}
            start = time.perf_counter()
            try:
                response = client.converse(**request)
                row.update(
                    output=response["output"],
                    stop_reason=response["stopReason"],
                    usage=response.get("usage"),
                    request_id=response["ResponseMetadata"]["RequestId"],
                )
                content = response["output"]["message"]["content"]
                row["passed"] = (
                    any(b.get("text", "").strip() == "OK" for b in content)
                    if kind == "text"
                    else any(b.get("toolUse", {}).get("name") == "receipts_recap" for b in content)
                    and response["stopReason"] == "tool_use"
                )
            except ClientError as exc:
                row.update(error=exc.response["Error"], passed=False)
            row["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 2)
            rows.append(row)
            print(json.dumps(row), flush=True)
            if row.get("error"):
                break  # No redundant second call against an access-denied model.
    client.close()
    evidence = {
        "observed_at": datetime.now(UTC).isoformat(),
        "region": args.region,
        "profile": args.profile,
        "tool_names": [s.name for s in TOOL_SPECS],
        "results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
