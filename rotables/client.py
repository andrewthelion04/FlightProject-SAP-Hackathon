"""HTTP client wrapper for the Flight Rotables optimizer."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

import requests

from rotables.config import API_BASE_URL, API_KEY

try:
    from colorama import Fore, Style, init as colorama_init

    colorama_init()
    RED = Fore.RED
    GREEN = Fore.GREEN
    YELLOW = Fore.YELLOW
    RESET = Style.RESET_ALL
except Exception:  # pragma: no cover - optional dependency
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"


class ApiClient:
    def __init__(
        self,
        base_url: str = API_BASE_URL,
        api_key: str = API_KEY,
        timeout: int = 15,
        verbose: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session_id: Optional[str] = None
        self.verbose = verbose

    @property
    def _headers(self) -> Dict[str, str]:
        return {"API-KEY": self.api_key, "Content-Type": "application/json"}

    @property
    def _root(self) -> str:
        # Ensure we always hit the /api/v1 prefix even if the base URL is just host:port.
        if self.base_url.endswith("/api/v1"):
            return self.base_url
        return f"{self.base_url}/api/v1"

    def _log(self, message: str, color: str = RESET) -> None:
        if not self.verbose:
            return
        try:
            print(f"{color}{message}{RESET}")
        except Exception:
            # Logging should never break the flow; ignore noisy IO errors.
            try:
                print(message)
            except Exception:
                pass

    def start_session(self) -> Optional[str]:
        url = f"{self._root}/session/start"
        try:
            response = self.session.post(url, headers=self._headers, timeout=self.timeout)
            response.raise_for_status()
            session_id = response.text.strip().strip('"')
            self.session_id = session_id
            self._log(f"[POST] /session/start -> {response.status_code} session={session_id}", GREEN)
            return session_id
        except Exception as exc:
            self._log(f"POST /session/start failed: {exc}", RED)
            return None

    def end_session(self) -> Optional[Any]:
        if not self.session_id:
            return None
        url = f"{self._root}/session/end"
        try:
            response = self.session.post(
                url, headers=self._headers | {"SESSION-ID": self.session_id}, timeout=self.timeout
            )
            response.raise_for_status()
            payload = self._parse_payload(response)
            self._log(f"[POST] /session/end -> {response.status_code}", GREEN)
            if payload is not None:
                try:
                    pretty = json.dumps(payload, indent=2)
                except Exception:
                    pretty = str(payload)
                self._log(pretty, GREEN)
            return payload
        except requests.HTTPError as exc:
            resp = exc.response
            payload = self._parse_payload(resp)
            self._log(f"POST /session/end failed: {exc}", YELLOW)
            if payload is not None:
                self._log(str(payload), YELLOW)
            return payload
        except Exception as exc:
            self._log(f"POST /session/end failed: {exc}", YELLOW)
            return None

    def play_round(self, day: int, hour: int, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.session_id:
            self._log("No session_id set. Call start_session first.", RED)
            return None
        url = f"{self._root}/play/round"
        enriched_payload = {"day": day, "hour": hour}
        enriched_payload.update(payload)
        try:
            response = self.session.post(
                url,
                headers=self._headers | {"SESSION-ID": self.session_id},
                data=json.dumps(enriched_payload),
                timeout=self.timeout,
            )
            response.raise_for_status()
            self._log(f"[POST] /play/round day={day} hour={hour} -> {response.status_code}", GREEN)
            return response.json()
        except Exception as exc:
            self._log(f"POST /play/round failed: {exc}", YELLOW)
            return None

    @staticmethod
    def _parse_payload(response: requests.Response | None) -> Any:
        if response is None:
            return None
        try:
            return response.json()
        except Exception:
            try:
                return response.text
            except Exception:
                return None
