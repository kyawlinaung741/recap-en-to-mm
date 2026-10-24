# Build an FFmpeg NVENC-compatible build for GTX 1070 (Windows)

## Goal

Build a separate FFmpeg binary that uses NVENC API 13.0 headers, rather than 13.1, so a Pascal GPU such as the GeForce GTX 1070 can be tested with a driver that exposes NVENC API 13.0.

**Important:** This document is a build recipe, not a prebuilt executable. It has not been compiled or tested on the user's PC. Keep the current FFmpeg folders intact until the new binary passes the test below.

## Why this is needed

The user's FFmpeg 8.1.2 binary reports:

```text
Driver does not support the required nvenc API version. Required: 13.1 Found: 13.0
```

The FFmpeg NVENC maintainer's guidance for Pascal GPUs with a driver exposing API 13.0 is to build FFmpeg with SDK / nv-codec-headers 13.0 rather than 13.1. The FFmpeg binary version number alone does not guarantee which NVENC API headers were used.

## Build approach

Use a Windows FFmpeg build environment such as Media Autobuild Suite (MABS), and explicitly pin its `nv-codec-headers` / `ffnvcodec` dependency to the 13.0 release/tag. Do not let the build update that dependency to 13.1 during the build.

Official reference for the Windows build workflow:
- NVIDIA Video Codec SDK 13.0 FFmpeg guide: https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/ffmpeg-with-nvidia-gpu/index.html
- Media Autobuild Suite: https://github.com/m-ab-s/media-autobuild_suite
- FFmpeg NVENC compatibility discussion: https://github.com/GyanD/codexffmpeg/issues/232

### Build requirements

1. Build for 64-bit Windows.
2. Enable FFmpeg NVENC support.
3. Use the 13.0 `nv-codec-headers` source/tag explicitly.
4. Build to a new output folder, for example `C:\\ffmpeg-nvenc13\\bin`; do not overwrite `C:\\ffmpeg\\bin` or `C:\\ffmpeg old\\bin`.
5. Preserve the build log so the exact header version can be checked.

## Test the resulting binary before using it in Recap

Open Command Prompt and run the following, replacing the path if the build output differs:

```bat
"C:\\ffmpeg-nvenc13\\bin\\ffmpeg.exe" -hide_banner -f lavfi -i testsrc2=size=1280x720:rate=30 -t 5 -c:v h264_nvenc -f null -
```

A successful test should complete without the messages `Required: 13.1 Found: 13.0` and should report that frames were encoded. If it fails, keep the existing FFmpeg and do not switch the Recap app to this build.

## Important limitation

The exact MABS steps to pin a dependency can change with the current MABS configuration. Verify that the generated build really uses API 13.0 by running the test above; merely naming the folder or binary “13.0” does not make it compatible.
