import unittest
from decimal import Decimal, InvalidOperation
from normalize_materials import RULES, si

class ConversionTests(unittest.TestCase):
    def test_temperature_offset_not_multiplier(self):
        self.assertEqual(Decimal(si('-40',RULES['Temperature'])[0]),Decimal('233.15'))
    def test_percent_coefficient(self):
        self.assertEqual(Decimal(si('-0.12',RULES['MagnetTempCoefBr'])[0]),Decimal('-0.0012'))
    def test_fractional_coefficient_not_percent(self):
        self.assertEqual(Decimal(si('0.00393',RULES['TempCoefElectricalResistivity'])[0]),Decimal('0.00393'))
    def test_dimensions(self):
        self.assertEqual(Decimal(si('0.35',RULES['LaminationThickness'])[0]),Decimal('0.00035'))
        self.assertEqual(Decimal(si('160000',RULES['YoungsCoefficient'])[0]),Decimal('160000000000'))
    def test_loss_is_mass_specific(self):
        self.assertEqual(RULES['LossDensity']['si_unit'],'W/kg')
        self.assertEqual(Decimal(si('2.3',RULES['LossDensity'])[0]),Decimal('2.3'))
    def test_reject_malformed_and_nonfinite(self):
        for raw in ['212BValue[0]=0.0177','NaN','Infinity']:
            with self.assertRaises((InvalidOperation,ValueError)):
                si(raw,RULES['YieldStress'])
    def test_no_guessed_polynomial_units(self):
        self.assertNotIn('MagnetTempCoefBr_Maxwell_2',RULES)

if __name__=='__main__':unittest.main()
