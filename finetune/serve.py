"""Serve the fine-tuned model behind an OpenAI-compatible endpoint.

SatQuery's vision-language model core speaks the OpenAI chat-completions
protocol, so a fine-tuned model plugs in by being served under that protocol
and named in configuration -- no SatQuery code changes::

    python finetune/serve.py --model-dir satquery-qwen2vl-rsvqa --port 8001

    # backend/.env
    SATQUERY_VQA_ENABLED=true
    SATQUERY_VQA_PROVIDER=hosted
    SATQUERY_VQA_BASE_URL=http://127.0.0.1:8001/v1
    SATQUERY_VQA_MODEL=satquery-qwen2vl-rsvqa
    SATQUERY_VQA_BENCHMARK_REPORT=<path>/satquery-qwen2vl-rsvqa/benchmark_report.json

``--model-dir`` is the folder unzipped from the notebook's output: it names
the base model and holds the LoRA adapter. Only what SatQuery sends is
implemented: one user message of text and ``data:`` image URLs, greedy
decoding, ``max_tokens``. A 2B model needs about 5 GB of GPU memory in
float16; ``--load-in-4bit`` brings that to about 2.5 GB (GTX 1650 class,
needs ``bitsandbytes``); without a GPU it runs on the CPU, slowly.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import time
import uuid
from typing import Any

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from peft import PeftModel
from PIL import Image
from transformers import AutoProcessor, Qwen2VLForConditionalGeneration

MAX_NEW_TOKENS = 512


def load(model_dir: str, load_in_4bit: bool) -> tuple[Any, Any, str]:
    with open(os.path.join(model_dir, "served_model.json"), encoding="utf-8") as handle:
        info = json.load(handle)
    cuda = torch.cuda.is_available()
    kwargs: dict[str, Any] = {"torch_dtype": torch.float16 if cuda else torch.float32}
    if cuda:
        kwargs["device_map"] = {"": 0}
    if load_in_4bit:
        from transformers import BitsAndBytesConfig

        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            # The vision encoder is small and sensitive; keep it in float16.
            llm_int8_skip_modules=["visual", "lm_head"],
        )
    base = Qwen2VLForConditionalGeneration.from_pretrained(info["base_model"], **kwargs)
    model = PeftModel.from_pretrained(base, os.path.join(model_dir, "adapter"))
    model.eval()
    processor = AutoProcessor.from_pretrained(info["base_model"])
    processor.tokenizer.padding_side = "left"
    return model, processor, info["served_name"]


def decode_image(url: str) -> Image.Image:
    if not url.startswith("data:") or ";base64," not in url:
        raise HTTPException(400, "Only data: image URLs are accepted.")
    try:
        return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")
    except Exception as error:  # noqa: BLE001 - any undecodable image is the caller's error
        raise HTTPException(400, f"Could not decode the image: {error}") from None


def split_message(messages: list[dict[str, Any]]) -> tuple[str, list[Image.Image]]:
    """The text and images of the last user message."""
    user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
    if user is None:
        raise HTTPException(400, "No user message.")
    content = user.get("content")
    if isinstance(content, str):
        return content, []
    texts, images = [], []
    for part in content or []:
        if part.get("type") == "text":
            texts.append(part.get("text", ""))
        elif part.get("type") == "image_url":
            images.append(decode_image((part.get("image_url") or {}).get("url", "")))
    return "\n".join(texts), images


def create_app(model: Any, processor: Any, served_name: str) -> FastAPI:
    app = FastAPI(title=f"{served_name} (OpenAI-compatible)")

    @app.get("/v1/models")
    def models() -> dict[str, Any]:
        return {"object": "list", "data": [{"id": served_name, "object": "model"}]}

    @app.post("/v1/chat/completions")
    def chat(request: dict[str, Any]) -> dict[str, Any]:
        if request.get("model") not in (None, served_name):
            raise HTTPException(404, f"This server serves '{served_name}', not '{request.get('model')}'.")
        text, images = split_message(request.get("messages") or [])
        conversation = [{
            "role": "user",
            "content": [{"type": "image"} for _ in images] + [{"type": "text", "text": text}],
        }]
        prompt = processor.apply_chat_template(conversation, tokenize=False, add_generation_prompt=True)
        inputs = processor(text=[prompt], images=images or None, return_tensors="pt").to(model.device)
        max_new = min(int(request.get("max_tokens") or MAX_NEW_TOKENS), MAX_NEW_TOKENS)
        with torch.no_grad():
            generated = model.generate(**inputs, max_new_tokens=max_new, do_sample=False)
        answer = processor.batch_decode(
            generated[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True
        )[0].strip()
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": served_name,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
        }

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model-dir", required=True, help="the folder unzipped from the notebook's output")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--load-in-4bit", action="store_true", help="4-bit weights for small GPUs")
    args = parser.parse_args()

    model, processor, served_name = load(args.model_dir, args.load_in_4bit)
    print(f"Serving {served_name} on http://{args.host}:{args.port}/v1 ({model.device})")
    uvicorn.run(create_app(model, processor, served_name), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
