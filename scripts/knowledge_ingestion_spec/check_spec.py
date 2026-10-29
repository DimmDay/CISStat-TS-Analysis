"""Documentation checks, not an implementation test of the future ingestion pipeline."""
from pathlib import Path
import unittest,re
ROOT=Path(__file__).resolve().parents[2]
class Contract(unittest.TestCase):
 def setUp(self):
  p=ROOT/'spec_knowledge_ingestion.md'; self.s=p.read_text() if p.exists() else ''
 def test_base_and_status(self):
  for t in ['cb46e3aca646cc77cc600af0de5d80094678c1b8','не реализован','14 статей','78','28']:self.assertIn(t,self.s)
 def test_lifecycle(self):
  for t in ['source_version','content_hash','review_required','release_id','last-known-good','manifest','UTF-8','Markdown','DOCX','PDF','OCR','dry-run']:self.assertIn(t,self.s)
 def test_all_consumers(self):
  for t in ['buildLearningStack','describeNode','glossary','registry_data.json','PROMOTE_KNOWLEDGE','lru_cache','stage_id','directions']:self.assertIn(t,self.s)
 def test_source_references(self):
  parts=self.s.split('<!-- SOURCE_PATHS -->');self.assertEqual(len(parts),3)
  paths=re.findall(r'`((?:apps|packages|scripts|docs)/[^`]+)`',parts[1]);self.assertGreaterEqual(len(paths),8)
  for p in paths:self.assertTrue((ROOT/p).exists(),p)
 def test_tasks(self):
  rows=[l.split('|')[1:-1] for l in self.s.splitlines() if re.match(r'\| KBI-\d\d \|',l)]
  self.assertGreaterEqual(len(rows),8);done=set()
  for r in rows:
   self.assertEqual(len(r),4)
   for d in re.findall(r'KBI-\d\d',r[1]):self.assertIn(d,done)
   self.assertNotIn(r[0].strip(),done);done.add(r[0].strip())
 def test_markdown(self):
  self.assertEqual(self.s.count('```')%2,0);w=[]
  for l in self.s.splitlines()+['']:
   if l.startswith('|'):w.append(l.count('|'))
   elif w:self.assertEqual(len(set(w)),1);w=[]
if __name__=='__main__':unittest.main(verbosity=2)
