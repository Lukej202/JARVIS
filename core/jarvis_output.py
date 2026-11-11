"""Clean local model output before displaying it to JARVIS users.

This filters textual reasoning tags; it does NOT change Ollama's internal
reasoning generation or guarantee that arbitrary untagged reasoning is absent.
"""
import re

_TAG = r"<\s*/?\s*(?:think|thinking|analysis)\s*>"
_COMPLETE = re.compile(r"<\s*(?:think|thinking|analysis)\s*>.*?<\s*/\s*(?:think|thinking|analysis)\s*>", re.I | re.S)
_START = re.compile(r"<\s*(?:think|thinking|analysis)\s*>", re.I)
_CLOSE = re.compile(r"<\s*/\s*(?:think|thinking|analysis)\s*>", re.I)


def clean_model_output(value: object) -> str:
    """Remove visible model reasoning markup, preserving final answer text.

    Some Ollama models omit the opening <think> but emit a closing </think>.
    In that case, discard the preamble preceding the first closing tag.
    """
    text = str(value or "").strip()
    # Some output paths add an escape before closing-tag slashes.
    text = re.sub(r"<\s*\\/", "</", text)
    text = _COMPLETE.sub("", text)
    # Unterminated opening reasoning tag: hide it and everything after it.
    opening = _START.search(text)
    if opening:
        text = text[:opening.start()]
    # Orphaned closing tag after an untagged reasoning preamble.
    closing = _CLOSE.search(text)
    if closing:
        text = text[closing.end():]
    text = text.strip()
    return text if text else "I couldn't produce a final answer. Please try again."
