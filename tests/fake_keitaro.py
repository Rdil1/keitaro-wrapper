"""In-memory эмулятор Keitaro Admin API для тестов (через httpx.MockTransport)."""

import json
import re

import httpx


class FakeKeitaro:
    def __init__(self):
        self.campaigns: dict[int, dict] = {}
        self.streams: dict[int, dict] = {}
        self.offers = {i: {"id": i, "name": f"Offer {i}", "state": "active"} for i in range(18001, 18011)}
        self.next_id = 1
        self.log: list[tuple[str, str, dict | None]] = []
        self.fail_stream_create = False

    def _id(self) -> int:
        self.next_id += 1
        return self.next_id

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("Api-Key") != "test-key":
            return httpx.Response(401, json={"error": "bad key"})
        path = request.url.path.replace("/admin_api/v1", "")
        body = json.loads(request.content) if request.content else None
        self.log.append((request.method, path, body))
        m = request.method

        if path == "/offers" and m == "GET":
            return httpx.Response(200, json=list(self.offers.values()))
        if (r := re.fullmatch(r"/offers/(\d+)", path)) and m == "GET":
            offer = self.offers.get(int(r[1]))
            return httpx.Response(200, json=offer) if offer else httpx.Response(404, json={"error": "Not found"})
        if path == "/domains":
            return httpx.Response(200, json=[{"id": 1813, "name": "test.example"}])
        if path == "/groups":
            return httpx.Response(200, json=[{"id": 10332, "name": "FORTESTS"}])
        if path == "/traffic_sources":
            return httpx.Response(200, json=[{"id": 836, "name": "FORTESTS"}])

        if path == "/campaigns" and m == "GET":
            return httpx.Response(200, json=sorted(self.campaigns.values(), key=lambda c: -c["id"]))
        if path == "/campaigns" and m == "POST":
            cid = self._id()
            self.campaigns[cid] = {"id": cid, "alias": f"al{cid}", "state": "active", **body}
            return httpx.Response(200, json=self.campaigns[cid])
        if r := re.fullmatch(r"/campaigns/(\d+)", path):
            cid = int(r[1])
            if cid not in self.campaigns:
                return httpx.Response(404, json={"error": "Not found"})
            if m == "GET":
                return httpx.Response(200, json=self.campaigns[cid])
            if m == "DELETE":
                del self.campaigns[cid]
                self.streams = {k: v for k, v in self.streams.items() if v["campaign_id"] != cid}
                return httpx.Response(200, json={"success": True})
        if (r := re.fullmatch(r"/campaigns/(\d+)/streams", path)) and m == "GET":
            cid = int(r[1])
            return httpx.Response(200, json=[s for s in self.streams.values() if s["campaign_id"] == cid])

        if path == "/streams" and m == "POST":
            if self.fail_stream_create:
                return httpx.Response(400, json={"error": "stream rejected"})
            sid = self._id()
            self.streams[sid] = {"id": sid, "offers": [], "filters": [], **body}
            return httpx.Response(200, json=self.streams[sid])
        if r := re.fullmatch(r"/streams/(\d+)", path):
            sid = int(r[1])
            if sid not in self.streams:
                return httpx.Response(404, json={"error": "Not found"})
            if m == "GET":
                return httpx.Response(200, json=self.streams[sid])
            if m == "PUT":
                self.streams[sid].update(body)
                return httpx.Response(200, json=self.streams[sid])

        return httpx.Response(404, json={"error": f"unsupported {m} {path}"})
