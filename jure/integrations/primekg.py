"""Typed, bounded read-only PrimeKG queries; no inferred edges."""
from collections import deque
import csv,json,sqlite3
from pathlib import Path
from jure.tools.real.contracts import Outcome,Status,ToolFailure
from jure.tools.real.registry import file_sha

def import_primekg(csv_path,db_path,source_meta):
    db_path=Path(db_path)
    if db_path.exists():raise FileExistsError('refuse overwrite of KG index')
    db_path.parent.mkdir(parents=True,exist_ok=True); db=sqlite3.connect(db_path)
    db.executescript('''CREATE TABLE nodes(id TEXT PRIMARY KEY,name TEXT,type TEXT,source TEXT,source_id TEXT);
    CREATE TABLE edges(id INTEGER PRIMARY KEY,source TEXT,target TEXT,relation TEXT);
    CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);''')
    with open(csv_path) as f:
        reader=csv.DictReader(f);nodes=[];edges=[]
        for i,r in enumerate(reader,1):
            for side in ('x','y'):
                nodes.append((r[side+'_index'],r[side+'_name'],r[side+'_type'],r[side+'_source'],r[side+'_id']))
            edges.append((i,r['x_index'],r['y_index'],r['relation']))
            if len(edges)>=10000:
                db.executemany('INSERT OR IGNORE INTO nodes VALUES(?,?,?,?,?)',nodes)
                db.executemany('INSERT INTO edges VALUES(?,?,?,?)',edges);nodes=[];edges=[]
        db.executemany('INSERT OR IGNORE INTO nodes VALUES(?,?,?,?,?)',nodes);db.executemany('INSERT INTO edges VALUES(?,?,?,?)',edges)
    db.executescript('CREATE INDEX edge_source ON edges(source);CREATE INDEX edge_target ON edges(target);CREATE INDEX node_name ON nodes(name COLLATE NOCASE);')
    db.execute('INSERT INTO metadata VALUES(?,?)',('source',json.dumps(source_meta)))
    db.commit();n=db.execute('SELECT count(*) FROM edges').fetchone()[0];db.close()
    return {'edges':n,'index_sha256':file_sha(db_path)}

class KnowledgeGraphTool:
    def __init__(self,path=None):
        self.path=Path(path) if path else None;self.db=None;self.version='UNAVAILABLE';self.source={}
        if self.path and self.path.exists():
            self.version=file_sha(self.path);self.db=sqlite3.connect(f'file:{self.path.resolve()}?mode=ro',uri=True);self.db.row_factory=sqlite3.Row
            self.source=json.loads(self.db.execute("SELECT value FROM metadata WHERE key='source'").fetchone()[0])
        self.source_mode=self.source.get('source_mode','REAL')
    def entity(self,value):
        rows=self.db.execute('SELECT * FROM nodes WHERE id=? OR name=? COLLATE NOCASE',(value,value)).fetchall()
        if len(rows)>1:raise ToolFailure(Status.AMBIGUOUS_ENTITY,'AMBIGUOUS_KG_ENTITY','Use a PrimeKG node ID',{'matches':[dict(r) for r in rows[:30]]})
        return dict(rows[0]) if rows else None
    def execute(self,q,ctx):
        if self.db is None:raise ToolFailure(Status.UNAVAILABLE,'PRIMEKG_UNAVAILABLE','Verified PrimeKG index is not available')
        start=self.entity(q.entity);target=self.entity(q.target) if q.target else None
        prov={'source':self.source,'index_sha256':self.version,'upstream_source_ids':['PrimeKG:10.7910/DVN/IXA7BM']}
        if not start:return Outcome(Status.NO_RESULT,result={'nodes':[],'edges':[]},provenance=prov)
        if q.operation=='query_entity':return Outcome(result={'nodes':[start]},record_ids=['PrimeKG:node:'+start['id']],provenance=prov)
        if q.operation in ('query_edge','find_paths') and not q.target:raise ValueError('target required')
        if q.target and not target:return Outcome(Status.NO_RESULT,result={'nodes':[start],'edges':[],'paths':[]},provenance=prov)
        nodes={start['id']:start};edges={};paths=[];truncated=False;queue=deque([(start['id'],[start['id']],[])])
        hop_limit=1 if q.operation=='query_edge' else q.max_hops
        expansions=0
        while queue:
            node,path,edgepath=queue.popleft()
            if len(edgepath)>=hop_limit:continue
            expansions+=1
            if expansions>500:truncated=True;break
            args=[node];sql='SELECT * FROM edges WHERE source=?'
            if q.relation_types:sql+=' AND relation IN ('+','.join('?'*len(q.relation_types))+')';args.extend(q.relation_types)
            # Filtering entity types in SQL prevents nonmatching neighbors from
            # consuming the bounded retrieval window.
            if q.entity_types:
                sql+=' AND target IN (SELECT id FROM nodes WHERE type IN ('+','.join('?'*len(q.entity_types))+'))';args.extend(q.entity_types)
            if q.operation=='query_edge':sql+=' AND target=?';args.append(target['id'])
            sql+=' ORDER BY id LIMIT ?';args.append(q.max_edges+1)
            adjacent=self.db.execute(sql,args).fetchall()
            if len(adjacent)>q.max_edges:truncated=True
            for edge in adjacent[:q.max_edges]:
                e=dict(edge);end=e['target']
                if end in path:continue
                if len(edges)>=q.max_edges or (end not in nodes and len(nodes)>=q.max_nodes):truncated=True;continue
                n=dict(self.db.execute('SELECT * FROM nodes WHERE id=?',(end,)).fetchone());nodes[end]=n
                e.update(direction='source_to_target_as_stored',confidence=None,publication_ids=[],
                    source_record_id='PrimeKG:row:'+str(e['id']),source_relation=e['relation'])
                edges[e['id']]=e
                newpath=path+[end];newedges=edgepath+[e['id']]
                if target and end==target['id']:
                    if len(paths)<q.max_paths:paths.append({'node_ids':newpath,'edge_ids':newedges})
                    else:truncated=True
                if q.operation!='query_edge':queue.append((end,newpath,newedges))
        if q.operation=='find_paths':
            used={i for p in paths for i in p['edge_ids']};edges={k:v for k,v in edges.items() if k in used}
            kept={i for p in paths for i in p['node_ids']};nodes={k:v for k,v in nodes.items() if k in kept or k==start['id']}
        status=Status.TRUNCATED if truncated else Status.OK if edges else Status.NO_RESULT
        return Outcome(status,result={'nodes':list(nodes.values()),'edges':list(edges.values()),'paths':paths,
            'search_complete_within_limits':not truncated,'max_hops':hop_limit,'traversal':'directed as stored'},
            record_ids=[e['source_record_id'] for e in edges.values()],provenance=prov,
            warnings=['No path found within a bounded/truncated search is not proof of biological absence.'] if not edges else [],
            limitations=['PrimeKG CSV does not provide edge-level confidence/PMIDs here; null/empty means unavailable.',
                'Typed paths are curated context, not new regulatory edges or case-specific mechanisms.'])
