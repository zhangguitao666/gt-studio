# Saved Resolve retime reference: initial setup evidence

This analysis recovered seven named test timelines and their saved relation/item rows from the dedicated reference-project snapshot. **It did not recover a successful speed change, a second video clip, later-clip ripple movement, or decoded source boundaries.** This first snapshot is useful evidence of incomplete test setup, not a retiming reference oracle.

## Artifact and reproduction

Inspected file: [reference-project-snapshot.sqlite](evidence/reference-project-snapshot.sqlite).

Snapshot SHA-256: `83d7ac9567db53641e375c159d7bfb9b8ffe8ccdfc5f4590dbea48e0f53f22c2`.

The main investigator created the snapshot using SQLite's backup API from the dedicated `REA Reference · 2026-10-21` project. This analysis opens **only the saved snapshot** using SQLite URI `mode=ro&immutable=1`, enables query-only mode, and checks that its bytes/hash are unchanged after reading. `PRAGMA integrity_check` returned `ok`. The original live database was not opened or modified by this analysis.

Run `python3 scripts/analyze_resolve_retime_snapshot.py`. The script accepts `--snapshot` for a separately saved file inside this project's `research/evidence` directory and `--output` for its JSON report. Keep the initial snapshot and JSON when inspecting a later capture; a later snapshot may reflect additional saves or different experiments.

[retime-reference.json](retime-reference.json) contains every selected table's schema, primary key columns, row count, selected relation rows, all original scalar column values, and each BLOB's size/SHA-256/prefix (full hex when at most 256 bytes). Every row includes its table/PK anchor and a reproducible digest over canonical original SQL values. Its `row_hash_algorithm` specifies the exact encoding. This permits verifying a value without assuming any native timing format.

## Saved structural observations

| Table | Saved rows |
| --- | ---: |
| Sm2Timeline | 7 |
| Sm2Sequence | 7 |
| Sm2SequenceContainer | 7 |
| Sm2TiTrack | 14 |
| Sm2TiItem | 14 |
| SmSpeedProfile | 0 |
| SM_Project_Sm2Timeline | 7 |
| Sm2Sequence_Sm2TiTrack | 0 |
| Sm2SequenceContainer_Sm2TiTrack | 14 |
| Sm2TiItem_Sm2TiTrack | 14 |
| Sm2TiItem_Sm2TiItem / Sm2Selector_Sm2TiItem / Sm2TiTrack_Sm2TiTrack | 0 / 0 / 0 |

The saved schema connects timeline/sequence/container identities and relation-table track membership. Each case has two track rows with `DbType=Sm2TiTrack`. Container membership labels one `VideoTrackVec` and one `AudioTrackVec`. Each track has exactly one `Items` relation at `DbIndex=0`. Associated item `DbType` values distinguish one `Sm2TiVideoClip` and one `Sm2TiAudioClip`. There is no saved `Items` membership at index 1 for these cases.

All 14 associated item rows contain literal SQL values `Start='86400'`, `Duration='47'`, `In=NULL`, `MediaStartTime=0.0`, and the generated `motion.mp4` source path. These strings/numbers are reported exactly as stored; this analysis does not infer their frame/time units or source-end convention. The `MediaTimemapBA` blobs all contain bytes `024007aaaaaaaaaaab` and are retained by hash/full hex without interpreting their proprietary layout. No explicit source end or decoded speed value was recovered.

| Attempted case label | Timeline primary key | Saved video/audio items |
| --- | --- | --- |
| 100, false | `c4a6a1a0-cfe6-4d05-a636-22a536f5dce6` | 1 / 1 |
| 200, false | `9a7b6dd0-4609-4a2c-a7a2-532fb998f6bd` | 1 / 1 |
| 50, false | `55ea0275-520b-4b30-8192-2469a58f01ab` | 1 / 1 |
| 200, true | `0da9591b-fcac-441c-a77e-aea0761c9646` | 1 / 1 |
| 50, true | `f4e5cfac-2578-4fdb-b0a2-b78cd69a5428` | 1 / 1 |
| -100, false | `c0763102-1d62-4835-bdfb-6338b92a00e2` | 1 / 1 |
| 0, false | `365454a1-5dda-464a-8418-f2902c5422c5` | 1 / 1 |

Every timeline name uses prefix `REA_SPEED_20261021_105104_`. The labels indicate attempted percentage/ripple arguments from the experiment setup. They do not prove those arguments reached `SetSpeed`, returned success, or were saved.

## Interpretation and missing evidence

The initial probe source observed during inspection called `CreateTimelineFromClips` with two identical source-range entries and asserted that two video-track items existed **before** invoking `SetSpeed`. The saved snapshot has only one item per video track. A failed precondition is therefore a plausible explanation for why no speed change can be demonstrated here. This is a source/snapshot consistency inference, not a captured Console error or successful method result. The probe is being revised separately; its current file hash must not be substituted for a transcript of an earlier execution.

An empty `SmSpeedProfile` table is only a bounded database observation. It does not prove that no speed data exists elsewhere, in unsaved application memory, or in proprietary fields. Some opaque blobs contain a Zstandard magic-byte candidate; this analysis records the candidate offset but does not decode an undocumented wrapper. Only recognized gzip/zlib/plist/XML payloads are cautiously inspected, retaining compression offsets and output digests; no native numeric/blob layout is guessed from column names.

To establish a useful behavioral retime reference, capture two distinct clips with verified positions, before/after getters and actual `SetSpeed` return for every case, then save and create another consistent snapshot. Compare source boundaries, duration, clip order/later positions, reverse/freeze behavior and pitch handling with rendered output. An incomplete save or missing Console result must remain explicitly incomplete; it cannot support a claim about absent functionality or parity.
