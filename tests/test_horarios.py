import sys, pathlib, unittest
from datetime import datetime
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from gasolineras.horarios import parse

# Lunes 26/10/2026 no: ese dia es lunes en 2026? Se fijan fechas explicitas abajo.
LUN = datetime(2026, 10, 26, 10, 0)   # lunes
SAB = datetime(2026, 10, 31, 10, 0)   # sabado
DOM = datetime(2026, 11, 1, 10, 0)    # domingo


class TestHorarios(unittest.TestCase):
    def test_veinticuatro_horas(self):
        h = parse("L-D: 24H")
        self.assertTrue(h.es_24h())
        for t in (LUN, SAB, DOM, datetime(2026, 10, 26, 3, 30)):
            self.assertIs(h.abierta(t), True, t)

    def test_franja_simple(self):
        h = parse("L-D: 06:00-22:00")
        self.assertIs(h.abierta(datetime(2026, 10, 26, 7, 0)), True)
        self.assertIs(h.abierta(datetime(2026, 10, 26, 5, 59)), False)
        self.assertIs(h.abierta(datetime(2026, 10, 26, 22, 0)), False)  # cierre exclusivo
        self.assertIs(h.abierta(datetime(2026, 10, 26, 21, 59)), True)

    def test_fin_medianoche_no_es_franja_nula(self):
        h = parse("L-D: 06:00-00:00")
        self.assertIs(h.abierta(datetime(2026, 10, 26, 23, 30)), True)
        self.assertIs(h.abierta(datetime(2026, 10, 26, 2, 0)), False)

    def test_cruce_de_medianoche_arrastra_al_dia_siguiente(self):
        h = parse("L-D: 06:00-02:00")
        self.assertIs(h.abierta(datetime(2026, 10, 26, 23, 0)), True)
        self.assertIs(h.abierta(datetime(2026, 10, 27, 1, 0)), True)   # madrugada del martes
        self.assertIs(h.abierta(datetime(2026, 10, 27, 3, 0)), False)

    def test_franja_partida_con_y(self):
        h = parse("L-V: 09:00-14:00 y 16:00-19:00")
        self.assertIs(h.abierta(datetime(2026, 10, 26, 10, 0)), True)
        self.assertIs(h.abierta(datetime(2026, 10, 26, 15, 0)), False)  # hora de comer
        self.assertIs(h.abierta(datetime(2026, 10, 26, 17, 0)), True)
        self.assertIs(h.abierta(SAB), False)

    def test_hora_sin_cero_inicial(self):
        h = parse("L-D: 7:00-22:00")
        self.assertIs(h.abierta(datetime(2026, 10, 26, 8, 0)), True)
        self.assertIs(h.abierta(datetime(2026, 10, 26, 6, 30)), False)

    def test_tramos_multiples_separados_por_punto_y_coma(self):
        h = parse("L-V: 06:00-22:00; S-D: 08:00-14:00")
        self.assertIs(h.abierta(datetime(2026, 10, 26, 21, 0)), True)
        self.assertIs(h.abierta(datetime(2026, 10, 31, 21, 0)), False)  # sabado tarde
        self.assertIs(h.abierta(datetime(2026, 10, 31, 9, 0)), True)

    def test_miercoles_es_X(self):
        h = parse("X-J: 08:00-20:00")
        self.assertIs(h.abierta(datetime(2026, 10, 28, 9, 0)), True)   # miercoles
        self.assertIs(h.abierta(datetime(2026, 10, 27, 9, 0)), False)  # martes

    def test_un_solo_dia_declarado_es_no_fiable(self):
        h = parse("L: 06:00-22:00")
        self.assertFalse(h.fiable)
        self.assertIsNone(h.abierta(LUN))       # no afirma abierta
        self.assertIsNone(h.abierta(DOM))       # ni cerrada
        self.assertIn("dudoso", h.descripcion())

    def test_basura_y_vacio_son_no_fiables(self):
        for crudo in ("", "   ", "sin especificar", "L-D"):
            with self.subTest(crudo=crudo):
                self.assertFalse(parse(crudo).fiable)
                self.assertIsNone(parse(crudo).abierta(LUN))

    def test_rango_invertido_envuelve_la_semana(self):
        h = parse("V-L: 08:00-20:00")  # viernes a lunes
        for d in (datetime(2026, 10, 30, 9, 0), datetime(2026, 10, 31, 9, 0),
                  datetime(2026, 11, 1, 9, 0), datetime(2026, 11, 2, 9, 0)):
            self.assertIs(h.abierta(d), True, d)
        self.assertIs(h.abierta(datetime(2026, 10, 28, 9, 0)), False)  # miercoles


if __name__ == "__main__":
    unittest.main(verbosity=2)
