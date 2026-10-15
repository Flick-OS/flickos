-- FlickOS weekly count: requests per ISO week, FlickOS version and age
-- bucket. Nothing else is stored (no address, no user agent, no time of day).
CREATE TABLE IF NOT EXISTS counts (
    week    TEXT    NOT NULL,   -- ISO week (UTC), e.g. 2026-W39
    version TEXT    NOT NULL,   -- FLICKOS_VERSION, e.g. 2.0
    age     INTEGER NOT NULL,   -- 1 first week, 2 first month, 3 first half year, 4 longer
    n       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (week, version, age)
);
