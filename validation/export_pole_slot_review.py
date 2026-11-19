"""Export analytical winding candidates without starting Motor-CAD."""
import json
from pathlib import Path
from rotor_catalog import preflight

def export(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    root=Path(__file__).resolve().parent
    request=json.loads((root/'jobs/20261022_162610/request.json').read_text(encoding='utf-8'))
    request['pole_slot_candidates']=[{'poles':p,'slots':q} for p,q in [(4,12),(8,12),(10,12),(14,12),(8,9),(10,9),(8,18),(10,18),(16,18),(10,24),(14,24)]]
    result=preflight(request)
    (folder/'winding_candidates.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'request.json').write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

if __name__=='__main__':
    export(Path(__file__).resolve().parent.parent/'outputs/pole_slot_winding_20261027')
