import requests
import gzip
import os

URL = "https://metabase.skit.ai/api/public/card/4e3ab1cc-2e49-4b94-ac39-07c7afa84210/query/json"

print("Fetching from Metabase...")
resp = requests.get(URL, timeout=300)
resp.raise_for_status()
data = resp.json()
print(f"Got {len(data)} rows")

numbers = set()

if len(data) > 0:
    first_row = data[0]
    caller_key = None
    for key in first_row.keys():
        if key.strip().lower() in ("caller_number", "caller number"):
            caller_key = key
            break

    for row in data:
        val = row.get(caller_key)
        if val is not None:
            if isinstance(val, float):
                val = int(val)
            s = str(val).strip()
            if s:
                numbers.add(s)

    print(f"Extracted {len(numbers)} unique numbers")
else:
    print("No rows returned — creating empty blocklist (likely start of month)")

# Always write the file, even if empty
with gzip.open("blocklist.txt.gz", "wt") as f:
    for num in sorted(numbers):
        f.write(num + "\n")

size_mb = os.path.getsize("blocklist.txt.gz") / (1024 * 1024)
print(f"Saved blocklist.txt.gz ({size_mb:.2f} MB, {len(numbers)} numbers)")
