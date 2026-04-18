import streamlit as st
import pandas as pd
import gzip
import os
import gc
from io import BytesIO
from datetime import datetime

# ============================================================
# CONFIG
# ============================================================
BLOCKLIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blocklist.txt.gz")


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


@st.cache_resource(ttl=7200)
def load_blocklist_from_file():
    """Load blocklist from compressed file — shared across all sessions."""
    try:
        numbers = set()
        with gzip.open(BLOCKLIST_PATH, "rt") as f:
            for line in f:
                num = line.strip()
                if num:
                    numbers.add(num)
        result = frozenset(numbers)
        del numbers
        gc.collect()
        return result, None
    except FileNotFoundError:
        return None, "blocklist.txt.gz not found in repo."
    except Exception as e:
        return None, f"Error reading blocklist: {e}"


def safe_extract_numbers_from_df(df, col):
    """Extract caller numbers from a dataframe column."""
    nums = set()
    for val in df[col]:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        if isinstance(val, float):
            val = int(val)
        s = str(val).strip()
        if s and s.lower() not in ("nan", "none"):
            nums.add(s)
    return frozenset(nums)


# ============================================================
# MAIN APP
# ============================================================
st.title("🔍 Placement File Filter")
st.caption("Upload placement file → Remove 8+ attempt numbers → Download clean file")
st.divider()

if "blocklist" not in st.session_state:
    st.session_state.blocklist = None
    st.session_state.bl_error = None

if st.session_state.blocklist is None:
    with st.spinner("⏳ Loading blocklist..."):
        numbers, err = load_blocklist_from_file()
    if numbers:
        st.session_state.blocklist = numbers
        st.session_state.bl_error = None
    else:
        st.session_state.bl_error = err

if st.session_state.blocklist:
    st.success(f"✅ Blocklist active — **{len(st.session_state.blocklist):,}** numbers with 8+ attempts")

    col1, col2, _ = st.columns([1, 1, 2])
    with col1:
        if st.button("🔄 Reload"):
            st.cache_resource.clear()
            st.session_state.blocklist = None
            gc.collect()
            st.rerun()
    with col2:
        if st.button("📁 Upload New Blocklist"):
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
                    nums = safe_extract_numbers_from_df(bl_df, "caller_number")
                    del bl_df
                    gc.collect()
                    st.session_state.blocklist = nums
                    st.session_state.show_manual = False
                    st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")
else:
    st.error(f"❌ {st.session_state.bl_error}")
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
            nums = safe_extract_numbers_from_df(bl_df, "caller_number")
            del bl_df
            gc.collect()
            st.session_state.blocklist = nums
            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")
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
            width="stretch"
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
            width="stretch"
        )

    with st.expander("👀 Preview cleaned data (first 100 rows)"):
        st.dataframe(cleaned.head(100), width="stretch")

st.markdown("---")
st.caption("Blocklist auto-updates every 4 hours via GitHub Actions.")
