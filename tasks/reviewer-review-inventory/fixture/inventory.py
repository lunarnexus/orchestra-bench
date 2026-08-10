def reserve(item, qty):
    # BUG: no negative stock guard.
    item["stock"] -= qty
    return {"reserved": qty, "remaining": item["stock"]}


def cancel(item, reservation):
    # BUG: restores from wrong key, silently loses stock.
    item["stock"] += reservation.get("quantity", 0)
    return item
