"""
realtime/kafka_consumer.py
─────────────────────────────────────────────────────────────────────────────
Kafka consumer. Reads sentinel.raw.transactions, drives PulseEngine,
publishes results to sentinel.transaction.pulse.
Failed messages go to sentinel.dlq.errors.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import signal
from datetime import datetime, timezone
from typing import Optional

from config.settings import get_settings
from schemas.transaction_event import TransactionEvent
from realtime.pulse_engine import PulseEngine

settings = get_settings()


class SentinelConsumer:

    def __init__(self, dry_run: bool = False):
        self.dry_run   = dry_run
        self._running  = False
        self._consumer = None
        self._producer = None
        self._redis    = None
        self.engine    = None

    def _setup(self):
        from confluent_kafka import Consumer, Producer
        import redis as redis_lib

        self._consumer = Consumer({
            "bootstrap.servers":    settings.KAFKA_BOOTSTRAP_SERVERS,
            "group.id":             "sentinel-pulse-consumer",
            "auto.offset.reset":    "latest",
            "enable.auto.commit":   False,
            "max.poll.interval.ms": 300000,
        })
        self._consumer.subscribe([settings.TOPIC_RAW_TRANSACTIONS])

        self._producer = Producer({
            "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
            "acks": "all",
        })

        try:
            self._redis = redis_lib.Redis(
                host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True)
            self._redis.ping()
        except Exception:
            self._redis = None

        self.engine = PulseEngine(redis_client=self._redis)

    def run(self, max_messages: Optional[int] = None):
        self._setup()
        self._running = True
        processed = errors = 0

        signal.signal(signal.SIGINT,  lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

        print(f"Consumer started — topic: {settings.TOPIC_RAW_TRANSACTIONS}")
        if self.dry_run:
            print("DRY RUN: no DB writes")

        try:
            while self._running:
                msg = self._consumer.poll(timeout=1.0)
                if msg is None:
                    continue
                if msg.error():
                    print(f"Consumer error: {msg.error()}")
                    continue
                try:
                    event  = TransactionEvent.from_kafka_payload(msg.value())
                    result = self.engine.process(event) if not self.dry_run else {"dry_run": True}
                    self._producer.produce(
                        topic=settings.TOPIC_TRANSACTION_PULSE,
                        key=event.customer_id.encode("utf-8"),
                        value=json.dumps(result).encode("utf-8"),
                    )
                    self._producer.poll(0)
                    self._consumer.commit(message=msg, asynchronous=False)
                    processed += 1
                    if not self.dry_run:
                        cat   = result.get("inferred_category", "UNKNOWN")
                        sev   = result.get("txn_severity", 0.0)
                        delta = result.get("delta_applied", 0.0)
                        s_bef = result.get("pulse_score_before", 0.0)
                        s_aft = result.get("pulse_score_after", 0.0)
                        label = result.get("risk_label", "?")
                        cid   = str(result.get("customer_id", "?"))[:12]
                        print(
                            f"[PULSE] {cid:<12}  {cat:<22}  "
                            f"sev={sev:.2f}  delta={delta:+.4f}  "
                            f"score={s_bef:.4f}→{s_aft:.4f}  {label}"
                        )
                    if processed % 100 == 0:
                        print(f"Processed: {processed}  Errors: {errors}")
                except Exception as e:
                    errors += 1
                    self._dlq(msg, str(e))
                    self._consumer.commit(message=msg, asynchronous=False)
                if max_messages and processed >= max_messages:
                    break
        finally:
            self._producer.flush(timeout=10)
            self._consumer.close()
            print(f"Consumer stopped. Processed: {processed}  Errors: {errors}")

    def stop(self):
        self._running = False

    def _dlq(self, msg, error_str):
        try:
            self._producer.produce(
                topic=settings.TOPIC_DLQ_ERRORS,
                value=json.dumps({
                    "original_topic": msg.topic(), "error": error_str,
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "payload": msg.value().decode("utf-8", errors="replace"),
                }).encode("utf-8"),
            )
        except Exception:
            pass


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run",      action="store_true")
    p.add_argument("--max-messages", type=int, default=None)
    args = p.parse_args()
    SentinelConsumer(dry_run=args.dry_run).run(max_messages=args.max_messages)