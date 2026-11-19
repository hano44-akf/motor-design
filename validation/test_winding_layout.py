import math
import unittest
from winding_layout import synthesize


class WindingTests(unittest.TestCase):
    def test_known_pitch_and_distribution_factors(self):
        for p,q,y,kw in [(4,12,3,1),(4,12,2,math.sqrt(3)/2),(8,12,1,math.sqrt(3)/2),(10,12,1,(2+math.sqrt(3))/4),(2,12,6,math.cos(math.pi/12))]:
            w=synthesize(p,q,y)
            self.assertTrue(w['balanced'])
            for value in w['fundamental_winding_factors']:self.assertAlmostEqual(value,kw)

    def test_each_slot_has_two_opposite_coil_sides_and_equal_phase_counts(self):
        for p,q in [(4,12),(8,12),(10,12),(14,12),(8,9),(10,9),(8,18),(10,18),(16,18),(10,24),(14,24)]:
            w=synthesize(p,q)
            self.assertTrue(w['balanced'])
            self.assertEqual(sorted(c['start_slot'] for c in w['coils']),list(range(1,q+1)))
            self.assertEqual(sorted(c['end_slot'] for c in w['coils']),list(range(1,q+1)))
            self.assertEqual(len(set(w['coils_per_phase'])),1)
            self.assertFalse(w['motorcad_winding_verified'])
            self.assertTrue(all(-1e-10<=v<=1+1e-10 for values in w['harmonic_winding_factors'].values() for v in values))

    def test_unbalanced_family_and_input_validation(self):
        self.assertFalse(synthesize(4,10)['balanced'])
        for p,q,y in [(3,12,None),(True,12,None),(4,0,None),(4,12,0),(4,12,12),(4,10000,None)]:
            with self.assertRaises(ValueError):synthesize(p,q,y)

    def test_cache_cannot_be_mutated_by_client(self):
        w=synthesize(10,12);w['coils'].clear()
        self.assertEqual(len(synthesize(10,12)['coils']),12)


if __name__=='__main__':unittest.main()
