"""Permission-controlled benchmark scorer auditing.

The package deliberately separates frozen generations, answer extraction, and
scoring policy so each stage can be replayed without another model call.
"""

from .engine import audit, summarize_audit
from .types import AnswerValue, GoldItem, PredictionItem

__all__ = ["AnswerValue", "GoldItem", "PredictionItem", "audit", "summarize_audit"]
