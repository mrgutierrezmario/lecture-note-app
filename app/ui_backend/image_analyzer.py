"""Last-resort image captioning with a local BLIP model.

Produces a one-line caption, not a transcription — used only when no vision
model (cloud or llava) is available. The model is loaded lazily on first use
and needs ``torch`` and ``transformers``, which the Docker image omits; in
that case ``caption_image`` raises and callers report the missing tier.
"""

import base64
import io
import logging

logger = logging.getLogger(__name__)

MODEL_ID = "Salesforce/blip-image-captioning-base"

_processor = None
_model = None


def _load_model():
    global _processor, _model
    if _model is not None:
        return

    logger.info("Loading BLIP caption model (first use)...")
    import torch
    from transformers import BlipForConditionalGeneration, BlipProcessor

    _processor = BlipProcessor.from_pretrained(MODEL_ID)
    _model = BlipForConditionalGeneration.from_pretrained(MODEL_ID, torch_dtype=torch.float32)
    _model.eval()
    logger.info("BLIP model ready.")


def _caption(image_base64: str) -> str:
    import torch

    data = base64.b64decode(image_base64)
    from PIL import Image

    image = Image.open(io.BytesIO(data)).convert("RGB")

    _load_model()
    inputs = _processor(image, return_tensors="pt")
    with torch.no_grad():
        out = _model.generate(**inputs, max_new_tokens=120)
    return _processor.decode(out[0], skip_special_tokens=True)


async def caption_image(image_base64: str) -> str:
    """Return a text description of the image using local BLIP."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    return await loop.run_in_executor(executor, _caption, image_base64)
