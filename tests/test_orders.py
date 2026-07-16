"""Tests for orders HTML parsing (no networking)."""

import sys
import unittest
from pathlib import Path

# Allow importing from src/
SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from oneway_cli.client import (
    Order,
    OrderCharge,
    OrdersResult,
    RepackedPackage,
    OneWayError,
    parse_orders,
)

# ── Fully sanitized synthetic HTML ───────────────────────────────────────────

HEADER_ROW = """<tr>
<th>Warehouse</th><th>Status</th><th>Tracking</th><th>Dimensions</th>
<th>Weight</th><th>Arrival USA</th><th>Arrival Venezuela</th>
<th>Notes</th><th>Total</th>
</tr>"""

MAIN_ROW_1 = """<tr>
<td>MIA123</td><td>En almacén</td>
<td><a href="/onewayidv2/orders/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee">ABC123456</a></td>
<td>30×20×15</td><td>5.2 kg</td><td>2025-06-01</td><td>—</td>
<td>—</td><td>$45.00</td>
</tr>"""

REPACKED_ROW = """<tr>
<td>MIA123</td><td>Reempaque</td>
<td><span class="line-through">ABC123456</span></td>
<td>25×18×12</td><td>4.8 kg</td><td>2025-06-01</td><td>—</td>
<td>Reempaque realizado</td><td>$10.00</td>
</tr>"""

FEE_REPACK_ROW = """<tr>
<td>MIA123</td><td>Pendiente</td><td>—</td><td>—</td><td>—</td>
<td>—</td><td>—</td><td>Repack Fee</td><td>$5.00</td>
</tr>"""

FEE_STORAGE_ROW = """<tr>
<td>MIA123</td><td>Pendiente</td><td>—</td><td>—</td><td>—</td>
<td>—</td><td>—</td><td>Storage Fee monthly</td><td>$15.00</td>
</tr>"""

FEE_HANDLING_ROW = """<tr>
<td>MIA123</td><td>Pendiente</td><td>—</td><td>—</td><td>—</td>
<td>—</td><td>—</td><td>Handling fee</td><td>$3.00</td>
</tr>"""

MAIN_ROW_2 = """<tr>
<td>CCS456</td><td>Pagado</td>
<td><a href="/onewayidv2/orders/ffffffff-gggg-hhhh-iiii-jjjjjjjjjjjj">DEF789012</a></td>
<td>40×30×20</td><td>8.0 kg</td><td>2025-06-10</td><td>2025-06-20</td>
<td>Frágil</td><td>$120.00</td>
</tr>"""

TOTAL_ROW = """<tr>
<td colspan="8">Total:</td><td>$198.00</td>
</tr>"""


COMPLETE_HTML = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Órdenes</title></head>
<body>
<div class="table-responsive">
<table class="table orders-table">
<thead>{HEADER_ROW}</thead>
<tbody>
{MAIN_ROW_1}
{REPACKED_ROW}
{FEE_REPACK_ROW}
{FEE_STORAGE_ROW}
{FEE_HANDLING_ROW}
{MAIN_ROW_2}
</tbody>
<tfoot>{TOTAL_ROW}</tfoot>
</table>
</div>
</body></html>"""


class TestParseOrders(unittest.TestCase):
    """Tests for parse_orders() — no session, no networking required."""

    def test_main_order_parsed(self) -> None:
        result = parse_orders(COMPLETE_HTML)
        self.assertEqual(len(result.orders), 2)

        order1 = result.orders[0]
        self.assertIsInstance(order1, Order)
        self.assertEqual(order1.warehouse, "MIA123")
        self.assertEqual(order1.status, "En almacén")
        self.assertEqual(order1.tracking, "ABC123456")
        self.assertEqual(order1.dimensions, "30×20×15")
        self.assertEqual(order1.weight, "5.2 kg")
        self.assertEqual(order1.arrived_usa, "2025-06-01")
        self.assertEqual(order1.arrived_venezuela, "—")
        self.assertEqual(order1.notes, "—")
        self.assertEqual(order1.total, "$45.00")
        self.assertFalse(order1.is_detail)

    def test_order_uuid_extracted(self) -> None:
        result = parse_orders(COMPLETE_HTML)
        self.assertEqual(
            result.orders[0].order_uuid,
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
        self.assertEqual(
            result.orders[1].order_uuid,
            "ffffffff-gggg-hhhh-iiii-jjjjjjjjjjjj",
        )

    def test_repacked_packages(self) -> None:
        result = parse_orders(COMPLETE_HTML)
        order1 = result.orders[0]
        self.assertEqual(len(order1.repacked_packages), 1)

        rp = order1.repacked_packages[0]
        self.assertIsInstance(rp, RepackedPackage)
        self.assertEqual(rp.warehouse, "MIA123")
        self.assertEqual(rp.tracking, "ABC123456")
        self.assertEqual(rp.dimensions, "25×18×12")
        self.assertEqual(rp.weight, "4.8 kg")
        self.assertEqual(rp.arrived_usa, "2025-06-01")
        self.assertEqual(rp.arrived_venezuela, "—")
        self.assertEqual(rp.total, "$10.00")

    def test_charges(self) -> None:
        result = parse_orders(COMPLETE_HTML)
        order1 = result.orders[0]
        self.assertEqual(len(order1.charges), 3)

        labels = [c.label for c in order1.charges]
        self.assertIn("Repack Fee", labels)
        self.assertIn("Storage Fee", labels)
        self.assertIn("Handling Fee", labels)

        repack = order1.charges[0]
        self.assertIsInstance(repack, OrderCharge)
        self.assertEqual(repack.warehouse, "MIA123")
        self.assertEqual(repack.status, "Pendiente")
        self.assertEqual(repack.label, "Repack Fee")
        self.assertEqual(repack.total, "$5.00")

    def test_second_order_has_no_children(self) -> None:
        result = parse_orders(COMPLETE_HTML)
        order2 = result.orders[1]
        self.assertEqual(len(order2.charges), 0)
        self.assertEqual(len(order2.repacked_packages), 0)

    def test_total_footer(self) -> None:
        result = parse_orders(COMPLETE_HTML)
        self.assertEqual(result.total, "$198.00")

    def test_orders_result_iterable(self) -> None:
        result = parse_orders(COMPLETE_HTML)
        self.assertEqual(len(result), 2)
        orders_list = [o for o in result]
        self.assertEqual(len(orders_list), 2)

    def test_orders_result_empty(self) -> None:
        html = """<!DOCTYPE html><html><body>
        <table><tr><th>Warehouse</th><th>Status</th><th>Tracking</th>
        <th>Dimensions</th><th>Weight</th><th>Arrival USA</th>
        <th>Arrival Venezuela</th><th>Notes</th><th>Total</th></tr>
        <tr><td>Total:</td><td colspan="7"></td><td>$0.00</td></tr>
        </table></body></html>"""
        result = parse_orders(html)
        self.assertEqual(len(result), 0)
        self.assertEqual(result.total, "$0.00")

    def test_no_orders_table_raises(self) -> None:
        html = "<html><body><p>No table here</p></body></html>"
        with self.assertRaises(OneWayError):
            parse_orders(html)

    def test_fee_case_insensitive(self) -> None:
        html = f"""<!DOCTYPE html><html><body>
        <table>
        <thead>{HEADER_ROW}</thead>
        <tbody>
        <tr><td>MIA1</td><td>Activo</td>
        <td><a href="/onewayidv2/orders/x-y-z">TRK001</a></td>
        <td>10×10×10</td><td>1 kg</td><td>—</td><td>—</td>
        <td>—</td><td>$0.00</td></tr>
        <tr><td>MIA1</td><td>Pendiente</td><td>—</td><td>—</td>
        <td>—</td><td>—</td><td>—</td>
        <td>repack fee</td><td>$2.00</td></tr>
        <tr><td>MIA1</td><td>Pendiente</td><td>—</td><td>—</td>
        <td>—</td><td>—</td><td>—</td>
        <td>STORAGE FEE</td><td>$5.00</td></tr>
        <tr><td>MIA1</td><td>Pendiente</td><td>—</td><td>—</td>
        <td>—</td><td>—</td><td>—</td>
        <td>Handling Fee</td><td>$1.00</td></tr>
        </tbody>
        <tfoot><tr><td colspan="8">Total:</td><td>$8.00</td></tr>
        </tfoot>
        </table>
        </body></html>"""
        result = parse_orders(html)
        self.assertEqual(len(result.orders), 1)
        self.assertEqual(len(result.orders[0].charges), 3)
        labels = {c.label for c in result.orders[0].charges}
        self.assertEqual(labels, {"Repack Fee", "Storage Fee", "Handling Fee"})

    def test_non_fee_detail_row_skipped(self) -> None:
        """Rows without uuid, without line-through, without fee label are skipped."""
        html = f"""<!DOCTYPE html><html><body>
        <table>
        <thead>{HEADER_ROW}</thead>
        <tbody>
        <tr><td>MIA1</td><td>Activo</td>
        <td><a href="/onewayidv2/orders/x-y-z">TRK001</a></td>
        <td>10×10×10</td><td>1 kg</td><td>—</td><td>—</td>
        <td>—</td><td>$0.00</td></tr>
        <tr><td>MIA1</td><td>Info</td><td>—</td><td>—</td>
        <td>—</td><td>—</td><td>—</td>
        <td>Some random note</td><td>$0.00</td></tr>
        </tbody>
        <tfoot><tr><td colspan="8">Total:</td><td>$0.00</td></tr>
        </tfoot>
        </table>
        </body></html>"""
        result = parse_orders(html)
        self.assertEqual(len(result.orders), 1)
        self.assertEqual(len(result.orders[0].charges), 0)
        self.assertEqual(len(result.orders[0].repacked_packages), 0)

    def test_detail_row_is_detail_flag(self) -> None:
        """A main row without tracking/dimensions/weight gets is_detail=True."""
        html = f"""<!DOCTYPE html><html><body>
        <table>
        <thead>{HEADER_ROW}</thead>
        <tbody>
        <tr><td>MIA1</td><td>Info</td>
        <td><a href="/onewayidv2/orders/detail-uuid">—</a></td>
        <td>—</td><td>—</td><td>—</td><td>—</td>
        <td>Note</td><td>$0.00</td></tr>
        </tbody>
        <tfoot><tr><td colspan="8">Total:</td><td>$0.00</td></tr>
        </tfoot>
        </table>
        </body></html>"""
        result = parse_orders(html)
        self.assertEqual(len(result.orders), 1)
        self.assertTrue(result.orders[0].is_detail)


if __name__ == "__main__":
    unittest.main()
