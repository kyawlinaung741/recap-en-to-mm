# Windows FFmpeg build for GTX 1070 (NVENC API 13.0)

This guide is for the `feature/gpu-overlay-pass` experiment. It does not change `main`, replace the project's FFmpeg, or claim that a binary has already been built.

## Why this is needed

The user's current FFmpeg reports:

```
Driver does not support the required nvenc API version. Required: 13.1 Found: 13.0
```

The GTX 1070 / installed driver combination reports NVENC API 13.0. A build compiled against API 13.1 headers can fail even if the FFmpeg version number looks suitable. NVIDIA's FFmpeg guidance recommends matching the headers/SDK to the driver and testing the resulting binary.

## Pin the headers to API 13.0

Use the official `FFmpeg/nv-codec-headers` release tag `n13.0.19.1` (or `n13.0.19.0`), not `master` and not `n13.1.*`.

Official release list: https://github.com/FFmpeg/nv-codec-headers/releases

In an MSYS2 UCRT64 terminal, keep the work in a separate build folder:

```bash
mkdir -p ~/ffmpeg-work/deps
cd ~/ffmpeg-work/deps
git clone --branch n13.0.19.1 --depth 1 https://github.com/FFmpeg/nv-codec-headers.git nv-codec-headers-13.0
cd nv-codec-headers-13.0
```

Check the header version before installing it:

```bash
grep -E 'NVENCAPI_MAJOR_VERSION|NVENCAPI_MINOR_VERSION' include/ffnvcodec/nvEncodeAPI.h
```

Expected values are major `13` and minor `0`. If the output shows minor `1`, stop: do not build against those headers.

Install the pinned headers into the UCRT64 prefix:

```bash
make
make install PREFIX=/ucrt64
```

## Build FFmpeg without changing the app's current FFmpeg

Use a separate FFmpeg source checkout and a separate output directory. Choose an FFmpeg source revision whose configure checks accept API 13.0; do not assume that the newest FFmpeg source is compatible just because the headers were pinned.

A minimal NVENC build needs the UCRT64 toolchain, NASM, pkg-config, and the dependencies required by the selected FFmpeg configuration. The exact `configure` options depend on which filters, codecs, and libraries the Recap app uses. If configuration rejects the 13.0 headers or requests API 13.1, stop and select a compatible FFmpeg source revision rather than patching the version macros.

Do not overwrite `C:\\ffmpeg\\bin` during experimentation. Put the built files in a new folder such as `C:\\ffmpeg-nvenc13\\bin` only after the build is complete.

## Verify the binary before using it

First check the version and available encoder:

```powershell
& 'C:\\ffmpeg-nvenc13\\bin\\ffmpeg.exe' -hide_banner -version
& 'C:\\ffmpeg-nvenc13\\bin\\ffmpeg.exe' -hide_banner -encoders | Select-String 'h264_nvenc'
```

Then run a five-second encoder smoke test:

```powershell
& 'C:\\ffmpeg-nvenc13\\bin\\ffmpeg.exe' -hide_banner -f lavfi -i 'testsrc2=size=1280x720:rate=30' -t 5 -c:v h264_nvenc -f null -
```

**Pass condition:** the command completes without an NVENC API-version mismatch. Seeing `h264_nvenc` in the encoder list alone is not enough; the smoke test must actually initialize the encoder.

Only after the smoke test passes should the app be pointed to this separate FFmpeg build. Keep the existing CPU `libx264` fallback; GPU encoding failure must not prevent video export.

## Important limitations

- This document is a build recipe/checklist, not a compiled FFmpeg download.
- The exact FFmpeg source revision and complete dependency set still need to be chosen and built on the target Windows machine.
- Blur, PNG overlays, and other software filters may still run on the CPU even when final encoding uses NVENC.
- Do not edit the project's FFmpeg resolver to prefer an untested build.
