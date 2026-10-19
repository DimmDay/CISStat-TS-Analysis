/** Shared wire DTO for file and database upload (apps/api/schemas.py). */
export interface ColumnInfoOut {
  name: string;
  dtype: string;
  type_icon: "numeric" | "datetime" | "categorical" | "text";
  non_null: number;
  nulls: number;
  unique: number;
}
export interface QualityTeaserOut {
  cols_with_missing: number;
  cols_with_outliers: number;
  rows_total: number;
  duplicates: number;
  missing_cols: string[];
  outlier_cols: string[];
}
export interface UploadApiResponse {
  dataset_id: string;
  name: string;
  rows: number;
  columns: number;
  preview: { head: string[][]; tail: string[][] };
  columns_info: ColumnInfoOut[] | null;
  quality: QualityTeaserOut | null;
  size_label: string | null;
  parse_warnings: string[];
  error?: string | null;
  detail?: string | { loc: (string | number)[]; msg: string; type: string }[];
  frequency?: string;
  domain?: string;
  n_series?: number;
  has_seasonality?: boolean;
  is_regular?: boolean;
}

/** UI metadata mirrors the canonical connector ids, not their aliases. */
export const DB_SOURCES = [
  { id: "postgresql", label: "PostgreSQL / Postgres Pro", port: 5432 },
  { id: "clickhouse", label: "ClickHouse", port: 8123 },
  { id: "mssql", label: "MS SQL Server", port: 1433 },
  { id: "mysql", label: "MySQL / MariaDB", port: 3306 },
  { id: "duckdb", label: "DuckDB (встроенная)", port: null },
  { id: "sqlite", label: "SQLite (встроенная)", port: null },
] as const;
export type DbKind = typeof DB_SOURCES[number]["id"];
