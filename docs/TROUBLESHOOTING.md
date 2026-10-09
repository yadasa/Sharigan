# Troubleshooting

- **Missing keys:** put your own `SEEDANCE_API_KEY` and `REPLICATE_API_TOKEN` in this folder's `.env` and restart. The UI configuration dialog reports presence only.
- **401/403 or unavailable model:** check the direct ModelArk API key, region, enabled Seedance 2.5 model access and account balance. Never log secrets.
- **Video-edit validation:** use 4–30 second MP4/MOV videos with audio, supported dimensions and frame rates. Source plus identity-reference videos must total at most 30 seconds.
- **Missing Rubber Band:** install the CLI from its official distribution/package manager, put it on PATH and rerun doctor.
- **Mesh worker absent:** run `bash setup-face-mesh.sh` with Python 3.12 in macOS/Linux/WSL. Review tracking across the entire clip.
- **Media download failure:** use real PNG/JPEG/WebP images or MP4/MOV video and reachable direct HTTPS URLs. Tmpfiles expires and hosts may be unavailable. Catbox fallback is opt in.
- **Mask coverage/holes/background spill:** reject input, use RGB repair within authorized inference scope, then inspect the full clip again. Hash checks are not visual QA.
- **Frame alignment:** mismatched mask/frame counts fail deliberately. Inspect provider output FPS and frame IDs before compositing.
- **Audio mismatch:** export permits a 0.25–0.5 second final-frame hold for a short provider rounding gap and records `duration-adjustment.json`. Larger differences are rejected. Original audio is never trimmed, looped or stretched.
- **No source audio:** currently unsupported. Use a clip with an audio track.
- **1080p preview will not play:** Seedance 2.5 can return HEVC/10-bit output. Download the MP4 and open it in a compatible player such as VLC.
- **Expired draft:** ModelArk draft task IDs expire after seven days. A new draft is a new paid operation.
- **Submission timeout:** inspect the saved request and ModelArk task list before retrying. A saved request guard prevents duplicate paid submissions.
- **Restart/recovery:** saved Seedance draft and HD task collection resumes automatically. Use CLI `resume` only when the server is not collecting the same job. Preprocessing recovery requires inspecting saved Replicate prediction IDs.
- **Sounds:** enable the Sound toggle explicitly. Effects are synthesized locally with Web Audio; the browser may require interaction. Sound is off by default and no anime recordings are included.
