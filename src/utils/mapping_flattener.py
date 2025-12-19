"""Utility to flatten Elasticsearch mappings and deduplicate fields."""

from typing import Dict, Any, Set

def flatten_mapping_fields(mapping: Dict[str, Any], prefix: str = "") -> Dict[str, str]:
    """
    Recursively flatten mapping properties to get field names and types.
    
    Args:
        mapping: Elasticsearch mapping properties
        prefix: Current field path prefix
        
    Returns:
        Dict of field_name -> field_type
    """
    fields = {}
    
    if not isinstance(mapping, dict):
        return fields
    
    for field_name, field_def in mapping.items():
        if not isinstance(field_def, dict):
            continue
            
        current_path = f"{prefix}.{field_name}" if prefix else field_name
        
        # Get field type
        field_type = field_def.get("type", "object")
        
        if field_type != "object":
            fields[current_path] = field_type
        
        # Recursively process nested properties
        if "properties" in field_def:
            nested_fields = flatten_mapping_fields(field_def["properties"], current_path)
            fields.update(nested_fields)
    
    return fields

def deduplicate_fields_across_indices(mappings: Dict[str, Any]) -> Dict[str, str]:
    """
    Flatten and deduplicate fields across multiple indices.
    
    Args:
        mappings: Dict of index_name -> mapping
        
    Returns:
        Dict of unique field_name -> field_type
    """
    all_fields = {}
    seen_fields: Set[str] = set()
    
    for index_name, mapping in mappings.items():
        if isinstance(mapping, dict) and "properties" in mapping:
            index_fields = flatten_mapping_fields(mapping["properties"])
            
            for field_name, field_type in index_fields.items():
                if field_name not in seen_fields:
                    all_fields[field_name] = field_type
                    seen_fields.add(field_name)
    
    return all_fields