class TransportError(Exception):
    pass


def fetch_user(http, user_id):
    try:
        r = http.get(f"/users/{user_id}")
        if r.status_code == 404:
            return None
        return r.json()
    except Exception:
        # BUG: swallows transport and JSON errors as not found.
        return None
