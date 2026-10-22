"""Spoken replies with Amazon Polly. Text always works; voice is a bonus and fails quietly."""
from __future__ import annotations

import logging
import os
import re

log = logging.getLogger("hearth.voice")

# Kajal is an Indian-English neural voice; Aditi is the standard fallback.
VOICES = [("Kajal", "neural"), ("Aditi", "standard")]


def available() -> bool:
    """True if boto3 can find AWS credentials (it does not call AWS)."""
    try:
        import boto3
        return boto3.Session().get_credentials() is not None
    except Exception:  # noqa: BLE001
        return False


def language_code(text: str) -> str:
    """hi-IN when the reply is mostly Devanagari, otherwise en-IN. (Kajal and Aditi both speak Hindi and Indian English.)"""
    letters = [c for c in text if c.isalpha()]
    deva = sum("\u0900" <= c <= "\u097f" for c in letters)
    return "hi-IN" if letters and deva / len(letters) > 0.3 else "en-IN"


def speakable(text: str) -> str:
    text = re.sub(r"[*_`#]", "", text)
    return re.sub(r"\s+", " ", text).strip()[:1200]


def speak(text: str) -> tuple[bytes | None, str | None]:
    """Return (mp3 bytes, None) or (None, short reason). Never raises."""
    if not text.strip():
        return None, "nothing to say"
    try:
        import boto3
        polly = boto3.client("polly", region_name=os.getenv("AWS_REGION", "us-east-1"))
    except Exception as err:  # noqa: BLE001
        return None, f"Polly unavailable: {type(err).__name__}"
    last = "no voice worked"
    for voice, engine in VOICES:
        try:
            res = polly.synthesize_speech(Text=speakable(text), OutputFormat="mp3", VoiceId=voice, Engine=engine,
                                          LanguageCode=language_code(text))
            return res["AudioStream"].read(), None
        except Exception as err:  # noqa: BLE001
            last = f"{type(err).__name__}"
            log.warning("Polly voice %s/%s failed: %s", voice, engine, err)
    return None, f"Polly error: {last}"
