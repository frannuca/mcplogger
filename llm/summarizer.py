import json
import sys
from typing import Dict, List, Optional

import requests

from config.constants import DEFAULT_LLM_BASE_URL, DEFAULT_OPENAI_MODEL


class LLMSummarizer:
    """
    Calls any OpenAI-compatible chat/completions endpoint.

    Works with:
      • OpenAI cloud  →  base_url="https://api.openai.com/v1"
      • llama.cpp     →  base_url="http://localhost:8080/v1"
                         (start server: llama-server -m model.gguf --port 8080)
      • Ollama        →  base_url="http://localhost:11434/v1"
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_OPENAI_MODEL,
        base_url: str = DEFAULT_LLM_BASE_URL,
    ) -> None:
        self.api_key = api_key or "local"   # llama.cpp ignores the key but needs a non-empty header
        self.model = model
        self.url = f"{base_url.rstrip('/')}/chat/completions"
        _log(f"LLM backend: {self.url}  model: {self.model}")

    # ── public methods ────────────────────────────────────────────────────────

    def summarize_findings(self, findings: Dict) -> str:
        prompt = (
            "You are an SRE assistant. Explain these log findings for a human operator. "
            "You MUST complete every section fully before stopping.\n\n"
            "Write a response with EXACTLY these sections — do not stop until all are complete:\n\n"
            "**Summary:** (one sentence overview)\n\n"
            "**Likely Impact:** (what is affected and how seriously)\n\n"
            "**Root Causes:** (top 2-3 probable causes)\n\n"
            "**Next Debugging Steps:**\n"
            "1. (specific command or action)\n"
            "2. (specific command or action)\n"
            "3. (specific command or action)\n\n"
            "Interpret any quantitative request in the prompt (e.g. percentage of errors).\n\n"
            "---\n"
            f"Findings JSON:\n{json.dumps(findings, indent=2)}"
        )
        return self._call(prompt)

    def summarize_search(
        self,
        prompt_text: str,
        matches: List[str],
        total_matches: int = 0,
        total_lines: int = 0,
    ) -> str:
        pct = f"{total_matches / total_lines * 100:.2f}%" if total_lines > 0 else "unknown"
        stats = (
            f"Total lines in log: {total_lines}\n"
            f"Lines matching this query: {total_matches} ({pct} of all lines)"
        )
        prompt = (
            "You are helping investigate production incidents. "
            "You MUST complete every section fully before stopping.\n\n"
            "Using the operator's question, the statistics, and the matching log lines below, "
            "write a response with EXACTLY these three sections — do not stop until all three are complete:\n\n"
            "**Likely Issue:** (one sentence describing the root cause)\n\n"
            "**Confidence:** (High / Medium / Low — explain why in one sentence)\n\n"            
            "IMPORTANT: the operator may be asking a quantitative question (e.g. 'how many', "
            "'what percentage'). Use the statistics section to answer it directly.\n\n"
            "---\n"
            f"Operator question: {prompt_text}\n\n"
            f"Statistics:\n{stats}\n\n"
            f"Sample matching log lines ({len(matches)} shown):\n{json.dumps(matches, indent=2)}"
        )
        return self._call(prompt)

    # ── internals ─────────────────────────────────────────────────────────────

    def _call(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You explain production issues in clear plain language. Always complete every section of your response fully."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 2048,   # prevent truncation on local models
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        resp = requests.post(self.url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]

        # warn if the model stopped because it hit max_tokens
        finish_reason = choice.get("finish_reason", "")
        if finish_reason == "length":
            _log("WARNING: response was truncated (finish_reason=length). "
                 "Increase max_tokens in llm/summarizer.py if answers are cut off.")

        return choice["message"]["content"].strip()


# backward-compat alias so old imports don't break immediately
ChatGPTSummarizer = LLMSummarizer


def _log(msg: str):
    print(f"[summarizer] {msg}", file=sys.stderr, flush=True)
