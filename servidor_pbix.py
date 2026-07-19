#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor local para RyukPowerBi Dashboard
=========================================
Extrae los DATOS de archivos .pbix (comprimidos con XPress9, formato
propietario de Microsoft que el navegador no puede leer) y los entrega
a la página web para generar el dashboard.

Uso:
  1) pip install pbixray pandas
  2) python servidor_pbix.py
  3) Abre la página del dashboard y sube tu .pbix en "Leer .pbix"

El servidor solo escucha en tu propio computador (127.0.0.1) y no
envía nada a internet. Creado por RyukPlay · https://calypsobronte.github.io/
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import json, tempfile, uuid, os

import time

# En la nube (Render, Railway...) la plataforma define PORT y hay que
# escuchar en 0.0.0.0; en local se usa 127.0.0.1:8765 por defecto.
PUERTO   = int(os.environ.get('PORT', 8765))
HOST     = os.environ.get('HOST', '0.0.0.0' if 'PORT' in os.environ else '127.0.0.1')
MAX_MB   = int(os.environ.get('MAX_MB', 150))     # tamaño máximo de .pbix
TTL_SEG  = int(os.environ.get('TTL_MIN', 30)) * 60  # vida de cada sesión
MAX_SES  = 15                                      # sesiones simultáneas máximas

MODELOS = {}   # token → {'modelo': PBIXRay, 'ruta': tmp, 'hora': ts}


def limpiar_sesiones():
    ahora = time.time()
    tokens = sorted(MODELOS, key=lambda t: MODELOS[t]['hora'])
    for t in tokens:
        viejo = (ahora - MODELOS[t]['hora']) > TTL_SEG
        exceso = len(MODELOS) > MAX_SES
        if viejo or exceso:
            try: os.unlink(MODELOS[t]['ruta'])
            except OSError: pass
            del MODELOS[t]


def cargar_pbixray():
    try:
        from pbixray import PBIXRay
        return PBIXRay
    except ImportError:
        return None


class Manejador(BaseHTTPRequestHandler):

    # ---------- utilidades ----------
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _json(self, codigo, contenido):
        cuerpo = contenido if isinstance(contenido, (str, bytes)) \
                 else json.dumps(contenido, ensure_ascii=False)
        if isinstance(cuerpo, str):
            cuerpo = cuerpo.encode('utf-8')
        self.send_response(codigo)
        self._cors()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *args):  # silenciar log por defecto
        pass

    # ---------- rutas ----------
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if u.path == '/salud':
            return self._json(200, {'ok': True, 'pbixray': cargar_pbixray() is not None})

        if u.path == '/tabla':
            token  = q.get('token', [''])[0]
            nombre = q.get('nombre', [''])[0]
            maxf   = int(q.get('max', ['50000'])[0])
            ses = MODELOS.get(token)
            if ses is None:
                return self._json(404, {'error': 'Sesión no encontrada o expirada. Vuelve a subir el archivo .pbix.'})
            modelo = ses['modelo']
            ses['hora'] = time.time()
            try:
                df = modelo.get_table(nombre).head(maxf)
                # to_json maneja NaN→null y fechas en formato ISO
                return self._json(200, df.to_json(orient='records', date_format='iso', force_ascii=False))
            except Exception as e:
                return self._json(500, {'error': f'No se pudo leer la tabla "{nombre}": {e}'})

        return self._json(404, {'error': 'Ruta no encontrada'})

    def do_POST(self):
        if urlparse(self.path).path != '/subir':
            return self._json(404, {'error': 'Ruta no encontrada'})

        PBIXRay = cargar_pbixray()
        if PBIXRay is None:
            return self._json(500, {'error': 'Falta la librería pbixray. Instálala con: pip install pbixray pandas'})

        tam = int(self.headers.get('Content-Length', '0') or 0)
        if tam <= 0:
            return self._json(400, {'error': 'No llegó ningún archivo.'})
        if tam > MAX_MB * 1024 * 1024:
            return self._json(413, {'error': f'El archivo supera el límite de {MAX_MB} MB.'})
        limpiar_sesiones()

        datos = self.rfile.read(tam)
        tmp = tempfile.NamedTemporaryFile(suffix='.pbix', delete=False)
        tmp.write(datos)
        tmp.close()

        try:
            modelo = PBIXRay(tmp.name)
            tablas = [str(t) for t in modelo.tables]
            token = uuid.uuid4().hex
            MODELOS[token] = {'modelo': modelo, 'ruta': tmp.name, 'hora': time.time()}

            respuesta = {'token': token, 'tablas': tablas}

            # Extras opcionales: si alguna falla, se omite sin romper
            try:
                respuesta['medidas'] = int(len(modelo.dax_measures))
            except Exception:
                pass
            try:
                esquema = modelo.schema  # DataFrame: tabla, columna, tipo
                cols = {}
                for _, fila in esquema.iterrows():
                    cols.setdefault(str(fila.iloc[0]), []).append(str(fila.iloc[1]))
                respuesta['columnas'] = cols
            except Exception:
                pass

            return self._json(200, respuesta)
        except Exception as e:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            return self._json(500, {'error': f'pbixray no pudo abrir el archivo: {e}'})


if __name__ == '__main__':
    disponible = cargar_pbixray() is not None
    print('=' * 56)
    print('  RyukPowerBi · Servidor local de lectura de .pbix')
    print('=' * 56)
    if not disponible:
        print('  ⚠ Falta pbixray. Ejecuta:  pip install pbixray pandas')
    print(f'  Escuchando en http://{HOST}:{PUERTO}')
    print('  Deja esta ventana abierta y sube tu .pbix en la página.')
    print('  (Ctrl+C para detener)')
    try:
        ThreadingHTTPServer((HOST, PUERTO), Manejador).serve_forever()
    except KeyboardInterrupt:
        print('\n  Servidor detenido.')
