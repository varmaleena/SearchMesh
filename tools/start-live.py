import getpass
import os
import subprocess
from pathlib import Path

root=Path(__file__).resolve().parents[1]
env=os.environ.copy()
config_path=root/'.env'
if config_path.exists():
    for line in config_path.read_text(encoding='utf-8-sig').splitlines():
        key, separator, value=line.strip().partition('=')
        if separator and key in {'SERPAPI_API_KEY','GOOGLE_API_KEY','SEARCHMESH_MODEL','GROQ_API_KEY','SEARCHMESH_GROQ_MODEL','SEARCHMESH_GATEWAY_TOKEN'}:
            env.setdefault(key,value.strip().strip('"').strip("'"))
print('SearchMesh live research setup — loads local .env; prompted credentials stay in this process and its child.')
for name,label in [('SERPAPI_API_KEY','SerpApi API key'),('GROQ_API_KEY','Groq API key')]:
    if not env.get(name):env[name]=getpass.getpass(label+' (hidden): ').strip()
if not env.get('SERPAPI_API_KEY') or not env.get('GROQ_API_KEY'):
    raise SystemExit('SerpApi and Groq keys are required.')
print('Starting live research at http://127.0.0.1:8001/#workspace')
subprocess.run([str(root/('.venv/Scripts/python.exe' if os.name=='nt' else '.venv/bin/python')),'-m','searchmesh.cli','serve','--mode','live','--port','8001','--open'],cwd=root,env=env,check=True)

