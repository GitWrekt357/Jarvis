"""
Pantry tool for Jarvis (and, via server.py, Friday).

Follows the same shape as calendar_tool.py / memory_tool.py: plain functions,
a list of Claude tool schemas, and one dispatcher that brain.py calls.

Storage is a single local SQLite file. Every tool returns a short plain string,
because the reply is read aloud (no dashes as punctuation, no long lists).

Barcode flow (for Friday later): the phone scans a code and sends it to the hub,
which calls pantry_add(barcode=...). If no name is given, the name is looked up
on Open Food Facts (free, no API key).
"""
import os
import re
import sqlite3
from datetime import datetime, date, timedelta

try:
    import requests
except ImportError:  # barcode lookup degrades gracefully if requests is missing
    requests = None

DB_PATH = os.environ.get(
    "PANTRY_DB_PATH", os.path.expanduser("~/desktopjarvis/pantry.db")
)

OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
OFF_TIMEOUT = 8
OFF_HEADERS = {"User-Agent": "Jarvis-Pantry/1.0 (personal household use)"}

MAX_LIST_ITEMS = 25  # keep spoken answers short

_UNIT_ALIASES = {
    "lbs": "lb", "pound": "lb", "pounds": "lb",
    "cups": "cup",
    "gram": "g", "grams": "g",
    "ounce": "oz", "ounces": "oz",
    "tablespoon": "tbsp", "tablespoons": "tbsp",
    "teaspoon": "tsp", "teaspoons": "tsp",
    "milliliter": "ml", "milliliters": "ml",
    "liter": "l", "liters": "l",
    "piece": "count", "pieces": "count", "item": "count", "items": "count",
    "each": "count", "unit": "count", "units": "count",
}


# ---------- storage ----------

def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
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
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_barcode ON items(barcode)")
    return conn


def _norm_unit(unit):
    u = (unit or "count").strip().lower()
    return _UNIT_ALIASES.get(u, u)


def _fmt_qty(q):
    return str(int(q)) if float(q).is_integer() else f"{q:g}"


def _parse_date(text):
    """Accept YYYY-MM-DD only; Claude converts spoken dates before calling."""
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise ValueError("Dates must be in YYYY-MM-DD format.")


def _find(conn, name):
    """Exact (case-insensitive) match first, then a unique substring match."""
    row = conn.execute("SELECT * FROM items WHERE name = ?", (name.strip(),)).fetchone()
    if row:
        return [row]
    like = f"%{name.strip()}%"
    return conn.execute(
        "SELECT * FROM items WHERE name LIKE ? ORDER BY name", (like,)
    ).fetchall()


# ---------- barcode lookup ----------

def lookup_barcode(barcode):
    """Return {'name', 'brand', 'package'} from Open Food Facts, or None."""
    barcode = re.sub(r"\D", "", barcode or "")
    if not barcode or requests is None:
        return None
    try:
        resp = requests.get(
            OFF_URL.format(barcode=barcode),
            params={"fields": "product_name,generic_name,brands,quantity"},
            headers=OFF_HEADERS,
            timeout=OFF_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None
    if data.get("status") != 1:
        return None
    product = data.get("product", {})
    name = (product.get("product_name") or product.get("generic_name") or "").strip()
    if not name:
        return None
    brand = (product.get("brands") or "").split(",")[0].strip()
    return {"name": name, "brand": brand, "package": product.get("quantity", "")}


# ---------- tools ----------

def pantry_add(name=None, quantity=1, unit="count", expires=None,
               location=None, barcode=None, low_threshold=None):
    barcode = re.sub(r"\D", "", barcode) if barcode else None
    conn = _connect()
    try:
        if barcode and not name:
            # Same barcode seen before? Reuse that item. Otherwise ask Open Food Facts.
            known = conn.execute(
                "SELECT * FROM items WHERE barcode = ?", (barcode,)
            ).fetchone()
            if known:
                name = known["name"]
            else:
                found = lookup_barcode(barcode)
                if not found:
                    return (f"I could not identify barcode {barcode}. "
                            "Tell me what the item is and I will add it.")
                name = found["name"]
        if not name:
            return "I need an item name or a barcode to add something."
        try:
            quantity = float(quantity)
            expires = _parse_date(expires)
        except (TypeError, ValueError) as e:
            return str(e) if "Dates" in str(e) else "The quantity needs to be a number."
        if quantity <= 0:
            return "The quantity has to be more than zero."
        unit = _norm_unit(unit)
        now = datetime.now().isoformat(timespec="seconds")

        row = conn.execute("SELECT * FROM items WHERE name = ?", (name.strip(),)).fetchone()
        if row:
            if row["quantity"] > 0 and row["unit"] != unit:
                return (f"{row['name']} is tracked in {row['unit']}, but you gave {unit}. "
                        f"Please use {row['unit']}, or tell me to reset that item.")
            new_qty = (row["quantity"] if row["unit"] == unit else 0) + quantity
            conn.execute(
                """UPDATE items SET quantity=?, unit=?,
                       expires=COALESCE(?, expires), location=COALESCE(?, location),
                       barcode=COALESCE(?, barcode),
                       low_threshold=COALESCE(?, low_threshold), updated_at=?
                   WHERE id=?""",
                (new_qty, unit, expires, location, barcode, low_threshold, now, row["id"]),
            )
            conn.commit()
            return f"Added {_fmt_qty(quantity)} {unit} of {row['name']}. You now have {_fmt_qty(new_qty)} {unit}."
        conn.execute(
            """INSERT INTO items (name, quantity, unit, location, expires, barcode,
                                  low_threshold, added_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (name.strip(), quantity, unit, location, expires, barcode, low_threshold, now, now),
        )
        conn.commit()
        return f"Added {_fmt_qty(quantity)} {unit} of {name.strip()} to the pantry."
    finally:
        conn.close()


def pantry_use(name, quantity=None):
    """Use up some of an item. No quantity means it is all gone."""
    conn = _connect()
    try:
        rows = _find(conn, name)
        if not rows:
            return f"I do not have {name} in the pantry."
        if len(rows) > 1:
            names = ", ".join(r["name"] for r in rows[:5])
            return f"That matches several items: {names}. Which one do you mean?"
        row = rows[0]
        now = datetime.now().isoformat(timespec="seconds")
        if quantity is None:
            new_qty = 0.0
        else:
            try:
                quantity = float(quantity)
            except (TypeError, ValueError):
                return "The quantity needs to be a number."
            if quantity <= 0:
                return "The quantity has to be more than zero."
            new_qty = max(0.0, row["quantity"] - quantity)
        conn.execute(
            "UPDATE items SET quantity=?, updated_at=? WHERE id=?", (new_qty, now, row["id"])
        )
        conn.commit()
        if new_qty == 0:
            note = "" if quantity is None or quantity <= row["quantity"] else (
                f" You only had {_fmt_qty(row['quantity'])} {row['unit']}.")
            return f"You are now out of {row['name']}.{note}"
        return f"You have {_fmt_qty(new_qty)} {row['unit']} of {row['name']} left."
    finally:
        conn.close()


def pantry_check(name):
    conn = _connect()
    try:
        rows = [r for r in _find(conn, name) if r["quantity"] > 0]
        if not rows:
            return f"You have no {name} in the pantry."
        parts = []
        for r in rows[:5]:
            part = f"{_fmt_qty(r['quantity'])} {r['unit']} of {r['name']}"
            if r["expires"]:
                part += f", expiring {r['expires']}"
            parts.append(part)
        return "You have " + "; ".join(parts) + "."
    finally:
        conn.close()


def pantry_list(location=None):
    conn = _connect()
    try:
        sql = "SELECT * FROM items WHERE quantity > 0"
        params = []
        if location:
            sql += " AND location LIKE ?"
            params.append(f"%{location}%")
        rows = conn.execute(sql + " ORDER BY name", params).fetchall()
        if not rows:
            return "The pantry is empty." if not location else f"Nothing is stored in {location}."
        shown = rows[:MAX_LIST_ITEMS]
        text = ", ".join(f"{r['name']} {_fmt_qty(r['quantity'])} {r['unit']}" for r in shown)
        extra = len(rows) - len(shown)
        tail = f", and {extra} more items" if extra > 0 else ""
        return f"{len(rows)} items: {text}{tail}."
    finally:
        conn.close()


def pantry_expiring(days=3):
    conn = _connect()
    try:
        try:
            days = int(days)
        except (TypeError, ValueError):
            days = 3
        cutoff = (date.today() + timedelta(days=days)).isoformat()
        rows = conn.execute(
            """SELECT * FROM items WHERE quantity > 0 AND expires IS NOT NULL
               AND expires <= ? ORDER BY expires""",
            (cutoff,),
        ).fetchall()
        if not rows:
            return f"Nothing in the pantry expires in the next {days} days."
        today = date.today().isoformat()
        parts = []
        for r in rows[:MAX_LIST_ITEMS]:
            when = "already expired" if r["expires"] < today else f"expires {r['expires']}"
            parts.append(f"{r['name']} {when}")
        return "; ".join(parts) + "."
    finally:
        conn.close()


def pantry_shopping_list():
    """Items that are out, or at or below their low threshold."""
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT * FROM items WHERE low_threshold IS NOT NULL
               AND quantity <= low_threshold ORDER BY name"""
        ).fetchall()
        if not rows:
            return ("Nothing is running low. Set a low threshold on items you "
                    "want me to watch.")
        parts = []
        for r in rows[:MAX_LIST_ITEMS]:
            state = "out" if r["quantity"] == 0 else f"{_fmt_qty(r['quantity'])} {r['unit']} left"
            parts.append(f"{r['name']} ({state})")
        return "Running low: " + ", ".join(parts) + "."
    finally:
        conn.close()


# ---------- schemas + dispatcher (what brain.py imports) ----------

pantry_tool_schemas = [
    {
        "name": "pantry_add",
        "description": (
            "Add food to the household pantry. Provide a name, or a barcode to "
            "identify the product automatically. Adds to the existing amount if "
            "the item is already tracked."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Item name, e.g. 'eggs'."},
                "quantity": {"type": "number", "description": "Amount to add. Default 1."},
                "unit": {"type": "string",
                         "description": "Unit such as count, cup, g, oz, lb, ml. Default count."},
                "expires": {"type": "string",
                            "description": "Expiration date in YYYY-MM-DD format, if known."},
                "location": {"type": "string",
                             "description": "Where it is stored: pantry, fridge, or freezer."},
                "barcode": {"type": "string", "description": "UPC or EAN barcode digits."},
                "low_threshold": {"type": "number",
                                  "description": "Warn and add to the shopping list at or below this amount."},
            },
        },
    },
    {
        "name": "pantry_use",
        "description": (
            "Record using up some of a pantry item. Omit quantity if it is all gone."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "quantity": {"type": "number", "description": "Amount used, in the item's unit."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "pantry_check",
        "description": "Check how much of an item is in the pantry.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "pantry_list",
        "description": "List what is in the pantry, optionally for one storage location.",
        "input_schema": {
            "type": "object",
            "properties": {"location": {"type": "string"}},
        },
    },
    {
        "name": "pantry_expiring",
        "description": "List pantry items that are expired or expire soon.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Look ahead this many days. Default 3."}
            },
        },
    },
    {
        "name": "pantry_shopping_list",
        "description": "List items that are out or running low and should be bought.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

PANTRY_TOOL_NAMES = {s["name"] for s in pantry_tool_schemas}

_DISPATCH = {
    "pantry_add": pantry_add,
    "pantry_use": pantry_use,
    "pantry_check": pantry_check,
    "pantry_list": pantry_list,
    "pantry_expiring": pantry_expiring,
    "pantry_shopping_list": pantry_shopping_list,
}


def run_pantry_tool(name, args):
    try:
        return _DISPATCH[name](**args)
    except TypeError as e:
        return f"I could not run {name}: bad arguments ({e})."
    except sqlite3.Error as e:
        return f"The pantry database had a problem: {e}"


if __name__ == "__main__":
    print(pantry_list())
