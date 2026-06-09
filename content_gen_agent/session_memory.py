from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# SessionMemory class
# ---------------------------------------------------------------------------

class SessionMemory:
    """
    Thread-safe in-process session memory.

    Stores a compact summary of each completed Content Creator Agent run.
    All data lives in a plain Python list — no DB, no files, no external deps.
    """

    def __init__(self) -> None:
        self._runs: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    # ── Write ─────────────────────────────────────────────────────────────

    def add(
        self,
        output: Any,            # ContentCreatorOutput
        config: dict[str, Any],
    ) -> None:
        """
        Extracts a compact summary from a completed run and stores it.

        Parameters
        ----------
        output : ContentCreatorOutput
            The Pydantic output model from ContentCreatorAgent.run().
        config : dict
            The brand configuration dict used for that run.
        """
        # ── Extract topics from generated posts ───────────────────────────
        topics: list[str] = [
            post.get("topic", "")
            for post in (output.generated_posts or [])
            if post.get("topic")
        ]

        # ── Extract campaign names ────────────────────────────────────────
        campaign_names: list[str] = [
            c.get("name", "")
            for c in (output.campaign_ideas or [])
            if c.get("name")
        ]

        # ── Extract pillar summary ────────────────────────────────────────
        pillars: list[str] = [
            f"{p.get('name', '?')} ({p.get('percentage', 0)}%)"
            for p in (output.content_pillars or [])
        ]

        # ── Extract top hashtags across all platforms ─────────────────────
        hashtags: list[str] = []
        seen_ht: set[str] = set()
        for post in (output.generated_posts or []):
            for ht in post.get("hashtags", []):
                if ht and ht not in seen_ht:
                    seen_ht.add(ht)
                    hashtags.append(ht)
                if len(hashtags) >= 15:
                    break
            if len(hashtags) >= 15:
                break

        # ── Build compact run record ──────────────────────────────────────
        run_record: dict[str, Any] = {
            "run_number":       len(self._runs) + 1,
            "run_id":           output.run_id,
            "timestamp":        datetime.now(timezone.utc).isoformat(),
            "status":           output.status,
            "brand_name":       config.get("brand_name", ""),
            "industry":         config.get("industry", ""),
            "country":          config.get("country", ""),
            "city":             config.get("city", ""),
            "foundation_date":  config.get("foundation_date", ""),
            "platforms":        config.get("social_platforms", []),
            "posts_requested":  config.get("posts_per_month", 0),
            "posts_generated":  len(output.generated_posts or []),
            "campaigns":        len(output.campaign_ideas or []),
            "has_anniversary":  output.anniversary_campaign is not None,
            "evidence_sources": output.summary.get("evidence_sources_used", 0),
            "total_duration_ms":output.summary.get("total_duration_ms", 0),
            "pillars":          pillars,
            "topics":           topics,
            "campaign_names":   campaign_names,
            "hashtags":         hashtags,
            "errors":           len(output.errors or []),
            "strategic_goal":   (
                (output.content_strategy or {}).get("strategic_goal", "")
            )[:200] if output.content_strategy else "",
        }

        with self._lock:
            self._runs.append(run_record)

    # ── Read ──────────────────────────────────────────────────────────────

    def has_runs(self) -> bool:
        """Returns True if at least one run has been stored."""
        with self._lock:
            return len(self._runs) > 0

    def last_run(self) -> dict[str, Any] | None:
        """Returns the most recent run record, or None."""
        with self._lock:
            return self._runs[-1] if self._runs else None

    def get_all_runs(self) -> list[dict[str, Any]]:
        """Returns a copy of all stored run records."""
        with self._lock:
            return list(self._runs)

    def get_previous_brands(self) -> list[str]:
        """Returns list of brand names from all previous runs."""
        with self._lock:
            return [r["brand_name"] for r in self._runs]

    def get_previous_topics(self) -> list[str]:
        """Returns all topics generated across all runs (deduplicated)."""
        with self._lock:
            seen: set[str] = set()
            topics: list[str] = []
            for r in self._runs:
                for t in r.get("topics", []):
                    if t and t not in seen:
                        seen.add(t)
                        topics.append(t)
            return topics

    def get_previous_campaign_names(self) -> list[str]:
        """Returns all campaign names generated across all runs."""
        with self._lock:
            seen: set[str] = set()
            names: list[str] = []
            for r in self._runs:
                for n in r.get("campaign_names", []):
                    if n and n not in seen:
                        seen.add(n)
                        names.append(n)
            return names

    def get_context(self) -> str:
        """
        Returns a formatted context block summarising all previous runs.
        Used for display in the terminal and optionally injected into
        LLM prompts for multi-run awareness.

        Returns empty string if no runs have been stored yet.
        """
        with self._lock:
            if not self._runs:
                return ""

        runs = self.get_all_runs()

        lines: list[str] = [
            f"SESSION MEMORY — {len(runs)} previous run(s) this session",
            "=" * 55,
        ]

        for run in runs:
            duration_s = run.get("total_duration_ms", 0) / 1000
            lines.append(
                f"\nRun #{run['run_number']} | {run['brand_name']} "
                f"({run['industry']}) | {run['city']}, {run['country']}"
            )
            lines.append(
                f"  Status    : {run['status'].upper()} | "
                f"{run['posts_generated']}/{run['posts_requested']} posts | "
                f"{run['campaigns']} campaigns | "
                f"{duration_s:.0f}s"
            )
            lines.append(
                f"  Platforms : {', '.join(run['platforms'])}"
            )
            if run.get("pillars"):
                lines.append(
                    f"  Pillars   : {' | '.join(run['pillars'])}"
                )
            if run.get("strategic_goal"):
                goal = run["strategic_goal"]
                lines.append(
                    f"  Goal      : {goal[:120]}{'...' if len(goal) > 120 else ''}"
                )
            if run.get("campaign_names"):
                lines.append(
                    f"  Campaigns : {', '.join(run['campaign_names'])}"
                )
            if run.get("has_anniversary"):
                lines.append("  Anniversary campaign: YES ⭐")

        lines.append("\n" + "=" * 55)
        return "\n".join(lines)

    def summary(self) -> str:
        """
        Returns a compact one-line-per-run summary for the terminal header.
        """
        with self._lock:
            if not self._runs:
                return "  No previous runs this session."
            lines = []
            for run in self._runs:
                status_icon = {
                    "success": "✓",
                    "partial": "⚠",
                    "failed":  "✗",
                }.get(run["status"], "?")
                lines.append(
                    f"  {status_icon} Run #{run['run_number']} | "
                    f"{run['brand_name']} | "
                    f"{run['posts_generated']}/{run['posts_requested']} posts | "
                    f"{run['campaigns']} campaigns | "
                    f"{run['status'].upper()}"
                )
            return "\n".join(lines)

    def clear(self) -> None:
        """Wipes all stored runs from the session."""
        with self._lock:
            self._runs.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._runs)

    def __repr__(self) -> str:
        return f"SessionMemory(runs={len(self)})"


# ---------------------------------------------------------------------------
# Module-level singleton
# One instance per Python process — shared across all imports.
# ---------------------------------------------------------------------------

_session_memory = SessionMemory()


def get_session_memory() -> SessionMemory:
    """Returns the module-level singleton SessionMemory instance."""
    return _session_memory
