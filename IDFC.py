import streamlit as st
import pandas as pd
import requests
import os
import gc
from io import BytesIO
from datetime import datetime

# ============================================================
# CONFIG
# ============================================================
METABASE_BASE = st.secrets.get("metabase_base", "https://metabase.skit.ai")
QUESTION_UUID = st.secrets.get("question_uuid", "4e3ab1cc-2e49-4b94-ac39-07c7afa84210")
METABASE_JSON_URL = f"{METABASE_BASE}/api/public/card/{QUESTION_UUID}/query/json"
BLOCKLIST_DIR = os.path.dirname(os.path.abspath(__file__))


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
    """Fetch blocklist — memory efficient: only store the set of numbers, not the full JSON."""
    errors = []

    try:
        # Stream the response to avoid loading entire JSON into memory at once
        resp = requests.get(METABASE_JSON_URL, timeout=300, stream=True)
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, list) and len(data) > 0:
            # Extract only caller_number, discard everything else immediately
            first_row = data[0]
            caller_key = None
            for key in first_row.keys():
                if key.strip().lower() in ("caller_number", "caller number"):
                    caller_key = key
                    break

            if caller_key:
                # Build set directly — most memory efficient
                numbers = set()
                count = 0
                for row in data:
                    val = row.get(caller_key)
                    if val is not None:
                        if isinstance(val, float):
                            val = int(val)
                        s = str(val).strip()
                        if s and s.lower() not in ("nan", "none"):
                            numbers.add(s)
                    count += 1

                # Free the large JSON list from memory
                del data
                gc.collect()

                if numbers:
                    return numbers, count, "Metabase API (live)", None

        errors.append("JSON endpoint returned 0 usable rows")
        del data
        gc.collect()

    except requests.exceptions.Timeout:
        errors.append("Metabase API timed out (5 min limit)")
    except requests.exceptions.ConnectionError:
        errors.append("Cannot connect to Metabase")
    except MemoryError:
        errors.append("Not enough memory to load full blocklist from API")
        gc.collect()
    except Exception as e:
        errors.append(f"API error: {e}")
        gc.collect()

    # --- Fallback: Local file ---
    csv_path = os.path.join(BLOCKLIST_DIR, "blocklist.csv")
    xlsx_path = os.path.join(BLOCKLIST_DIR, "blocklist.xlsx")
    fallback_path = csv_path if os.path.exists(csv_path) else (xlsx_path if os.path.exists(xlsx_path) else None)

    if fallback_path:
        try:
            if fallback_path.endswith(".csv"):
                # Read only the caller_number column to save memory
                df = pd.read_csv(fallback_path, usecols=["caller_number"])
            else:
                df = pd.read_excel(fallback_path, usecols=["caller_number"])
            numbers = set()
            for val in df["caller_number"]:
                if val is not None and not (isinstance(val, float) and pd.isna(val)):
                    if isinstance(val, float):
                        val = int(val)
                    s = str(val).strip()
                    if s and s.lower() not in ("nan", "none"):
                        numbers.add(s)
            del df
            gc.collect()
            if numbers:
                mod_time = datetime.fromtimestamp(os.path.getmtime(fallback_path)).strftime("%d %b %Y, %I:%M %p")
                return numbers, len(numbers), f"Local file (updated {mod_time})", None
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
    with st.spinner("⏳ Fetching blocklist from Metabase (loading 2.6M+ numbers, may take 1-2 min)..."):
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
            gc.collect()
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
                    nums = set()
                    for val in bl_df["caller_number"]:
                        if val is not None and not (isinstance(val, float) and pd.isna(val)):
                            if isinstance(val, float):
                                val = int(val)
                            s = str(val).strip()
                            if s and s.lower() not in ("nan", "none"):
                                nums.add(s)
                    del bl_df
                    gc.collect()
                    st.session_state.blocklist = nums
                    st.session_state.bl_count = len(nums)
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
            nums = set()
            for val in bl_df["caller_number"]:
                if val is not None and not (isinstance(val, float) and pd.isna(val)):
                    if isinstance(val, float):
                        val = int(val)
                    s = str(val).strip()
                    if s and s.lower() not in ("nan", "none"):
                        nums.add(s)
            del bl_df
            gc.collect()
            st.session_state.blocklist = nums
            st.session_state.bl_count = len(nums)
            st.session_state.bl_source = "Manual upload"
            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")
    if st.button("🔄 Retry Metabase"):
        st.cache_data.clear()
        st.session_state.blocklist = None
        gc.collect()
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

    # Free original df
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
st.caption("Blocklist refreshes from Metabase every 30 min. Use 'Refresh' for latest or 'Upload Instead' as backup.")