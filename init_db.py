import sqlite3

DB_FILE = "msa_history.db"

def initialize_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            task_id TEXT NOT NULL UNIQUE,
            tool TEXT NOT NULL,
            input_file TEXT NOT NULL,
            output_file TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()
    print(f"Database {DB_FILE} initialized.")

initialize_db()

