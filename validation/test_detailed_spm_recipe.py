import unittest
from detailed_spm_recipe import compile_recipe,apply_recipe_checked


def request(shape='Radial'):
    return {'spm':{'shape':shape,'magnetisation':'Parallel' if shape=='Parallel' else 'Radial'},
        'pole_slot_candidates':[{'poles':4,'slots':12}],
        'dimensions':{'diameter_mm':85,'length_mm':20},'airgap_bounds_mm':[.4,.6],
        'geometry_parameters':{'slot_depth_mm':{'mode':'range','min':9,'max':11}},
        }


class FakeMC:
    def __init__(self):self.values={}
    def set_variable(self,key,value):self.values[key]=value
    def get_variable(self,key):return self.values[key]


class RecipeTests(unittest.TestCase):
    def test_pilot_count_and_holdout_separation(self):
        from detailed_spm_plan import make_plan
        plan=make_plan()
        self.assertEqual(plan['planned_fea'],38)
        self.assertEqual(plan['mapping_save_readback_checks'],3)
        self.assertEqual(plan['executed_fea'],0)
        for group in plan['groups']:
            points=[tuple(sorted(case['point'].items())) for case in group['cases']]
            self.assertEqual(len(points),len(set(points)))
            self.assertEqual(sum(c['role']=='independent_holdout' for c in group['cases']),3)
            for case in group['cases']:
                self.assertFalse(case['recipe']['performance_model_connected'])

    def test_explicit_values_reach_native_and_readback(self):
        r=request();r['spm']['parameters']={'pole_arc_ed':{'mode':'fixed','value':130},'magnet_thickness_mm':{'mode':'fixed','value':2.8}}
        recipe=compile_recipe(r,{'slot_depth_mm':10.2,'airgap_mm':.5})
        values=apply_recipe_checked(FakeMC(),recipe)
        self.assertEqual(values['Slot_Depth'],10.2)
        self.assertEqual(values['Magnet_Thickness'],2.8)
        self.assertEqual(values['Magnet_Arc_[ED]'],130)
        self.assertFalse(recipe['performance_model_connected'])
        self.assertIsNone(recipe['performance']['efficiency_pct'])
        self.assertEqual(r['geometry_parameters']['slot_depth_mm']['mode'],'range')

    def test_ranges_cannot_silently_use_midpoints(self):
        for point in ({},{'slot_depth_mm':10},{'slot_depth_mm':12,'airgap_mm':.5},{'slot_depth_mm':10.25,'airgap_mm':.5}):
            with self.assertRaises(ValueError):compile_recipe(request(),point)

    def test_pending_mapping_is_blocked_before_mutation(self):
        recipe=compile_recipe(request('Breadloaf'),{'slot_depth_mm':10,'airgap_mm':.5})
        mc=FakeMC()
        with self.assertRaises(ValueError):apply_recipe_checked(mc,recipe)
        self.assertEqual(mc.values,{})

    def test_mismatch_is_not_accepted(self):
        class WrongMC(FakeMC):
            def get_variable(self,key):return super().get_variable(key)+(.1 if key=='Slot_Depth' else 0)
        with self.assertRaises(RuntimeError):apply_recipe_checked(WrongMC(),compile_recipe(request(),{'slot_depth_mm':10,'airgap_mm':.5}))

    def test_other_windings_and_interference_are_blocked(self):
        r=request();r['pole_slot_candidates']=[{'poles':8,'slots':12}]
        with self.assertRaises(ValueError):compile_recipe(r,{'slot_depth_mm':10,'airgap_mm':.5})
        r=request();r['geometry_parameters']['slot_depth_mm']={'mode':'fixed','value':20}
        with self.assertRaises(ValueError):compile_recipe(r,{'airgap_mm':.5})


if __name__=='__main__':unittest.main()
