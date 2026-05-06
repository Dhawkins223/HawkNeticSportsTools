from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from app.config import settings
from app.repositories import ConversationRepository, FindingsRepository


@dataclass
class AIResult:
    content: str
    provider: str
    model: str
    conversation_id: int


class AIService:
    @staticmethod
    async def explain_finding(user_id: int, prompt: str, conversation_id: int | None = None) -> AIResult:
        if conversation_id is None:
            conversation_id = ConversationRepository.create(
                user_id=user_id,
                title=prompt[:60] if prompt else "New conversation",
                provider="openai" if settings.openai_api_key else "local",
                model=settings.openai_model if settings.openai_api_key else "rule-engine",
            )

        ConversationRepository.add_message(conversation_id, "user", prompt)

        if settings.openai_api_key:
            content = await AIService._call_openai(prompt=prompt)
            provider = "openai"
            model = settings.openai_model
        else:
            content = AIService._local_explainer(prompt)
            provider = "local"
            model = "rule-engine"

        ConversationRepository.add_message(conversation_id, "assistant", content)
        FindingsRepository.create(user_id=user_id, title=prompt[:80] or "Finding", body=content)
        return AIResult(content=content, provider=provider, model=model, conversation_id=conversation_id)

    @staticmethod
    async def _call_openai(prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.openai_model,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You are HawkNetic's analyst explainer. Be precise, concise, and practical. "
                                "If data is missing, say so plainly. Focus on what the user can act on next."
                            ),
                        }
                    ],
                },
                {"role": "user", "content": [{"type": "input_text", "text": prompt}]},
            ],
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post("https://api.openai.com/v1/responses", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        if "output_text" in data and data["output_text"]:
            return data["output_text"]
        # Fall back to safely extracting text blocks if the API shape varies.
        outputs = data.get("output", [])
        parts: list[str] = []
        for item in outputs:
            for content in item.get("content", []):
                text = content.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip() or "The AI call completed but returned no text."

    @staticmethod
    def _local_explainer(prompt: str) -> str:
        lowered = prompt.lower()
        if "subscription" in lowered or "cancel" in lowered:
            bullets = [
                "Current account flows support self-serve cancellation from the account page.",
                "Every subscription action is audited so support can reconstruct what happened.",
                "Move paid production traffic to Stripe only after your live keys are in place.",
            ]
        elif "bet" in lowered or "edge" in lowered or "finding" in lowered:
            bullets = [
                "Treat this as a structured finding, not a promise of profit.",
                "Check whether the evidence is current, whether the uncertainty is explicit, and whether the user can act on it.",
                "Write the result into the user's finding history so they can compare later outcomes.",
            ]
        else:
            bullets = [
                "The platform stores your question, returns a plain-English explanation, and logs the result for later review.",
                "Real ChatGPT responses activate automatically when OPENAI_API_KEY is present.",
                "Until then, the local explainer still gives a usable breakdown so the website remains testable end to end.",
            ]
        return "\n".join(f"- {line}" for line in bullets)
