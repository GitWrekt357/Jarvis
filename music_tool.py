import os
import sqlite3
import difflib
import subprocess
import time

INDEX_DB_PATH = os.path.expanduser("~/desktopjarvis/music_index.db")
VLC_LOG_PATH = os.path.expanduser("~/desktopjarvis/vlc_playback.log")


def ensure_alias_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alias TEXT UNIQUE NOT NULL COLLATE NOCASE,
            canonical_name TEXT NOT NULL,
            match_type TEXT NOT NULL
        )
    """)
    conn.commit()


def save_alias(conn, alias, canonical_name, match_type):
    conn.execute("""
        INSERT INTO aliases (alias, canonical_name, match_type)
        VALUES (?, ?, ?)
        ON CONFLICT(alias) DO UPDATE SET
            canonical_name=excluded.canonical_name, match_type=excluded.match_type
    """, (alias, canonical_name, match_type))
    conn.commit()


def resolve_query(conn, query: str):
    ql = query.strip().lower()

    row = conn.execute(
        "SELECT canonical_name, match_type FROM aliases WHERE alias = ? COLLATE NOCASE",
        (query,)
    ).fetchone()
    if row:
        return ("resolved", (row[1], row[0]))

    artists = [r[0] for r in conn.execute(
        "SELECT DISTINCT artist FROM tracks WHERE artist IS NOT NULL"
    ).fetchall()]
    albums = [r[0] for r in conn.execute(
        "SELECT DISTINCT album FROM tracks WHERE album IS NOT NULL"
    ).fetchall()]

    exact = [("artist", a) for a in artists if a.lower() == ql] + \
            [("album", a) for a in albums if a.lower() == ql]
    if len(exact) == 1:
        return ("resolved", exact[0])
    if len(exact) > 1:
        return ("confirm", exact)

    substring = [("artist", a) for a in artists if ql in a.lower() or a.lower() in ql] + \
                [("album", a) for a in albums if ql in a.lower() or a.lower() in ql]
    if substring:
        return ("confirm", substring)

    all_names = [("artist", a) for a in artists] + [("album", a) for a in albums]
    close_names = difflib.get_close_matches(query, [n for _, n in all_names], n=3, cutoff=0.6)
    fuzzy = [(t, n) for t, n in all_names if n in close_names]
    if fuzzy:
        return ("confirm", fuzzy)

    return ("none", None)


def shuffle_music(query: str, confirmed_name: str = None, confirmed_type: str = None) -> str:
    conn = sqlite3.connect(INDEX_DB_PATH)
    ensure_alias_table(conn)

    if confirmed_name and confirmed_type:
        kind, payload = resolve_query(conn, query)
        valid_candidates = []
        if kind == "resolved":
            valid_candidates = [payload]
        elif kind == "confirm":
            valid_candidates = payload

        if (confirmed_type, confirmed_name) not in valid_candidates:
            conn.close()
            return (
                f"Error: '{confirmed_name}' is not an actual candidate this tool found for "
                f"'{query}'. Refusing to play it. Ask the user to clarify what they meant, and "
                f"only confirm an option this tool has genuinely presented."
            )

        match_type, canonical_name = confirmed_type, confirmed_name
        save_alias(conn, query, canonical_name, match_type)
    else:
        kind, payload = resolve_query(conn, query)

        if kind == "none":
            conn.close()
            return f"I couldn't find anything in your library matching '{query}'."

        if kind == "confirm":
            candidates = payload
            if len(candidates) == 1:
                match_type, name = candidates[0]
                conn.close()
                return (
                    f"CONFIRMATION NEEDED: The closest match for '{query}' is the {match_type} "
                    f"'{name}'. Ask the user to confirm this is correct. If they confirm, call "
                    f"shuffle_music again with query='{query}', confirmed_name='{name}', "
                    f"confirmed_type='{match_type}'. If they say no, ask them to clarify."
                )
            else:
                options = "; ".join(f"{t}: {n}" for t, n in candidates)
                conn.close()
                return (
                    f"CONFIRMATION NEEDED: Multiple possible matches for '{query}': {options}. "
                    f"Ask the user which one they meant, then call shuffle_music again with "
                    f"query='{query}' and their chosen confirmed_name/confirmed_type."
                )

        match_type, canonical_name = payload

    if match_type == "artist":
        rows = conn.execute("SELECT filepath FROM tracks WHERE artist = ?", (canonical_name,)).fetchall()
    else:
        rows = conn.execute("SELECT filepath FROM tracks WHERE album = ?", (canonical_name,)).fetchall()
    conn.close()

    filepaths = [r[0] for r in rows]
    if not filepaths:
        return f"Found '{canonical_name}' but no indexed tracks are attached to it."

    subprocess.run(["pkill", "-x", "vlc"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)

    log_file = open(VLC_LOG_PATH, "w")
    subprocess.Popen(
        ["vlc", "--intf", "dummy", "--no-video", "--random"] + filepaths,
        stdout=log_file, stderr=log_file
    )

    return f"Now shuffling {len(filepaths)} track(s) from the {match_type} '{canonical_name}'."


def stop_music() -> str:
    result = subprocess.run(["pkill", "-x", "vlc"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode == 0:
        return "Stopped the music."
    return "No music appears to be playing right now."


music_tool_schema = {
    "name": "shuffle_music",
    "description": (
        "Shuffle-play music from the user's local library by artist or album name. "
        "Handles near-matches and shorthand (e.g. 'DOOM' for 'MF DOOM') by asking the "
        "user to confirm on first use, then remembering the match for next time."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The artist or album name the user asked for, as they said it.",
            },
            "confirmed_name": {
                "type": "string",
                "description": "Only set after the user has confirmed which artist/album they meant.",
            },
            "confirmed_type": {
                "type": "string",
                "enum": ["artist", "album"],
                "description": "Only set alongside confirmed_name, indicating which kind it is.",
            },
        },
        "required": ["query"],
    },
}

stop_music_schema = {
    "name": "stop_music",
    "description": "Stop any currently playing music.",
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}
