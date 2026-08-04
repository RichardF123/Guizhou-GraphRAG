"""Optional speech-to-text adapter for the GraphRAG query pipeline.

The production API can point ASR_URL at an existing speech service. If no
remote service is configured, FunASR is loaded lazily when installed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests


_funasr_model = None


def _extract_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, list):
        for item in payload:
            text = _extract_text(item)
            if text:
                return text
        return ""
    if isinstance(payload, dict):
        for key in ("text", "value", "transcript", "result"):
            text = _extract_text(payload.get(key))
            if text:
                return text
    return ""


def _transcribe_remote(audio_path: str) -> dict:
    url = os.getenv("ASR_URL", "").strip()
    if not url:
        return {}
    with open(audio_path, "rb") as audio:
        response = requests.post(
            url,
            files={"file": (Path(audio_path).name, audio, "audio/wav")},
            data={"language": "zh", "hotwords": os.getenv("ASR_HOTWORDS", "")},
            timeout=float(os.getenv("ASR_TIMEOUT", "120")),
        )
    response.raise_for_status()
    payload = response.json()
    text = _extract_text(payload)
    if not text:
        raise RuntimeError("ASR service returned no transcript")
    return {"text": text, "provider": "remote", "raw": payload}


def _get_funasr_model():
    global _funasr_model
    if _funasr_model is not None:
        return _funasr_model
    try:
        from funasr import AutoModel
    except ImportError as exc:
        raise RuntimeError(
            "未配置 ASR_URL，且本地未安装 FunASR。请安装 backend/requirements-speech.txt。"
        ) from exc
    kwargs = {
        "model": os.getenv("ASR_MODEL", "paraformer-zh"),
        "vad_model": os.getenv("ASR_VAD_MODEL", "fsmn-vad"),
        "punc_model": os.getenv("ASR_PUNC_MODEL", "ct-punc"),
    }
    _funasr_model = AutoModel(**kwargs)
    return _funasr_model


def transcribe_audio(audio_path: str) -> dict:
    """Transcribe Chinese speech and return text plus provider metadata."""
    remote_result = _transcribe_remote(audio_path)
    if remote_result:
        return remote_result
    model = _get_funasr_model()
    result = model.generate(
        input=audio_path,
        language="zh",
        use_itn=True,
        hotword=os.getenv("ASR_HOTWORDS", ""),
    )
    text = _extract_text(result)
    if not text:
        raise RuntimeError("FunASR returned no transcript")
    return {"text": text, "provider": "funasr", "raw": result}
