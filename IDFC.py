import streamlit as st
import pandas as pd
import sqlite3
import shutil
import os
import gc
from io import BytesIO
from datetime import datetime

REPO_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blocklist.db")
WORK_DB_PATH = "/tmp/blocklist.db"

st.set_page_config(page_title="Placement File Filter", page_icon="🔍", layout="centered")

st.markdown("""
<style>
    .metric-card {
        background: #f8f9fa; border-radius: 12px; padding: 20px;
        text-align: center; border: 1px solid #e9ecef;
    }
    .metric-value { font-size: 2rem; font-weight: 700; }
    .metric-label { font-size: 0.85rem; color: #888; margin-top: 4px; }
</style>
""", unsafe_allow_html=True)


def get_db():
    if not os.path.exists(REPO_DB_PATH):
        return None
    if not os.path.exists(WORK_DB_PATH) or os.path.getmtime(REPO_DB_PATH) > os.path.getmtime(WORK_DB_PATH):
        shutil.copy2(REPO_DB_PATH, WORK_DB_PATH)
    return WORK_DB_PATH


def get_count():
    db = get_db()
    if not db:
        return 0
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM blocklist").fetchone()[0]
    conn.close()
    return count


def check_blocked(numbers_list):
    db = get_db()
    if not db:
        return set()
    conn = sqlite3.connect(db)
    blocked = set()
    batch_size = 500
    for i in range(0, len(numbers_list), batch_size):
        batch = numbers_list[i:i + batch_size]
        placeholders = ",".join(["?"] * len(batch))
        rows = conn.execute(
            f"SELECT caller_number FROM blocklist WHERE caller_number IN ({placeholders})",
            batch
        ).fetchall()
        blocked.update(row[0] for row in rows)
    conn.close()
    return blocked


st.title("🔍 Placement File Filter")
st.caption("Upload placement file → Remove 8+ attempt numbers → Download clean file")
st.divider()

db = get_db()
if not db:
    st.error("❌ blocklist.db not found. Waiting for GitHub Actions to generate it.")
    st.stop()

count = get_count()
st.success(f"✅ Blocklist active — **{count:,}** numbers with 8+ attempts")

st.divider()
st.subheader("📁 Upload Placement File")
uploaded_file = st.file_uploader(
    "Drop your CSV or Excel file here",
    type=["csv", "xlsx", "xls"],
    help="File must contain a 'caller_number' column",
    key="placement_upload"
)

if uploaded_file:
    file_ext = uploaded_file.name.split(".")[-1].lower()
    try:
        df = pd.read_csv(uploaded_file) if file_ext == "csv" else pd.read_excel(uploaded_file)
    except Exception as e:
        st.error(f"❌ Could not read file: {e}")
        st.stop()

    df.columns = [c.strip() for c in df.columns]
    if "caller_number" not in df.columns:
        st.error(f"❌ 'caller_number' not found. Your file has: {', '.join(df.columns)}")
        st.stop()

    with st.spinner("⏳ Filtering placement file..."):
        df["_clean"] = df["caller_number"].apply(
            lambda x: str(int(x)) if isinstance(x, float) and pd.notna(x) and x == int(x)
            else (str(x).strip() if pd.notna(x) else "")
        )

        blocked = check_blocked(df["_clean"].tolist())
        total = len(df)
        cleaned = df[~df["_clean"].isin(blocked)].drop(columns=["_clean"]).copy()
        dropped = total - len(cleaned)

    del df
    gc.collect()

    st.divider()
    st.subheader("📊 Results")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"""<div class="metric-card">
            <div class="metric-value" style="color: #495057;">{total:,}</div>
            <div class="metric-label">Total Rows</div>
        </div>""", unsafe_allow_html=True)
    with col2:
        st.markdown(f"""<div class="metric-card">
            <div class="metric-value" style="color: #28a745;">{len(cleaned):,}</div>
            <div class="metric-label">Kept ✓</div>
        </div>""", unsafe_allow_html=True)
    with col3:
        st.markdown(f"""<div class="metric-card">
            <div class="metric-value" style="color: #dc3545;">{dropped:,}</div>
            <div class="metric-label">Dropped (8+ attempts)</div>
        </div>""", unsafe_allow_html=True)

    if dropped > 0:
        st.markdown("")
        st.error(f"🚫 {dropped:,} numbers removed — they already have 8+ attempts this month.")

    st.markdown("")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = uploaded_file.name.rsplit(".", 1)[0]

    col_csv, col_xlsx = st.columns(2)
    with col_csv:
        csv_data = cleaned.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇️ Download as CSV",
            data=csv_data,
            file_name=f"cleaned_{base_name}_{timestamp}.csv",
            mime="text/csv",
            use_container_width=True
        )
    with col_xlsx:
        buffer = BytesIO()
        cleaned.to_excel(buffer, index=False, engine="openpyxl")
        buffer.seek(0)
        st.download_button(
            label="⬇️ Download as Excel",
            data=buffer,
            file_name=f"cleaned_{base_name}_{timestamp}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

    with st.expander("👀 Preview cleaned data (first 100 rows)"):
        st.dataframe(cleaned.head(100), use_container_width=True)

st.markdown("---")
st.caption("Blocklist auto-updates every 4 hours via GitHub Actions.")
