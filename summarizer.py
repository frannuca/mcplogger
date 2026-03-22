import json
import sys
from typing import Dict, List, Optional

import requests

from constants import DEFAULT_LLM_BASE_URL, DEFAULT_OPENAI_MODEL


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
            "Include likely impact, potential root causes, and concrete next debugging steps. "
            "Keep it concise and practical.\n\n"
            f"Findings JSON:\n{json.dumps(findings, indent=2)}"
        )
        return self._call(prompt)

    def summarize_search(self, prompt_text: str, matches: List[str]) -> str:
        prompt = (
            "You are helping investigate production incidents. "
            "Given the operator's question and matching log lines, provide the likely issue, "
            "confidence, and next checks to run. Keep it concise.\n\n"
            f"Question:\n{prompt_text}\n\n"
            f"Matching lines (max {len(matches)}):\n{json.dumps(matches, indent=2)}"
        )
        return self._call(prompt)

    # ── internals ─────────────────────────────────────────────────────────────

    def _call(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You explain production issues in clear plain language."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        resp = requests.post(self.url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


# backward-compat alias so old imports don't break immediately
ChatGPTSummarizer = LLMSummarizer


def _log(msg: str):
    print(f"[summarizer] {msg}", file=sys.stderr, flush=True)
