"""Bounded public GET requests with raw-response hashes and finite retries."""
import hashlib
import json
from pathlib import Path
import ssl
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from jure.tools.real.contracts import ToolFailure, Status, now

ALLOWED_HOSTS = {'eutils.ncbi.nlm.nih.gov','maayanlab.cloud'}

class PublicHTTP:
    def __init__(self, artifact_root, *, timeout=20, retries=2):
        self.root=Path(artifact_root); self.root.mkdir(parents=True,exist_ok=True)
        self.timeout=timeout; self.retries=retries; self.lock=threading.Lock(); self.last_ncbi=0.
        self.ssl=ssl.create_default_context()
        if not ssl.get_default_verify_paths().cafile and Path('/etc/ssl/cert.pem').exists():
            self.ssl.load_verify_locations('/etc/ssl/cert.pem')

    def get(self,url):
        parts=urlsplit(url)
        if parts.scheme!='https' or parts.hostname not in ALLOWED_HOSTS or parts.username or parts.password:
            raise ToolFailure(Status.INVALID_QUERY,'UNTRUSTED_SOURCE','Only configured public evidence endpoints are allowed')
        attempts=[]
        for attempt in range(self.retries+1):
            started=now(); before=time.monotonic()
            try:
                with self.lock:
                    if parts.hostname=='eutils.ncbi.nlm.nih.gov':
                        time.sleep(max(0,.36-(time.monotonic()-self.last_ncbi)))
                        self.last_ncbi=time.monotonic()
                    request=urllib.request.Request(url,headers={'User-Agent':'JURE-Real-Evidence/0.1','Accept':'application/json, application/xml'})
                    with urllib.request.urlopen(request,context=self.ssl,timeout=self.timeout) as response:
                        if urlsplit(response.url).hostname not in ALLOWED_HOSTS:
                            raise ToolFailure(Status.SOURCE_ERROR,'REDIRECT_HOST','Unexpected upstream redirect')
                        body=response.read(8_000_001)
                        if len(body)>8_000_000: raise ToolFailure(Status.SOURCE_ERROR,'RESPONSE_LIMIT','Source response exceeded 8 MB')
                        headers={k:response.headers[k] for k in ('ETag','Last-Modified','Content-Type') if k in response.headers}
                digest=hashlib.sha256(body).hexdigest(); path=self.root/(digest+'.raw')
                if not path.exists(): path.write_bytes(body)
                attempts.append(dict(attempt=attempt+1,timestamp=started,status=200,latency_seconds=time.monotonic()-before))
                return body,dict(url=url,retrieved_at=now(),sha256=digest,artifact_path=str(path.resolve()),headers=headers,http_attempts=attempts)
            except ToolFailure: raise
            except (urllib.error.URLError,TimeoutError,OSError) as e:
                code=getattr(e,'code',None)
                attempts.append(dict(attempt=attempt+1,timestamp=started,status=code or 'NETWORK_ERROR',latency_seconds=time.monotonic()-before))
                if code==404: raise ToolFailure(Status.NO_RESULT,'HTTP_404','Source record not found',{'http_attempts':attempts,'url':url})
                if attempt==self.retries or (code and code not in (429,500,502,503,504)):
                    raise ToolFailure(Status.SOURCE_ERROR,'HTTP_SOURCE_ERROR','Public source request failed',{'http_attempts':attempts,'url':url}) from None
                time.sleep(min(2**attempt,4))

    def json(self,url):
        data,provenance=self.get(url)
        try: return json.loads(data),provenance
        except (ValueError,UnicodeError):
            raise ToolFailure(Status.SOURCE_ERROR,'INVALID_JSON','Source returned invalid JSON',provenance) from None
