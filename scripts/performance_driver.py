"""Bounded open-loop HTTP generator; private session inputs arrive only on stdin."""

import asyncio
import json
import math
import sys
import time
from collections import Counter

import httpx


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)] if ordered else None


def distribution(values):
    return {"p50": percentile(values, 0.5), "p95": percentile(values, 0.95), "max": max(values, default=0)}


def summarize(results, scheduled_rate=None, duration=None):
    return {
        "requests": len(results), "scheduled_rate_rps": scheduled_rate, "schedule_seconds": duration,
        "status_counts": dict(Counter(str(item["status"]) for item in results)),
        "latency_ms": distribution([item["elapsed_ms"] for item in results]),
        "dispatch_lag_ms": distribution([item["dispatch_lag_ms"] for item in results]),
        "http_duration_ms": distribution([item["http_duration_ms"] for item in results]),
        "observations": results,
        "all_responses_within_2_seconds": all(item["elapsed_ms"] <= 2000 for item in results),
    }


async def request_sample(client, config, session, scheduled_at, method="GET", body=None):
    headers = {"Cookie": f"{config['session_cookie']}={session['opaque']}"}
    if method == "POST":
        headers.update({"Origin": config["origin"], "X-CSRF-Token": session["csrf"]})
    dispatched_at, identifier = time.perf_counter(), None
    try:
        response = await client.request(method, config["endpoint"], headers=headers, json=body)
        status, identifier = response.status_code, response.headers.get("x-correlation-id")
    except httpx.HTTPError as error:
        status = type(error).__name__
    finished = time.perf_counter()
    return {"status": status, "elapsed_ms": round((finished - scheduled_at) * 1000, 3),
            "dispatch_lag_ms": round(max(0, dispatched_at - scheduled_at) * 1000, 3),
            "http_duration_ms": round((finished - dispatched_at) * 1000, 3), "correlation_id": identifier}


def client(config, connections):
    limits = httpx.Limits(max_connections=connections, max_keepalive_connections=connections)
    return httpx.AsyncClient(base_url=config["base_url"], timeout=2, limits=limits, trust_env=False)


async def measured_phase(config, rate, duration=2):
    count, sessions = rate * duration, config["sessions"]
    async with client(config, count) as http:
        started, jobs = time.perf_counter(), []
        for index in range(count):
            scheduled_at = started + index / rate
            await asyncio.sleep(max(0, scheduled_at - time.perf_counter()))
            jobs.append(asyncio.create_task(request_sample(
                http, config, sessions[index % len(sessions)], scheduled_at,
            )))
        results = await asyncio.gather(*jobs)
    return {**summarize(results, rate, duration), "generator_connection_limit": count,
            "generator_connection_limit_covers_every_scheduled_arrival": True}


async def warmup(config):
    async with client(config, 10) as http:
        results = []
        for index in range(5):
            results.append(await request_sample(http, config, config["sessions"][index], time.perf_counter()))
        started = time.perf_counter()
        results += await asyncio.gather(*(
            request_sample(http, config, config["sessions"][index], started) for index in range(5, 10)
        ))
    return {"purpose": "Separate startup and connection warmup; excluded from measured arrivals",
            **summarize(results)}


async def simultaneous_fault(config):
    async with client(config, 40) as http:
        started = time.perf_counter()
        results = await asyncio.gather(*(
            request_sample(http, config, config["sessions"][index % len(config["sessions"])], started)
            for index in range(40)
        ))
    return summarize(results)


async def denied_probes(config):
    async with client(config, 20) as http:
        results = []
        for index in range(20):
            results.append(await request_sample(
                http, config, config["sessions"][index % len(config["sessions"])], time.perf_counter(),
                "POST", config["body"],
            ))
    return summarize(results)


async def run(config):
    handlers = {"warmup": warmup, "fault": simultaneous_fault, "deny": denied_probes}
    if config["operation"] == "load":
        return {str(rate): await measured_phase(config, rate) for rate in (10, 40, 160)}
    return await handlers[config["operation"]](config)


if __name__ == "__main__":
    configuration = json.load(sys.stdin)
    print(json.dumps(asyncio.run(run(configuration))))
