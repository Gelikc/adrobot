from .errors import AppError


def recalculate(links):
    active = sorted((x for x in links if x.active), key=lambda x: (x.position, x.offer_id))
    if not active:
        raise AppError("LAST_OFFER", "В потоке должен оставаться хотя бы один активный оффер.")
    fixed = sum(x.share for x in active if x.pinned)
    free = [x for x in active if not x.pinned]
    if fixed > 100 or (not free and fixed != 100):
        raise AppError("INVALID_PINS", "Закреплённые доли не позволяют распределить 100% трафика.")
    if free:
        base, extra = divmod(100 - fixed, len(free))
        for i, link in enumerate(free):
            link.share = base + (i < extra)
    for link in links:
        if not link.active:
            link.share, link.pinned = 0, False
