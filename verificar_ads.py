#!/usr/bin/env python3
"""
verificar_ads.py — ¿Sirve este token para leer campañas de Meta Ads?

POR QUÉ EXISTE
El token del panel (IG_PAGE_TOKEN) es de PÁGINA, y las cuentas publicitarias cuelgan del
USUARIO. Es como tener la llave del local pero no la de la caja fuerte: las dos son llaves
de verdad, abren cosas distintas.

Antes de escribir el módulo de campañas hay que confirmar tres cosas, y este script las
chequea de una: que el token sea de usuario, que tenga ads_read, y que efectivamente vea
alguna cuenta publicitaria con datos.

USO
    python3 verificar_ads.py 'EL_TOKEN_QUE_GENERASTE'

o dejándolo en el .env de la raíz del repo como META_ACCESS_TOKEN y corriendo:

    python3 verificar_ads.py

No guarda nada ni modifica nada: solo pregunta y te dice qué encontró.
"""

import json
import os
import sys
import urllib.parse
import urllib.request

VERSION = "v23.0"
GRAPH = f"https://graph.facebook.com/{VERSION}"
RAIZ = os.path.dirname(os.path.abspath(__file__))  # el .env está acá al lado


def get(ruta, token, **params):
    params["access_token"] = token
    url = f"{GRAPH}/{ruta}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detalle = json.loads(e.read() or b"{}").get("error", {})
        return {"_error": detalle.get("message", str(e)), "_code": detalle.get("code")}
    except Exception as e:
        return {"_error": str(e)}


def token_del_env():
    ruta = os.path.join(RAIZ, ".env")
    if not os.path.exists(ruta):
        return None
    for linea in open(ruta):
        if linea.startswith("META_ACCESS_TOKEN="):
            return linea.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def main():
    token = sys.argv[1] if len(sys.argv) > 1 else token_del_env()
    if not token:
        sys.exit("Pasá el token como argumento, o ponelo en el .env de la raíz "
                 "como META_ACCESS_TOKEN.\n"
                 "    python3 verificar_ads.py 'EAAxxxx...'")

    print("1. Mirando qué es este token...")
    d = get("debug_token", token, input_token=token).get("data", {})
    if not d:
        sys.exit("   NO SIRVE: el token no es válido o ya venció.")

    tipo = d.get("type", "?")
    scopes = d.get("scopes", [])
    expira = d.get("expires_at", 0)
    print(f"   tipo: {tipo}")
    print(f"   vence: {'nunca' if expira == 0 else expira}")

    if "ads_read" not in scopes:
        print("   FALTA el permiso ads_read.")
        print(f"   permisos que sí tiene: {', '.join(sorted(scopes)) or '(ninguno)'}")
        sys.exit("   Volvé a generar el token marcando ads_read.")
    print("   ads_read: OK")

    print("\n2. Buscando cuentas publicitarias...")
    cuentas = get("me/adaccounts", token,
                  fields="name,account_id,account_status,currency,amount_spent").get("data")
    if cuentas is None or not cuentas:
        print("   Ninguna. Dos motivos posibles:")
        print("   - Es un token de PÁGINA (las cuentas de ads cuelgan del usuario), o")
        print("   - Tu usuario no tiene ninguna cuenta publicitaria creada.")
        sys.exit("   Sin cuenta publicitaria no hay nada que mostrar en el panel.")

    # account_status: 1 = activa. El resto son pausadas, en revisión o cerradas.
    for c in cuentas:
        estado = "activa" if c.get("account_status") == 1 else f"estado {c.get('account_status')}"
        gastado = int(c.get("amount_spent", 0)) / 100  # Meta lo devuelve en centavos
        print(f"   act_{c['account_id']}  {c.get('name', '?')[:34]:36} "
              f"{c.get('currency', '?')}  gastado histórico: {gastado:,.0f}  [{estado}]")

    print("\n3. Probando leer campañas y métricas de la primera cuenta...")
    act = f"act_{cuentas[0]['account_id']}"
    camps = get(f"{act}/campaigns", token, fields="name,status,objective", limit=5)
    if "_error" in camps:
        sys.exit(f"   No pude leer campañas: {camps['_error']}")
    lista = camps.get("data", [])
    print(f"   campañas visibles: {len(lista)}")
    for c in lista[:5]:
        print(f"     - [{c.get('status')}] {c.get('name', '?')[:50]}  ({c.get('objective', '?')})")

    ins = get(f"{act}/insights", token,
              fields="spend,impressions,reach,clicks,ctr,cpm,frequency",
              date_preset="last_30d")
    if "_error" in ins:
        print(f"   Métricas: no pude leerlas ({ins['_error']})")
    else:
        filas = ins.get("data", [])
        if not filas:
            print("   Métricas: la cuenta existe pero no gastó nada en los últimos 30 días.")
        else:
            f = filas[0]
            print(f"   Métricas últimos 30 días: gasto {f.get('spend')} · "
                  f"impresiones {f.get('impressions')} · alcance {f.get('reach')} · "
                  f"CTR {f.get('ctr')}% · CPM {f.get('cpm')}")

    print("\nLISTO: este token sirve para el panel.")
    print("Guardalo en el .env de la raíz como META_ACCESS_TOKEN y avisame.")


if __name__ == "__main__":
    main()
