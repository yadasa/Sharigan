# Using the Sharingan studio

The interface runs on your computer. Preparation uses hosted models, and generation uses the direct Seedance API. Media is uploaded to external providers during these operations; selecting a source and inspecting it locally does not start inference.

## Check setup

Open **API configuration** to inspect Python, preparation packages, Rubber Band, key presence, the optional face-mesh worker and media-host configuration. Follow the instructions for missing requirements and restart the server after editing `.env` or PATH. **Check again** reruns local checks without displaying key values or making paid calls. These checks cannot establish remote account access, balance or hosted model availability.

## Prepare and review

Choose a 4–30 second source with audio. The preview reports duration, dimensions, frame rate, file size and audio presence. The server also checks whether the original audio can be copied unchanged into the final MP4. Fix reported media problems before preparing; clip trimming and cropping are done in your video editor.

- **Depth + SAM** masks selected subjects and composites their colored depth over the original background.
- **Face mesh** tracks expressions on the original video without depth or SAM.
- **Depth + face mesh** adds facial guidance to the depth composite.

Mesh modes require the optional worker and are designed for one centered speaker. The subject prompt `person` includes all detected people; use a more specific description when appropriate. All modes use hosted vocal separation and embed vocals pitched up three semitones in the prepared input.

Watch the entire prepared clip. Compare with the original, select depth or mask previews when available, step through frames, and listen to the audio stems. Review every cut, hair, hands, clothing, feet, background spill, holes and flicker. Mesh modes additionally require checking the eyes, mouth, tracking gaps and alignment throughout. The checklist changes with the actual prepared mode.

**Needs fixing** rejects the current input and blocks submission. In depth modes, **Repair mask from original video** reruns segmentation using RGB detail while preserving the depth colors. This can use provider credits. Repair clears approval before processing, including when the repair fails. Watch and approve the complete repaired input again. For tracking problems, load a new variation and reprepare the source; there is no manual landmark or mask painting editor.

## Map references and submit

Assign each reference to a described subject, such as “the person on the left.” The first reference can be an image or a video; the second must be an image. Video references are playable in the interface. WebM identity references are converted to MP4 video while retaining their role as video references. A video identity supplies appearance only, while the source supplies speech and performance. Input and identity videos must total at most 30 seconds.

**Review submission** validates the media locally and opens the complete prompt, including reference tokens, subject mapping and guidance instructions. It does not upload to a media host or start generation. Editing the form invalidates this preview. Confirm **Submit paid 480p draft** to upload the reviewed inputs and start one generation. The server verifies the preview token, input hashes, reference hashes and API configuration before submission.

## Export and recover

The result player restores the untouched complete original soundtrack. Compare it with the original or download it. A recorded short final-frame hold is disclosed when needed to retain the full audio. Approve a separate paid 1080p generation only after reviewing the draft. The version selector retains access to both outputs. External imports can restore audio, but cannot use the draft upgrade without a direct-API draft task.

**Recent transformations** lists local jobs and supports searching by name or job ID. Rename a transformation in its header. **Processing activity** records durable stage messages. **New variation from this source** loads the source, references and mapping into a fresh workspace without immediately starting processing.

When a saved task ID exists, **Resume draft collection** or **Resume 1080p collection** polls that task without submitting another paid request. The server also resumes collection on startup. Connection failures use bounded polling backoff and expose **Reconnect**. A submitted request without a saved response ID requires inspecting the ModelArk task list; Sharingan blocks automatic resubmission. Interrupted preparation is reported explicitly and is never restarted automatically. Server and CLI collectors must not operate on the same job concurrently.
