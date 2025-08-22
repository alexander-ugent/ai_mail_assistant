import os
import time
import json
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from services.llm import get_llm
from services.email_processor import process_email_non_streaming, process_email_streaming


class ProcessEmailRequest(BaseModel):
    email_id: Optional[str] = None
    subject: str = Field(..., description="Email subject")
    body: str = Field(..., description="Email body, HTML or plain text")
    recipients: Optional[List[str]] = None
    enable_context: bool = False
    provider: str = Field(default="mock")
    model_name: Optional[str] = None


class ProcessEmailResponse(BaseModel):
    summary: str
    action_items: List[str]
    draft_reply_html: str
    citations: List[Dict[str, Any]] = []
    debug: Dict[str, Any] = {}


app = FastAPI(title="AI Mail assistant API", description="Local-first API with mock LLM")

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
    return {"status": "ok", "app": "AI Mail assistant"}


@app.post("/api/v1/process_email_for_addin", response_model=ProcessEmailResponse)
async def process_email_for_addin(payload: ProcessEmailRequest = Body(...)) -> ProcessEmailResponse:
    llm = get_llm(provider=payload.provider, model_name=payload.model_name)
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
    llm = get_llm(provider=payload.provider, model_name=payload.model_name)

    async def streamer() -> AsyncIterator[bytes]:
        yield _sse_format("status_update", {"message": "initialising LLM agent"})
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


