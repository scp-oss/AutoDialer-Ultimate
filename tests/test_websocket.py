"""Dashboard WebSocket: connection, initial snapshot, and Redis-backed broadcast."""

import json
import os

import redis as sync_redis


def test_websocket_connects_and_receives_initial_snapshot(client):
    with client.websocket_connect("/api/ws/dashboard") as ws:
        message = ws.receive_json()
        assert message["type"] == "system"
        assert "data" in message


def test_websocket_receives_broadcast_published_via_redis(client):
    """
    WebSocketService subscribes to Redis Pub/Sub (see app/services/websocket.py)
    so events published by any process (dialer, workers, another API replica)
    reach every connected dashboard client. Publish directly with a plain
    sync Redis client here, independent of the app's own event loop, to
    prove that cross-process delivery path actually works end-to-end.
    """
    r = sync_redis.Redis(
        host=os.environ.get("REDIS_HOST", "127.0.0.1"),
        port=int(os.environ.get("REDIS_PORT", 6379)),
    )
    try:
        with client.websocket_connect("/api/ws/dashboard") as ws:
            ws.receive_json()  # initial snapshot

            payload = {"type": "system", "data": {"message": "test-broadcast"}}
            r.publish("ws_channels:system", json.dumps(payload))

            received = ws.receive_json()
            assert received["type"] == "system"
            assert received["data"]["message"] == "test-broadcast"
    finally:
        r.close()
