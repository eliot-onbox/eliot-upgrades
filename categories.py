"""Merchant-to-category mapping for spending classification."""

# Maps lowercase substrings in description to categories.
# Order matters: first match wins. More specific patterns go first.
MERCHANT_RULES = [
    # Income
    ("guard service bewa", "income"),
    ("trustly group", "income"),
    ("payment from", "income"),
    ("apple pay deposit", "top_up"),

    # Loan payments
    ("cashper", "loan_payment"),
    ("tf bank", "loan_payment"),

    # Remittances (Philippines)
    ("gelbert t cuevas", "remittance"),
    ("wise", "remittance"),

    # Personal transfers
    ("aurelia russkii", "personal_transfer"),
    ("pocket withdrawal", "savings_transfer"),
    ("to pocket", "savings_transfer"),
    ("closing transaction", "savings_transfer"),

    # Compute / AI
    ("runpod", "compute"),
    ("anthropic", "ai_services"),

    # Food delivery
    ("wolt", "food_delivery"),
    ("foodpanda", "food_delivery"),

    # Food / dining
    ("mcdonald", "food_dining"),
    ("cafe pi pergamon", "food_dining"),
    ("shakey", "food_dining"),

    # Groceries
    ("rewe", "groceries"),
    ("robinsons supermarket", "groceries"),

    # Subscriptions
    ("netflix", "subscriptions"),
    ("apple", "subscriptions"),
    ("google one", "subscriptions"),
    ("brave browser", "subscriptions"),

    # Gaming
    ("riot games", "gaming"),
    ("steam", "gaming"),

    # Shopping
    ("amazon", "shopping"),
    ("beyond the box", "shopping"),
    ("ups", "shipping"),

    # Crypto / trading
    ("revolut digital assets", "crypto"),
    ("fxflat", "trading"),

    # Currency exchange
    ("exchanged to", "currency_exchange"),
]

# Human-readable labels for display
CATEGORY_LABELS = {
    "income": "Income",
    "top_up": "Top-up",
    "loan_payment": "Loan Payment",
    "remittance": "Remittance (PH)",
    "personal_transfer": "Personal Transfer",
    "savings_transfer": "Savings Transfer",
    "compute": "Compute (RunPod)",
    "ai_services": "AI Services",
    "food_delivery": "Food Delivery",
    "food_dining": "Dining Out",
    "groceries": "Groceries",
    "subscriptions": "Subscriptions",
    "gaming": "Gaming",
    "shopping": "Shopping",
    "shipping": "Shipping",
    "crypto": "Crypto",
    "trading": "Trading",
    "currency_exchange": "Currency Exchange",
    "uncategorized": "Uncategorized",
}


def categorize(description: str) -> str:
    desc_lower = description.lower()
    for pattern, category in MERCHANT_RULES:
        if pattern in desc_lower:
            return category
    return "uncategorized"
