"""SSE broadcaster for live draft updates.

Maintains one Sleeper polling loop per active draft_id and fans out
pick/status events to all connected clients via per-client asyncio queues.

Capacity limits exist to bound memory growth from abusive clients (subscribing
to thousands of fake draft_ids to leak asyncio queues). The limits are well
above any legitimate friends-scale usage.
"""

import asyncio
import dataclasses
import json
import logging
from typing import Dict, List

from src.data_sources.sleeper_client import SleeperClient

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 2.0
_KEEPALIVE_INTERVAL = 15.0


class BroadcasterCapacityError(Exception):
    """Raised when DraftBroadcaster capacity caps are hit."""


class DraftBroadcaster:
    # Hard caps prevent unbounded memory growth from hostile clients.
    # Realistic peak for friends-scale beta is < 20 simultaneous drafts and
    # < 10 concurrent viewers per draft, so 50/50 is generous headroom.
    MAX_ACTIVE_DRAFTS = 50
    MAX_SUBSCRIBERS_PER_DRAFT = 50

    def __init__(self, client: SleeperClient):
        self._client = client
        self._tasks: Dict[str, asyncio.Task] = {}
        self._queues: Dict[str, List[asyncio.Queue]] = {}

    async def subscribe(self, draft_id: str) -> asyncio.Queue:
        existing = self._queues.get(draft_id)
        if existing is None:
            # New draft_id — enforce the global cap before allocating.
            if len(self._queues) >= self.MAX_ACTIVE_DRAFTS:
                logger.warning(
                    "DraftBroadcaster MAX_ACTIVE_DRAFTS=%d hit; rejecting draft_id=%s",
                    self.MAX_ACTIVE_DRAFTS,
                    draft_id,
                )
                raise BroadcasterCapacityError(
                    "Too many active drafts. Try again later."
                )
        else:
            # Existing draft — enforce the per-draft subscriber cap.
            if len(existing) >= self.MAX_SUBSCRIBERS_PER_DRAFT:
                logger.warning(
                    "DraftBroadcaster MAX_SUBSCRIBERS_PER_DRAFT=%d hit for draft_id=%s",
                    self.MAX_SUBSCRIBERS_PER_DRAFT,
                    draft_id,
                )
                raise BroadcasterCapacityError(
                    "Too many viewers for this draft. Try again later."
                )
        queue: asyncio.Queue = asyncio.Queue()
        self._queues.setdefault(draft_id, []).append(queue)
        if draft_id not in self._tasks or self._tasks[draft_id].done():
            self._tasks[draft_id] = asyncio.create_task(self._poll(draft_id))
        return queue

    async def unsubscribe(self, draft_id: str, queue: asyncio.Queue) -> None:
        queues = self._queues.get(draft_id, [])
        try:
            queues.remove(queue)
        except ValueError:
            pass
        if not queues:
            self._queues.pop(draft_id, None)
            task = self._tasks.pop(draft_id, None)
            if task:
                task.cancel()

    def _broadcast(self, draft_id: str, event: dict) -> None:
        for q in self._queues.get(draft_id, []):
            q.put_nowait(event)

    async def _poll(self, draft_id: str) -> None:
        last_pick_count = 0
        last_status = None
        last_keepalive = asyncio.get_event_loop().time()

        while True:
            try:
                now = asyncio.get_event_loop().time()
                if now - last_keepalive >= _KEEPALIVE_INTERVAL:
                    self._broadcast(draft_id, {"type": "keepalive"})
                    last_keepalive = now

                picks = self._client.get_draft_picks(draft_id)
                if len(picks) > last_pick_count:
                    for pick in picks[last_pick_count:]:
                        self._broadcast(draft_id, {
                            "type": "pick",
                            "data": dataclasses.asdict(pick),
                        })
                    last_pick_count = len(picks)

                details = self._client.get_draft_details(draft_id)
                if details:
                    status = details.get("status")
                    if status != last_status:
                        if last_status is not None:
                            self._broadcast(draft_id, {"type": "status", "data": {"status": status}})
                        last_status = status
                    if status == "complete":
                        break

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Draft poll error for %s", draft_id, exc_info=True)

            await asyncio.sleep(_POLL_INTERVAL)
