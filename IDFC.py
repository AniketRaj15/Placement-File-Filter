import streamlit as st
import pandas as pd
import requests
import os
from io import BytesIO
from datetime import datetime

# ============================================================
# CONFIG — reads from Streamlit secrets (set in Streamlit Cloud)
# Fallback values used for local development only
# ============================================================
METABASE_BASE = st.secrets.get("metabase_base", "https://metabase.skit.ai")
QUESTION_UUID = st.secrets.get("question_uuid", "4e3ab1cc-2e49-4b94-ac39-07c7afa84210")
METABASE_JSON_URL = f"{METABASE_BASE}/api/public/card/{QUESTION_UUID}/query/json"
METABASE_QUERY_URL = f"{METABASE_BASE}/api/public/card/{QUESTION_UUID}/query"
BLOCKLIST_DIR = os.path.dirname(os.path.abspath(__file__))


def safe_extract_numbers(values):
    numbers = set()
    for val in values:
        if val is None:
            continue
        try:
            if isinstance(val, float):
                if pd.isna(val):
                    continue
                val = int(val)
            s = str(val).strip()
            if s and s.lower() not in ("nan", "none", ""):
                numbers.add(s)
        except (ValueError, TypeError):
            continue
    return numbers


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


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_blocklist():
    errors = []

    # --- Attempt 1: /query/json ---
    try:
        resp = requests.get(METABASE_JSON_URL, timeout=180)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and len(data) > 0:
            first_row = data[0]
            caller_key = None
            for key in first_row.keys():
                if key.strip().lower() in ("caller_number", "caller number"):
                    caller_key = key
                    break
            if caller_key:
                raw = [row.get(caller_key) for row in data]
                numbers = safe_extract_numbers(raw)
                if numbers:
                    return numbers, len(data), "Metabase API (live)", None
        errors.append("JSON endpoint returned 0 rows")
    except requests.exceptions.Timeout:
        errors.append("Metabase API timed out")
    except requests.exceptions.ConnectionError:
        errors.append("Cannot connect to Metabase")
    except Exception as e:
        errors.append(f"JSON endpoint: {e}")

    # --- Attempt 2: /query ---
    try:
        resp = requests.get(METABASE_QUERY_URL, timeout=180)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "data" in data and "rows" in data["data"]:
            cols = [c["name"].strip().lower() for c in data["data"]["cols"]]
            rows = data["data"]["rows"]
            if "caller_number" in cols and len(rows) > 0:
                idx = cols.index("caller_number")
                raw = [row[idx] for row in rows]
                numbers = safe_extract_numbers(raw)
                if numbers:
                    return numbers, len(rows), "Metabase API (live)", None
        errors.append("Query endpoint returned 0 rows")
    except Exception as e:
        errors.append(f"Query endpoint: {e}")

    # --- Attempt 3: Local file fallback ---
    csv_path = os.path.join(BLOCKLIST_DIR, "blocklist.csv")
    xlsx_path = os.path.join(BLOCKLIST_DIR, "blocklist.xlsx")
    fallback_path = csv_path if os.path.exists(csv_path) else (xlsx_path if os.path.exists(xlsx_path) else None)

    if fallback_path:
        try:
            if fallback_path.endswith(".csv"):
                df = pd.read_csv(fallback_path)
            else:
                df = pd.read_excel(fallback_path)
            df.columns = [c.strip().lower() for c in df.columns]
            if "caller_number" in df.columns:
                numbers = safe_extract_numbers(df["caller_number"].tolist())
                if numbers:
                    mod_time = datetime.fromtimestamp(os.path.getmtime(fallback_path)).strftime("%d %b %Y, %I:%M %p")
                    return numbers, len(df), f"Local file (updated {mod_time})", None
        except Exception as e:
            errors.append(f"Local file: {e}")

    return None, 0, None, " | ".join(errors)


# ============================================================
# MAIN APP
# ============================================================
st.title("🔍 Placement File Filter")
st.caption("Upload placement file → Remove 8+ attempt numbers → Download clean file")
st.divider()

if "blocklist" not in st.session_state:
    st.session_state.blocklist = None
    st.session_state.bl_count = 0
    st.session_state.bl_source = None
    st.session_state.bl_error = None

if st.session_state.blocklist is None:
    with st.spinner("⏳ Fetching blocklist from Metabase (this may take a minute for 2.6M+ numbers)..."):
        numbers, count, source, err = fetch_blocklist()
    if numbers:
        st.session_state.blocklist = numbers
        st.session_state.bl_count = count
        st.session_state.bl_source = source
        st.session_state.bl_error = None
    else:
        st.session_state.bl_error = err

if st.session_state.blocklist:
    st.success(
        f"✅ Blocklist active — **{len(st.session_state.blocklist):,}** numbers with 8+ attempts\n\n"
        f"Source: {st.session_state.bl_source}"
    )
    col1, col2, _ = st.columns([1, 1, 2])
    with col1:
        if st.button("🔄 Refresh"):
            st.cache_data.clear()
            st.session_state.blocklist = None
            st.rerun()
    with col2:
        if st.button("📁 Upload Instead"):
            st.session_state.show_manual = True
            st.rerun()

    if st.session_state.get("show_manual"):
        st.divider()
        st.caption("Upload a fresh blocklist export from Metabase to override.")
        manual_file = st.file_uploader("Upload blocklist CSV/Excel", type=["csv", "xlsx", "xls"], key="manual_bl")
        if manual_file:
            ext = manual_file.name.split(".")[-1].lower()
            try:
                bl_df = pd.read_csv(manual_file) if ext == "csv" else pd.read_excel(manual_file)
                bl_df.columns = [c.strip().lower() for c in bl_df.columns]
                if "caller_number" not in bl_df.columns:
                    st.error(f"'caller_number' not found. Columns: {', '.join(bl_df.columns)}")
                else:
                    nums = safe_extract_numbers(bl_df["caller_number"].tolist())
                    st.session_state.blocklist = nums
                    st.session_state.bl_count = len(bl_df)
                    st.session_state.bl_source = "Manual upload"
                    st.session_state.show_manual = False
                    st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")
else:
    st.error(f"❌ Could not load blocklist: {st.session_state.bl_error}")
    st.info("**Fallback:** Upload the blocklist file exported from Metabase below.")
    fallback_file = st.file_uploader("Upload blocklist CSV/Excel", type=["csv", "xlsx", "xls"], key="fallback_bl")
    if fallback_file:
        ext = fallback_file.name.split(".")[-1].lower()
        try:
            bl_df = pd.read_csv(fallback_file) if ext == "csv" else pd.read_excel(fallback_file)
            bl_df.columns = [c.strip().lower() for c in bl_df.columns]
            if "caller_number" not in bl_df.columns:
                st.error(f"'caller_number' not found. Columns: {', '.join(bl_df.columns)}")
                st.stop()
            nums = safe_extract_numbers(bl_df["caller_number"].tolist())
            st.session_state.blocklist = nums
            st.session_state.bl_count = len(bl_df)
            st.session_state.bl_source = "Manual upload"
            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")
    if st.button("🔄 Retry Metabase"):
        st.cache_data.clear()
        st.session_state.blocklist = None
        st.rerun()
    st.stop()

# --- PLACEMENT FILE UPLOAD ---
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

    df["_clean"] = df["caller_number"].apply(
        lambda x: str(int(x)) if isinstance(x, float) and pd.notna(x) and x == int(x)
        else (str(x).strip() if pd.notna(x) else "")
    )

    total = len(df)
    cleaned = df[~df["_clean"].isin(st.session_state.blocklist)].drop(columns=["_clean"]).copy()
    dropped = total - len(cleaned)

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
st.caption("Blocklist refreshes from Metabase every 30 min. Use 'Refresh' for latest or 'Upload Instead' as backup.")