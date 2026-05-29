import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import os
import io
import datetime

from src.matcher import fuzzy_match_columns, auto_detect_primary_key
from src.engine import ReconciliationEngine
from src.reporter import generate_excel_report

# Set up page configurations
st.set_page_config(
    page_title="Smart Data Reconciliation Platform",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load CSS styling
def load_css(css_path):
    if os.path.exists(css_path):
        with open(css_path, "r") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    else:
        st.warning("Custom CSS file not found. Falling back to default layout.")

# Resolve absolute path for custom CSS
css_file = os.path.join(os.path.dirname(__file__), "assets", "custom.css")
load_css(css_file)

# Helper function to generate mock ETL datasets
def generate_demo_datasets() -> tuple[pd.DataFrame, pd.DataFrame, str]:
    np.random.seed(42)
    rows_cnt = 500
    
    users = ["Alice", "Bob", "Charlie", "Diana", "Eve"]
    projects = ["Project Alpha", "Project Beta", "Project Gamma"]
    
    # 1. Source dataset
    source_data = {
        "id": [f"ID-{1000 + i}" for i in range(rows_cnt)],
        "user": np.random.choice(users, size=rows_cnt),
        "project_name": np.random.choice(projects, size=rows_cnt),
        "minutes": [int(np.random.uniform(30, 480)) for _ in range(rows_cnt)],
        "date": [(pd.Timestamp("2026-05-01") + pd.Timedelta(days=np.random.randint(0, 20))).strftime("%Y-%m-%d") for _ in range(rows_cnt)]
    }
    df_src = pd.DataFrame(source_data)
    
    # 2. Introduce ETL discrepancies into Target dataset
    df_tgt = df_src.copy()
    
    # Schema Column Names change
    df_tgt = df_tgt.rename(columns={
        "user": "user_name",
        "date": "entry_date",
        "minutes": "mins",
        "project_name": "project_id"
    })
    
    # Row Count Differences: Drop rows in target (missing records)
    drop_indices = [15, 42, 108, 250, 314, 389, 412, 480]
    df_tgt = df_tgt.drop(drop_indices)
    
    # Extra Records: Add phantom records in target
    extra_records = [
        {"id": "ID-20001", "user_name": "Bob", "project": "Project Alpha", "mins": 120, "entry_date": "2026-05-18"},
        {"id": "ID-20002", "user_name": "Alice", "project": "Project Beta", "mins": 90, "entry_date": "2026-05-19"},
    ]
    df_tgt = pd.concat([df_tgt, pd.DataFrame(extra_records)], ignore_index=True)
    
    # Value level differences:
    df_tgt.loc[5, "mins"] = df_tgt.loc[5, "mins"] + 15
    df_tgt.loc[12, "mins"] = df_tgt.loc[12, "mins"] - 10
    
    # 3. Create simulated ETL Log File contents
    etl_log = "[2026-05-28 18:01:05] INFO: Starting ETL job 'timesheet_sync'\n"
    return df_src, df_tgt, etl_log


# Title and Description
st.markdown("<h1>🔍 Smart Data Reconciliation Platform</h1>", unsafe_allow_html=True)
st.markdown(
    "<p style='color: #94a3b8; font-size: 1.1rem; margin-top: -10px; margin-bottom: 25px;'>"
    "An ETL verification dashboard to automatically match, align, and reconcile source and target datasets."
    "</p>", 
    unsafe_allow_html=True
)

# Initialize Session State
if "df_source" not in st.session_state:
    st.session_state.df_source = None
if "df_target" not in st.session_state:
    st.session_state.df_target = None
if "etl_log" not in st.session_state:
    st.session_state.etl_log = ""
if "src_filename" not in st.session_state:
    st.session_state.src_filename = ""
if "tgt_filename" not in st.session_state:
    st.session_state.tgt_filename = ""
if "demo_loaded" not in st.session_state:
    st.session_state.demo_loaded = False

# ==========================================
# SIDEBAR: SETUP & CONFIGURATION
# ==========================================
with st.sidebar:
    st.markdown("<h2 style='margin-top: 0;'>⚙️ Upload & Setup</h2>", unsafe_allow_html=True)
    
    # Demo Data Loader
    if st.button("🚀 Load Sample Demo Datasets"):
        df_s, df_t, log = generate_demo_datasets()
        st.session_state.df_source = df_s
        st.session_state.df_target = df_t
        st.session_state.etl_log = log
        st.session_state.src_filename = "source_transactions.csv"
        st.session_state.tgt_filename = "dw_transactions_target.xlsx"
        st.session_state.demo_loaded = True
        st.toast("Loaded sample e-commerce data with schema, row, duplicate and value discrepancies!", icon="✅")
        st.rerun()

    st.markdown("<hr style='border-color: #1e293b; margin: 15px 0;'>", unsafe_allow_html=True)
    
    # Real file uploaders
    st.markdown("### 📂 Datasets Upload")
    src_file = st.file_uploader("Source Dataset (CSV or Excel)", type=["csv", "xlsx", "xls"])
    tgt_file = st.file_uploader("Target Dataset (CSV or Excel)", type=["csv", "xlsx", "xls"])
    log_file = st.file_uploader("ETL Pipeline Log (Optional)", type=["txt", "log"])

    if src_file:
        st.session_state.src_filename = src_file.name
        if src_file.name.endswith('.csv'):
            st.session_state.df_source = pd.read_csv(src_file)
        else:
            st.session_state.df_source = pd.read_excel(src_file)
            
    if tgt_file:
        st.session_state.tgt_filename = tgt_file.name
        if tgt_file.name.endswith('.csv'):
            st.session_state.df_target = pd.read_csv(tgt_file)
        else:
            st.session_state.df_target = pd.read_excel(tgt_file)
            
    if log_file:
        st.session_state.etl_log = io.StringIO(log_file.getvalue().decode("utf-8")).read()

    # Advanced Matching parameters
    st.markdown("### 🔧 Match Parameters")
    float_tol = st.number_input("Float Precision Tolerance", value=1e-4, format="%.6f", help="Precision difference permitted before numeric values are marked as mismatched.")
    ignore_case = st.checkbox("Ignore String Casing", value=False, help="Treat 'Completed' and 'completed' as identical values.")
    trim_space = st.checkbox("Trim Whitespaces", value=True, help="Strip leading and trailing spaces from text elements.")
    fuzzy_thresh = st.slider("Fuzzy Column Schema Threshold", min_value=50, max_value=100, value=70, help="Similarity index above which source and target columns are auto-mapped.")

    # Optional configuration panel removed.

# ==========================================
# MAIN PAGE ROUTING & INTERFACE
# ==========================================

# Show introductory Splash Screen if no files are loaded
if st.session_state.df_source is None or st.session_state.df_target is None:
    st.markdown(
        """
        <div style="background: rgba(30, 41, 59, 0.45); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 20px; padding: 2.5rem; text-align: center; margin-top: 2rem;">
            <div style="font-size: 4rem; margin-bottom: 1rem;">⚖️</div>
            <h2 style="margin-top: 0; color: #ffffff;">Welcome to the ETL Reconciliation Suite</h2>
            <p style="color: #94a3b8; max-width: 600px; margin: 0 auto 1.5rem auto; font-size: 1.05rem;">
                This platform automatically aligns tables, highlights row-level inconsistencies, handles type coercion checks, and explains ETL pipeline failures.
            </p>
            <p style="color: #e2e8f0; font-weight: 500; margin-bottom: 2rem;">
                To begin, upload your source and target datasets in the left panel, or load our simulated demo suite.
            </p>
            <div style="max-width: 400px; margin: 0 auto; padding: 1.5rem; background: rgba(15, 23, 42, 0.4); border-radius: 12px; border: 1px solid #1e293b; text-align: left;">
                <h4 style="margin-top: 0; color: #38bdf8;">💡 Key features demonstrated:</h4>
                <ul style="color: #94a3b8; font-size: 0.9rem; margin-bottom: 0; padding-left: 1.2rem;">
                    <li>Fuzzy schema mapping (RapidFuzz alignment)</li>
                    <li>Orphaned row validation (Missing vs Extra keys)</li>
                    <li>Duplicate join-key audits</li>
                    <li>Cell-by-cell numerical difference tolerance</li>
                    <li>Automated openpyxl Excel exception reports</li>
                </ul>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
    st.stop()

# Datasets loaded: Show reconciliation configuration editor
df_src = st.session_state.df_source
df_tgt = st.session_state.df_target

st.markdown("## 📊 Schema Mapping & Key Selection")

# Perform fuzzy column matching on load
source_cols = list(df_src.columns)
target_cols = list(df_tgt.columns)

mappings_suggested = fuzzy_match_columns(source_cols, target_cols, threshold=fuzzy_thresh)

col_mapping_selections = {src: tgt for src, (tgt, score) in mappings_suggested.items()}

# Suggest a primary key
auto_key = auto_detect_primary_key(df_src, df_tgt, col_mapping_selections)
key_options = [c for c in source_cols if col_mapping_selections.get(c)]

if not key_options or not auto_key:
    st.error("No valid column mappings configured or no primary key detected. Please check datasets.")
    st.stop()

join_key_source = auto_key
join_key_target = col_mapping_selections[join_key_source]

with st.expander("🛠️ Auto-Detected Schema Alignments", expanded=False):
    st.success(f"**Auto-Selected Primary Key**: `{join_key_source}` ➔ `{join_key_target}`")
    st.markdown("**Mapped Columns:**")
    for src, tgt in col_mapping_selections.items():
        if tgt:
            st.markdown(f"- `{src}` ➔ `{tgt}`")

# Reset demo load state triggers
st.session_state.demo_loaded = False

with st.spinner("Executing reconciliation audits..."):
    # Initialize engine
    engine = ReconciliationEngine(
        df_source=df_src,
        df_target=df_tgt,
        source_key=join_key_source,
        target_key=join_key_target,
        column_mappings=col_mapping_selections,
        float_tolerance=float_tol,
        ignore_casing=ignore_case,
        trim_whitespace=trim_space
    )
    
    results = engine.execute()
    
summary = results["summary"]

# ----------------------------------------------------
# RENDER KPI DASHBOARD METRICS
# ----------------------------------------------------
# Helper to find matching column names
def find_col(df, keywords):
    for k in keywords:
        for col in df.columns:
            if k.lower() in str(col).lower():
                return col
    return None
    
u_src = find_col(df_src, ['user'])
d_src = find_col(df_src, ['date', 'time'])
p_src = find_col(df_src, ['project name', 'project_name', 'projectname', 'project id', 'project_id', 'projectid', 'project', 'proj'])
m_src = find_col(df_src, ['min', 'time', 'amount'])

u_tgt = find_col(df_tgt, ['user'])
d_tgt = find_col(df_tgt, ['date', 'time'])
p_tgt = find_col(df_tgt, ['project name', 'project_name', 'projectname', 'project id', 'project_id', 'projectid', 'project', 'proj'])
m_tgt = find_col(df_tgt, ['min', 'time', 'amount'])

source_mins_total = int(df_src[m_src].sum()) if m_src else 0
target_mins_total = int(df_tgt[m_tgt].sum()) if m_tgt else 0

kpi_html = f"""
<div class="reconcile-card-container">
    <div class="reconcile-card info">
        <div class="card-title">Source Rows</div>
        <div class="card-value">{summary['source_row_count']:,}</div>
        <div class="card-subtext">{st.session_state.src_filename or 'Uploaded dataset'}</div>
    </div>
    <div class="reconcile-card info">
        <div class="card-title">Target Rows</div>
        <div class="card-value">{summary['target_row_count']:,}</div>
        <div class="card-subtext">{st.session_state.tgt_filename or 'Uploaded target'}</div>
    </div>
    <div class="reconcile-card info">
        <div class="card-title">Source Minutes</div>
        <div class="card-value">{source_mins_total:,}</div>
        <div class="card-subtext">Total Mins from Source</div>
    </div>
    <div class="reconcile-card info">
        <div class="card-title">Transformed Minutes</div>
        <div class="card-value">{target_mins_total:,}</div>
        <div class="card-subtext">Total Mins from Target</div>
    </div>
</div>
"""
st.markdown(kpi_html, unsafe_allow_html=True)

# ----------------------------------------------------
# TABULAR DASHBOARD CONTAINER
# ----------------------------------------------------
tab_overview, tab_schema, tab_missing, tab_values, tab_duplicates = st.tabs([
    "📊 Summary & Analytics",
    "📐 Schema Audit",
    "📂 Missing / Extra Rows",
    "⚠️ Value Mismatches",
    "👥 Duplicate Audit"
])

# ----------------------------------------------------
# TAB 1: OVERVIEW & PLOTLY CHARTS
# ----------------------------------------------------
with tab_overview:
    col_c1, col_c2 = st.columns([3, 2])
    
    with col_c1:
        st.markdown("### 📊 Dataset Counts")
        
        # 1. Total row counts of source vs target
        fig_counts = go.Figure(data=[
            go.Bar(
                x=['Source Rows', 'Target Rows'], 
                y=[summary['source_row_count'], summary['target_row_count']],
                marker_color=['#6366f1', '#10b981'],
                text=[summary['source_row_count'], summary['target_row_count']],
                textposition='auto'
            )
        ])
        fig_counts.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#94a3b8', family='Outfit'),
            yaxis=dict(gridcolor='#1e293b', title="Count"),
            xaxis=dict(gridcolor='#1e293b'),
            margin=dict(l=20, r=20, t=10, b=10),
            height=300
        )
        st.plotly_chart(fig_counts, use_container_width=True)
        

        st.markdown("### ⏱️ Minutes Comparison (Source vs Target)")
        
        def render_comparison(df_src_grp, df_tgt_grp, group_cols, title):
            # Merge source and target
            merged = pd.merge(df_src_grp, df_tgt_grp, on=group_cols, how='outer').fillna(0)
            merged['Unmatched'] = merged['Target Mins'] - merged['Source Mins']
            
            # Format and Style Table
            # Create total row
            total_row = {col: 'TOTAL' if col in group_cols else merged[col].sum() for col in merged.columns}
            merged_with_total = pd.concat([merged, pd.DataFrame([total_row])], ignore_index=True)
            
            def highlight_unmatched(val):
                if isinstance(val, (int, float)):
                    if val == 0:
                        return 'background-color: rgba(16, 185, 129, 0.15); color: #34d399;' # match (green)
                    else:
                        return 'background-color: rgba(239, 68, 68, 0.15); color: #f87171;' # mismatch (red)
                return ''
                
            styled_df = merged_with_total.style.map(highlight_unmatched, subset=['Unmatched'])
            
            st.markdown(f"#### {title}")
            
            # Plotly Bar Chart
            plot_df = merged.copy()
            if len(group_cols) == 1:
                x_axis = plot_df[group_cols[0]].astype(str)
            else:
                x_axis = plot_df[group_cols[0]].astype(str) + " - " + plot_df[group_cols[1]].astype(str)
                
            fig = go.Figure(data=[
                go.Bar(name='Source Mins', x=x_axis, y=plot_df['Source Mins'], marker_color='#6366f1'),
                go.Bar(name='Target Mins', x=x_axis, y=plot_df['Target Mins'], marker_color='#10b981')
            ])
            fig.update_layout(
                barmode='group',
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#94a3b8', family='Outfit'),
                yaxis=dict(gridcolor='#1e293b'),
                xaxis=dict(gridcolor='#1e293b'),
                margin=dict(l=10, r=10, t=10, b=10),
                height=250
            )
            
            st.plotly_chart(fig, use_container_width=True, key=f"chart_{title.replace(' ', '_')}")
            st.dataframe(styled_df, use_container_width=True)
            st.markdown("<hr style='border-color: #1e293b; margin: 20px 0;'>", unsafe_allow_html=True)
        
        if u_src and m_src and u_tgt and m_tgt:
            # 1. By User
            df_u_src = df_src.groupby(u_src)[m_src].sum().reset_index().rename(columns={u_src: 'User', m_src: 'Source Mins'})
            df_u_tgt = df_tgt.groupby(u_tgt)[m_tgt].sum().reset_index().rename(columns={u_tgt: 'User', m_tgt: 'Target Mins'})
            render_comparison(df_u_src, df_u_tgt, ['User'], "Aggregated by User")
            
            # 2. By Project
            if p_src and p_tgt:
                df_p_src = df_src.groupby(p_src)[m_src].sum().reset_index().rename(columns={p_src: 'Project', m_src: 'Source Mins'})
                df_p_tgt = df_tgt.groupby(p_tgt)[m_tgt].sum().reset_index().rename(columns={p_tgt: 'Project', m_tgt: 'Target Mins'})
                render_comparison(df_p_src, df_p_tgt, ['Project'], "Aggregated by Project")
                
                # 3. By User & Project
                df_up_src = df_src.groupby([u_src, p_src])[m_src].sum().reset_index().rename(columns={u_src: 'User', p_src: 'Project', m_src: 'Source Mins'})
                df_up_tgt = df_tgt.groupby([u_tgt, p_tgt])[m_tgt].sum().reset_index().rename(columns={u_tgt: 'User', p_tgt: 'Project', m_tgt: 'Target Mins'})
                render_comparison(df_up_src, df_up_tgt, ['User', 'Project'], "Aggregated by User & Project")
                
        else:
            st.info("Required columns (User and Minutes) could not be identified to generate comparison tables.")
    with col_c2:
        st.markdown("### 📂 Export Reconciliation Report")
        st.write("Generate and download a comprehensive Microsoft Excel exception audit sheet styling all issues into separated sheets with standard formulas.")
        
        # Generate Excel binary
        excel_bytes = generate_excel_report(
            results=results,
            source_name=st.session_state.src_filename or "source_transactions.csv",
            target_name=st.session_state.tgt_filename or "dw_transactions_target.xlsx"
        )
        
        st.download_button(
            label="📥 Download Excel Exception Report",
            data=excel_bytes,
            file_name=f"Reconciliation_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        
        st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
        
        # Text explanation block
        if summary["total_issues"] == 0:
            st.success("🎉 Success! Source and Target tables matched perfectly with zero errors.")
        else:
            st.warning(f"⚠️ Reconciliation completed with **{summary['total_issues']}** structural or cell exceptions. Click through the tabs above to review row lists.")
            
    # Show uploaded ETL log preview in Overview tab if uploaded
    if st.session_state.etl_log:
        with st.expander("📝 Uploaded Pipeline execution log preview"):
            st.markdown(f'<div class="code-log-container">{st.session_state.etl_log}</div>', unsafe_allow_html=True)

# ----------------------------------------------------
# TAB 2: SCHEMA DRIFT
# ----------------------------------------------------
with tab_schema:
    st.markdown("### 📐 Database Schema Drift Audits")
    
    schema_issues = results.get("schema_issues", [])
    if not schema_issues:
        st.success("✅ Mapped schema definitions and database column datatypes match perfectly between source and target.")
    else:
        st.write("Data Type discrepancies could cause value truncations, mathematical rounding drift, or pipeline ingestion aborts:")
        df_schema_issues = pd.DataFrame(schema_issues)
        st.dataframe(df_schema_issues, use_container_width=True)
        
    # Display Mapped Columns table for reference
    st.markdown("#### Mapping Overview Details")
    mapping_details = []
    for src_c, tgt_c in col_mapping_selections.items():
        if tgt_c:
            src_type = str(df_src[src_c].dtype)
            tgt_type = str(df_tgt[tgt_c].dtype)
            mapping_details.append({
                "Source Column": src_c,
                "Source Dtype": src_type,
                "Target Column": tgt_c,
                "Target Dtype": tgt_type,
                "Status": "Matched" if src_type == tgt_type else "Type Discrepancy"
            })
    df_map = pd.DataFrame(mapping_details)
    def style_schema_status(val):
        if val == 'Matched':
            return 'background-color: rgba(16, 185, 129, 0.15); color: #34d399; font-weight: 600;'
        else:
            return 'background-color: rgba(239, 68, 68, 0.15); color: #f87171; font-weight: 600;'
            
    styled_map = df_map.style.map(style_schema_status, subset=['Status'])
    st.dataframe(styled_map, use_container_width=True)
# ----------------------------------------------------
# TAB 3: MISSING & EXTRA RECORDS
# ----------------------------------------------------
with tab_missing:
    st.markdown("### 📂 Orphaned Rows & Cardinality Audits")
    
    df_missing = results.get("missing_records")
    df_extra = results.get("extra_records")
    
    col_m1, col_m2 = st.columns(2)
    
    with col_m1:
        st.markdown(f"#### 🔴 Missing in Target (`{len(df_missing)}` rows)")
        st.write("Rows present in Source dataset that did not load into Target database:")
        if df_missing is not None and not df_missing.empty:
            st.dataframe(df_missing.head(100), use_container_width=True)
            csv_miss = df_missing.to_csv(index=False).encode('utf-8')
            st.download_button("Download Missing Rows CSV", csv_miss, "missing_records.csv", "text/csv")
        else:
            st.success("Zero missing records detected.")
            
    with col_m2:
        st.markdown(f"#### 🟡 Extra in Target (`{len(df_extra)}` rows)")
        st.write("Rows present in Target database that do not exist in Source:")
        if df_extra is not None and not df_extra.empty:
            st.dataframe(df_extra.head(100), use_container_width=True)
            csv_extra = df_extra.to_csv(index=False).encode('utf-8')
            st.download_button("Download Extra Rows CSV", csv_extra, "extra_records.csv", "text/csv")
        else:
            st.success("Zero extra records detected.")

# ----------------------------------------------------
# TAB 4: VALUE LEVEL INCONSISTENCIES
# ----------------------------------------------------
with tab_values:
    st.markdown("### ⚠️ Cell-Level Reconciliation Differences")
    
    df_val_mismatch = results.get("value_mismatches")
    
    if df_val_mismatch is not None and not df_val_mismatch.empty:
        st.write(f"The following `{len(df_val_mismatch)}` cell-level discrepancies were identified in matching records:")
        
        # We want to format values for display
        display_df = df_val_mismatch[[
            join_key_source, 
            "source_column", 
            "target_column", 
            "source_value_str", 
            "target_value_str", 
            "reason"
        ]].copy()
        
        display_df = display_df.rename(columns={
            join_key_source: "Join Key ID",
            "source_column": "Source Col",
            "target_column": "Target Col",
            "source_value_str": "Source Value",
            "target_value_str": "Target DW Value",
            "reason": "Diagnostic Reason"
        })
        
        # Streamlit dataframe search
        search_col = st.text_input("🔍 Filter mismatches by column name or key:")
        if search_col:
            display_df = display_df[
                display_df['Source Col'].str.contains(search_col, case=False, na=False) |
                display_df['Join Key ID'].astype(str).str.contains(search_col, case=False, na=False)
            ]
            
        st.dataframe(display_df, use_container_width=True)
        
        # Download Value mismatches
        csv_val = df_val_mismatch.to_csv(index=False).encode('utf-8')
        st.download_button("Download Value Mismatches CSV", csv_val, "value_mismatches.csv", "text/csv")
    else:
        st.success("✅ Perfect cell values reconciliation! All aligned records match data content exactly.")

# ----------------------------------------------------
# TAB 5: DUPLICATES AUDIT
# ----------------------------------------------------
with tab_duplicates:
    st.markdown("### 👥 Duplicate Key Inspections")
    st.write("Primary/Join key duplications can trigger relational join card multiplications in warehouse views.")
    
    df_src_dup = results.get("duplicates", {}).get("source")
    df_tgt_dup = results.get("duplicates", {}).get("target")
    
    col_d1, col_d2 = st.columns(2)
    
    with col_d1:
        st.markdown(f"#### Source Duplicates (`{len(df_src_dup)}` rows)")
        if df_src_dup is not None and not df_src_dup.empty:
            st.dataframe(df_src_dup.head(100), use_container_width=True)
        else:
            st.success("No duplicate primary keys in source dataset.")
            
    with col_d2:
        st.markdown(f"#### Target Duplicates (`{len(df_tgt_dup)}` rows)")
        if df_tgt_dup is not None and not df_tgt_dup.empty:
            st.dataframe(df_tgt_dup.head(100), use_container_width=True)
        else:
            st.success("No duplicate primary keys in target database.")
