from sqlalchemy.orm import Session

from app.config import Settings
from app.keitaro import KeitaroClient, KeitaroError
from app.models import CreatedCampaign, StreamOffer
from app.schemas import CampaignCreateIn, CampaignCreateOut


class ValidationProblem(Exception):
    pass


def apply_prefix(name: str, prefix: str) -> str:
    if prefix and not name.startswith(prefix):
        return prefix + name
    return name


def geo_stream_payload(campaign_id: int, geo: list[str], url: str) -> dict:
    """Поток 1: ловит всех из указанных стран и редиректит на Google."""
    return {
        "campaign_id": campaign_id,
        "name": f"Geo {','.join(geo)} -> Google"[:200],
        "type": "regular",
        "position": 1,
        "state": "active",
        "schema": "redirect",
        "action_type": "http",
        "action_payload": url,
        "filters": [{"name": "country", "mode": "accept", "payload": list(geo)}],
    }


def offer_stream_payload(campaign_id: int, offer_id: int) -> dict:
    """Поток 2: всех остальных отправляет на оффер."""
    return {
        "campaign_id": campaign_id,
        "name": "Offers",
        "type": "default",
        "position": 2,
        "state": "active",
        "schema": "landings",
        "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
    }


def create_campaign(db: Session, kt: KeitaroClient, data: CampaignCreateIn,
                    settings: Settings) -> CampaignCreateOut:
    # Проверяем оффер до того, как что-то создавать
    try:
        kt.get_offer(data.offer_id)
    except KeitaroError as exc:
        if exc.status == 404:
            raise ValidationProblem(f"Offer {data.offer_id} not found in Keitaro") from exc
        raise

    name = apply_prefix(data.name, settings.campaign_prefix)
    campaign_body: dict = {"name": name}
    for field, default in (
        ("domain_id", settings.default_domain_id),
        ("group_id", settings.default_group_id),
        ("traffic_source_id", settings.default_traffic_source_id),
    ):
        value = getattr(data, field) or default
        if value:
            campaign_body[field] = value

    campaign = kt.create_campaign(campaign_body)
    campaign_id = int(campaign["id"])

    # Если поток не создался — откатываем кампанию, чтобы не оставлять полуфабрикат
    try:
        geo = kt.create_stream(geo_stream_payload(campaign_id, data.geo, settings.geo_redirect_url))
        offers = kt.create_stream(offer_stream_payload(campaign_id, data.offer_id))
    except KeitaroError:
        try:
            kt.delete_campaign(campaign_id)
        except KeitaroError:
            pass
        raise

    # ID в Keitaro уникальны, но если кампанию удалили мимо обёртки — убираем устаревшую запись
    db.query(CreatedCampaign).filter_by(keitaro_id=campaign_id).delete()
    record = CreatedCampaign(
        keitaro_id=campaign_id,
        name=campaign.get("name", name),
        alias=campaign.get("alias"),
        geo=",".join(data.geo),
        offer_id=data.offer_id,
        geo_stream_id=int(geo["id"]),
        offer_stream_id=int(offers["id"]),
    )
    db.add(record)
    db.commit()

    return CampaignCreateOut(
        id=campaign_id,
        name=record.name,
        alias=record.alias,
        geo=data.geo,
        offer_id=record.offer_id,
        geo_stream_id=record.geo_stream_id,
        offer_stream_id=record.offer_stream_id,
        admin_url=settings.admin_campaign_url(campaign_id),
    )


def delete_campaign(db: Session, kt: KeitaroClient, campaign_id: int) -> None:
    kt.delete_campaign(campaign_id)
    db.query(CreatedCampaign).filter_by(keitaro_id=campaign_id).delete()
    db.query(StreamOffer).filter_by(campaign_id=campaign_id).delete()
    db.commit()
