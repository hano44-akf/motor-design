from low_voltage import *
mc=None
try:
 mc,launch=start()
 solve(mc,'pilot_arc120',85,20,6,1.8,40)
except Exception:print(traceback.format_exc(),flush=True)
finally:
 if mc:mc.quit()
