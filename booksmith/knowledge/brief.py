"""The brief, expressed as data so every agent reads it from one place."""

BRIEF = {
    "title": "Pay Me on UPI: How Digital Payments Changed Small Business in India",
    "audience": "First-time small-business owners in India",
    "language": "English (Indian business context)",
    "chapters": 3,
    "min_words": 600,
    "max_words": 900,
    "voice": (
        "A patient mentor talking to a new shop owner across the counter. Warm, "
        "plain, concrete and encouraging. Short sentences. No jargon without an "
        "immediate plain-English explanation. Never condescending, never a "
        "press release."
    ),
    "citation_style": "Every fact, figure and date carries a bracketed number like [1].",
    "reference_rules": [
        "Each chapter ends with its own numbered reference list.",
        "Each reference gives source organisation, title, date and a working link.",
        "Sources must be real and publicly accessible.",
        "Prefer official sources (RBI, government, NPCI) and reputable news outlets.",
    ],
    "format_rules": [
        "Flowing prose only; no bullet points inside a chapter.",
        "Each chapter ends with a single line starting with 'Takeaway:'.",
        "The Takeaway line comes immediately before that chapter's reference list.",
        "The same tone and voice across all three chapters.",
    ],
    "quality_rules": [
        "Correct grammar, spelling and punctuation throughout.",
        "Every technical term is explained the first time it appears.",
        "No invented or broken sources.",
    ],
}

# Terms the Editor insists are glossed the first time they appear.
GLOSSARY = {
    "UPI": "Unified Payments Interface, India's instant account-to-account payment system",
    "UPI ID": "the virtual payment address that stands in for a bank account number",
    "QR code": "the square scannable pattern printed on a counter or sticker",
    "NPCI": "National Payments Corporation of India, the organisation that runs UPI",
    "RBI": "Reserve Bank of India, the central bank that regulates payments",
    "MDR": "merchant discount rate, the fee a payment company charges a shop for a transaction",
    "P2M": "person-to-merchant, a payment from a customer to a shop",
    "P2P": "person-to-person, a payment from one individual to another",
    "IMPS": "Immediate Payment Service, the bank-to-bank backbone UPI runs on",
    "soundbox": "the small speaker device that announces a payment at a shop counter",
    "turn-around time": "how long a bank may take to fix a failed payment",
    "auto-reversal": "the automatic refund when a payment fails",
    "chargeback": "a request to reverse a payment the customer says was wrong or unauthorised",
    "UPI Lite": "a small-balance version of UPI for low-value payments",
    "UPI 123Pay": "a version of UPI that works on basic feature phones",
    "credit line": "a small loan a bank agrees to lend you in advance",
}