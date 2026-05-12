"""
Disposable email detection using disposable-email-domains blocklist.
"""
from functools import lru_cache
from disposable_email_domains import blocklist


@lru_cache(maxsize=1)
def _blocklist_set() -> set[str]:
    return {domain.lower().strip() for domain in blocklist}


def is_disposable_email(email: str) -> bool:
    """Return True when the email domain (or parent domain) is disposable."""
    if not email or "@" not in email:
        return False

    domain = email.rsplit("@", 1)[-1].lower().strip()
    if not domain:
        return False

    domains = _blocklist_set()
    if domain in domains:
        return True

    parts = domain.split(".")
    for idx in range(1, len(parts)):
        suffix = ".".join(parts[idx:])
        if suffix in domains:
            return True

    return False
