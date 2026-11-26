import datetime as dt, io, json, tempfile, unittest
from pathlib import Path
from radar_bridge import transform, fetch, atomic_json
NOW=dt.datetime(2026,11,23,tzinfo=dt.timezone.utc)
def item(**kw):
    return dict({'id':1,'source_id':'openrouter-free','url':'https://example.com/model','title':'Free AI credits','summary':'Startup benefit','kind':'freebie','category':'ai','obtain':'free','status':'active'},**kw)
class Mock:
    def __init__(self,pages): self.pages=iter(pages)
    def open(self,url,timeout): return io.BytesIO(json.dumps(next(self.pages)).encode())
class Bridge(unittest.TestCase):
    def run_rows(self,*r): return transform(r,now=NOW)
    def test_pending(self):
        c=self.run_rows(item())['candidates'][0]
        for k in ['verified','official','country','eligibility','amount']: self.assertIsNone(c[k])
        self.assertEqual(c['status'],'pending_verification')
    def test_games(self): self.assertEqual(self.run_rows(item(category='game'))['candidate_count'],0)
    def test_news(self): self.assertEqual(self.run_rows(item(kind='news'))['candidate_count'],0)
    def test_lottery(self): self.assertEqual(self.run_rows(item(obtain='lottery'))['candidate_count'],0)
    def test_discount(self): self.assertEqual(self.run_rows(item(kind='deal',obtain='paid',title='Cloud discount'))['candidate_count'],1)
    def test_expired(self): self.assertEqual(self.run_rows(item(expires_at='2026-01-01T00:00:00Z'))['rejected'],{'expired':1})
    def test_no_signal(self): self.assertEqual(self.run_rows(item(title='New model',summary=''))['candidate_count'],0)
    def test_dedup(self):
        r=self.run_rows(item(),item(id=2,source_id='github',url='https://example.com/model?utm_source=rss'))
        self.assertEqual(r['duplicate_count'],1); self.assertEqual(len(r['candidates'][0]['source_refs']),2)
    def test_distinct_title(self): self.assertEqual(self.run_rows(item(),item(id=2,title='Student credits'))['candidate_count'],2)
    def test_existing(self): self.assertEqual(transform([item()],[{'id':'existing','official':'https://example.com/model'}],NOW)['candidates'][0]['possible_existing_ids'],['existing'])
    def test_unsafe_urls(self):
        for u in ['http://example.com','https://user:pass@example.com','https://127.0.0.1','https://example.com/?token=secret','https://service.internal']:
            self.assertEqual(self.run_rows(item(url=u))['candidate_count'],0)
    def test_redaction(self): self.assertNotIn('foo@example.com',json.dumps(self.run_rows(item(summary='Email foo@example.com'))))
    def test_pagination(self):
        pages=[{'total':2,'offset':0,'limit':1,'items':[item()]},{'total':2,'offset':1,'limit':1,'items':[item(id=2)]}]
        self.assertEqual(len(fetch('http://127.0.0.1:8788',page_size=1,opener=Mock(pages))),2)
    def test_partial_blocked(self):
        with self.assertRaises(ValueError): fetch('http://localhost:8788',max_pages=1,page_size=1,opener=Mock([{'total':2,'offset':0,'limit':1,'items':[item()]}]))
    def test_changed_total(self):
        with self.assertRaises(ValueError): fetch('http://localhost:8788',page_size=1,opener=Mock([{'total':2,'offset':0,'limit':1,'items':[item()]},{'total':3,'offset':1,'limit':1,'items':[item(id=2)]}]))
    def test_remote_denied(self):
        with self.assertRaises(ValueError): fetch('https://example.com')
    def test_atomic(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'out'/'candidates.json'; atomic_json(p,self.run_rows(item())); self.assertEqual(json.loads(p.read_text())['candidate_count'],1)
if __name__=='__main__': unittest.main()
