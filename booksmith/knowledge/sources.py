"""Candidate sources with testable evidence probes.

This is a *candidate* pool, not a citation list. Nothing here is trusted. The
Researcher fetches every URL live and only promotes a probe to `verified` when
the page still literally contains the text the probe looks for. If a publisher
moves a page or deletes a number, the claim silently drops out of the book and
the Writer never gets to use it.

Each probe pattern uses named capture groups. Those captures become
`Claim.values`, which is the only route a number can take into the prose. The
Fact-checker later re-reads the cited page and re-confirms the same captures, so
a figure cannot be invented and cannot drift away from its source.

Sources marked `bot_protected` sit behind a WAF that rejects automated clients
(npci.org.in is the big one) while serving real readers normally. They are never
cited on their own: a claim may only borrow such a link when another,
machine-verifiable source carries the same figure.
"""

from __future__ import annotations

from ..models import EvidenceProbe, SourceSeed
from .brief import BRIEF  # noqa: F401  (kept for a single import surface)


def P(key: str, claim: str, pattern: str, required: bool = True) -> EvidenceProbe:
    return EvidenceProbe(key=key, claim=claim, pattern=pattern, required=required)


# --------------------------------------------------------------- official
SEEDS: tuple[SourceSeed, ...] = (

    # --- Chapter 1: scale and shape of UPI -------------------------------
    SourceSeed(
        key="pib_10y",
        org="Press Information Bureau, Government of India",
        title=(
            "UPI completes 10 glorious years, Emerges as World's Largest Real-Time "
            "Payments Platform, Anchoring India's Digital Economy"
        ),
        url="https://www.pib.gov.in/PressReleasePage.aspx?PRID=2257087&lang=1&reg=3",
        published="2026-04-30",
        tier="official",
        slots=("scale_now", "growth", "share", "small_ticket", "reach", "global"),
        probes=(
            P("fy26_volume",
              "In the financial year 2025-26 UPI handled 24,161.69 crore transactions.",
              r"Annual Transaction Volume \(FY2025-26\)\s*(?P<volume_crore>[\d,]+\.?\d*)\s*Crore"),
            P("fy26_value",
              "In the financial year 2025-26 UPI moved 314 lakh crore rupees of value.",
              r"Annual Transaction Value \(FY2025-26\)\s*₹\s*(?P<value_lakh_crore>[\d,]+)\s*Lakh Crore"),
            P("yoy_volume",
              "UPI transaction volume grew 30.0 per cent year on year in 2025-26.",
              r"YoY Volume Growth \(2025-2026\)\s*(?P<volume_growth>[\d.]+)\s*%"),
            P("yoy_value",
              "UPI transaction value grew 20.59 per cent year on year in 2025-26.",
              r"YoY Value Growth \(2025-2026\)\s*(?P<value_growth>[\d.]+)\s*%"),
            P("daily_volume",
              "On average 66 crore UPI transactions happen every single day.",
              r"Daily Average Transactions \(2025\)\s*(?P<daily_crore>[\d,]+)\s*Crore"),
            P("record_month",
              "The record monthly volume was 2264 crore transactions in March 2026.",
              r"Record Monthly Volume \(March 2026\)\s*(?P<record_month_crore>[\d,]+)\s*Crore"),
            P("banks_live",
              "703 banks were live on UPI as on March 2026, against 21 banks at launch.",
              r"Banks Live on UPI \(As on March 2026\)\s*(?P<banks_live>[\d,]+)\s*Banks"),
            P("banks_launch",
              "Only 21 banks were live on UPI when it launched in April 2016.",
              r"Banks at Launch \(April 2016\)\s*(?P<banks_launch>[\d,]+)\s*Banks"),
            P("share_digital",
              "UPI accounted for 85 per cent of India's digital payments in 2025-26.",
              r"Share of UPI in India'?s Digital Payments\s*(?P<share_digital_pct>[\d.]+)\s*%"),
            P("share_global",
              "UPI accounts for 49 per cent of the world's real-time payment volume.",
              r"Share of Global Real-Time Volume\s*(?P<share_global_pct>[\d.]+)\s*% of World"),
            P("p2m_share",
              "Person-to-merchant payments are 63 per cent of UPI transaction volume.",
              r"account for (?P<p2m_volume_pct>\d+)% of total transaction volume"),
            P("p2m_small_ticket",
              "86 per cent of person-to-merchant UPI payments are for amounts under 500 rupees.",
              r"with (?P<pct_below_500>\d+)% below ₹\s?500"),
            P("surge",
              "UPI transaction volume has surged nearly 12,000-fold in ten years.",
              r"Transaction volume surges (?P<surge>[\d,]+-fold)"),
        ),
    ),
    SourceSeed(
        key="pib_55crore",
        org="Press Information Bureau, Government of India",
        title="Nearly 55.49 Crore Users Onboarded on UPI as in June 2026",
        url="https://www.pib.gov.in/PressReleasePage.aspx?PRID=2286608&lang=1&reg=3",
        published="2026-07-20",
        tier="official",
        slots=("reach", "users"),
        probes=(
            P("users",
              "There were 55.49 crore users on the UPI platform as in June 2026.",
              r"(?P<users_crore>\d+\.\d+) crore users onboarded on UPI platform"),
            P("fy_table",
              "UPI volume rose from 4,595.61 crore transactions in 2021-22 to "
              "24,161.69 crore in 2025-26.",
              r"FY 2021-22\s+(?P<volume_fy2122>[\d,]+\.?\d*)\s+(?P<value_fy2122>[\d,]+\.?\d*)"
              r"[\s\S]{0,400}?FY 2025-26\s+(?P<volume_fy2526>[\d,]+\.?\d*)\s+"
              r"(?P<value_fy2526>[\d,]+\.?\d*)"),
        ),
    ),
    SourceSeed(
        key="pib_imf_aci",
        org="Press Information Bureau, Government of India",
        title=(
            "UPI Recognized as World's Largest Real-Time Payment System by IMF; "
            "Accounts for 49% of Global Transactions"
        ),
        url="https://www.pib.gov.in/PressReleasePage.aspx?PRID=2200569&lang=1&reg=3",
        published="2025-12-08",
        tier="official",
        slots=("global",),
        probes=(
            P("india_share",
              "India processed 129.3 billion real-time payments, 49 per cent of the "
              "world total.",
              r"India\s+(?P<india_bn>[\d.]+)\s+(?P<share_pct>\d+)%"),
            P("world_total",
              "The world processed 266.2 billion real-time payments in total.",
              r"Total\s+(?P<world_bn>[\d.]+)\s+100%"),
            P("imf_label",
              "The IMF recognised UPI as the world's largest retail fast-payment system "
              "by transaction volume in its June 2025 report.",
              r"IMF report on[\s\S]{0,200}?June 2025\s+had recognized Unified Payments "
              r"Interface \(UPI\) as the world.{0,3}s\s+largest retail fast-payment system"),
            P("aci_source",
              "The 49 per cent global share comes from an ACI Worldwide report titled "
              "'Prime Time for Real-Time' 2024.",
              r"ACI Worldwide report on\s*.{0,10}Prime Time for Real-Time.{0,6}\s*2024"),
        ),
    ),
    SourceSeed(
        key="pib_pidf",
        org="Press Information Bureau, Government of India",
        title="Coordinated Efforts of Government, RBI and NPCI Accelerate Growth in Digital Payments",
        url="https://www.pib.gov.in/PressReleasePage.aspx?PRID=2240723&reg=3&lang=1",
        published="2026-03-16",
        tier="official",
        slots=("reach", "share", "growth", "feature_phones"),
        probes=(
            P("qr_deployed",
              "About 56.86 crore QR codes and 5.80 crore digital touch points have been "
              "deployed under the RBI's Payments Infrastructure Development Fund.",
              r"(?P<touch_point_crore>[\d.]+)\s*crore digital touch points and about "
              r"(?P<qr_crore>[\d.]+)\s*crore QR codes"),
            P("share_fy25",
              "UPI accounted for 81 per cent of India's retail digital payments in 2024-25.",
              r"Unified Payments Interface \(UPI\) accounts for (?P<share_fy25_pct>\d+)% "
              r"in FY2024-25"),
            P("retail_total",
              "Retail digital payments in 2024-25 came to 22,167.90 crore transactions "
              "worth 849.12 lakh crore rupees.",
              r"FY 2024-25\s+(?P<retail_volume>[\d,]+\.?\d*)\s+"
              r"(?P<retail_value>[\d,]+\.?\d*)\s+(?P<retail_vol_growth>[\d.]+)%\s+"
              r"(?P<retail_val_growth>[\d.]+)%"),
            P("pidf",
              "The Payments Infrastructure Development Fund was set up by the RBI.",
              r"PIDF was set up by RBI"),
            P("123pay_purpose",
              "NPCI has launched UPI 123PAY, which lets feature-phone users pay through "
              "voice calls and sound-based proximity payments.",
              r"launched UPI 123PAY \(enabling payments through Interactive Voice Response "
              r"\(IVR\) and sound-based proximity payments\)"),
        ),
    ),
    SourceSeed(
        key="rbi_ar_2025",
        org="Reserve Bank of India",
        title="Annual Report of the Reserve Bank of India 2024-25, Chapter IX: Payment and Settlement Systems and Information Technology",
        url="https://www.rbi.org.in/Scripts/AnnualReportPublications.aspx?Id=1439",
        published="2025-05-29",
        tier="regulator",
        slots=("growth", "reach", "share", "settlement"),
        probes=(
            P("growth_fy25",
              "In 2024-25 UPI transaction volume grew 41.7 per cent and value grew "
              "30.3 per cent.",
              r"UPI transactions increased by (?P<volume_growth>[\d.]+) per cent in terms "
              r"of volume and (?P<value_growth>[\d.]+) per cent in terms of value"),
            P("share_retail",
              "UPI had the highest share of total retail payments in 2024-25, at "
              "84 per cent by volume.",
              r"highest share \((?P<share_retail_pct>\d+) per cent\) in total\s+retail "
              r"payments during 2024-25"),
            P("qr_growth",
              "UPI QR codes grew 91.5 per cent to 65.8 crore as on 31 March 2025.",
              r"UPI Quick Response \(QR\) codes increased by (?P<qr_growth>[\d.]+) per cent "
              r"to (?P<qr_crores>[\d.]+) crore as on March 31, 2025"),
            P("pos_growth",
              "Point-of-sale terminals grew 24.7 per cent to 1.1 crore during 2024-25.",
              r"point of sale \(PoS\) terminals increased by (?P<pos_growth>[\d.]+) per "
              r"cent to (?P<pos_crore>[\d.]+) crore"),
            P("settlement",
              "UPI settles for merchants in real time, unlike card payments which settle "
              "after a T-plus-n cycle.",
              r"UPI as a merchant payment system also facilitates real-time settlement, "
              r"as against the T\+n settlement cycle for card settlements"),
        ),
    ),

    SourceSeed(
        key="rbi_ar_2026",
        org="Reserve Bank of India",
        title=(
            "Annual Report of the Reserve Bank of India 2025-26, Chapter IX: "
            "Payment and Settlement Systems and Information Technology"
        ),
        url="https://www.rbi.org.in/scripts/AnnualReportPublications.aspx?Id=1469",
        published="2026-05-29",
        tier="regulator",
        slots=("merchant_adoption", "growth", "share"),
        probes=(
            P("merchant_acceptance",
              "Among merchants surveyed, 67 per cent reported accepting digital payment "
              "modes, with a majority reporting a positive impact on their business.",
              r"Among merchants, (?P<merchant_accept_pct>\d+) per cent reported accepting "
              r"digital payment modes"),
            P("upi_predominant",
              "UPI emerged as the predominant payment mode for both usage and acceptance.",
              r"UPI emerged as the predominant payment mode"),
            P("retail_growth",
              "Retail payment transactions rose 26.8 per cent in volume and 14 per cent "
              "in value during 2025-26.",
              r"Retail payment transactions recorded an increase of (?P<retail_vol>[\d.]+) "
              r"per cent in volume terms and (?P<retail_val>[\d.]+) per cent in value "
              r"terms during the year"),
            P("upi_growth_26",
              "UPI volume increased by 30 per cent in 2025-26, after 42 per cent in 2024-25.",
              r"UPI volume increased by (?P<upi_vol_growth>\d+) per cent\s*\((?P<upi_prev_growth>\d+) "
              r"per cent in 2024-25\)"),
            P("vision_2028",
              "The RBI released Payments Vision 2028 in the year, setting the roadmap to "
              "December 2028.",
              r"Payments Vision 2028[\s\S]{0,200}?December 2028"),
        ),
    ),

    # --- Chapter 2: what it costs a shop -------------------------------
    SourceSeed(
        key="pib_incentive",
        org="Press Information Bureau, Government of India",
        title=(
            "Cabinet approves Incentive scheme for promotion of low-value BHIM-UPI "
            "transactions Person to Merchant (P2M)"
        ),
        url="https://www.pib.gov.in/PressReleasePage.aspx?PRID=2112771&lang=1&reg=6",
        published="2025-03-19",
        tier="official",
        slots=("incentive", "free_to_accept"),
        probes=(
            P("outlay",
              "The incentive scheme had an estimated outlay of 1,500 crore rupees for "
              "the financial year 2024-25.",
              r"estimated outlay of (?P<outlay_crore>[\d,]+) crore, from 01\.04\.2024 to "
              r"31\.03\.2025"),
            P("rate",
              "Small merchants were paid an incentive of 0.15 per cent on transactions "
              "up to 2,000 rupees.",
              r"Incentive at the rate of (?P<rate_pct>[\d.]+)% per transaction value will "
              r"be provided\s+for transactions upto Rs\.\s?(?P<limit>[\d,]+),"),
            P("zero_mdr_table",
              "Under the scheme small merchants faced zero MDR on all amounts, with the "
              "incentive on the small ones.",
              r"Up to Rs\.\s*2k\s+Zero MDR / Incentive"),
        ),
    ),
    SourceSeed(
        key="pib_gst",
        org="Press Information Bureau, Government of India",
        title="Clarification on misleading reports regarding GST on UPI transactions",
        url="https://www.pib.gov.in/PressReleasePage.aspx?PRID=2122747&lang=1&reg=1",
        published="2025-04-18",
        tier="official",
        slots=("no_gst", "free_to_accept", "incentive"),
        probes=(
            P("gazette",
              "A Gazette Notification dated 30 December 2019 removed the merchant "
              "discount rate on person-to-merchant UPI transactions with effect from "
              "January 2020.",
              r"removed the MDR on Person-to-Merchant \(P2M\) UPI transactions through "
              r"the Gazette Notification dated 30\s?th\s?December\s(?P<gazette_year>\d{4})"),
            P("no_gst",
              "Because no MDR is charged on UPI, no GST applies to these transactions.",
              r"there is consequently no GST applicable to these transactions"),
            P("allocations",
              "Government support for zero-charge payments rose from 1,389 crore rupees "
              "in 2021-22 to 3,631 crore rupees in 2023-24.",
              r"FY2021-22:\s*₹\s*(?P<alloc_first>[\d,]+)\s*crore[\s\S]{0,300}?"
              r"FY2023-24:\s*₹\s*(?P<alloc_last>[\d,]+)\s*crore"),
        ),
    ),
    SourceSeed(
        key="rbi_charges_dp",
        org="Reserve Bank of India",
        title="Discussion Paper on Charges in Payment Systems",
        url="https://www.rbi.org.in/Scripts/PublicationsView.aspx?id=21082",
        published="2022-08-17",
        tier="regulator",
        slots=("free_to_accept", "no_gst", "card_mdr", "settlement"),
        probes=(
            P("section10a",
              "Section 10A of the Payment and Settlement Systems Act 2007 says no bank or "
              "system provider may charge anyone for making or receiving a payment by a "
              "prescribed method.",
              r"section 10A of the Payment and Settlement Systems Act, 2007.{0,400}?"
              r"no bank or system provider shall impose.{0,120}?any charge"),
            P("zero_from",
              "The zero-charge arrangement for UPI and RuPay debit cards took effect on "
              "1 January 2020.",
              r"arrangement of zero charges came into effect from (?P<zero_from>[A-Za-z]+ \d+, \d{4})"),
            P("reimbursement",
              "The Government budgeted about 1,500 crore rupees in 2021-22 to reimburse "
              "charges for RuPay debit card and UPI transactions.",
              r"budgeted ~₹\s*(?P<reimbursement_crore>[\d,]+) crore for the financial year (?P<reimbursement_year>\d{4}-\d{2})"),
            P("card_mdr_table",
              "For card payments, the cap was 0.40 per cent for small merchants with "
              "turnover up to 20 lakh rupees.",
              r"turnover up to ₹(?P<turnover_lakh>[\d]+) lakh during the previous "
              r"financial year\)[\s\S]{0,200}?Not exceeding (?P<card_mdr_pct>[\d.]+)% "
              r"\(MDR cap of ₹(?P<cap>[\d]+)"),
            P("settlement",
              "UPI settles for merchants in real time, unlike card payments which settle "
              "after a T-plus-n cycle.",
              r"UPI as a merchant payment system also facilitates real-time settlement, "
              r"as against the T\+n settlement cycle for card settlements"),
            P("immediate_credit",
              "UPI, unlike card networks, facilitates immediate credit with real-time "
              "confirmation.",
              r"UPI, unlike these, facilitates immediate credit with real-time confirmation"),
        ),
    ),
    SourceSeed(
        key="pib_mdr_96",
        org="Press Information Bureau, Government of India",
        title="UPI Continues to Remain Free for Peer to Peer Transactions and 96% of Merchant Transactions",
        url="https://www.pib.gov.in/PressReleasePage.aspx?lang=1&PRID=2310586&reg=48",
        published="2026-09-15",
        tier="official",
        slots=("mdr_now", "p2pm"),
        probes=(
            P("free_96",
              "UPI stays completely free for person-to-person payments and for 96 per "
              "cent of merchant transactions.",
              r"96% of Merchant Transactions"),
            P("p2p_free",
              "UPI remains completely free for all person-to-person transactions.",
              r"completely free for all person-to-person transactions"),
            P("mdr_rate",
              "A merchant discount rate of 0.4 per cent applies only to person-to-merchant "
              "payments above 2,000 rupees.",
              r"nominal MDR of (?P<rate_pct>[\d.]+)% will apply only to P2M transactions "
              r"above ₹\s?(?P<limit>[\d,]+)"),
            P("mdr_cap",
              "For transactions of 75,000 rupees and above, the MDR is capped at 300 rupees.",
              r"For transactions of ₹\s?(?P<cap_from>[\d,]+) and above, the MDR will be "
              r"capped at ₹\s?(?P<cap_amount>[\d,]+) per transaction"),
            P("p2pm",
              "Small merchants, including street vendors receiving up to 1 lakh rupees a "
              "month through UPI QR codes, keep zero MDR on all transactions.",
              r"receiving up to ₹\s?(?P<p2pm_monthly>[\d,]+) per month through UPI QR "
              r"codes under the Person-to-Person-Merchant \(P2PM\) category will continue "
              r"to enjoy zero MDR"),
            P("essential_sectors",
              "Railways, telecoms, insurance, fuel and farm inputs get a flat MDR above "
              "2,000 rupees.",
              r"railways, telecommunications, insurance, fuel and agricultural inputs"),
        ),
    ),

    # --- Chapter 3: trust, failure and what is next ----------------------
    SourceSeed(
        key="rbi_tat",
        org="Reserve Bank of India",
        title=(
            "Harmonisation of Turn Around Time (TAT) and customer compensation for "
            "failed transactions using authorised Payment Systems, "
            "RBI/2019-20/67 DPSS.CO.PD No.629/02.01.014/2019-20"
        ),
        url="https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=11693",
        published="2019-09-20",
        tier="regulator",
        slots=("failed_txn", "compensation"),
        probes=(
            P("transfer_t1",
              "If a UPI transfer debits an account but the beneficiary account is not "
              "credited, the bank must auto-reverse it by the next working day.",
              r"beneficiary account is not credited \(transfer of funds\).{0,200}?"
              r"auto reversal \(R\) by the Beneficiary bank latest on T\s*\+\s*1 day"),
            P("merchant_t5",
              "If a UPI payment to a shop is debited but the shop never gets a "
              "confirmation, it must be auto-reversed within five days.",
              r"transaction confirmation not received at merchant location \(payment to "
              r"merchant\).{0,120}?Auto-reversal within T\s*\+\s*5 days"),
            P("compensation",
              "Compensation of 100 rupees a day is payable once that deadline is crossed.",
              r"T\s*\+\s*5 days\.?\s*₹\s?(?P<amount>\d+)/- per day"),
            P("compensation_transfer",
              "If a transfer credit is delayed, the customer's bank must pay 100 rupees a day.",
              r"latest on T\s*\+\s*1 day\.?\s*₹\s?(?P<amount>\d+)/- per day"),
        ),
    ),
    SourceSeed(
        key="rbi_ombudsman",
        org="Reserve Bank of India",
        title="Reserve Bank - Integrated Ombudsman Scheme, 2026",
        url="https://www.rbi.org.in/commonperson/English/Scripts/FAQs.aspx?Id=3407",
        published="2026-07-01",
        tier="regulator",
        slots=("ombudsman",),
        probes=(
            P("effective",
              "The Reserve Bank - Integrated Ombudsman Scheme, 2026 came into force on "
              "1 July 2026.",
              r"Integrated Ombudsman Scheme, 2026\s*\(Updated as on\s*"
              r"(?P<effective>[A-Za-z]+\s*\d+,?\s*\d{4})"),
            P("cost_free",
              "The scheme is a cost-free, expeditious and non-adversarial route for "
              "customers to escalate bank complaints.",
              r"cost-free,\s*expeditious and non-adversarial"),
            P("comp_30lakh",
              "The RBI Ombudsman can award compensation up to 30 lakh rupees for "
              "consequential loss.",
              r"compensation up to Rs\.?\s*(?P<amount>\d+) lakh"),
            P("comp_3lakh",
              "A further 3 lakh rupees can be awarded for lost time, expenses and "
              "harassment.",
              r"compensation up to Rs\.?\s*(?P<amount>\d+) lakh for loss of the complainant"),
            P("monetary_limit",
              "Complainants need not pay any fee to file a complaint with the RBI Ombudsman.",
              r"need not approach any third-party agency or pay any fee to file a complaint"),
        ),
    ),
    SourceSeed(
        key="rbi_fraud_dp",
        org="Reserve Bank of India",
        title="Exploring safeguards in digital payments to curb frauds",
        url="https://www.rbi.org.in/Scripts/PublicationsView.aspx?id=23810",
        published="2026-04-09",
        tier="regulator",
        slots=("fraud_scale", "fraud_concentration", "fraud_response"),
        probes=(
            P("fraud_table",
              "Reported digital-payment fraud rose from 2.6 lakh cases worth 551 crore "
              "rupees in 2021 to 28 lakh cases worth 22,931 crore rupees in 2025.",
              r"2021\s+(?P<cases_2021>[\d.]+)\s+lakh\s+(?P<value_2021>[\d,]+)[\s\S]{0,200}?"
              r"2025\s+(?P<cases_2025>[\d.]+)\s+lakh\s+(?P<value_2025>[\d,]+)"),
            P("concentration",
              "Transactions above 10,000 rupees are about 45 per cent of fraud cases by "
              "count but 98.5 per cent by value.",
              r"transactions above ₹\s*(?P<threshold>[\d,]+) account for approximately "
              r"(?P<pct_by_count>\d+) per cent of reported fraud cases by volume, but about "
              r"(?P<pct_by_value>[\d.]+) per cent by value"),
            P("lag",
              "One safeguard under consideration is a one-hour delay on credits for "
              "authorised push payments above 10,000 rupees.",
              r"lag period of one hour could be applied"),
            P("mulehunter",
              "The RBI's innovation hub built a tool called Mulehunter.AI in 2024 to "
              "detect mule bank accounts quickly.",
              r"Mulehunter\.AI"),
        ),
    ),
    SourceSeed(
        key="rbi_123pay",
        org="Reserve Bank of India",
        title=(
            "Reserve Bank of India launches (a) UPI for Feature Phones (UPI123pay) and "
            "(b) 24x7 Helpline for Digital Payments (DigiSaathi)"
        ),
        url="https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx?prid=53385",
        published="2022-03-08",
        tier="regulator",
        slots=("feature_phones",),
        probes=(
            P("launch_date",
              "The Reserve Bank of India launched UPI123Pay on 8 March 2022.",
              r"Date\s*:\s*(?P<launch_date>[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})"),
            P("four_paths",
              "UPI123Pay offers four options: an app on a feature phone, a missed call, "
              "a voice call and a sound-based proximity payment.",
              r"UPI123Pay includes four distinct options[\s\S]{0,2500}?"
              r"Proximity Sound-based Payments"),
            P("pin_every_time",
              "The customer has to enter the UPI PIN every single time.",
              r"authenticate the transaction by entering UPI PIN"),
        ),
    ),
    SourceSeed(
        key="rbi_credit_upi",
        org="Reserve Bank of India",
        title=(
            "Operation of Pre-Sanctioned Credit Lines at Banks through Unified Payments "
            "Interface (UPI), RBI/2023-24/58 CO.DPSS.POLC.No.S-567/02-23-001/2023-2024"
        ),
        url="https://www.rbi.org.in/scripts/NotificationUser.aspx?Id=12532",
        published="2023-09-04",
        tier="regulator",
        slots=("credit_upi",),
        probes=(
            P("title",
              "The RBI circular on pre-sanctioned credit lines through UPI is dated "
              "4 September 2023 and was updated on 12 February 2025.",
              r"CO\.DPSS\.POLC\.No\.S-567/02-23-001/2023-2024\s*September\s+\d{2},\s*(?P<circ_year>\d{4})"
              r"\s*\(Updated as on\s+(?P<updated_month>[A-Za-z]+)\s+\d{1,2},\s*(?P<updated_year>\d{4})\)"),
            P("scope",
              "The scope of UPI was expanded to include credit lines as a funding account.",
              r"scope of UPI is now being expanded by inclusion of credit lines as a "
              r"funding account"),
            P("board_policy",
              "Banks may set the credit limit, period and interest rate under a "
              "board-approved policy.",
              r"stipulate.{0,160}?credit limit, period of credit, rate of interest"),
        ),
    ),
    SourceSeed(
        key="rbi_dpi",
        org="Reserve Bank of India",
        title="RBI - Digital Payments Index for September 2025",
        url="https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=62213",
        published="2026-02-12",
        tier="regulator",
        slots=("growth", "dpi"),
        probes=(
            P("index",
              "The RBI's Digital Payments Index stood at 516.76 for September 2025, up "
              "from 493.22 in March 2025.",
              r"index for September 2025 stands at (?P<index>[\d.]+) as against (?P<index_prev>[\d.]+) for March 2025"),
            P("base",
              "The index is compiled with March 2018 as the base and has been published "
              "since January 2021.",
              r"since January 1, (\d{4}) with March (\d{4}) as base"),
        ),
    ),

    # --- reputable press ------------------------------------------------
    SourceSeed(
        key="bs_small_merchants",
        org="Business Standard",
        title="Small merchants built UPI's reach. Here's what government data shows",
        url="https://www.business-standard.com/finance/news/small-merchants-built-upi-s-reach-here-s-what-government-data-shows-126081700057_1.html",
        published="2026-08-17",
        tier="reputable_press",
        slots=("merchant_adoption", "share"),
        probes=(
            P("survey",
              "A government-commissioned study found 94 per cent of small merchants "
              "surveyed had adopted UPI.",
              r"with (?P<survey_pct>\d+) per cent of small merchants surveyed reporting that they had "
              r"adopted UPI"),
            P("merchants_onboarded",
              "An NPCI and BCG report estimated soundboxes and interoperable QR codes "
              "brought 65 million to 70 million merchants onto digital payments.",
              r"had helped bring (?P<merchants_low>\d+) million to (?P<merchants_high>\d+) million merchants onto digital payments"),
            P("share",
              "UPI accounts for about 85 per cent of India's digital payment transaction volume.",
              r"accounting for about (?P<share_pct>\d+) per cent of India.{0,3}s digital payment "
              r"transaction volume"),
        ),
    ),
    SourceSeed(
        key="bs_record_july",
        org="Business Standard",
        title="UPI clocks record monthly volume as July transactions rise 4.1% to 23.66 bn",
        url="https://www.business-standard.com/finance/news/upi-transactions-hit-record-23-66-billion-in-july-value-rs-29-88-trillion-126080100548_1.html",
        published="2026-08-01",
        tier="reputable_press",
        slots=("recent_moment",),
        probes=(
            P("july_record",
              "UPI recorded its highest-ever monthly volume in July 2026 at 23.66 billion "
              "transactions, up 22 per cent year on year.",
              r"Transaction volume rose ([\d.]+) per cent from June and (\d+) per cent "
              r"year-on-year"),
            P("record_word",
              "July 2026 was UPI's highest-ever monthly volume on record.",
              r"highest-ever monthly volume"),
        ),
    ),
    SourceSeed(
        key="thehindu_h1",
        org="The Hindu",
        title="UPI volume jumps 27% to touch 145 bn in first half",
        url="https://www.thehindu.com/business/upi-volume-jumps-27-to-touch-145-bn-in-first-half/article71538372.ece",
        published="2026-10-02",
        tier="reputable_press",
        slots=("recent_moment", "scale_now"),
        probes=(
            P("sept",
              "In September 2026 UPI handled 24.07 billion transactions worth 29.37 lakh "
              "crore rupees.",
              r"volume moderated by ([\d.]+)% to ([\d.]+) billion compared to ([\d.]+) "
              r"billion last month"),
            P("h1",
              "In the first half of the 2026-27 financial year UPI volume rose 27 per "
              "cent to touch 145 billion transactions.",
              r"UPI volume jumps (\d+)% to touch (\d+) bn in first half"),
            P("h1_value",
              "UPI value in that half rose 20 per cent to 177 lakh crore rupees from "
              "148 lakh crore rupees.",
              r"value term rose a slightly lower rate of (\d+)% to ₹\s*([\d,]+) lakh crore "
              r"as against ₹\s*([\d,]+) lakh crore"),
        ),
    ),
    SourceSeed(
        key="medianama_soundbox",
        org="Medianama",
        title="223: NPCI Plans Interoperable Soundbox for Merchants",
        url="https://www.medianama.com/2026/05/223-npci-roll-out-one-soundbox-upi-apps-retail-payments",
        published="2026-05-21",
        tier="reputable_press",
        slots=("qr_soundbox_cost",),
        probes=(
            P("subscription_cost",
              "Merchants typically pay between 100 and 150 rupees a month for each "
              "soundbox device they run.",
              r"cost between Rs ?(?P<cost_low>\d+) and Rs ?(?P<cost_high>\d+) per month"),
            P("one_box",
              "Each separate payment app QR code needs its own linked soundbox.",
              r"Each QR code is linked to a separate Soundbox"),
            P("interoperable_box",
              "NPCI is working on a single interoperable soundbox for all apps.",
              r"unified, interoperable Soundbox system for merchants"),
        ),
    ),
    SourceSeed(
        key="india_today_journey",
        org="India Today",
        title="100 milliseconds, 4 hops, zero mistakes: The invisible journey of your UPI payments",
        url="https://www.indiatoday.in/science/story/upi-payment-process-explained-how-banks-npci-and-soundboxes-finish-payments-in-seconds-2997558-2026-09-18",
        published="2026-09-18",
        tier="reputable_press",
        slots=("how_it_works",),
        probes=(
            P("four_hops",
              "A UPI payment passes through four hops, ending with the mobile network "
              "alerting the shopkeeper's soundbox.",
              r"The third is the shopkeeper.{0,3}s\s+bank, or the beneficiary bank"
              r"[\s\S]{0,400}?four separate computer systems"),
            P("switchboard",
              "NPCI works as the switchboard that routes the payment but never holds the money.",
              r"the switchboard operator who never actually touches a rupee"),
            P("guardian",
              "The customer's own bank, called the remitter bank, guards the money first.",
              r"called the remitter bank"),
        ),
    ),
    SourceSeed(
        key="toi_lite_x",
        org="Times of India",
        title="Upi: UPI Lite X for offline payments: What it means for users",
        url="https://timesofindia.indiatimes.com/gadgets-news/upi-lite-x-for-offline-payments-what-it-means-for-users/articleshow/103534458.cms",
        published="2023-09-09",
        tier="reputable_press",
        slots=("lite_x",),
        probes=(
            P("offline",
              "UPI Lite X lets people send and receive money while completely offline.",
              r"Lite X, which allows users to send and receive money while being "
              r"completely offline"),
            P("nfc",
              "UPI Lite X uses near-field communication to move money between balances "
              "held on the phone.",
              r"uses Near Field Communication \(NFC\) to transfer money between on-device wallets"),
            P("poor_connectivity",
              "UPI Lite X is aimed at areas with poor connectivity.",
              r"especially in areas with poor connectivity"),
        ),
    ),
    SourceSeed(
        key="mint_market_cap",
        org="Mint",
        title="NPCI extends deadline for compliance with UPI volume cap by 2 years",
        url="https://www.livemint.com/industry/npci-upi-volume-cap-kyc-phonepe-paytm-google-pay-traps-navi-cred-bhim-whatsapp-pay-fintech-rbi-rupay-11735653716559.html",
        published="2025-01-01",
        tier="reputable_press",
        slots=("market_cap",),
        probes=(
            P("cap",
              "No single UPI app may handle more than 30 per cent of total UPI volume.",
              r"no UPI \(unified payments interface\) app could account for more than "
              r"(?P<cap_pct>\d+)% of UPI transaction volumes"),
            P("deadline",
              "The deadline for complying with the cap was extended to 31 December 2026.",
              r"extended by two years till (?P<deadline>[A-Za-z]+ \d+, \d{4})"),
        ),
    ),
    SourceSeed(
        key="bbc_fraud",
        org="BBC News",
        title="RBI: India's central bank steps up fight against digital fraud",
        url="https://www.bbc.com/news/articles/cp3l3p7lzppo",
        published="2026-04-29",
        tier="reputable_press",
        slots=("fraud_scale",),
        probes=(
            P("victims",
              "Nearly 2.5 million people lost about 2.5 billion dollars to digital fraud "
              "in 2025, a rise of 4,300 per cent since 2021.",
              r"Nearly (?P<victims_mn>[\d.]+) million people have lost some \$(?P<loss_bn>[\d.]+)bn in (?P<victims_year>\d{4}), "
              r"a staggering (?P<rise_pct>[\d,]+)% rise since (?P<base_year>\d{4})"),
            P("rbi_response",
              "The rising numbers prompted the RBI to step in with a discussion paper.",
              r"prompted India's central bank, the Reserve Bank of India \(RBI\) to step in"),
        ),
    ),

    # --- official but bot-protected: may only be cited with corroboration
    SourceSeed(
        key="npci_about_upi",
        org="National Payments Corporation of India",
        title="About UPI - Unified Payments Interface",
        url="https://www.npci.org.in/product/upi/about-upi",
        published="2026",
        tier="official",
        slots=("how_it_works",),
        probes=(
            P("built_on_imps",
              "UPI is built over the IMPS infrastructure and allows instant transfers "
              "between two bank accounts.",
              r"built over the IMPS infrastructure"),
        ),
    ),
    SourceSeed(
        key="npci_stats",
        org="National Payments Corporation of India",
        title="Unified Payments Interface (UPI) Product Statistics",
        url="https://www.npci.org.in/product/upi/product-statistics",
        published="2026",
        tier="official",
        slots=("scale_now", "recent_moment"),
        probes=(
            P("monthly_table",
              "NPCI publishes the official month-by-month UPI transaction volume and "
              "value table.",
              r"Product Statistics"),
        ),
    ),
    SourceSeed(
        key="npci_123pay",
        org="National Payments Corporation of India",
        title="UPI 123PAY",
        url="https://www.npci.org.in/product/upi-123pay",
        published="2026",
        tier="official",
        slots=("feature_phones",),
        probes=(
            P("call_karo",
              "UPI 123PAY is an instant payment system for feature phone users.",
              r"instant payment system for feature phone users"),
        ),
    ),
    SourceSeed(
        key="npci_lite",
        org="National Payments Corporation of India",
        title="UPI LITE",
        url="https://www.npci.org.in/product/upi/upi-lite",
        published="2026",
        tier="official",
        slots=("lite_x",),
        probes=(
            P("below_1000",
              "UPI LITE is designed to process transactions below 1,000 rupees in a "
              "faster, PIN-less way.",
              r"designed to process low value transactions that are below"),
        ),
    ),
)


# Which probe keys each bot-protected source may borrow, and from where.
CORROBORATION: dict[str, tuple[str, ...]] = {
    "npci_about_upi": ("india_today_journey",),
    "npci_stats": ("pib_10y", "thehindu_h1"),
    "npci_123pay": ("rbi_123pay",),
    "npci_lite": ("toi_lite_x",),
}

SEED_BY_KEY = {s.key: s for s in SEEDS}

# Which claim slot each probe feeds. This is the contract between a probe and the
# chapter movement that needs it: the Researcher files a probe's claim under its
# slot here, and the Writer only asks for the slots its movements name.
PROBE_SLOTS: dict[str, str] = {
    "pib_10y:fy26_volume": "scale_now",
    "pib_10y:fy26_value": "scale_now",
    "pib_10y:yoy_volume": "growth",
    "pib_10y:yoy_value": "growth",
    "pib_10y:daily_volume": "scale_now",
    "pib_10y:record_month": "scale_now",
    "pib_10y:banks_live": "reach",
    "pib_10y:banks_launch": "reach",
    "pib_10y:share_digital": "share",
    "pib_10y:share_global": "global",
    "pib_10y:p2m_share": "small_ticket",
    "pib_10y:p2m_small_ticket": "small_ticket",
    "pib_10y:surge": "growth",
    "pib_55crore:users": "users",
    "pib_55crore:fy_table": "scale_now",
    "pib_imf_aci:india_share": "global",
    "pib_imf_aci:world_total": "global",
    "pib_imf_aci:imf_label": "global",
    "pib_imf_aci:aci_source": "global",
    "pib_pidf:qr_deployed": "reach",
    "pib_pidf:share_fy25": "share",
    "pib_pidf:retail_total": "scale_now",
    "pib_pidf:pidf": "reach",
    "pib_pidf:123pay_purpose": "feature_phones",
    "rbi_ar_2025:growth_fy25": "growth",
    "rbi_ar_2025:share_retail": "share",
    "rbi_ar_2025:qr_growth": "reach",
    "rbi_ar_2025:pos_growth": "reach",
    "rbi_ar_2025:settlement": "settlement",
    "pib_incentive:outlay": "incentive",
    "pib_incentive:rate": "incentive",
    "pib_incentive:zero_mdr_table": "free_to_accept",
    "pib_gst:gazette": "no_gst",
    "pib_gst:no_gst": "no_gst",
    "pib_gst:allocations": "no_gst",
    "rbi_charges_dp:section10a": "free_to_accept",
    "rbi_charges_dp:zero_from": "free_to_accept",
    "rbi_charges_dp:reimbursement": "incentive",
    "rbi_charges_dp:card_mdr_table": "card_mdr",
    "pib_mdr_96:free_96": "mdr_now",
    "pib_mdr_96:p2p_free": "mdr_now",
    "pib_mdr_96:mdr_rate": "mdr_now",
    "pib_mdr_96:mdr_cap": "mdr_now",
    "pib_mdr_96:p2pm": "p2pm",
    "pib_mdr_96:essential_sectors": "mdr_now",
    "rbi_tat:transfer_t1": "failed_txn",
    "rbi_tat:merchant_t5": "failed_txn",
    "rbi_tat:compensation": "compensation",
    "rbi_tat:compensation_transfer": "compensation",
    "rbi_ombudsman:effective": "ombudsman",
    "rbi_ombudsman:cost_free": "ombudsman",
    "rbi_ombudsman:comp_30lakh": "ombudsman",
    "rbi_ombudsman:comp_3lakh": "ombudsman",
    "rbi_ombudsman:monetary_limit": "ombudsman",
    "rbi_fraud_dp:fraud_table": "fraud_scale",
    "rbi_fraud_dp:concentration": "fraud_concentration",
    "rbi_fraud_dp:lag": "fraud_response",
    "rbi_fraud_dp:mulehunter": "fraud_response",
    "rbi_123pay:launch_date": "feature_phones",
    "rbi_123pay:four_paths": "feature_phones",
    "rbi_123pay:pin_every_time": "feature_phones",
    "rbi_credit_upi:title": "credit_upi",
    "rbi_credit_upi:scope": "credit_upi",
    "rbi_credit_upi:board_policy": "credit_upi",
    "rbi_dpi:index": "dpi",
    "rbi_dpi:base": "dpi",
    "rbi_ar_2026:merchant_acceptance": "merchant_adoption",
    "rbi_ar_2026:upi_predominant": "merchant_adoption",
    "rbi_ar_2026:retail_growth": "growth",
    "rbi_ar_2026:upi_growth_26": "growth",
    "rbi_ar_2026:vision_2028": "recent_moment",
    "bs_small_merchants:survey": "merchant_adoption",
    "bs_small_merchants:merchants_onboarded": "merchant_adoption",
    "bs_small_merchants:share": "share",
    "bs_record_july:july_record": "recent_moment",
    "bs_record_july:record_word": "recent_moment",
    "thehindu_h1:sept": "recent_moment",
    "thehindu_h1:h1": "recent_moment",
    "thehindu_h1:h1_value": "scale_now",
    "medianama_soundbox:subscription_cost": "qr_soundbox_cost",
    "medianama_soundbox:one_box": "qr_soundbox_cost",
    "medianama_soundbox:interoperable_box": "qr_soundbox_cost",
    "india_today_journey:four_hops": "how_it_works",
    "india_today_journey:switchboard": "how_it_works",
    "india_today_journey:guardian": "how_it_works",
    "toi_lite_x:offline": "lite_x",
    "toi_lite_x:nfc": "lite_x",
    "toi_lite_x:poor_connectivity": "lite_x",
    "mint_market_cap:cap": "market_cap",
    "mint_market_cap:deadline": "market_cap",
    "bbc_fraud:victims": "fraud_scale",
    "bbc_fraud:rbi_response": "fraud_response",
    "npci_about_upi:built_on_imps": "how_it_works",
    "npci_stats:monthly_table": "scale_now",
    "npci_123pay:call_karo": "feature_phones",
    "npci_lite:below_1000": "lite_x",
}

SLOT_TITLES = {
    "how_it_works": "How a UPI payment actually travels",
    "scale_now": "How big UPI is right now",
    "growth": "How fast it is growing",
    "share": "How much of India's payment traffic UPI now is",
    "global": "How India compares with the rest of the world",
    "small_ticket": "The size of the payments shops actually take",
    "reach": "How far UPI reaches into the country",
    "users": "How many people use UPI",
    "merchant_adoption": "How small merchants have adopted it",
    "recent_moment": "The very latest numbers",
    "free_to_accept": "Why accepting UPI costs nothing",
    "no_gst": "Why there is no GST on UPI",
    "card_mdr": "How charges work on card payments, for contrast",
    "incentive": "Government incentives for small UPI transactions",
    "mdr_now": "The charge rules as they stand now",
    "p2pm": "The rule that protects very small merchants",
    "settlement": "How fast the money reaches your account",
    "qr_soundbox_cost": "What the equipment costs you",
    "failed_txn": "What happens when a payment fails",
    "compensation": "What you are owed if the bank is slow",
    "ombudsman": "Where a customer takes a complaint",
    "fraud_scale": "How much digital-payment fraud there is",
    "fraud_concentration": "Which payments fraudsters target",
    "fraud_response": "What the regulator is doing about it",
    "feature_phones": "UPI for basic mobile phones",
    "lite_x": "Paying when the network is down",
    "credit_upi": "Lending and borrowing on UPI",
    "market_cap": "Keeping any one app from taking over",
    "dpi": "The regulator's own measure of digitisation",
}