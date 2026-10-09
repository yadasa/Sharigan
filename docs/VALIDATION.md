# Validation

The Sharingan migration replaces the provider adapter with direct ModelArk requests and adds an independent dark UI, generic reference fields, original SVG branding and opt-in synthesized sounds.

Automated validation covers direct Bearer authentication, request shapes, image/video reference routing, draft completion, collection and source-audio restoration, duplicate/uncertain-submission guards, mesh guidance, review fingerprints, hosting fallback and media alignment. The audio test checks original compressed audio packets byte for byte after export.

Direct task creation/polling and draft completion are based on official ModelArk documentation. External API calls are mocked in the automated suite. No paid direct Seedance generation was performed as part of this migration. Actual generation requires the user's API keys, model access, sufficient balance, valid media and complete visual input review.

Mesh modes remain experimental for one centered speaker. Public hosting availability and provider account/content restrictions are external dependencies. 1080p HEVC browser support varies. The localhost server is single-user, with process-local workers rather than a durable distributed queue.

## Local verification on 2026-10-09

- 28 automated tests passed on Windows with Python 3.12.8 and the pinned requirements.
- The standalone compositor check passed, including subject selection, retained background and aligned output frames.
- JavaScript syntax checking passed. The localhost health/static routes and generic reference form schema passed.
- Desktop and 390-pixel mobile layouts were visually inspected in Chrome. The configuration modal and opt-in sound toggle worked, with no captured browser console errors.
- Source scan found no previous company/provider branding. Only current source/assets are committed; credentials, runtime jobs and environments are ignored.
- No paid Seedance or preprocessing job was submitted. This machine currently lacks Rubber Band and populated provider keys; the local UI is running, while generation readiness still requires those prerequisites. Optional mesh worker setup was not performed.

See the [studio preview](studio-preview.jpg).
