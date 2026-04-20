import streamlit as st
import pandas as pd
import gzip
import os
import gc
from io import BytesIO
from datetime import datetime

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


@st.cache_resource
def load_blocklist():
    """Load blocklist once, share across all users."""
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
        return None, "blocklist.txt.gz not found."
    except Exception as e:
        return None, str(e)


def clean_number(x):
    if isinstance(x, float) and pd.notna(x) and x == int(x):
        return str(int(x))
    elif pd.notna(x):
        return str(x).strip()
    return ""


def process_file(uploaded_file, file_ext, blocklist):
    """Read only caller_number column, filter, return clean numbers."""
    uploaded_file.seek(0)

    if file_ext == "csv":
        df = pd.read_csv(uploaded_file, usecols=["caller_number"], dtype={"caller_number": str})
    else:
        df = pd.read_excel(uploaded_file, usecols=["caller_number"])

    df.columns = [c.strip() for c in df.columns]
    df["_clean"] = df["caller_number"].apply(clean_number)

    total = len(df)
    kept = df[~df["_clean"].isin(blocklist)]["_clean"].tolist()
    dropped = total - len(kept)

    del df
    gc.collect()

    # Create clean output
    result_df = pd.DataFrame({"caller_number": kept})
    del kept
    gc.collect()

    return result_df, total, len(result_df), dropped


# ============================================================
# MAIN APP
# ============================================================
st.title("🔍 Placement File Filter")
st.caption("Upload placement file → Remove 8+ attempt numbers → Download clean caller numbers")
st.divider()

if not os.path.exists(BLOCKLIST_PATH):
    st.error("❌ blocklist.txt.gz not found.")
    st.stop()

blocklist, err = load_blocklist()
if err:
    st.error(f"❌ {err}")
    st.stop()

st.success(f"✅ Blocklist active — **{len(blocklist):,}** numbers with 8+ attempts")

col1, col2, _ = st.columns([1, 1, 2])
with col1:
    if st.button("🔄 Reload Blocklist"):
        st.cache_resource.clear()
        gc.collect()
        st.rerun()

st.divider()
st.subheader("📁 Upload Placement File")
st.caption("The app reads only the **caller_number** column, filters out 8+ attempt numbers, and returns clean caller numbers.")
uploaded_file = st.file_uploader(
    "Drop your CSV or Excel file here",
    type=["csv", "xlsx", "xls"],
    help="File must contain a 'caller_number' column",
    key="placement_upload"
)

if uploaded_file:
    file_ext = uploaded_file.name.split(".")[-1].lower()

    # Validate columns
    uploaded_file.seek(0)
    try:
        if file_ext == "csv":
            test_df = pd.read_csv(uploaded_file, nrows=1)
        else:
            test_df = pd.read_excel(uploaded_file, nrows=1)
        test_df.columns = [c.strip() for c in test_df.columns]
        if "caller_number" not in test_df.columns:
            st.error(f"❌ 'caller_number' not found. Your file has: {', '.join(test_df.columns)}")
            st.stop()
        del test_df
    except Exception as e:
        st.error(f"❌ Could not read file: {e}")
        st.stop()

    with st.spinner("⏳ Filtering placement file..."):
        try:
            result_df, total, kept_count, dropped = process_file(uploaded_file, file_ext, blocklist)
        except Exception as e:
            st.error(f"❌ Error processing file: {e}")
            st.stop()

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
            <div class="metric-value" style="color: #28a745;">{kept_count:,}</div>
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

    csv_data = result_df.to_csv(index=False).encode("utf-8")

    col_csv, col_xlsx = st.columns(2)
    with col_csv:
        st.download_button(
            label="⬇️ Download Clean Numbers (CSV)",
            data=csv_data,
            file_name=f"clean_numbers_{base_name}_{timestamp}.csv",
            mime="text/csv",
            use_container_width=True
        )
    with col_xlsx:
        buffer = BytesIO()
        result_df.to_excel(buffer, index=False, engine="openpyxl")
        buffer.seek(0)
        st.download_button(
            label="⬇️ Download Clean Numbers (Excel)",
            data=buffer,
            file_name=f"clean_numbers_{base_name}_{timestamp}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

    del result_df
    gc.collect()

    with st.expander("👀 Preview clean numbers (first 100)"):
        preview = pd.read_csv(BytesIO(csv_data), nrows=100)
        st.dataframe(preview, use_container_width=True)
        del preview

    st.divider()
    st.info(
        "📋 **Next step:** Use the downloaded clean numbers file to filter your original placement file.\n\n"
        "In Excel: Use VLOOKUP or FILTER to keep only rows where caller_number exists in the clean numbers file."
    )

st.markdown("---")
st.caption("Blocklist auto-updates every 4 hours via GitHub Actions.")
