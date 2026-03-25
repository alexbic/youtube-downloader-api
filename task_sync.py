#!/usr/bin/env python3
"""
Task Synchronization Module

Shared functions for syncing task data between disk (metadata.json) and Redis cache.
Used by both app.py and orchestrator.py to avoid code duplication.

Architecture:
- Disk (metadata.json) = source of truth
- Redis = fast cache with TTL
"""

import os
import json
import logging

logger = logging.getLogger(__name__)

# Redis configuration
REDIS_TASK_PREFIX = "task:"
TASK_TTL_MINUTES = int(os.getenv('TASK_TTL_MINUTES', 1440))  # 24 hours default


def sync_task_to_redis(redis_conn, task_id: str, metadata: dict, ttl_seconds: int = None):
    """
    Sync task metadata to Redis cache.

    Args:
        redis_conn: Redis connection object
        task_id: Task identifier
        metadata: Full metadata dictionary
        ttl_seconds: TTL in seconds (default: TASK_TTL_MINUTES * 60)

    Returns:
        bool: True if synced successfully, False otherwise
    """
    if ttl_seconds is None:
        ttl_seconds = TASK_TTL_MINUTES * 60

    try:
        redis_conn.setex(
            f"{REDIS_TASK_PREFIX}{task_id}",
            ttl_seconds,
            json.dumps(metadata)
        )
        logger.debug(f"[{task_id[:8]}] ✓ Synced to Redis (TTL: {ttl_seconds}s)")
        return True
    except Exception as e:
        logger.debug(f"[{task_id[:8]}] Redis sync failed (non-critical): {e}")
        return False


def save_metadata_to_disk(task_id: str, metadata: dict, tasks_dir: str = "/app/tasks") -> bool:
    """
    Save metadata.json to disk using atomic write.

    Args:
        task_id: Task identifier
        metadata: Full metadata dictionary
        tasks_dir: Base directory for tasks (default: /app/tasks)

    Returns:
        bool: True if saved successfully, False otherwise
    """
    try:
        task_dir = os.path.join(tasks_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)

        metadata_path = os.path.join(task_dir, "metadata.json")
        temp_path = metadata_path + ".tmp"
        
        # Atomic write: write to temp file then rename
        with open(temp_path, 'w') as f:
            json.dump(metadata, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
            
        os.replace(temp_path, metadata_path)

        logger.debug(f"[{task_id[:8]}] ✓ Saved to disk (atomic): {metadata_path}")
        return True
    except Exception as e:
        logger.error(f"[{task_id[:8]}] Failed to save metadata to disk: {e}")
        return False


def save_and_sync_metadata(
    redis_conn,
    task_id: str,
    metadata: dict,
    tasks_dir: str = "/app/tasks",
    sync_redis: bool = True,
    ttl_seconds: int = None
) -> bool:
    """
    Save metadata to disk and optionally sync to Redis.

    This is the recommended way to update task metadata from both app.py and orchestrator.py.

    Args:
        redis_conn: Redis connection object
        task_id: Task identifier
        metadata: Full metadata dictionary
        tasks_dir: Base directory for tasks
        sync_redis: Whether to sync to Redis (default: True)
        ttl_seconds: Redis TTL in seconds

    Returns:
        bool: True if disk save successful (Redis sync is non-critical)
    """
    # 1. Save to disk first (source of truth)
    disk_ok = save_metadata_to_disk(task_id, metadata, tasks_dir)

    if not disk_ok:
        return False

    # 2. Sync to Redis (optional, non-critical)
    if sync_redis and redis_conn:
        sync_task_to_redis(redis_conn, task_id, metadata, ttl_seconds)

    return True


def update_webhook_state(
    redis_conn,
    task_id: str,
    webhook_updates: dict,
    tasks_dir: str = "/app/tasks",
    ttl_seconds: int = None
) -> bool:
    """
    Update webhook state in metadata.json and sync to Redis.

    This is a specialized function for webhook updates to avoid reading/writing full metadata.

    Args:
        redis_conn: Redis connection object
        task_id: Task identifier
        webhook_updates: Dictionary with webhook fields to update
        tasks_dir: Base directory for tasks
        ttl_seconds: Redis TTL in seconds

    Returns:
        bool: True if updated successfully
    """
    try:
        # Read current metadata
        metadata_path = os.path.join(tasks_dir, task_id, "metadata.json")

        if not os.path.exists(metadata_path):
            logger.warning(f"[{task_id[:8]}] Metadata not found, cannot update webhook state")
            return False

        with open(metadata_path, 'r') as f:
            metadata = json.load(f)

        # Update webhook state
        if 'webhook' not in metadata:
            metadata['webhook'] = {}

        metadata['webhook'].update(webhook_updates)

        # Save and sync
        return save_and_sync_metadata(
            redis_conn,
            task_id,
            metadata,
            tasks_dir,
            sync_redis=True,
            ttl_seconds=ttl_seconds
        )

    except Exception as e:
        logger.error(f"[{task_id[:8]}] Failed to update webhook state: {e}")
        return False
