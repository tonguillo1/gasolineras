"""No es un test unitario: mide el parser contra TODOS los horarios reales."""
import sys, pathlib, json, glob, collections
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from gasolineras import horarios

f = glob.glob(sys.argv[1])[0]
L = json.load(open(f, encoding="utf-8-sig"))["ListaEESSPrecio"]
crudos = [e["Horario"].strip() for e in L]

no_fiables, sin_tramos, ok = [], [], 0
for c in crudos:
    h = horarios.parse(c)
    if not h.fiable:
        no_fiables.append(c)
    elif not any(h.tramos.values()):
        sin_tramos.append(c)
    else:
        ok += 1

print(f"estaciones            : {len(crudos)}")
print(f"parseadas con franjas : {ok}  ({100*ok/len(crudos):.1f}%)")
print(f"marcadas no fiables   : {len(no_fiables)}  ({100*len(no_fiables)/len(crudos):.1f}%)")
print(f"fiables pero vacias   : {len(sin_tramos)}  <-- deberia ser 0")
print()
print("=== muestras de no fiable (deben ser de un solo dia o ilegibles) ===")
for c, n in collections.Counter(no_fiables).most_common(8):
    print(f"  {n:5}  {c!r}")
if sin_tramos:
    print("\n=== FALLO: fiables sin franjas ===")
    for c, n in collections.Counter(sin_tramos).most_common(15):
        print(f"  {n:5}  {c!r}")
