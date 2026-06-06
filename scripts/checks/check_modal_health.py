#!/usr/bin/env python3
"""
Quick health check script for Modal-deployed backend.
Tests /health endpoint and WebSocket connectivity.

Usage:
  python scripts/checks/check_modal_health.py <modal_url>
  python scripts/checks/check_modal_health.py https://username--orchgraph-rag.modal.run
"""

import asyncio
import sys
import time

import httpx
import websockets


async def check_http_health(base_url: str) -> bool:
    """Test /health endpoint."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{base_url}/health")
            if response.status_code == 200:
                print(f"✓ /health endpoint: {response.json()}")
                return True
            else:
                print(f"✗ /health returned {response.status_code}")
                return False
    except Exception as e:
        print(f"✗ /health connection failed: {e}")
        return False


async def check_websocket(base_url: str) -> bool:
    """Test WebSocket connectivity on /interview/ws."""
    ws_url = base_url.replace("https://", "wss://").replace("http://", "ws://")
    ws_url = f"{ws_url}/interview/ws"

    try:
        async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as websocket:
            # Send a simple test frame (in practice, would be actual interview data)
            await websocket.send("ping")
            response = await asyncio.wait_for(websocket.recv(), timeout=5)
            print(f"✓ WebSocket /interview/ws: connected and responsive")
            return True
    except asyncio.TimeoutError:
        print("✗ WebSocket timeout (may still be healthy if server processing)")
        return False
    except Exception as e:
        print(f"✗ WebSocket connection failed: {e}")
        return False


async def main(base_url: str) -> None:
    """Run health checks."""
    base_url = base_url.rstrip("/")
    print(f"Checking Modal deployment at {base_url}")
    print("-" * 60)

    start = time.time()

    # Test HTTP health
    http_ok = await check_http_health(base_url)

    # Test WebSocket
    ws_ok = await check_websocket(base_url)

    elapsed = time.time() - start
    print("-" * 60)

    if http_ok:
        print(f"✓ Health check passed in {elapsed:.2f}s")
        sys.exit(0)
    else:
        print(f"✗ Health check failed after {elapsed:.2f}s")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    url = sys.argv[1]
    asyncio.run(main(url))
