"""Per-route harvest adapters.

Each adapter exposes:

- a pure `normalise_*` function that maps one native record to a
  `HarvestedDataset` (offline-testable, no network), and
- a `harvest(config, *, fetcher, on_raw_page, max_pages)` generator that
  drives the portal's pagination, yields normalised datasets, and hands
  each raw page to `on_raw_page` for the disk cache.

The generator takes an injectable `fetcher` so the pagination logic can be
tested offline with canned pages.
"""
