"""JWT token storage in config.json."""

import json
import logging
import os

log = logging.getLogger(__name__)

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")


class TokenStore:
    def __init__(self):
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._load()

    @property
    def is_authenticated(self) -> bool:
        return self._access_token is not None

    @property
    def access_token(self) -> str | None:
        return self._access_token

    @property
    def refresh_token(self) -> str | None:
        return self._refresh_token

    def save(self, access_token: str, refresh_token: str):
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._persist()
        log.info("Tokens saved")

    def clear(self):
        self._access_token = None
        self._refresh_token = None
        self._persist()
        log.info("Tokens cleared")

    def _load(self):
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._access_token = data.get("access_token")
            self._refresh_token = data.get("refresh_token")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _persist(self):
        # Read existing config, merge tokens
        data = {}
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        if self._access_token:
            data["access_token"] = self._access_token
            data["refresh_token"] = self._refresh_token
        else:
            data.pop("access_token", None)
            data.pop("refresh_token", None)

        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
