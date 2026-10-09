"""Agent CLI. Run from the project directory; all job IDs are local IDs."""
import argparse,json
from pathlib import Path
from config import ROOT,load_env
load_env()
p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
c=sub.add_parser('prepare');c.add_argument('video');c.add_argument('--subject',default='person');c.add_argument('--provider',default='replicate',choices=['replicate','replicate-chenxwh','huggingface'])
for command in ['status','repair-rgb','resume','hd','review','submit']:
 c=sub.add_parser(command);c.add_argument('job')
 if command=='review':c.add_argument('--approve',action='store_true');c.add_argument('--fingerprint',required=True);c.add_argument('--note',required=True)
 if command=='submit':c.add_argument('--prompt-file',required=True);c.add_argument('--reference',required=True);c.add_argument('--second-reference')
 if command=='resume':c.add_argument('--hd',action='store_true')
sub.choices['prepare'].add_argument('--mode',choices=['depth','face_mesh','depth_mesh'],default='depth')
a=p.parse_args()
if a.command=='prepare':
 import uuid,shutil
 from pipeline import run
 folder=ROOT/'runs'/uuid.uuid4().hex;folder.mkdir(parents=True)
 shutil.copy2(a.video,folder/'upload.mp4');print('JOB:',folder.name,flush=True)
 if a.mode=='face_mesh':
  from face_mesh import run as run_mesh
  run_mesh(folder/'upload.mp4',folder)
 elif a.mode=='depth_mesh':
  from face_mesh import run_depth
  run_depth(folder/'upload.mp4',folder,a.subject,a.provider)
 else:run(folder/'upload.mp4',folder,a.subject,a.provider)
 (folder/'status.json').write_text(json.dumps({'id':folder.name,'state':'done','status':'Mask review required'}));raise SystemExit
if len(a.job)!=32 or any(c not in '0123456789abcdef' for c in a.job):p.error('Expected a 32-character local job ID')
folder=ROOT/'runs'/a.job
if not folder.is_dir():p.error('Job does not exist')
if a.command=='status':
 from mask_review import state
 print(json.dumps({'mask_review':state(folder),'generation':json.loads((folder/'generation.json').read_text()) if (folder/'generation.json').exists() else None},indent=2))
elif a.command=='review':
 from mask_review import review
 print(review(folder,a.approve,a.note,a.fingerprint))
elif a.command=='repair-rgb':
 from studio import repair_rgb
 repair_rgb(folder)
else:
 from seedance_bridge import submit,submit_hd,wait_and_finish
 if a.command=='submit':
  request=submit(folder,Path(a.prompt_file).read_text(),a.reference,a.second_reference)
 elif a.command=='hd':
  request=submit_hd(folder);folder=folder/'hd'
 else:
  folder=folder/'hd' if a.hd else folder
  saved=folder/('response.json' if a.hd else 'seedance-response.json')
  request=json.loads(saved.read_text())['id']
 wait_and_finish(folder,request)
 (folder/'status.json').write_text(json.dumps({'id':a.job,'state':'done','status':'Final preview ready · original source audio','final_url':f'/runs/{a.job}/'+('hd/' if folder.name=='hd' else '')+'final-preview.mp4'}))
 print(folder/'final-preview.mp4')
