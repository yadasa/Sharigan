---
name: sharingan-video-workflow
description: Operate Sharingan video character replacement with direct Seedance tasks, full-clip review, draft retrieval and explicitly approved HD export.
---

Read `AGENTS.md`, `docs/AGENT-OPERATIONS.md` and `docs/SEEDANCE-API.md` before a job. Resolve the root as the folder containing `workflow.py`; use the local UI and CLI. Do not hardcode prior users' credentials, media, subjects or task IDs.

Complete authorized processing and collection through the final preview. Full-clip review is mandatory; if you cannot inspect video, ask the user to review through the UI. Fix mask coverage with raw masks/original-RGB segmentation while preserving depth colors. Review again after repair. Approval binds all current preparation artifacts and embedded audio.

Send +3-semitone isolated vocals inside the prepared video with no standalone audio. Primary image uses @Image1; primary video uses @Video2 for appearance only, with source @Video1. Both use direct ModelArk video editing. Show the creative prompt and respect submission authorization. Restore the entire original soundtrack. Resume existing task IDs and inspect uncertain submissions before retries. Ask before HD unless already explicitly approved.

Face mesh uses local facial landmarks with no depth/SAM calls; combined mode overlays landmarks on the depth composite. Mesh modes need the isolated Python 3.12 worker. Inspect full-clip tracking and, in combined mode, masks. Remove all guidance overlays/depth colors in the generation prompt. Keep independent draft and HD artifacts.
