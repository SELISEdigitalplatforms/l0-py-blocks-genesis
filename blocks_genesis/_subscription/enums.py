"""Stored ints on SubscriptionUsageCurrent.SubscriptionStatus.

Mirrors blocks-utilities, which writes the field and is the authority:
server/Subscription.DomainService/Enums/SubscriptionStatus.cs. The values there are explicit
precisely because they are persisted -- inserting a member without one would renumber every
value after it and silently reinterpret stored documents. Keep the two in step.
"""
from enum import IntEnum


class SubscriptionStatus(IntEnum):
    INCOMPLETE = 0
    INCOMPLETE_EXPIRED = 1
    TRIALING = 2
    ACTIVE = 3
    PAST_DUE = 4
    UNPAID = 5
    CANCELED = 6
