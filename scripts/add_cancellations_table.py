import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "schedule.db")

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cancellations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            cancel_date TEXT NOT NULL,
            reason TEXT,
            is_restored BOOLEAN DEFAULT 0,
            restored_schedule_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (schedule_id) REFERENCES schedule(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cancellations_date ON cancellations(cancel_date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cancellations_schedule ON cancellations(schedule_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cancellations_restored ON cancellations(is_restored)")
    conn.commit()
    conn.close()
    print("OK: cancellations table added")

if __name__ == "__main__":
    migrate()
