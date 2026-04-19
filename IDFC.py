import streamlit as st
import pandas as pd
import gzip
import os
import gc
import tempfile
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


def get_blocklist_count():
    try:
        count = 0
        with gzip.open(BLOCKLIST_PATH, "rt") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count, None
    except FileNotFoundError:
        return 0, "blocklist.txt.gz not found."
    except Exception as e:
        return 0, str(e)


def clean_number(x):
    if isinstance(x, float) and pd.notna(x) and x == int(x):
        return str(int(x))
    elif pd.notna(x):
        return str(x).strip()
    return ""


def find_blocked_numbers(placement_numbers):
    """Read blocklist line by line, return only numbers found in placement file."""
    blocked = set()
    with gzip.open(BLOCKLIST_PATH, "rt") as f:
        for line in f:
            num = line.strip()
            if num in placement_numbers:
                blocked.add(num)
    return blocked


def process_csv_chunked(uploaded_file):
    """Process CSV in chunks — low memory."""
    # Pass 1: Read only caller_number to find unique numbers
    uploaded_file.seek(0)
    placement_numbers = set()
    total_rows = 0
    for chunk in pd.read_csv(uploaded_file, usecols=["caller_number"], chunksize=50000):
        chunk.columns = [c.strip() for c in chunk.columns]
        for val in chunk["caller_number"]:
            placement_numbers.add(clean_number(val))
        total_rows += len(chunk)
    gc.collect()

    # Find blocked numbers
    blocked = find_blocked_numbers(placement_numbers)
    del placement_numbers
    gc.collect()

    # Pass 2: Read full file in chunks, filter, write to temp CSV
    uploaded_file.seek(0)
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
    header_written = False
    kept_count = 0

    for chunk in pd.read_csv(uploaded_file, chunksize=50000):
        chunk.columns = [c.strip() for c in chunk.columns]
        chunk["_clean"] = chunk["caller_number"].apply(clean_number)
        kept = chunk[~chunk["_clean"].isin(blocked)].drop(columns=["_clean"])
        kept.to_csv(tmp, index=False, header=not header_written, mode="a")
        header_written = True
        kept_count += len(kept)
        del chunk, kept
        gc.collect()

    tmp.close()
    dropped = total_rows - kept_count
    del blocked
    gc.collect()

    return tmp.name, total_rows, kept_count, dropped


def process_excel_chunked(uploaded_file):
    """Process Excel — read caller_number first, then full file in chunks."""
    # Pass 1: Only caller_number column
    uploaded_file.seek(0)
    df_caller = pd.read_excel(uploaded_file, usecols=["caller_number"])
    df_caller.columns = [c.strip() for c in df_caller.columns]
    placement_numbers = set(df_caller["caller_number"].apply(clean_number).tolist())
    total_rows = len(df_caller)
    del df_caller
    gc.collect()

    # Find blocked numbers
    blocked = find_blocked_numbers(placement_numbers)
    del placement_numbers
    gc.collect()

    # Pass 2: Full file in chunks
    uploaded_file.seek(0)
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
    header_written = False
    kept_count = 0

    # Excel doesn't support chunked reading natively, so read full but filter immediately
    for chunk_start in range(0, total_rows, 50000):
        uploaded_file.seek(0)
        df_chunk = pd.read_excel(
            uploaded_file,
            skiprows=range(1, chunk_start + 1) if chunk_start > 0 else None,
            nrows=50000
        )
        df_chunk.columns = [c.strip() for c in df_chunk.columns]
        df_chunk["_clean"] = df_chunk["caller_number"].apply(clean_number)
        kept = df_chunk[~df_chunk["_clean"].isin(blocked)].drop(columns=["_clean"])
        kept.to_csv(tmp, index=False, header=not header_written, mode="a")
        header_written = True
        kept_count += len(kept)
        del df_chunk, kept
        gc.collect()

    tmp.close()
    dropped = total_rows - kept_count
    del blocked
    gc.collect()

    return tmp.name, total_rows, kept_count, dropped


# ============================================================
# MAIN APP
# ============================================================
st.title("🔍 Placement File Filter")
st.caption("Upload placement file → Remove 8+ attempt numbers → Download clean file")
st.divider()

if not os.path.exists(BLOCKLIST_PATH):
    st.error("❌ blocklist.txt.gz not found.")
    st.stop()

count, err = get_blocklist_count()
if err:
    st.error(f"❌ {err}")
    st.stop()

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

    with st.spinner("⏳ Filtering placement file (may take 30-60 seconds for large files)..."):
        try:
            if file_ext == "csv":
                tmp_path, total, kept_count, dropped = process_csv_chunked(uploaded_file)
            else:
                tmp_path, total, kept_count, dropped = process_excel_chunked(uploaded_file)
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

    # Read the temp file for download
    with open(tmp_path, "rb") as f:
        csv_data = f.read()

    col_csv, col_xlsx = st.columns(2)
    with col_csv:
        st.download_button(
            label="⬇️ Download as CSV",
            data=csv_data,
            file_name=f"cleaned_{base_name}_{timestamp}.csv",
            mime="text/csv",
            use_container_width=True
        )
    with col_xlsx:
        # Convert temp CSV to Excel
        df_out = pd.read_csv(tmp_path)
        buffer = BytesIO()
        df_out.to_excel(buffer, index=False, engine="openpyxl")
        buffer.seek(0)
        del df_out
        gc.collect()
        st.download_button(
            label="⬇️ Download as Excel",
            data=buffer,
            file_name=f"cleaned_{base_name}_{timestamp}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

    # Preview
    with st.expander("👀 Preview cleaned data (first 100 rows)"):
        preview = pd.read_csv(tmp_path, nrows=100)
        st.dataframe(preview, use_container_width=True)
        del preview

    # Cleanup temp file
    try:
        os.unlink(tmp_path)
    except:
        pass

st.markdown("---")
st.caption("Blocklist auto-updates every 4 hours via GitHub Actions.")
