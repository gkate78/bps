"""
Biller categories (DEC-074): a fixed list, so reports can total bills by kind of bill.

Each biller rule has one category, chosen in Admin Settings. New billers get a best guess from their name,
which the owner can change.
"""

CATEGORIES = (
    "ELECTRICITY",
    "WATER",
    "INTERNET",
    "MOBILE POSTPAID",
    "GOVERNMENT",
    "CREDIT CARD",
    "TOLL",
    "OTHER",
)

# Name keywords → category, checked in order (first match wins).
_KEYWORDS = (
    (("WATER",), "WATER"),
    (("MERALCO", "ELECTRIC", "POWER", "ENERGY", "ELECTRIC COOP"), "ELECTRICITY"),
    (("POSTPAID",), "MOBILE POSTPAID"),
    (("CONVERGE", "PLDT", "FIBER", "GLOBE AT HOME", "SKY", "DITO HOME", "INTERNET", "BROADBAND"), "INTERNET"),
    (("SSS", "PHILHEALTH", "PAG-IBIG", "PAGIBIG", "HDMF", "PSA", "BIR", "NBI", "LTO", "DFA"), "GOVERNMENT"),
    (("BPICC", "CREDIT CARD", "BDO CARD", "METROBANK CARD", "CARD"), "CREDIT CARD"),
    (("EASY TRIP", "EASYTRIP", "AUTO SWEEP", "AUTOSWEEP", "RFID", "TOLL"), "TOLL"),
)


def normalize_category(value) -> str:
    """The category as stored ('' when not one of the list)."""
    text = " ".join(str(value or "").split()).upper()
    return text if text in CATEGORIES else ""


def guess_category(biller) -> str:
    name = " ".join(str(biller or "").split()).upper()
    for words, category in _KEYWORDS:
        if any(word in name for word in words):
            return category
    return "OTHER"
