# Stratum — Test Inventory

## Why This File Exists

Not a general-purpose nice-to-have. This exists because a specific failure pattern has recurred multiple times on this project: a test that runs and passes without actually exercising the risky path it claims to cover, or test coverage narrowing silently while the overall pass/fail signal stays green. Concrete instances already on record: three previously-passing invariant tests (duplicate-key detection, truncated-file detection, `scan()` type-checking) were commented out during a constructor-signature refactor and never migrated back; a tmp-file-cleanup assertion checked a path that was never correct even under the bug it claimed to guard against, so it passed regardless of whether the bug was present.

**Rule going forward: if a test file changes, this file changes in the same sitting.** A test removed, renamed, or commented out without an explanation recorded here is treated the same as an undocumented scope cut — not acceptable, even under deadline pressure. If a test is deliberately removed (e.g., made obsolete by a redesign), say so here, with the reason, rather than letting it silently vanish.

This file records _what each test is supposed to prove_, not the code itself — read the actual test file for exact assertions. If the two disagree (a test exists here that isn't in the file, or vice versa), that mismatch is itself the bug to chase down first, before touching anything else.

---

## SSTable — File Format & Flush

| Test                                                             | What it proves                                                                                                                 |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `test_flush_rejects_non_path_path_argument`                      | `flush()` fails loud (`TypeError`) on a non-`Path` argument — boundary enforcement, not silent coercion.                       |
| `test_flush_empty_memtable_creates_empty_sstable_file`           | Zero-entry flush produces a real, valid (empty) file pair, not a crash or a skipped write.                                     |
| `test_flush_single_entry_sets_min_max_equal_and_returns_sstable` | `min_key`/`max_key` correctly collapse to the same value for a single-entry table.                                             |
| `test_flush_multiple_entries_writes_records_in_sorted_key_order` | Entries land on disk in the order given (callers are responsible for pre-sorting; flush doesn't re-sort).                      |
| `test_flush_writes_tombstone_byte_for_deleted_entries`           | The `deleted` flag round-trips correctly through the binary format.                                                            |
| `test_flush_removes_tmp_file_and_creates_final_sstable`          | Final `.sst` and `.idx` paths remain in the requested `table_dir`, and both temporary files are absent after the atomic flush. |
| `test_sstable_flush_empty_memtable_items_produces_empty_table`   | `search()` on an empty table returns `[]` cleanly — no crash, no `IndexError` from bisecting an empty sample list.             |
| `test_sstable_single_entry_round_trips_through_from_file`        | Flush → reload → search all agree for the minimal non-empty case.                                                              |

## SSTable — Bloom Filter & Empty-Flush Edge Cases

| Test                                                                            | What it proves                                                                                                                                                                                                                                                        |
| ------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_bloom_might_contain_returns_true_for_added_key`                           | A key added to a BloomFilter is later reported as present.                                                                                                                                                                                                            |
| `test_bloom_might_contain_returns_false_for_key_never_added`                    | A non-inserted key is not reported as present under normal conditions.                                                                                                                                                                                                |
| `test_bloom_false_positive_rate_stays_near_target_at_scale`                     | Scale check for Bloom false-positive behavior against the target FPR.                                                                                                                                                                                                 |
| `test_bloom_for_size_zero_entries_does_not_crash`                               | Directly covers the `n == 0` edge case for `BloomFilter.for_size()` and ensures it returns a valid object rather than raising `ZeroDivisionError`.                                                                                                                    |
| `test_bloom_for_size_produces_sane_m_and_k`                                     | `m` and `k` are sane and positive for a non-empty filter.                                                                                                                                                                                                             |
| `test_bloom_restore_filter_matches_original_on_same_keys`                       | Round-tripped filter state preserves key membership.                                                                                                                                                                                                                  |
| `test_bloom_add_is_idempotent`                                                  | Re-adding the same key does not mutate the bitset away from its original state.                                                                                                                                                                                       |
| `test_flush_bloom_filter_contains_all_flushed_keys`                             | A flushed SSTable's Bloom filter contains all flushed keys.                                                                                                                                                                                                           |
| `test_flush_empty_memtable_bloom_filter_does_not_crash`                         | The empty-flush path produces a usable `BloomFilter` object, not just a non-crashing flush. It explicitly inspects `bloom_filter` state (`isinstance`, `filter_length == bits_number`) and `might_contain()` behavior.                                                |
| `test_from_file_bloom_filter_matches_pre_flush_membership`                      | Bloom membership survives a flush→reload cycle.                                                                                                                                                                                                                       |
| `test_from_file_bloom_filter_m_k_survive_round_trip`                            | Critical round-trip integrity check: asserts `reloaded.bloom_filter.bits_number == sstable.bloom_filter.bits_number`, `hashes_number` equality, and `filter` byte equality directly. This is the separate guard against false positives masking a wrong `m`/`k` pair. |
| `test_sstable_bloom_filter_footer_does_not_corrupt_sample_index_read`           | The stored Bloom filter footer is placed after the data payload without corrupting the sample-index read logic during reload.                                                                                                                                         |
| `test_engine_get_skips_search_on_bloom_negative_key`                            | `Engine.get()` short-circuits table search when Bloom says the key is absent.                                                                                                                                                                                         |
| `test_engine_get_does_not_skip_search_on_bloom_positive_key`                    | `Engine.get()` still does the real search when Bloom says the key may be present.                                                                                                                                                                                     |
| `test_engine_get_correctness_unaffected_by_bloom_filter_across_multiple_tables` | Bloom false negatives/false positives do not alter correctness across multi-table reads.                                                                                                                                                                              |

## SSTable — Sparse Index Sampling

| Test                                                                        | What it proves                                                                                                                     |
| --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `test_sstable_samples_at_the_1000th_entry_boundary`                         | Entry 0 and entry 1000 are both sampled at a 1000-entry table — confirms entry-0-always-sampled plus the interval boundary itself. |
| `test_sstable_samples_only_once_for_999_entries_and_twice_for_1001_entries` | Off-by-one correctness at the interval edge in both directions (just under, just over).                                            |

## SSTable — `search()` (indexed point lookup)

| Test                                                                  | What it proves                                                                                                                 |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `test_sstable_search_for_sampled_key_returns_the_exact_entry`         | Bisect lands exactly on a sampled key with no off-by-one.                                                                      |
| `test_sstable_search_between_samples_uses_the_correct_offset`         | The forward scan from a resolved offset actually reaches a target that isn't itself sampled.                                   |
| `test_sstable_search_for_missing_key_between_real_keys_returns_empty` | The overshoot `break` fires correctly on a genuine miss — no scan to EOF.                                                      |
| `test_sstable_search_out_of_range_returns_empty_without_crashing`     | Targets below the lowest key and above the highest key both resolve safely, including the below-first-sample bisect edge case. |

## SSTable — `scan()` (range scan, used directly by `compact()`)

| Test                                                                                                                                                                                                                                                                                                                                                                        | What it proves                                                                                                                                                                                                                                                                                   |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `test_scan_full_range_round_trips_flushed_records`                                                                                                                                                                                                                                                                                                                          | A full min→max scan returns every entry, in order.                                                                                                                                                                                                                                               |
| `test_scan_narrow_range_excludes_out_of_range_entries`                                                                                                                                                                                                                                                                                                                      | Range bounds are respected, not just used as a post-filter after a full read.                                                                                                                                                                                                                    |
| `test_scan_omits_deleted_records_in_range` — _(confirm current name/assertion; `scan()`'s actual contract is to return tombstones untouched per `STRATUM_PROJECT.md`, with `Engine.get()` responsible for stopping at the first hit — if this test's name and behavior disagree with that documented contract, that mismatch is a real bug to chase, not a naming nitpick._ | Tombstone handling within a range scan.                                                                                                                                                                                                                                                          |
| `test_scan_rejects_non_bytes_start_and_end_keys`                                                                                                                                                                                                                                                                                                                            | Boundary type enforcement (`bytes`-only), matching every other component's fail-loud pattern.                                                                                                                                                                                                    |
| `test_scan_returns_empty_list_for_fully_out_of_range_query`                                                                                                                                                                                                                                                                                                                 | A query range that overlaps nothing returns `[]`, not an error.                                                                                                                                                                                                                                  |
| `test_scan_raises_on_duplicate_keys_in_sstable_file`                                                                                                                                                                                                                                                                                                                        | **Reactivated this phase after being silently dropped — the exact failure pattern this file exists to prevent.** Confirms `read_entries()`'s duplicate-key integrity check still fires when a hand-corrupted file is fed through `scan()`, under the current footer-aware constructor signature. |
| `test_scan_raises_on_truncated_sstable_file`                                                                                                                                                                                                                                                                                                                                | **Reactivated this phase, same as above.** Confirms truncation is still caught, not silently accepted as EOF.                                                                                                                                                                                    |

## SSTable — `from_file()` (restart / reload path)

| Test                                                       | What it proves                                                                          |
| ---------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `test_sstable_from_file_round_trip_preserves_metadata`     | `min_key`/`max_key`/`indexes`/`index_start` all survive a flush→reload cycle unchanged. |
| `test_sstable_from_file_raises_for_corrupt_idx_file`       | A hand-corrupted `.idx` sidecar fails loud, not silently.                               |
| `test_sstable_from_file_exists_and_loads_sstable_metadata` | Basic reload sanity check, redundant with the round-trip test above but cheap to keep.  |

## SSTable — Crash Safety

| Test                                                               | What it proves                                                                                                                                                                                                                                                                        |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_sstable_flush_commits_idx_before_sstable_when_replace_fails` | Mocked `os.replace` failure specifically on the `.sst` commit confirms `.idx` survives on disk while `.sst` does not — direct evidence for the documented `.idx`-before-`.sst` commit ordering claim. Not a live kill — same rigor precedent as Phase 3's mocked-unlink-failure test. |

## Engine — Load & Boundary Enforcement

| Test                                                           | What it proves                                                                                                                   |
| -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `test_engine_load_sstables_raises_when_idx_sidecar_is_missing` | `_load_sstables()` fails loud on an orphaned `.sst` with no matching `.idx`, rather than silently skipping or misaligning pairs. |

## Engine — Read Path

| Test                                                                                                        | What it proves                                                                                                                                                                                               |
| ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `test_engine_get_returns_memtable_value_without_flushing`                                                   | The fast path (memtable hit, no disk touched) still works — hasn't regressed from all the SSTable-side changes.                                                                                              |
| `test_engine_get_reads_key_from_sstable_after_flush`                                                        | `Engine.get()` correctly falls through to `search()` once a key is only on disk.                                                                                                                             |
| `test_engine_get_returns_none_for_tombstone_over_sstable_value`                                             | A tombstone correctly shadows an older on-disk value within a single engine session.                                                                                                                         |
| `test_engine_get_returns_tombstone_value_when_newer_sstable_has_tombstone_and_older_sstable_has_live_value` | Same shadowing guarantee across _two separate SSTable files_, not just memtable-over-disk — this is the cross-table case that actually exercises `Engine.get()`'s reverse-iteration-stop-at-first-hit logic. |

## Engine — `scan()` Cross-Source Resolution

| Test                                                | What it proves                                                                                                                 |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `test_scan_suppresses_live_tombstone`               | A memtable tombstone suppresses a live value in an SSTable.                                                                    |
| `test_scan_suppresses_flushed_tombstone`            | A tombstone in the same SSTable as the older live value is filtered from the scan.                                             |
| `test_scan_suppresses_tombstone_from_newer_sstable` | A tombstone in a newer SSTable suppresses the live value in an older SSTable through `scan()`'s merge-by-sequence-number path. |

## gRPC — Streaming API

| Test                                                  | What it proves                                                                                                              |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `test_put_then_get_round_trip`                        | `Put` followed by `Get` preserves key/value bytes over an in-process RPC server.                                            |
| `test_get_missing_key_returns_not_found_result`       | A missing key is a successful RPC (`OK`) with `found=false`, matching the response schema rather than using a status error. |
| `test_put_empty_key_returns_invalid_argument`         | The servicer rejects proto3's unset/empty `Put` key at the API boundary with `INVALID_ARGUMENT`.                          |
| `test_get_empty_key_returns_invalid_argument`         | The servicer rejects proto3's unset/empty `Get` key at the API boundary with `INVALID_ARGUMENT`.                          |
| `test_scan_returns_multiple_results_in_key_order`     | Streaming `Scan` returns all results in ascending key order.                                                                |
| `test_scan_empty_range_returns_no_results`            | A valid range with no matching keys yields an empty stream.                                                                 |
| `test_scan_start_after_end_returns_no_results`        | A reversed range yields an empty stream.                                                                                    |
| `test_scan_empty_bound_returns_invalid_argument`      | The servicer rejects an omitted/empty inclusive `start_key` or `end_key` with `INVALID_ARGUMENT`.                          |
| `test_scan_omits_tombstoned_key`                      | A tombstoned key does not appear in the RPC stream.                                                                         |
| `test_malformed_wire_request_returns_internal_status` | Invalid protobuf wire bytes are rejected by gRPC before the servicer and return `INTERNAL`.                                 |
| `test_non_bytes_request_field_is_rejected_before_rpc` | The protobuf client rejects non-bytes fields locally; the invalid value cannot reach the engine over the wire.              |

## Engine — Restart / Persistence

| Test                                                                | What it proves                                                                                                                                                                                             |
| ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_engine_restart_round_trip_preserves_expected_values`          | A fresh `Engine` instance against the same `data_dir` reproduces pre-restart `get()` results, including a delete.                                                                                          |
| `test_engine_restart_shadowing_prefers_newest_sstable_after_reload` | Newest-write-wins is preserved specifically _across_ a restart, not just in-process.                                                                                                                       |
| `test_engine_handles_thousands_of_writes_and_restarts`              | Scale/volume check — 60,000 writes, multiple flush cycles, full restart, every key re-verified. Also asserts the expected SSTable file count, which doubles as a regression check on flush-threshold math. |

## Engine — Compaction

| Test                                                                                      | What it proves                                                                                                                                                                                        |
| ----------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_engine_compact_all_tombstones_leaves_deleted_keys_unavailable`                      | Compacting a fully-deleted key set produces a zero-entry table and `get()` still resolves correctly against it (exercises the empty-index path end-to-end, not just at the isolated `SSTable` level). |
| `test_engine_compact_resolves_latest_seq_no_across_multiple_tables_and_removes_old_files` | Real cross-table `seq_no` conflict resolution (not just the single-table case above), plus confirms old `.sst`/`.idx` pairs are actually gone from disk afterward via a glob-count assertion.         |
| `test_one_million_entries_compaction`                                                     | **Slow, deselected by default:** inserts and compacts 1,000,000 entries, then verifies every key/value survives compaction.                                                                        |

## Kill-9 / Subprocess Crash Tests

| Test                                                                               | What it proves                                                                                                                                             |
| ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_kill_during_flush_before_rename_preserves_wal_and_prevents_sstable_exposure` | A process killed before `os.replace()` commits a flush leaves no partially-visible `.sst`, and WAL replay on restart recovers exactly the pre-crash state. |
| `test_kill_after_replace_before_wal_truncate_replays_redundant_entries_safely`     | A process killed after commit but before WAL truncation replays safely (idempotent re-application), doesn't double-apply or corrupt state.                 |

---

## Known Gaps — Not Built, Tracked Deliberately

- **Live SIGKILL test for `flush()`'s `.idx`-then-`.sst` commit window.** Not built. Same reasoning as the Phase 3 compaction-unlink precedent: this window is narrower than that one, which was already attempted multiple times and never reliably landed. Mocked-`os.replace`-failure test (see above) judged sufficient. Revisit only if that reasoning is directly challenged, not by default.
- **Tmp-file-path regression coverage.** Resolved: `test_flush_removes_tmp_file_and_creates_final_sstable` asserts both final paths remain in `table_dir` and both `.tmp` files are absent. `SSTable.flush()` derives the temporary names from those final paths and atomically replaces them in the same directory.
- **Hypothesis property-based tests.** Roadmap-mandated (WAL pack/unpack roundtrip fuzzing, compaction tombstone-preservation invariant), listed as a Phase 6 gating requirement. Nothing in this inventory uses it — every test above is example-based. This is a real, roadmap-required gap, not an oversight to silently accept.
- **Bloom filter tests.** N/A until the bloom filter itself is built (currently deferred — see `STRATUM_PROJECT.md` Discrepancy #2). Roadmap's own milestone for this phase specifies a false-positive-rate measurement and a test asserting zero file I/O for a bloom-negative key — both will need entries here once that work starts.
- **Tiered/`heapq` compaction tests.** N/A until the compaction architecture question (Discrepancy #1) is resolved one way or the other.

---

## Maintenance Rule

Before marking any phase "done" going forward: diff this file's test list against the actual test file's function names. Any test present in one but not the other is the first thing to resolve — either the code needs the missing test, or this inventory needs an explicit, reasoned update (not a silent deletion).
