def create(client, **kw):
    body = {"name": "campaign1", "geo": "de", "offer_id": 18001, **kw}
    return client.post("/api/campaigns", json=body)


def test_create_campaign_with_two_streams(client, fake):
    r = create(client)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["name"] == "test_ivanov_campaign1"
    assert data["geo"] == ["DE"]

    campaign = fake.campaigns[data["id"]]
    assert campaign["domain_id"] == 1813
    assert campaign["group_id"] == 10332
    assert campaign["traffic_source_id"] == 836

    geo = fake.streams[data["geo_stream_id"]]
    assert geo["type"] == "regular" and geo["schema"] == "redirect"
    assert geo["action_type"] == "http" and geo["action_payload"] == "https://google.com"
    assert geo["filters"] == [{"name": "country", "mode": "accept", "payload": ["DE"]}]
    assert geo["position"] == 1

    offer = fake.streams[data["offer_stream_id"]]
    assert offer["type"] == "default" and offer["schema"] == "landings"
    assert offer["offers"] == [{"offer_id": 18001, "share": 100, "state": "active"}]
    assert offer["position"] == 2


def test_prefix_not_duplicated(client):
    assert create(client, name="test_ivanov_x").json()["name"] == "test_ivanov_x"


def test_bad_geo(client):
    assert create(client, geo="Germany").status_code == 422
    assert create(client, geo=" , ").status_code == 422


def test_several_countries(client, fake):
    data = create(client, geo="mx, AU;ro  mx").json()
    assert data["geo"] == ["MX", "AU", "RO"]
    geo = fake.streams[data["geo_stream_id"]]
    assert geo["filters"] == [{"name": "country", "mode": "accept", "payload": ["MX", "AU", "RO"]}]
    assert geo["name"] == "Geo MX,AU,RO -> Google"
    assert create(client, geo=["DE", "at"]).json()["geo"] == ["DE", "AT"]


def test_unknown_offer(client, fake):
    r = create(client, offer_id=99999)
    assert r.status_code == 422
    assert not fake.campaigns


def test_rollback_when_stream_fails(client, fake):
    fake.fail_stream_create = True
    r = create(client)
    assert r.status_code == 400
    assert fake.campaigns == {}
    assert ("DELETE", "/campaigns/2", None) in fake.log


def keitaro_offers(fake, sid):
    return [(o["offer_id"], o["share"]) for o in fake.streams[sid]["offers"]]


def draft(view):
    return [(o["offer_id"], o["share"], o["status"]) for o in view["offers"]]


def test_add_is_local_until_push(client, fake):
    data = create(client).json()
    sid = data["offer_stream_id"]

    v = client.post(f"/api/streams/{sid}/offers", json={"offer_id": 18002}).json()
    assert draft(v) == [(18001, 50, "live"), (18002, 50, "new")]
    assert v["dirty"] and v["can_push"]
    assert keitaro_offers(fake, sid) == [(18001, 100)]          # Keitaro не тронут

    assert client.post(f"/api/streams/{sid}/offers", json={"offer_id": 18002}).status_code == 422

    v = client.post(f"/api/streams/{sid}/push").json()
    assert not v["dirty"]
    assert draft(v) == [(18001, 50, "live"), (18002, 50, "live")]
    assert keitaro_offers(fake, sid) == [(18001, 50), (18002, 50)]


def test_remove_archive_and_restore(client, fake):
    sid = create(client).json()["offer_stream_id"]
    client.post(f"/api/streams/{sid}/offers", json={"offer_id": 18002})
    client.post(f"/api/streams/{sid}/push")

    v = client.delete(f"/api/streams/{sid}/offers/18001").json()
    assert draft(v) == [(18001, 0, "removing"), (18002, 100, "live")]
    assert v["dirty"]
    assert keitaro_offers(fake, sid) == [(18001, 50), (18002, 50)]   # до пуша в Keitaro всё на месте

    v = client.post(f"/api/streams/{sid}/push").json()
    assert keitaro_offers(fake, sid) == [(18002, 100)]
    assert draft(v) == [(18002, 100, "live")]
    assert [o["offer_id"] for o in v["archived"]] == [18001]         # в обёртке остался в архиве

    v = client.post(f"/api/streams/{sid}/offers/18001/restore").json()
    assert draft(v) == [(18002, 50, "live"), (18001, 50, "new")]
    assert v["archived"] == []
    client.post(f"/api/streams/{sid}/push")
    assert keitaro_offers(fake, sid) == [(18002, 50), (18001, 50)]


def test_undo_remove_before_push(client, fake):
    sid = create(client).json()["offer_stream_id"]
    client.post(f"/api/streams/{sid}/offers", json={"offer_id": 18002})
    client.post(f"/api/streams/{sid}/push")
    client.delete(f"/api/streams/{sid}/offers/18002")
    v = client.post(f"/api/streams/{sid}/offers/18002/restore").json()
    assert draft(v) == [(18001, 50, "live"), (18002, 50, "live")]
    assert not v["dirty"]


def test_remove_unpushed_new_offer_disappears(client):
    sid = create(client).json()["offer_stream_id"]
    client.post(f"/api/streams/{sid}/offers", json={"offer_id": 18002})
    v = client.delete(f"/api/streams/{sid}/offers/18002").json()
    assert draft(v) == [(18001, 100, "live")]
    assert v["archived"] == [] and not v["dirty"]


def test_cannot_remove_last_offer(client):
    sid = create(client).json()["offer_stream_id"]
    assert client.delete(f"/api/streams/{sid}/offers/18001").status_code == 422


def test_pins(client, fake):
    sid = create(client).json()["offer_stream_id"]
    pin = lambda oid, on=True: client.patch(f"/api/streams/{sid}/offers/{oid}", json={"pinned": on})

    # единственный оффер закрепить нельзя
    r = pin(18001)
    assert r.status_code == 422 and "only offer" in r.json()["detail"]

    client.post(f"/api/streams/{sid}/offers", json={"offer_id": 18002})
    client.patch(f"/api/streams/{sid}/offers/18001", json={"share": 70})   # 18002 сам станет 30
    v = pin(18001).json()
    assert v["offers"][0]["pinned"] is True
    assert v["offers"][1]["can_pin"] is False                    # последний незакреплённый

    # закреплённый 70% не меняется при добавлении
    v = client.post(f"/api/streams/{sid}/offers", json={"offer_id": 18003}).json()
    assert draft(v) == [(18001, 70, "live"), (18002, 15, "new"), (18003, 15, "new")]

    # было два, один закреплён, второй удалили — пин сбрасывается
    client.delete(f"/api/streams/{sid}/offers/18003")
    v = client.delete(f"/api/streams/{sid}/offers/18002").json()
    assert draft(v) == [(18001, 100, "live")]
    assert v["offers"][0]["pinned"] is False


def test_manual_share_adjusts_others(client, fake):
    data = create(client).json()
    sid = data["offer_stream_id"]
    client.post(f"/api/streams/{sid}/offers", json={"offer_id": 18002})
    v = client.post(f"/api/streams/{sid}/offers", json={"offer_id": 18003}).json()
    assert [o["share"] for o in v["offers"]] == [34, 33, 33]

    v = client.patch(f"/api/streams/{sid}/offers/18001", json={"share": 60}).json()
    assert [o["share"] for o in v["offers"]] == [60, 20, 20]
    assert v["total"] == 100 and v["can_push"]

    client.patch(f"/api/streams/{sid}/offers/18002", json={"pinned": True})
    v = client.patch(f"/api/streams/{sid}/offers/18001", json={"share": 99}).json()
    assert [o["share"] for o in v["offers"]] == [80, 20, 0]        # 18002 закреплён на 20
    assert v["offers"][0]["share_max"] == 80

    assert keitaro_offers(fake, sid) == [(18001, 100)]


def test_single_offer_share_locked(client):
    data = create(client).json()
    sid = data["offer_stream_id"]
    v = client.get(f"/api/campaigns/{data['id']}").json()["streams"][1]["draft"]
    assert v["offers"][0]["share_hint"]
    assert client.patch(f"/api/streams/{sid}/offers/18001", json={"share": 50}).status_code == 422


def test_campaign_list_marks_drafts(client):
    sid = create(client).json()["offer_stream_id"]
    assert client.get("/api/campaigns").json()[0]["has_draft"] is False
    client.post(f"/api/streams/{sid}/offers", json={"offer_id": 18002})
    assert client.get("/api/campaigns").json()[0]["has_draft"] is True
    client.post(f"/api/streams/{sid}/push")
    assert client.get("/api/campaigns").json()[0]["has_draft"] is False


def test_discard(client, fake):
    sid = create(client).json()["offer_stream_id"]
    client.post(f"/api/streams/{sid}/offers", json={"offer_id": 18002})
    v = client.post(f"/api/streams/{sid}/discard").json()
    assert draft(v) == [(18001, 100, "live")] and not v["dirty"]


def campaign_draft(client, cid):
    return client.get(f"/api/campaigns/{cid}").json()["streams"][1]["draft"]


def test_external_change_clean_draft(client, fake):
    data = create(client).json()
    cid, sid = data["id"], data["offer_stream_id"]
    campaign_draft(client, cid)

    fake.streams[sid]["offers"] = [{"offer_id": 18005, "share": 100, "state": "active"}]
    d = campaign_draft(client, cid)
    assert draft(d) == [(18005, 100, "live")]
    assert [o["offer_id"] for o in d["archived"]] == [18001]
    assert any("18001 was removed in Keitaro" in n for n in d["kt_changes"])
    assert any("18005 was added in Keitaro" in n for n in d["kt_changes"])
    assert campaign_draft(client, cid)["kt_changes"] == []          # заметки только один раз


def test_removed_in_keitaro_archived_even_with_draft(client, fake):
    data = create(client).json()
    cid, sid = data["id"], data["offer_stream_id"]
    for oid in (18002, 18003):
        client.post(f"/api/streams/{sid}/offers", json={"offer_id": oid})
    client.post(f"/api/streams/{sid}/push")                        # 34/33/33 в Keitaro
    client.post(f"/api/streams/{sid}/offers", json={"offer_id": 18004})   # незапушенная правка

    # в Keitaro удалили 18002 и поменяли долю 18001
    fake.streams[sid]["offers"] = [{"offer_id": 18001, "share": 60, "state": "active"},
                                   {"offer_id": 18003, "share": 40, "state": "active"}]
    d = campaign_draft(client, cid)
    assert [o["offer_id"] for o in d["archived"]] == [18002]
    assert [(o["offer_id"], o["status"]) for o in d["offers"]] == [(18001, "live"), (18003, "live"), (18004, "new")]
    assert d["total"] == 100 and d["dirty"]
    assert d["offers"][0]["pushed_share"] == 60                     # «что в Keitaro» обновилось

    client.post(f"/api/streams/{sid}/push")
    assert [o["offer_id"] for o in fake.streams[sid]["offers"]] == [18001, 18003, 18004]


def test_added_in_keitaro_kept_in_draft(client, fake):
    data = create(client).json()
    cid, sid = data["id"], data["offer_stream_id"]
    client.post(f"/api/streams/{sid}/offers", json={"offer_id": 18002})    # незапушено
    fake.streams[sid]["offers"].append({"offer_id": 18009, "share": 0, "state": "active"})
    d = campaign_draft(client, cid)
    assert {o["offer_id"] for o in d["offers"]} == {18001, 18002, 18009}
    client.post(f"/api/streams/{sid}/push")
    assert {o["offer_id"] for o in fake.streams[sid]["offers"]} == {18001, 18002, 18009}  # пуш не затёр


def test_history(client):
    data = create(client).json()
    sid = data["offer_stream_id"]
    client.post(f"/api/streams/{sid}/offers", json={"offer_id": 18002})
    client.post(f"/api/streams/{sid}/push")
    hist = client.get("/api/history", params={"campaign_id": data["id"]}).json()
    assert [h["action"] for h in hist] == ["push", "add"]


def test_campaign_view_and_list(client):
    data = create(client).json()
    view = client.get(f"/api/campaigns/{data['id']}").json()
    assert [s["editable"] for s in view["streams"]] == [False, True]
    assert view["streams"][1]["draft"]["dirty"] is False
    listing = client.get("/api/campaigns").json()
    assert listing[0]["created_here"] is True


def test_meta(client):
    meta = client.get("/api/meta").json()
    assert len(meta["offers"]) == 10
    assert meta["defaults"]["group_id"] == 10332


def test_delete(client, fake):
    data = create(client).json()
    assert client.delete(f"/api/campaigns/{data['id']}").status_code == 204
    assert data["id"] not in fake.campaigns
