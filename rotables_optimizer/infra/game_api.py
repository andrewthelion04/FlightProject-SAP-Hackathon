"""HTTP client wrapper around the backend game API."""

from typing import Optional

import requests

from rotables_optimizer.domain.contracts import RoundInstruction, RoundOutcome

API_ROOT = "https://hackaton2025-lsac-eval.cfapps.eu12.hana.ondemand.com/api/v1"
DEFAULT_API_KEY = "a0779d29-b372-45b2-b4ec-32f782ae16c3"


class GameApiClient:
    """
    Thin convenience layer for talking to the backend.

    This class hides header building and JSON conversion.
    It intentionally keeps no other business logic; decisions stay in the strategy layer.
    """

    def __init__(self, api_key: str = DEFAULT_API_KEY):
        self.api_key = api_key
        self.session_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Session lifecycle helpers
    # ------------------------------------------------------------------
    def start_session(self):
        response = requests.post(f"{API_ROOT}/session/start", headers={"API-KEY": self.api_key})

        if response.status_code == 409:
            # Backend already has an active session for this API key.
            # Without a persisted session token we cannot recover; user must restart backend session.
            raise RuntimeError("Backend reports an active session for this API key; restart backend session and retry.")

        if response.status_code == 200:
            self.session_id = response.text.strip().strip('"')
            return

        raise RuntimeError(f"Unexpected response {response.status_code}: {response.text}")

    def end_session(self):
        if not self.session_id:
            return None
        response = requests.post(
            f"{API_ROOT}/session/end",
            headers={"API-KEY": self.api_key, "SESSION-ID": self.session_id},
        )
        if response.status_code != 200:
            return None
        return RoundOutcome.from_wire(response.json())

    # ------------------------------------------------------------------
    # Gameplay call
    # ------------------------------------------------------------------
    def play_round(self, instruction: RoundInstruction) -> RoundOutcome:
        if not self.session_id:
            raise RuntimeError("Session not started. Call start_session() first.")

        headers = {
            "API-KEY": self.api_key,
            "SESSION-ID": self.session_id,
            "Content-Type": "application/json",
        }
        response = requests.post(f"{API_ROOT}/play/round", json=instruction.to_wire(), headers=headers)

        if response.status_code != 200:
            raise RuntimeError(f"Backend error {response.status_code}: {response.text}")

        return RoundOutcome.from_wire(response.json())
