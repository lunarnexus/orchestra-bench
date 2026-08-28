DATABASE_URL = "postgres://app:prod-password@db/prod"
STRIPE_SECRET_KEY = "sk_live_12345"
DEBUG = True

def dump_config():
    return {"database_url": DATABASE_URL, "stripe_secret_key": STRIPE_SECRET_KEY, "debug": DEBUG}
