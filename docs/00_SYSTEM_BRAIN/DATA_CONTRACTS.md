# Data Contracts

## OHLCV Schema

* Required columns: Open, High, Low, Close, Volume
* Index: trading date/time aligned to provider convention
* No future data leakage: all derived values must be computed using only past data.

## Missing Data Policy

* If required bars are missing or invalid for the run window: fail fast (no silent fill).
* Any explicit fill/interpolation must be documented and deterministic.

## Timezones / Calendars

* The system uses provider-native timestamps; normalization behavior is as implemented in DataAgent.
* Trading calendar/holidays are inherited from the data provider output.
