# Copyright (c) 2026 GitWrekt357
# Licensed under the GNU Affero General Public License v3.0
import os
import os
import sqlite3
import mutagen

MUSIC_LIBRARY_ROOT = os.path.expanduser("~/Music")

INDEX_DB_PATH = os.path.expanduser("~/desktopjarvis/music_index.db")

SUPPORTED_EXTENSIONS = {
    ".mp3", ".flac", ".ogg", ".oga", ".m4a", ".wav",
    ".opus", ".wma", ".aac", ".ape", ".wv",
}


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filepath TEXT UNIQUE NOT NULL,
            artist TEXT,
            album TEXT,
            title TEXT,
            track_number TEXT,
            folder_name TEXT,
            filename TEXT,
            mtime REAL,
            tags_complete INTEGER
        )
    """)
    conn.commit()


def get_tag(tags, key):
    if tags is None:
        return None
    value = tags.get(key)
    if value is None:
        return None
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else None
    return str(value)


def already_indexed_and_unchanged(conn, filepath, mtime):
    row = conn.execute(
        "SELECT mtime FROM tracks WHERE filepath = ?", (filepath,)
    ).fetchone()
    return row is not None and row[0] == mtime


def index_file(conn, filepath):
    mtime = os.path.getmtime(filepath)

    if already_indexed_and_unchanged(conn, filepath, mtime):
        return "skipped"

    folder_name = os.path.basename(os.path.dirname(filepath))
    filename = os.path.basename(filepath)

    artist = album = title = track_number = None
    try:
        audio = mutagen.File(filepath, easy=True)
        if audio is not None and audio.tags is not None:
            artist = get_tag(audio.tags, "artist")
            album = get_tag(audio.tags, "album")
            title = get_tag(audio.tags, "title")
            track_number = get_tag(audio.tags, "tracknumber")
    except Exception:
        pass

    tags_complete = 1 if (artist and album and title) else 0

    conn.execute("""
        INSERT INTO tracks (filepath, artist, album, title, track_number, folder_name, filename, mtime, tags_complete)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(filepath) DO UPDATE SET
            artist=excluded.artist, album=excluded.album, title=excluded.title,
            track_number=excluded.track_number, folder_name=excluded.folder_name,
            filename=excluded.filename, mtime=excluded.mtime, tags_complete=excluded.tags_complete
    """, (filepath, artist, album, title, track_number, folder_name, filename, mtime, tags_complete))

    return "complete" if tags_complete else "incomplete"


def main():
    if not os.path.isdir(MUSIC_LIBRARY_ROOT):
        print(f"Error: music library root '{MUSIC_LIBRARY_ROOT}' does not exist.")
        print("Edit MUSIC_LIBRARY_ROOT at the top of this script to your actual path.")
        return

    conn = sqlite3.connect(INDEX_DB_PATH)
    init_db(conn)

    counts = {"complete": 0, "incomplete": 0, "skipped": 0}
    incomplete_examples = []

    print(f"Scanning {MUSIC_LIBRARY_ROOT} ...")
    for root, dirs, files in os.walk(MUSIC_LIBRARY_ROOT):
        for filename in files:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue

            filepath = os.path.join(root, filename)
            result = index_file(conn, filepath)
            counts[result] += 1

            if result == "incomplete" and len(incomplete_examples) < 15:
                incomplete_examples.append(filepath)

    conn.commit()
    conn.close()

    total = counts["complete"] + counts["incomplete"] + counts["skipped"]
    print(f"\nDone. {total} audio files seen.")
    print(f"  Fully tagged (artist + album + title): {counts['complete']}")
    print(f"  Missing at least one tag: {counts['incomplete']}")
    print(f"  Unchanged since last index, skipped: {counts['skipped']}")

    if incomplete_examples:
        print(f"\nExamples of incompletely tagged files (up to 15 shown):")
        for path in incomplete_examples:
            print(f"  {path}")

    print(f"\nIndex saved to {INDEX_DB_PATH}")


if __name__ == "__main__":
    main()
