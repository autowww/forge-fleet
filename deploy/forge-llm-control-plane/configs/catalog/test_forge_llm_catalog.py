import unittest,json,os,importlib.util
ROOT=os.path.dirname(__file__)
with open(os.path.join(ROOT,'forge_llm_catalog_2026-11-03.json'),encoding='utf-8') as f:cat=json.load(f)
spec=importlib.util.spec_from_file_location('selector',os.path.join(ROOT,'forge_llm_selector.py'))
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class Tests(unittest.TestCase):
 def test_unique(self):
  names=[m['alias'] for m in cat['models']];self.assertEqual(len(names),len(set(names)))
  self.assertEqual(len({x['model_id'] for x in cat['models']}),len(names))
 def test_cell_refs(self):
  names={m['alias'] for m in cat['models']}
  for r in cat['tasks']:
   self.assertEqual(set(r['candidates_by_vram_gb']),set(map(str,cat['vram_tiers_gb'])))
   for v in r['candidates_by_vram_gb'].values():
    for c in v:self.assertIn(c['alias'],names)
 def test_no_autopromote(self):
  for r in cat['tasks']:
   for tier in cat['vram_tiers_gb']:
    res=mod.select(cat,r['task_id'],tier)
    self.assertFalse(any(c['deployment_authorized'] for c in res['candidates']))
 def test_task_mismatch(self):
  self.assertEqual(mod.select(cat,'foobar',8)['error'],'unknown_task')
 def test_filter_runtime(self):
  out=mod.select(cat,'asr',8,runtime='vLLM')
  self.assertFalse(out['candidates'])
 def test_memory_floor(self):
  self.assertFalse(mod.select(cat,'code_repo',2)['candidates'])
 def test_warning_on_concurrency(self):
  res=mod.select(cat,'code_generate',16,active=8,context=32768)
  self.assertTrue(all('active_concurrency_not_memory_benchmarked' in x['blockers'] for x in res['candidates']))
 def test_known_language_exclusion(self):
  out=mod.select(cat,'asr',8,language='uk')
  self.assertNotIn('AS17',[c['alias'] for c in out['candidates']])
  out2=mod.select(cat,'asr',8,language='en')
  self.assertIn('AS17',[c['alias'] for c in out2['candidates']])
 def test_sources_are_official_repo_links(self):
  for m in cat['models']:
   self.assertTrue(m['source_url'].endswith(m['model_id']))
if __name__=='__main__':unittest.main()
