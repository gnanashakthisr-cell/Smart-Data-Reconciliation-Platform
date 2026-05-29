import pandas as pd
import sys
import os

from src.matcher import fuzzy_match_columns, auto_detect_primary_key
from src.engine import ReconciliationEngine
from src.reporter import generate_excel_report
from src.ai_analyser import run_rule_based_analysis

def main():
    print("🚀 Running ETL Reconciliation Backend Verification...")
    
    src_file = "demo_files/source_inventory.csv"
    tgt_file = "demo_files/target_warehouse_inventory.xlsx"
    log_file = "demo_files/inventory_etl.log"
    
    # 1. Assert file exists
    for f in [src_file, tgt_file, log_file]:
        if not os.path.exists(f):
            print(f"❌ Error: Required test file not found: {f}")
            sys.exit(1)
            
    print("✅ Test files verified on disk.")
    
    # 2. Read datasets
    df_src = pd.read_csv(src_file)
    df_tgt = pd.read_excel(tgt_file)
    
    with open(log_file, "r") as f:
        log_text = f.read()
        
    print(f"✅ Loaded datasets. Source: {len(df_src)} rows, Target: {len(df_tgt)} rows.")
    
    # 3. Fuzzy Column Mapping
    src_cols = list(df_src.columns)
    tgt_cols = list(df_tgt.columns)
    
    mappings = fuzzy_match_columns(src_cols, tgt_cols, threshold=70)
    print("\n📋 Suggested Column Mappings:")
    for k, (v, score) in mappings.items():
         print(f"  - {k} -> {v} (Confidence: {score}%)")
         
    # Convert mappings from (col, score) to plain string mapping
    column_mappings = {k: v for k, (v, _) in mappings.items()}
    
    # Simulating User overrides in UI for columns that RapidFuzz cannot match (e.g. item_id -> product_id)
    column_mappings["item_id"] = "product_id"
    column_mappings["qty_on_hand"] = "stock_qty"
    
    # 4. Auto-detect primary key (using correct mapping context)
    join_key_source = auto_detect_primary_key(df_src, df_tgt, column_mappings)
    join_key_target = column_mappings.get(join_key_source)
    print(f"\n🔑 Auto-detected Join Key (with corrected mappings): {join_key_source} -> {join_key_target}")
    
    assert join_key_source == "item_id", f"Expected join key to be 'item_id', got {join_key_source}"
    print("✅ Join key auto-detection assertions passed.")
    
    # 5. Reconciliation Engine Execution
    print("\n⚖️ Running reconciliation computations...")
    engine = ReconciliationEngine(
        df_source=df_src,
        df_target=df_tgt,
        source_key=join_key_source,
        target_key=join_key_target,
        column_mappings=column_mappings,
        float_tolerance=1e-4,
        ignore_casing=False,
        trim_whitespace=True
    )
    
    results = engine.execute()
    summary = results["summary"]
    
    print("\n📊 Reconciliation Results Summary:")
    for k, v in summary.items():
        print(f"  - {k}: {v}")
        
    # Assert values are as expected
    assert summary["source_row_count"] == 200, "Source count should be 200"
    # Target row count includes 200 - 4 (missing) + 2 (extra) + 2 (duplicates) = 200 rows.
    # Let's verify target rows:
    assert summary["target_row_count"] == 200, f"Target count should be 200, got {summary['target_row_count']}"
    assert summary["missing_count"] == 4, f"Missing rows should be 4, got {summary['missing_count']}"
    assert summary["extra_count"] == 2, f"Extra rows should be 2, got {summary['extra_count']}"
    assert summary["tgt_duplicates_count"] == 4, f"Target duplicates row count should be 4 (2 sets of duplicated keys), got {summary['tgt_duplicates_count']}"
    assert summary["value_mismatches_count"] > 0, "Should detect value mismatches"
    
    print("✅ Reconciliation metrics assertions passed.")
    
    # 6. Verify Excel report builder
    print("\n📦 Generating Excel report in memory...")
    excel_report_bytes = generate_excel_report(results, "source_inventory.csv", "target_warehouse_inventory.xlsx")
    print(f"✅ Excel Report byte length: {len(excel_report_bytes)} bytes.")
    assert len(excel_report_bytes) > 2000, "Excel file should be non-trivial size"
    print("✅ Excel report generation assertions passed.")
    
    # 7. Verify Rule-based Diagnostic output
    print("\n📝 Compiling rule-based diagnostics...")
    diagnostics = run_rule_based_analysis(results, log_text)
    print(diagnostics[:600] + "\n... [TRUNCATED] ...")
    
    assert "Row Mismatch" not in diagnostics, "Row count is equal (both are 200), so Row Mismatch should not be printed"
    assert "Data Loss" in diagnostics, "Should mention data loss / missing keys"
    assert "Phantom Records" in diagnostics, "Should mention phantom records"
    assert "Conversion warning" in diagnostics, "Should extract conversion warning from log"
    
    print("✅ Diagnostics reports assertions passed.")
    print("\n💯 All backend validation checks completed successfully! Ready for Streamlit execution.")

if __name__ == "__main__":
    main()
