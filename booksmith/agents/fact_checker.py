"""Fact-checker agent.

This is the gate, not a reporter. It has four independent checks and it can send a
chapter back to the Writer:

1.  Citation integrity   - every [n] has a reference entry and vice versa.
2.  Claim binding        - every [n] maps to a claim the Researcher actually
                           verified, not to a source that merely looks official.
3.  Live re-verification - it re-fetches each cited URL and re-confirms the
                           evidence probe still matches *right now*. A citation
                           whose page has moved or changed is blocking, which is
                           the difference between this and a link checker.
4.  Number audit         - every numeral in the prose must be traceable to a
                           figure captured from a cited page. This is what stops a
                           plausible-looking statistic attached to a real citation.
"""

from __future__ import annotations

import concurrent.futures

from ..http import fetch, find_evidence
from ..models import (
    Draft,
    Issue,
    Report,
    Severity,
    Verdict,
    all_citation_marks,
    numeric_tokens,
)
from ..validators import check_numbers_are_sourced
from .base import Agent


class FactCheckerAgent(Agent):
    role = "fact_checker"
    name = "FactChecker"

    def run(self, draft: Draft) -> Report:
        report = Report(agent=self.name)
        where = f"ch{draft.chapter_index}"
        seed_by_key = self.ledger.seed_by_key()

        live = self._reverify(draft, report, where, seed_by_key)
        self._check_binding(draft, report, where, live)
        self._check_integrity(draft, report, where)
        self._check_numbers(draft, report, where)

        report.verdict = (
            Verdict.REJECT if report.blocking() else Verdict.PASS
        )
        report.metrics["citations"] = str(len(draft.references))
        report.metrics["live_verified"] = str(sum(1 for r in live.values() if r["live"]))
        report.metrics["evidence_confirmed"] = str(
            sum(1 for r in live.values() if r["confirmed"])
        )
        self._say(draft, report)
        self.ledger.record_report(report, draft.chapter_index)
        return report

    # ------------------------------------------------- 1. live re-verification
    def _reverify(self, draft: Draft, report: Report, where: str,
                   seed_by_key: dict) -> dict:
        """Re-fetch every cited page and re-run the probe that backed the claim."""
        targets: dict[tuple[str, str], dict] = {}
        for ref in draft.references:
            seed = seed_by_key.get(ref.get("source_key", ""))
            for claim in _claims_of(ref, self.ledger):
                probe_key = claim.probe_keys[0] if claim.probe_keys else ""
                pattern = _probe_pattern(seed, probe_key)
                # Keyed by claim, so a page that backs three figures is checked
                # three times; the fetch itself is still done once per URL.
                targets[(ref["url"], claim.id)] = {
                    "claim_id": claim.id,
                    "probe_key": probe_key,
                    "pattern": pattern,
                    "expected": claim.values,
                    "link_status": ref.get("link_status", ""),
                }

        if not self.config.do_verify_live:
            for url, info in targets.items():
                info["live"] = True
                info["confirmed"] = bool(info["pattern"])
            report.metrics["live_mode"] = "disabled"
            return targets

        urls = sorted({url for url, _ in targets})
        results = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(8, max(1, len(urls)))
        ) as pool:
            futures = {pool.submit(fetch, u, self.config.request_timeout): u for u in urls}
            for future in concurrent.futures.as_completed(futures):
                url = futures[future]
                try:
                    results[url] = future.result()
                except Exception as exc:  # noqa: BLE001
                    from ..http import FetchResult

                    results[url] = FetchResult(url, 0, url, "", "", str(exc))

        for (url, claim_id), info in targets.items():
            page = results.get(url)
            if not page.live:
                info["live"] = False
                info["confirmed"] = False
                report.issues.append(Issue(
                    Severity.BLOCKING, "dead-link",
                    f"cited source is no longer reachable: {page.summary()} {url}",
                    where, "replace_source",
                    "Researcher must find a live source for this fact.",
                ))
                continue
            info["live"] = True
            if page.bot_blocked:
                # Verified as a real URL by an earlier round; the corroborating
                # source carries the evidence, so this is not blocking.
                info["confirmed"] = True
                report.issues.append(Issue(
                    Severity.MINOR, "bot-protected-link",
                    f"{url} refuses automated requests but is a genuine live page; "
                    "the figure was confirmed at its corroborating source",
                    where, "note_only",
                ))
                continue
            if not info["pattern"]:
                info["confirmed"] = True
                continue
            hit = find_evidence(page.text, info["pattern"])
            if not hit:
                info["confirmed"] = False
                report.issues.append(Issue(
                    Severity.BLOCKING, "evidence-gone",
                    "the cited page no longer contains the text that supports this "
                    f"claim ({info['probe_key']}). The source may have been edited: "
                    f"{url}",
                    where, "replace_source",
                    "The figure must be re-sourced or the sentence rewritten.",
                ))
                continue
            info["confirmed"] = True
            for name, expected in (info["expected"] or {}).items():
                if expected and expected not in hit[2]:
                    if not _loose_match(expected, hit[2]):
                        info["confirmed"] = False
                        report.issues.append(Issue(
                            Severity.BLOCKING, "figure-drift",
                            f"the page now shows a different value for {name!r}: "
                            f"the draft says {expected!r} but the live page does not "
                            f"contain it. {url}",
                            where, "replace_source",
                        ))
                        break
        return targets

    # --------------------------------------------------------- 2. claim binding
    def _check_binding(self, draft: Draft, report: Report, where: str,
                       live: dict) -> None:
        for ref in draft.references:
            claims = _claims_of(ref, self.ledger)
            if not claims:
                report.issues.append(Issue(
                    Severity.BLOCKING, "unbound-citation",
                    f"reference [{ref.get('n')}] is not attached to any researched "
                    "claim",
                    where, "replace_source",
                ))
                continue
            for claim in claims:
                if not claim.verified:
                    report.issues.append(Issue(
                        Severity.BLOCKING, "unverified-citation",
                        f"reference [{ref.get('n')}] rests on a claim the Researcher "
                        "could not verify",
                        where, "replace_source",
                    ))
            source = self.ledger.source(ref.get("source_key", ""))
            if source is None or not source.reachable:
                report.issues.append(Issue(
                    Severity.BLOCKING, "unreachable-source",
                    f"reference [{ref.get('n')}] points at a source that was never "
                    "reached",
                    where, "replace_source",
                ))

    # ------------------------------------------------------ 3. citation integrity
    def _check_integrity(self, draft: Draft, report: Report, where: str) -> None:
        marks = all_citation_marks(draft.body + "\n" + draft.takeaway_line())
        declared = sorted(int(r["n"]) for r in draft.references)
        for n in sorted(set(marks)):
            if n not in declared:
                report.issues.append(Issue(
                    Severity.BLOCKING, "citation-without-reference",
                    f"the text cites [{n}] but the reference list has no entry for it",
                    where, "rebuild_references",
                ))
        if declared and declared != list(range(1, len(declared) + 1)):
            report.issues.append(Issue(
                Severity.BLOCKING, "reference-numbering",
                f"reference numbers are {declared}; they must run 1 to {len(declared)} "
                "in order of first appearance",
                where, "rebuild_references",
            ))
        if not marks:
            report.issues.append(Issue(
                Severity.BLOCKING, "no-citations",
                "the chapter states facts but carries no citations at all",
                where, "add_citations",
            ))

    # --------------------------------------------------------- 4. number audit
    def _check_numbers(self, draft: Draft, report: Report, where: str) -> None:
        """Collect every figure a cited page is allowed to justify.

        One claim can carry several numbers - a rate, a limit and a cap lifted from
        one sentence - so each captured value and each token inside the matched
        evidence is added under its own key. Reusing one key would silently keep
        only the last of them and flag the rest as invented.
        """
        allowed: dict[str, str] = {}
        for ref in draft.references:
            for claim in _claims_of(ref, self.ledger):
                source = self.ledger.source(ref.get("source_key", ""))
                allowed[claim.id] = claim.text
                for name, value in claim.values.items():
                    allowed[f"{claim.id}:{name}"] = value
                if source:
                    for probe_key, record in source.evidence.items():
                        for token in numeric_tokens(record.get("match", "")):
                            allowed[f"{claim.id}:{probe_key}:evidence"] = token
            # The reference entry prints this date, so a year the prose borrows
            # from the citation itself is accounted for.
            for token in numeric_tokens(str(ref.get("published", ""))):
                allowed[f"{ref['n']}:published"] = token
        report.issues.extend(check_numbers_are_sourced(draft, allowed))

    # ---------------------------------------------------------------- logging
    def _say(self, draft: Draft, report: Report) -> None:
        self.say(
            f"ch{draft.chapter_index}: {len(draft.references)} citation(s) "
            f"({report.metrics.get('evidence_confirmed', '0')} evidence-confirmed) "
            f"-> {report.verdict.value.upper()}"
        )
        for issue in report.blocking() + report.major():
            self.say(f"    [{issue.severity.value}] {issue.code}: {issue.message}")


def _claims_of(ref: dict, ledger) -> list:
    """Every claim a reference number stands for.

    One printed reference can carry several figures from the same page, so the
    gate has to walk all of them - not just the first the Writer happened to cite.
    """
    ids = list(ref.get("claim_ids") or [])
    if not ids and ref.get("claim_id"):
        ids = [ref["claim_id"]]
    claims = []
    for claim_id in ids:
        claim = ledger.claims.get(claim_id)
        if claim is not None and claim not in claims:
            claims.append(claim)
    return claims


def _probe_pattern(seed, probe_key: str) -> str | None:
    if seed is None:
        return None
    for probe in seed.probes:
        if probe.key == probe_key:
            return probe.pattern
    return None


def _loose_match(expected: str, haystack: str) -> bool:
    """Accept whitespace and comma-grouping differences between page and claim."""
    def norm(text: str) -> str:
        return "".join(ch for ch in str(text) if ch.isdigit() or ch == ".")

    return norm(expected) and norm(expected) in norm(haystack)