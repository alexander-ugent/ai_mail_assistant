import os
import time
import json
from typing import Any, AsyncIterator, Dict, List, Optional
import logging
from dotenv import load_dotenv, find_dotenv

from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from services.llm import get_llm
from services.email_processor import process_email_non_streaming, process_email_streaming

# Load environment variables from a local .env file (if present)
# Search upwards so running from project root or backend/ both work.
load_dotenv(find_dotenv(), override=False)


class ProcessEmailRequest(BaseModel):
    email_id: Optional[str] = None
    subject: str = Field(..., description="Email subject")
    body: str = Field(..., description="Email body, HTML or plain text")
    recipients: Optional[List[str]] = None
    enable_context: bool = False
    provider: Optional[str] = None  # If omitted, backend will use LLM_PROVIDER from env (defaults to mock)
    model_name: Optional[str] = None


class ProcessEmailResponse(BaseModel):
    summary: str
    action_items: List[str]
    draft_reply_html: str
    citations: List[Dict[str, Any]] = []
    debug: Dict[str, Any] = {}


# Configure module logger (INFO by default)
logger = logging.getLogger("ai_mail_assistant")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(levelname)s:%(name)s:%(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Log key environment selections at startup
logger.info(
    "startup env LLM_PROVIDER=%s GEMINI_MODEL=%s has_key=%s",
    os.getenv("LLM_PROVIDER"),
    os.getenv("GEMINI_MODEL"),
    bool(os.getenv("GEMINI_API_KEY")),
)

app = FastAPI(title="AI Mail Assistant API", description="Local-first API with mock LLM")

origins = [
    "https://localhost:3000",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok", "app": "AI Mail Assistant"}


@app.post("/api/v1/process_email_for_addin", response_model=ProcessEmailResponse)
async def process_email_for_addin(payload: ProcessEmailRequest = Body(...)) -> ProcessEmailResponse:
    env_provider = os.getenv("LLM_PROVIDER")  # no default; allow GEMINI_API_KEY fallback
    selected_input = payload.provider or env_provider
    # Determine effective provider for logging/UI
    if not selected_input and os.getenv("GEMINI_API_KEY"):
        effective_provider = "gemini"
    else:
        effective_provider = (selected_input or "mock").lower()
    selected_model = payload.model_name or (os.getenv("GEMINI_MODEL") if effective_provider == "gemini" else None)
    logger.info(
        "process_email provider_effective=%s model=%s payload_provider=%s env_provider=%s",
        effective_provider,
        selected_model,
        payload.provider,
        env_provider,
    )
    llm = get_llm(provider=(selected_input or ""), model_name=selected_model)
    result = process_email_non_streaming(
        llm=llm,
        email={"subject": payload.subject, "body": payload.body, "recipients": payload.recipients or []},
        enable_context=payload.enable_context,
    )
    return ProcessEmailResponse(**result)


def _sse_format(event: str, data: Dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


@app.post("/api/v1/process_email_for_addin_stream")
async def process_email_for_addin_stream(payload: ProcessEmailRequest = Body(...)) -> StreamingResponse:
    env_provider = os.getenv("LLM_PROVIDER")
    selected_input = payload.provider or env_provider
    if not selected_input and os.getenv("GEMINI_API_KEY"):
        effective_provider = "gemini"
    else:
        effective_provider = (selected_input or "mock").lower()
    selected_model = payload.model_name or (os.getenv("GEMINI_MODEL") if effective_provider == "gemini" else None)
    logger.info(
        "process_email_stream provider_effective=%s model=%s payload_provider=%s env_provider=%s",
        effective_provider,
        selected_model,
        payload.provider,
        env_provider,
    )
    llm = get_llm(provider=(selected_input or ""), model_name=selected_model)

    async def streamer() -> AsyncIterator[bytes]:
        yield _sse_format("status_update", {"message": f"initialising LLM agent ({effective_provider}{(':'+selected_model) if selected_model else ''})"})
        async for chunk in process_email_streaming(
            llm=llm,
            email={"subject": payload.subject, "body": payload.body, "recipients": payload.recipients or []},
            enable_context=payload.enable_context,
        ):
            if chunk.get("event") == "token":
                yield _sse_format("token", {"content": chunk["content"]})
            elif chunk.get("event") == "final":
                yield _sse_format("final", chunk["data"]) 
        yield _sse_format("status_update", {"message": "done"})

    return StreamingResponse(streamer(), media_type="text/event-stream")


@app.get("/test/list_emails")
async def test_list_emails(limit: int = 5) -> Dict[str, Any]:
    emails = [
        {"id": f"demo-{i}", "subject": f"Demo subject {i}", "snippet": "This is a demo message body snippet."}
        for i in range(1, limit + 1)
    ]
    return {"emails": emails}


@app.get("/test/user_details")
async def test_user_details() -> Dict[str, Any]:
    return {
        "display_name": "Demo User",
        "email": "demo.user@example.com",
        "tenant": "local",
    }


@app.post("/api/v1/list_demo_sharepoint_files")
async def list_demo_sharepoint_files() -> Dict[str, Any]:
    # Simple static demo tree
    return {
        "sites": [
            {"id": "site-1", "name": "Legal", "drives": [
                {"id": "drive-1", "name": "Documents", "children": [
                    {"id": "doc-1", "name": "Contract_v1.docx", "type": "file"},
                    {"id": "folder-1", "name": "Case-1234", "type": "folder", "children": [
                        {"id": "doc-2", "name": "Summary.pdf", "type": "file"}
                    ]}
                ]}
            ]}
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)


