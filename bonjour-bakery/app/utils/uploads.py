import os
import secrets
from pathlib import Path
from fastapi import UploadFile, HTTPException
from app.config import get_settings

MAX = 3 * 1024 * 1024
SIGS = {b"\x89PNG\r\n\x1a\n": ".png", b"\xff\xd8\xff": ".jpg", b"RIFF": ".webp"}


def upload_root() -> Path:
    p = Path(get_settings().upload_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


async def save_image(file: UploadFile, folder: str) -> str:
    data = await file.read(MAX + 1)
    if len(data) > MAX:
        raise HTTPException(413, "Image is too large (max 3MB).")
    ext = next((e for sig, e in SIGS.items() if data.startswith(sig)), None)
    if ext == ".webp" and data[8:12] != b"WEBP":
        ext = None
    if not ext:
        raise HTTPException(400, "Only PNG, JPEG or WebP images are allowed.")
    d = upload_root() / folder
    d.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(8)}{ext}"
    (d / name).write_bytes(data)
    return f"/uploads/{folder}/{name}"
