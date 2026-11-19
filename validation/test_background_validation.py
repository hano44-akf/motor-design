import unittest
from background_validation import controls_differ


class BackgroundTests(unittest.TestCase):
    def test_bus_alone_is_not_a_new_electromagnetic_control_point(self):
        a={'phase_peak_A':20.,'phase_advance_deg':0.,'bus':9}
        b={**a,'bus':16}
        self.assertFalse(controls_differ(a,b))
        b['phase_advance_deg']=5
        self.assertTrue(controls_differ(a,b))
        b={**a,'phase_peak_A':21}
        self.assertTrue(controls_differ(a,b))

if __name__=='__main__':unittest.main()
