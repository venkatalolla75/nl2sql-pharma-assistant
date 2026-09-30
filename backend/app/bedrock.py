"""Amazon Bedrock (Claude) client wrapper using the Converse API."""

import os

import boto3

from app.prompts import ANSWER_SYSTEM_PROMPT, build_system_prompt

MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
)
REGION = os.environ.get("AWS_REGION", "us-east-1")

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client("bedrock-runtime", region_name=REGION)
    return _client


def _history_to_messages(history: list[dict]) -> list[dict]:
    """history: [{"role": "user"|"assistant", "content": "..."}], most recent last."""
    messages = []
    for turn in history:
        messages.append(
            {"role": turn["role"], "content": [{"text": turn["content"]}]}
        )
    return messages


def generate_sql(question: str, history: list[dict], role: str, full_name: str,
                  territory_name: str | None, region_name: str | None) -> str:
    system_prompt = build_system_prompt(role, full_name, territory_name, region_name)
    messages = _history_to_messages(history) + [
        {"role": "user", "content": [{"text": question}]}
    ]

    resp = _get_client().converse(
        modelId=MODEL_ID,
        system=[{"text": system_prompt}],
        messages=messages,
        inferenceConfig={"maxTokens": 1024, "temperature": 0},
    )
    return resp["output"]["message"]["content"][0]["text"].strip()


def generate_answer(question: str, sql: str, columns: list[str], rows: list[list],
                     access_note: str | None, row_count: int) -> str:
    rows_preview = rows[:50]
    payload = (
        f"Question: {question}\n\n"
        f"SQL executed: {sql}\n\n"
        f"Columns: {columns}\n"
        f"Row count: {row_count}\n"
        f"Rows (up to 50 shown): {rows_preview}\n"
    )
    if access_note:
        payload += f"\nAccess note to weave in naturally: {access_note}\n"

    resp = _get_client().converse(
        modelId=MODEL_ID,
        system=[{"text": ANSWER_SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": payload}]}],
        inferenceConfig={"maxTokens": 512, "temperature": 0.2},
    )
    return resp["output"]["message"]["content"][0]["text"].strip()
