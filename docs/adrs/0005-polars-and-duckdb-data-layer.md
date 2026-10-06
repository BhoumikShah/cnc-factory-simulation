# ADR 0005: Polars, DuckDB, and Parquet Persistence Architecture

## Status
Accepted

## Context
High-frequency discrete simulation runs generate hundreds of thousands of discrete state transitions. We need fast, zero-daemon persistence and analytical querying for KPIs and rule facts.

## Decision
1. **Event Streaming**: Events stream into an in-memory buffer or SQLite/DuckDB table.
2. **Analytical Aggregations**: DuckDB provides embedded SQL queries over columnar representations.
3. **High-Throughput Transformation**: Polars performs sub-second DataFrame transformations and exports to Apache Parquet for disk storage.

## Consequences
- **Positive**: Blazing analytical speed with zero external database setup.
- **Positive**: Parquet enables standard, highly compressed columnar archival.
- **Trade-off**: Polars/DuckDB bridge requires lightweight conversion to Pandas where legacy plotting/scikit-learn APIs require it.
