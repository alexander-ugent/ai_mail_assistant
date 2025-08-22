from __future__ import annotations

import os
import re
import json
import asyncio
from typing import Any, AsyncIterator, Dict, List, Optional


class LlmClient:
    """Abstract LLM client interface."""

    def generate(self, email: Dict[str, Any], documents: List[Dict[str, Any]], *, include_citations: bool = True) -> Dict[str, Any]:
        raise NotImplementedError

    async def astream(self, email: Dict[str, Any], documents: List[Dict[str, Any]], *, include_citations: bool = True) -> AsyncIterator[str]:
        raise NotImplementedError


class MockLlmClient(LlmClient):
    """Deterministic mock LLM for local development."""

    def generate(self, email: Dict[str, Any], documents: List[Dict[str, Any]], *, include_citations: bool = True) -> Dict[str, Any]:
        subject = email.get("subject", "(no subject)")
        body = email.get("body", "").strip()

        # Very naive action item extraction: bullet-like lines or imperative sentences
        action_items: List[str] = []
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith(('- ', '* ', '• ')):
                action_items.append(line.lstrip('-*• ').strip())
            elif line.endswith('.') and line[:1].isupper():
                # Take short imperative-looking sentences as action items (heuristic)
                if len(line) <= 120:
                    action_items.append(line)

        if not action_items:
            action_items = [
                "Review the email content and confirm next steps.",
                "Reply with a brief acknowledgment and proposed timeline.",
            ]

        summary = f"Summary of: {subject}"
        draft_reply_html = (
            f"<p>Hi,</p>\n"
            f"<p>Thanks for your email regarding <strong>{subject}</strong>. "
            f"Here's a quick recap and next steps:</p>\n"
            f"<ul>" + ''.join(f"<li>{item}</li>" for item in action_items[:5]) + "</ul>\n"
            f"<p>Best regards,<br/>AI Mail assistant</p>"
        )

        return {
            "summary": summary,
            "action_items": action_items,
            "draft_reply_html": draft_reply_html,
            "citations": [],
            "debug": {"provider": "mock"},
        }

    async def astream(self, email: Dict[str, Any], documents: List[Dict[str, Any]], *, include_citations: bool = True) -> AsyncIterator[str]:
        # Stream a canned message token-by-token
        text = (
            f"Hi, Thanks for your email about {email.get('subject', '(no subject)')}. "
            f"I'll follow up shortly with next steps. Best, AI Mail assistant"
        )
        for token in text.split(' '):
            await asyncio.sleep(0.03)
            yield token + ' '


def _build_prompt(email: Dict[str, Any], documents: List[Dict[str, Any]]) -> str:
    subject = email.get("subject", "(no subject)")
    body = email.get("body", "")
    doc_snippets = "\n".join(
        f"- {d.get('title', 'doc')}: {d.get('snippet', '')[:200]}" for d in (documents or [])
    )
    prompt = (
        "You are an assistant that processes an email and returns a strict JSON object. "
        "Respond with ONLY valid JSON, no code fences. Schema: {\n"
        "  \"summary\": string,\n"
        "  \"action_items\": string[],\n"
        "  \"draft_reply_html\": string\n"
        "}\n\n"
        f"Email subject: {subject}\n"
        f"Email body (HTML or text):\n{body}\n\n"
        f"Context documents (optional):\n{doc_snippets if doc_snippets else '(none)'}\n\n"
        "Rules: concise summary; 2-6 action items; draft_reply_html must be valid HTML; JSON only."
    )
    return prompt


def _parse_generation_to_result(text: str) -> Dict[str, Any]:
    # Try to extract the first JSON object in the text
    try:
        # Fast path: pure JSON
        obj = json.loads(text)
    except Exception:
        # Fallback: find a JSON object with a regex
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            # Last resort: wrap plain text into our schema
            return {
                "summary": "Generated draft",
                "action_items": [],
                "draft_reply_html": f"<p>{text}</p>",
                "citations": [],
                "debug": {"provider": "external", "raw": text[:1000]},
            }
        obj = json.loads(match.group(0))

    summary = obj.get("summary", "")
    action_items = obj.get("action_items", [])
    draft_reply_html = obj.get("draft_reply_html", "")
    if not isinstance(action_items, list):
        action_items = [str(action_items)]
    return {
        "summary": str(summary),
        "action_items": [str(x) for x in action_items],
        "draft_reply_html": str(draft_reply_html),
        "citations": [],
        "debug": {"provider": "external"},
    }


class GeminiLlmClient(LlmClient):
    def __init__(self, model_name: Optional[str] = None) -> None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        try:
            import google.generativeai as genai  # type: ignore
        except Exception as e:
            raise RuntimeError("google-generativeai is not installed. Add it to requirements.") from e
        genai.configure(api_key=api_key)
        self._genai = genai
        self._model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

    def generate(self, email: Dict[str, Any], documents: List[Dict[str, Any]], *, include_citations: bool = True) -> Dict[str, Any]:
        prompt = _build_prompt(email, documents)
        model = self._genai.GenerativeModel(self._model_name)
        resp = model.generate_content(prompt)
        text = getattr(resp, "text", None) or "".join(getattr(resp, "candidates", []) or []) or str(resp)
        result = _parse_generation_to_result(text)
        result.setdefault("debug", {})["provider"] = "gemini"
        result.setdefault("debug", {})["model"] = self._model_name
        return result

    async def astream(self, email: Dict[str, Any], documents: List[Dict[str, Any]], *, include_citations: bool = True) -> AsyncIterator[str]:
        # Gemini SDK supports streaming; provide a simple token stream of the text
        prompt = _build_prompt(email, documents)
        model = self._genai.GenerativeModel(self._model_name)
        try:
            stream = model.generate_content(prompt, stream=True)
            accumulated = ""
            for chunk in stream:
                token = getattr(chunk, "text", "")
                if token:
                    accumulated += token
                    # yield space-separated tokens to align with frontend expectations
                    for t in token.split(" "):
                        if t:
                            yield t + " "
            # small pause to mimic tokenization pacing
            await asyncio.sleep(0)
        except Exception:
            # Fallback: non-streaming
            text = self.generate(email, documents)["draft_reply_html"]
            for t in re.split(r"\s+", re.sub(r"<[^>]+>", " ", text)):
                if t:
                    yield t + " "


class GroqLlmClient(LlmClient):
    def __init__(self, model_name: Optional[str] = None) -> None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        try:
            from groq import Groq  # type: ignore
        except Exception as e:
            raise RuntimeError("groq is not installed. Add it to requirements.") from e
        self._client = Groq(api_key=api_key)
        self._model_name = model_name or os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")

    def _messages(self, prompt: str) -> List[Dict[str, str]]:
        return [{"role": "system", "content": "You are a helpful assistant."}, {"role": "user", "content": prompt}]

    def generate(self, email: Dict[str, Any], documents: List[Dict[str, Any]], *, include_citations: bool = True) -> Dict[str, Any]:
        prompt = _build_prompt(email, documents)
        resp = self._client.chat.completions.create(
            model=self._model_name,
            messages=self._messages(prompt),
            temperature=0.2,
        )
        text = resp.choices[0].message.content or ""
        result = _parse_generation_to_result(text)
        result.setdefault("debug", {})["provider"] = "groq"
        result.setdefault("debug", {})["model"] = self._model_name
        return result

    async def astream(self, email: Dict[str, Any], documents: List[Dict[str, Any]], *, include_citations: bool = True) -> AsyncIterator[str]:
        prompt = _build_prompt(email, documents)
        stream = self._client.chat.completions.create(
            model=self._model_name,
            messages=self._messages(prompt),
            temperature=0.2,
            stream=True,
        )
        for chunk in stream:
            delta = getattr(chunk.choices[0], "delta", None)
            if delta and getattr(delta, "content", None):
                for t in delta.content.split(" "):
                    if t:
                        yield t + " "
            await asyncio.sleep(0)


def get_llm(provider: str = "mock", model_name: Optional[str] = None) -> LlmClient:
    provider = (provider or os.getenv("LLM_PROVIDER", "mock")).lower()
    if provider == "mock":
        return MockLlmClient()
    if provider in {"gemini", "google", "googleai"}:
        return GeminiLlmClient(model_name=model_name)
    if provider == "groq":
        return GroqLlmClient(model_name=model_name)
    # Default to mock with hint
    return MockLlmClient()


