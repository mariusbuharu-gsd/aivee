"""Web Push for the dashboard PWA: VAPID settings, subscription storage, sending.

The API stores subscriptions and serves the public key; ingest sends the alert pushes
through the same `push_to_all` so expired subscriptions are dropped in one place.
"""
