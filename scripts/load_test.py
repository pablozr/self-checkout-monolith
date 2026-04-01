import argparse
import asyncio
import hashlib
import hmac
import json
import statistics
import time
import uuid
from pathlib import Path
from typing import Any

import httpx


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run real load bursts against the running self-checkout API.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    checkout = subparsers.add_parser("checkout", help="Burst POST /checkout/stripe")
    checkout.add_argument("--base-url", default="http://127.0.0.1:8000")
    checkout.add_argument("--requests", type=int, default=25)
    checkout.add_argument("--concurrency", type=int, default=10)
    checkout.add_argument("--table", type=int, required=True)
    checkout.add_argument("--product-id", type=int, required=True)
    checkout.add_argument("--quantity", type=int, default=1)
    checkout.add_argument("--timeout", type=float, default=10.0)
    checkout.add_argument(
        "--idempotency-mode",
        choices=("same", "unique"),
        default="same",
        help="Use the same key to test dedupe or unique keys to test throughput.",
    )
    checkout.add_argument(
        "--shared-session",
        action="store_true",
        help="Reuse one prepared anon session across all requests.",
    )

    webhook = subparsers.add_parser("webhook", help="Burst POST /webhooks/stripe")
    webhook.add_argument("--base-url", default="http://127.0.0.1:8000")
    webhook.add_argument("--requests", type=int, default=25)
    webhook.add_argument("--concurrency", type=int, default=10)
    webhook.add_argument("--timeout", type=float, default=10.0)
    webhook.add_argument("--payload-file", required=True)
    webhook.add_argument("--webhook-secret", required=True)
    webhook.add_argument(
        "--event-id-mode",
        choices=("same", "unique"),
        default="same",
        help="Use same event id to test dedupe or unique ids to test throughput.",
    )

    return parser


def percentile(latencies_ms: list[float], p: float) -> float:
    if not latencies_ms:
        return 0.0
    ordered = sorted(latencies_ms)
    index = min(len(ordered) - 1, max(0, round((p / 100) * (len(ordered) - 1))))
    return ordered[index]


def print_report(title: str, results: list[dict[str, Any]], started_at: float) -> None:
    status_counts: dict[str, int] = {}
    message_counts: dict[str, int] = {}
    latencies = [result["latency_ms"] for result in results]

    for result in results:
        status_key = str(result.get("status_code", "error"))
        status_counts[status_key] = status_counts.get(status_key, 0) + 1

        message = result.get("message") or result.get("detail") or result.get("error") or "<empty>"
        message_counts[message] = message_counts.get(message, 0) + 1

    duration_s = max(time.perf_counter() - started_at, 0.001)
    print(f"\n=== {title} ===")
    print(f"requests={len(results)} duration={duration_s:.2f}s rps={len(results) / duration_s:.2f}")
    print(
        "latency_ms "
        f"min={min(latencies):.2f} avg={statistics.mean(latencies):.2f} "
        f"p50={percentile(latencies, 50):.2f} p95={percentile(latencies, 95):.2f} max={max(latencies):.2f}"
    )
    print("status_counts:")
    for key, value in sorted(status_counts.items()):
        print(f"  {key}: {value}")
    print("message_counts:")
    for key, value in sorted(message_counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {value}x {key}")


def build_stripe_signature(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    signed_at = timestamp or int(time.time())
    signed_payload = f"{signed_at}.".encode("utf-8") + payload
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={signed_at},v1={digest}"


async def prepare_checkout_session(
    client: httpx.AsyncClient,
    base_url: str,
    table: int,
    product_id: int,
    quantity: int,
) -> str:
    menu_response = await client.get(f"{base_url}/menu", params={"table": table})
    menu_response.raise_for_status()

    anon_session = client.cookies.get("anon_session")
    if not anon_session:
        raise RuntimeError("anon_session cookie was not returned by GET /menu")

    add_response = await client.post(
        f"{base_url}/cart/items",
        json={"productId": product_id, "quantity": quantity},
    )
    add_response.raise_for_status()
    return anon_session


async def run_checkout(args: argparse.Namespace) -> int:
    timeout = httpx.Timeout(args.timeout)
    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
    session_cookies: list[str] = []

    async with httpx.AsyncClient(timeout=timeout, limits=limits, follow_redirects=True) as setup_client:
        if args.shared_session:
            cookie = await prepare_checkout_session(
                setup_client,
                args.base_url,
                args.table,
                args.product_id,
                args.quantity,
            )
            session_cookies = [cookie] * args.requests
        else:
            for _ in range(args.requests):
                client = httpx.AsyncClient(timeout=timeout, limits=limits, follow_redirects=True)
                try:
                    cookie = await prepare_checkout_session(
                        client,
                        args.base_url,
                        args.table,
                        args.product_id,
                        args.quantity,
                    )
                    session_cookies.append(cookie)
                finally:
                    await client.aclose()

    semaphore = asyncio.Semaphore(args.concurrency)
    shared_key = f"load-{uuid.uuid4()}"

    async with httpx.AsyncClient(timeout=timeout, limits=limits, follow_redirects=True) as client:
        async def fire(index: int) -> dict[str, Any]:
            async with semaphore:
                idempotency_key = shared_key if args.idempotency_mode == "same" else f"{shared_key}-{index}"
                started = time.perf_counter()
                try:
                    response = await client.post(
                        f"{args.base_url}/checkout/stripe",
                        headers={"Idempotency-Key": idempotency_key},
                        cookies={"anon_session": session_cookies[index]},
                    )
                    latency_ms = (time.perf_counter() - started) * 1000
                    payload = response.json()
                    return {
                        "status_code": response.status_code,
                        "message": payload.get("message"),
                        "detail": payload.get("detail"),
                        "latency_ms": latency_ms,
                    }
                except Exception as exc:
                    return {
                        "status_code": "error",
                        "error": str(exc),
                        "latency_ms": (time.perf_counter() - started) * 1000,
                    }

        started_at = time.perf_counter()
        results = await asyncio.gather(*[fire(i) for i in range(args.requests)])

    print_report("checkout burst", results, started_at)
    return 0


def load_webhook_payload(payload_file: str) -> dict[str, Any]:
    payload = json.loads(Path(payload_file).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("payload file must contain a JSON object")
    return payload


async def run_webhook(args: argparse.Namespace) -> int:
    template = load_webhook_payload(args.payload_file)
    timeout = httpx.Timeout(args.timeout)
    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
    semaphore = asyncio.Semaphore(args.concurrency)
    base_event_id = str(template.get("id") or f"evt_load_{uuid.uuid4().hex}")

    async with httpx.AsyncClient(timeout=timeout, limits=limits, follow_redirects=True) as client:
        async def fire(index: int) -> dict[str, Any]:
            async with semaphore:
                event = json.loads(json.dumps(template))
                if args.event_id_mode == "unique":
                    event["id"] = f"{base_event_id}_{index}"
                else:
                    event["id"] = base_event_id

                body = json.dumps(event, separators=(",", ":")).encode("utf-8")
                signature = build_stripe_signature(body, args.webhook_secret)
                started = time.perf_counter()
                try:
                    response = await client.post(
                        f"{args.base_url}/webhooks/stripe",
                        content=body,
                        headers={
                            "Content-Type": "application/json",
                            "Stripe-Signature": signature,
                        },
                    )
                    latency_ms = (time.perf_counter() - started) * 1000
                    payload = response.json()
                    return {
                        "status_code": response.status_code,
                        "message": payload.get("message"),
                        "detail": payload.get("detail"),
                        "latency_ms": latency_ms,
                    }
                except Exception as exc:
                    return {
                        "status_code": "error",
                        "error": str(exc),
                        "latency_ms": (time.perf_counter() - started) * 1000,
                    }

        started_at = time.perf_counter()
        results = await asyncio.gather(*[fire(i) for i in range(args.requests)])

    print_report("webhook burst", results, started_at)
    return 0


async def main_async() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "checkout":
        return await run_checkout(args)
    if args.command == "webhook":
        return await run_webhook(args)

    raise ValueError(f"Unsupported command: {args.command}")


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
