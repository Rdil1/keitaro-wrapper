"""Редактор офферов: черновик в БД обёртки, отправка в Keitaro — только пушем."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.keitaro import KeitaroClient, KeitaroError
from app.models import OfferChange, StreamOffer
from app.services import shares as S


class EditorProblem(Exception):
    pass


# ---------- Keitaro ----------
def keitaro_offers(stream: dict) -> list[dict]:
    return [{
        "offer_id": int(o["offer_id"]),
        "share": int(o.get("share") or 0),
        "state": o.get("state") or "active",
    } for o in stream.get("offers") or []]


def is_offer_stream(stream: dict) -> bool:
    return stream.get("schema") == "landings" or bool(stream.get("offers"))


# ---------- черновик ----------
def _rows(db: Session, stream_id: int) -> list[StreamOffer]:
    q = select(StreamOffer).where(StreamOffer.stream_id == stream_id).order_by(StreamOffer.position, StreamOffer.id)
    return list(db.scalars(q))


def _snapshot(rows: list[StreamOffer]) -> list[dict]:
    return [{"offer_id": r.offer_id, "share": r.share, "state": r.state, "pinned": r.pinned, "status": r.status}
            for r in rows]


def _log(db: Session, rows: list[StreamOffer], campaign_id: int, stream_id: int, action: str,
         before: list[dict]) -> None:
    db.add(OfferChange(campaign_id=campaign_id, stream_id=stream_id, action=action,
                       offers_before=before, offers_after=_snapshot(rows)))


def _renumber(rows: list[StreamOffer]) -> None:
    for i, r in enumerate(rows):
        r.position = i


def apply_keitaro(db: Session, campaign_id: int, stream_id: int, rows: list[StreamOffer],
                  offers: list[dict]) -> list[StreamOffer]:
    """Приводит черновик к тому, что сейчас лежит в Keitaro. Архив и закрепления сохраняются."""
    by_id = {r.offer_id: r for r in rows}
    live: list[StreamOffer] = []
    for o in offers:
        r = by_id.pop(o["offer_id"], None)
        if r is None:
            r = StreamOffer(campaign_id=campaign_id, stream_id=stream_id, offer_id=o["offer_id"], pinned=False)
            db.add(r)
        r.status = S.LIVE
        r.share = r.pushed_share = o["share"]
        r.state = r.pushed_state = o["state"]
        r.archived_at = None
        live.append(r)

    rest: list[StreamOffer] = []
    for r in by_id.values():
        if r.status in S.PUSHED:                      # пропал из Keitaro — в архив
            _to_archive(r)
        elif r.status == S.NEW:
            if r.archived_at is None:                 # был только в черновике
                db.delete(r)
                continue
            _to_archive(r, keep_date=True)            # вернули из архива, но не запушили
        rest.append(r)

    result = live + sorted(rest, key=lambda r: r.position)
    _renumber(result)
    S.fix_pins(result)
    return result


def _to_archive(r: StreamOffer, keep_date: bool = False) -> None:
    r.status = S.ARCHIVED
    r.share = 0
    r.pinned = False
    r.pushed_share = None
    r.pushed_state = None
    if not keep_date or r.archived_at is None:
        r.archived_at = datetime.now(timezone.utc)


def _load_stream(kt: KeitaroClient, stream_id: int) -> dict:
    stream = kt.get_stream(stream_id)
    if not is_offer_stream(stream):
        raise EditorProblem("This stream has no offers: it is a redirect stream")
    return stream


def _context(db: Session, kt: KeitaroClient, stream_id: int) -> tuple[int, list[StreamOffer]]:
    """ID кампании и черновик потока; при первом обращении черновик создаётся из Keitaro."""
    rows = _rows(db, stream_id)
    if rows:
        return rows[0].campaign_id, rows
    stream = _load_stream(kt, stream_id)
    campaign_id = int(stream["campaign_id"])
    rows = apply_keitaro(db, campaign_id, stream_id, [], keitaro_offers(stream))
    db.flush()
    return campaign_id, rows


def _next_position(rows: list[StreamOffer]) -> int:
    return max((r.position for r in rows), default=-1) + 1


def view(rows: list[StreamOffer], kt_changes: list[str] | None = None) -> dict:
    visible = [r for r in rows if r.status != S.ARCHIVED]
    archived = sorted((r for r in rows if r.status == S.ARCHIVED),
                      key=lambda r: r.archived_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    problems = S.push_problems(rows)
    dirty = S.is_dirty(rows)

    def row(r: StreamOffer) -> dict:
        hint = S.pin_problem(rows, r)
        share_max, share_hint = S.share_limits(rows, r)
        return {
            "offer_id": r.offer_id,
            "share": r.share,
            "state": r.state,
            "pinned": r.pinned,
            "status": r.status,
            "pushed_share": r.pushed_share,
            "changed": S.is_changed(r),
            "can_pin": hint is None,
            "pin_hint": hint,
            "share_max": share_max,
            "share_hint": share_hint,
            "archived_at": r.archived_at.isoformat() if r.archived_at else None,
        }

    return {
        "offers": [row(r) for r in visible],
        "archived": [row(r) for r in archived],
        "total": S.total(rows),
        "dirty": dirty,
        "kt_changes": kt_changes or [],
        "problems": problems,
        "can_push": dirty and not problems,
    }


# ---------- чтение ----------
def load_campaign(db: Session, kt: KeitaroClient, campaign_id: int) -> dict:
    campaign = kt.get_campaign(campaign_id)
    streams = sorted(kt.campaign_streams(campaign_id), key=lambda s: s.get("position") or 0)
    for s in streams:
        s["editable"] = is_offer_stream(s)
        if s["editable"]:
            s["draft"] = sync_stream(db, campaign_id, s)
    db.commit()
    return {"campaign": campaign, "streams": streams}


def _kt_diff(rows: list[StreamOffer], actual: list[dict]) -> list[str]:
    """Человекочитаемый список того, что поменяли в Keitaro мимо обёртки."""
    notes: list[str] = []
    kt = {o["offer_id"]: o for o in actual}
    by_id = {r.offer_id: r for r in rows}
    for r in rows:
        if r.status in S.PUSHED and r.offer_id not in kt:
            notes.append(f"Offer {r.offer_id} was removed in Keitaro and moved to the archive")
    for o in actual:
        r = by_id.get(o["offer_id"])
        if r is None or r.status in (S.ARCHIVED, S.NEW):
            notes.append(f"Offer {o['offer_id']} was added in Keitaro")
        elif r.pushed_share != o["share"]:
            notes.append(f"Offer {o['offer_id']} share was changed in Keitaro: {r.pushed_share}% → {o['share']}%")
        elif r.pushed_state != o["state"]:
            notes.append(f"Offer {o['offer_id']} was {'disabled' if o['state'] != 'active' else 'enabled'} in Keitaro")
    return notes


def merge_keitaro(db: Session, campaign_id: int, stream_id: int, rows: list[StreamOffer],
                  actual: list[dict]) -> list[StreamOffer]:
    """Вливает изменения из Keitaro в черновик с незапушенными правками, не теряя их:
    удалённые в Keitaro офферы уходят в архив, добавленные появляются, а «что в Keitaro»
    у остальных обновляется. Если состав участников поменялся, доли пересчитываются."""
    kt = {o["offer_id"]: o for o in actual}
    by_id = {r.offer_id: r for r in rows}
    before = {r.offer_id for r in rows if S.participates(r)}

    for r in rows:
        if r.status in S.PUSHED and r.offer_id not in kt:
            _to_archive(r)
    for o in actual:
        r = by_id.get(o["offer_id"])
        if r is None:
            r = StreamOffer(campaign_id=campaign_id, stream_id=stream_id, offer_id=o["offer_id"],
                            position=_next_position(rows), pinned=False, share=o["share"], state=o["state"])
            db.add(r)
            rows.append(r)
        elif r.status == S.ARCHIVED:
            r.share, r.state = o["share"], o["state"]
            r.position = _next_position(rows)
        r.status = S.LIVE if r.status != S.REMOVING else S.REMOVING
        r.pushed_share, r.pushed_state = o["share"], o["state"]
        r.archived_at = None

    if {r.offer_id for r in rows if S.participates(r)} != before:
        S.rebalance(rows)
    else:
        S.fix_pins(rows)
    return rows


def sync_stream(db: Session, campaign_id: int, stream: dict) -> dict:
    """Сверяет черновик с Keitaro. Без незапушенных правок черновик просто становится копией
    Keitaro; с правками — изменения из Keitaro вливаются в черновик. В обоих случаях
    удалённые в Keitaro офферы попадают в архив."""
    stream_id = int(stream["id"])
    actual = keitaro_offers(stream)
    rows = _rows(db, stream_id)
    if not rows:
        return view(apply_keitaro(db, campaign_id, stream_id, [], actual))

    notes = _kt_diff(rows, actual)
    if not notes:
        return view(rows)
    before = _snapshot(rows)
    if S.is_dirty(rows):
        rows = merge_keitaro(db, campaign_id, stream_id, rows, actual)
    else:
        rows = apply_keitaro(db, campaign_id, stream_id, rows, actual)
    _log(db, rows, campaign_id, stream_id, "sync", before)
    db.flush()
    return view(_rows(db, stream_id), kt_changes=notes)


# ---------- правки черновика ----------
def _find(rows: list[StreamOffer], offer_id: int) -> StreamOffer:
    for r in rows:
        if r.offer_id == offer_id:
            return r
    raise EditorProblem(f"Offer {offer_id} is not in this stream")


def _commit(db: Session, campaign_id: int, stream_id: int, rows: list[StreamOffer], action: str,
            before: list[dict]) -> dict:
    _log(db, rows, campaign_id, stream_id, action, before)
    db.commit()
    return view(_rows(db, stream_id))



def add_offer(db: Session, kt: KeitaroClient, stream_id: int, offer_id: int) -> dict:
    campaign_id, rows = _context(db, kt, stream_id)
    before = _snapshot(rows)
    existing = next((r for r in rows if r.offer_id == offer_id), None)
    if existing is not None:
        if existing.status in (S.ARCHIVED, S.REMOVING):
            return restore_offer(db, kt, stream_id, offer_id)
        raise EditorProblem(f"Offer {offer_id} is already in this stream")
    try:
        kt.get_offer(offer_id)
    except KeitaroError as exc:
        if exc.status == 404:
            raise EditorProblem(f"Offer {offer_id} not found in Keitaro") from exc
        raise
    row = StreamOffer(campaign_id=campaign_id, stream_id=stream_id, offer_id=offer_id,
                      position=_next_position(rows), share=0, state="active",
                      pinned=False, status=S.NEW)
    db.add(row)
    rows.append(row)
    S.rebalance(rows)
    return _commit(db, campaign_id, stream_id, rows, "add", before)


def remove_offer(db: Session, kt: KeitaroClient, stream_id: int, offer_id: int) -> dict:
    campaign_id, rows = _context(db, kt, stream_id)
    before = _snapshot(rows)
    row = _find(rows, offer_id)
    if row.status not in S.IN_STREAM:
        raise EditorProblem(f"Offer {offer_id} is already removed")
    if sum(1 for r in rows if r.status in S.IN_STREAM) == 1:
        raise EditorProblem("A stream must keep at least one offer")
    if row.status == S.LIVE:
        row.status = S.REMOVING
    elif row.archived_at is not None:
        row.status = S.ARCHIVED              # возвращали из архива, но передумали
    else:
        db.delete(row)                       # был только в черновике
        rows.remove(row)
    row.pinned = False
    S.rebalance(rows)
    return _commit(db, campaign_id, stream_id, rows, "remove", before)


def restore_offer(db: Session, kt: KeitaroClient, stream_id: int, offer_id: int) -> dict:
    campaign_id, rows = _context(db, kt, stream_id)
    before = _snapshot(rows)
    row = _find(rows, offer_id)
    if row.status == S.REMOVING:
        row.status = S.LIVE
        row.state = row.pushed_state or "active"
    elif row.status == S.ARCHIVED:
        row.status = S.NEW
        row.state = "active"
        row.position = _next_position(rows)
    else:
        raise EditorProblem(f"Offer {offer_id} is already in this stream")
    S.rebalance(rows)
    return _commit(db, campaign_id, stream_id, rows, "restore", before)


def update_offer(db: Session, kt: KeitaroClient, stream_id: int, offer_id: int, *,
                 share: int | None = None, pinned: bool | None = None) -> dict:
    campaign_id, rows = _context(db, kt, stream_id)
    before = _snapshot(rows)
    row = _find(rows, offer_id)
    if row.status not in S.IN_STREAM:
        raise EditorProblem("Only offers that stay in the stream can be edited")

    if pinned is not None and pinned != row.pinned:
        if pinned:
            problem = S.pin_problem(rows, row)
            if problem:
                raise EditorProblem(problem)
        row.pinned = pinned
    if share is not None and share != row.share:
        try:
            S.set_share(rows, row, share)
        except ValueError as exc:
            raise EditorProblem(str(exc)) from exc
    return _commit(db, campaign_id, stream_id, rows, "edit", before)


def dirty_campaigns(db: Session, campaign_ids: list[int]) -> set[int]:
    """Кампании, у которых есть незапушенные правки офферов."""
    if not campaign_ids:
        return set()
    rows = db.scalars(select(StreamOffer).where(StreamOffer.campaign_id.in_(campaign_ids)))
    return {r.campaign_id for r in rows if S.is_changed(r)}


def rebalance_stream(db: Session, kt: KeitaroClient, stream_id: int) -> dict:
    campaign_id, rows = _context(db, kt, stream_id)
    before = _snapshot(rows)
    S.rebalance(rows)
    return _commit(db, campaign_id, stream_id, rows, "rebalance", before)


def discard(db: Session, kt: KeitaroClient, stream_id: int) -> dict:
    """Отменяет незапушенные правки: черновик снова равен тому, что сейчас в Keitaro."""
    campaign_id, rows = _context(db, kt, stream_id)
    before = _snapshot(rows)
    stream = _load_stream(kt, stream_id)
    rows = apply_keitaro(db, campaign_id, stream_id, rows, keitaro_offers(stream))
    return _commit(db, campaign_id, stream_id, rows, "discard", before)


def push(db: Session, kt: KeitaroClient, stream_id: int) -> dict:
    campaign_id, rows = _context(db, kt, stream_id)
    problems = S.push_problems(rows)
    if problems:
        raise EditorProblem("; ".join(problems))
    before = _snapshot(rows)
    payload = [{"offer_id": r.offer_id, "share": r.share, "state": r.state}
               for r in rows if r.status in S.IN_STREAM]
    kt.update_stream(stream_id, {"offers": payload})

    for r in rows:
        if r.status in S.IN_STREAM:
            r.status = S.LIVE
            r.pushed_share = r.share
            r.pushed_state = r.state
            r.archived_at = None
        elif r.status == S.REMOVING:
            _to_archive(r)
    S.fix_pins(rows)
    return _commit(db, campaign_id, stream_id, rows, "push", before)


def forget_campaign(db: Session, campaign_id: int) -> None:
    db.query(StreamOffer).filter_by(campaign_id=campaign_id).delete()
