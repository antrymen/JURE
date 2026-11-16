"""Harmonizome API wrapper; preserve mixed upstream evidence classes."""
from urllib.parse import quote
from jure.tools.real.contracts import Outcome,Status,ToolFailure

class GeneKnowledgeTool:
    def __init__(self,http,resolver=None):self.http=http;self.resolver=resolver
    def execute(self,q,ctx):
        if not self.resolver:raise ToolFailure(Status.UNAVAILABLE,'HGNC_UNAVAILABLE','Verified human gene mapping is not configured')
        entity=self.resolver.resolve(q.gene);gene=entity['symbol']
        url='https://maayanlab.cloud/Harmonizome/api/1.0/gene/'+quote(gene,safe='')
        if q.operation!='get_gene_info':url+='?showAssociations=true'
        obj,prov=self.http.json(url)
        if obj.get('status') or 'symbol' not in obj:raise ToolFailure(Status.NO_RESULT,'GENE_NOT_IN_SOURCE','Harmonizome has no gene record',prov)
        if obj['symbol'].upper()!=gene:raise ToolFailure(Status.SOURCE_ERROR,'ENTITY_MISMATCH','HGNC and source symbols disagree',prov)
        items=obj.pop('associations',[])
        # Pathway labels identify a subset; no enrichment or mechanism is computed.
        if q.operation=='query_pathways':
            items=[x for x in items if any(t in x.get('geneSet',{}).get('name','').lower() for t in ('pathway','reactome','kegg','wikipathways'))]
        upstream=[]
        for item in items:
            name=item.get('geneSet',{}).get('name','');dataset=name.split('/',1)[-1]
            upstream.append('harmonizome-dataset:'+dataset)
            low=dataset.lower()
            item['source_class']=('COMPUTATIONAL_PREDICTION' if any(s in low for s in ('prediction','predicted','text-mining')) else 'CURATED_GENESET_DATABASE')
            item['independence']='Not independent of the named upstream dataset/publications'
        if q.operation=='get_gene_info':status=Status.OK
        else:status=Status.TRUNCATED if len(items)>q.limit else Status.OK if items else Status.NO_RESULT
        return Outcome(status,result={'identity':entity,'gene_info':obj,'associations':items[:q.limit],
            'total_associations_in_scope':len(items),'returned':min(len(items),q.limit)},
            record_ids=['HGNC:'+entity['hgnc_id'].removeprefix('HGNC:'),'NCBIGene:'+str(obj['ncbiEntrezGeneId'])],
            provenance={**prov,'upstream_source_ids':sorted(set(upstream)) or ['HGNC:'+entity['hgnc_id'].removeprefix('HGNC:')],
                'mapping_sha256':self.resolver.version},
            limitations=['Gene annotations/sets are contextual knowledge, not perturbation-specific evidence.',
                'Scores retain upstream meaning; no confidence or causal interpretation is invented.',
                'Harmonizome has mixed experimental, curated and computational datasets; inspect each source.'])
