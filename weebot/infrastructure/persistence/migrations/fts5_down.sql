-- FTS5 DOWN migration: remove event search virtual table
-- Run this if FTS5 indexing causes performance issues on large databases.
DROP TABLE IF EXISTS event_fts;
