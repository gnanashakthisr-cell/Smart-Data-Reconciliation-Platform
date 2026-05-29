import re
from typing import Dict, List, Tuple
from rapidfuzz import process, fuzz

def normalize_name(name: str) -> str:
    """
    Normalize column names to improve matching accuracy.
    Converts to lowercase, removes special characters, spaces, and underscores.
    """
    if not isinstance(name, str):
        name = str(name)
    name = name.strip().lower()
    # Replace spaces, dashes, dots, and underscores with empty strings or spaces
    name = re.sub(r'[\s_\-\.]+', '', name)
    return name

def fuzzy_match_columns(
    source_cols: List[str], 
    target_cols: List[str], 
    threshold: float = 70.0
) -> Dict[str, Tuple[str, float]]:
    """
    Fuzzy matches source columns to target columns.
    
    Args:
        source_cols: List of column names from the source dataset.
        target_cols: List of column names from the target dataset.
        threshold: Score threshold (0-100) below which columns are not auto-mapped.
        
    Returns:
        A dictionary mapping source_column -> (target_column, similarity_score).
        If no target column meets the threshold, the value is (None, 0.0).
    """
    mappings: Dict[str, Tuple[str, float]] = {}
    
    # 1. Try case-insensitive exact matching first (after stripping whitespace)
    normalized_target_map = {normalize_name(tc): tc for tc in target_cols}
    matched_targets = set()
    
    for sc in source_cols:
        norm_sc = normalize_name(sc)
        if norm_sc in normalized_target_map:
            target_col = normalized_target_map[norm_sc]
            mappings[sc] = (target_col, 100.0)
            matched_targets.add(target_col)
            
    # 2. For remaining unmapped source columns, use RapidFuzz process
    unmapped_sources = [sc for sc in source_cols if sc not in mappings]
    available_targets = [tc for tc in target_cols if tc not in matched_targets]
    
    if not available_targets:
        # If all target columns are already matched, map the rest to None
        for sc in unmapped_sources:
            mappings[sc] = ("", 0.0)
        return mappings
        
    for sc in unmapped_sources:
        norm_sc = normalize_name(sc)
        # We perform fuzzy matching on normalized names, but we also try matching original names
        # process.extractOne uses WRatio by default which works well for variations
        best_match = None
        best_score = 0.0
        
        # Method A: Fuzzy match original names
        res_orig = process.extractOne(sc, available_targets, scorer=fuzz.WRatio)
        if res_orig:
            match_val_orig, score_orig, _ = res_orig
            best_match = match_val_orig
            best_score = score_orig
            
        # Method B: Fuzzy match normalized names (helps with cust_id -> customer_id if we check token sort)
        # We construct a map of normalized available targets
        norm_avail_targets = {normalize_name(tc): tc for tc in available_targets}
        res_norm = process.extractOne(norm_sc, list(norm_avail_targets.keys()), scorer=fuzz.token_sort_ratio)
        if res_norm:
            norm_match, score_norm, _ = res_norm
            # If normalized score is higher, we prefer it
            if score_norm > best_score:
                best_match = norm_avail_targets[norm_match]
                best_score = score_norm
                
        # If the best score is above our threshold, map it
        if best_score >= threshold and best_match:
            mappings[sc] = (best_match, round(best_score, 1))
            # We don't remove it from available_targets immediately to allow N:1 mappings if user has duplicates,
            # but usually schemas are 1:1. We can let the user adjust it in the UI.
        else:
            mappings[sc] = ("", 0.0)
            
    return mappings

def auto_detect_primary_key(
    df_source: 'pandas.DataFrame', 
    df_target: 'pandas.DataFrame', 
    mappings: Dict[str, str]
) -> str:
    """
    Inspects source columns and mapped target columns to suggest a likely Join/Primary Key.
    Checks common patterns: 'id', 'key', 'code', 'num', 'number', 'email', 'sku', etc.
    Validates if they are unique in source or target.
    """
    import pandas as pd
    
    possible_keys = []
    
    # 1. Search columns with 'id', 'key', 'code' in name (case-insensitive)
    patterns = [r'\bid\b', r'_id$', r'^id_', r'key', r'code', r'sku', r'uuid', r'email']
    
    for col in df_source.columns:
        col_str = str(col).lower()
        if any(re.search(pat, col_str) for pat in patterns):
            # Check if it has a valid mapping in the target
            target_col = mappings.get(col)
            if target_col and target_col in df_target.columns:
                possible_keys.append(col)
                
    # 2. Check uniqueness of candidates in source
    unique_candidates = []
    for col in possible_keys:
        if df_source[col].is_unique:
            unique_candidates.append(col)
            
    if unique_candidates:
        return unique_candidates[0]
        
    if possible_keys:
        return possible_keys[0]
        
    # 3. Fallback: Check if any column is unique in source and has target mapping
    for col in df_source.columns:
        target_col = mappings.get(col)
        if target_col and target_col in df_target.columns:
            if df_source[col].is_unique:
                return col
                
    # 4. Final fallback: return the first mapped column
    for col in df_source.columns:
        target_col = mappings.get(col)
        if target_col and target_col in df_target.columns:
            return col
            
    return ""
