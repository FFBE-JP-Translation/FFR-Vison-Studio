"""Review persistence and filtering operate on isolated test data only."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zlib
from tools.effect_review.report_server import records,save,detail


class AbilityReportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        db=sqlite3.connect(self.folder/'report.sqlite')
        db.executescript('''CREATE TABLE records(ordinal INTEGER PRIMARY KEY,source_key TEXT UNIQUE,source TEXT,kind TEXT,source_id TEXT,level INTEGER,name TEXT,outcome TEXT,partial INTEGER,retained INTEGER,omitted INTEGER,summary TEXT,reason TEXT,detail BLOB);
        CREATE TABLE record_effects(ordinal INTEGER,key TEXT,retained INTEGER,omitted INTEGER);
        CREATE TABLE decisions(source_key TEXT PRIMARY KEY,status TEXT,notes TEXT,revision INTEGER,updated_at TEXT);''')
        for n,(name,outcome,partial) in enumerate([('Cure','good',0),('Roulette','bad',0),('Mixed','good',1)]):
            blob=zlib.compress(json.dumps({'name':name,'outcome':outcome}).encode())
            db.execute('INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(n,f'TEST/ability/{n}','TEST','ability',str(n),None,name,outcome,partial,1,partial,name,'Unsupported' if outcome=='bad' else '',blob))
            db.execute('INSERT INTO record_effects VALUES (?,?,?,?)',(n,'active:73' if n==1 else 'active:2',1,partial))
        db.commit();db.close()

    def tearDown(self):self.temp.cleanup()

    def test_filters_and_page_bounds(self):
        result=records(self.folder,{'outcome':['good'],'partial':['1'],'page':['9000']})
        self.assertEqual(result['total'],1);self.assertEqual(result['rows'][0]['name'],'Mixed');self.assertEqual(result['page'],0)
        self.assertEqual(records(self.folder,{'effect':['active:73']})['total'],1)
        self.assertEqual(records(self.folder,{'q':["'; drop table records; --"]})['total'],0)

    def test_save_reload_and_conflict(self):
        value={'source_key':'TEST/ability/1','status':'changes','notes':'Keep the random selection note.','revision':0}
        saved=save(self.folder,value);self.assertEqual(saved['revision'],1)
        self.assertEqual(detail(self.folder,value['source_key'])['review']['notes'],value['notes'])
        with self.assertRaisesRegex(ValueError,'conflict'):save(self.folder,value)
        self.assertEqual(records(self.folder,{'review':['changes']})['total'],1)

    def test_unknown_records_are_not_created(self):
        with self.assertRaises(ValueError):save(self.folder,{'source_key':'missing','status':'accepted','notes':'','revision':0})


if __name__=='__main__':unittest.main()
