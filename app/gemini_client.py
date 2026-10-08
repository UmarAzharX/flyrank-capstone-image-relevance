from google import genai

from app.config import settings


def create_gemini_client() -> genai.Client:
    api_key = (settings.gemini_api_key or "").strip()

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing from settings")

    return genai.Client(
        api_key=api_key,
        vertexai=False,
    )