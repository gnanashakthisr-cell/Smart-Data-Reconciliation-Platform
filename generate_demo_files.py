import os
import pandas as pd
import numpy as np

def main():
    # Target directory for demo files
    demo_dir = "demo_files"
    os.makedirs(demo_dir, exist_ok=True)
    
    np.random.seed(100)
    size = 200
    
    # 1. Source Data
    source_df = pd.DataFrame({
        "item_id": [f"SKU-{1000 + i}" for i in range(size)],
        "vendor_code": [f"V-{np.random.randint(10, 99)}" for _ in range(size)],
        "retail_price": [round(float(np.random.uniform(1.0, 100.0)), 2) for _ in range(size)],
        "qty_on_hand": [np.random.randint(0, 500) for _ in range(size)],
        "expiry_date": [(pd.Timestamp("2027-01-01") + pd.Timedelta(days=np.random.randint(0, 365))).strftime("%Y-%m-%d") for _ in range(size)]
    })
    
    # Write source CSV
    src_path = os.path.join(demo_dir, "source_inventory.csv")
    source_df.to_csv(src_path, index=False)
    print(f"Created Source file: {src_path}")
    
    # 2. Target Data with ETL errors
    target_df = source_df.copy()
    
    # Rename columns (fuzzy mapping demo)
    target_df = target_df.rename(columns={
        "item_id": "product_id",
        "vendor_code": "vendor_ref",
        "retail_price": "price",
        "qty_on_hand": "stock_qty"
        # leave expiry_date as is
    })
    
    # Data type drift (e.g. stock_qty converted to floats)
    target_df["stock_qty"] = target_df["stock_qty"].astype(float)
    
    # Missing rows in target
    target_df = target_df.drop([10, 45, 99, 150]) # 4 missing rows
    
    # Extra rows in target
    extra_rows = [
        {"product_id": "SKU-9001", "vendor_ref": "V-12", "price": 49.99, "stock_qty": 100.0, "expiry_date": "2027-05-10"},
        {"product_id": "SKU-9002", "vendor_ref": "V-88", "price": 9.95, "stock_qty": 250.0, "expiry_date": "2027-08-14"}
    ]
    target_df = pd.concat([target_df, pd.DataFrame(extra_rows)], ignore_index=True)
    
    # Duplicates in target
    target_df = pd.concat([target_df, target_df.iloc[[20, 60]]], ignore_index=True)
    
    # Cell mismatches
    # A. Floating precision discrepancy
    target_df.loc[5, "price"] = target_df.loc[5, "price"] + 0.005 # rounding issue
    
    # B. Value change
    target_df.loc[12, "stock_qty"] = target_df.loc[12, "stock_qty"] - 5 # stock mismatch
    
    # C. Casing mismatch
    target_df.loc[30, "vendor_ref"] = target_df.loc[30, "vendor_ref"].lower() # "V-XX" to "v-xx"
    
    # Write target Excel
    tgt_path = os.path.join(demo_dir, "target_warehouse_inventory.xlsx")
    target_df.to_excel(tgt_path, index=False)
    print(f"Created Target file: {tgt_path}")
    
    # 3. ETL logs
    log_content = """[2026-05-28 19:00:00] INFO: Starting inventory synchronization pipeline 'sync_dwh_inventory'
[2026-05-28 19:00:01] INFO: Extraction source CSV completed. Count: 200 rows.
[2026-05-28 19:00:02] INFO: Running column mapper: item_id -> product_id, vendor_code -> vendor_ref, retail_price -> price, qty_on_hand -> stock_qty.
[2026-05-28 19:00:02] WARNING: Conversion warning: Integer 'qty_on_hand' cast to Double precision float in Snowflake destination column 'stock_qty'.
[2026-05-28 19:00:03] ERROR: Failed to insert product SKU-1010. Null constraint violation on non-nullable field 'location_id'. Row skipped.
[2026-05-28 19:00:03] ERROR: Failed to insert product SKU-1045. Null constraint violation on non-nullable field 'location_id'. Row skipped.
[2026-05-28 19:00:04] ERROR: Failed to insert product SKU-1099. Deadlock detected during warehouse transaction. Row skipped.
[2026-05-28 19:00:04] ERROR: Failed to insert product SKU-1150. Connection timeout while copying batch. Row skipped.
[2026-05-28 19:00:05] WARNING: Value mapping warning: Vendor code for record SKU-1030 was cast to lower-case 'v-xx' due to warehouse casing rule.
[2026-05-28 19:00:06] INFO: Completed write. 198 target records successfully stored (with 2 duplicates re-injected due to retry attempts).
[2026-05-28 19:00:07] INFO: Pipeline completed with 4 database write errors."""
    
    log_path = os.path.join(demo_dir, "inventory_etl.log")
    with open(log_path, "w") as f:
        f.write(log_content)
    print(f"Created Log file: {log_path}")

if __name__ == "__main__":
    main()
