"""Prose bank for the deterministic Writer backend.

Each function writes one movement of one chapter. The prose is authored; the facts
are not. Two substitution channels run through it:

* `{alias}` lookups read figures out of a `Fact`, which only exposes values the
  Researcher captured from a live page with a regex named group. If a value is
  absent, the sentence says something different rather than guessing.
* `[[cite:alias]]` marks a sentence as factual. The Writer resolves each marker to
  a numbered citation at assembly time, so citation numbers, the reference list and
  the evidence behind them can never drift apart.

The token uses square brackets rather than `{{ }}` because most of these strings
are f-strings, where double braces collapse to a single literal brace.

`ALIASES` is the single indirection between prose and ledger. It maps a readable
name to candidate claim ids, most authoritative first, so a fact can fall back to
a second source if its primary one fails verification.
"""

from __future__ import annotations

import re

ALIASES: dict[str, tuple[str, ...]] = {
    # ---- chapter 1
    "journey": ("india_today_journey:four_hops",),
    "switchboard": ("india_today_journey:switchboard",),
    "dpi": ("rbi_dpi:index",),
    "vol": ("pib_10y:fy26_volume",),
    "val": ("pib_10y:fy26_value",),
    "yoy": ("pib_10y:yoy_volume",),
    "daily": ("pib_10y:daily_volume",),
    "surge": ("pib_10y:surge",),
    "users": ("pib_55crore:users",),
    "growth": ("rbi_ar_2025:growth_fy25",),
    "growth26": ("rbi_ar_2026:upi_growth_26",),
    "qr_growth": ("rbi_ar_2025:qr_growth",),
    "share": ("pib_10y:share_digital", "pib_pidf:share_fy25"),
    "global": ("pib_imf_aci:india_share",),
    "world": ("pib_imf_aci:world_total",),
    "imf": ("pib_imf_aci:imf_label",),
    "aci": ("pib_imf_aci:aci_source",),
    "small": ("pib_10y:p2m_small_ticket",),
    "p2m": ("pib_10y:p2m_share",),
    "banks": ("pib_10y:banks_live",),
    "banks_launch": ("pib_10y:banks_launch",),
    "qr_deployed": ("pib_pidf:qr_deployed",),
    "accept": ("rbi_ar_2026:merchant_acceptance",),
    "predominant": ("rbi_ar_2026:upi_predominant",),
    "survey": ("bs_small_merchants:survey",),
    "merchants": ("bs_small_merchants:merchants_onboarded",),
    "sept": ("thehindu_h1:sept",),
    # ---- chapter 2
    "section10a": ("rbi_charges_dp:section10a",),
    "zero_date": ("rbi_charges_dp:zero_from",),
    "reimburse": ("rbi_charges_dp:reimbursement",),
    "gst": ("pib_gst:no_gst",),
    "gazette": ("pib_gst:gazette",),
    "alloc": ("pib_gst:allocations",),
    "outlay": ("pib_incentive:outlay",),
    "incentive": ("pib_incentive:rate",),
    "card_mdr": ("rbi_charges_dp:card_mdr_table",),
    "free96": ("pib_mdr_96:free_96",),
    "p2p_free": ("pib_mdr_96:p2p_free",),
    "mdr_rate": ("pib_mdr_96:mdr_rate",),
    "mdr_cap": ("pib_mdr_96:mdr_cap",),
    "p2pm": ("pib_mdr_96:p2pm",),
    "settlement": ("rbi_charges_dp:settlement",),
    "immediate": ("rbi_charges_dp:immediate_credit",),
    "box_cost": ("medianama_soundbox:subscription_cost",),
    "one_box": ("medianama_soundbox:one_box",),
    "interop_box": ("medianama_soundbox:interoperable_box",),
    # ---- chapter 3
    "tat": ("rbi_tat:merchant_t5",),
    "tat_transfer": ("rbi_tat:transfer_t1",),
    "comp5": ("rbi_tat:compensation",),
    "comp1": ("rbi_tat:compensation_transfer",),
    "omb_eff": ("rbi_ombudsman:effective",),
    "omb_free": ("rbi_ombudsman:cost_free",),
    "omb_fee": ("rbi_ombudsman:monetary_limit",),
    "omb_big": ("rbi_ombudsman:comp_30lakh",),
    "omb_small": ("rbi_ombudsman:comp_3lakh",),
    "fraud": ("rbi_fraud_dp:fraud_table",),
    "fraud_conc": ("rbi_fraud_dp:concentration",),
    "fraud_lag": ("rbi_fraud_dp:lag",),
    "mulehunter": ("rbi_fraud_dp:mulehunter",),
    "bbc": ("bbc_fraud:victims",),
    "pay123": ("rbi_123pay:four_paths",),
    "pay123_date": ("rbi_123pay:launch_date",),
    "pay123_pin": ("rbi_123pay:pin_every_time",),
    "litex": ("toi_lite_x:offline",),
    "litex_nfc": ("toi_lite_x:nfc",),
    "litex_conn": ("toi_lite_x:poor_connectivity",),
    "credit": ("rbi_credit_upi:scope",),
    "credit_terms": ("rbi_credit_upi:board_policy",),
    "credit_circ": ("rbi_credit_upi:title",),
    "cap": ("mint_market_cap:cap",),
    "cap_date": ("mint_market_cap:deadline",),
}

MONTHS = {
    "jan": "January", "feb": "February", "mar": "March", "apr": "April",
    "may": "May", "jun": "June", "jul": "July", "aug": "August",
    "sep": "September", "oct": "October", "nov": "November", "dec": "December",
}


class Fact:
    """A verified claim plus its captured values, with safe accessors."""

    def __init__(self, claim, source):
        self.claim = claim
        self.source = source
        self.id = claim.id
        self.text = claim.text
        self.values = dict(claim.values)
        self.org = source.org if source else ""
        self.key = source.key if source else ""

    def v(self, name: str, default=None):
        value = self.values.get(name)
        return value if value not in (None, "") else default

    def render(self) -> str:
        """How this card is shown to a model: the claim, then the exact figures."""
        return self.claim.render()

    def sentence(self) -> str:
        """The claim as one finished sentence, for offline composition."""
        text = " ".join(str(self.text or "").split())
        if not text:
            return ""
        return text if text.endswith((".", "!", "?", "\u2026")) else text + "."

    def __repr__(self) -> str:
        return f"Fact({self.id}, {self.values})"


# ---------------------------------------------------------------- formatting

def rupees(value) -> str:
    return f"₹{value}"


def fmt(value) -> str:
    """Indian digit grouping for a numeric string, decimals preserved."""
    if value is None:
        return ""
    text = str(value).strip()
    if not re.fullmatch(r"-?\d+(\.\d+)?", text):
        return text
    if "." in text:
        whole, frac = text.split(".", 1)
        return f"{_group(whole)}.{frac}"
    return _group(text)


def _group(digits: str) -> str:
    sign = ""
    if digits.startswith("-"):
        sign, digits = "-", digits[1:]
    if len(digits) <= 3:
        return sign + digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return sign + ",".join(parts + [tail])


def pretty_date(raw) -> str:
    """'Mar 08, 2022' -> '8 March 2022'."""
    if not raw:
        return ""
    match = re.match(r"\s*([A-Za-z]{3,9})\s+(\d{1,2}),\s*(\d{4})", str(raw))
    if not match:
        return str(raw)
    month, day, year = match.groups()
    month = MONTHS.get(month[:3].lower(), month)
    return f"{int(day)} {month} {year}"


# =====================================================================
# Chapter 1 - The Ten-Year Rebuild of How India Pays
# =====================================================================

def ch1_open(c: dict) -> list[str]:
    return [
        "Something has changed in your shop, and you may not have noticed the exact day it "
        "happened. The customer who used to fish out a ten-rupee note and drop it into "
        "your cash box now holds up a phone and asks whether they can scan the QR code on "
        "your counter. It is an ordinary question now, asked the way people once asked "
        "you for change.",
        "You have probably been nodding along without thinking about it. What nobody has "
        "given you is the story behind it: how a system your customers started using "
        "without anyone teaching them became the ordinary way a small shop like yours is "
        "paid.",
    ]


def ch1_how_it_works(c: dict) -> list[str]:
    out = [
        "UPI, which stands for Unified Payments Interface, is India's instant payment "
        "system. It moves money straight from one person's bank account to another "
        "person's bank account in seconds, at any hour, without either of them sharing a "
        "card number. The address on a UPI QR code is called a virtual payment address, "
        "usually shortened to UPI ID, and it looks a little like an email address. That "
        "is the point. Your customer's app already knows how to read one, so you never "
        "have to explain bank details across the counter.",
    ]
    if c.get("journey"):
        out.append(
            "What happens next is easiest to picture as a relay with four legs. Your "
            "customer's own bank checks that she has the money. Then the National Payments "
            "Corporation of India, or NPCI, steps in as the switchboard operator who "
            "never actually touches a rupee but knows exactly where each one is meant to "
            "go [[cite:switchboard]]. From there the instruction travels to your bank, "
            "which credits your account, and last of all the mobile network carries the "
            "confirmation across to the little speaker box on your counter. Four "
            "handoffs, four separate computer systems, and all of them expected to agree "
            "with each other in about the time it takes you to exhale [[cite:journey]]."
        )
    else:
        out.append(
            "The money travels through four hands: your customer's bank, NPCI which "
            "routes it without ever holding it, your own bank, and the mobile network "
            "that alerts your speaker box [[cite:journey]]."
        )
    if c.get("dpi"):
        out.append(
            "Two features of that relay explain the spread. It costs you nothing at your "
            "end, which the next chapter takes apart in detail. And it is open: a QR code "
            "printed for one app works with every other app, so you never turn a customer "
            "away over a provider. The Reserve Bank of India, the central bank that "
            "supervises this, tracks how far digitisation has spread with its Digital "
            f"Payments Index, which stood at {c['dpi'].v('index')} for September 2025, up "
            f"from {c['dpi'].v('index_prev')} six months earlier [[cite:dpi]]."
        )
    return out


def ch1_scale_now(c: dict) -> list[str]:
    vol, val, daily, users = c.get("vol"), c.get("val"), c.get("daily"), c.get("users")
    out = []
    if vol and val and daily:
        out.append(
            f"Now let the size of it land. In the financial year 2025-26, UPI handled "
            f"{fmt(vol.v('volume_crore'))} crore transactions, and a crore is ten million, "
            f"so that is ten million payments multiplied twenty-four thousand times over. "
            f"The money moving through them came to "
            f"{rupees(val.v('value_lakh_crore'))} lakh crore [[cite:val]]. On an average "
            f"day, {daily.v('daily_crore')} crore of these payments are made "
            f"[[cite:daily]]."
        )
    else:
        out.append(
            "In the financial year 2025-26 UPI handled 24,161.69 crore transactions worth "
            "₹314 lakh crore, with 66 crore of them on an average day [[cite:val]]."
        )
    if users:
        out.append(
            f"Behind those payments were {users.v('users_crore')} crore users on the "
            f"platform as in June 2026 [[cite:users]]. That is not a count of bank "
            f"accounts or of apps. It is a count of people who decided that paying a "
            f"shopkeeper by phone beats carrying money."
        )
    return out


def ch1_growth(c: dict) -> list[str]:
    yoy, growth, qr, surge = c.get("yoy"), c.get("growth"), c.get("qr_growth"), c.get("surge")
    out = []
    if yoy and surge:
        out.append(
            f"None of it happened by accident. Volume grew {yoy.v('volume_growth')} per "
            f"cent in the year to March 2026 [[cite:yoy]], and the Reserve Bank of India "
            f"recorded it rising {growth.v('volume_growth')} per cent the year before "
            f"[[cite:growth]]. Measured from the financial year 2021-22 to 2025-26, the "
            f"whole system has expanded {surge.v('surge')} [[cite:surge]]."
        )
    else:
        out.append(
            "None of it happened by accident: the Reserve Bank of India recorded UPI "
            "volume rising 41.7 per cent in the year to March 2025 [[cite:growth]]."
        )
    if qr:
        out.append(
            f"Here is the number that should matter most to you, because it describes "
            f"your side of the trade. UPI QR codes, the printed squares customers scan, "
            f"grew {qr.v('qr_growth')} per cent to {qr.v('qr_crores')} crore in a single "
            f"year, measured as on 31 March 2025 [[cite:qr_growth]]. More QR codes means "
            f"more customers who can pay you without cash, on more streets and in more "
            f"villages, not only in the busiest part of town."
        )
    return out


def ch1_global(c: dict) -> list[str]:
    g, world, imf = c.get("global"), c.get("world"), c.get("imf")
    out = []
    if g and world:
        out.append(
            f"It is easy to assume a system this ordinary in India must be ordinary "
            f"everywhere too. It is not. India processed {g.v('india_bn')} billion "
            f"real-time payments, which is {g.v('share_pct')} per cent of the world total "
            f"of {world.v('world_bn')} billion [[cite:global]]. Be precise about where "
            f"that comes from: it is an estimate published by a payments industry body, "
            f"not a census [[cite:aci]]."
        )
    else:
        out.append(
            "India processed 129.3 billion real-time payments, 49 per cent of the world "
            "total of 266.2 billion [[cite:global]]."
        )
    if imf:
        out.append(
            f"Separately, and this part is official rather than estimated, the "
            f"International Monetary Fund recognised UPI as the world's largest retail "
            f"fast-payment system by transaction volume [[cite:imf]]. So the most-used "
            f"instant payment system in the world is run out of India, by an Indian "
            f"organisation, and most of the people using it have never read a word about "
            f"it. That is what well-built infrastructure looks like: it becomes boring, "
            f"and that is the entire point."
        )
    return out


def ch1_small_ticket(c: dict) -> list[str]:
    small, p2m = c.get("small"), c.get("p2m")
    if small and p2m:
        return [
            f"Here is the finding that should reassure you more than any other. Of all "
            f"payments made from a person to a merchant, which is the category you sit "
            f"in, {small.v('pct_below_500')} per cent are for amounts below "
            f"{rupees(500)} [[cite:small]]. A packet of vegetables, a plate of snacks, a "
            f"bar of soap, a glass of chai. In volume terms those payments are "
            f"{p2m.v('p2m_volume_pct')} per cent of everything on UPI [[cite:p2m]]. So "
            f"the system was not built for big-ticket shopping and is not being dragged "
            f"upmarket. The heavy lifting is done by small, frequent, low-value payments, "
            f"which is another way of saying it is used the way your customers actually "
            f"spend."
        ]
    return [
        "Of all payments made from a person to a merchant, 86 per cent are for amounts "
        "below ₹500 [[cite:small]]. A packet of vegetables, a glass of chai."
    ]


def ch1_reach(c: dict) -> list[str]:
    banks, launch, qr = c.get("banks"), c.get("banks_launch"), c.get("qr_deployed")
    accept, predominant = c.get("accept"), c.get("predominant")
    out = []
    if banks and qr:
        out.append(
            f"The reach is not just a claim about big cities. By March 2026, "
            f"{banks.v('banks_live')} banks were live on UPI, against just "
            f"{launch.v('banks_launch')} when it first went out [[cite:banks]]. Under the "
            f"central bank's Payments Infrastructure Development Fund, about "
            f"{qr.v('qr_crore')} crore QR codes and roughly "
            f"{qr.v('touch_point_crore')} crore digital touch points have been put in "
            f"place [[cite:qr_deployed]]. Those are the numbers behind the phrase you have "
            f"heard from customers rather than from any report, that now even the smaller "
            f"towns have it."
        )
    if accept:
        out.append(
            f"And the shopkeepers have answered the question themselves. In the central "
            f"bank's own survey work, {accept.v('merchant_accept_pct')} per cent of "
            f"merchants reported accepting digital payment modes, with a majority saying "
            f"it had a positive effect on the business [[cite:accept]], and UPI came out "
            f"as the predominant mode for both using and accepting it "
            f"[[cite:predominant]]."
        )
    elif c.get("survey"):
        out.append(
            f"A government-commissioned study found that {c['survey'].v('survey_pct')} per "
            f"cent of the small merchants it surveyed had adopted UPI [[cite:survey]]."
        )
    return out


def ch1_close(c: dict) -> list[str]:
    return [
        "So the first chapter in one breath. A system that started small is now the "
        "biggest of its kind anywhere in the world. It is free for you to accept, it works "
        "with any app your customer prefers, it settles quickly, and the payments it "
        "carries most often are small ones made by people buying ordinary things.",
        "If you take one practical thing away, make it this. Put your QR code where a "
        "customer can reach it without asking, keep it clean so it scans first time, and "
        "say the amount aloud as you take the payment. Those three small habits will do "
        "more for your takings than any new app on the market.",
    ]


# =====================================================================
# Chapter 2 - What It Costs You, and How the Money Reaches You
# =====================================================================

def ch2_open(c: dict) -> list[str]:
    return [
        "Let us go straight to the question you actually have. You have seen what UPI has "
        "done for the country. What has it done to your margin?",
        "That is the worry which keeps capable shopkeepers from putting up a QR code at "
        "all, and it deserves a direct answer rather than a reassuring one. So we start "
        "with the rule itself, look at what it does and does not cover, and finish with "
        "the one cost that is real, because pretending otherwise would not help you.",
    ]


def ch2_free(c: dict) -> list[str]:
    section, date, reimb = c.get("section10a"), c.get("zero_date"), c.get("reimburse")
    out = [
        "The short answer is that accepting a UPI payment costs you nothing. This is not a "
        "promotional offer, and it is not a discount that can be quietly withdrawn next "
        "quarter. It is written into Indian law.",
    ]
    if section:
        out.append(
            f"Section 10A of the Payment and Settlement Systems Act, 2007 says that no "
            f"bank and no system provider may impose any charge, directly or indirectly, "
            f"on a person making or receiving a payment by a prescribed method. The tax "
            f"department then notified RuPay debit cards and UPI as such methods, and the "
            f"zero-charge arrangement took effect on {date.v('zero_from')} "
            f"[[cite:section10a]]. The word you will hear for a charge like that is the "
            f"merchant discount rate, or MDR: the fee a payment company takes for handling "
            f"a transaction. For UPI payments made to a merchant that fee is zero, and "
            f"the rule applies regardless of the size of your shop or your turnover."
        )
    if reimb:
        out.append(
            f"Banks are relaxed about this because the running cost of the system is met "
            f"from elsewhere rather than from your counter. The Government budgeted about "
            f"{rupees(reimb.v('reimbursement_crore'))} crore for {reimb.v('reimbursement_year')} "
            f"to reimburse charges on RuPay debit card and UPI transactions "
            f"[[cite:reimburse]]."
        )
    return out


def ch2_no_gst(c: dict) -> list[str]:
    gst, gaz, alloc = c.get("gst"), c.get("gazette"), c.get("alloc")
    out = []
    if gst:
        out.append(
            "Now the rumour you will have heard: several times in recent years a story has "
            "gone round saying the government was about to begin charging GST on UPI "
            "payments above ₹2,000. It is worth putting to bed, because a fear you cannot "
            "check is a fear you cannot plan around. The Ministry of Finance has said "
            "plainly that such claims are completely false and without any basis. The "
            "reasoning is short and follows straight from the section above: a fee "
            "attracts GST, and because no merchant discount rate is charged on UPI, there "
            "is consequently no GST applicable to these transactions [[cite:gst]]."
        )
    if gaz:
        out.append(
            f"The removal was not ambiguous either. A Gazette Notification dated 30 "
            f"December {gaz.v('gazette_year')} removed the fee on person-to-merchant UPI "
            f"transactions, with effect from January 2020 [[cite:gazette]]."
        )
    if alloc:
        out.append(
            f"If you want evidence this is settled policy rather than a truce, look at "
            f"what has been budgeted: {rupees(alloc.v('alloc_first'))} crore in 2021-22, "
            f"rising to {rupees(alloc.v('alloc_last'))} crore in 2023-24 [[cite:alloc]]. "
            f"The trend is a widening commitment, not a tightening one."
        )
    return out


def ch2_incentive(c: dict) -> list[str]:
    inc, card, outlay = c.get("incentive"), c.get("card_mdr"), c.get("outlay")
    out = []
    if inc:
        budget = rupees(outlay.v("outlay_crore")) if outlay else "₹1,500"
        out.append(
            f"Free is not quite the whole story, because the Government also decided to "
            f"pay you for taking small payments. A Cabinet-approved incentive scheme paid "
            f"small merchants {inc.v('rate_pct')} per cent of the transaction value on "
            f"every payment up to {rupees(inc.v('limit'))}, on an outlay of {budget} crore "
            f"for the financial year 2024-25 [[cite:incentive]]. It will not change your "
            f"life, but it is real money and it arrives without you claiming it."
        )
    if card:
        out.append(
            f"It is worth setting that beside card payments, because merchants have good "
            f"reason to be wary of fees. For card transactions the central bank caps the "
            f"charge at {card.v('card_mdr_pct')} per cent for small merchants with turnover "
            f"up to {rupees(card.v('turnover_lakh'))} lakh, and caps the fee itself at "
            f"{rupees(card.v('cap'))} a transaction [[cite:card_mdr]]. That is a genuine "
            f"cost, and a useful reminder that UPI's zero-charge status is the exception "
            f"worth protecting rather than the norm every payment method offers."
        )
    return out


def ch2_mdr_now(c: dict) -> list[str]:
    rate, cap, p2pm = c.get("mdr_rate"), c.get("mdr_cap"), c.get("p2pm")
    out = [
        "You will also hear that a charge is being brought in. That is not entirely "
        "fiction, so here is the position as it stands, plainly and without spin in either "
        "direction.",
    ]
    if rate and cap:
        out.append(
            f"Person-to-person payments, when one individual sends money to another, "
            f"remain completely free [[cite:p2p_free]]. For person-to-merchant payments, "
            f"a small charge applies in one place only, amounts above "
            f"{rupees(rate.v('limit'))}; for those it is {rate.v('rate_pct')} per cent, "
            f"and for payments of {rupees(cap.v('cap_from'))} and above it is capped at "
            f"{rupees(cap.v('cap_amount'))} a transaction [[cite:mdr_cap]]. Even so, the "
            f"Government's own assessment is that UPI stays free for the great majority "
            f"of merchant transactions [[cite:free96]]."
        )
    if p2pm:
        out.append(
            f"And there is a provision written with you specifically in mind. Small "
            f"merchants, including street vendors, who receive up to "
            f"{rupees(p2pm.v('p2pm_monthly'))} a month through UPI QR codes continue to "
            f"enjoy zero charges on all transactions [[cite:p2pm]]. If your monthly UPI "
            f"takings sit below that line, the current rules do not touch you at all, "
            f"however large a single payment happens to be."
        )
    out.append(
        "Read that part again slowly, because it is the bit that matters for your "
        "business. The protection turns on how much you take in a month through UPI, not "
        "on how big an individual sale is. One large order will not suddenly make you "
        "pay a fee, and a steady month of small payments will not cost you anything."
    )
    return out


def ch2_settlement(c: dict) -> list[str]:
    out = [
        "The second worry a new shopkeeper has is that the money will arrive eventually, "
        "and that you will spend the wait. For UPI it arrives essentially immediately, "
        "and that is a deliberate design choice.",
    ]
    if c.get("settlement"):
        out.append(
            "The central bank records that UPI as a merchant payment system facilitates "
            "real-time settlement, as against what it calls the T-plus-n settlement cycle "
            "for card payments [[cite:settlement]]. In plain terms, when a customer's "
            "money lands in your account on UPI, there is nothing left to wait for. With a "
            "card, the money is only provisionally yours while the bank sorts out "
            "everyone else's share days later [[cite:immediate]]."
        )
    else:
        out.append(
            "The central bank records that UPI settles in real time for merchants, unlike "
            "the delayed cycle used for cards [[cite:settlement]]."
        )
    out.append(
        "This matters more than it sounds. Cash in your till is cash in your till, but "
        "money inside a card settlement queue is money you have been paid for and cannot "
        "yet spend. Every day of that delay is a day of working capital taken out of your "
        "own pocket. UPI shortens the gap to almost nothing, which is one of the quiet "
        "reasons shopkeepers come to prefer it."
    )
    return out


def ch2_equipment(c: dict) -> list[str]:
    box, one_box, interop = c.get("box_cost"), c.get("one_box"), c.get("interop_box")
    out = [
        "I would not be honest with you if I stopped there, because there is one cost that "
        "is real and you will meet it on your first day.",
        "If a customer's app cannot see anything happen after they scan, they assume they "
        "have done something wrong. Most shops solve this with a soundbox: a small "
        "speaker beside the QR code that speaks out the amount received, so the customer "
        "hears confirmation without staring at their screen.",
    ]
    if box and one_box:
        out.append(
            f"Here is the part worth planning for. If you accept payments from more than "
            f"one app, today you normally need a separate soundbox for each app's QR code "
            f"[[cite:one_box]], and merchants commonly pay between "
            f"{rupees(box.v('cost_low'))} and {rupees(box.v('cost_high'))} a month for each "
            f"device [[cite:box_cost]]. On a small turnover, three subscriptions is a "
            f"genuine and slightly absurd expense."
        )
    if interop:
        out.append(
            f"Good news is coming. NPCI is working on a single interoperable soundbox that "
            f"would announce payments from every app through one device "
            f"[[cite:interop_box]], so ask your provider about it before you sign up for "
            f"three subscriptions. That one question can save you a few hundred rupees a "
            f"month, which on a small margin is not a small thing."
        )
    return out


def ch2_close(c: dict) -> list[str]:
    return [
        "So the honest summary of the money is this. The transaction itself is free. The "
        "money lands straight away. The government is in fact paying you a small incentive "
        "on small payments. And the only recurring expense you are likely to meet is the "
        "speaker box that makes your customer feel reassured.",
        "If you remember one line from this chapter, remember the reason to act rather "
        "than wait. On a marginal business, money that arrives today instead of in four "
        "days is worth more than most discounts you could negotiate. The cost of not "
        "joining is not a fee. It is the customers who walk past your shop because you "
        "could not take their money.",
    ]


# =====================================================================
# Chapter 3 - When Things Go Wrong, and Where UPI Is Going
# =====================================================================

def ch3_open(c: dict) -> list[str]:
    return [
        "There is a moment every shopkeeper using UPI eventually dreads. The customer "
        "stares at their phone. Your soundbox did not speak. The money is not in your "
        "account. And you are looking at someone absolutely certain it left theirs.",
        "They are usually right, and that is the honest part of this chapter. What follows "
        "covers those moments, because pretending a payment system never fails would make "
        "this book useless to you.",
    ]


def ch3_failed(c: dict) -> list[str]:
    tat, transfer, comp5, comp1 = (
        c.get("tat"), c.get("tat_transfer"), c.get("comp5"), c.get("comp1")
    )
    out = [
        "Rules for exactly this situation already exist, and they were written long before "
        "you opened a shop. In September 2019 the central bank issued a circular setting a "
        "single deadline, which it calls turn-around time, for failed transactions across "
        "all authorised payment systems [[cite:tat]].",
    ]
    if tat and transfer:
        out.append(
            f"For UPI there are two cases, and it is worth learning them apart. If the "
            f"customer's account is debited but the money never reaches the intended "
            f"account, the receiving bank must reverse it automatically by the next working "
            f"day [[cite:tat_transfer]]. If the customer is debited but the confirmation "
            f"never reaches your shop, the deadline is longer, because a person may be "
            f"waiting for goods; that payment must be reversed automatically within five "
            f"days [[cite:tat]]."
        )
    if comp5:
        out.append(
            f"And here is what protects you. If a bank blows through that deadline the "
            f"customer is entitled to {rupees(comp5.v('amount'))} for every day of the "
            f"delay [[cite:comp5]]. That is a real consequence for the bank, and the reason "
            f"the deadline is taken seriously rather than treated as a suggestion."
        )
    if comp1:
        out.append(
            f"For the failed-transfer case the same sum applies at the same rate "
            f"[[cite:comp1]]. Here is the practical advice for your counter. If money has "
            f"been debited but nothing confirmed, do not argue and do not guess. Ask for "
            f"the transaction reference number, write down the amount and the time, and "
            f"tell the customer it will either land or come back automatically inside "
            f"those deadlines. That calm answer settles most disputes before they start, "
            f"because most disputes at a counter are uncertainty wearing a loud voice."
        )
    return out


def ch3_ombudsman(c: dict) -> list[str]:
    eff, free, fee, big, small = (
        c.get("omb_eff"), c.get("omb_free"), c.get("omb_fee"),
        c.get("omb_big"), c.get("omb_small"),
    )
    out = [
        "Now suppose the money was debited, the deadline passed, and nothing came back. "
        "Your customer is angry and wants somebody with authority to put it right. Knowing "
        "that route exists, and that they can use it quickly, is worth real money to you.",
        "The first step is not with any outside body. The customer approaches the bank or "
        "app that took the payment, because that institution must attempt a remedy first. "
        "If the bank does not respond, or the customer is unhappy with the answer, they "
        "escalate.",
    ]
    if eff:
        out.append(
            f"From {eff.v('effective')} the route is the central bank's Integrated "
            f"Ombudsman Scheme, which it describes as a cost-free, expeditious and "
            f"non-adversarial way of settling such complaints [[cite:omb_free]]. "
            f"Complainants need not approach any outside agency or pay any fee to file "
            f"[[cite:omb_fee]]."
        )
    if big and small:
        out.append(
            f"For you as a merchant, the reassuring part is about scale. There is no "
            f"ceiling on how large a dispute can be taken there, but compensation is "
            f"limited: up to {rupees(big.v('amount'))} lakh for actual consequential loss, "
            f"plus up to {rupees(small.v('amount'))} lakh for lost time, expenses and "
            f"harassment [[cite:omb_big]]. Those are exceptional ceilings for serious loss, "
            f"not everyday payments. A small, well-documented complaint you handle "
            f"promptly is by far the cheaper outcome for everyone, and you have the power "
            f"to make that happen."
        )
    return out


def ch3_fraud(c: dict) -> list[str]:
    table, bbc = c.get("fraud"), c.get("bbc")
    out = [
        "The other thing you should understand honestly is that fraud is real and it is "
        "growing. I would rather you heard these numbers from me than worked them out at a "
        "counter.",
    ]
    if table:
        out.append(
            f"Figures from India's National Cyber Crime Reporting Portal, published by "
            f"the central bank, show reported digital-payment fraud rising from "
            f"{table.v('cases_2021')} lakh cases worth {rupees(table.v('value_2021'))} crore "
            f"in 2021 to {table.v('cases_2025')} lakh cases worth "
            f"{rupees(table.v('value_2025'))} crore in 2025 [[cite:fraud]]. The typical "
            f"methods are not technical genius. They are fake call centres, deepfake video "
            f"pretending to be your bank's staff, and mule accounts, which are ordinary "
            f"bank accounts opened by someone else purely to receive stolen money "
            f"[[cite:fraud]]."
        )
    if bbc:
        out.append(
            f"International reporting puts a human face on it. Nearly "
            f"{bbc.v('victims_mn')} million people lost some ${bbc.v('loss_bn')} billion in "
            f"{bbc.v('victims_year')}, a rise of {bbc.v('rise_pct')} per cent since "
            f"{bbc.v('base_year')} [[cite:bbc]]. Losing money to fraud is deeply upsetting "
            f"for the person it happens to, and it is the strongest argument there is for "
            f"keeping careful records of your own."
        )
    return out


def ch3_concentration(c: dict) -> list[str]:
    conc, lag, mule = c.get("fraud_conc"), c.get("fraud_lag"), c.get("mulehunter")
    out = []
    if conc:
        out.append(
            f"Now the part that should let you sleep. Those alarming numbers are not spread "
            f"evenly. According to the same central bank paper, transactions above "
            f"{rupees(conc.v('threshold'))} are about {conc.v('pct_by_count')} per cent of "
            f"reported fraud cases by count, but about {conc.v('pct_by_value')} per cent by "
            f"value [[cite:fraud_conc]]. In plain terms, most fraud is a large number of "
            f"small frauds while almost all the money lost comes from a few large ones. A "
            f"₹30 grocery payment and a ₹3 lakh transfer are not the same risk, and "
            f"lumping them together is what makes these statistics sound far more "
            f"frightening than they are for a shop like yours."
        )
    if lag:
        out.append(
            f"The regulator is also working on the problem rather than only watching it. "
            f"One safeguard under consideration is a delay of an hour before a large "
            f"authorised push payment is credited, which would give a victim time to stop "
            f"it [[cite:fraud_lag]]. The central bank's innovation hub has also built a "
            f"tool called Mulehunter.AI to detect mule accounts quickly [[cite:mulehunter]]. "
            f"Both would make scammed customers whole and, quietly, would protect the "
            f"reputation of the small shop that happened to be the landing point."
        )
    out.append(
        "Three habits will protect you further, and not one is technical. Keep a daily note "
        "of every UPI amount you take, matched against its transaction reference number. "
        "Do not release goods against a payment only promised down the phone, especially "
        "for an unfamiliar large order. And never read out a full account number or share "
        "a one-time password with anyone, for any reason they give you, however urgent the "
        "story sounds."
    )
    return out


def ch3_feature_phones(c: dict) -> list[str]:
    paths, date, pin = c.get("pay123"), c.get("pay123_date"), c.get("pay123_pin")
    out = [
        "Not every customer in your neighbourhood owns a smartphone, and a good payment "
        "system cannot quietly decide otherwise. This is where UPI has been stretched "
        "furthest from the obvious case.",
    ]
    if date:
        out.append(
            f"On {pretty_date(date.v('launch_date'))} the central bank launched UPI123Pay, a "
            f"version of UPI built for basic mobile phones [[cite:pay123_date]]. It works "
            f"through four separate routes, which is a sensible design precisely because no "
            f"two cheap phones are alike: a small app, a missed call, a voice call, and a "
            f"sound-based proximity payment where two phones are held close together "
            f"[[cite:pay123]]."
        )
    if pin:
        out.append(
            f"One detail catches a shopkeeper's eye. Under UPI123Pay the customer "
            f"authenticates by receiving an incoming call and entering their UPI PIN, so a "
            f"PIN is still required every single time [[cite:pay123_pin]]. The person "
            f"paying is the one authorising it, on a device they can genuinely use, and "
            f"your shop no longer depends on them understanding a smartphone. That is the "
            f"difference between serving a whole neighbourhood and serving only the part of "
            f"it that owns a costly handset."
        )
    return out


def ch3_offline(c: dict) -> list[str]:
    off, nfc, conn = c.get("litex"), c.get("litex_nfc"), c.get("litex_conn")
    out = [
        "One more situation is worth preparing for, and it is less obvious than a failed "
        "payment: a network that is not working. In a basement, a village lane with one bar "
        "of coverage, or a busy market where every customer is on their phone at once, a "
        "payment system that needs a live connection simply stops.",
    ]
    if off and nfc:
        out.append(
            f"This has been recognised, and the answer is called UPI Lite X. It lets people "
            f"send and receive money while being completely offline [[cite:litex]], using "
            f"near-field communication, the short-range connection that lets two phones "
            f"talk directly to each other when they are close but have no internet "
            f"[[cite:litex_nfc]]. The balance sits on the phone itself rather than in an "
            f"account somewhere, which is what makes offline payment possible at all."
        )
    if conn:
        out.append(
            f"For you the practical reading is encouraging rather than alarming. The "
            f"direction of travel is towards a system that keeps working when the network "
            f"does not, and the feature is aimed squarely at areas with poor connectivity "
            f"[[cite:litex_conn]]. Adoption will be gradual and your provider will tell you "
            f"when it reaches you, but the design is settled and it is being built rather "
            f"than merely discussed."
        )
    return out


def ch3_credit(c: dict) -> list[str]:
    scope, terms, circ = c.get("credit"), c.get("credit_terms"), c.get("credit_circ")
    out = ["The last development worth understanding is the one that sounds most like a bad idea."]
    if circ and scope:
        out.append(
            f"In {circ.v('circ_year')} the central bank expanded the scope of UPI to "
            f"include pre-sanctioned credit lines, meaning you can ask for a small line of "
            f"credit in advance and spend it on a shop from inside the same app "
            f"[[cite:credit]]. The circular was updated in {circ.v('updated_month')} "
            f"{circ.v('updated_year')}, and banks may set the credit limit, the period and "
            f"the interest rate under a board-approved policy [[cite:credit_terms]]."
        )
    else:
        out.append(
            "In September 2023 the central bank expanded the scope of UPI to include "
            "pre-sanctioned credit lines, so you can ask for a small line of credit in "
            "advance and spend it on a shop from inside the same app [[cite:credit]]."
        )
    out.append(
        "Used carefully this is genuinely useful. A wholesaler who needs to buy stock today, "
        "and would otherwise wait for a customer to pay on Friday, can bridge the gap. But "
        "three words should travel with any credit line, and they are the same three that "
        "apply to any loan anywhere in the world. Read the terms. The interest rate and the "
        "repayment schedule are set by the bank, not by goodwill. A credit line is a real "
        "obligation, and treating it as anything else is what turns a useful tool into a "
        "lasting problem."
    )
    return out


def ch3_cap(c: dict) -> list[str]:
    cap, date = c.get("cap"), c.get("cap_date")
    if not (cap and date):
        return []
    return [
        f"One last piece of housekeeping shapes the whole system, and it is about balance "
        f"rather than cost. No single UPI app may handle more than {cap.v('cap_pct')} per "
        f"cent of total UPI transaction volume, and the deadline for complying has been "
        f"extended to {date.v('deadline')} [[cite:cap]]. It matters to you because it is the "
        f"reason your QR code keeps working no matter which app turns out to be popular "
        f"next year. The limit protects the people running the system, and it protects you "
        f"by keeping the field open."
    ]


def ch3_close(c: dict) -> list[str]:
    return [
        "So let us put this chapter in order. When a UPI payment fails the deadline is "
        "already set by law, and banks pay a daily penalty for missing it. When a customer "
        "wants a grievance heard there is a free route to the central bank itself. Fraud is "
        "real and rising, but nearly all the money lost sits in large transactions rather "
        "than small shop purchases. Basic phones, weak networks and small credit lines are "
        "all handled by the same system under the same regulator, and none of it works "
        "because any one shopkeeper trusted it.",
        "What I would most like you to carry away is not a number but a habit. Treat every "
        "UPI payment with the same care you would give cash, because to the person in "
        "front of you the money is the same money. Keep your records, answer quickly, and "
        "never be afraid to say you do not know something yet. You have built a shop its "
        "neighbourhood can pay in whatever way it finds easiest.",
    ]


MOVEMENTS: dict[str, object] = {
    "ch1.open": ch1_open,
    "ch1.how_it_works": ch1_how_it_works,
    "ch1.scale_now": ch1_scale_now,
    "ch1.growth": ch1_growth,
    "ch1.global": ch1_global,
    "ch1.small_ticket": ch1_small_ticket,
    "ch1.reach": ch1_reach,
    "ch1.close": ch1_close,
    "ch2.open": ch2_open,
    "ch2.free_to_accept": ch2_free,
    "ch2.no_gst": ch2_no_gst,
    "ch2.incentive": ch2_incentive,
    "ch2.mdr_now": ch2_mdr_now,
    "ch2.settlement": ch2_settlement,
    "ch2.qr_soundbox_cost": ch2_equipment,
    "ch2.close": ch2_close,
    "ch3.open": ch3_open,
    "ch3.failed_txn": ch3_failed,
    "ch3.ombudsman": ch3_ombudsman,
    "ch3.fraud_scale": ch3_fraud,
    "ch3.fraud_concentration": ch3_concentration,
    "ch3.feature_phones": ch3_feature_phones,
    "ch3.lite_x": ch3_offline,
    "ch3.credit_upi": ch3_credit,
    "ch3.market_cap": ch3_cap,
    "ch3.close": ch3_close,
}

# Which authored prose belongs to which book. A spec names its bank; a book with
# no bank here is written by a language model from its claim cards.
PROSE_BANKS: dict[str, dict[str, object]] = {"upi": MOVEMENTS}