"""Indian equity delivery trading costs, itemised.

Every swing backtest pays these, so a strategy that only works before costs is
reported as not working. Rates are the statutory ones for NSE delivery trades
(as published by NSE and SEBI); brokerage is zero at the common discount
brokers for delivery, and slippage is an assumption for liquid NIFTY 100
names, recorded as such.

Not modelled: the flat depository charge per scrip sold (about Rs 15 to 20,
negligible for the position sizes the paper accounts use) and capital-gains
tax, which depends on the investor.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

__all__ = ["CostModel", "DELIVERY", "ZERO"]


@dataclass(frozen=True)
class CostModel:
    stt: float = 0.001                 # securities transaction tax, both sides (delivery)
    stamp_duty_buy: float = 0.00015    # buy side only
    exchange_txn: float = 0.0000297    # NSE transaction charge
    sebi_fee: float = 0.000001
    gst: float = 0.18                  # on brokerage + exchange + SEBI fees
    brokerage: float = 0.0
    slippage: float = 0.0005           # assumption: half a spread plus impact

    @property
    def _fees(self) -> float:
        return (self.brokerage + self.exchange_txn + self.sebi_fee) * (1.0 + self.gst)

    @property
    def buy_rate(self) -> float:
        return self.stt + self.stamp_duty_buy + self._fees + self.slippage

    @property
    def sell_rate(self) -> float:
        return self.stt + self._fees + self.slippage

    @property
    def round_trip(self) -> float:
        return self.buy_rate + self.sell_rate

    def cost(self, bought: float, sold: float) -> float:
        """Rupee (or fraction-of-equity) cost of buying and selling these values."""
        return bought * self.buy_rate + sold * self.sell_rate

    def describe(self) -> dict:
        return {**asdict(self), "buy_rate": self.buy_rate, "sell_rate": self.sell_rate,
                "round_trip": self.round_trip}


DELIVERY = CostModel()
ZERO = CostModel(stt=0.0, stamp_duty_buy=0.0, exchange_txn=0.0, sebi_fee=0.0, brokerage=0.0, slippage=0.0)
