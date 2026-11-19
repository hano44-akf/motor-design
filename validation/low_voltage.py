"""Reusable isolated Motor-CAD low voltage study. Internal dimensions mm, phase currents checked in exports."""
from pathlib import Path
import json,csv,time,math,shutil,traceback,hashlib,re
from ansys.motorcad.core import MotorCAD
from dimension_grid import mm,wire_outer
from geometry_adapters import build_geometry
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'optimization_12V_50PN470';OUT.mkdir(exist_ok=True)
SOURCE=Path('C:/Users/jo061/AppData/Roaming/Ansys/v261/MotorCAD/materials')
def parse_csv(path):
 text=path.read_text(encoding='cp1252',errors='replace');d={}
 for row in csv.reader(text.splitlines(),delimiter=';'):
  if len(row)>1:
   try:d.setdefault(row[0],float(row[1]))
   except ValueError:pass
 return d,'Operating point outside voltage limit' in text
def start():
 t=time.perf_counter();mc=MotorCAD(open_new_instance=True,keep_instance_open=False);mc.set_variable('MessageDisplayState',2);mc.set_visible(False)
 return mc,time.perf_counter()-t
def prepare(mc,core='POSCO | 50PN470',magnet='JL Mag Rare-Earth | N48UH'):
 seed=(ROOT/'baseline.mot').read_text(encoding='latin1')
 for key in ['Windage_Loss_@Ref_Speed','Windage_Loss_(Ext_Fan)_@Ref_Speed','Friction_Loss_[F]_@Ref_Speed','Friction_Loss_[R]_@Ref_Speed','Encoder_Loss_@Ref_Speed']:
  seed=re.sub(r'^'+re.escape(key)+r'=.*$',key+'=0',seed,flags=re.M)
 (OUT/'zero_mechanical_seed.mot').write_text(seed,encoding='latin1')
 mc.load_from_file(str(OUT/'zero_mechanical_seed.mot'))
 db=OUT/'working_materials.mdb'
 if not db.exists():shutil.copy2(SOURCE/'solids_test.mdb',db)
 mc.select_material_database(str(db),False)
 for source,name in [(SOURCE/'Granta_Steels/Electrical_steel_non_grain_oriented.gdb',core),(SOURCE/'Granta_Magnets/Neodymium_magnet_JL_Mag.gdb',magnet)]:
  print('IMPORT '+name,flush=True);mc.import_solid_material(str(source),name)
 components={'Stator Lam (Back Iron)':core,'Stator Lam (Tooth)':core,'Rotor Lam (Back Iron)':core,'Magnet':magnet}
 for comp,name in components.items():mc.set_component_material(comp,name)
 readback={comp:mc.get_component_material(comp) for comp in components}
 for comp,name in components.items():
  if readback[comp]!=name:raise RuntimeError('Material assignment mismatch '+comp)
 settings={'ShaftSpeed':3500,'CurrentDefinition':0,'PhaseAdvance':0,'DCBusVoltage':9,'WindingConnection':1,'NumberStrandsHand':1,'ParallelPaths':1,'TorquePointsPerCycle':60,'TorqueNumberCycles':1,'BackEMFPointsPerCycle':60,'BackEMFNumberCycles':1,'BackEMFCalculation':True,'TorqueCalculation':True,'CoggingTorqueCalculation':False,'ElectromagneticForcesCalc_OC':False,'ElectromagneticForcesCalc_Load':False,'TorqueSpeedCalculation':False,'DemagnetizationCalc':False,'InductanceCalc':False,'BPMShortCircuitCalc':False,'Magnet_Temperature':20,'StatorConductor_Temperature':20,'StatorLam_Temperature':20,'RotorLam_Temperature':20}
 for k,v in settings.items():mc.set_variable(k,v)
 mc.save_to_file(str(OUT/'material_seed.mot'))
 (OUT/'material_assignments.json').write_text(json.dumps(readback,indent=2),encoding='utf-8')
 return readback
def configure(mc,d,l,n,wire,current,voltage=9,points=60,geometry=None,rotor_options=None):
 if any(abs(value-mm(value))>1e-8 for value in [d,l,wire]):raise ValueError('Independent dimensions must be on the 0.1 mm grid')
 dimensions=build_geometry(rotor_options or {'shape':'Radial'},d,l,geometry)
 # Always restore the same seed so changes do not accumulate between candidates.
 mc.load_from_file(str(OUT/'material_seed.mot'))
 mc.set_variable('Pole_Number',4)
 mc.set_variable('Slot_Number',12)
 mc.set_variable('Magnet_Arc_[ED]',120)
 for k,value in dimensions.items():
  if abs(value-mm(value))>1e-8:raise ValueError('Dimension must be on 0.1 mm grid: '+k)
  mc.set_variable(k,value)
 mc.set_variable('Wire_Type_Stator',2)
 for k,v in {'MagTurnsConductor':int(n),'Copper_Diameter':mm(wire),'Wire_Diameter':wire_outer(wire),'NumberStrandsHand':1,'ParallelPaths':1,'PeakCurrent':current,'DCBusVoltage':voltage,'TorquePointsPerCycle':points,'BackEMFPointsPerCycle':points}.items():mc.set_variable(k,v)
 if points>=120:
  mc.set_variable('TorqueNumberCycles',2)
  mc.set_variable('BackEMFNumberCycles',2)
 return dimensions
def solve(mc,label,d,l,n,wire,current,voltage=9,points=60,options=None,geometry=None,calculation_settings=None,graph_names=None):
 starttime=time.perf_counter();dimensions=configure(mc,d,l,n,wire,current,voltage,points,geometry,options)
 applied={}
 if options is not None:
  from motorcad_adapter import apply_checked
  applied=apply_checked(mc,options)
 if calculation_settings:
  allowed={'CoggingTorqueCalculation','TorqueNumberCycles','BackEMFNumberCycles',
           'AirgapMeshPoints_layers','AirgapMeshPoints_mesh','MagnetMeshLength','StatorLamMeshLength','RotorLamMeshLength'}
  if set(calculation_settings)-allowed:raise ValueError('Unsupported diagnostic calculation setting')
  for key,value in calculation_settings.items():
   mc.set_variable(key,value)
   if abs(float(mc.get_variable(key))-float(value))>1e-9:raise RuntimeError('Diagnostic setting readback mismatch: '+key)
 model=OUT/(label+'.mot');mc.save_to_file(str(model));setup=time.perf_counter()-starttime
 t=time.perf_counter();mc.do_magnetic_calculation();solver=time.perf_counter()-t
 t=time.perf_counter();csvpath=OUT/(label+'.csv');mc.export_results('EMagnetic',str(csvpath));values,outside=parse_csv(csvpath)
 readback={k:mc.get_variable(k) for k in ['WindingConnection','NumberStrandsHand','ParallelPaths','MagTurnsConductor','Copper_Diameter','Wire_Diameter','PeakCurrent','DCBusVoltage','Slot_Number','Pole_Number','PhaseAdvance']}
 readback.update({key:mc.get_variable(key) for key in applied})
 if any(abs(readback[key]-value)>1e-7 for key,value in applied.items()):
  raise RuntimeError('Applied input changed during magnetic calculation')
 if abs(readback['Copper_Diameter']-wire)>1e-6:raise RuntimeError('Requested wire diameter was not applied')
 geometry_readback={key:mc.get_variable(key) for key in dimensions}
 for key,value in dimensions.items():
  if abs(geometry_readback[key]-value)>1e-6:raise RuntimeError('Dimension changed during solve: '+key)
 mc.save_to_file(str(model));post=time.perf_counter()-t
 result=dict(label=label,design=dict(diameter_mm=d,length_mm=l,turns_per_coil=n,wire_diameter_mm=wire,input_peak_current_A=current,voltage_V=voltage),values=values,voltage_limit_exceeded=outside,readback=readback,timings=dict(setup_s=setup,solver_s=solver,export_save_s=post,total_s=time.perf_counter()-starttime))
 result['geometry_mm']=geometry_readback
 result['derived_lengths_mm']={'EWdg_MLT':mc.get_variable('EWdg_MLT')}
 result['dimension_resolution_scope']='Independent geometry and conductor dimension inputs; derived winding lengths are not rounded in loss calculations'
 result['dimension_resolution_mm']=.1
 if calculation_settings:result['calculation_settings']=calculation_settings
 if graph_names:
  graphs={};graph_errors={}
  for name in graph_names:
   try:
    gx,gy=mc.get_magnetic_graph(name)
    gx,gy=list(map(float,gx)),list(map(float,gy))
    if len(gx)!=len(gy) or not gy or not all(math.isfinite(v) for v in gx+gy):raise ValueError('Invalid graph samples')
    graphs[name]={'x':gx,'y':gy,'mean':sum(gy)/len(gy),'peak_to_peak':max(gy)-min(gy),
                  'axis_units':'Native Motor-CAD graph axes; confirm angle convention before FFT order interpretation'}
   except Exception as exc:graph_errors[name]=str(exc)
  result['graphs']=graphs;result['graph_errors']=graph_errors
 if geometry:result['design']['geometry_mm']=geometry
 if options is not None:
  result['input_options']=options
  result['component_materials']={k:mc.get_component_material(k) for k in ['Stator Lam (Back Iron)','Stator Lam (Tooth)','Rotor Lam (Back Iron)','Magnet']}
 (OUT/(label+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(dict(label=label,T=values.get('Shaft Torque'),eta=values.get('System Efficiency'),V=values.get('Line-Line Terminal Voltage (rms)'),outside=outside,phase_peak=values.get('Phase Current (peak)'),line_peak=values.get('Line Current (peak)'),R=values.get('Phase Resistance'),fill=values.get('Copper Slot Fill (Slot Area)'),solver_s=solver)),flush=True)
 return result
if __name__=='__main__':
 mc=None;t=time.perf_counter()
 try:
  mc,launch=start();prepare(mc)
  (OUT/'startup_timing.json').write_text(json.dumps({'launch_s':launch,'material_setup_s':time.perf_counter()-t-launch}),encoding='utf-8')
  solve(mc,'pilot',70,35,2,1.5,35)
 except Exception:
  (OUT/'error.txt').write_text(traceback.format_exc(),encoding='utf-8');print(traceback.format_exc(),flush=True)
 finally:
  if mc:mc.quit()


