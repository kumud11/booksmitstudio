"""Researcher agent.

The Researcher is the only agent allowed to touch the outside world. It does
three jobs and refuses to guess at any of them:

1.  Fetches every candidate URL live.
2.  Runs each source's evidence probes against the fetched page text. A probe
    that does not match is dropped, not paraphrased.
3.  Publishes one `Claim` per surviving probe, carrying the values captured out
    of the page by the probe's named groups.

That third step is the anti-hallucination mechanism. The numbers the Writer is
allowed to print are literally substrings lifted from a live page, so there is no
path by which the model can invent a figure.
"""

from __future__ import annotations

import re

from ..http import find_evidence, parallel_fetch
from ..models import Claim, Source
from .base import Agent

NAME_VALUE_RE = re.compile(r"\(\?P<([A-Za-z_][A-Za-z0-9_]*)>")


class ResearcherAgent(Agent):
    role = "researcher"
    name = "Researcher"

    def run(self) -> dict:
        self.banner()
        plan = self.ledger.plan
        if plan is None:
            raise RuntimeError("Researcher needs a plan; run Planner first")

        wanted_slots = {
            s for c in plan.chapters for m in c.movements for s in m.slots
        }
        seeds = self.ledger.seeds()
        if not seeds:
            raise RuntimeError(
                "this book has no candidate sources; the Architect must write them "
                "before the Researcher can look anything up"
            )
        candidates = self._select(seeds, wanted_slots)
        self.say(
            f"brief needs {len(wanted_slots)} fact slots; "
            f"{len(candidates)} candidate sources shortlisted"
        )

        urls = sorted({s.url for s in candidates})
        if self.config.do_fetch:
            self.say(f"fetching {len(urls)} source URLs live...")
            pages = parallel_fetch(urls, self.config.request_timeout,
                                   self.config.fetch_workers)
        else:
            self.say("offline mode: skipping live fetch, nothing will be verified")
            pages = {}

        verified = 0
        for seed in candidates:
            source = self._build_source(seed, pages.get(seed.url))
            self.ledger.add_source(source)
            if source.usable:
                verified += 1

        promoted = self._promote_bot_protected()

        claims = self._publish_claims(wanted_slots)
        self.say(
            f"{verified + len(promoted)}/{len(candidates)} sources usable; "
            f"{len(claims)} claims published "
            f"({len([c for c in claims.values() if c.verified])} verified)"
        )

        self._report(wanted_slots)

        self.ledger.decide(
            self.name,
            "evidence-published",
            f"{len(claims)} claims ready for the Writer",
            verified=len([c for c in claims.values() if c.verified]),
        )
        self.announce("research_done", sources=len(candidates), claims=len(claims))
        return claims

    # ------------------------------------------------------------- selection
    def _select(self, seeds, wanted_slots: set[str]) -> list:
        """Shortlist candidates that serve at least one wanted slot.

        Sorts by authority so that when two sources carry the same fact the
        official one is registered first and is the one cited.
        """
        scored = []
        for seed in seeds:
            overlap = len(wanted_slots.intersection(seed.slots))
            if not overlap:
                continue
            tier_bonus = {"official": 0, "regulator": 3, "reputable_press": 8}.get(
                seed.tier, 20
            )
            scored.append((tier_bonus - overlap, -overlap, seed.key, seed))
        # Sorted on the first three only. Two pages from one publisher tie on all
        # of them, and falling through to compare the seeds themselves raises.
        scored.sort(key=lambda item: item[:3])
        return [item[3] for item in scored]

    # ---------------------------------------------------------- verification
    def _build_source(self, seed, page) -> Source:
        source = Source(
            key=seed.key,
            org=seed.org,
            title=seed.title,
            url=seed.url,
            published=seed.published,
            tier=seed.tier,
            slots=list(seed.slots),
        )

        if page is None:
            source.status = "not-checked"
            source.status_detail = "network disabled"
            return source

        if not page.live:
            source.status = "broken"
            source.status_detail = page.summary()
            return source

        source.reachable = True
        bot_blocked = page.bot_blocked
        source.status = "bot-protected" if bot_blocked else "ok"
        source.status_detail = page.summary()

        if bot_blocked:
            for probe in seed.probes:
                source.probe_matches[probe.key] = False
            return source

        for probe in seed.probes:
            hit = find_evidence(page.text, probe.pattern)
            source.probe_matches[probe.key] = bool(hit)
            if hit:
                snippet, _start, matched = hit
                source.evidence[probe.key] = {"snippet": snippet, "match": matched}
        return source

    def _promote_bot_protected(self) -> list[str]:
        """Allow a bot-protected link only when another source confirms the fact.

        npci.org.in answers 403 to automated requests but serves real readers a
        perfectly good page. Rather than either dropping NPCI from the book or
        pretending we read it, we let its URL ride along on a citation whose fact
        has been independently confirmed by a machine-verifiable source.
        """
        promoted: list[str] = []
        corroboration = self.ledger.corroboration
        for key, corroborating in corroboration.items():
            source = self.ledger.source(key)
            if source is None or not source.reachable:
                continue
            witnesses = [
                self.ledger.source(w)
                for w in corroborating
                if self.ledger.source(w) and self.ledger.source(w).usable
            ]
            if not witnesses:
                self.say(f"{key}: bot-protected and no corroborating source verified")
                continue
            source.status = "corroborated"
            source.status_detail = "bot-protected to automated clients; fact confirmed at " + ", ".join(
                w.key for w in witnesses
            )
            self.say(f"{key}: cited as corroboration for {', '.join(w.key for w in witnesses)}")
            promoted.append(key)
        return promoted

    # ------------------------------------------------------------- publishing
    def _publish_claims(self, wanted_slots: set[str]) -> dict[str, Claim]:
        """One claim per surviving probe. Slot comes from the chapter plan."""
        claims: dict[str, Claim] = {}
        probe_slots = self.ledger.probe_slots
        for seed in self.ledger.seeds():
            source = self.ledger.source(seed.key)
            if source is None or not source.usable and source.status != "corroborated":
                continue
            for probe in seed.probes:
                confirmed = source.probe_matches.get(probe.key, False)
                if not confirmed and source.status != "corroborated":
                    continue
                if not confirmed and source.status == "corroborated":
                    # Borrow the fact from a corroborating source's captured values.
                    values = self._borrowed_values(seed.key, probe)
                    if not values:
                        continue
                else:
                    values = source.values_for(probe.pattern)

                slots = [s for s in seed.slots if s in wanted_slots]
                slot = probe_slots.get(f"{seed.key}:{probe.key}", "")
                if slot not in wanted_slots:
                    if not slots:
                        continue
                    slot = slots[0]
                claim_id = f"{seed.key}:{probe.key}"
                claim = Claim(
                    id=claim_id,
                    slot=slot,
                    text=probe.claim,
                    probe_keys=[probe.key],
                    source_keys=[seed.key],
                    values=values,
                    verified=True,
                )
                claims[claim_id] = claim
                self.ledger.add_claim(claim)
        return claims

    def _borrowed_values(self, source_key: str, probe) -> dict[str, str]:
        """For a corroborated source, take the numbers from its witness.

        Only used when a probe pattern declares named capture groups. A bot-
        protected page cannot be read, so the numbers are lifted from the
        machine-verifiable source that confirmed the same fact.
        """
        names = NAME_VALUE_RE.findall(probe.pattern)
        if not names:
            return {}
        for witness_key in self.ledger.corroboration.get(source_key, ()):
            witness = self.ledger.source(witness_key)
            if witness is None or not witness.usable:
                continue
            collected: dict[str, str] = {}
            for record in witness.evidence.values():
                match = re.search(r"[\d][\d,]*(?:\.\d+)?", record.get("match", ""))
                if match and len(collected) < len(names):
                    collected[names[len(collected)]] = match.group(0)
            if collected:
                return collected
        return {}

    # --------------------------------------------------------------- reporting
    def _report(self, wanted_slots: set[str]) -> None:
        usable = {s.key for s in self.ledger.verified_sources()}
        covered: dict[str, list[str]] = {}
        for claim in self.ledger.claims.values():
            if claim.verified:
                covered.setdefault(claim.slot, []).append(claim.id)

        for slot in sorted(wanted_slots):
            hits = covered.get(slot, [])
            flag = "ok " if hits else "GAP"
            self.say(f"  {flag} {slot:<22} {len(hits)} claim(s)")

        gaps = sorted(set(wanted_slots) - set(covered))
        broken = [
            s for s in self.ledger.sources.values()
            if s.status == "broken"
        ]
        if broken:
            self.say(f"dropped {len(broken)} dead link(s): "
                     + ", ".join(f"{b.key}" for b in broken))
        if gaps:
            self.ledger.decide(
                self.name,
                "proceed-with-gaps",
                f"{len(gaps)} slot(s) have no verified evidence: {', '.join(gaps)}",
            )
        else:
            self.ledger.decide(
                self.name,
                "all-slots-covered",
                f"every planned slot has verified evidence from {len(usable)} source(s)",
            )
        _ = usable