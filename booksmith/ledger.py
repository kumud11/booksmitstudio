"""The shared blackboard.

Agents never call each other. They read the ledger, write their own artefacts
into it, and return a decision. The orchestrator is the only thing that decides
what happens next. That keeps the interaction rules in one readable place.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path

from .models import BookPlan, Claim, Draft, Issue, Report, Severity, Source, Verdict


class Ledger:
    def __init__(self) -> None:
        self.spec = None
        self.brief: dict = {}
        self.plan: BookPlan | None = None
        self.sources: dict[str, Source] = {}
        self.claims: dict[str, Claim] = {}
        self.drafts: dict[int, Draft] = {}
        self.reports: list[Report] = []
        self.decisions: list[dict] = []
        self.trace: list[dict] = []
        self.started = time.time()

    # --------------------------------------------------------- spec accessors
    def seeds(self) -> tuple:
        """Candidate sources for this book, from its spec."""
        return self.spec.seeds() if self.spec is not None else ()

    def seed_by_key(self) -> dict:
        return self.spec.seed_by_key() if self.spec is not None else {}

    @property
    def probe_slots(self) -> dict:
        return dict(self.spec.probe_slots) if self.spec is not None else {}

    @property
    def corroboration(self) -> dict:
        return dict(self.spec.corroboration) if self.spec is not None else {}

    # ------------------------------------------------------------- bookkeeping
    def note(self, agent: str, event: str, **detail) -> None:
        self.trace.append(
            {
                "t": round(time.time() - self.started, 3),
                "agent": agent,
                "event": event,
                **detail,
            }
        )

    def decide(self, actor: str, decision: str, reason: str, **detail) -> None:
        self.decisions.append(
            {
                "t": round(time.time() - self.started, 3),
                "actor": actor,
                "decision": decision,
                "reason": reason,
                **detail,
            }
        )

    def record_report(self, report: Report, chapter_index: int | None = None) -> None:
        report.metrics.setdefault("elapsed_s", f"{time.time() - self.started:.1f}")
        self.reports.append(report)
        self.note(
            report.agent,
            "review",
            chapter=chapter_index,
            verdict=report.verdict.value,
            blocking=len(report.blocking()),
            major=len(report.major()),
            minor=len(report.minor()),
        )

    # ------------------------------------------------------------------ reads
    def verified_sources(self) -> list[Source]:
        return sorted(
            (s for s in self.sources.values() if s.usable),
            key=lambda s: (s.authority, s.key),
        )

    def source(self, key: str) -> Source | None:
        return self.sources.get(key)

    def verified_claims(self, slots: list[str] | None = None) -> list[Claim]:
        out = [c for c in self.claims.values() if c.verified]
        if slots:
            wanted = set(slots)
            out = [c for c in out if c.slot in wanted]
        return sorted(out, key=lambda c: c.id)

    def claims_for_chapter(self, chapter_index: int) -> list[Claim]:
        if not self.plan:
            return []
        chapter = next(
            (c for c in self.plan.chapters if c.index == chapter_index), None
        )
        if not chapter:
            return []
        slots = set()
        for movement in chapter.movements:
            slots.update(movement.slots)
        return self.verified_claims(sorted(slots))

    def issues_for_chapter(self, chapter_index: int, kinds=None) -> list[Issue]:
        out: list[Issue] = []
        for report in self.reports:
            for issue in report.issues:
                if issue.location.startswith(f"ch{chapter_index}"):
                    if kinds is None or issue.code in kinds:
                        out.append(issue)
        return out

    def unresolved_blocking(self) -> list[Issue]:
        """Blocking issues that were raised and never cleared by a later pass."""
        seen: dict[str, Issue] = {}
        for report in self.reports:
            for issue in report.blocking():
                seen[f"{issue.location}|{issue.code}|{issue.message}"] = issue
        resolved = set()
        for report in self.reports:
            if report.agent == "FactChecker" and report.verdict is Verdict.PASS:
                for issue in report.issues:
                    resolved.add(f"{issue.location}|{issue.code}|{issue.message}")
        return [i for k, i in seen.items() if k not in resolved]

    # ----------------------------------------------------------------- writing
    def add_source(self, source: Source) -> None:
        self.sources[source.key] = source

    def add_claim(self, claim: Claim) -> None:
        self.claims[claim.id] = claim

    def put_draft(self, draft: Draft) -> None:
        self.drafts[draft.chapter_index] = draft

    # ------------------------------------------------------------------ stats
    def stats(self) -> dict:
        by_sev = {s.value: 0 for s in Severity}
        for report in self.reports:
            for issue in report.issues:
                by_sev[issue.severity.value] += 1
        return {
            "sources_considered": len(self.sources),
            "sources_verified": len(self.verified_sources()),
            "claims_total": len(self.claims),
            "claims_verified": len([c for c in self.claims.values() if c.verified]),
            "chapters_drafted": len(self.drafts),
            "reviews": len(self.reports),
            "issues": by_sev,
            "elapsed_s": round(time.time() - self.started, 1),
        }

    # ---------------------------------------------------------------- persist
    def dump(self, path: Path) -> None:
        payload = {
            "stats": self.stats(),
            "spec": {
                "slug": getattr(self.spec, "slug", ""),
                "title": getattr(self.spec, "title", ""),
                "origin": getattr(self.spec, "origin", ""),
            } if self.spec is not None else {},
            "brief": self.brief,
            "plan": _jsonable(self.plan),
            "sources": {
                k: {
                    "org": s.org,
                    "title": s.title,
                    "url": s.url,
                    "published": s.published,
                    "tier": s.tier,
                    "slots": s.slots,
                    "reachable": s.reachable,
                    "status": s.status,
                    "status_detail": s.status_detail,
                    "confirmed_probes": s.confirmed_probes,
                    "evidence": {
                        k: {"snippet": v.get("snippet", ""), "match": v.get("match", "")}
                        for k, v in s.evidence.items()
                    },
                }
                for k, s in self.sources.items()
            },
            "claims": {
                k: {
                    "slot": c.slot,
                    "text": c.text,
                    "source_keys": c.source_keys,
                    "values": c.values,
                    "verified": c.verified,
                    "unsupported": c.unsupported,
                    "source_dead": c.source_dead,
                }
                for k, c in self.claims.items()
            },
            "reports": [
                {
                    "agent": r.agent,
                    "verdict": r.verdict.value,
                    "metrics": r.metrics,
                    "issues": [
                        {
                            "severity": i.severity.value,
                            "code": i.code,
                            "message": i.message,
                            "location": i.location,
                            "hint": i.hint,
                        }
                        for i in r.issues
                    ],
                }
                for r in self.reports
            ],
            "decisions": self.decisions,
            "trace": self.trace,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), "utf-8")


def _jsonable(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    return str(obj)