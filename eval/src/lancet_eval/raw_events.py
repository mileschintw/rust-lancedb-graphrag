"""Bounded raw-SSE stream event sink and deterministic baseline selection."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lancet_eval.corpus import GoldQuestion

logger = logging.getLogger(__name__)

RAW_EVENT_BYTES_PER_UNIT = 32768
RAW_EVENT_BYTES_PER_RUN = 67108864
BASELINE_SAMPLE_SIZE = 25


def baseline_sample_ids(questions: list[GoldQuestion]) -> set[str]:
    """Deterministically select the baseline question IDs.

    Sorts question IDs ascending and selects the first 25.
    """
    sorted_ids = sorted(q.id for q in questions)
    return set(sorted_ids[:BASELINE_SAMPLE_SIZE])


class RawEventSink:
    """Bounded filesystem sink for forensic raw SSE events."""

    def __init__(self, run_dir: Path | str) -> None:
        self.run_dir = Path(run_dir)
        self.raw_dir = self.run_dir / "raw_events"
        self.total_bytes_written = 0
        self._run_cap_exceeded = False

    def write_events(
        self,
        *,
        corpus: str,
        question_id: str,
        graph_arm: str,
        events: list[dict[str, Any]],
        dropped_frames: int = 0,
        truncated: bool = False,
    ) -> Path | None:
        """Write raw events for a work unit.

        Guaranteed never to raise: logs warning and returns None on error.
        """
        if self._run_cap_exceeded:
            return None

        import lancet_eval.raw_events as mod

        bytes_per_unit = getattr(
            mod, "RAW_EVENT_BYTES_PER_UNIT", RAW_EVENT_BYTES_PER_UNIT
        )
        bytes_per_run = getattr(
            mod, "RAW_EVENT_BYTES_PER_RUN", RAW_EVENT_BYTES_PER_RUN
        )

        try:
            target_dir = self.raw_dir / graph_arm
            target_dir.mkdir(parents=True, exist_ok=True)
            target_file = target_dir / f"{question_id}.jsonl"

            lines_to_write: list[str] = []
            unit_bytes = 0
            unwritten_count = dropped_frames
            was_unit_truncated = truncated

            for idx, ev in enumerate(events):
                record = {
                    "seq": idx,
                    "event": ev.get("event", ""),
                    "data": ev.get("data", ""),
                }
                line = json.dumps(record, ensure_ascii=False) + "\n"
                line_bytes = len(line.encode("utf-8"))

                if unit_bytes + line_bytes > bytes_per_unit:
                    was_unit_truncated = True
                    unwritten_count += len(events) - idx
                    break

                lines_to_write.append(line)
                unit_bytes += line_bytes

            if was_unit_truncated:
                trunc_record = {
                    "seq": len(lines_to_write),
                    "event": "truncation",
                    "data": {
                        "truncated": True,
                        "unwritten_frames": unwritten_count,
                    },
                }
                trunc_line = json.dumps(trunc_record, ensure_ascii=False) + "\n"
                lines_to_write.append(trunc_line)
                unit_bytes += len(trunc_line.encode("utf-8"))

            if self.total_bytes_written + unit_bytes > bytes_per_run:
                self._run_cap_exceeded = True
                backstop_note = self.raw_dir / "RUN_CAP_EXCEEDED.txt"
                try:
                    backstop_note.write_text(
                        f"Run-level byte cap of {bytes_per_run} exceeded. "
                        "Retention stopped.\n",
                        encoding="utf-8",
                    )
                except Exception:
                    pass
                return None

            with open(target_file, "w", encoding="utf-8", newline="\n") as f:
                f.writelines(lines_to_write)

            self.total_bytes_written += unit_bytes
            return target_file

        except Exception as exc:
            logger.warning(
                "Failed to write raw events for %s:%s: %s",
                graph_arm,
                question_id,
                exc,
            )
            return None

