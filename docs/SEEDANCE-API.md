# Direct Seedance integration

Sharingan uses BytePlus ModelArk's HTTP API, verified against the official documentation on 2026-10-09:

- [Create task API](https://docs.byteplus.com/en/docs/modelark/create-video-generation-task-api)
- [Get task API](https://docs.byteplus.com/en/docs/modelark/get-video-generation-task-api)
- [Seedance 2.5 tutorial and draft mode](https://docs.byteplus.com/en/docs/modelark/seedance-2-5)

Default base: `https://ark.ap-southeast.bytepluses.com/api/v3`.
Authentication: `Authorization: Bearer SEEDANCE_API_KEY`.
Default model: `dreamina-seedance-2-5-260628`.

## Draft

`POST /contents/generations/tasks` with a JSON body:

```json
{
  "model": "dreamina-seedance-2-5-260628",
  "content": [
    {"type": "text", "text": "Video edit: replace the character in @Video1 with @Image1."},
    {"type": "video_url", "video_url": {"url": "https://YOUR_HOST/source.mp4"}, "role": "reference_video"},
    {"type": "image_url", "image_url": {"url": "https://YOUR_HOST/identity.png"}, "role": "reference_image"}
  ],
  "omni_reference_task_type": "edit",
  "draft": true,
  "resolution": "480p",
  "ratio": "adaptive",
  "duration": -1,
  "generate_audio": true,
  "output_format": "mp4",
  "watermark": false
}
```

The prepared video contains embedded pitched vocals. No standalone audio is submitted. The returned `id` is persisted in `seedance-response.json`; provider headers/keys are never persisted. `generation.json` includes the exact augmented prompt and task origin.

For a video identity, send a second `video_url` item with role `reference_video`. The prompt specifies source `@Video1`, identity `@Video2` (appearance only), and the optional secondary `@Image1`. With image identity, secondary image is `@Image2`. Both reference types remain video-edit tasks.

Input videos must be MP4/MOV, each 4–30 seconds for editing, with a combined duration at most 30 seconds, 24–60 fps, valid provider dimensions/pixel counts and at most 200 MB each. A source near 30 seconds leaves no duration budget for a second video. Public hosts have their own lower file-size/expiry limits. Provider account access and content requirements still apply.

## Poll and retrieve

`GET /contents/generations/tasks/{id}`. Poll queued/running tasks. On `succeeded`, download `content.video_url` and restore original audio. Terminal `failed`, `cancelled` and `expired` states are errors. Transient polling connection errors/429/5xx can be retried; paid creation POSTs are never automatically retried.

## Approved final

After the user reviews the completed draft and explicitly approves HD, POST:

```json
{
  "model": "dreamina-seedance-2-5-260628",
  "content": [{"type": "draft_task", "draft_task": {"id": "SAVED_DRAFT_TASK_ID"}}],
  "resolution": "1080p",
  "output_format": "mp4",
  "watermark": false
}
```

Use the draft's original model. Do not resend prompt, references, ratio, duration, generate_audio or task type; the service reuses them. Draft IDs are valid for seven days. Draft and HD requests/results are kept separately; both exports restore original audio. Provider 1080p output may use HEVC/10-bit color, so browser playback support depends on the installed codec. The MP4 download remains available for compatible players.

## Recovery and local API

Requests are written exclusively before transmission to prevent duplicate submissions, including concurrent attempts and ambiguous network outcomes. A saved request without a response ID requires inspecting the ModelArk task list. If you locate the task, save its confirmed `id` in the corresponding response file and resume collection. Do not delete request guards just to try again.

Startup resumes saved task collection without paid submissions. CLI: `workflow.py resume JOB` or `workflow.py resume JOB --hd`. Do not collect concurrently through the server and CLI.

- `POST /jobs`: video, subject prompt, depth provider, preparation mode.
- `POST /jobs/{id}/mask-review`: approved, fingerprint, note.
- `POST /jobs/{id}/seedance`: prompt, reference, optional second_reference.
- `POST /jobs/{id}/hd`: explicit approval to create the final.
- `GET /configuration`: key presence and model only; no secrets.
