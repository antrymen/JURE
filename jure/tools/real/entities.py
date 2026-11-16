"""Deterministic HGNC identity resolution; ambiguous aliases never auto-select."""
import csv,json
from pathlib import Path
from .contracts import ToolFailure,Status
from .registry import file_sha

class GeneResolver:
    def __init__(self,path):
        self.path=Path(path);self.version=file_sha(path);self.primary={};self.lookup={}
        with self.path.open() as f:
            for row in csv.DictReader(f,delimiter='\t'):
                if row['status']!='Approved':continue
                symbol=row['symbol'];self.primary[symbol]=row
                for value in [symbol,row.get('ensembl_gene_id',''),row.get('hgnc_id',''),*row.get('alias_symbol','').split('|'),*row.get('prev_symbol','').split('|')]:
                    if value:self.lookup.setdefault(value.upper(),set()).add(symbol)
    def resolve(self,query):
        key=query.strip().upper()
        # A currently approved symbol wins over historical aliases.
        symbols={key} if key in self.primary else self.lookup.get(key,set())
        if not symbols:raise ToolFailure(Status.NOT_EVALUABLE,'UNKNOWN_GENE','No approved human gene mapping',{'query':query,'hgnc_sha256':self.version})
        if len(symbols)>1:raise ToolFailure(Status.AMBIGUOUS_ENTITY,'AMBIGUOUS_GENE','Gene alias maps to multiple approved genes',{'query':query,'candidates':sorted(symbols)})
        symbol=next(iter(symbols));row=self.primary[symbol]
        return dict(input=query,symbol=symbol,hgnc_id=row['hgnc_id'],ensembl_gene_id=row.get('ensembl_gene_id'),
            entrez_id=row.get('entrez_id'),species='Homo sapiens',mapping_source='HGNC approved complete set',mapping_sha256=self.version)
