"""Local, paginated whole-catalog report with durable review notes."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit,parse_qs
import zlib
from .conversion.run import current_folder,dumps

ROOT=Path(__file__).resolve().parents[2]
PAGE=Path(__file__).with_name('report.html')


@contextmanager
def connect(folder,write=False):
    db=sqlite3.connect((folder/'report.sqlite').resolve().as_uri()+('' if write else '?mode=ro'),uri=True,timeout=30)
    db.row_factory=sqlite3.Row
    try:
        with db:yield db
    finally:db.close()


def where(params):
    conditions=[];values=[]
    for query,column,allowed in (
        ('outcome','r.outcome',('good','bad')),('source','r.source',None),('kind','r.kind',None)):
        value=params.get(query,[''])[0]
        if value and (allowed is None or value in allowed):conditions.append(column+'=?');values.append(value)
    if params.get('partial',[''])[0]=='1':conditions.append('r.partial=1')
    if params.get('partial',[''])[0]=='0':conditions.append('r.partial=0')
    if key:=params.get('effect',[''])[0]:
        conditions.append('EXISTS (SELECT 1 FROM record_effects e WHERE e.ordinal=r.ordinal AND e.key=?)');values.append(key)
    if q:=params.get('q',[''])[0].strip():
        q=q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        conditions.append("(r.name LIKE ? ESCAPE '\\' OR r.source_key LIKE ? ESCAPE '\\')");values.extend(['%'+q+'%']*2)
    if reason:=params.get('reason',[''])[0]:
        conditions.append('instr(r.reason,?)>0');values.append(reason)
    review=params.get('review',[''])[0]
    if review in ('pending','accepted','changes'):
        conditions.append("coalesce(d.status,'pending')=?");values.append(review)
    return (' WHERE '+' AND '.join(conditions) if conditions else ''),values


def records(folder,params):
    page=max(0,min(1000000,int(params.get('page',['0'])[0])));size=40
    clause,args=where(params)
    with connect(folder) as db:
        total=db.execute('SELECT count(*) FROM records r LEFT JOIN decisions d USING(source_key)'+clause,args).fetchone()[0]
        page=min(page,max(0,(total-1)//size))
        rows=db.execute("SELECT r.ordinal,r.source_key,r.name,r.source,r.kind,r.source_id,r.level,r.outcome,r.partial,r.retained,r.omitted,r.summary,coalesce(d.status,'pending') AS review FROM records r LEFT JOIN decisions d USING(source_key)"+clause+' ORDER BY r.ordinal LIMIT ? OFFSET ?',[*args,size,page*size]).fetchall()
    return {'total':total,'page':page,'pageSize':size,'rows':[dict(r) for r in rows]}


def detail(folder,key):
    with connect(folder) as db:
        row=db.execute('SELECT detail FROM records WHERE source_key=?',(key,)).fetchone()
        if row is None:raise ValueError('Source record not found.')
        result=json.loads(zlib.decompress(row[0]))
        review=db.execute('SELECT * FROM decisions WHERE source_key=?',(key,)).fetchone()
    return {'conversion':result,'review':dict(review) if review else {'source_key':key,'status':'pending','notes':'','revision':0}}


def save(folder,data):
    key=data.get('source_key');status=data.get('status');notes=data.get('notes');revision=data.get('revision')
    if not isinstance(key,str) or status not in ('pending','accepted','changes') or not isinstance(notes,str) or len(notes)>20000 or type(revision) is not int:
        raise ValueError('Invalid review. Choose a review state and keep notes below 20,000 characters.')
    with connect(folder,True) as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM records WHERE source_key=?',(key,)).fetchone() is None:raise ValueError('Source record not found.')
        old=db.execute('SELECT revision FROM decisions WHERE source_key=?',(key,)).fetchone()
        if (old[0] if old else 0)!=revision:raise ValueError('Save conflict: this record was changed in another tab. Copy your notes, reload the record, and try again.')
        updated=datetime.now(timezone.utc).isoformat()
        db.execute('INSERT INTO decisions VALUES (?,?,?,?,?) ON CONFLICT(source_key) DO UPDATE SET status=excluded.status,notes=excluded.notes,revision=excluded.revision,updated_at=excluded.updated_at',
            (key,status,notes,revision+1,updated))
    return {'source_key':key,'status':status,'notes':notes,'revision':revision+1,'updated_at':updated}


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass

    def send(self,data,mime='application/json; charset=utf-8',status=200):
        body=data if isinstance(data,bytes) else dumps(data).encode('utf-8')
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)

    def do_GET(self):
        url=urlsplit(self.path);params=parse_qs(url.query);folder=self.server.folder
        try:
            if url.path in ('/','/index.html'):return self.send(PAGE.read_bytes(),'text/html; charset=utf-8')
            if url.path.startswith('/fonts/'):
                name=Path(url.path).name
                if name not in ('Barlow-Regular.ttf','Barlow-SemiBold.ttf','BarlowCondensed-Bold.ttf'):raise ValueError('Font not found.')
                return self.send((ROOT/'docs/effect-review/fonts'/name).read_bytes(),'font/ttf')
            if url.path=='/api/health':return self.send({'service':'ffr-ability-review','run':folder.name})
            if url.path=='/api/summary':
                state=json.loads((folder/'run.json').read_text())
                summary=json.loads((folder/'summary.json').read_text()) if (folder/'summary.json').exists() else {}
                with connect(folder) as db:reviews={r[0]:r[1] for r in db.execute('SELECT status,count(*) FROM decisions GROUP BY status')}
                return self.send({'state':state,'summary':summary,'reviews':reviews})
            if url.path=='/api/records':return self.send(records(folder,params))
            if url.path=='/api/detail':return self.send(detail(folder,params.get('key',[''])[0]))
            if url.path=='/api/rules':return self.send(json.loads((folder/'compiled-rules.json').read_text(encoding='utf-8')))
            if url.path=='/api/export':
                with connect(folder) as db:rows=[dict(r) for r in db.execute('SELECT * FROM decisions ORDER BY source_key')]
                return self.send({'run':folder.name,'decisions':rows})
            if url.path=='/api/download':
                name=params.get('file',[''])[0]
                if name not in ('summary.json','compiled-rules.json','review-snapshot.json','exceptions.json','source-manifest.json','implementation-manifest.json'):raise ValueError('Unknown report file.')
                return self.send((folder/name).read_bytes())
            self.send({'error':'Page not found.'},status=404)
        except (ValueError,sqlite3.Error,FileNotFoundError) as ex:self.send({'error':str(ex)},status=400)

    def do_POST(self):
        origin=self.headers.get('Origin')
        if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}') or origin and origin not in (f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'):
            return self.send({'error':'Review saves must come from this local page.'},status=403)
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<100000:raise ValueError('Invalid review size.')
            data=json.loads(self.rfile.read(size))
            if self.path!='/api/review':raise ValueError('Unknown save endpoint.')
            self.send(save(self.server.folder,data))
        except (ValueError,sqlite3.Error) as ex:self.send({'error':str(ex)},status=409)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8768);parser.add_argument('--run',type=Path)
    args=parser.parse_args();server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.folder=args.run or current_folder()
    print(f'http://127.0.0.1:{args.port}/',flush=True);server.serve_forever()


if __name__=='__main__':main()
