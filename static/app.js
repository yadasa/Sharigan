const $ = selector => document.querySelector(selector);
const field = (form, name) => $(form).elements.namedItem(name);
const validId = value => /^[a-f0-9]{32}$/.test(value || '');
const query = new URLSearchParams(location.search);
let jobId = validId(query.get('job')) ? query.get('job') : null;
let configuration = null, current = null, saved = {}, busy = false, pending = false;
let sourceValid = false, formLoaded = false, selectedPreview = 'seedance-input.mp4';
let previewToken = null, formRevision = 0, pollTimer, failures = 0, historyItems = [], actionError = null;
let sourceInspection = 0, audioKey = '', mediaUrls = new Map();
const modes = {
  depth: 'Depth + SAM masks the selected subjects and replaces their appearance while retaining the background.',
  face_mesh: 'Face mesh guides expressions on the original video without depth or SAM. Requires the optional worker and works best with one centered speaker.',
  depth_mesh: 'Combined mode adds facial motion guidance to the depth composite. Requires the optional worker and a full review of both masks and tracking.'
};
function status(message, error = false) {
  $('#status-text').textContent = message;
  $('#status').classList.toggle('error', error);
}
function reportError(error) { actionError = error.message; status(actionError, true); }
async function json(url, options) {
  const response = await fetch(url, {cache: 'no-store', ...options});
  let result;
  try { result = await response.json(); } catch { throw Error('The server returned an unreadable response. Reconnect to check the saved job.'); }
  if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'The request could not be completed. Check the selected files and try again.');
  return result;
}
function setVideo(video, url) {
  if (url && video.getAttribute('src') !== url) video.src = url;
}
function objectUrl(name, file) {
  if (mediaUrls.has(name)) URL.revokeObjectURL(mediaUrls.get(name));
  const url = URL.createObjectURL(file);
  mediaUrls.set(name, url);
  return url;
}
function invalidatePreview() {
  formRevision++;
  previewToken = null;
  $('#confirm-draft').disabled = true;
  if ($('#submission-dialog').open) $('#submission-dialog').close();
}
function referenceVideo() {
  const selected = field('#seedance', 'reference').files[0];
  return selected ? selected.type.startsWith('video/') || /\.(mp4|mov|webm)$/i.test(selected.name) : /\.(mp4|mov|webm)$/i.test(saved.reference?.file || '');
}
function showReference(name, url, video) {
  const image = $('#' + name + '-img'), player = $('#' + name + '-video');
  $('#' + name + '-preview').hidden = !url;
  image.hidden = !url || video;
  player.hidden = !url || !video;
  if (url && video) setVideo(player, url);
  else if (url) image.src = url;
  else { player.pause(); player.removeAttribute('src'); image.removeAttribute('src'); }
  const primaryVideo = referenceVideo();
  $('#mode-label').textContent = primaryVideo ? 'Video identity reference' : 'Image identity reference';
  $('#primary-token').textContent = (primaryVideo ? '@Video2' : '@Image1') + ' supplies this character’s appearance.';
  $('#secondary-token').textContent = (primaryVideo ? '@Image1' : '@Image2') + ' supplies this character’s appearance.';
}
function updateButtons() {
  const mode = field('#form', 'mode').value;
  $('#mode-help').textContent = modes[mode];
  const ready = Boolean(configuration?.modes[mode]);
  $('#go').disabled = busy || pending || !ready || !sourceValid;
  $('#prepare-reason').textContent = !ready ? 'Open API configuration to resolve the missing preparation requirements.' :
    !sourceValid ? current ? 'Use “New variation from this source” to prepare this clip again.' : 'Choose a valid source video before preparing.' : busy ? 'Wait for the current operation to finish.' : 'Preparation creates reviewable guidance and pitched vocals.';
  $('#setup-banner').hidden = ready;
  $('#setup-message').textContent = !configuration ? 'Checking requirements for the selected method…' :
    configuration.checks.filter(c => !c.ready && ['python','packages','rubberband','REPLICATE_API_TOKEN', ...(mode !== 'depth' ? ['mesh'] : [])].includes(c.id)).map(c => c.label).join(', ') + '.';
  const hasReference = Boolean(field('#seedance', 'reference').files.length || saved.reference);
  const hasSecond = Boolean(field('#seedance', 'second_reference').files.length || saved.second_reference);
  field('#seedance', 'subject_two').required = hasSecond;
  let reason = 'Review the complete prompt before confirming the paid draft.';
  if (!current?.files['seedance-input.mp4']) reason = 'Prepare a source video first.';
  else if (!current.review.approved) reason = 'Review the full input and approve it first.';
  else if (current.attempted) reason = 'This transformation already has a submission attempt. Resume its task or create a new variation.';
  else if (!configuration?.generation_ready) reason = 'Configure the Seedance key and media host before generating.';
  else if (failures) reason = 'Reconnect to verify the saved job before reviewing another submission.';
  else if (!hasReference) reason = 'Choose the first character reference and describe the subject it replaces.';
  else if (busy || pending) reason = 'Wait for the current operation to finish.';
  $('#draft-reason').textContent = reason;
  $('#draft-button').disabled = !current?.files['seedance-input.mp4'] || !current?.review.approved || current?.attempted ||
    !configuration?.generation_ready || !hasReference || busy || pending || failures > 0;
  const reviewLocked = busy || pending || current?.attempted;
  $('#approve-mask').disabled = reviewLocked || !$('#review-check').checked || !current?.review.fingerprint;
  $('#reject-mask').disabled = reviewLocked;
  $('#repair-mask').disabled = busy || pending || !configuration?.modes[current?.mode || mode];
  $('#upgrade').disabled = busy || pending || !current?.can_hd || !configuration?.generation_ready;
  for (const id of ['resume-draft', 'resume-hd']) $('#' + id).disabled = busy || pending;
}
async function loadConfiguration() {
  $('#configuration-refresh').disabled = true;
  try {
    configuration = await json('/configuration');
    const ready = configuration.modes.depth && configuration.generation_ready;
    $('#connection-label').textContent = ready ? 'Local requirements are ready for depth preparation and generation.' : 'Some requirements need setup.';
    $('#connection-detail').textContent = configuration.note;
    $('#model-name').textContent = configuration.model;
    $('#media-hosts').textContent = configuration.media_hosts.join(', ');
    $('#setup-checks').replaceChildren();
    for (const check of configuration.checks) {
      const row = document.createElement('div'); row.className = 'setup-check' + (check.ready ? ' ready' : '');
      const title = document.createElement('strong'); title.textContent = check.label;
      const state = document.createElement('span'); state.textContent = check.ready ? 'Ready locally' : 'Needs setup'; title.append(state);
      const help = document.createElement('p'); help.textContent = check.help;
      row.append(title, help); $('#setup-checks').append(row);
    }
    for (const option of field('#form', 'mode').options) {
      option.textContent = ({depth:'Depth + SAM', face_mesh:'Face mesh', depth_mesh:'Depth + face mesh'})[option.value] +
        (configuration.modes[option.value] ? '' : ' (setup required)');
      option.disabled = !configuration.modes[option.value];
    }
  } catch (error) { $('#connection-label').textContent = error.message; }
  finally { $('#configuration-refresh').disabled = false; updateButtons(); }
}
async function inspectSource(file) {
  const request = ++sourceInspection;
  sourceValid = false;
  $('#source-video').hidden = false;
  setVideo($('#source-video'), objectUrl('source', file));
  $('#source-info').textContent = 'Checking duration, framing and audio on the local server…';
  $('#source-info').classList.remove('error'); updateButtons();
  const data = new FormData(); data.set('video', file);
  try {
    const info = await json('/media/inspect', {method:'POST', body:data});
    if (request !== sourceInspection) return;
    sourceValid = info.valid;
    $('#source-info').textContent = `${info.duration.toFixed(2)} s · ${info.width} × ${info.height} · ${info.fps} fps · ${info.audio ? 'Audio present' : 'No audio'} · ${(info.bytes / 1048576).toFixed(1)} MB` +
      (info.issues.length ? '\n' + info.issues.join(' ') : '\nReady for preparation. Video is normalized to 24 fps.');
    $('#source-info').classList.toggle('error', !info.valid);
  } catch (error) { if (request === sourceInspection) { $('#source-info').textContent = error.message; $('#source-info').classList.add('error'); } }
  updateButtons();
}
for (const input of document.querySelectorAll('input[type=file]')) {
  input.addEventListener('change', () => {
    const file = input.files[0]; if (!file) return;
    input.closest('.upload').querySelector('[data-filename]').textContent = file.name;
    if (input.form.id === 'form') inspectSource(file);
    else if (input.form.id === 'seedance') {
      invalidatePreview(); saved[input.name] = null;
      showReference(input.name, objectUrl(input.name, file), file.type.startsWith('video/') || /\.(mp4|mov|webm)$/i.test(file.name));
      updateButtons();
    }
  });
}
field('#form', 'mode').onchange = updateButtons;
$('#seedance').addEventListener('input', () => { invalidatePreview(); updateButtons(); });
$('#remove-second').onclick = () => {
  field('#seedance', 'second_reference').value = '';
  field('#seedance', 'subject_two').value = '';
  saved.second_reference = null;
  field('#seedance', 'second_reference').closest('.upload').querySelector('small').textContent = 'Optional · PNG, JPG or WebP';
  showReference('second_reference', null, false); invalidatePreview(); updateButtons();
};
function renderSteps(data) {
  const prepared = Boolean(data.files['seedance-input.mp4']);
  const draft = Boolean(data.files['final-preview.mp4']), hd = Boolean(data.files['hd/final-preview.mp4']);
  const states = {
    source: prepared ? 'complete' : data.job.state === 'error' ? 'error' : 'active',
    review: data.review.approved ? 'complete' : prepared ? 'active' : '',
    draft: draft ? 'complete' : data.attempted || data.job.stage === 'draft' ? data.job.state === 'error' ? 'error' : 'active' : data.review.approved ? 'active' : '',
    final: hd ? 'complete' : draft ? 'active' : ''
  };
  const labels = {source: prepared ? 'Prepared' : data.job.state === 'running' ? 'Preparing' : 'Needs attention',
    review: data.review.approved ? 'Approved' : prepared ? 'Review required' : 'Waiting',
    draft: draft ? 'Ready' : data.attempted ? data.job.state === 'running' ? 'Rendering' : 'Check task' : data.review.approved ? 'Add references' : 'Waiting',
    final: hd ? '1080p ready' : data.hd.state === 'running' ? 'Rendering 1080p' : draft ? 'Draft available' : 'Waiting'};
  for (const link of document.querySelectorAll('[data-step]')) {
    link.className = states[link.dataset.step];
    link.querySelector('small').textContent = labels[link.dataset.step];
    if (states[link.dataset.step] === 'active') link.setAttribute('aria-current','step'); else link.removeAttribute('aria-current');
  }
}
function renderInput(data) {
  const files = data.files;
  const ready = Boolean(files['seedance-input.mp4']) && !(data.job.state === 'running' && data.job.stage === 'preparation');
  $('#input-ready').hidden = !ready; $('#input-empty').hidden = ready;
  if (!ready) return;
  const previews = [['seedance-input.mp4','Prepared input'], ['original.mp4','Original'], ['depth.mp4','Depth'], ['mask.mp4','Mask']].filter(([name]) => files[name]);
  if (!previews.some(([name]) => name === selectedPreview)) selectedPreview = previews[0][0];
  $('#tabs').replaceChildren();
  const choose = (name, title) => {
    selectedPreview = name;
    for (const button of $('#tabs').children) { const active = button.dataset.file === name; button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active)); }
    const revision = name === 'original.mp4' ? '' : '?v=' + (data.review.fingerprint || 'pending');
    setVideo($('#input-video'), files[name] + revision);
    $('#input-caption').textContent = title + (name === 'seedance-input.mp4' ? ' · vocals pitched +3 semitones' : '');
    $('#input-download').href = files[name];
  };
  for (const [name, title] of previews) {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = title; button.dataset.file = name;
    button.onclick = () => choose(name, title); $('#tabs').append(button);
  }
  choose(...previews.find(([name]) => name === selectedPreview));
  setVideo($('#input-original'), files['original.mp4']);
  $('#mask-review-status').textContent = data.review.note || data.review.status;
  if (document.activeElement !== $('#review-check')) $('#review-check').checked = Boolean(data.review.approved);
  const checks = [];
  if (data.mode !== 'face_mesh') checks.push('Inspect hair, hands, clothing and feet for complete subject coverage.', 'Check background spill, holes, flicker and alignment through every cut.');
  if (data.mode !== 'depth') checks.push('Check that eyes, mouth and facial landmarks stay aligned throughout.', 'Reject tracking gaps, incorrect faces and jumps between cuts.');
  checks.push('Listen to the complete embedded vocals and check timing against the source.');
  $('#review-checklist').replaceChildren(...checks.map(text => { const item = document.createElement('li'); item.textContent = text; return item; }));
  $('#repair-mask').hidden = !data.can_repair;
  $('#repair-help').textContent = data.attempted ? 'This submitted input is locked. Start a new variation to change its guidance.' :
    data.mode === 'face_mesh' ? 'For tracking problems, use “New variation from this source” to prepare and review it again.' :
    'Repair rebuilds segmentation from original RGB detail, preserves depth colors, and requires another full-clip review. Hosted calls may use provider credits.';
  const stems = [['vocals.wav','Isolated vocals'],['vocals-plus3.wav','Vocals pitched +3'],['music.wav','Music stem']].filter(([file]) => files[file]);
  const key = JSON.stringify(stems);
  if (key !== audioKey) {
    audioKey = key; $('#audio-links').replaceChildren();
    for (const [name, title] of stems) {
      const wrap = document.createElement('div'), label = document.createElement('strong'), audio = document.createElement('audio'), link = document.createElement('a');
      label.textContent = title; audio.controls = true; audio.preload = 'none'; audio.src = files[name]; audio.setAttribute('aria-label', title);
      link.href = files[name]; link.download = name; link.textContent = 'Download stem'; wrap.append(label, audio, link); $('#audio-links').append(wrap);
    }
  }
  comparison('input');
}
function renderResult(data) {
  const versions = [['final-preview.mp4',data.generation.request_id ? '480p draft' : 'Imported result'],['hd/final-preview.mp4','1080p final']].filter(([name]) => data.files[name]);
  $('#final-ready').hidden = !versions.length; $('#final-empty').hidden = Boolean(versions.length);
  if (!versions.length) return;
  const select = $('#result-version'), previous = select.value;
  select.replaceChildren(...versions.map(([name, title]) => { const option = document.createElement('option'); option.value = name; option.textContent = title; return option; }));
  select.value = versions.some(([name]) => name === previous) ? previous : versions.at(-1)[0];
  select.onchange = () => {
    const name = select.value, hd = name.startsWith('hd/');
    setVideo($('#final-video'), data.files[name]); setVideo($('#final-original'), data.files['original.mp4'] || data.files['upload.mp4']);
    $('#quality-label').textContent = (hd ? '1080p final' : data.generation.request_id ? '480p draft' : 'Imported result') + ' · original audio';
    $('#final-download').href = data.files[name]; $('#final-download').textContent = hd ? 'Download 1080p final' : 'Download ' + (data.generation.request_id ? 'draft' : 'imported result');
    const raw = data.files[hd ? 'hd/seedance-result.mp4' : 'seedance-result.mp4'];
    $('#raw-link').hidden = !raw; if (raw) $('#raw-link').href = raw;
    const adjustment = hd ? data.hd_adjustment : data.adjustment;
    $('#duration-note').hidden = !adjustment.seconds;
    $('#duration-note').textContent = adjustment.seconds ? `The final frame is held for ${Number(adjustment.seconds).toFixed(2)} seconds to preserve the complete original audio without stretching or trimming it.` : '';
    comparison('final');
  };
  select.onchange();
  $('#hd-reason').textContent = !data.generation.request_id ? 'Imported results have no direct-API draft task and cannot be upgraded here.' :
    data.files['hd/final-preview.mp4'] ? '1080p is ready. Use the version selector to switch between the draft and final.' :
    data.hd_attempted ? 'A 1080p submission was already attempted. Resume collection of its saved task when available.' : 'Approve this draft to start a separate paid 1080p generation.';
  $('#upgrade-status').textContent = data.hd.state !== 'idle' ? data.hd.status : '';
}
function renderJob(data) {
  current = data; busy = data.job.state === 'running' || data.hd.state === 'running';
  $('#job-actions').hidden = false; $('#reuse-source').href = '/?reuse=' + jobId;
  $('#resume-draft').hidden = !data.can_resume; $('#resume-hd').hidden = !data.can_resume_hd;
  const uncertain = data.attempted && !data.generation.request_id && !data.can_resume && !data.files['final-preview.mp4'];
  $('#submission-warning').hidden = !uncertain;
  $('#submission-warning').textContent = 'Submission outcome needs inspection in ModelArk. Sharingan will not send the request again.';
  $('#rename-form').hidden = false; $('#new-title').hidden = true;
  if (document.activeElement !== $('#project-name')) $('#project-name').value = data.meta.name || 'Untitled transformation';
  if (!formLoaded) {
    formLoaded = true;
    field('#form', 'mode').value = data.mode; field('#form', 'prompt').value = data.meta.subject || 'person';
    field('#form', 'provider').value = data.meta.provider || 'replicate';
    for (const key of ['prompt','subject_one','subject_two']) if (data.form[key]) field('#seedance',key).value = data.form[key];
    saved = {...data.references};
    for (const name of ['reference','second_reference']) if (saved[name]) {
      showReference(name, saved[name].url, /\.(mp4|mov|webm)$/i.test(saved[name].file));
      field('#seedance',name).closest('.upload').querySelector('small').textContent = 'Saved reference: ' + saved[name].file;
    }
    if (data.files['upload.mp4']) { $('#source-video').hidden = false; setVideo($('#source-video'), data.files['upload.mp4']); }
    if (data.meta.media) { const info = data.meta.media; $('#source-info').textContent = `${data.meta.source_name} · ${info.duration} s · ${info.width} × ${info.height} · ${info.fps} fps · Audio preserved`; }
  }
  $('#sent-details').hidden = !data.generation.request_id;
  if (data.generation.request_id) { $('#generation-id').textContent = 'Seedance task: ' + data.generation.request_id; $('#sent-prompt').textContent = data.generation.prompt; }
  renderInput(data); renderResult(data); renderSteps(data);
  const events = [...(data.job.events || []), ...(data.hd.events || [])].sort((a,b) => a.time.localeCompare(b.time));
  $('#activity-panel').hidden = !events.length;
  $('#activity').replaceChildren(...events.map(event => { const li = document.createElement('li'), time = document.createElement('time'); time.dateTime = event.time; time.textContent = new Date(event.time).toLocaleTimeString(); li.append(time, document.createTextNode(event.message)); return li; }));
  const active = data.hd.state !== 'idle' ? data.hd : data.job;
  if (actionError) status(actionError, true); else status(active.status, ['error','interrupted'].includes(active.state));
  updateButtons();
}
async function loadJob() {
  clearTimeout(pollTimer); if (!jobId) return;
  try {
    renderJob(await json('/jobs/' + jobId + '/details'));
    failures = 0; $('#reconnect').hidden = true;
    if (busy) pollTimer = setTimeout(loadJob, 3000);
  } catch (error) {
    status(error.message + ' Reconnecting to the saved transformation…', true); $('#reconnect').hidden = false;
    pollTimer = setTimeout(loadJob, Math.min(30000, 3000 * 2 ** failures++));
  }
}
$('#reconnect').onclick = () => { actionError = null; loadJob(); };
function comparison(kind) {
  const enabled = $('#' + (kind === 'input' ? 'compare-input' : 'compare-final')).checked;
  $('#' + kind + '-original-wrap').hidden = !enabled;
  $('#' + kind + '-comparison').classList.toggle('single', !enabled);
  if (!enabled) $('#' + kind + '-original').pause();
}
for (const kind of ['input','final']) {
  const video = $('#' + kind + '-video'), original = $('#' + kind + '-original');
  const enabled = () => !$('#' + kind + '-original-wrap').hidden;
  const sync = (force = false) => { if (enabled() && original.readyState && Math.abs(original.currentTime - video.currentTime) > (force ? .0001 : .06)) original.currentTime = video.currentTime; };
  video.addEventListener('play', () => { if (enabled()) { sync(true); original.play().catch(() => {}); } });
  video.addEventListener('pause', () => original.pause());
  video.addEventListener('ratechange', () => { original.playbackRate = video.playbackRate; });
  video.addEventListener('seeking', () => sync(true)); video.addEventListener('seeked', () => sync(true));
  video.addEventListener('timeupdate', () => sync()); original.addEventListener('loadedmetadata', () => sync(true));
  $('#' + (kind === 'input' ? 'compare-input' : 'compare-final')).onchange = () => { comparison(kind); sync(true); if (enabled() && !video.paused) original.play().catch(() => {}); };
}
for (const button of document.querySelectorAll('.frame-step')) button.onclick = () => {
  const video = $('#input-video'); video.pause();
  if (Number.isFinite(video.duration)) video.currentTime = Math.min(video.duration, Math.max(0, video.currentTime + Number(button.dataset.delta) / 24));
};
$('#form').onsubmit = async event => {
  event.preventDefault(); if (!sourceValid || pending || busy) return;
  actionError = null; pending = true; updateButtons(); status('Uploading the source to the local server for preparation…');
  try {
    const result = await json('/jobs', {method:'POST',body:new FormData(event.target)});
    jobId = result.id; history.replaceState(null,'','/?job=' + jobId);
    current = null; formLoaded = true; audioKey = ''; selectedPreview = 'seedance-input.mp4'; invalidatePreview();
    await loadJob();
  }
  catch (error) { reportError(error); }
  finally { pending = false; updateButtons(); }
};
async function referenceData() {
  const data = new FormData($('#seedance'));
  for (const name of ['reference','second_reference']) if (!field('#seedance',name).files.length) {
    if (saved[name]) {
      const response = await fetch(saved[name].url); if (!response.ok) throw Error('The saved reference is unavailable. Choose the file again.');
      data.set(name, new File([await response.blob()],saved[name].file));
    } else if (name === 'second_reference') data.delete(name);
    else throw Error('Choose the first character reference.');
  }
  return data;
}
$('#seedance').onsubmit = async event => {
  event.preventDefault(); if (!jobId || pending || busy) return;
  const revision = formRevision; actionError = null; pending = true; updateButtons(); status('Validating references and building the exact prompt locally…');
  try {
    const result = await json('/jobs/' + jobId + '/preview', {method:'POST',body:await referenceData()});
    if (revision !== formRevision) throw Error('The form changed during validation. Review the updated submission again.');
    previewToken = result.token; $('#preview-prompt').textContent = result.prompt;
    $('#submission-specs').textContent = result.model + ' · ' + result.resolution + ' draft';
    $('#submission-note').textContent = result.note; $('#confirm-draft').disabled = false;
    $('#submission-dialog').showModal(); status('Submission preview ready. No generation has been started.');
  } catch (error) { reportError(error); }
  finally { pending = false; updateButtons(); }
};
$('#confirm-draft').onclick = async () => {
  if (!previewToken || pending || busy) return;
  const token = previewToken; actionError = null; previewToken = null; pending = true;
  $('#confirm-draft').disabled = true; $('#submission-dialog').close(); updateButtons();
  const data = new FormData(); data.set('preview_token',token);
  try { status('Submitting the reviewed paid draft…'); await json('/jobs/' + jobId + '/seedance',{method:'POST',body:data}); playSfx('activate'); }
  catch (error) { reportError(error); }
  finally { pending = false; await loadJob(); updateButtons(); }
};
async function saveReview(approved) {
  if (!current || pending || busy) return;
  actionError = null; pending = true; invalidatePreview(); updateButtons();
  const data = new FormData(); data.set('approved',String(approved)); data.set('fingerprint',current.review.fingerprint);
  data.set('note',approved ? 'Input approved after full-clip visual and audio review.' : 'Input rejected. Repair the mask or prepare a new source before generating.');
  try { await json('/jobs/' + jobId + '/mask-review',{method:'POST',body:data}); if (approved) playSfx('approve'); }
  catch (error) { reportError(error); }
  finally { pending = false; await loadJob(); }
}
$('#review-check').onchange = updateButtons;
$('#approve-mask').onclick = () => saveReview(true); $('#reject-mask').onclick = () => saveReview(false);
function confirmAction(title,message,label,action) {
  $('#confirm-title').textContent = title; $('#confirm-message').textContent = message; $('#confirm-action').textContent = label;
  $('#confirm-action').onclick = async () => { $('#confirm-dialog').close(); actionError = null; pending = true; updateButtons(); try { await action(); } catch (error) { reportError(error); } finally { pending = false; await loadJob(); } };
  $('#confirm-dialog').showModal();
}
$('#repair-mask').onclick = () => confirmAction('Repair the subject mask', 'Rebuild segmentation using original video detail while preserving the depth colors. This may use hosted provider credits. Your current approval will be cleared, and you must review the full repaired clip.', 'Rebuild mask', async () => { invalidatePreview(); await json('/jobs/' + jobId + '/repair',{method:'POST'}); });
$('#upgrade').onclick = () => confirmAction('Generate the approved draft in 1080p', 'This starts a separate paid generation from the saved draft task. The draft is preserved and the complete original soundtrack will be restored to the final.', 'Approve & submit paid 1080p', async () => { await json('/jobs/' + jobId + '/hd',{method:'POST'}); });
for (const [id,hd] of [['resume-draft',false],['resume-hd',true]]) $('#' + id).onclick = async () => {
  actionError = null; pending = true; updateButtons(); const data = new FormData(); data.set('hd',String(hd));
  try { await json('/jobs/' + jobId + '/resume',{method:'POST',body:data}); }
  catch (error) { reportError(error); }
  finally { pending = false; await loadJob(); }
};
$('#finish').onsubmit = async event => {
  event.preventDefault(); if (!jobId) { status('Prepare the original source before importing a result.',true); return; }
  if (pending || busy) return; actionError = null; pending = true; updateButtons();
  const button = event.target.querySelector('button'); button.disabled = true;
  try { await json('/jobs/' + jobId + '/finish',{method:'POST',body:new FormData(event.target)}); }
  catch (error) { reportError(error); }
  finally { pending = false; button.disabled = false; await loadJob(); }
};
$('#rename-form').onsubmit = async event => {
  event.preventDefault(); const data = new FormData(); data.set('name',$('#project-name').value);
  try { await json('/jobs/' + jobId + '/name',{method:'POST',body:data}); status('Transformation name saved.'); }
  catch (error) { reportError(error); }
};
function renderHistory() {
  const search = $('#history-search').value.toLowerCase();
  const items = historyItems.filter(item => (item.name + ' ' + item.id).toLowerCase().includes(search));
  $('#history-list').replaceChildren();
  if (!items.length) { $('#history-list').textContent = historyItems.length ? 'No transformations match your search.' : 'No transformations have been saved yet.'; return; }
  for (const item of items) {
    const link = document.createElement('a'); link.className = 'history-item'; link.href = '/?job=' + item.id;
    const title = document.createElement('strong'), detail = document.createElement('small'); title.textContent = item.name;
    detail.textContent = `${item.quality} · ${new Date(item.created_at).toLocaleString()} · ${item.status}`;
    link.append(title,detail); $('#history-list').append(link);
  }
}
async function openHistory() {
  $('#history-dialog').showModal(); $('#history-list').textContent = 'Loading saved transformations…';
  try { historyItems = await json('/jobs'); renderHistory(); } catch (error) { $('#history-list').textContent = error.message; }
}
$('#history-search').oninput = renderHistory;
for (const id of ['history-open','mobile-history']) $('#' + id).onclick = openHistory;
for (const id of ['settings-open','mobile-settings','setup-open']) $('#' + id).onclick = () => $('#settings-dialog').showModal();
for (const id of ['help-open','footer-help']) $('#' + id).onclick = () => $('#help-dialog').showModal();
$('#configuration-refresh').onclick = loadConfiguration;
for (const button of document.querySelectorAll('[data-close]')) button.onclick = () => $('#' + button.dataset.close).close();
for (const dialog of document.querySelectorAll('dialog')) dialog.addEventListener('click',event => { if (event.target === dialog) { const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close(); } });
async function reuseSource(ident) {
  try {
    const data = await json('/jobs/' + ident + '/details');
    const response = await fetch(data.files['upload.mp4']); if (!response.ok) throw Error('The saved source is unavailable.');
    const source = new File([await response.blob()],data.meta.source_name || 'source.mp4',{type:'video/mp4'});
    const transfer = new DataTransfer(); transfer.items.add(source); field('#form','video').files = transfer.files;
    field('#form','video').closest('.upload').querySelector('small').textContent = source.name;
    field('#form','name').value = (data.meta.name || 'Transformation') + ' variation';
    field('#form','mode').value = data.mode; field('#form','prompt').value = data.meta.subject || 'person';
    field('#form','provider').value = data.meta.provider || 'replicate';
    saved = {...data.references};
    for (const key of ['prompt','subject_one','subject_two']) if (data.form[key]) field('#seedance',key).value = data.form[key];
    for (const name of ['reference','second_reference']) if (saved[name]) showReference(name,saved[name].url,/\.(mp4|mov|webm)$/i.test(saved[name].file));
    await inspectSource(source); status('Source and references loaded. Review the settings before preparing a new transformation.');
  } catch (error) { reportError(error); }
}

// Original synthesized cues, silent until explicitly enabled.
let soundEnabled = false, audioContext;
try { soundEnabled = localStorage.getItem('sharingan-sound') === 'on'; } catch {}
function updateSound() { $('#sound-toggle').setAttribute('aria-pressed',String(soundEnabled)); $('#sound-toggle').textContent = soundEnabled ? 'Sound on' : 'Sound off'; }
function playSfx(kind = 'activate') {
  if (!soundEnabled) return;
  try {
    const Audio = window.AudioContext || window.webkitAudioContext; if (!Audio) return;
    audioContext ??= new Audio(); audioContext.resume(); const time = audioContext.currentTime;
    const oscillator = audioContext.createOscillator(), gain = audioContext.createGain(); oscillator.connect(gain); gain.connect(audioContext.destination);
    oscillator.type = 'sine'; oscillator.frequency.setValueAtTime(kind === 'approve' ? 440 : 160,time); oscillator.frequency.exponentialRampToValueAtTime(kind === 'approve' ? 880 : 56,time + .45);
    gain.gain.setValueAtTime(.0001,time); gain.gain.exponentialRampToValueAtTime(.12,time + .025); gain.gain.exponentialRampToValueAtTime(.0001,time + .6); oscillator.start(time); oscillator.stop(time + .65);
    const size = audioContext.sampleRate * .35, buffer = audioContext.createBuffer(1,size,audioContext.sampleRate), samples = buffer.getChannelData(0);
    for (let i = 0; i < size; i++) samples[i] = (Math.random() * 2 - 1) * (1 - i / size);
    const noise = audioContext.createBufferSource(), filter = audioContext.createBiquadFilter(), level = audioContext.createGain(); noise.buffer = buffer; filter.type = 'bandpass'; filter.frequency.setValueAtTime(2400,time); filter.frequency.exponentialRampToValueAtTime(180,time + .35); level.gain.value = .035;
    noise.connect(filter); filter.connect(level); level.connect(audioContext.destination); noise.start(time); noise.stop(time + .35);
  } catch {}
}
updateSound(); $('#sound-toggle').onclick = () => { soundEnabled = !soundEnabled; try { localStorage.setItem('sharingan-sound',soundEnabled ? 'on' : 'off'); } catch {} updateSound(); playSfx(); };
$('#eye-activate').onclick = () => { playSfx(); const eye = $('#eye-activate'); eye.classList.remove('activated'); void eye.offsetWidth; eye.classList.add('activated'); };
loadConfiguration();
if (jobId) loadJob(); else if (validId(query.get('reuse'))) reuseSource(query.get('reuse'));
window.addEventListener('beforeunload', () => { clearTimeout(pollTimer); for (const url of mediaUrls.values()) URL.revokeObjectURL(url); });
