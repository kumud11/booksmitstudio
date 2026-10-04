"""Voicekeeper agent.

The brief asks for "the same tone and voice across all three chapters", which is a
book-level property that no single-chapter review can see. This agent compares
the chapters against each other and flags where the voice drifts.

It is cheap, deterministic and it catches the failure the Editor structurally
cannot: three individually clean chapters written at three different registers.
"""

from __future__ import annotations

import re
from statistics import mean

from ..models import Draft, Issue, Report, Severity, Verdict
from ..validators import _split_sentences, count_words
from .base import Agent

# Preferred terms. If two chapters call the same thing different things, a first-time
# reader notices, even when each chapter reads well on its own.
TERM_PREFERENCE = {
    "app": r"\bapplication\b",
    "cellphone": r"\bcell phone\b",
    "mobile phone": r"\bcellphone\b",
    "internet connection": r"\bnetwork connection\b",
    "payment": r"\bpayment method\b",
}

SECOND_PERSON_MIN = 3
SECOND_PERSON_MAX = 26


class VoicekeeperAgent(Agent):
    role = "voicekeeper"
    name = "Voicekeeper"

    def run(self, drafts: list[Draft]) -> Report:
        report = Report(agent=self.name)
        if len(drafts) < 2:
            self.say("only one chapter; nothing to compare")
            return report

        self._check_term_drift(drafts, report)
        self._check_register(drafts, report)
        self._check_rhythm(drafts, report)
        self._check_opener_closer(drafts, report)
        self._check_prose_continuity(drafts, report)

        report.verdict = (
            Verdict.REVISE if any(i.severity is Severity.MAJOR for i in report.issues)
            else Verdict.PASS
        )
        report.metrics["chapters"] = str(len(drafts))
        self._say(report)
        self.ledger.record_report(report)
        return report

    # ----------------------------------------------------------------- checks
    def _check_term_drift(self, drafts, report) -> None:
        seen: dict[str, dict[int, int]] = {}
        for draft in drafts:
            lowered = draft.body.lower()
            for canonical, variant in TERM_PREFERENCE.items():
                hits = len(re.findall(variant, lowered, re.I))
                if hits:
                    seen.setdefault(variant, {})[draft.chapter_index] = hits
        for variant, per_chapter in seen.items():
            if len(per_chapter) > 1:
                report.issues.append(Issue(
                    Severity.MINOR, "term-drift",
                    f"'{variant.strip(chr(92)+'b')}' appears in chapters "
                    f"{sorted(per_chapter)}; use one term throughout",
                    "", "harmonise_terms",
                ))

    def _check_register(self, drafts, report) -> None:
        for draft in drafts:
            body = draft.body
            second = len(re.findall(r"\byou\b|\byour\b", body, re.I))
            if second < SECOND_PERSON_MIN:
                report.issues.append(Issue(
                    Severity.MAJOR, "voice-distance",
                    f"ch{draft.chapter_index} addresses the reader only {second} time(s); "
                    "the voice elsewhere is a mentor talking to 'you'",
                    f"ch{draft.chapter_index}", "increase_second_person",
                ))
            if second > SECOND_PERSON_MAX:
                report.issues.append(Issue(
                    Severity.MINOR, "voice-overfamiliar",
                    f"ch{draft.chapter_index} uses 'you' {second} times; that can read "
                    "as pushy",
                    f"ch{draft.chapter_index}", "reduce_second_person",
                ))
            passive = len(re.findall(r"\b(?:is|are|was|were|be|been)\s+\w+(?:ed|en)\b",
                                     body, re.I))
            ratio = passive / max(1, len(_split_sentences(body)))
            if ratio > 0.22:
                report.issues.append(Issue(
                    Severity.MINOR, "passive-heavy",
                    f"ch{draft.chapter_index} is {ratio:.0%} passive; the mentor voice "
                    "is more direct",
                    f"ch{draft.chapter_index}", "use_active_voice",
                ))

    def _check_rhythm(self, drafts, report) -> None:
        averages = {}
        for draft in drafts:
            lengths = [count_words(s) for s in _split_sentences(draft.body)]
            if lengths:
                averages[draft.chapter_index] = mean(lengths)
        if len(averages) < 2:
            return
        spread = max(averages.values()) - min(averages.values())
        if spread > 8:
            report.issues.append(Issue(
                Severity.MINOR, "rhythm-drift",
                "mean sentence length differs by "
                f"{spread:.1f} words across chapters "
                f"({', '.join(f'ch{k}: {v:.1f}' for k, v in sorted(averages.items()))})",
                "", "even_out_rhythm",
                "Bring the outliers towards the book average.",
            ))

    def _check_opener_closer(self, drafts, report) -> None:
        for draft in drafts:
            first = _split_sentences(draft.body)
            if first:
                opener = first[0]
                if not re.search(r"\byou\b|\byour\b", opener, re.I):
                    report.issues.append(Issue(
                        Severity.MINOR, "opener-distance",
                        f"ch{draft.chapter_index} opens without addressing the reader "
                        "directly, unlike the other chapters",
                        f"ch{draft.chapter_index}", "rewrite_opener",
                    ))
            closing = draft.takeaway_line()
            if closing and not closing.rstrip().endswith((".", "!", "?")):
                report.issues.append(Issue(
                    Severity.MINOR, "takeaway-punctuation",
                    f"ch{draft.chapter_index} takeaway has no closing punctuation",
                    f"ch{draft.chapter_index}", "shorten_takeaway",
                ))

    def _check_prose_continuity(self, drafts, report) -> None:
        """Consecutive chapters should not repeat the same opening gambit."""
        openers = []
        for draft in drafts:
            sentences = _split_sentences(draft.body)
            if sentences:
                openers.append((draft.chapter_index, sentences[0][:40]))
        seen: dict[str, list[int]] = {}
        for index, opener in openers:
            head = " ".join(opener.lower().split()[:4])
            seen.setdefault(head, []).append(index)
        for head, indices in seen.items():
            if len(indices) > 1:
                report.issues.append(Issue(
                    Severity.MINOR, "repeated-opener",
                    f"chapters {indices} open with the same words ({head!r})",
                    "", "rewrite_opener",
                ))

    # ---------------------------------------------------------------- logging
    def _say(self, report: Report) -> None:
        self.say(
            f"{len(report.issues)} cross-chapter issue(s) -> "
            f"{report.verdict.value.upper()}"
        )
        for issue in report.issues:
            self.say(f"    [{issue.severity.value}] {issue.code}: {issue.message}")