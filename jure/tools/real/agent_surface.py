"""Machine-readable role surface for a host controller, without Agent policy.

The existing legacy mock-tool normalization protocol is deliberately not used
for weighted control estimates. Consumers must preserve EvidenceEnvelope.
"""

def functions_for(client):
    return [{'type':'function','function':{'name':card['tool_name'],
        'description':card['description']+' '+card['when_to_use'],
        'parameters':card['input_schema']}} for card in client.cards()]

def execute_function(client,name,arguments,**context):
    return client.compact(client.call(name,arguments,**context))
