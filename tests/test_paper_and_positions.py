import pytest

from src.core.models import BookLevel, Order, OrderBook, OrderStatus, Settlement, Side
from src.execution.paper import PaperBroker
from src.execution.positions import PositionManager
from src.fee_engine.engine import FeeEngine
from src.fee_engine.tiers import get_tier
from tests.helpers import mk_book, t


@pytest.fixture
def broker() -> PaperBroker:
    return PaperBroker(FeeEngine(get_tier("gold")), {"GGAL": 1000})


def order(side: Side, qty: float, price: float) -> Order:
    return Order(strategy="x", symbol="GGAL", side=side, qty=qty, price=price, ts=t(12, 0))


async def test_buy_walks_book_levels_and_charges_fees(broker: PaperBroker) -> None:
    book = OrderBook(
        symbol="GGAL",
        ts=t(12, 0),
        bids=[BookLevel(price=99, size=100)],
        asks=[BookLevel(price=100, size=50), BookLevel(price=101, size=100)],
    )
    o, fills = await broker.submit(order(Side.BUY, 120, 101), book)
    assert [f.qty for f in fills] == [50, 70]
    assert o.status is OrderStatus.FILLED
    assert o.avg_price == pytest.approx((50 * 100 + 70 * 101) / 120)
    assert all(f.fee > 0 for f in fills)
    assert broker.available("GGAL") == 1120


async def test_limit_price_respected_remainder_rests(broker: PaperBroker) -> None:
    book = mk_book("GGAL", 99, 100, t(12, 0), asize=30)
    o, fills = await broker.submit(order(Side.BUY, 100, 100), book)  # solo hay 30 a <=100
    assert sum(f.qty for f in fills) == 30
    assert o.status is OrderStatus.PARTIAL and len(broker.open_orders()) == 1
    later = mk_book("GGAL", 98, 99.5, t(12, 1), asize=500)  # el mercado cruza nuestro limite
    more = broker.on_book(later)
    assert sum(f.qty for f in more) == 70 and not broker.open_orders()


async def test_cannot_sell_without_inventory(broker: PaperBroker) -> None:
    book = mk_book("GGAL", 99, 100, t(12, 0))
    o, fills = await broker.submit(order(Side.SELL, 5000, 99), book)
    assert o.status is OrderStatus.REJECTED and not fills


async def test_intraday_closing_leg_pays_less_commission(broker: PaperBroker) -> None:
    book = mk_book("GGAL", 100, 100.5, t(12, 0))
    _, entry = await broker.submit(order(Side.BUY, 100, 101), book)
    _, exit_ = await broker.submit(order(Side.SELL, 100, 100), book, closing=True)
    assert exit_[0].fee < entry[0].fee


def test_position_realized_pnl_and_flip() -> None:
    pm = PositionManager()
    from src.core.models import Fill

    def fill(side: Side, qty: float, px: float) -> Fill:
        return Fill(
            order_id="1",
            strategy="s",
            symbol="GGAL",
            settlement=Settlement.CI,
            side=side,
            qty=qty,
            price=px,
            fee=0,
            ts=t(12, 0),
        )

    assert pm.apply_fill(fill(Side.BUY, 100, 100)) == 0
    assert pm.apply_fill(fill(Side.BUY, 100, 110)) == 0
    pos = pm.get("s", "GGAL", Settlement.CI)
    assert pos and pos.avg_price == 105 and pos.qty == 200
    assert pm.apply_fill(fill(Side.SELL, 50, 115)) == pytest.approx(500)  # 50 * (115-105)
    assert pm.apply_fill(fill(Side.SELL, 150, 100)) == pytest.approx(150 * -5)
    assert not pm.open_positions()
