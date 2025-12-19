"""CSV handling utilities for large query results."""

import csv
import os
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
import uuid

from src.utils.logger import get_logger

logger = get_logger("csv_handler")

async def save_query_result_to_csv(query_result: Dict[str, Any], user_query: str) -> Optional[str]:
    """
    Save query result to CSV file and return file path.
    
    Args:
        query_result: The tabular data from ES|QL execution
        user_query: Original user query for filename
        
    Returns:
        File path if successful, None if failed
    """
    if not query_result or not query_result.get("columns") or not query_result.get("values"):
        return None
    
    def _write_csv():
        # Create exports directory if it doesn't exist
        exports_dir = "/tmp/es_agent_exports"
        os.makedirs(exports_dir, exist_ok=True)
        
        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        query_hash = str(uuid.uuid4())[:8]
        filename = f"query_result_{timestamp}_{query_hash}.csv"
        file_path = os.path.join(exports_dir, filename)
        
        # Extract column names
        columns = query_result["columns"]
        column_names = [col["name"] if isinstance(col, dict) else str(col) for col in columns]
        
        # Write CSV
        with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            
            # Write header
            writer.writerow(column_names)
            
            # Write data rows
            for row in query_result["values"]:
                # Handle None values and ensure all values are strings
                formatted_row = [str(val) if val is not None else "" for val in row]
                writer.writerow(formatted_row)
        
        return file_path
    
    try:
        file_path = await asyncio.to_thread(_write_csv)
        logger.info(f"Saved {len(query_result['values'])} rows to {file_path}")
        return file_path
        
    except Exception as e:
        logger.error(f"Failed to save CSV: {e}")
        return None

def generate_download_url(file_path: str) -> str:
    """Generate a download URL for the CSV file."""
    if not file_path:
        return ""
    
    filename = os.path.basename(file_path)
    # In a real deployment, this would be a proper URL
    # For now, return the file path as a placeholder
    return f"file://{file_path}"

def get_csv_summary(file_path: str) -> Dict[str, Any]:
    """Get summary information about the CSV file."""
    if not file_path or not os.path.exists(file_path):
        return {}
    
    try:
        file_size = os.path.getsize(file_path)
        
        # Count rows (excluding header)
        with open(file_path, 'r', encoding='utf-8') as f:
            row_count = sum(1 for _ in f) - 1  # Subtract header
        
        return {
            "file_size_bytes": file_size,
            "file_size_mb": round(file_size / (1024 * 1024), 2),
            "row_count": row_count,
            "filename": os.path.basename(file_path)
        }
    except Exception as e:
        logger.error(f"Failed to get CSV summary: {e}")
        return {}