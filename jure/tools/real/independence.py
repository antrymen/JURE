"""Small provenance graph; no numerical independence score or truth inference."""
def build_source_graph(envelopes):
    nodes={};edges=[];owners={}
    for env in envelopes:
        eid=env.query_id;nodes[eid]={'id':eid,'type':'EvidenceAcquisition'}
        ids=set(env.independence.get('upstream_source_ids',[]))
        if env.dataset_id:ids.add('dataset:'+env.dataset_id)
        for sid in sorted(ids):
            kind='Paper' if sid.startswith('PMID:') else 'Dataset' if sid.startswith('dataset:') else 'Database'
            nodes[sid]={'id':sid,'type':kind}
            edges.append({'source':eid,'target':sid,'type':'CITES' if kind=='Paper' else 'DERIVED_FROM'})
            for other in owners.get(sid,[]):
                edges.append({'source':eid,'target':other,'type':'REUSES_DATA' if kind=='Dataset' else 'SAME_SOURCE','via':sid})
            owners.setdefault(sid,[]).append(eid)
    return {'nodes':list(nodes.values()),'edges':edges,'policy':'Shared sources remain dependent; different tools do not imply independence.'}
