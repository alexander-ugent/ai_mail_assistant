from __future__ import annotations

import time
from typing import Any, AsyncIterator, Dict, List

from .llm import LlmClient


def process_email_non_streaming(*, llm: LlmClient, email: Dict[str, Any], enable_context: bool = False) -> Dict[str, Any]:
    start = time.time()
    documents: List[Dict[str, Any]] = []
    # Context is not implemented; keep it empty and deterministic
    result = llm.generate(email=email, documents=documents)
    result.setdefault("debug", {})["processing_time"] = round(time.time() - start, 3)
    return result


async def process_email_streaming(*, llm: LlmClient, email: Dict[str, Any], enable_context: bool = False) -> AsyncIterator[Dict[str, Any]]:
    # Yield token events, then a final result
    async for token in llm.astream(email=email, documents=[]):
        yield {"event": "token", "content": token}
    final = llm.generate(email=email, documents=[])
    yield {"event": "final", "data": final}


