# ComfyUI-Video-Segment-Writer

**Video Segment Writer**

[English](README.md) | [简体中文](README.zh-CN.md)

Stream each decoded video/audio segment to disk in MieLoop v3 workflows, then assemble MP4 segments by stream copy after the loop finishes. Works with H3 and other workflows producing standard IMAGE/AUDIO data.

This pack does not remove continuation overlap or validate lip sync. Audio is encoded to AAC separately per segment; short audio is padded with silence and excess audio is trimmed to video duration. For a continuous PCM master and shared-context trimming, use ComfyUI-H3-AV-Continuation.

## Installation

Clone or extract this repository into `ComfyUI/custom_nodes/ComfyUI-Video-Segment-Writer/`, with `__init__.py` directly inside that directory. Install dependencies using the same Python environment that runs ComfyUI:

```bash
python -m pip install -r custom_nodes/ComfyUI-Video-Segment-Writer/requirements.txt
```

Windows portable edition (run from the portable root):

```powershell
.\python_embeded\python.exe -m pip install -r .\ComfyUI\custom_nodes\ComfyUI-Video-Segment-Writer\requirements.txt
```

Restart ComfyUI and refresh the browser. FFmpeg must provide `libx264` and `aac`; the pack uses FFmpeg on PATH, falling back to the executable bundled with imageio-ffmpeg.

Requires a MieLoop pack providing `MIE_LOOP_CTX` v3, containing `version=3`, a 24-character lowercase hexadecimal `run_id`, zero-based `index`, and a positive `count`. Loop nodes are not included.

## Language and compatibility

Plugin categories, node titles, parameter names, input/output labels, tooltips and combo choices have English and Chinese translations. They follow `Comfy > Locale > Language` (`Comfy.Locale`); `zh` uses Simplified Chinese and other unprovided languages fall back to English.

Translations use native `locales/en` and `locales/zh`. A frontend extension also updates existing canvas nodes on language changes and preserves custom titles. Requires ComfyUI with `/api/i18n`; reload the page if an older frontend leaves the node search menu stale. GitHub repository and installation directory names are fixed identifiers.

Original node IDs, socket keys, input order, defaults and output directories are preserved for existing workflows.

When migrating, move the old `h3_disk_video` folder out of custom_nodes to avoid duplicate registrations.

[ComfyUI official i18n documentation](https://docs.comfy.org/custom-nodes/i18n)

## Typical connections

1. Connect MieLoop `loop_ctx`, decoded `images` and `audio` to the segment writer. Use identical dimensions, frame rate, audio layout and encoding settings across segments.
2. Route the returned `loop_ctx` back into the loop so each segment is saved before advancing.
3. Connect the completed loop context and `done` to the assembler to output the final MP4.

## Nodes and parameters

### Video Segment Writer (H.264 + AAC)

`H3DiskEncodeSegment`

Stream one decoded video/audio segment to an MP4 on disk and record its frame count in an ordered manifest.

| Input (internal key) | Label | Type / default | Purpose |
| --- | --- | --- | --- |
| `loop_ctx` | Loop Context | MIE_LOOP_CTX | Connect the MieLoop v3 context for this run and segment index. |
| `images` | Video Frames | IMAGE | Decoded RGB IMAGE batch shaped [frames, height, width, 3]; H.264 requires even width and height. |
| `audio` | Segment Audio | AUDIO | Decoded AUDIO with waveform [1, channels, samples] and a positive sample_rate, from the same segment as the video. |
| `fps` | Frame Rate | INT / `24` | Frames per second. Keep the same value across all segments in a run. |
| `crf` | H.264 Quality (CRF) | INT / `19` | Constant rate factor, 0–51. Smaller values improve quality and increase file size; default 19. |
| `preset` | H.264 Encoding Preset | medium/fast/veryfast/slow | medium is balanced; fast/veryfast reduce encoding time; slow spends more time on compression at the same CRF. |

| Output index | Label | Type | Meaning |
| --- | --- | --- | --- |
| 0 | Loop Context | `MIE_LOOP_CTX` | Connect the MieLoop v3 context for this run and segment index. |
| 1 | Segment MP4 Path | `STRING` | Absolute path to the encoded H.264/AAC segment MP4. |

### Video Segment Assembler (Stream Copy)

`H3DiskConcat`

Assemble all committed MP4 segments without video or audio re-encoding when the loop finishes.

| Input (internal key) | Label | Type / default | Purpose |
| --- | --- | --- | --- |
| `loop_ctx` | Loop Context | MIE_LOOP_CTX | Connect the MieLoop v3 context for this run and segment index. |
| `done` | Loop Finished | BOOLEAN / connection required | Connect the MieLoop completion flag; concatenation runs only when true and all segments are committed. |

| Output index | Label | Type | Meaning |
| --- | --- | --- | --- |
| 0 | Final MP4 Path | `STRING` | Absolute path to the assembled MP4 containing video and audio. |

## Files and troubleshooting

Output directory: `ComfyUI/output/h3_long_video/<run_id>/`, kept compatible with the original pack.

- `manifest.json`: committed segment order; `final.mp4`: final video; `*.log`: FFmpeg diagnostics.
- Keep at least 2 GiB free for writing. Assembly also requires the segment total size plus 1 GiB. Completed segments remain on disk after a low-space failure.
- For overwrite, manifest or index errors, check wiring and start a new loop run_id. Do not delete a manifest and continue using old segments. Segments for one run_id must be committed sequentially.

Each `segment_*.mp4` contains H.264 video and 48 kHz stereo AAC audio. Final assembly copies these encoded streams; it does not correct seams, delay or padding from independent AAC encoding.

## Development checks

```bash
python -m unittest discover -s tests -v
node --test tests/localization.test.mjs
```

Tests cover bilingual node/parameter/option completeness, stable node/socket compatibility, language switching without changing connections or values, and core planning or loop-control branches. Real model generation requires ComfyUI with H3 and MieLoop installed.
