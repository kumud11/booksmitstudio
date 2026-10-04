"""The curated three-chapter skeleton for the bundled UPI book.

The skeleton lives here, apart from the Planner, because a `BookSpec` owns the
outline of whatever book is being made. The bundled book is just the first spec;
a book created from the studio index page carries its own outline, and the Planner
reads that instead of this one.
"""

from __future__ import annotations

SKELETON: tuple[dict, ...] = (
    {
        "title": "The Ten-Year Rebuild of How India Pays",
        "purpose": (
            "Show a first-time shop owner that UPI is no longer a novelty but the "
            "ordinary way a huge share of their customers will pay, and explain in "
            "plain words what actually happens when a customer scans."
        ),
        "movements": [
            ("open", "Open with the change in the reader's own shop: the customer who "
                     "used to ask for cash now asks for the QR code.", ()),
            ("how_it_works", "Explain the journey of one rupee, naming each party as a "
                            "person rather than a system.",
             ("how_it_works",), ("UPI", "UPI ID", "NPCI")),
            ("scale_now", "Give the size of the system in one breath, then shrink it down "
                          "to a single day.", ("scale_now", "users"), ()),
            ("growth", "Show the trend line: five years of growth, and the growth in the "
                       "number of QR codes in the country.",
             ("growth", "share", "dpi"), ()),
            ("global", "Place India in the world, crediting the actual source of the "
                       "comparison.", ("global",), ()),
            ("small_ticket", "Bring it back to the counter: most shop payments are tiny.",
             ("small_ticket",), ("P2M", "P2P")),
            ("reach", "Explain the equipment: QR codes, touch points, and what they mean "
                      "for a customer in a small town.",
             ("reach", "merchant_adoption", "recent_moment"), ("QR code",)),
            ("close", "Land the chapter on what this means for the reader's own counter.",
             ()),
        ],
    },
    {
        "title": "What It Costs You, and How the Money Reaches You",
        "purpose": (
            "Remove the two fears every new shopkeeper has - that digital payments will "
            "eat into their margin and that the money will not arrive - by showing the "
            "zero-charge rule and how fast settlement really works."
        ),
        "movements": [
            ("open", "Open with the fear: will I be charged for this?", ()),
            ("free_to_accept", "Explain why accepting UPI is free, using the statute and "
                               "the date it began.", ("free_to_accept",), ("MDR",)),
            ("no_gst", "Deal with the rumour about GST head-on.", ("no_gst",), ()),
            ("incentive", "Explain the government incentive for small transactions and "
                          "what it is worth.", ("incentive", "card_mdr"), ()),
            ("mdr_now", "Explain the current charge rules honestly, including who does "
                        "pay and how much.", ("mdr_now", "p2pm"), ()),
            ("settlement", "Explain settlement: real time for UPI against days for cards.",
             ("settlement",), ("turn-around time",)),
            ("qr_soundbox_cost", "Be honest about the one cost that is real: equipment.",
             ("qr_soundbox_cost",), ("soundbox",)),
            ("close", "Summarise the money picture for a first-time owner.", ()),
        ],
    },
    {
        "title": "When Things Go Wrong, and Where UPI Is Going",
        "purpose": (
            "Honesty about the weak spots, then the practical protections, then the "
            "direction of travel - so the reader feels equipped rather than sold to."
        ),
        "movements": [
            ("open", "Open with the moment every shopkeeper dreads: money debited, "
                     "nothing delivered.", ()),
            ("failed_txn", "Explain auto-reversal and the deadlines the banks must meet.",
             ("failed_txn", "compensation"), ("auto-reversal", "turn-around time")),
            ("ombudsman", "Explain the customer's route to a complaint, and what it "
                          "means for you as a merchant.", ("ombudsman",), ("chargeback",)),
            ("fraud_scale", "Present the fraud numbers honestly and explain what they "
                            "mean for a small counter.", ("fraud_scale",), ()),
            ("fraud_concentration", "Explain that most fraud value sits in large "
                                    "transactions, not small ones.",
             ("fraud_concentration", "fraud_response"), ()),
            ("feature_phones", "Explain UPI on basic phones for customers without "
                               "smartphones.", ("feature_phones",), ("UPI 123Pay",)),
            ("lite_x", "Explain paying when the network is down.", ("lite_x",),
             ("UPI Lite",)),
            ("credit_upi", "Explain credit on UPI, carefully and with the risks named.",
             ("credit_upi",), ("credit line",)),
            ("market_cap", "Explain the limit that stops any single app taking over UPI.",
             ("market_cap",), ()),
            ("close", "Close with a practical, encouraging summary.", ()),
        ],
    },
)