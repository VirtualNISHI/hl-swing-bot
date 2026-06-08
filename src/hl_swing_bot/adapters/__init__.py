"""Read-only adapters that ingest sibling-project outputs into the feature store.

Each adapter reads another project's persisted output (never its code paths) and
maps it into hl-swing-bot's tall `features` table. Forward-only by default:
adapters only ingest records newer than what's already stored.
"""
