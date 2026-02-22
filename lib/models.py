"""
Model attribution from Cursor's AI tracking database.

Cursor maintains a SQLite database at ~/.cursor/ai-tracking/ai-code-tracking.db
that logs which model was used for each code edit. We query this to attribute
a model name and code-edit count to each session.
"""

import os
import sqlite3

_DB_PATH = os.path.expanduser("~/.cursor/ai-tracking/ai-code-tracking.db")

_QUERY = """
    SELECT conversationId, model, COUNT(*) as edits
    FROM ai_code_hashes
    WHERE conversationId IS NOT NULL
    GROUP BY conversationId, model
    ORDER BY edits DESC
"""


def load_model_map(db_path=None):
    """Load model name and code-edit count per conversation from Cursor's DB.

    Queries the ai_code_hashes table, grouping by conversationId and model.
    For sessions that used multiple models, the model with the most edits wins.

    Args:
        db_path: Override path to the SQLite DB (for testing).
                 Defaults to ~/.cursor/ai-tracking/ai-code-tracking.db.

    Returns:
        Dict mapping session_id -> {"model": str, "edits": int}.
        Returns an empty dict if the DB doesn't exist or can't be read.
    """
    path = db_path or _DB_PATH
    if not os.path.exists(path):
        return {}

    result = {}
    try:
        with sqlite3.connect(path, timeout=2) as conn:
            for cid, model, edits in conn.execute(_QUERY).fetchall():
                if cid not in result:
                    result[cid] = {"model": model, "edits": edits}
                else:
                    result[cid]["edits"] += edits
    except Exception:
        pass
    return result
