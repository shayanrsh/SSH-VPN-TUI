from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from config import EXPIRY_CHECK_SECONDS, ResetMode, TRAFFIC_SAMPLE_SECONDS
from db import Database
from system import lock_user, unlock_user
from traffic import TrafficManager

logger = logging.getLogger(__name__)


class Scheduler:
    """Background scheduler for traffic sampling and expiry enforcement."""
    def __init__(self, db: Database, traffic: TrafficManager) -> None:
        """Create a scheduler bound to the database and traffic manager."""
        self.db = db
        self.traffic = traffic
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        """Start the background thread."""
        self.thread.start()

    def stop(self) -> None:
        """Stop the background thread."""
        self.stop_event.set()
        self.thread.join(timeout=3)

    def _run(self) -> None:
        last_expiry = 0.0
        last_sample = 0.0
        while not self.stop_event.is_set():
            now = time.time()
            if now - last_sample >= TRAFFIC_SAMPLE_SECONDS:
                self._sample_traffic()
                last_sample = now
            if now - last_expiry >= EXPIRY_CHECK_SECONDS:
                self._check_expiry()
                self._check_resets()
                last_expiry = now
            self.stop_event.wait(1)

    def _sample_traffic(self) -> None:
        users = self.db.list_users()
        usernames = [user.username for user in users if user.deleted_at is None]
        samples = self.traffic.sample(usernames)
        updates: list[tuple[str, dict[str, int]]] = []
        sample_map = {sample.username: sample.used_bytes for sample in samples}
        for sample in samples:
            updates.append((sample.username, {"traffic_used_bytes": sample.used_bytes}))
        if updates:
            self.db.update_bulk(updates)

        for user in users:
            if user.deleted_at is not None:
                continue
            current_used = sample_map.get(user.username, user.traffic_used_bytes)
            if user.traffic_limit_bytes > 0 and current_used >= user.traffic_limit_bytes:
                try:
                    lock_user(user.username)
                    self.db.update_user_record(user.username, {"is_active": 0})
                    self.db.record_event(user.username, "traffic_limit", "Traffic limit reached")
                except Exception as exc:
                    logger.error("Traffic limit enforcement failed: %s", exc)

    def _check_expiry(self) -> None:
        now = datetime.now(timezone.utc)
        for user in self.db.list_users():
            if user.deleted_at is not None:
                continue
            if user.expiry_at and user.is_active:
                expiry = datetime.fromisoformat(user.expiry_at)
                if expiry <= now:
                    try:
                        lock_user(user.username)
                        self.db.update_user_record(user.username, {"is_active": 0})
                        self.db.record_event(user.username, "expired", "User expired")
                    except Exception as exc:
                        logger.error("Expiry enforcement failed: %s", exc)

    def _check_resets(self) -> None:
        now = datetime.now(timezone.utc)
        for user in self.db.list_users():
            if user.deleted_at is not None:
                continue
            if user.traffic_reset_mode == ResetMode.UNLIMITED:
                continue
            if not user.last_traffic_reset:
                self.db.reset_traffic(user.username)
                continue

            last_reset = datetime.fromisoformat(user.last_traffic_reset)
            should_reset = False
            if user.traffic_reset_mode == ResetMode.DAILY:
                should_reset = now.date() != last_reset.date() and now.hour == 0
            elif user.traffic_reset_mode == ResetMode.WEEKLY:
                should_reset = now.weekday() == 0 and now.hour == 0 and now.date() != last_reset.date()
            elif user.traffic_reset_mode == ResetMode.MONTHLY:
                should_reset = now.day == 1 and now.hour == 0 and now.date() != last_reset.date()

            if should_reset:
                try:
                    self.traffic.reset_user(user.username)
                except Exception as exc:
                    logger.error("Traffic counter reset failed: %s", exc)
                self.db.reset_traffic(user.username)
                try:
                    if not user.expiry_at or datetime.fromisoformat(user.expiry_at) > now:
                        unlock_user(user.username)
                        self.db.update_user_record(user.username, {"is_active": 1})
                    self.db.record_event(user.username, "traffic_reset", "Traffic reset")
                except Exception as exc:
                    logger.error("Traffic reset unlock failed: %s", exc)
