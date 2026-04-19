import requests
import sqlite3
import os

URL = "https://metabase.skit.ai/api/public/card/4e3ab1cc-2e49-4b94-ac39-07c7afa84210/query/json"
DB_PATH = "blocklist.db"

print("Fetching from Metabase...")
resp = requests.get(URL, timeout=300)
resp.raise_for_status()
data = resp.json()
print(f"Got {len(data)} rows")

first_row = data[0]
caller_key = None
for key in first_row.keys():
    if key.strip().lower() in ("caller_number", "caller number"):
        caller_key = key
        break

numbers = set()
for row in data:
    val = row.get(caller_key)
    if val is not None:
        if isinstance(val, float):
            val = int(val)
        s = str(val).strip()
        if s:
            numbers.add(s)

print(f"Extracted {len(numbers)} unique numbers")

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute("CREATE TABLE blocklist (caller_number TEXT PRIMARY KEY)")
c.executemany("INSERT INTO blocklist VALUES (?)", [(n,) for n in numbers])
conn.commit()
count = c.execute("SELECT COUNT(*) FROM blocklist").fetchone()[0]
conn.close()

size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
print(f"Saved blocklist.db ({size_mb:.1f} MB, {count} numbers)")
