"""Tests for orders HTML parsing (no networking)."""

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from oneway_cli.client import (
    Order,
    OrderCharge,
    RepackedPackage,
    OneWayError,
    parse_orders,
)

# ── Sanitized synthetic HTML ────────────────────────────────────────────────

HEADER = """<tr>
<th>Warehouse</th><th>Status</th><th>Tracking</th><th>Dimensions</th>
<th>Weight</th><th>Arrival USA</th><th>Arrival Venezuela</th>
<th>Notes</th><th>Total</th>
</tr>"""

MAIN_1 = """<tr>
<td>MIA123</td><td>En almacén</td>
<td><a href="/onewayidv2/orders/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee">ABC123456</a></td>
<td>30×20×15</td><td>5.2 kg</td><td>2025-06-01</td><td>—</td>
<td>—</td><td>$45.00</td>
</tr>"""

REPACK = """<tr>
<td>MIA123</td><td>Reempaque</td>
<td><span class="line-through">ABC123456</span></td>
<td>25×18×12</td><td>4.8 kg</td><td>2025-06-01</td><td>—</td>
<td>Reempaque realizado</td><td>$10.00</td>
</tr>"""

FEE = """<tr>
<td>MIA123</td><td>Pendiente</td><td>—</td><td>—</td><td>—</td>
<td>—</td><td>—</td><td>Repack Fee</td><td>$5.00</td>
</tr>"""

MAIN_2 = """<tr>
<td>CCS456</td><td>Pagado</td>
<td><a href="/onewayidv2/orders/ffffffff-gggg-hhhh-iiii-jjjjjjjjjjjj">DEF789012</a></td>
<td>40×30×20</td><td>8.0 kg</td><td>2025-06-10</td><td>2025-06-20</td>
<td>Frágil</td><td>$120.00</td>
</tr>"""

TOTAL = """<tr><td colspan="8">Total:</td><td>$198.00</td></tr>"""


COMPLETE_HTML = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Órdenes</title></head>
<body><div class="table-responsive">
<table class="table orders-table">
<thead>{HEADER}</thead>
<tbody>{MAIN_1}{REPACK}{FEE}{MAIN_2}</tbody>
<tfoot>{TOTAL}</tfoot>
</table></div></body></html>"""


class TestParseOrders(unittest.TestCase):

    def test_main_row_parsed(self) -> None:
        result = parse_orders(COMPLETE_HTML)
        self.assertEqual(len(result.orders), 2)
        o1 = result.orders[0]
        self.assertIsInstance(o1, Order)
        self.assertEqual(o1.warehouse, "MIA123")
        self.assertEqual(o1.status, "En almacén")
        self.assertEqual(o1.tracking, "ABC123456")
        self.assertEqual(o1.dimensions, "30×20×15")
        self.assertEqual(o1.weight, "5.2 kg")
        self.assertEqual(o1.arrived_usa, "2025-06-01")
        self.assertEqual(o1.arrived_venezuela, "—")
        self.assertEqual(o1.notes, "—")
        self.assertEqual(o1.total, "$45.00")
        self.assertEqual(o1.order_uuid, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        self.assertFalse(o1.is_detail)
        # Second order has no children
        self.assertEqual(len(result.orders[1].charges), 0)
        self.assertEqual(len(result.orders[1].repacked_packages), 0)

    def test_repacked_and_fees(self) -> None:
        result = parse_orders(COMPLETE_HTML)
        o1 = result.orders[0]
        self.assertEqual(len(o1.repacked_packages), 1)
        self.assertEqual(len(o1.charges), 1)

        rp = o1.repacked_packages[0]
        self.assertIsInstance(rp, RepackedPackage)
        self.assertEqual(rp.tracking, "ABC123456")
        self.assertEqual(rp.total, "$10.00")

        ch = o1.charges[0]
        self.assertIsInstance(ch, OrderCharge)
        self.assertEqual(ch.label, "Repack Fee")
        self.assertEqual(ch.total, "$5.00")

    def test_total_footer(self) -> None:
        self.assertEqual(parse_orders(COMPLETE_HTML).total, "$198.00")

    def test_empty_table(self) -> None:
        html = """<html><body><table><tr><th>Warehouse</th><th>Status</th>
        <th>Tracking</th><th>Dimensions</th><th>Weight</th><th>Arrival USA</th>
        <th>Arrival Venezuela</th><th>Notes</th><th>Total</th></tr>
        <tr><td>Total:</td><td colspan="7"></td><td>$0.00</td></tr>
        </table></body></html>"""
        result = parse_orders(html)
        self.assertEqual(len(result), 0)
        self.assertEqual(result.total, "$0.00")

    def test_missing_table_raises(self) -> None:
        with self.assertRaises(OneWayError):
            parse_orders("<html><body><p>No table</p></body></html>")

    def test_detail_row_flag(self) -> None:
        html = f"""<html><body><table>
        <thead>{HEADER}</thead>
        <tbody><tr><td>MIA1</td><td>Info</td>
        <td><a href="/onewayidv2/orders/detail-uuid">—</a></td>
        <td>—</td><td>—</td><td>—</td><td>—</td>
        <td>Note</td><td>$0.00</td></tr></tbody>
        <tfoot><tr><td colspan="8">Total:</td><td>$0.00</td></tr></tfoot>
        </table></body></html>"""
        self.assertTrue(parse_orders(html).orders[0].is_detail)


if __name__ == "__main__":
    unittest.main()
