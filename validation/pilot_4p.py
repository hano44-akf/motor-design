from low_voltage import *
mc=None
try:
 mc,launch=start()
 solve(mc,'pilot_4p',70,35,2,1.5,39)
except Exception:print(traceback.format_exc(),flush=True)
finally:
 if mc:mc.quit()
