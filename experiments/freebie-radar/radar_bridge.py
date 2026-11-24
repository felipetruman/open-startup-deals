#!/usr/bin/env python3
"""Read-only Freebie Radar discovery bridge. No writes to any OSD catalog."""
import argparse, datetime as dt, hashlib, ipaddress, json, os, re, tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler

CATEGORIES = {'ai','cloud','vps','dev','software','design','security','edu','domain'}
MODES = {'free','conditional','trial','paid','promo'}
SIGNAL = re.compile(r'\b(?:free|credit[s]?|startup[s]?|student[s]?|discount[s]?|coupon[s]?|trial|free[ -]?tier|developer[s]?|scholarship|grátis|gratuito[s]?|créditos?|estudantes?|descontos?|bolsa[s]?|cupom|cupons)\b|免费|额度|优惠|学生|初创',re.I)
TRACKING = {'fbclid','gclid','ref','referral','affiliate','aff','mc_cid','mc_eid'}
PRIVATE = re.compile(r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|\b(?:sk-[\w-]{12,}|gh[pousr]_[\w]{20,})\b|Bearer\s+[\w.~-]{12,}|(?:api[_ -]?key|password)\s*[:=]\s*\S{8,}|(?<!\d)(?:\+?55[\s().-]*)?\(?\d{2}\)?[\s().-]*9\d{4}[\s().-]*\d{4}(?!\d)')

def safe_url(s):
    if not isinstance(s,str) or len(s)>2000 or any(ord(c)<33 for c in s): raise ValueError('invalid URL')
    p=urlsplit(s)
    host=p.hostname
    if p.scheme!='https' or not host or p.username or p.password or p.port not in (None,443): raise ValueError('invalid public URL')
    try: ipaddress.ip_address(host)
    except ValueError: pass
    else: raise ValueError('IP address not accepted')
    if '.' not in host or host.endswith(('.local','.localhost','.internal','.test')): raise ValueError('non-public hostname')
    if any(k.lower() not in TRACKING and not k.lower().startswith('utm_') for k,v in parse_qsl(p.query,keep_blank_values=True)):
        raise ValueError('unreviewed query parameters')
    return urlunsplit(('https',host.lower(),p.path or '/', '', ''))

def clean(s,n):
    return PRIVATE.sub('[redigido]',s[:n]).strip() if isinstance(s,str) else ''

def timestamp(s):
    if not isinstance(s,str): return None
    try:
        t=dt.datetime.fromisoformat(s.replace('Z','+00:00'))
        if t.tzinfo is None: return None
        return t.astimezone(dt.timezone.utc)
    except ValueError: return None

def candidate(row,now):
    if not isinstance(row,dict): return None,'invalid'
    if row.get('status')!='active': return None,'inactive'
    if row.get('category') not in CATEGORIES or row.get('kind') not in {'freebie','deal'} or row.get('obtain') not in MODES: return None,'out_of_scope'
    expiry=timestamp(row.get('expires_at'))
    if expiry and expiry<=now: return None,'expired'
    title=clean(row.get('title'),300); summary=clean(row.get('summary'),1200)
    if not title or not SIGNAL.search(title+' '+summary): return None,'no_benefit_signal'
    try: url=safe_url(row.get('url'))
    except (ValueError,TypeError): return None,'unsafe_url'
    src=clean(row.get('source_id'),100)
    if not src or not isinstance(row.get('id'),int): return None,'invalid_provenance'
    key=hashlib.sha256((url+'\n'+' '.join(title.casefold().split())).encode()).hexdigest()[:24]
    return {'candidate_id':'fr-'+key,'name':title,'category_hint':row['category'],'offer_type_hint':row['obtain'],'discovery_url':url,'summary_unverified':summary,'source_refs':[{'source_id':src,'radar_item_id':row['id']}],'official':None,'status':'pending_verification','confidence':'unverified','country':None,'eligibility':None,'verified':None,'amount':None,'deadline_hint':expiry.isoformat() if expiry else None},None

def transform(items,existing=(),now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    known={}
    for d in existing:
        if not isinstance(d,dict): continue
        try: known.setdefault(safe_url(d.get('official')),[]).append(clean(d.get('id'),128))
        except (ValueError,TypeError): pass
    result={}; rejected={}; duplicates=0
    for row in items:
        c,reason=candidate(row,now)
        if reason: rejected[reason]=rejected.get(reason,0)+1; continue
        k=c['candidate_id']
        if k in result:
            duplicates+=1
            for ref in c['source_refs']:
                if ref not in result[k]['source_refs']: result[k]['source_refs'].append(ref)
        else:
            c['possible_existing_ids']=sorted(set(known.get(c['discovery_url'],[])))
            result[k]=c
    return {'schema_version':1,'mode':'discovery_only','generated_at':now.isoformat(),'input_count':len(items),'candidate_count':len(result),'duplicate_count':duplicates,'rejected':rejected,'candidates':sorted(result.values(),key=lambda c:c['candidate_id'])}

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def fetch(base,max_pages=50,page_size=100,opener=None):
    p=urlsplit(base)
    if p.scheme!='http' or p.hostname not in {'127.0.0.1','localhost'} or p.username or p.password or p.path not in {'','/'} or p.query or p.fragment: raise ValueError('use local HTTP radar URL only')
    opener=opener or build_opener(ProxyHandler({}),NoRedirect())
    rows=[]; seen=set(); expected=None
    for page in range(max_pages):
        offset=page*page_size
        with opener.open(base.rstrip('/')+'/api/items?'+urlencode({'limit':page_size,'offset':offset,'merge':'0'}),timeout=20) as response:
            raw=response.read(8_000_001)
        if len(raw)>8_000_000: raise ValueError('response too large')
        doc=json.loads(raw); batch=doc.get('items'); total=doc.get('total')
        if not isinstance(batch,list) or type(total)!=int or total<0 or doc.get('offset')!=offset or doc.get('limit')!=page_size: raise ValueError('invalid radar page')
        if expected is None: expected=total
        if total!=expected or len(batch)!=min(page_size,max(total-offset,0)): raise ValueError('inconsistent scan; retry without concurrent collection')
        for row in batch:
            if not isinstance(row,dict) or type(row.get('id'))!=int or row['id'] in seen: raise ValueError('invalid or duplicate paginated item')
            seen.add(row['id']); rows.append(row)
        if len(rows)==expected: return rows
    raise ValueError('page cap reached; no partial output written')

def atomic_json(path,doc):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as f:
        tmp=f.name
        try: json.dump(doc,f,ensure_ascii=False,indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
        except BaseException: os.unlink(tmp); raise
    try: os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def main():
    p=argparse.ArgumentParser(); g=p.add_mutually_exclusive_group(required=True); g.add_argument('--input'); g.add_argument('--radar-url'); p.add_argument('--existing'); p.add_argument('--output',default='out/candidates.json'); a=p.parse_args()
    try:
        target=Path(a.output).resolve()
        if target.name!='candidates.json' or 'out' not in target.parts or a.existing and target==Path(a.existing).resolve() or a.input and target==Path(a.input).resolve(): raise ValueError('output must be a separate out/candidates.json')
        if a.input:
            d=json.loads(Path(a.input).read_text()); items=d.get('items') if isinstance(d,dict) else None
            if not isinstance(items,list): raise ValueError('expected items array')
        else: items=fetch(a.radar_url)
        existing=[]
        if a.existing:
            existing=json.loads(Path(a.existing).read_text()).get('deals')
            if not isinstance(existing,list): raise ValueError('expected existing deals array')
        report=transform(items,existing); atomic_json(target,report)
        print(json.dumps({k:v for k,v in report.items() if k!='candidates'},ensure_ascii=False))
    except (ValueError,OSError,TypeError,AttributeError) as e: p.exit(1,f'BLOCKED: {type(e).__name__}\n')
if __name__=='__main__': main()
