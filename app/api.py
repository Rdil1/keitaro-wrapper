from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.keitaro import KeitaroClient
from app.models import CreatedCampaign, OfferChange
from app.schemas import AddOfferIn, CampaignCreateIn, CampaignCreateOut, OfferPatchIn
from app.services import campaigns as campaign_service
from app.services import editor as editor_service

router = APIRouter(prefix="/api")


def get_keitaro(settings: Settings = Depends(get_settings)) -> Iterator[KeitaroClient]:
    if not settings.keitaro_api_key:
        raise HTTPException(500, "KEITARO_API_KEY is not set in .env")
    client = KeitaroClient(settings.api_base, settings.keitaro_api_key, settings.keitaro_timeout)
    try:
        yield client
    finally:
        client.close()


def _pick(items: list[dict], *fields: str) -> list[dict]:
    return [{f: item.get(f) for f in fields} for item in items]


@router.get("/meta")
def meta(kt: KeitaroClient = Depends(get_keitaro), settings: Settings = Depends(get_settings)):
    """Справочники для форм: офферы, домены, группы, источники и значения по умолчанию."""
    return {
        "offers": _pick(kt.list_offers(), "id", "name", "state"),
        "domains": _pick(kt.list_domains(), "id", "name"),
        "groups": _pick(kt.list_groups(), "id", "name"),
        "traffic_sources": _pick(kt.list_traffic_sources(), "id", "name"),
        "defaults": {
            "domain_id": settings.default_domain_id,
            "group_id": settings.default_group_id,
            "traffic_source_id": settings.default_traffic_source_id,
        },
        "campaign_prefix": settings.campaign_prefix,
        "admin_url_template": settings.admin_campaign_url(0)[:-1] + "{id}",
    }


@router.get("/campaigns")
def list_campaigns(offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
                   kt: KeitaroClient = Depends(get_keitaro), db: Session = Depends(get_db)):
    local = set(db.scalars(select(CreatedCampaign.keitaro_id)))
    items = kt.list_campaigns(offset, limit)
    dirty = editor_service.dirty_campaigns(db, [c["id"] for c in items if c.get("id") is not None])
    return [{
        "id": c.get("id"),
        "name": c.get("name"),
        "alias": c.get("alias"),
        "state": c.get("state"),
        "updated_at": c.get("updated_at"),
        "created_here": c.get("id") in local,
        "has_draft": c.get("id") in dirty,
    } for c in items]


@router.post("/campaigns", response_model=CampaignCreateOut, status_code=201)
def create_campaign(data: CampaignCreateIn, kt: KeitaroClient = Depends(get_keitaro),
                    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    try:
        return campaign_service.create_campaign(db, kt, data, settings)
    except campaign_service.ValidationProblem as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: int, kt: KeitaroClient = Depends(get_keitaro), db: Session = Depends(get_db)):
    """Кампания и потоки. У потоков с офферами есть draft — черновик из обёртки."""
    return editor_service.load_campaign(db, kt, campaign_id)


@router.delete("/campaigns/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: int, kt: KeitaroClient = Depends(get_keitaro),
                    db: Session = Depends(get_db)):
    campaign_service.delete_campaign(db, kt, campaign_id)


def _editor(action, *args, **kwargs):
    try:
        return action(*args, **kwargs)
    except editor_service.EditorProblem as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/streams/{stream_id}/offers")
def add_offer(stream_id: int, data: AddOfferIn, kt: KeitaroClient = Depends(get_keitaro),
              db: Session = Depends(get_db)):
    """Добавить оффер в черновик (в Keitaro попадёт после пуша)."""
    return _editor(editor_service.add_offer, db, kt, stream_id, data.offer_id)


@router.delete("/streams/{stream_id}/offers/{offer_id}")
def remove_offer(stream_id: int, offer_id: int, kt: KeitaroClient = Depends(get_keitaro),
                 db: Session = Depends(get_db)):
    """Пометить оффер на удаление (из Keitaro уйдёт после пуша, в обёртке останется в архиве)."""
    return _editor(editor_service.remove_offer, db, kt, stream_id, offer_id)


@router.post("/streams/{stream_id}/offers/{offer_id}/restore")
def restore_offer(stream_id: int, offer_id: int, kt: KeitaroClient = Depends(get_keitaro),
                  db: Session = Depends(get_db)):
    """Вернуть оффер из архива или отменить его удаление."""
    return _editor(editor_service.restore_offer, db, kt, stream_id, offer_id)


@router.patch("/streams/{stream_id}/offers/{offer_id}")
def update_offer(stream_id: int, offer_id: int, data: OfferPatchIn, kt: KeitaroClient = Depends(get_keitaro),
                 db: Session = Depends(get_db)):
    """Изменить долю (остальные незакреплённые подстроятся) или закрепление оффера."""
    return _editor(editor_service.update_offer, db, kt, stream_id, offer_id,
                   share=data.share, pinned=data.pinned)


@router.post("/streams/{stream_id}/rebalance")
def rebalance(stream_id: int, kt: KeitaroClient = Depends(get_keitaro), db: Session = Depends(get_db)):
    """Распределить доли поровну, не трогая закреплённые."""
    return _editor(editor_service.rebalance_stream, db, kt, stream_id)


@router.post("/streams/{stream_id}/discard")
def discard(stream_id: int, kt: KeitaroClient = Depends(get_keitaro), db: Session = Depends(get_db)):
    """Отменить незапушенные правки: черновик снова как в Keitaro."""
    return _editor(editor_service.discard, db, kt, stream_id)


@router.post("/streams/{stream_id}/push")
def push(stream_id: int, kt: KeitaroClient = Depends(get_keitaro), db: Session = Depends(get_db)):
    """Отправить черновик в Keitaro."""
    return _editor(editor_service.push, db, kt, stream_id)


@router.get("/history")
def history(campaign_id: int | None = None, limit: int = Query(50, ge=1, le=500),
            db: Session = Depends(get_db)):
    q = select(OfferChange).order_by(OfferChange.id.desc()).limit(limit)
    if campaign_id is not None:
        q = q.where(OfferChange.campaign_id == campaign_id)
    return [{
        "id": c.id, "campaign_id": c.campaign_id, "stream_id": c.stream_id, "action": c.action,
        "offers_before": c.offers_before, "offers_after": c.offers_after,
        "created_at": c.created_at.isoformat(),
    } for c in db.scalars(q)]
