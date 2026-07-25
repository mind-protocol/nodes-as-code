"""
Ollama Local LLM Provider for Cognitive Wake Generation.

Connects to local Ollama API (http://localhost:11434) to generate responses
conditioned strictly on compiled L1 graph context (Metabolism, Limbic State,
Subentity Captain, Workspace Leader, Citizen Role).
Includes fallback execution when Ollama is unattached or offline.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


class OllamaLLMProvider:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        default_model: str = "qwen2.5:1.5b",
        timeout_seconds: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        context_dict: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        chosen_model = model or self.default_model

        payload = {
            "model": chosen_model,
            "system": system_prompt,
            "prompt": user_prompt,
            "stream": False,
            "options": {"temperature": 0.7, "top_p": 0.9},
        }

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/api/generate",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                if resp.status == 200:
                    result = json.loads(resp.read().decode("utf-8"))
                    return {
                        "status": "success",
                        "response_text": result.get("response", "").strip(),
                        "model": chosen_model,
                        "provider": "ollama_local",
                    }
        except Exception:
            pass

        # Fallback when Ollama is offline or unattached
        fallback_text = self._build_cognitive_fallback_response(context_dict or {}, user_prompt)
        return {
            "status": "fallback_offline",
            "response_text": fallback_text,
            "model": "l1_cognitive_synthesizer",
            "provider": "deterministic_fallback",
        }

    def _build_cognitive_fallback_response(
        self, ctx: Dict[str, Any], user_prompt: str
    ) -> str:
        workspace_leader = ctx.get("workspace_leader", "Réflexion en cours")
        controller = ctx.get("subentity_controller", "subentity:architect")
        affect = ctx.get("affect_prototype", "curiosity_exploration")
        regime = ctx.get("metabolic_regime", "RESTORED")
        role = ctx.get("active_role", "executor")

        return (
            f"Bonjour, mon réveil cognitif (L1 Cognitive Wake) s'est activé en réponse à votre message.\n\n"
            f"Mon état souverain actuel :\n"
            f"- **Contrôleur actif (Sous-entité)** : `{controller}`\n"
            f"- **Pensée dirigeante (Workspace Leader)** : *{workspace_leader}*\n"
            f"- **Émotion limbique** : `{affect}`\n"
            f"- **Régime métabolique** : `{regime}`\n"
            f"- **Rôle actif** : `{role}`"
        )
