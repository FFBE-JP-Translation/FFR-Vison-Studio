"""Record decoded source gaps even when another effect makes a group nonempty."""
from copy import deepcopy


def record_empty_sources(entry, spawns, docs, audits):
    for spawn in spawns:
        doc=docs[spawn['file']]
        if any(doc['frames']):
            continue
        audit=audits.get(spawn['file'],{})
        coverage=entry.setdefault('visualCoverage',{'complete':True,'omitted':[]})
        coverage['complete']=False
        omission={'reason':'source decoder emitted no drawable sprites', 'spawn':deepcopy(spawn),
                  'count':1,'decoderEvidence':{'decodedSpriteFrames':0,'decodedFrames':len(doc['frames']),
                  'textureReferences':len(doc.get('textures',[])),
                  'declaredFrames':audit.get('declaredFrames')}}
        if omission not in coverage['omitted']:
            coverage['omitted'].append(omission)
        issue=spawn['file']+': source decoder emitted no drawable sprites; source channel remains unresolved'
        if issue not in entry['issues']:
            entry['issues'].append(issue)
