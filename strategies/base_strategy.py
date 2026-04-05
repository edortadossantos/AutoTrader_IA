"""
Interfaz base para todas las estrategias.
"""
from abc import ABC, abstractmethod


class BaseStrategy(ABC):
    name: str = "base"

    @abstractmethod
    def generate_signal(
        self,
        technical: dict,
        news: dict,
        market_sentiment: float,
    ) -> dict:
        """
        Retorna:
          {
            "action": "BUY" | "SELL" | "HOLD",
            "confidence": float 0-1,
            "reason": str,
          }
        """
        ...
