EVENTS = []
SEEN_EVENT_IDS = set()

def ingest_event(event):
    raise NotImplementedError('usage ingestion not implemented')

def invoice_customer(customer_id):
    raise NotImplementedError('invoice calculation not implemented')

def build_webhook(invoice, secret):
    """Return {'payload': ..., 'signature': ...}."""
    raise NotImplementedError('webhook signing not implemented')
