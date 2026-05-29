import io
import datetime
import pandas as pd
from typing import Dict, Any
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

def generate_excel_report(
    results: Dict[str, Any], 
    source_name: str, 
    target_name: str
) -> bytes:
    """
    Generates a beautifully styled multi-tab Excel report containing reconciliation metrics
    and detailed lists of exceptions.
    
    Returns:
        Bytes containing the binary Excel workbook.
    """
    wb = Workbook()
    
    # Define styles
    font_family = "Segoe UI"
    title_font = Font(name=font_family, size=16, bold=True, color="1E293B")
    header_font = Font(name=font_family, size=11, bold=True, color="FFFFFF")
    data_font = Font(name=font_family, size=10)
    bold_data_font = Font(name=font_family, size=10, bold=True)
    kpi_val_font = Font(name=font_family, size=18, bold=True, color="1E3A8A")
    kpi_lbl_font = Font(name=font_family, size=9, bold=False, color="475569")
    
    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    stripe_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    
    # Soft alert fills
    red_fill = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid") # Soft red
    red_font = Font(name=font_family, size=10, color="991B1B")
    green_fill = PatternFill(start_color="D1FAE5", end_color="D1FAE5", fill_type="solid") # Soft green
    green_font = Font(name=font_family, size=10, color="065F46")
    yellow_fill = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid") # Soft yellow
    yellow_font = Font(name=font_family, size=10, color="92400E")
    
    thin_side = Side(border_style="thin", color="CBD5E1")
    border_all = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    double_bottom_border = Border(bottom=Side(border_style="double", color="1E293B"), top=Side(border_style="thin", color="CBD5E1"))
    
    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")
    
    # ----------------------------------------------------
    # TAB 1: SUMMARY DASHBOARD
    # ----------------------------------------------------
    ws_summary = wb.active
    ws_summary.title = "Summary Dashboard"
    ws_summary.views.sheetView[0].showGridLines = True
    
    # Report Title
    ws_summary["A1"] = "ETL DATA RECONCILIATION REPORT"
    ws_summary["A1"].font = title_font
    
    ws_summary["A2"] = f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    ws_summary["A2"].font = Font(name=font_family, size=10, italic=True, color="64748B")
    
    # File Metadata Table
    meta_headers = ["Metadata Attribute", "Value"]
    for col_idx, header in enumerate(meta_headers, start=1):
        cell = ws_summary.cell(row=4, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = align_left
        
    meta_data = [
        ["Source Dataset Name", source_name],
        ["Target Dataset Name", target_name],
        ["Reconciliation Rate", f"{results['summary']['reconciliation_rate']}%"],
        ["Execution Status", "COMPLETED WITH DISCREPANCIES" if results['summary']['total_issues'] > 0 else "FULLY RECONCILED"]
    ]
    
    for r_idx, (k, v) in enumerate(meta_data, start=5):
        cell_k = ws_summary.cell(row=r_idx, column=1, value=k)
        cell_v = ws_summary.cell(row=r_idx, column=2, value=v)
        cell_k.font = bold_data_font
        cell_v.font = data_font
        cell_k.border = border_all
        cell_v.border = border_all
        
        # Color code status
        if k == "Execution Status":
            if "FULLY" in v:
                cell_v.fill = green_fill
                cell_v.font = Font(name=font_family, size=10, bold=True, color="065F46")
            else:
                cell_v.fill = red_fill
                cell_v.font = Font(name=font_family, size=10, bold=True, color="991B1B")
        elif k == "Reconciliation Rate":
            rate_val = results['summary']['reconciliation_rate']
            if rate_val == 100.0:
                cell_v.fill = green_fill
                cell_v.font = Font(name=font_family, size=10, bold=True, color="065F46")
            elif rate_val > 95.0:
                cell_v.fill = yellow_fill
                cell_v.font = Font(name=font_family, size=10, bold=True, color="92400E")
            else:
                cell_v.fill = red_fill
                cell_v.font = Font(name=font_family, size=10, bold=True, color="991B1B")
                
    # KPI Metric Cards
    kpis = [
        ("SOURCE ROWS", results['summary']['source_row_count'], "A10:B11", None),
        ("TARGET ROWS", results['summary']['target_row_count'], "D10:E11", None),
        ("ROW DIFFERENCE", results['summary']['difference'], "G10:H11", yellow_fill if results['summary']['difference'] != 0 else green_fill),
        ("MISSING ROWS", results['summary']['missing_count'], "A13:B14", red_fill if results['summary']['missing_count'] > 0 else green_fill),
        ("EXTRA ROWS", results['summary']['extra_count'], "D13:E14", red_fill if results['summary']['extra_count'] > 0 else green_fill),
        ("VALUE MISMATCHES", results['summary']['value_mismatches_count'], "G13:H14", red_fill if results['summary']['value_mismatches_count'] > 0 else green_fill)
    ]
    
    for lbl, val, range_str, fill in kpis:
        # We write to the top left cell of the merged region
        start_cell_ref = range_str.split(":")[0]
        start_col = start_cell_ref[0]
        start_row = int(start_cell_ref[1:])
        
        # Write Title
        title_cell = ws_summary[f"{start_col}{start_row}"]
        title_cell.value = lbl
        title_cell.font = kpi_lbl_font
        title_cell.alignment = align_center
        
        # Write Value
        val_cell = ws_summary[f"{start_col}{start_row+1}"]
        val_cell.value = val
        val_cell.font = kpi_val_font
        val_cell.alignment = align_center
        
        # Apply borders & fills to all cells in range
        col_letters = range_str.translate(str.maketrans('', '', '1234567890')).split(":")
        row_nums = [int(x) for x in range_str.translate(str.maketrans('', '', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ')).split(":")]
        
        for col_let in [col_letters[0], chr(ord(col_letters[0])+1)]:
            for r in range(row_nums[0], row_nums[1]+1):
                c = ws_summary[f"{col_let}{r}"]
                c.border = border_all
                if fill:
                    c.fill = fill

    # ----------------------------------------------------
    # helper for adding sheets
    # ----------------------------------------------------
    def add_data_sheet(title: str, df: pd.DataFrame, is_exception_sheet: bool = False):
        if df is None:
            return
            
        ws = wb.create_sheet(title=title)
        ws.views.sheetView[0].showGridLines = True
        
        # Title of sheet
        ws["A1"] = f"{title.upper()} DETAIL"
        ws["A1"].font = title_font
        
        # Table Headers
        headers = list(df.columns)
        for col_idx, h in enumerate(headers, start=1):
            cell = ws.cell(row=3, column=col_idx, value=str(h))
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = align_left
            
        # Table Data
        for r_idx, row in enumerate(df.itertuples(index=False), start=4):
            for c_idx, val in enumerate(row, start=1):
                cell = ws.cell(row=r_idx, column=c_idx)
                
                # Format cell values nicely
                if pd.isna(val):
                    cell.value = "NULL"
                    cell.fill = stripe_fill
                    cell.font = Font(name=font_family, size=10, color="94A3B8")
                else:
                    cell.value = val
                    cell.font = data_font
                    
                cell.border = border_all
                
                # Highlight exception sheets or details
                if is_exception_sheet and title == "Value Mismatches":
                    # Highlight values specifically in Mismatch table
                    # Columns in value_mismatches: JoinKey, Source Column, Target Column, Source Value, Target Value, Source Value Str, Target Value Str, Reason
                    # Let's highlight Source Value (col 4) and Target Value (col 5) in light red
                    if c_idx in [4, 5]:
                        cell.fill = red_fill
                        cell.font = red_font
                    elif c_idx == 8: # Reason column
                        cell.fill = yellow_fill
                        cell.font = yellow_font
                elif is_exception_sheet:
                    # Highlight entire rows of missing or extra files
                    cell.fill = red_fill
                    cell.font = red_font

    # 2. Schema Issues Sheet
    schema_issues = results.get("schema_issues", [])
    if schema_issues:
        df_schema = pd.DataFrame(schema_issues)
        add_data_sheet("Schema Mismatches", df_schema, is_exception_sheet=True)
        
    # 3. Missing Records
    df_missing = results.get("missing_records")
    if df_missing is not None and not df_missing.empty:
        # Cap columns to avoid massive files, but export everything up to 100 columns
        add_data_sheet("Missing in Target", df_missing, is_exception_sheet=True)
        
    # 4. Extra Records
    df_extra = results.get("extra_records")
    if df_extra is not None and not df_extra.empty:
        add_data_sheet("Extra in Target", df_extra, is_exception_sheet=True)
        
    # 5. Value Mismatches
    df_mismatches = results.get("value_mismatches")
    if df_mismatches is not None and not df_mismatches.empty:
        add_data_sheet("Value Mismatches", df_mismatches, is_exception_sheet=True)
        
    # 6. Duplicates Detail
    df_src_dup = results.get("duplicates", {}).get("source")
    df_tgt_dup = results.get("duplicates", {}).get("target")
    
    if (df_src_dup is not None and not df_src_dup.empty) or (df_tgt_dup is not None and not df_tgt_dup.empty):
        ws_dup = wb.create_sheet("Duplicate Keys")
        ws_dup.views.sheetView[0].showGridLines = True
        ws_dup["A1"] = "DUPLICATE JOIN KEYS DETECTED"
        ws_dup["A1"].font = title_font
        
        row_offset = 3
        if df_src_dup is not None and not df_src_dup.empty:
            ws_dup.cell(row=row_offset, column=1, value="DUPLICATES IN SOURCE FILE").font = bold_data_font
            row_offset += 1
            for col_idx, col in enumerate(df_src_dup.columns, start=1):
                cell = ws_dup.cell(row=row_offset, column=col_idx, value=col)
                cell.font = header_font
                cell.fill = header_fill
                
            row_offset += 1
            for r_idx, row in enumerate(df_src_dup.itertuples(index=False), start=row_offset):
                for c_idx, val in enumerate(row, start=1):
                    c = ws_dup.cell(row=r_idx, column=c_idx, value=str(val) if not pd.isna(val) else "NULL")
                    c.font = data_font
                    c.fill = yellow_fill
                    c.border = border_all
                row_offset += 1
                
        row_offset += 2
        if df_tgt_dup is not None and not df_tgt_dup.empty:
            ws_dup.cell(row=row_offset, column=1, value="DUPLICATES IN TARGET FILE").font = bold_data_font
            row_offset += 1
            for col_idx, col in enumerate(df_tgt_dup.columns, start=1):
                cell = ws_dup.cell(row=row_offset, column=col_idx, value=col)
                cell.font = header_font
                cell.fill = header_fill
                
            row_offset += 1
            for r_idx, row in enumerate(df_tgt_dup.itertuples(index=False), start=row_offset):
                for c_idx, val in enumerate(row, start=1):
                    c = ws_dup.cell(row=r_idx, column=c_idx, value=str(val) if not pd.isna(val) else "NULL")
                    c.font = data_font
                    c.fill = yellow_fill
                    c.border = border_all
                row_offset += 1

    # Auto-adjust column widths across all sheets for visual elegance
    for sheet in wb.worksheets:
        for col in sheet.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            
            for cell in col:
                # Avoid calculating merged cell height or massive formulas
                if cell.coordinate in ['A1', 'A2'] and sheet.title == "Summary Dashboard":
                    continue
                if cell.value:
                    val_str = str(cell.value)
                    if len(val_str) > max_len:
                        max_len = len(val_str)
            
            # Add safety margin
            sheet.column_dimensions[col_letter].width = min(max(max_len + 3, 10), 50)
            
    # Save to buffer
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
