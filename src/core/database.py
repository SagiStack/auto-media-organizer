import sqlite3
import uuid
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional

class HistoryManager:
    """
    Manages the persistent history of file operations for the Undo system.
    """
    def __init__(self, db_path: str = "organizer_history.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                # Move History
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT,
                        original_path TEXT,
                        new_path TEXT,
                        timestamp TEXT
                    )
                """)
                # File Catalog (for Gallery and Duplicates)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS files (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        file_hash TEXT,
                        file_path TEXT UNIQUE,
                        category TEXT,
                        subcategory TEXT,
                        size INTEGER,
                        timestamp TEXT
                    )
                """)
                conn.commit()

    def log_move(self, session_id: str, original_path: str, new_path: str):
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO history (session_id, original_path, new_path, timestamp) VALUES (?, ?, ?, ?)",
                    (session_id, str(original_path), str(new_path), datetime.now().isoformat())
                )
                conn.commit()

    def log_file(self, file_hash: str, file_path: str, category: str, subcategory: str, size: int):
        """Adds or updates a file in the catalog."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO files (file_hash, file_path, category, subcategory, size, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (file_hash, str(file_path), category, subcategory, size, datetime.now().isoformat()))
                conn.commit()

    def get_library(self, category: Optional[str] = None) -> List[dict]:
        """Fetches files for the gallery, filtered by category."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM files"
            params = []
            if category:
                query += " WHERE category = ?"
                params.append(category)
            query += " ORDER BY timestamp DESC"
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_duplicates(self) -> List[dict]:
        """Identifies groups of files with the same hash."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            # Find hashes that appear more than once
            cursor = conn.execute("""
                SELECT file_hash, COUNT(*) as count 
                FROM files 
                GROUP BY file_hash 
                HAVING count > 1
            """)
            duplicate_hashes = [row['file_hash'] for row in cursor.fetchall()]
            
            results = []
            for h in duplicate_hashes:
                cursor = conn.execute("SELECT * FROM files WHERE file_hash = ?", (h,))
                results.append({
                    "hash": h,
                    "files": [dict(row) for row in cursor.fetchall()]
                })
            return results

    def remove_file(self, file_path: str):
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM files WHERE file_path = ?", (str(file_path),))
                conn.commit()

    def get_last_session(self) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT session_id FROM history ORDER BY id DESC LIMIT 1")
            result = cursor.fetchone()
            return result[0] if result else None

    def get_session_moves(self, session_id: str) -> List[Tuple[str, str]]:
        """Returns moves in LIFO order (last move first) for undoing."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT original_path, new_path FROM history WHERE session_id = ? ORDER BY id DESC",
                (session_id,)
            )
            return cursor.fetchall()

    def clear_session(self, session_id: str):
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM history WHERE session_id = ?", (session_id,))
                conn.commit()

    @staticmethod
    def generate_session_id() -> str:
        return str(uuid.uuid4())
