def render_v1(order):
    return {"id": order["id"], "total_cents": order["total_cents"], "status": order["status"]}


def render_v2(order):
    # BUG: mutates caller-owned order and leaks internal note in the public response.
    order["tracking_url"] = order.get("tracking_url")
    return order
