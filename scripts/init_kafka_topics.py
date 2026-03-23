"""
scripts/init_kafka_topics.py
─────────────────────────────────────────────────────────────────────────────
Creates all required Kafka topics for Sentinel V2.
Safe to run multiple times — skips topics that already exist.
─────────────────────────────────────────────────────────────────────────────
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from confluent_kafka.admin import AdminClient, NewTopic
from confluent_kafka.error import KafkaException
from config.settings import get_settings

settings = get_settings()


# Topic configurations
# (topic_name, num_partitions, replication_factor, config_overrides)
TOPICS = [
    (
        settings.TOPIC_RAW_TRANSACTIONS,
        16,   # high parallelism — main ingestion topic
        1,
        {"retention.ms": str(7 * 24 * 60 * 60 * 1000)},   # 7 days
    ),
    (
        settings.TOPIC_TRANSACTION_PULSE,
        16,
        1,
        {"retention.ms": str(30 * 24 * 60 * 60 * 1000)},  # 30 days
    ),
    (
        settings.TOPIC_SCORES_PULSE,
        8,
        1,
        {"retention.ms": str(30 * 24 * 60 * 60 * 1000)},  # 30 days
    ),
    (
        settings.TOPIC_ALERTS_HIGH,
        4,
        1,
        {"retention.ms": str(7 * 24 * 60 * 60 * 1000)},   # 7 days
    ),
    (
        settings.TOPIC_INTERVENTIONS_SENT,
        4,
        1,
        {"retention.ms": str(90 * 24 * 60 * 60 * 1000)},  # 90 days
    ),
    (
        settings.TOPIC_DLQ_ERRORS,
        4,
        1,
        {"retention.ms": str(30 * 24 * 60 * 60 * 1000)},  # 30 days
    ),
]


def init_topics():
    admin = AdminClient({
        "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
    })

    # Get existing topics
    try:
        metadata = admin.list_topics(timeout=10)
        existing = set(metadata.topics.keys())
    except KafkaException as e:
        print(f"  ✗ Cannot connect to Kafka at {settings.KAFKA_BOOTSTRAP_SERVERS}")
        print(f"    Error: {e}")
        print("    Is Kafka running? Try: docker compose up -d kafka")
        return False

    to_create = []
    for topic_name, partitions, replication, config in TOPICS:
        if topic_name in existing:
            print(f"  - {topic_name} (already exists)")
        else:
            to_create.append(NewTopic(
                topic=topic_name,
                num_partitions=partitions,
                replication_factor=replication,
                config=config,
            ))

    if not to_create:
        print("  All topics already exist.")
        return True

    results = admin.create_topics(to_create)
    all_ok = True
    for topic_name, future in results.items():
        try:
            future.result()
            print(f"  ✓ Created: {topic_name}")
        except KafkaException as e:
            print(f"  ✗ Failed to create {topic_name}: {e}")
            all_ok = False

    return all_ok


if __name__ == "__main__":
    print("\nInitialising Kafka topics...")
    success = init_topics()
    if success:
        print("Done.\n")
    else:
        sys.exit(1)