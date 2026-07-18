"""General geometry and semantic inference for statement tables."""

from ccparser.layout.columns import infer_column_bands, infer_column_roles
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableRegion, TableSchema
from ccparser.layout.regions import detect_table_regions, logical_rows
from ccparser.layout.rows import cluster_rows
from ccparser.layout.text import logical_text_for_bbox

__all__ = [
    "Cell",
    "ColumnRole",
    "ColumnSpec",
    "Row",
    "TableRegion",
    "TableSchema",
    "cluster_rows",
    "detect_table_regions",
    "infer_column_bands",
    "infer_column_roles",
    "logical_rows",
    "logical_text_for_bbox",
]
