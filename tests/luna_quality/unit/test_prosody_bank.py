import json,tempfile,unittest
from pathlib import Path
from scripts.luna_quality.prosody_bank import ProsodyBankStore,ingest_directory
from scripts.luna_quality.prosody_bank.queries import take_history,selected_with_features
class BankTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'B01').mkdir();self.store=ProsodyBankStore(self.root/'bank.sqlite');self.store.migrate()
 def tearDown(self):self.store.close();self.tmp.cleanup()
 def write(self,take=0,ok=True,why=None):
  p=self.root/'B01'/f'P00_t{take}.json';p.write_text(json.dumps({'take':take,'ok':ok,'why':why or [],'n_syl':10,'text':'테스트','metrics':{'dur':2.0,'median_hz':235,'range_st':8,'tail_delta':-2}}),encoding='utf-8');return p
 def test_create_idempotency_and_revision(self):
  p=self.write();self.assertEqual(ingest_directory(self.store,self.root,'P')["inserted"],1);self.assertEqual(ingest_directory(self.store,self.root,'P')["unchanged"],1);p.write_text(p.read_text().replace('235','236'));ingest_directory(self.store,self.root,'P');self.assertEqual(len(take_history(self.store.connection,'P')),2)
 def test_pins_and_nonselection_are_distinct(self):
  self.write(0);self.write(1);(self.root/'B01_pins.json').write_text('{"P00":1}');ingest_directory(self.store,self.root,'P');rows=take_history(self.store.connection,'P');self.assertEqual([r['decision'] for r in rows],['not_selected','selected']);selected=selected_with_features(self.store.connection,'P');self.assertEqual(len(selected),1);self.assertEqual(selected[0]['selection_source_path'],'B01_pins.json');self.assertEqual(len(selected[0]['selection_source_sha256']),64)
 def test_explicit_rejection_and_unknown(self):
  self.write(0,False,['rate']);self.write(1,False,[]);ingest_directory(self.store,self.root,'P');self.assertEqual([r['decision'] for r in take_history(self.store.connection,'P')],['rejected','unknown'])
 def test_malformed_isolated(self):
  self.write();(self.root/'B01'/'P01_t0.json').write_text('{bad');r=ingest_directory(self.store,self.root,'P');self.assertEqual((r['inserted'],r['errors']),(1,1))
 def test_transaction_rolls_back(self):
  with self.assertRaises(RuntimeError):
   with self.store.transaction() as db: db.execute("INSERT INTO ingest_runs VALUES ('x','x','x')");raise RuntimeError()
  self.assertIsNone(self.store.connection.execute("SELECT 1 FROM ingest_runs WHERE id='x'").fetchone())
 def test_migration_dry_run(self):
  other=ProsodyBankStore(self.root/'dry.sqlite');self.assertEqual(other.migrate(True),[1]);self.assertEqual(other.connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0],0);other.close()
if __name__=='__main__':unittest.main()
