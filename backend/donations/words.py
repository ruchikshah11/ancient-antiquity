"""Amounts in words with Indian numbering (thousand, lakh, crore), as printed on receipts."""
from decimal import ROUND_HALF_UP, Decimal

ONES = ("", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
        "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen")
TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")


def _below_hundred(n):
    if n < 20:
        return ONES[n]
    return TENS[n // 10] + (f"-{ONES[n % 10]}" if n % 10 else "")


def _below_thousand(n):
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f"{ONES[hundreds]} Hundred")
    if rest:
        parts.append(_below_hundred(rest))
    return " ".join(parts)


def number_in_words(n):
    """1234567 -> 'Twelve Lakh Thirty-Four Thousand Five Hundred Sixty-Seven'."""
    n = int(n)
    if n == 0:
        return "Zero"
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    parts = []
    if crore:
        parts.append(f"{number_in_words(crore)} Crore")  # 100 crore and more: "One Hundred Crore"
    if lakh:
        parts.append(f"{_below_hundred(lakh)} Lakh")
    if thousand:
        parts.append(f"{_below_hundred(thousand)} Thousand")
    if n:
        parts.append(_below_thousand(n))
    return " ".join(parts)


def rupees_in_words(amount):
    """Decimal('1250.50') -> 'Rupees One Thousand Two Hundred Fifty and Fifty Paise Only'."""
    amount = Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rupees = int(amount)
    paise = int((amount - rupees) * 100)
    text = f"Rupees {number_in_words(rupees)}"
    if paise:
        text += f" and {_below_hundred(paise)} Paise"
    return text + " Only"
