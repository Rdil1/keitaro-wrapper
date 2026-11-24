"""Тонкий клиент Keitaro Admin API (v1). Ключ передаётся в заголовке Api-Key."""

from typing import Any

import httpx


class KeitaroError(Exception):
    def __init__(self, status: int, message: str, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.payload = payload


def _error_message(body: Any, status: int) -> str:
    if isinstance(body, dict):
        for key in ("error", "message", "detail", "errors"):
            if body.get(key):
                return str(body[key])
    if isinstance(body, str) and body.strip():
        return body.strip()[:300]
    return f"Keitaro responded with status {status}"


def as_list(data: Any) -> list:
    """Keitaro отдаёт списки как массив; на всякий случай поддерживаем обёртку {data|items: [...]}."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "items", "rows"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


class KeitaroClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 15.0,
                 transport: httpx.BaseTransport | None = None):
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Api-Key": api_key, "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise KeitaroError(502, f"Keitaro is unreachable: {exc}") from exc
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise KeitaroError(resp.status_code, _error_message(body, resp.status_code), body)
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    # --- кампании ---
    def list_campaigns(self, offset: int = 0, limit: int = 100) -> list[dict]:
        return as_list(self._request("GET", "/campaigns", params={"offset": offset, "limit": limit}))

    def get_campaign(self, campaign_id: int) -> dict:
        return self._request("GET", f"/campaigns/{campaign_id}")

    def create_campaign(self, data: dict) -> dict:
        return self._request("POST", "/campaigns", json=data)

    def update_campaign(self, campaign_id: int, data: dict) -> dict:
        return self._request("PUT", f"/campaigns/{campaign_id}", json=data)

    def delete_campaign(self, campaign_id: int) -> None:
        self._request("DELETE", f"/campaigns/{campaign_id}")

    def campaign_streams(self, campaign_id: int) -> list[dict]:
        return as_list(self._request("GET", f"/campaigns/{campaign_id}/streams"))

    # --- потоки ---
    def create_stream(self, data: dict) -> dict:
        return self._request("POST", "/streams", json=data)

    def get_stream(self, stream_id: int) -> dict:
        return self._request("GET", f"/streams/{stream_id}")

    def update_stream(self, stream_id: int, data: dict) -> dict:
        return self._request("PUT", f"/streams/{stream_id}", json=data)

    # --- справочники (только чтение) ---
    def list_offers(self) -> list[dict]:
        return as_list(self._request("GET", "/offers"))

    def get_offer(self, offer_id: int) -> dict:
        return self._request("GET", f"/offers/{offer_id}")

    def list_groups(self) -> list[dict]:
        return as_list(self._request("GET", "/groups", params={"type": "campaigns"}))

    def list_domains(self) -> list[dict]:
        return as_list(self._request("GET", "/domains"))

    def list_traffic_sources(self) -> list[dict]:
        return as_list(self._request("GET", "/traffic_sources"))
