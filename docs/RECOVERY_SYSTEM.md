# System Recovery & State Tracking

## Overview

The API implements a comprehensive state tracking system using `metadata.json` as the single source of truth. Every task operation is recorded step-by-step with verification, enabling complete recovery from any failure point.

## State Progression

### 1. Task Initialization (`queued`)

**When**: Immediately after task creation (async mode)

**Content**:
```json
{
  "task_id": "uuid",
  "status": "queued",
  "created_at": "timestamp",
  "input": {
    "url": "video_url",
    "quality": "quality_value"
  },
  "webhook": {...},
  "client_meta": {...}
}
```

**Verification**: File write verified by re-reading and comparing content

**Log**: `✓ Initial metadata.json created and verified`

---

### 2. Download Start (`downloading`)

**When**: Background task starts processing

**Updates**:
- `status`: `"queued"` → `"downloading"`
- `started_at`: timestamp added

**Verification**: Write verified

**Log**: `✓ Metadata updated: queued -> downloading`

---

### 3. Video Info Retrieved (`processing`)

**When**: After yt-dlp extracts video information

**Updates**:
- `status`: `"downloading"` → `"processing"`
- `video_info_retrieved_at`: timestamp added
- `output` section created with:
  - `video_id`
  - `title`
  - `duration`
  - `resolution`
  - `ext`

**Verification**: Write verified

**Log**: `✓ Metadata updated: video info added`

---

### 4. Task Completed (`completed`)

**When**: Download finished successfully

**Final Structure**:
```json
[{
  "task_id": "uuid",
  "status": "completed",
  "created_at": "timestamp",
  "completed_at": "timestamp",
  "expires_at": "timestamp",
  "input": {
    "video_url": "url",
    "operations": ["download_video"],
    "operations_count": 1,
    "video_id": "id",
    "title": "title",
    "duration": seconds,
    "resolution": "WxH",
    "ext": "mp4"
  },
  "output": {
    "output_files": [{
      "filename": "file.mp4",
      "download_path": "/download/...",
      "download_url_internal": "http://...",
      "expires_at": "timestamp"
    }],
    "total_files": 1,
    "metadata_url_internal": "http://...",
    "ttl_seconds": 86400,
    "ttl_human": "24h"
  },
  "webhook": {...},
  "client_meta": {...}
}]
```

**Verification**: Write verified

**Logs**:
- `Saving final metadata.json (status=completed)`
- `✓ Final metadata.json saved and verified successfully`

---

### 5. Task Failed (`error`)

**When**: Any exception during processing

**Structure**:
```json
{
  "task_id": "uuid",
  "status": "error",
  "operation": "download_video_async",
  "error_type": "unavailable|blocked|network|...",
  "error_message": "Human readable message",
  "user_action": "Recommended action",
  "raw_error": "Full error text (truncated 1000 chars)",
  "failed_at": "timestamp",
  "webhook": {...},
  "client_meta": {...}
}
```

**Verification**: Write verified

**Logs**:
- `ERROR: [exception details]`
- `Saving error metadata (exception: error_type)`
- `✓ Error metadata saved and verified`

---

## Recovery Scenarios

### Scenario 1: Crash During Download

**Indicators**:
- metadata.json status: `"downloading"` or `"processing"`
- No `completed_at` or `failed_at` timestamp
- Task still in Redis with status `"downloading"`

**Recovery Action**:
1. Read metadata.json to determine exact state
2. Check if video file exists in output directory
3. If file exists → resume from verification step
4. If file missing → restart download from beginning
5. Update metadata.json with new attempt timestamp

---

### Scenario 2: Verification Failure

**Indicators**:
- Log: `✗ CRITICAL: Failed to save metadata: [error]`
- metadata.json may be incomplete or corrupted

**Recovery Action**:
1. Check if backup metadata exists (previous state)
2. Reconstruct metadata from Redis task data
3. Re-verify file integrity (checksum/size)
4. Retry metadata save with verification
5. If all fails, mark task for manual review

---

### Scenario 3: Network Error Mid-Process

**Indicators**:
- metadata.json status: `"processing"`
- `video_info_retrieved_at` exists
- No output files

**Recovery Action**:
1. Video info already extracted (saved in metadata)
2. Retry download using saved video_id
3. No need to re-extract info from YouTube
4. Continue from download step

---

### Scenario 4: Webhook Delivery Failure

**Indicators**:
- metadata.json complete with status `"completed"`
- webhook_state.json shows `"status": "pending"`
- Multiple failed attempts logged

**Recovery Action**:
1. Task completed successfully (metadata.json is authoritative)
2. Background webhook resender will retry
3. Client can poll `/task_status` or `/download/{id}/metadata.json`
4. No data loss - file and metadata intact

---

## Verification System

Every metadata write is verified with this process:

```python
def save_task_metadata(task_id, metadata, verify=True):
    # 1. Write to file
    with open(meta_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    # 2. Verify (if enabled)
    if verify:
        with open(meta_path, 'r') as f:
            verified = json.load(f)
        
        if verified != metadata:
            raise Exception("Verification failed")
        
        logger.debug("✓ Metadata verified successfully")
```

**Benefits**:
- Catches write errors immediately
- Prevents corrupted metadata files
- Ensures disk I/O completed successfully
- Provides clear failure point in logs

---

## Troubleshooting Guide

### Finding Failure Point

```bash
# Check metadata progression
docker exec container cat /app/tasks/{task_id}/metadata.json

# Check logs for specific task
docker logs container | grep "{task_id_prefix}"

# Look for verification marks
docker logs container | grep "✓"
docker logs container | grep "✗"
```

### Log Markers

- `✓ Initial metadata.json created and verified` → Task initialized
- `✓ Metadata updated: queued -> downloading` → Download started
- `✓ Metadata updated: video info added` → Video extracted
- `✓ Final metadata.json saved and verified` → Success
- `✓ Error metadata saved and verified` → Error recorded
- `✗ CRITICAL: Failed to save metadata` → Write failure

### Recovery Commands

```bash
# Check task state
curl http://localhost:5000/task_status/{task_id}

# Get full metadata
curl http://localhost:5000/download/{task_id}/metadata.json

# Check if file exists
docker exec container ls -lh /app/tasks/{task_id}/output/

# Restart stuck task (manual intervention)
# 1. Get metadata state
# 2. Delete corrupted files
# 3. Re-queue task with same parameters
```

---

## Integration with Webhooks

### Success Flow

1. Task completes → metadata.json saved
2. Webhook receives **exact** metadata.json content
3. No reconstruction - direct transmission
4. If webhook fails → metadata.json still intact
5. Background resender retries using metadata.json

### Error Flow

1. Error occurs → error metadata.json saved
2. Webhook receives error metadata directly
3. Contains: error_type, error_message, user_action
4. Client can decide retry strategy
5. metadata.json provides full error context

---

## Best Practices

### For Operators

1. **Monitor logs** for `✗ CRITICAL` markers
2. **Check metadata.json** first when investigating issues
3. **Verify disk space** - insufficient space causes write failures
4. **Review webhook_state.json** for delivery issues
5. **Enable DEBUG logging** for detailed state tracking

### For Developers

1. **Always verify** metadata writes (verify=True)
2. **Log state transitions** with descriptive markers
3. **Include timestamps** at every stage
4. **Preserve error context** (raw_error, stack traces)
5. **Test recovery scenarios** in development

### For API Clients

1. **Use /task_status** for quick checks
2. **Read metadata.json** for complete state
3. **Check webhook delivery** via webhook_state.json
4. **Implement exponential backoff** for retries
5. **Store task_id** for recovery reference

---

## Performance Impact

**Verification Overhead**:
- Read-verify adds ~1-2ms per write
- Negligible compared to download time (seconds/minutes)
- Critical for data integrity
- Can be disabled for batch operations (verify=False)

**Storage**:
- metadata.json: ~2-5KB per task
- Minimal compared to video files (MB-GB)
- Compressed by filesystem (ext4, btrfs)
- Auto-deleted after TTL expires

---

## Future Enhancements

### Planned Features

1. **Checkpoint system** - Save intermediate download progress
2. **Metadata history** - Keep previous versions for rollback
3. **Atomic writes** - Use temp files + rename for safety
4. **Compression** - Gzip old metadata.json files
5. **Metrics** - Track verification success rates

### Pro Version

- PostgreSQL metadata storage
- Transaction support for atomic updates
- Replication for high availability
- Point-in-time recovery
- Audit trail for all state changes
