"""Speech-to-text via hosted Whisper (Groq OpenAI-compatible endpoint).

Transcription only — it generates no answers. Audio is sent once and never
stored. Returns (text, error); never raises to the UI.
"""
from __future__ import annotations

import io
import re

from .config import settings

# ISO-639-1 hints for Whisper
_LANG_HINT = {"en": "en", "hi": "hi", "kn": "kn", "ta": "ta", "ml": "ml"}

# domain vocabulary nudges Whisper toward RideWise terms / ID shapes
_DOMAIN_PROMPT = (
    "RideWise two-wheeler and EV rental support. Booking IDs look like B-0001; "
    "customer IDs like CUST0001; payment IDs like PAY00001; vehicle IDs like VEH001. "
    "Terms: refund, cancellation, late return fee, penalty, deposit, GST, low battery, "
    "KYC, GOLD/SILVER/STANDARD tier. Hubs: Koramangala, Indiranagar, Jayanagar, "
    "HSR Layout, Electronic City, Whitefield, Hebbal."
)

# native-script digits -> ASCII
_DIGIT_MAP = {}
for base in (0x0966, 0x0CE6, 0x0BE6, 0x0D66):  # Devanagari, Kannada, Tamil, Malayalam
    for i in range(10):
        _DIGIT_MAP[chr(base + i)] = str(i)
_DIGIT_TABLE = {ord(k): v for k, v in _DIGIT_MAP.items()}


def _normalise(text: str) -> str:
    t = (text or "").strip().translate(_DIGIT_TABLE)
    # "B 1709" / "B-1709" / "b 1709" -> "B-1709"; same for other prefixes
    t = re.sub(r"\b([Bb])[\s-]?(\d{3,4})\b", lambda m: f"B-{int(m.group(2)):04d}", t)
    t = re.sub(r"\b(cust)[\s-]?(\d{1,4})\b", lambda m: f"CUST{int(m.group(2)):04d}", t, flags=re.I)
    t = re.sub(r"\b(pay)[\s-]?(\d{1,5})\b", lambda m: f"PAY{int(m.group(2)):05d}", t, flags=re.I)
    t = re.sub(r"\b(veh)[\s-]?(\d{1,3})\b", lambda m: f"VEH{int(m.group(2)):03d}", t, flags=re.I)
    t = re.sub(r"\b(dmg)[\s-]?(\d{1,4})\b", lambda m: f"DMG{int(m.group(2)):04d}", t, flags=re.I)
    return t


def transcribe(audio_bytes: bytes, language: str = "en",
               filename: str = "audio.wav") -> tuple[str, str | None]:
    if not settings.stt_configured():
        return "", "voice input is disabled"
    if not audio_bytes:
        return "", "no audio received"
    try:
        from openai import OpenAI
        client = OpenAI(base_url=settings.stt_base_url, api_key=settings.groq_api_key,
                        timeout=30)
        buf = io.BytesIO(audio_bytes)
        buf.name = filename
        kwargs = {"model": settings.stt_model, "file": buf, "prompt": _DOMAIN_PROMPT}
        hint = _LANG_HINT.get(language)
        if hint:
            kwargs["language"] = hint
        resp = client.audio.transcriptions.create(**kwargs)
        text = getattr(resp, "text", "") or ""
        return _normalise(text), None
    except Exception as e:  # noqa: BLE001
        return "", f"transcription failed: {e}"
