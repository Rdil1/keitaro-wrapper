"""Правила распределения долей офферов внутри потока.

* Доли офферов, которые после пуша окажутся в Keitaro и активны («участники»), в сумме дают 100.
* При добавлении, удалении, возврате или выключении оффера доли пересчитываются:
  закреплённые (pinned) офферы сохраняют свою долю, остаток делится поровну между
  незакреплёнными, лишние проценты получают первые: 3 оффера -> 34/33/33.
* Закрепить можно только участника и только если после этого останется хотя бы один
  незакреплённый участник: кто-то должен принимать изменения. Поэтому единственный
  оффер закрепить нельзя.
* Если после удаления все оставшиеся участники закреплены (например, было два оффера,
  один закреплён, второй удалили), закрепления сбрасываются.
* Удалённые, архивные и выключенные офферы получают долю 0 и теряют закрепление.
* Ручной ввод доли: остаток делится между остальными незакреплёнными офферами пропорционально
  их текущим долям (50/30/20 -> первому 60 -> 60/24/16). Закреплённые не меняются, поэтому
  доля ограничена сверху 100 минус закреплённые. Если подстраивать некого, менять долю нельзя.

Функции работают с любыми объектами с атрибутами status, state, pinned, share.
"""

TOTAL = 100

LIVE = "live"
NEW = "new"
REMOVING = "removing"
ARCHIVED = "archived"
IN_STREAM = (LIVE, NEW)          # будут в Keitaro после пуша
PUSHED = (LIVE, REMOVING)        # лежат в Keitaro сейчас


def split_evenly(count: int, total: int = TOTAL) -> list[int]:
    if count <= 0:
        return []
    total = max(0, total)
    base, rest = divmod(total, count)
    return [base + 1 if i < rest else base for i in range(count)]


def participates(offer) -> bool:
    return offer.status in IN_STREAM and offer.state == "active"


def participants(offers) -> list:
    return [o for o in offers if participates(o)]


def fix_pins(offers) -> None:
    for o in offers:
        if not participates(o):
            o.pinned = False
    parts = participants(offers)
    if parts and all(o.pinned for o in parts):
        for o in parts:
            o.pinned = False


def rebalance(offers) -> None:
    """Пересчитывает доли на месте с учётом закреплений."""
    for o in offers:
        if not participates(o):
            o.share = 0
    fix_pins(offers)
    parts = participants(offers)
    pinned = [o for o in parts if o.pinned]
    free = [o for o in parts if not o.pinned]
    remaining = TOTAL - sum(o.share for o in pinned)
    for o, share in zip(free, split_evenly(len(free), remaining)):
        o.share = share


def distribute_proportionally(offers, amount: int) -> None:
    """Делит amount между offers пропорционально текущим долям (метод наибольших остатков)."""
    if not offers:
        return
    amount = max(0, amount)
    weights = [max(0, o.share) for o in offers]
    weight_sum = sum(weights)
    if weight_sum == 0:
        for o, share in zip(offers, split_evenly(len(offers), amount)):
            o.share = share
        return
    base = [amount * w // weight_sum for w in weights]
    remainders = [amount * w % weight_sum for w in weights]
    leftover = amount - sum(base)
    for i in sorted(range(len(offers)), key=lambda i: (-remainders[i], i))[:leftover]:
        base[i] += 1
    for o, share in zip(offers, base):
        o.share = share


def share_limits(offers, target) -> tuple[int, str | None]:
    """Максимальная доля, которую можно вручную задать офферу, и причина, если менять нельзя."""
    if not participates(target):
        return 0, "Share can only be set for an active offer that stays in the stream"
    others = [o for o in participants(offers) if o is not target]
    if not others:
        return TOTAL, "The only offer always gets 100%"
    if all(o.pinned for o in others):
        return target.share, "All other offers are pinned: unpin one to change this share"
    return max(0, TOTAL - sum(o.share for o in others if o.pinned)), None


def set_share(offers, target, value: int) -> int:
    """Задаёт долю вручную и подстраивает незакреплённые офферы. Возвращает применённую долю."""
    cap, problem = share_limits(offers, target)
    if problem:
        raise ValueError(problem)
    value = min(max(0, value), cap)
    target.share = value
    free = [o for o in participants(offers) if o is not target and not o.pinned]
    distribute_proportionally(free, cap - value)
    return value


def pin_problem(offers, target) -> str | None:
    """Почему оффер нельзя закрепить; None — можно."""
    if target.pinned:
        return None
    if not participates(target):
        return "Only an active offer that stays in the stream can be pinned"
    parts = participants(offers)
    if len(parts) == 1:
        return "The only offer cannot be pinned: it always gets 100%"
    if not any(not o.pinned and o is not target for o in parts):
        return "At least one offer must stay unpinned to absorb share changes"
    return None


def total(offers) -> int:
    return sum(o.share for o in participants(offers))


def push_problems(offers) -> list[str]:
    errors: list[str] = []
    in_stream = [o for o in offers if o.status in IN_STREAM]
    if not in_stream:
        errors.append("A stream must keep at least one offer")
        return errors
    parts = participants(offers)
    if not parts:
        errors.append("At least one active offer is required")
    for o in in_stream:
        if not 0 <= o.share <= TOTAL:
            errors.append(f"Share of offer {o.offer_id} must be between 0 and 100")
    s = total(offers)
    if parts and s != TOTAL:
        errors.append(f"Active offer shares add up to {s}%, must be 100%")
    return errors


def is_changed(offer) -> bool:
    if offer.status in (NEW, REMOVING):
        return True
    if offer.status == LIVE:
        return offer.share != offer.pushed_share or offer.state != offer.pushed_state
    return False


def is_dirty(offers) -> bool:
    return any(is_changed(o) for o in offers)
