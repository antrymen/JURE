"""Sequential continuation; never bypass incomplete/failed Day8 discovery."""
from pathlib import Path
import json,time,subprocess,sys
P=Path(__file__).resolve().parent;D=P/'day8_discovery'
while True:
 try:s=json.loads((D/'execution_status.json').read_text())
 except (FileNotFoundError,json.JSONDecodeError):time.sleep(10);continue
 phase=s.get('phase')
 if phase=='failed':raise RuntimeError('Day8 reference failed: '+str(s))
 if phase=='Stage1_complete_stage2_pending':break
 time.sleep(10)
with (P/'day8_scan_and_validation.log').open('w') as f:
 r=subprocess.run([sys.executable,str(P/'run_day8_scan_and_validate.py')],stdout=f,stderr=subprocess.STDOUT)
(D/'continuation_status.json').write_text(json.dumps({'stage':'day8_scan_and_day6_validation','status':'complete' if r.returncode==0 else 'failed','returncode':r.returncode},indent=2))
sys.exit(r.returncode)
