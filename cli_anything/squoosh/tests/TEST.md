# cli-anything-squoosh: Test Plan and Results

## Part 1: Test Plan

### Test inventory

| File | Kind | Planned |
|---|---|---|
| `test_core.py` | Unit tests, synthetic data, no Node/WASM | ~45 |
| `test_full_e2e.py` | Real Squoosh WASM codecs via Node, real images, installed CLI via subprocess | ~45 |

The E2E suite needs Node 18+ and the Squoosh `codecs/` tree. It **fails**
(doesn't skip) when either is missing: the software is a hard dependency.

### Unit test plan (`test_core.py`)

- **`core/codecs.py`** (~12): every encoder has a name, extension, MIME and format; `merge_options` returns the full default struct; `coerce_option` handles bools ("true"/"0"/...), ints, floats and ranges; rejects unknown options, out-of-range values, non-numeric strings and a float for an int option; `parse_option_pairs` rejects text without `=`; an unknown encoder raises; the AVIF struct uses `enableSharpDownsampling` (the field name the shipped binary uses).
- **`core/project.py`** (~16): `new_project` sets defaults and rejects a bad encoder; `validate` rejects foreign JSON and missing keys; `set_source` rejects missing files and stores probe data; `set_rotate` normalises (-90 → 270, 450 → 90) and rejects 45; `set_resize` checks sizes, methods and fit, and keeps the aspect ratio when given one side; `target_size` swaps for 90/270; `pipeline_steps` is in order rotate → resize → quantize and skips disabled steps; `set_quantize` checks colour and dither bounds; `set_encoder` resets options when the codec changes and keeps them otherwise; `info` reflects state.
- **`core/session.py`** (~10): `require` with no project; new/save/open round trip; `mutate` records undo and clears redo; a failed mutation restores the snapshot and records no history; undo/redo symmetry; errors when there is nothing to undo or redo; history capped at 100; `_locked_save_json` truncates a longer old file correctly; opening corrupt JSON raises `ValueError`.
- **`core/export.py`** (~5): `verify_output` accepts the right magic bytes for all 7 formats and rejects wrong magic, empty and missing files; `default_output` naming; `render` without a source raises; refuses to overwrite without `overwrite`.
- **`core/preview.py`** (~3): the fingerprint is stable and changes when options change; `latest` raises with no bundles; the `_building` context removes a partial bundle on failure.

### E2E plan (`test_full_e2e.py`)

Real inputs: `codecs/example.png` (2558×1347 RGBA photo) plus small synthetic PNGs
encoded by Squoosh itself (solid red, gradient, 2×1 orientation marker).

- **Decoders**: probe PNG, JPEG, WebP, AVIF, JXL, WP2, QOI files produced by the encoders; dimensions must match.
- **Every encoder** (8): output exists, size > 0, correct magic bytes, re-decoded by Squoosh to the right size; for a solid red image the decoded mean colour is within tolerance of (255,0,0).
- **Options take effect**: mozjpeg q=10 < q=90 in bytes; webp lossless=1 decodes to an exact solid colour; oxipng level 0 ≥ level 6 in bytes.
- **Processors**: resize changes the dimensions (each method, including hqx upscaling); `contain` crops to the target aspect ratio; rotate 90 swaps the dimensions and moves the marker pixel to the expected corner; quantize to 4 colours gives ≤ 4 unique colours after a lossless PNG round trip.
- **Preview**: a capture writes a manifest (`preview-bundle/v1`), encoded/decoded/source artifacts and a summary; a second capture is cached; a forced capture renders again; a diff has both sides and the right `smaller` field; `latest` returns the newest bundle.
- **Export bookkeeping**: export records history in the project; compare ranks by size; batch handles a glob and reports failures per file.

### Realistic workflow scenarios

1. **Web hero image**: new project → source example.png → resize to 1280 wide (lanczos3) → webp q=75 → export. Checks: 1280×674, WebP magic, < 10% of the source bytes.
2. **Thumbnail set**: rotate 90 → resize 200×200 contain → mozjpeg q=60 → batch over 2 images. Checks: every output is 200×200 JPEG.
3. **Codec shoot-out**: compare mozjpeg, webp, avif, jxl and oxipng on one source. Checks: results sorted ascending; a lossy codec is smallest; all files valid.
4. **Palette PNG for an icon**: quantize 16 colours → oxipng level 3. Checks: ≤ 16 unique colours, PNG magic.
5. **Iterative tuning with undo**: set webp q=90 → q=50 → undo → export. Checks: the exported options have quality 90; redo restores 50.
6. **Agent subprocess flow** (installed command): `project new -o` → `source set` → `edit resize` → `encoder set avif quality=40` → `export` → `preview capture` → `--json project info`, each a separate process with auto-save. Checks: state persists across processes, outputs are valid, `--dry-run` doesn't write the project, errors exit non-zero with JSON `{"error": ...}`.

### Added later: `folder` command

- Unit (4): input that isn't a folder, a folder with no images, output folder equal to the input, default output name.
- E2E (6): defaults (quality 70, `<dir>-squoosh-q70`, top level only, `.txt` ignored, a corrupt JPEG reported as failed without stopping the run); quality 30 gives a smaller total than 90; `-r` mirrors subfolders and `-w` resizes; existing outputs are skipped, then replaced with `--overwrite`; lossless encoders ignore quality; installed-command subprocess test, including JSON output for a bad quality value.

---

## Part 2: Test Results

Re-run on 2026-11-11 after adding `folder`, using the installed command.
Command: `CLI_ANYTHING_FORCE_INSTALLED=1 pytest cli_anything/squoosh/tests -v --tb=no`

```
============================= test session starts ==============================
platform darwin -- Python 3.14.7, pytest-9.2.0, pluggy-1.7.0 -- <repo>/squoosh-dev/agent-harness/.venv/bin/python3.14
rootdir: <repo>/squoosh-dev/agent-harness
collecting ... collected 135 items

cli_anything/squoosh/tests/test_core.py::TestCodecs::test_registry_complete PASSED [  0%]
cli_anything/squoosh/tests/test_core.py::TestCodecs::test_merge_full_struct PASSED [  1%]
cli_anything/squoosh/tests/test_core.py::TestCodecs::test_defaults_are_copies PASSED [  2%]
cli_anything/squoosh/tests/test_core.py::TestCodecs::test_bool_coercion[true-True] PASSED [  2%]
cli_anything/squoosh/tests/test_core.py::TestCodecs::test_bool_coercion[0-False] PASSED [  3%]
cli_anything/squoosh/tests/test_core.py::TestCodecs::test_bool_coercion[on-True] PASSED [  4%]
cli_anything/squoosh/tests/test_core.py::TestCodecs::test_bool_coercion[No-False] PASSED [  5%]
cli_anything/squoosh/tests/test_core.py::TestCodecs::test_bool_coercion[True-True] PASSED [  5%]
cli_anything/squoosh/tests/test_core.py::TestCodecs::test_bool_bad PASSED [  6%]
cli_anything/squoosh/tests/test_core.py::TestCodecs::test_int_and_float PASSED [  7%]
cli_anything/squoosh/tests/test_core.py::TestCodecs::test_int_rejects_fraction PASSED [  8%]
cli_anything/squoosh/tests/test_core.py::TestCodecs::test_range PASSED   [  8%]
cli_anything/squoosh/tests/test_core.py::TestCodecs::test_unknown_option PASSED [  9%]
cli_anything/squoosh/tests/test_core.py::TestCodecs::test_non_numeric PASSED [ 10%]
cli_anything/squoosh/tests/test_core.py::TestCodecs::test_pairs PASSED   [ 11%]
cli_anything/squoosh/tests/test_core.py::TestCodecs::test_unknown_encoder PASSED [ 11%]
cli_anything/squoosh/tests/test_core.py::TestCodecs::test_avif_matches_shipped_binary PASSED [ 12%]
cli_anything/squoosh/tests/test_core.py::TestCodecs::test_unsupported_value_rejected PASSED [ 13%]
cli_anything/squoosh/tests/test_core.py::TestProject::test_new_defaults PASSED [ 14%]
cli_anything/squoosh/tests/test_core.py::TestProject::test_new_bad_encoder PASSED [ 14%]
cli_anything/squoosh/tests/test_core.py::TestProject::test_validate PASSED [ 15%]
cli_anything/squoosh/tests/test_core.py::TestProject::test_source_missing PASSED [ 16%]
cli_anything/squoosh/tests/test_core.py::TestProject::test_source_probe PASSED [ 17%]
cli_anything/squoosh/tests/test_core.py::TestProject::test_rotate_normalise[-90-270] PASSED [ 17%]
cli_anything/squoosh/tests/test_core.py::TestProject::test_rotate_normalise[450-90] PASSED [ 18%]
cli_anything/squoosh/tests/test_core.py::TestProject::test_rotate_normalise[180-180] PASSED [ 19%]
cli_anything/squoosh/tests/test_core.py::TestProject::test_rotate_normalise[0-0] PASSED [ 20%]
cli_anything/squoosh/tests/test_core.py::TestProject::test_rotate_bad PASSED [ 20%]
cli_anything/squoosh/tests/test_core.py::TestProject::test_resize_validation PASSED [ 21%]
cli_anything/squoosh/tests/test_core.py::TestProject::test_resize_aspect PASSED [ 22%]
cli_anything/squoosh/tests/test_core.py::TestProject::test_target_size_rotated PASSED [ 22%]
cli_anything/squoosh/tests/test_core.py::TestProject::test_target_size_unknown PASSED [ 23%]
cli_anything/squoosh/tests/test_core.py::TestProject::test_pipeline_order PASSED [ 24%]
cli_anything/squoosh/tests/test_core.py::TestProject::test_disable_bad PASSED [ 25%]
cli_anything/squoosh/tests/test_core.py::TestProject::test_quantize_bounds PASSED [ 25%]
cli_anything/squoosh/tests/test_core.py::TestProject::test_set_encoder_options PASSED [ 26%]
cli_anything/squoosh/tests/test_core.py::TestProject::test_set_encoder_reset PASSED [ 27%]
cli_anything/squoosh/tests/test_core.py::TestProject::test_info PASSED   [ 28%]
cli_anything/squoosh/tests/test_core.py::TestSession::test_require PASSED [ 28%]
cli_anything/squoosh/tests/test_core.py::TestSession::test_roundtrip PASSED [ 29%]
cli_anything/squoosh/tests/test_core.py::TestSession::test_save_no_path PASSED [ 30%]
cli_anything/squoosh/tests/test_core.py::TestSession::test_undo_redo PASSED [ 31%]
cli_anything/squoosh/tests/test_core.py::TestSession::test_new_mutation_clears_redo PASSED [ 31%]
cli_anything/squoosh/tests/test_core.py::TestSession::test_failed_mutation_rolls_back PASSED [ 32%]
cli_anything/squoosh/tests/test_core.py::TestSession::test_nothing_to_undo PASSED [ 33%]
cli_anything/squoosh/tests/test_core.py::TestSession::test_history_cap PASSED [ 34%]
cli_anything/squoosh/tests/test_core.py::TestSession::test_locked_save_truncates PASSED [ 34%]
cli_anything/squoosh/tests/test_core.py::TestSession::test_open_corrupt PASSED [ 35%]
cli_anything/squoosh/tests/test_core.py::TestExport::test_magic_ok[mozjpeg] PASSED [ 36%]
cli_anything/squoosh/tests/test_core.py::TestExport::test_magic_ok[oxipng] PASSED [ 37%]
cli_anything/squoosh/tests/test_core.py::TestExport::test_magic_ok[webp] PASSED [ 37%]
cli_anything/squoosh/tests/test_core.py::TestExport::test_magic_ok[avif] PASSED [ 38%]
cli_anything/squoosh/tests/test_core.py::TestExport::test_magic_ok[jxl] PASSED [ 39%]
cli_anything/squoosh/tests/test_core.py::TestExport::test_magic_ok[qoi] PASSED [ 40%]
cli_anything/squoosh/tests/test_core.py::TestExport::test_magic_ok[wp2] PASSED [ 40%]
cli_anything/squoosh/tests/test_core.py::TestExport::test_magic_bad PASSED [ 41%]
cli_anything/squoosh/tests/test_core.py::TestExport::test_empty_and_missing PASSED [ 42%]
cli_anything/squoosh/tests/test_core.py::TestExport::test_default_output PASSED [ 42%]
cli_anything/squoosh/tests/test_core.py::TestExport::test_render_guards PASSED [ 43%]
cli_anything/squoosh/tests/test_core.py::TestPreview::test_fingerprint PASSED [ 44%]
cli_anything/squoosh/tests/test_core.py::TestPreview::test_latest_none PASSED [ 45%]
cli_anything/squoosh/tests/test_core.py::TestPreview::test_building_cleans_up PASSED [ 45%]
cli_anything/squoosh/tests/test_core.py::TestFolderGuards::test_not_a_folder PASSED [ 46%]
cli_anything/squoosh/tests/test_core.py::TestFolderGuards::test_no_images PASSED [ 47%]
cli_anything/squoosh/tests/test_core.py::TestFolderGuards::test_output_same_as_input PASSED [ 48%]
cli_anything/squoosh/tests/test_core.py::TestFolderGuards::test_default_output_name PASSED [ 48%]
cli_anything/squoosh/tests/test_full_e2e.py::TestBackend::test_doctor PASSED [ 49%]
cli_anything/squoosh/tests/test_full_e2e.py::TestBackend::test_probe_example PASSED [ 50%]
cli_anything/squoosh/tests/test_full_e2e.py::TestBackend::test_probe_rejects_garbage PASSED [ 51%]
cli_anything/squoosh/tests/test_full_e2e.py::TestBackend::test_missing_root_env PASSED [ 51%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_encode_example[mozjpeg] PASSED [ 52%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_encode_example[webp] PASSED [ 53%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_encode_example[avif] PASSED [ 54%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_encode_example[jxl] PASSED [ 54%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_encode_example[wp2] PASSED [ 55%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_encode_example[oxipng] PASSED [ 56%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_encode_example[qoi] PASSED [ 57%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_encode_example[png] PASSED [ 57%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_solid_red_colour[mozjpeg] PASSED [ 58%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_solid_red_colour[webp] PASSED [ 59%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_solid_red_colour[avif] PASSED [ 60%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_solid_red_colour[jxl] PASSED [ 60%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_solid_red_colour[wp2] PASSED [ 61%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_solid_red_colour[oxipng] PASSED [ 62%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_solid_red_colour[qoi] PASSED [ 62%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_solid_red_colour[png] PASSED [ 63%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_decoder_roundtrip[mozjpeg-jpeg] PASSED [ 64%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_decoder_roundtrip[webp-webp] PASSED [ 65%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_decoder_roundtrip[avif-avif] PASSED [ 65%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_decoder_roundtrip[jxl-jxl] PASSED [ 66%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_decoder_roundtrip[wp2-wp2] PASSED [ 67%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_decoder_roundtrip[qoi-qoi] PASSED [ 68%]
cli_anything/squoosh/tests/test_full_e2e.py::TestEncoders::test_decoder_roundtrip[oxipng-png] PASSED [ 68%]
cli_anything/squoosh/tests/test_full_e2e.py::TestOptionsTakeEffect::test_mozjpeg_quality PASSED [ 69%]
cli_anything/squoosh/tests/test_full_e2e.py::TestOptionsTakeEffect::test_webp_lossless_exact PASSED [ 70%]
cli_anything/squoosh/tests/test_full_e2e.py::TestOptionsTakeEffect::test_oxipng_levels PASSED [ 71%]
cli_anything/squoosh/tests/test_full_e2e.py::TestOptionsTakeEffect::test_avif_speed PASSED [ 71%]
cli_anything/squoosh/tests/test_full_e2e.py::TestOptionsTakeEffect::test_avif_sharp_downsampling_rejected PASSED [ 72%]
cli_anything/squoosh/tests/test_full_e2e.py::TestProcessors::test_resize_methods[triangle] PASSED [ 73%]
cli_anything/squoosh/tests/test_full_e2e.py::TestProcessors::test_resize_methods[catrom] PASSED [ 74%]
cli_anything/squoosh/tests/test_full_e2e.py::TestProcessors::test_resize_methods[mitchell] PASSED [ 74%]
cli_anything/squoosh/tests/test_full_e2e.py::TestProcessors::test_resize_methods[lanczos3] PASSED [ 75%]
cli_anything/squoosh/tests/test_full_e2e.py::TestProcessors::test_resize_methods[hqx] PASSED [ 76%]
cli_anything/squoosh/tests/test_full_e2e.py::TestProcessors::test_contain_crops PASSED [ 77%]
cli_anything/squoosh/tests/test_full_e2e.py::TestProcessors::test_rotate_moves_marker[90-top-right] PASSED [ 77%]
cli_anything/squoosh/tests/test_full_e2e.py::TestProcessors::test_rotate_moves_marker[180-bottom-right] PASSED [ 78%]
cli_anything/squoosh/tests/test_full_e2e.py::TestProcessors::test_rotate_moves_marker[270-bottom-left] PASSED [ 79%]
cli_anything/squoosh/tests/test_full_e2e.py::TestProcessors::test_quantize_colours PASSED [ 80%]
cli_anything/squoosh/tests/test_full_e2e.py::TestPreview::test_capture_and_cache PASSED [ 80%]
cli_anything/squoosh/tests/test_full_e2e.py::TestPreview::test_diff PASSED [ 81%]
cli_anything/squoosh/tests/test_full_e2e.py::TestPreview::test_failed_capture_leaves_nothing PASSED [ 82%]
cli_anything/squoosh/tests/test_full_e2e.py::TestWorkflows::test_web_hero PASSED [ 82%]
cli_anything/squoosh/tests/test_full_e2e.py::TestWorkflows::test_thumbnail_batch PASSED [ 83%]
cli_anything/squoosh/tests/test_full_e2e.py::TestWorkflows::test_codec_shootout PASSED [ 84%]
cli_anything/squoosh/tests/test_full_e2e.py::TestWorkflows::test_palette_icon PASSED [ 85%]
cli_anything/squoosh/tests/test_full_e2e.py::TestWorkflows::test_iterative_undo PASSED [ 85%]
cli_anything/squoosh/tests/test_full_e2e.py::TestFolder::test_defaults_quality_70 PASSED [ 86%]
cli_anything/squoosh/tests/test_full_e2e.py::TestFolder::test_quality_changes_size PASSED [ 87%]
cli_anything/squoosh/tests/test_full_e2e.py::TestFolder::test_recursive_mirrors_tree PASSED [ 88%]
cli_anything/squoosh/tests/test_full_e2e.py::TestFolder::test_skip_existing_then_overwrite PASSED [ 88%]
cli_anything/squoosh/tests/test_full_e2e.py::TestFolder::test_lossless_ignores_quality PASSED [ 89%]
cli_anything/squoosh/tests/test_full_e2e.py::TestCLISubprocess::test_help PASSED [ 90%]
cli_anything/squoosh/tests/test_full_e2e.py::TestCLISubprocess::test_version PASSED [ 91%]
cli_anything/squoosh/tests/test_full_e2e.py::TestCLISubprocess::test_encoder_list_json PASSED [ 91%]
cli_anything/squoosh/tests/test_full_e2e.py::TestCLISubprocess::test_encoder_options_json PASSED [ 92%]
cli_anything/squoosh/tests/test_full_e2e.py::TestCLISubprocess::test_doctor PASSED [ 93%]
cli_anything/squoosh/tests/test_full_e2e.py::TestCLISubprocess::test_full_agent_workflow PASSED [ 94%]
cli_anything/squoosh/tests/test_full_e2e.py::TestCLISubprocess::test_dry_run_does_not_save PASSED [ 94%]
cli_anything/squoosh/tests/test_full_e2e.py::TestCLISubprocess::test_error_json_nonzero PASSED [ 95%]
cli_anything/squoosh/tests/test_full_e2e.py::TestCLISubprocess::test_export_without_source PASSED [ 96%]
cli_anything/squoosh/tests/test_full_e2e.py::TestCLISubprocess::test_compress_oneshot PASSED [ 97%]
cli_anything/squoosh/tests/test_full_e2e.py::TestCLISubprocess::test_compare_and_batch PASSED [ 97%]
cli_anything/squoosh/tests/test_full_e2e.py::TestCLISubprocess::test_undo_across_repl PASSED [ 98%]
cli_anything/squoosh/tests/test_full_e2e.py::TestCLISubprocess::test_folder_command PASSED [ 99%]
cli_anything/squoosh/tests/test_full_e2e.py::TestCLISubprocess::test_decode_and_probe PASSED [100%]

============================= 135 passed in 50.65s =============================
```

### Summary

- Total: **135 tests**: 66 unit (`test_core.py`), 69 E2E (`test_full_e2e.py`, 15 of them subprocess tests against the installed command)
- Pass rate: **100%**

### Coverage notes

- All 8 Node-capable encoders and all 7 decoders run on a real photo (`codecs/example.png`) and on synthetic images. Checks: magic bytes, size after decoding again, mean colour (solid red), an exact lossless round trip (WebP lossless), and that a smaller quality setting gives a smaller file (MozJPEG, OxiPNG).
- All 5 resize methods, contain-fit, rotation (a marker pixel moves to the expected corner for 90/180/270) and quantization (colour count limit) are checked pixel by pixel after decoding.
- Preview bundles: manifest, artifacts, caching, `--force`, diff, `latest`, and that a failed capture leaves no partial bundle.
- Found while testing: the shipped AVIF binary aborts if `enableSharpDownsampling=true`. The CLI now rejects that value, and both suites test it.
- Not covered: the browser-only encoders and SVG vector resize (they need a canvas and are not exposed); a GUI round trip (Squoosh has no project file to load); the multithreaded `_mt` AVIF/OxiPNG builds (the bridge uses the single-threaded builds); live preview (not implemented).
