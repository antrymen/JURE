"""Real ESearch/EFetch. No claim judgment, synthetic references or LLM extraction."""
from urllib.parse import urlencode
import xml.etree.ElementTree as ET
from jure.tools.real.contracts import Outcome,Status,ToolFailure

BASE='https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'

def text(node):return ''.join(node.itertext()).strip() if node is not None else ''

def parse_articles(raw):
    try:root=ET.fromstring(raw)
    except ET.ParseError:raise ToolFailure(Status.SOURCE_ERROR,'INVALID_XML','PubMed XML cannot be parsed') from None
    if root.find('.//ERROR') is not None:raise ToolFailure(Status.SOURCE_ERROR,'PUBMED_ERROR','PubMed reported an error')
    records=[]
    for node in root.findall('.//PubmedArticle'):
        pmid=text(node.find('./MedlineCitation/PMID'));article=node.find('./MedlineCitation/Article')
        if article is None:continue
        sections=[{'section':e.get('Label') or e.get('NlmCategory') or 'Abstract','text':text(e),
            'location':f'PubMed:{pmid}:Abstract:{i+1}','verbatim':True} for i,e in enumerate(article.findall('./Abstract/AbstractText'))]
        ids={e.get('IdType'):text(e) for e in node.findall('./PubmedData/ArticleIdList/ArticleId')}
        records.append(dict(pmid=pmid,doi=ids.get('doi'),pmcid=ids.get('pmc'),title=text(article.find('./ArticleTitle')),
            year=text(article.find('./Journal/JournalIssue/PubDate/Year')) or text(article.find('./Journal/JournalIssue/PubDate/MedlineDate')),
            journal=text(article.find('./Journal/Title')),abstract_sections=sections,
            publication_types=[text(e) for e in article.findall('./PublicationTypeList/PublicationType')],
            organism_mesh=[text(e) for e in node.findall('./MedlineCitation/MeshHeadingList/MeshHeading/DescriptorName') if text(e) in ('Humans','Mice','Rats','Animals')],
            source_url='https://pubmed.ncbi.nlm.nih.gov/'+pmid+'/',retrieval_scope='ABSTRACT_ONLY',
            full_text_available=False,ranking_score=None))
    return records

class LiteratureTool:
    def __init__(self,http):self.http=http
    def retrieve(self,pmids):
        url=BASE+'efetch.fcgi?'+urlencode({'db':'pubmed','id':','.join(pmids),'retmode':'xml','rettype':'abstract','tool':'JURE'})
        raw,prov=self.http.get(url);records=parse_articles(raw)
        unexpected=set(r['pmid'] for r in records)-set(pmids)
        if unexpected:raise ToolFailure(Status.SOURCE_ERROR,'PMID_MISMATCH','PubMed returned an unexpected PMID',prov)
        return records,prov
    def execute(self,q,ctx):
        if q.operation=='search':
            terms=[*q.entities,*q.keywords,*[x for x in (q.relation,q.process,q.cell_type,q.perturbation) if x]]
            if any(any(c in s for c in '"[]\n\r') or not s.strip() for s in terms):raise ValueError('use literal terms without query operators')
            query=' AND '.join('"'+s.strip()+'"[Title/Abstract]' for s in terms)
            obj,searchprov=self.http.json(BASE+'esearch.fcgi?'+urlencode({'db':'pubmed','term':query,'retmode':'json','retmax':q.limit,'sort':'relevance','tool':'JURE'}))
            if 'esearchresult' not in obj:raise ToolFailure(Status.SOURCE_ERROR,'PUBMED_ERROR','Missing ESearch result',searchprov)
            sr=obj['esearchresult'];ids=sr.get('idlist',[])
            records,retrieveprov=self.retrieve(ids) if ids else ([],{})
            byid={r['pmid']:r for r in records};ordered=[byid[p] for p in ids if p in byid]
            return Outcome(Status.OK if ids else Status.NO_RESULT,result={'search_query':query,'query_translation':sr.get('querytranslation'),
                'total_hits':int(sr['count']),'items':ordered,'search_hits_are_evidence_records':False,
                'ranking':'NCBI relevance order; numeric score not supplied'},record_ids=['PMID:'+p for p in ids],
                provenance={'search':searchprov,'metadata_retrieval':retrieveprov,'upstream_source_ids':['PMID:'+p for p in ids]},
                warnings=['Search result relevance is not claim support.'],limitations=['PubMed title/abstract scope; no automatic synonym or keyword broadening.'])
        records,prov=self.retrieve(q.pmids)
        if q.operation=='retrieve':
            return Outcome(Status.OK if records else Status.NO_RESULT,result={'articles':records,'missing_pmids':sorted(set(q.pmids)-{r['pmid'] for r in records})},
                record_ids=['PMID:'+r['pmid'] for r in records],provenance={**prov,'upstream_source_ids':['PMID:'+r['pmid'] for r in records]},
                limitations=['Abstract only; unavailable full text is not silently supplied. Biological context must be checked against the retrieved text.'])
        # v0.1 validates caller-selected exact passages, but refuses to assign a
        # scientific support category without an independently validated extractor.
        verified=[]
        for candidate in q.passages:
            pmid=candidate.get('pmid');passage=candidate.get('verbatim_passage','')
            for record in records:
                if record['pmid']!=pmid:continue
                for section in record['abstract_sections']:
                    if passage and passage in section['text']:
                        verified.append({'pmid':pmid,'verbatim_passage':passage,'location':section['location'],
                            'claim':q.claim,'classification':None,'allowed_classifications':['DIRECT','INDIRECT','CONTEXTUAL','CONTRADICTORY','NOT_FOUND'],
                            'organism':None,'cell_type':None,'perturbation':None,'readout':None,
                            'context_match':{'same_gene':None,'same_cell_type':None,'same_perturbation':None,'same_readout':None},
                            'paraphrase':None,'limitations':['Exact text match only; no claim-level support judgment has been performed.']})
        return Outcome(Status.NOT_EVALUABLE,result={'extraction_status':'PARTIAL','verified_passages':verified,'automatic_claim_classification':'NOT_IMPLEMENTED'},
            record_ids=['PMID:'+r['pmid'] for r in records],provenance={**prov,'upstream_source_ids':['PMID:'+r['pmid'] for r in records]},
            limitations=['A validated scientific extractor is not implemented. Exact passage validation is not evidence classification.'])
