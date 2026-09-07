"""Stored ints on SubscriptionUsageCurrent.SubscriptionStatus.

Mirrors blocks-utilities, which writes the field. Values are explicit because they are
stored -- keep the two in step.
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
