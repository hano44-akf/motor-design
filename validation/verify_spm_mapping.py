"""Live configuration/persistence check for all six SPM shape/direction pairs."""
from pathlib import Path
import json
from low_voltage import start
from motorcad_adapter import apply_checked

ROOT=Path(__file__).resolve().parent
if __name__=='__main__':
    out=ROOT/'automation';out.mkdir(exist_ok=True);mc=None;records=[]
    try:
        mc,_=start()
        for shape in ['Radial','Parallel','Breadloaf']:
            for direction in ['Parallel','Radial']:
                mc.load_from_file(str(ROOT/'baseline.mot'))
                requested={'shape':shape,'magnetisation':direction}
                before=apply_checked(mc,requested)
                path=out/f'{shape}_{direction}.mot';mc.save_to_file(str(path));mc.load_from_file(str(path))
                after={k:mc.get_variable(k) for k in before}
                if before!=after:raise RuntimeError('Saved model did not preserve mapping')
                records.append({'shape':shape,'magnetisation':direction,'readback':after,'save_reload_pass':True})
        (out/'spm_mapping_verification.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
        print('PASS: all six shape/magnetisation pairs applied and preserved after save/reload')
    finally:
        if mc:mc.quit()
