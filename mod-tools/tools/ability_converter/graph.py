"""Region/version-aware action references with iterative cycle detection."""
from collections import defaultdict
from .catalog import record_scope, reference_scope


class SkillGraph:
    def __init__(self):
        self.nodes = {}
        self.identities = defaultdict(list)

    def add(self, result):
        source = result["source"]
        key = source["key"]
        if key in self.nodes:
            raise ValueError(f"Duplicate source identity {key}")
        kind = record_scope(source)
        self.identities[source["source"], kind, source["id"]].append(key)
        self.nodes[key] = {"source": source, "dependencies": result["dependencies"], "status": result["status"]}

    def resolve(self, catalog=None):
        edges, missing, ambiguous = [], [], []
        adjacency = defaultdict(list)
        for key, node in self.nodes.items():
            for dep in node["dependencies"]:
                candidates = ([p["key"] for p in catalog.candidates(node["source"], dep)] if catalog else
                    self.identities.get((node["source"]["source"], reference_scope(node["source"], dep["kind"]), dep["id"]), []))
                if dep['relation']=='tag':
                    if str(dep['id'])==str(node['source']['id']):
                        candidates=[key]
                    elif not catalog and node['source']['kind']!='enemy':
                        lbs=self.identities.get((node['source']['source'],'lb',dep['id']),[])
                        if lbs:candidates=[*candidates,max(lbs,key=lambda k:int(self.nodes[k]['source']['level'] or 0))]
                edge = {"from":key, **dep, "to":None}
                if not catalog and dep["kind"] == "lb" and candidates:
                    candidates = [max(candidates, key=lambda k: int(self.nodes[k]["source"]["level"] or 0))]
                if len(candidates) == 1:
                    edge["to"] = candidates[0]
                    if candidates[0] not in self.nodes:
                        edge["outsideSelection"] = True
                    elif dep["relation"] not in ("prerequisite", "unlock", "lb_variant", "charge_pool", "tag"):
                        adjacency[key].append(candidates[0])
                elif not candidates:
                    missing.append(edge)
                else:
                    ambiguous.append({**edge, "candidates":candidates})
                edges.append(edge)
        # Iterative DFS remains bounded even for long chains in enemy data.
        colors, cycles = {}, []
        for start in self.nodes:
            if colors.get(start):
                continue
            colors[start] = 1
            path, positions = [start], {start:0}
            stack = [(start, iter(adjacency[start]))]
            while stack:
                node, children = stack[-1]
                child = next(children, None)
                if child is None:
                    colors[node] = 2
                    stack.pop(); positions.pop(node); path.pop()
                elif colors.get(child) == 1:
                    cycles.append(path[positions[child]:]+[child])
                elif not colors.get(child):
                    colors[child] = 1
                    positions[child] = len(path); path.append(child)
                    stack.append((child, iter(adjacency[child])))
        return {"nodes":len(self.nodes),"edges":edges,"missing":missing,"ambiguous":ambiguous,"cycles":cycles}
