#!/usr/bin/env python3
"""FastAPI server wrapping Mirage VLM as OpenAI-compatible /v1/chat/completions endpoint.

Usage: mirage_server.py [--port 8092] [--host 127.0.0.1]
"""
import base64
import io
import json
import os
import sys
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

# Lazy import to fail fast if cactus not installed
try:
    import cactus
    MIRAGE_AVAILABLE = True
except ImportError:
    MIRAGE_AVAILABLE = False

app = FastAPI(title="Mirage VLM Server", version="0.1.0")

# Global Mirage instance (lazy init)
_mirage = None

def get_mirage():
    global _mirage
    if _mirage is None:
        if not MIRAGE_AVAILABLE:
            raise RuntimeError("cactus-compute not installed")
        _mirage = cactus.Mirage()
    return _mirage

class ChatCompletionRequest(BaseModel):
    model: str = "mirage"
    messages: list[dict[str, Any]]
    max_tokens: int = 300
    temperature: float = 0.0

class ChatCompletionChoice(BaseModel):
    index: int
    message: dict[str, Any]
    finish_reason: str = "stop"

class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

def extract_image_url(content: list[dict]) -> str | None:
    for item in content:
        if item.get("type") == "image_url":
            url = item.get("image_url", {}).get("url", "")
            if url.startswith("data:"):
                return url
    return None

def decode_image_data_url(data_url: str) -> bytes:
    """Decode base64 image from data URL."""
    if not data_url.startswith("data:"):
        raise ValueError(f"Expected data URL, got: {data_url[:50]}...")
    b64 = data_url.split(",", 1)[1] if "," in data_url else data_url
    return base64.b64decode(b64)

def build_response(caption: str, model: str = "mirage") -> dict:
    return ChatCompletionResponse(
        id=f"chatcmpl-{os.urandom(8).hex()}",
        created=int(os.times().elapsed * 1000) if hasattr(os.times(), 'elapsed') else 0,
        model=model,
        choices=[ChatCompletionChoice(index=0, message={"role": "assistant", "content": caption})]
    ).model_dump()

@app.post("/v1/chat/completions")
async def chat_completions(req: Request):
    try:
        body = await req.json()
        request = ChatCompletionRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Find image in messages
    image_url = None
    prompt_text = ""
    for msg in request.messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                image_url = extract_image_url(content)
                for item in content:
                    if item.get("type") == "text":
                        prompt_text = item.get("text", "")
            elif isinstance(content, str):
                prompt_text = content

    if not image_url:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "No image_url found in request", "type": "invalid_request_error"}}
        )

    try:
        img_bytes = decode_image_data_url(image_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to decode image: {e}")

    try:
        m = get_mirage()
        result = m.describe(img_bytes)
        reasoning = result.get("reasoning", "")
        # Parse "lang: en | description" format
        if "|" in reasoning:
            caption = reasoning.split("|", 1)[1].strip()
        else:
            caption = reasoning.strip() if reasoning else "Image processed."
        if not caption:
            caption = "Image processed."
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Mirage inference error: {e}")

    return build_response(caption, request.model)

@app.get("/health")
async def health():
    return {"status": "ok", "mirage": MIRAGE_AVAILABLE}

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8092)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    
    if not MIRAGE_AVAILABLE:
        print("ERROR: cactus-compute not installed. Run: pip install cactus-compute", file=sys.stderr)
        sys.exit(1)
    
    print(f"Starting Mirage VLM server on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)