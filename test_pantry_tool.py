"""Run with: python -m unittest test_pantry_tool -v   (uses a throwaway database)"""
import os
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest import mock

import pantry_tool as p


class PantryBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "pantry.db")
        patcher = mock.patch.object(p, "DB_PATH", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def row(self, name):
        conn = p._connect()
        try:
            return dict(conn.execute("SELECT * FROM items WHERE name = ?", (name,)).fetchone())
        finally:
            conn.close()


class PantryToolTests(PantryBase):
    """Original behaviour that must keep working."""

    def test_add_and_merge(self):
        p.pantry_add(name="Eggs", quantity=12)
        out = p.pantry_add(name="eggs", quantity=6)
        self.assertIn("18", out)
        self.assertIn("18 count of Eggs", p.pantry_check("egg"))

    def test_unit_normalization(self):
        p.pantry_add(name="flour", quantity=2, unit="Cups")
        self.assertIn("2 cup of flour", p.pantry_check("flour"))

    def test_weight_added_to_volume_item_asks_once(self):
        p.pantry_add(name="flour", quantity=2, unit="cups")
        out = p.pantry_add(name="flour", quantity=100, unit="g")
        self.assertIn("pantry_set_conversion", out)
        self.assertIn("2 cup of flour", p.pantry_check("flour"))  # nothing was added

    def test_use_and_out(self):
        p.pantry_add(name="milk", quantity=2, unit="l")
        self.assertIn("1 l of milk left", p.pantry_use("milk", 1))
        self.assertIn("out of milk", p.pantry_use("milk"))
        self.assertIn("no milk", p.pantry_check("milk"))

    def test_overuse_floors_at_zero(self):
        p.pantry_add(name="rice", quantity=1, unit="lb")
        out = p.pantry_use("rice", 5)
        self.assertIn("out of rice", out)
        self.assertIn("only had 1", out)

    def test_ambiguous_match(self):
        p.pantry_add(name="brown sugar", quantity=1, unit="lb")
        p.pantry_add(name="white sugar", quantity=1, unit="lb")
        self.assertIn("several items", p.pantry_use("sugar", 1))

    def test_expiring(self):
        soon = (date.today() + timedelta(days=1)).isoformat()
        past = (date.today() - timedelta(days=2)).isoformat()
        later = (date.today() + timedelta(days=30)).isoformat()
        p.pantry_add(name="yogurt", quantity=1, expires=soon)
        p.pantry_add(name="spinach", quantity=1, expires=past)
        p.pantry_add(name="rice", quantity=1, expires=later)
        out = p.pantry_expiring(3)
        self.assertIn("yogurt", out)
        self.assertIn("spinach already expired", out)
        self.assertNotIn("rice", out)

    def test_bad_date_rejected(self):
        self.assertIn("YYYY-MM-DD", p.pantry_add(name="x", expires="next friday"))

    def test_shopping_list(self):
        p.pantry_add(name="coffee", quantity=1, unit="lb", low_threshold=1)
        p.pantry_add(name="salt", quantity=5, unit="oz", low_threshold=1)
        out = p.pantry_shopping_list()
        self.assertIn("coffee", out)
        self.assertNotIn("salt", out)

    def test_unknown_barcode(self):
        with mock.patch.object(p, "lookup_barcode", return_value=None):
            self.assertIn("could not identify", p.pantry_add(barcode="999"))

    def test_dispatcher(self):
        self.assertIn("Added", p.run_pantry_tool("pantry_add", {"name": "oats", "quantity": 1}))
        self.assertIn("bad arguments", p.run_pantry_tool("pantry_check", {"wrong": 1}))
        self.assertEqual({s["name"] for s in p.pantry_tool_schemas}, set(p._DISPATCH))
        self.assertIn("pantry_set", p.PANTRY_TOOL_NAMES)
        self.assertIn("pantry_set_conversion", p.PANTRY_TOOL_NAMES)

    def test_list_caps_length(self):
        for i in range(30):
            p.pantry_add(name=f"item{i:02d}", quantity=1)
        out = p.pantry_list()
        self.assertIn("30 items", out)
        self.assertIn("5 more items", out)


class ParsePackageTests(unittest.TestCase):
    def check(self, text, dim, grams_or_ml, unit):
        got = p.parse_package(text)
        self.assertIsNotNone(got, text)
        self.assertEqual(got["dimension"], dim, text)
        self.assertAlmostEqual(got["amount"], grams_or_ml, delta=0.01, msg=text)
        self.assertEqual(got["unit"], unit, text)

    def test_common_label_formats(self):
        self.check("10 oz", "mass", 283.495, "oz")
        self.check("8 OZ", "mass", 226.796, "oz")
        self.check("16 ounces", "mass", 453.592, "oz")
        self.check("1 lb (454 g)", "mass", 453.592, "lb")
        self.check("2 lbs", "mass", 907.185, "lb")
        self.check("400g", "mass", 400, "g")
        self.check("Net wt 10 oz", "mass", 283.495, "oz")
        self.check("10 oz. (283g)", "mass", 283.495, "oz")
        self.check("12 fl oz (355 ml)", "volume", 354.882, "fl oz")
        self.check("32 fl. oz", "volume", 946.353, "fl oz")
        self.check("1,5 L", "volume", 1500, "l")
        self.check("1 gallon", "volume", 3785.41, "gallon")
        self.check("1 lb", "mass", 453.592, "lb")  # lb must not be read as l

    def test_multipack(self):
        self.check("2 x 400 g", "mass", 800, "g")
        got = p.parse_package("6 x 12 fl oz")
        self.assertAlmostEqual(got["amount"], 6 * 12 * 29.5735295625, places=3)
        self.assertEqual(got["label"], "6 x 12 fl oz")

    def test_counts(self):
        for text in ("12", "12 ct", "12 eggs", "12 count"):
            got = p.parse_package(text)
            self.assertEqual((got["dimension"], got["amount"]), ("count", 12), text)

    def test_unusable_text(self):
        for text in ("", None, "assorted", "large", "1 bag", "0 oz", "family size"):
            self.assertIsNone(p.parse_package(text), repr(text))


class BarcodeAndPackageTests(PantryBase):
    PB = {"name": "Peanut Butter", "brand": "Acme", "package": "16 oz"}

    def test_scan_adds_one_package_with_real_size(self):
        with mock.patch.object(p, "lookup_barcode", return_value=self.PB) as m:
            out = p.pantry_add(barcode="0123456789012")
            self.assertIn("Peanut Butter", out)
            self.assertIn("1 package (16 oz)", out)
            m.assert_called_once()
        self.assertIn("16 oz of Peanut Butter, about 1 package", p.pantry_check("peanut"))
        row = self.row("Peanut Butter")
        self.assertAlmostEqual(row["quantity"], 453.59237, places=3)  # stored in grams
        self.assertEqual(row["dimension"], "mass")

    def test_second_scan_needs_no_network_and_totals(self):
        with mock.patch.object(p, "lookup_barcode", return_value=self.PB):
            p.pantry_add(barcode="0123456789012")
        with mock.patch.object(p, "lookup_barcode") as m:
            out = p.pantry_add(barcode="0123456789012")
            m.assert_not_called()
        self.assertIn("32 oz", out)
        self.assertIn("about 2 packages", out)

    def test_use_part_of_a_package(self):
        p.pantry_add(name="cheddar", quantity=1, unit="block", package_size="8 oz")
        self.assertIn("8 oz of cheddar", p.pantry_check("cheddar"))
        out = p.pantry_use("cheddar", 3, "oz")
        self.assertIn("5 oz of cheddar left", out)
        self.assertIn("block", out)
        # grams convert too: 3 oz is about 85 g
        out = p.pantry_use("cheddar", 85, "g")
        self.assertIn("2 oz", out)

    def test_unsized_scan_then_size_taught_once(self):
        unsized = {"name": "Mystery Chips", "brand": "", "package": ""}
        with mock.patch.object(p, "lookup_barcode", return_value=unsized):
            out = p.pantry_add(barcode="555")
        self.assertIn("do not know how much one holds", out)
        self.assertIn("1 package of Mystery Chips", p.pantry_check("chips"))
        out = p.pantry_set("chips", package_size="10 oz")
        self.assertIn("10 oz", out)
        self.assertIn("treated the 1 you had as 1 package", out)
        self.assertIn("about 1 package", p.pantry_check("chips"))

    def test_tortilla_strips_scenario(self):
        """The real case: 1.5 bags left, a recipe wants a cup."""
        legacy = sqlite3.connect(self.db)
        legacy.executescript(OLD_SCHEMA)
        legacy.execute(
            "INSERT INTO items (name, quantity, unit, barcode, added_at, updated_at) "
            "VALUES ('Tricolor Tortilla Strips', 1, 'count', '0123', 'x', 'x')")
        legacy.commit()
        legacy.close()
        strips = {"name": "Tricolor Tortilla Strips", "brand": "", "package": "10 oz (283 g)"}
        with mock.patch.object(p, "lookup_barcode", return_value=strips) as m:
            out = p.pantry_set("tortilla strips", quantity=1.5, unit="bags")
            m.assert_called_once()  # package size was filled in from the saved barcode
        self.assertIn("15 oz", out)
        self.assertIn("about 1.5 bags", out)
        # A cup is volume, strips are weight: ask once.
        ask = p.pantry_use("tortilla strips", 1, "cup")
        self.assertIn("pantry_set_conversion", ask)
        self.assertIn("15 oz", p.pantry_check("tortilla strips"))  # untouched
        self.assertIn("remember", p.pantry_set_conversion(
            "tortilla strips", 1, "cup", 1.5, "oz"))
        out = p.pantry_use("tortilla strips", 1, "cup")
        self.assertIn("13.5 oz", out)
        # Never asked again, and the other direction works too.
        out = p.pantry_use("tortilla strips", 0.5, "cup")
        self.assertIn("12.75 oz", out)

    def test_carton_of_eggs(self):
        p.pantry_add(name="eggs", quantity=12)
        out = p.pantry_add(name="eggs", quantity=2, unit="cartons", package_size="12 count")
        self.assertIn("36 count", out)

    def test_oz_of_a_liquid_means_fluid_ounces(self):
        p.pantry_add(name="milk", quantity=1, unit="l")
        out = p.pantry_use("milk", 8, "oz")
        self.assertIn("0.76 l of milk left", out)

    def test_count_item_rejects_measured_use(self):
        p.pantry_add(name="eggs", quantity=12)
        self.assertIn("counted", p.pantry_use("eggs", 3, "oz"))
        self.assertIn("12 count", p.pantry_check("eggs"))

    def test_measured_item_rejects_count_use(self):
        p.pantry_add(name="flour", quantity=5, unit="lb")
        self.assertIn("weight", p.pantry_use("flour", 2, "count"))

    def test_package_use_without_size_explains(self):
        p.pantry_add(name="flour", quantity=5, unit="lb")
        self.assertIn("package_size", p.pantry_use("flour", 1, "bag"))

    def test_low_threshold_in_packages(self):
        with mock.patch.object(p, "lookup_barcode",
                               return_value={"name": "Coffee", "brand": "", "package": "12 oz"}):
            p.pantry_add(barcode="777", low_threshold=1, low_threshold_unit="bag")
        self.assertIn("Coffee", p.pantry_shopping_list())
        with mock.patch.object(p, "lookup_barcode"):
            p.pantry_add(barcode="777")  # now 2 bags
        self.assertIn("Nothing is running low", p.pantry_shopping_list())

    def test_exact_use_ends_at_zero_not_float_dust(self):
        p.pantry_add(name="oil", quantity=1, unit="cup")
        self.assertIn("out of oil", p.pantry_use("oil", 16, "tbsp"))
        self.assertIn("no oil", p.pantry_check("oil"))

    def test_set_validation(self):
        p.pantry_add(name="rice", quantity=1, unit="lb")
        self.assertIn("new amount", p.pantry_set("rice"))
        self.assertIn("could not read", p.pantry_set("rice", package_size="big"))
        self.assertIn("cannot be negative", p.pantry_set("rice", quantity=-1))
        self.assertIn("do not have", p.pantry_set("nothing", quantity=1))
        self.assertIn("rice is now 2 lb", p.pantry_set("rice", quantity=2, unit="lb"))

    def test_conversion_validation(self):
        p.pantry_add(name="rice", quantity=1, unit="lb")
        self.assertIn("one weight and one volume",
                      p.pantry_set_conversion("rice", 1, "oz", 28, "g"))
        self.assertIn("one weight and one volume",
                      p.pantry_set_conversion("rice", 1, "cup", 1, "bag"))
        self.assertIn("do not have", p.pantry_set_conversion("nope", 1, "cup", 4, "oz"))
        self.assertIn("numbers", p.pantry_set_conversion("rice", "a", "cup", 4, "oz"))


class LookupBarcodeTests(unittest.TestCase):
    def fake_get(self, payload):
        calls = []

        def get(url, params=None, headers=None, timeout=None):
            calls.append(params)
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
        return SimpleNamespace(get=get), calls

    def test_requests_package_fields(self):
        fake, calls = self.fake_get({"status": 1, "product": {
            "product_name": "Cheddar", "brands": "Acme, Other", "quantity": "8 oz"}})
        with mock.patch.object(p, "requests", fake):
            got = p.lookup_barcode("0123")
        self.assertEqual(got, {"name": "Cheddar", "brand": "Acme", "package": "8 oz"})
        self.assertIn("product_quantity", calls[0]["fields"])

    def test_falls_back_to_numeric_size(self):
        fake, _ = self.fake_get({"status": 1, "product": {
            "product_name": "Chips", "quantity": "1 bag",
            "product_quantity": "283", "product_quantity_unit": "g"}})
        with mock.patch.object(p, "requests", fake):
            self.assertEqual(p.lookup_barcode("1")["package"], "283 g")

    def test_not_found_and_network_failure(self):
        fake, _ = self.fake_get({"status": 0})
        with mock.patch.object(p, "requests", fake):
            self.assertIsNone(p.lookup_barcode("1"))

        def boom(*a, **k):
            raise OSError("offline")
        with mock.patch.object(p, "requests", SimpleNamespace(get=boom)):
            self.assertIsNone(p.lookup_barcode("1"))


OLD_SCHEMA = """
CREATE TABLE items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    quantity      REAL NOT NULL DEFAULT 0,
    unit          TEXT NOT NULL DEFAULT 'count',
    location      TEXT,
    expires       TEXT,
    barcode       TEXT,
    low_threshold REAL,
    added_at      TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
"""


class MigrationTests(PantryBase):
    def make_old_db(self):
        conn = sqlite3.connect(self.db)
        conn.executescript(OLD_SCHEMA)
        rows = [
            ("flour", 2, "cup", None), ("rice", 1, "lb", 1), ("eggs", 12, "count", None),
            ("salsa", 2, "jars", None), ("thyme", 3, "sprigs", None),
        ]
        for name, qty, unit, thr in rows:
            conn.execute(
                "INSERT INTO items (name, quantity, unit, low_threshold, added_at, updated_at) "
                "VALUES (?,?,?,?,'x','x')", (name, qty, unit, thr))
        conn.commit()
        conn.close()

    def test_old_database_upgrades_without_losing_amounts(self):
        self.make_old_db()
        self.assertIn("2 cup of flour", p.pantry_check("flour"))
        self.assertIn("1 lb of rice", p.pantry_check("rice"))
        self.assertIn("12 count of eggs", p.pantry_check("eggs"))
        self.assertIn("2 jars of salsa", p.pantry_check("salsa"))
        self.assertIn("3 sprigs of thyme", p.pantry_check("thyme"))
        self.assertAlmostEqual(self.row("flour")["quantity"], 2 * 236.5882365, places=3)
        self.assertEqual(self.row("flour")["dimension"], "volume")
        self.assertAlmostEqual(self.row("rice")["low_threshold"], 453.59237, places=3)
        self.assertIn("rice", p.pantry_shopping_list())  # 1 lb is at its 1 lb threshold

    def test_migration_is_idempotent(self):
        self.make_old_db()
        first = self.row("rice")
        for _ in range(3):
            p._connect().close()
        self.assertEqual(self.row("rice"), first)

    def test_old_rows_work_with_new_tools(self):
        self.make_old_db()
        self.assertIn("1 cup of flour left", p.pantry_use("flour", 1, "cup"))
        self.assertIn("pantry_set_conversion", p.pantry_use("flour", 100, "g"))
        self.assertIn("14 count", p.pantry_add(name="eggs", quantity=2))


if __name__ == "__main__":
    unittest.main()
