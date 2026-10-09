# Sharingan video workflow

For installation/onboarding, follow `docs/SETUP-AGENT.md`. Do not run paid inference during setup. Distinguish a running UI from generation-ready configuration. Never expose credentials.

Carry authorized jobs through preparation, visual quality review, generation and delivery. Ask only for missing creative choices or submission approval not already given. Never automatically purchase a 1080p final; explicit HD approval is required.

1. Preserve the source file and complete original audio.
2. Isolate vocals with hosted Demucs, pitch +3 semitones with timing preserved, and embed them in the prepared video. Do not attach standalone audio to Seedance.
3. Generate colored depth with `lucataco/depth-anything-video` and retain its exact colors. Obtain raw SAM 3 masks. If depth segmentation loses the subject or includes background, repair using original RGB detail and composite the original colored depth through those masks. Record the fallback.
4. Mandatory full-clip visual QA before every generation: inspect all cuts, extremities, hair, hands, clothing, background spill, holes, alignment and flicker. Automated checks/contact sheets cannot establish full-clip approval. Repair and review again. Bind approval to current artifacts with `mask_review`. If an agent cannot inspect full video, request user review through the UI without claiming agent approval.
5. Match references and prompt to actual subjects. Use generic character names and user-provided identity references. Never carry over previous subject mappings.
6. Show the exact creative prompt before submission. Honor existing authorization. Submit a 480p Seedance 2.5 draft through the direct ModelArk API using the reviewed prepared video.
7. Retrieve the result and restore the entire untouched source audio, discarding generated audio. Preserve draft artifacts. Report failures honestly.
8. Only after explicit approval, create the 1080p final using the saved draft task ID, then restore original audio again.
9. Show final preview/download. Persist status and keep preview selection stable. Resume saved requests instead of requeueing; never retry a paid POST automatically.

## Direct API reference routing

Read `docs/SEEDANCE-API.md`. The source is `@Video1` with role `reference_video`. A video identity stays a video and becomes `@Video2`, appearance only. An image identity is `@Image1`; the optional secondary image is `@Image2` or `@Image1` when the primary identity is a video. Both use `omni_reference_task_type=edit`, `ratio=adaptive`, `duration=-1`. Do not extract pictures from video references without permission. Keep full original audio in the final export and disclose any recorded last-frame hold.

## Face mesh and combined mode

Fast face mesh preserves the normalized original video, tracks landmarks, draws guidance, and embeds +3 pitched vocals. It makes no depth or SAM calls. Install its optional Python 3.12 worker using `bash setup-face-mesh.sh`. The model downloads from Google's official storage. Designed for one centered speaker; inspect all frames and stop on tracking gaps or incorrect alignment. Review tracking and audio rather than claiming mask review.

Combined mode runs depth/SAM then overlays face tracking from original frames. Review both mask coverage and tracking. Artifact hashes include depth, masks, landmarks, overlay and embedded audio. Prompts must remove all guidance lines/depth colors and replace the whole identity including hair. Keep all three modes available and retain draft → explicitly approved HD → source-audio restoration.
