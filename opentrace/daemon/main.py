# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Main daemon loop: poll → collect → push → save state → sleep."""


import json
import logging
import os
import signal
import socket
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone

from opentrace import __version__
from opentrace.daemon.collector import CollectResult, collect_file, extract_session_meta
from opentrace.daemon.config import DaemonConfig
from opentrace.daemon.push_status import init_session, record_push, record_push_metrics
from opentrace.daemon.pusher import Pusher
from opentrace.daemon.state import StateManager
from opentrace.daemon.watcher import ChangedFile, FileWatcher
from opentrace.schemas.unified import NormalizedMessage, SessionContext
from opentrace.utils.repo_resolver import resolve_global_identity, resolve_repo

logger = logging.getLogger("quickcall")


class Daemon:
    """The QuickCall OpenTrace daemon process."""

    def __init__(
        self,
        config: DaemonConfig | None = None,
        *,
        event_filter: Callable[[object], bool] | None = None,
        on_startup: Callable[[DaemonConfig], None] | None = None,
        message_augmenter: Callable[[object], None] | None = None,
    ) -> None:
        self.config = config or DaemonConfig()
        self.state_mgr = StateManager(state_file=self.config.state_file)
        self.watcher = FileWatcher(self.config, self.state_mgr)
        self.pusher = Pusher(config=self.config)
        self._shutdown = False
        self.device_name: str | None = None
        self.device_id: str | None = None
        self.global_email: str | None = None
        self.global_name: str | None = None
        self._event_filter = event_filter
        self._on_startup = on_startup
        self._message_augmenter = message_augmenter

    def run(self) -> None:
        """Main daemon loop."""
        self._setup_signals()
        self._write_pid()
        self.state_mgr.load()
        self._reconcile()
        self.state_mgr.prune_missing_files()
        self.device_name = socket.gethostname()
        self.device_id = self.config.device_id
        self.global_email, self.global_name = resolve_global_identity()
        init_session()
        self._truncate_err_log()
        if self._on_startup is not None:
            self._on_startup(self.config)

        logger.info(
            "quickcall-daemon started v%s (poll_interval=%.1fs, ingest=%s)",
            __version__,
            self.config.poll_interval,
            self.config.ingest_url,
        )

        try:
            while not self._shutdown:
                self._poll_cycle()
                self._sleep(self.config.poll_interval)
        except KeyboardInterrupt:
            pass
        finally:
            self._cleanup()

    def _reconcile(self) -> None:
        """Reconcile local state against server's file_progress markers.

        The server tracks the daemon's reported read position (last_line_read)
        via POST /api/file-progress. On restart, we use this to resume from
        where we left off rather than re-pushing data the server already has.

        Rules:
        - If server has a last_line_read for a file, use it as the resume point
          (this is the daemon's own reported position from a previous run).
        - If server has messages but no last_line_read, use max_line as fallback.
        - If server has nothing for a file, keep local state (conservative —
          don't reset, since ON CONFLICT dedup means messages may already exist).
        - For hash-based sources (gemini, cursor), only re-process if server
          has 0 messages AND no content_hash in file_progress.
        """
        try:
            server_state = self._fetch_server_state()
        except Exception as e:
            logger.warning("Reconciliation skipped — server unreachable: %s", e)
            return

        adjusted_count = 0
        for file_path, local in self.state_mgr.all_states().items():
            server = server_state.get(file_path)

            if server is None:
                # Server has no record at all — keep local state.
                # The daemon already pushed these messages (ON CONFLICT DO NOTHING
                # deduplicates), so resetting would just waste time re-pushing.
                logger.debug(
                    "Reconciliation: %s — no server record, keeping local (line %d)",
                    file_path, local.last_line_processed,
                )
                continue

            if local.source in ("claude_code", "codex_cli"):
                # JSONL sources: use server's last_line_read (daemon's reported
                # position) as authoritative, fall back to max_line from messages
                server_line = server.get("last_line_read") or server.get("max_line", 0)
                if server_line and server_line != local.last_line_processed:
                    logger.info(
                        "Reconciliation: %s — adjusting from line %d to server's %d",
                        file_path, local.last_line_processed, server_line,
                    )
                    local.last_line_processed = server_line
                    self.state_mgr.set_state(local)
                    adjusted_count += 1

            elif local.source in ("gemini_cli", "cursor"):
                # Hash-based sources: only re-process if server truly has nothing
                server_hash = server.get("content_hash")
                if server["message_count"] == 0 and not server_hash:
                    logger.info(
                        "Reconciliation: %s — server has 0 messages and no hash, re-processing",
                        file_path,
                    )
                    self.state_mgr.reset_state(file_path)
                    adjusted_count += 1

        if adjusted_count > 0:
            logger.info(
                "Reconciliation: adjusted %d file(s)", adjusted_count
            )
            self.state_mgr.save()
        else:
            logger.info("Reconciliation: all files in sync")

        self._backfill_session_metadata()

    @staticmethod
    def _read_first_timestamp(file_path: str) -> str:
        """Read the first timestamp from a session file.

        Claude Code / Codex CLI: JSONL with top-level "timestamp" field.
        Returns ISO 8601 string, or current UTC time as fallback.
        """
        fallback = datetime.now(timezone.utc).isoformat()
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for raw_line in f:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        data = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    ts = data.get("timestamp", "")
                    if ts and ts > "2000":
                        return ts
        except OSError:
            pass
        return fallback

    def _backfill_session_metadata(self) -> None:
        """Backfill git_branch/repo_name for sessions where resolve_repo previously failed.

        This handles the macOS TCC case: the daemon couldn't access protected folders
        (e.g. ~/Documents) when sessions were first processed. After the user grants
        access, this fills in the missing git metadata on daemon restart.

        Tracks already-backfilled sessions in a local file to avoid redundant
        resolve_repo calls (5 git subprocesses each) on every restart.
        """
        # Load set of already-backfilled session IDs
        backfilled_file = self.config.base_dir / "backfilled_sessions.json"
        backfilled: set[str] = set()
        try:
            if backfilled_file.exists():
                backfilled = set(json.loads(backfilled_file.read_text()))
        except (json.JSONDecodeError, OSError):
            pass

        updated = 0
        skipped = 0
        failed = 0

        for file_path, fstate in self.state_mgr.all_states().items():
            if fstate.source == "gemini_cli":
                continue

            session_id, cwd = extract_session_meta(file_path, fstate.source)
            if not cwd:
                skipped += 1
                continue

            if not session_id:
                skipped += 1
                continue

            # Skip sessions we've already backfilled successfully
            if session_id in backfilled:
                skipped += 1
                continue

            try:
                repo_info = resolve_repo(cwd)
            except Exception:
                failed += 1
                continue

            if not repo_info.git_branch and not repo_info.repo_name:
                skipped += 1
                continue

            ctx = SessionContext(
                cwd=cwd,
                git_branch=repo_info.git_branch,
                repo_name=repo_info.repo_name,
                repo_url=repo_info.repo_url,
                git_commit=repo_info.git_commit,
                org=self.config.org,
            )
            msg = NormalizedMessage(
                id=f"backfill-{session_id}",
                session_id=session_id,
                source=fstate.source,
                source_schema_version=1,
                msg_type="system",
                timestamp=self._read_first_timestamp(file_path),
                content="[backfill: git metadata]",
                session_context=ctx,
                raw_file_path=file_path,
            )
            if self.pusher.push([msg]):
                updated += 1
                backfilled.add(session_id)
            else:
                failed += 1

        # Persist backfilled set
        try:
            backfilled_file.write_text(json.dumps(sorted(backfilled)))
        except OSError:
            pass

        if updated > 0 or failed > 0:
            logger.info(
                "Backfill: updated %d sessions, skipped %d, failed %d",
                updated, skipped, failed,
            )

    def _fetch_server_state(self) -> dict[str, dict]:
        """GET /api/sync from the ingest server, return dict keyed by file_path."""
        url = urllib.parse.urljoin(self.config.ingest_url, "/api/sync")
        req = urllib.request.Request(url, method="GET")
        if self.config.api_key:
            req.add_header("X-API-Key", self.config.api_key)
        with urllib.request.urlopen(req, timeout=10) as resp:
            rows = json.loads(resp.read())
        return {row["raw_file_path"]: row for row in rows}

    _MAX_ACCUMULATE = 2000  # Cap in-memory messages before mid-cycle flush

    def _poll_cycle(self) -> None:
        """One poll-collect-push cycle (accumulate-then-flush).

        Phase 1: Collect messages from all changed files
        Phase 2: Push accumulated messages in batch_size chunks
        Phase 3: Bulk-report progress for successfully-pushed files
        Phase 4: Advance state only for files whose messages were fully pushed
        """
        _profiling = self.config.profile_polls
        if _profiling:
            wall_start = time.perf_counter()
            cpu_start = time.process_time()

        changed_files = self.watcher.get_changed_files()

        if _profiling:
            t_scan = time.perf_counter()

        # Process smaller sources first so they don't starve behind large backlogs
        changed_files.sort(key=lambda f: f.size)

        # Phase 1: Collect all messages and build progress reports
        collected: list[tuple[list, CollectResult, ChangedFile]] = []
        all_messages: list[tuple[object, int]] = []  # (message, file_index)
        total_message_count = 0

        for changed in changed_files:
            if self._shutdown:
                break

            existing_state = self.state_mgr.get_state(changed.path)

            try:
                result = collect_file(
                    changed,
                    existing_state,
                    device_name=self.device_name,
                    device_id=self.device_id,
                    global_email=self.global_email,
                    global_name=self.global_name,
                    org=self.config.org,
                )
            except Exception as e:
                logger.error("Failed to collect %s: %s", changed.path, e)
                if existing_state:
                    existing_state.retry_count += 1
                    existing_state.last_error = str(e)
                    existing_state.last_mtime = changed.mtime
                    existing_state.last_size = changed.size
                    self.state_mgr.set_state(existing_state)
                continue

            # Scoped mode: skip files whose session cwd is not in scope
            # Gemini uses projectHash instead of cwd, so exempt it from filtering
            if self.config.scoped_mode and result.messages and changed.source != "gemini_cli":
                cwd = None
                for msg in result.messages:
                    if msg.session_context and msg.session_context.cwd:
                        cwd = msg.session_context.cwd
                        break
                if not self.config.is_path_in_scope(cwd):
                    logger.debug(
                        "Scoped filter: skipping %s (cwd=%s)", changed.path, cwd
                    )
                    # Advance local state so we don't re-process, but don't
                    # push messages or report progress to server
                    self.state_mgr.set_state(result.new_state)
                    continue

            filtered_messages = result.messages
            if self._event_filter is not None and result.messages:
                filtered_messages = [msg for msg in result.messages if self._event_filter(msg)]

            if self._message_augmenter is not None and filtered_messages:
                for msg in filtered_messages:
                    try:
                        self._message_augmenter(msg)
                    except Exception:
                        logger.warning("message_augmenter raised; continuing", exc_info=True)

            file_idx = len(collected)
            collected.append((filtered_messages, result, changed))

            for msg in filtered_messages:
                all_messages.append((msg, file_idx))
            total_message_count += len(filtered_messages)

            # Mid-cycle flush if accumulation exceeds cap
            if total_message_count >= self._MAX_ACCUMULATE:
                remaining = len(changed_files) - len(collected)
                logger.info(
                    "Accumulation cap reached (%d messages) — deferring %d file(s) to next cycle",
                    total_message_count, remaining,
                )
                break

        if _profiling:
            t_collect = time.perf_counter()

        # Phase 2: Push accumulated messages in batch_size chunks
        # Track which file indices had all their messages pushed
        failed_at: int | None = None  # index into all_messages where failure occurred

        for i in range(0, len(all_messages), self.config.batch_size):
            if self._shutdown:
                failed_at = i
                break
            batch_pairs = all_messages[i : i + self.config.batch_size]
            batch_msgs = [msg for msg, _ in batch_pairs]
            if not self.pusher.push(batch_msgs):
                failed_at = i
                break

        # Determine which files had ALL their messages successfully pushed
        if failed_at is not None:
            # Find which file indices were in the failed batch or later
            failed_file_indices = {idx for _, idx in all_messages[failed_at:]}
            successfully_pushed_indices = {
                idx for idx in range(len(collected))
                if idx not in failed_file_indices and collected[idx][0]  # has messages
            }
        else:
            successfully_pushed_indices = {
                idx for idx in range(len(collected)) if collected[idx][0]
            }

        # Also include files with no messages (state-only updates)
        no_message_indices = {
            idx for idx in range(len(collected)) if not collected[idx][0]
        }

        # Phase 3: Advance state and build progress reports for successful files
        progress_reports: list[dict] = []
        total_pushed = 0

        for idx in range(len(collected)):
            msgs, result, changed = collected[idx]

            if idx in successfully_pushed_indices or idx in no_message_indices:
                self.state_mgr.set_state(result.new_state)
                progress_reports.append({
                    "raw_file_path": changed.path,
                    "source": result.new_state.source,
                    "last_line_read": result.new_state.last_line_processed,
                    "content_hash": result.new_state.content_hash or None,
                })
                if msgs:
                    total_pushed += len(msgs)
            else:
                logger.warning(
                    "Push failed for %s — state not advanced", changed.path
                )

        # Record push stats
        if total_pushed > 0:
            # Group by source for record_push
            source_counts: dict[str, int] = {}
            for idx in successfully_pushed_indices:
                msgs, result, _ = collected[idx]
                src = result.new_state.source
                source_counts[src] = source_counts.get(src, 0) + len(msgs)
            for src, count in source_counts.items():
                record_push(src, count)

        if _profiling:
            t_push = time.perf_counter()

        # Bulk-report progress
        if progress_reports:
            if not self.pusher.report_progress_bulk(progress_reports):
                logger.warning(
                    "Bulk progress report failed for %d file(s) — server may re-push on restart",
                    len(progress_reports),
                )

        if _profiling:
            t_progress = time.perf_counter()

        # Record queue metrics
        record_push_metrics(self.pusher.queue_size, self.pusher.current_backoff)

        self.state_mgr.save()

        # Poll cycle profiling — enable with QUICKCALL_OPENTRACE_PROFILE_POLLS=1
        # Logs wall time, actual CPU time, and I/O wait (the difference)
        # per phase: scan (watcher), collect (file parsing), push (HTTP POST
        # to /ingest), progress (HTTP POST to /api/file-progress-bulk).
        # Use this to distinguish real CPU work from network I/O wait —
        # Activity Monitor / ps report both as "CPU" which is misleading.
        if _profiling:
            wall_total = time.perf_counter() - wall_start
            cpu_total = time.process_time() - cpu_start
            io_wait = wall_total - cpu_total
            if wall_total > 0.1 or total_message_count > 0:
                logger.info(
                    "poll: wall=%.2fs cpu=%.2fs io=%.2fs | "
                    "scan=%.2fs collect=%.2fs push=%.2fs progress=%.2fs | "
                    "%d files %d msgs",
                    wall_total, cpu_total, io_wait,
                    t_scan - wall_start,
                    t_collect - t_scan,
                    t_push - t_collect,
                    t_progress - t_push,
                    len(changed_files), total_message_count,
                )

    def _sleep(self, duration: float) -> None:
        """Sleep that respects shutdown signal."""
        end = time.monotonic() + duration
        while not self._shutdown and time.monotonic() < end:
            time.sleep(max(0, min(0.5, end - time.monotonic())))

    _ERR_LOG_MAX_LINES = 1000

    def _truncate_err_log(self) -> None:
        """Keep opentrace.err to last _ERR_LOG_MAX_LINES lines."""
        err_file = self.config.base_dir / "quickcall.err"
        if not err_file.is_file():
            return
        try:
            lines = err_file.read_text().splitlines()
            if len(lines) <= self._ERR_LOG_MAX_LINES:
                return
            truncated = lines[-self._ERR_LOG_MAX_LINES:]
            err_file.write_text("\n".join(truncated) + "\n")
            logger.info("Truncated opentrace.err from %d to %d lines", len(lines), len(truncated))
        except OSError as e:
            logger.debug("Failed to truncate opentrace.err: %s", e)

    def _setup_signals(self) -> None:
        """Register signal handlers for graceful shutdown."""
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum: int, frame: object) -> None:
        logger.info("Received signal %d, shutting down...", signum)
        self._shutdown = True

    def _write_pid(self) -> None:
        """Write PID file, killing any existing daemon process first."""
        self.config.base_dir.mkdir(parents=True, exist_ok=True)
        if self.config.pid_file.exists():
            try:
                old_pid = int(self.config.pid_file.read_text().strip())
                if old_pid == os.getpid():
                    pass  # it's us, skip
                else:
                    os.kill(old_pid, 0)  # check if process exists
                    logger.warning("Killing existing daemon (PID %d)", old_pid)
                    os.kill(old_pid, signal.SIGTERM)
                    for _ in range(30):
                        try:
                            os.kill(old_pid, 0)
                        except ProcessLookupError:
                            break
                        time.sleep(0.1)
                    else:
                        try:
                            os.kill(old_pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    logger.info("Previous daemon (PID %d) terminated", old_pid)
            except (ValueError, ProcessLookupError):
                logger.info("Removing stale PID file")
            except PermissionError:
                logger.warning("Cannot kill existing daemon (permission denied)")
        self.config.pid_file.write_text(str(os.getpid()))
        version_file = self.config.base_dir / "daemon_version"
        version_file.write_text(__version__)

    def _cleanup(self) -> None:
        """Clean up on shutdown."""
        logger.info("quickcall-daemon shutting down")
        self.state_mgr.save()
        try:
            self.config.pid_file.unlink(missing_ok=True)
        except OSError:
            pass


def run(
    *,
    event_filter: Callable[[object], bool] | None = None,
    on_startup: Callable[[DaemonConfig], None] | None = None,
    message_augmenter: Callable[[object], None] | None = None,
) -> int:
    """Run the daemon with optional startup hooks.

    Default kwargs preserve historical behavior.
    """
    daemon = Daemon(
        event_filter=event_filter,
        on_startup=on_startup,
        message_augmenter=message_augmenter,
    )
    daemon.run()
    return 0
