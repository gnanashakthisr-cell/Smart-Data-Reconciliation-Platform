import pandas as pd
import numpy as np
from typing import Dict, List, Any, Tuple, Optional

class ReconciliationEngine:
    def __init__(
        self,
        df_source: pd.DataFrame,
        df_target: pd.DataFrame,
        source_key: str,
        target_key: str,
        column_mappings: Dict[str, str],  # source_col -> target_col
        float_tolerance: float = 1e-4,
        ignore_casing: bool = False,
        trim_whitespace: bool = True
    ):
        # Create copies to prevent modifying user's dataframes
        self.df_source = df_source.copy()
        self.df_target = df_target.copy()
        
        self.source_key = source_key
        self.target_key = target_key
        
        # Clean mappings: remove empty target columns
        self.column_mappings = {k: v for k, v in column_mappings.items() if v}
        
        self.float_tolerance = float_tolerance
        self.ignore_casing = ignore_casing
        self.trim_whitespace = trim_whitespace
        
        # Results container
        self.results = {}

    def execute(self) -> Dict[str, Any]:
        """
        Executes all reconciliation checks.
        """
        # 1. Clean key columns (handle NaN and convert to string for robust joining)
        self._prepare_keys()
        
        # 2. Row counts
        src_row_count = len(self.df_source)
        tgt_row_count = len(self.df_target)
        
        # 3. Schema & Datatype checks
        schema_issues = self._check_schema_and_types()
        
        # 4. Duplicate checks
        src_duplicates, tgt_duplicates = self._check_duplicates()
        
        # 5. Record alignment and partitioning (Missing vs Extra)
        missing_records, extra_records, common_src, common_tgt = self._align_records()
        
        # 6. Value-level reconciliation
        value_mismatches, match_count, compared_count = self._compare_values(common_src, common_tgt)
        
        # Compute overall stats
        total_issues = (
            len(schema_issues) + 
            len(src_duplicates) + 
            len(tgt_duplicates) + 
            len(missing_records) + 
            len(extra_records) + 
            len(value_mismatches)
        )
        
        # Calculate reconciliation rate (percentage of matched keys that have zero value mismatches)
        aligned_keys_count = len(common_src)
        mismatched_keys_count = value_mismatches[self.source_key].nunique() if len(value_mismatches) > 0 else 0
        perfect_match_count = aligned_keys_count - mismatched_keys_count
        
        reconciliation_rate = 100.0
        if src_row_count > 0:
            reconciliation_rate = (perfect_match_count / src_row_count) * 100.0
        
        self.results = {
            "summary": {
                "source_row_count": src_row_count,
                "target_row_count": tgt_row_count,
                "difference": tgt_row_count - src_row_count,
                "reconciliation_rate": round(reconciliation_rate, 2),
                "total_issues": total_issues,
                "missing_count": len(missing_records),
                "extra_count": len(extra_records),
                "src_duplicates_count": len(src_duplicates),
                "tgt_duplicates_count": len(tgt_duplicates),
                "value_mismatches_count": len(value_mismatches),
                "schema_issues_count": len(schema_issues)
            },
            "schema_issues": schema_issues,
            "duplicates": {
                "source": src_duplicates,
                "target": tgt_duplicates
            },
            "missing_records": missing_records,
            "extra_records": extra_records,
            "value_mismatches": value_mismatches,
            "compared_rows_count": compared_count,
            "matched_rows_count": perfect_match_count
        }
        
        return self.results

    def _prepare_keys(self):
        """
        Converts the primary/join key columns to consistent string formats,
        removing spaces and handling NaNs to ensure stable joins.
        """
        # Ensure keys exist
        if self.source_key not in self.df_source.columns:
            raise ValueError(f"Source key '{self.source_key}' not found in source dataframe.")
        if self.target_key not in self.df_target.columns:
            raise ValueError(f"Target key '{self.target_key}' not found in target dataframe.")
            
        # Convert to string, strip, and replace NaNs with empty string
        for df, key in [(self.df_source, self.source_key), (self.df_target, self.target_key)]:
            # Fill NaN values in the key column
            df[key] = df[key].fillna("MISSING_KEY")
            # Convert to string and strip
            df[key] = df[key].astype(str).str.strip()

    def _check_schema_and_types(self) -> List[Dict[str, Any]]:
        """
        Validates mapped column data types.
        """
        issues = []
        
        for src_col, tgt_col in self.column_mappings.items():
            if src_col not in self.df_source.columns:
                issues.append({
                    "column": src_col,
                    "issue_type": "Missing Source Column",
                    "severity": "High",
                    "detail": f"Column '{src_col}' mapped but not found in source dataset."
                })
                continue
                
            if tgt_col not in self.df_target.columns:
                issues.append({
                    "column": tgt_col,
                    "issue_type": "Missing Target Column",
                    "severity": "High",
                    "detail": f"Column '{tgt_col}' mapped but not found in target dataset."
                })
                continue
                
            # Compare data types
            src_dtype = str(self.df_source[src_col].dtype)
            tgt_dtype = str(self.df_target[tgt_col].dtype)
            
            # Simple check for basic compatibility (numeric vs text vs date vs boolean)
            src_is_num = any(x in src_dtype for x in ['int', 'float', 'double', 'decimal'])
            tgt_is_num = any(x in tgt_dtype for x in ['int', 'float', 'double', 'decimal'])
            
            src_is_date = 'datetime' in src_dtype or 'date' in src_dtype
            tgt_is_date = 'datetime' in tgt_dtype or 'date' in tgt_dtype
            
            src_is_bool = 'bool' in src_dtype
            tgt_is_bool = 'bool' in tgt_dtype
            
            type_mismatch = False
            if src_is_num != tgt_is_num:
                type_mismatch = True
            elif src_is_date != tgt_is_date:
                type_mismatch = True
            elif src_is_bool != tgt_is_bool:
                type_mismatch = True
                
            if type_mismatch:
                issues.append({
                    "source_column": src_col,
                    "target_column": tgt_col,
                    "issue_type": "Datatype Mismatch",
                    "severity": "Medium",
                    "detail": f"Source column '{src_col}' ({src_dtype}) is incompatible with target column '{tgt_col}' ({tgt_dtype})."
                })
                
        return issues

    def _check_duplicates(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Checks for duplicate join keys in source and target datasets.
        """
        # Find duplicates
        src_dups_mask = self.df_source.duplicated(subset=[self.source_key], keep=False)
        tgt_dups_mask = self.df_target.duplicated(subset=[self.target_key], keep=False)
        
        src_duplicates = self.df_source[src_dups_mask].sort_values(by=self.source_key)
        tgt_duplicates = self.df_target[tgt_dups_mask].sort_values(by=self.target_key)
        
        return src_duplicates, tgt_duplicates

    def _align_records(self) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Partitions records based on the join key into:
        - Missing in target (present in source only)
        - Extra in target (present in target only)
        - Common to both (aligned for row-level verification)
        """
        # Remove duplicates from the alignment process to prevent cross-join explosions,
        # but keep them in the copies we align.
        # We perform matching based on the first occurrence of duplicate keys,
        # or we just perform a direct match. The safest for reconciliation is to align unique keys.
        src_keys = set(self.df_source[self.source_key])
        tgt_keys = set(self.df_target[self.target_key])
        
        missing_keys = src_keys - tgt_keys
        extra_keys = tgt_keys - src_keys
        common_keys = src_keys & tgt_keys
        
        # Missing records dataframe
        missing_records = self.df_source[self.df_source[self.source_key].isin(missing_keys)].copy()
        
        # Extra records dataframe
        extra_records = self.df_target[self.df_target[self.target_key].isin(extra_keys)].copy()
        
        # For value-level reconciliation, we only use rows with common keys.
        # If there are duplicates, we only keep the first occurrence to avoid key ambiguity during row-by-row checks
        common_src = self.df_source[self.df_source[self.source_key].isin(common_keys)].drop_duplicates(subset=[self.source_key], keep='first')
        common_tgt = self.df_target[self.df_target[self.target_key].isin(common_keys)].drop_duplicates(subset=[self.target_key], keep='first')
        
        # Sort both by key to ensure direct index-wise comparison after aligning
        common_src = common_src.sort_values(by=self.source_key).reset_index(drop=True)
        common_tgt = common_tgt.sort_values(by=self.target_key).reset_index(drop=True)
        
        return missing_records, extra_records, common_src, common_tgt

    def _compare_values(
        self, 
        df_src: pd.DataFrame, 
        df_tgt: pd.DataFrame
    ) -> Tuple[pd.DataFrame, int, int]:
        """
        Compares cells row-by-row, column-by-column for common rows.
        """
        mismatches = []
        compared_count = len(df_src)
        match_count = 0
        
        if compared_count == 0:
            return pd.DataFrame(), 0, 0
            
        for idx in range(compared_count):
            row_src = df_src.iloc[idx]
            row_tgt = df_tgt.iloc[idx]
            
            key_val = row_src[self.source_key]
            row_has_mismatch = False
            
            for src_col, tgt_col in self.column_mappings.items():
                # Skip the primary key if it's in the mapping (already verified equal by design)
                if src_col == self.source_key:
                    continue
                    
                val_src = row_src.get(src_col)
                val_tgt = row_tgt.get(tgt_col)
                
                # Check mismatch
                is_mismatched = self._is_value_mismatched(val_src, val_tgt)
                
                if is_mismatched:
                    row_has_mismatch = True
                    mismatches.append({
                        self.source_key: key_val,
                        "source_column": src_col,
                        "target_column": tgt_col,
                        "source_value": val_src,
                        "target_value": val_tgt,
                        "source_value_str": str(val_src),
                        "target_value_str": str(val_tgt),
                        "reason": self._get_mismatch_reason(val_src, val_tgt)
                    })
                    
            if not row_has_mismatch:
                match_count += 1
                
        value_mismatches_df = pd.DataFrame(mismatches)
        
        return value_mismatches_df, match_count, compared_count

    def _is_value_mismatched(self, val_src: Any, val_tgt: Any) -> bool:
        """
        Determines whether two cell values are mismatched based on type-aware logic and tolerances.
        """
        # Handle both being null/NaN
        src_null = pd.isna(val_src) or val_src is None or str(val_src).strip().lower() in ['nan', 'none', 'null', '']
        tgt_null = pd.isna(val_tgt) or val_tgt is None or str(val_tgt).strip().lower() in ['nan', 'none', 'null', '']
        
        if src_null and tgt_null:
            return False  # Both are null, so they reconcile
        if src_null != tgt_null:
            return True   # One is null and the other is not
            
        # Float comparisons with tolerance
        try:
            float_src = float(val_src)
            float_tgt = float(val_tgt)
            # If successfully cast to floats, compare within tolerance
            return abs(float_src - float_tgt) > self.float_tolerance
        except (ValueError, TypeError):
            pass
            
        # Datetime comparisons
        try:
            # Check if columns could be dates, parse them
            date_src = pd.to_datetime(val_src, errors='raise')
            date_tgt = pd.to_datetime(val_tgt, errors='raise')
            return date_src != date_tgt
        except (ValueError, TypeError, OverflowError):
            pass
            
        # Fallback to string comparison
        str_src = str(val_src)
        str_tgt = str(val_tgt)
        
        if self.trim_whitespace:
            str_src = str_src.strip()
            str_tgt = str_tgt.strip()
            
        if self.ignore_casing:
            str_src = str_src.lower()
            str_tgt = str_tgt.lower()
            
        return str_src != str_tgt

    def _get_mismatch_reason(self, val_src: Any, val_tgt: Any) -> str:
        """
        Deterministic diagnostic of why two values are mismatched.
        """
        src_null = pd.isna(val_src) or val_src is None or str(val_src).strip().lower() in ['nan', 'none', 'null', '']
        tgt_null = pd.isna(val_tgt) or val_tgt is None or str(val_tgt).strip().lower() in ['nan', 'none', 'null', '']
        
        if src_null and not tgt_null:
            return "Null in Source, Value in Target"
        if not src_null and tgt_null:
            return "Value in Source, Null in Target"
            
        try:
            float_src = float(val_src)
            float_tgt = float(val_tgt)
            diff = abs(float_src - float_tgt)
            if diff > self.float_tolerance:
                return f"Numeric difference ({diff:.6f} > tolerance)"
        except (ValueError, TypeError):
            pass
            
        # Check for length truncation
        str_src = str(val_src)
        str_tgt = str(val_tgt)
        if len(str_src) > len(str_tgt) and str_src.startswith(str_tgt):
            return f"Possible Truncation (Target length {len(str_tgt)} vs Source {len(str_src)})"
            
        # Check casing differences
        if str_src.lower() == str_tgt.lower():
            return "Case Mismatch Only"
            
        # Check leading/trailing spaces
        if str_src.strip() == str_tgt.strip():
            return "Whitespace Mismatch Only"
            
        return "Value Difference"
