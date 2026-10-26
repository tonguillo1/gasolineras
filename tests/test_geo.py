import sys, pathlib, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from gasolineras import geo

BCN = (41.3874, 2.1700)
LLEIDA = (41.6176, 0.6200)


class TestGeo(unittest.TestCase):
    def test_haversine_distancia_conocida(self):
        # Barcelona-Lleida en linea recta. Comprobado aparte sobre la
        # esfera: dlon 1,55 grados a lat 41,5 son 129,2 km y dlat 0,23 son
        # 25,6 km, hipotenusa 131,7 km.
        d = geo.haversine(*BCN, *LLEIDA)
        self.assertAlmostEqual(d, 131.6, delta=0.5)

    def test_haversine_mismo_punto(self):
        self.assertEqual(geo.haversine(*BCN, *BCN), 0.0)

    def test_dist_a_segmento_proyeccion_interior(self):
        # Punto justo al norte del punto medio de un segmento este-oeste.
        a, b = (41.0, 1.0), (41.0, 2.0)
        p = (41.09, 1.5)  # ~10 km al norte
        self.assertAlmostEqual(geo.dist_a_segmento(p, a, b), 10, delta=0.5)

    def test_dist_a_segmento_fuera_del_extremo(self):
        # Mas alla del extremo: la distancia es al extremo, no a la recta.
        a, b = (41.0, 1.0), (41.0, 2.0)
        p = (41.0, 3.0)
        d = geo.dist_a_segmento(p, a, b)
        esperado = geo.haversine(41.0, 3.0, 41.0, 2.0)
        self.assertAlmostEqual(d, esperado, delta=1.0)

    def test_dist_a_segmento_degenerado(self):
        a = b = (41.0, 1.0)
        self.assertAlmostEqual(geo.dist_a_segmento((41.09, 1.0), a, b), 10, delta=0.5)

    def test_submuestrear_conserva_extremos(self):
        pts = [(41.0 + i * 0.001, 1.0) for i in range(500)]
        out = geo.submuestrear(pts, paso_km=1.0)
        self.assertEqual(out[0], pts[0])
        self.assertEqual(out[-1], pts[-1])
        self.assertLess(len(out), len(pts))
        # ~55 km de recorrido a paso de 1 km: del orden de 55 vertices.
        self.assertAlmostEqual(len(out), 56, delta=5)

    def test_submuestrear_vacio(self):
        self.assertEqual(geo.submuestrear([]), [])

    def test_submuestrear_un_punto(self):
        self.assertEqual(geo.submuestrear([BCN]), [BCN])


if __name__ == "__main__":
    unittest.main(verbosity=2)
