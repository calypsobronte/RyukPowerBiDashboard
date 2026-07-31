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


# ---------- MongoDB (para compartir dashboards por URL) ----------
# Configura MONGO_URI con tu cadena de conexión de MongoDB Atlas.
# La colección se crea sola al primer guardado; por defecto "dashboard"
# (cámbiala con MONGO_COLECCION si prefieres otro nombre).
_COL = None

def _normalizar_uri(uri):
    """Escapa usuario y contraseña según RFC 3986 (p. ej. una @ en la clave
    se vuelve %40). Es idempotente: si ya vienen escapados, no los daña."""
    try:
        from urllib.parse import quote_plus, unquote_plus
        for esquema in ('mongodb+srv://', 'mongodb://'):
            if uri.startswith(esquema):
                resto = uri[len(esquema):]
                if '@' not in resto:
                    return uri
                # El host no puede contener @, así que el último @ es el separador real
                cred, host = resto.rsplit('@', 1)
                if ':' in cred:
                    usuario, clave = cred.split(':', 1)
                    cred = quote_plus(unquote_plus(usuario)) + ':' + quote_plus(unquote_plus(clave))
                else:
                    cred = quote_plus(unquote_plus(cred))
                return esquema + cred + '@' + host
        return uri
    except Exception:
        return uri


def obtener_coleccion():
    global _COL
    if _COL is not None:
        return _COL, None
    uri = _normalizar_uri(os.environ.get('MONGO_URI', '').strip())
    if not uri:
        return None, 'Falta configurar MONGO_URI (cadena de conexión de MongoDB Atlas) en el servidor.'
    try:
        from pymongo import MongoClient
    except ImportError:
        return None, 'Falta la librería pymongo en el servidor. Instálala con: pip install pymongo'
    try:
        cliente = MongoClient(uri, serverSelectionTimeoutMS=6000)
        cliente.admin.command('ping')
        db  = cliente[os.environ.get('MONGO_DB', 'ryukpowerbi')]
        _COL = db[os.environ.get('MONGO_COLECCION', 'dashboard')]
        try:
            _COL.create_index('huella')
        except Exception:
            pass
        return _COL, None
    except Exception as e:
        return None, f'No se pudo conectar a MongoDB: {e}'


MAX_FILAS_COMPARTIR = int(os.environ.get('MAX_FILAS_COMPARTIR', 20000))
MAX_JSON_MB = int(os.environ.get('MAX_JSON_MB', 8))


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
            return self._json(200, {'ok': True,
                                    'version': '5.4',
                                    'pbixray': cargar_pbixray() is not None,
                                    'mongo': bool(os.environ.get('MONGO_URI', '').strip())})

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

        if u.path == '/dashboard/huella':
            col, err = obtener_coleccion()
            if col is None:
                return self._json(500, {'error': err})
            h = q.get('h', [''])[0]
            if not h:
                return self._json(400, {'error': 'Falta el parámetro h.'})
            doc = col.find_one({'huella': h})
            if not doc:
                return self._json(404, {'error': 'Sin dashboard para esta huella.'})
            return self._json(200, {'id': doc['_id'],
                                    'titulo': doc.get('titulo', ''),
                                    'creado': doc.get('creado', 0)})

        if u.path == '/dashboard':
            col, err = obtener_coleccion()
            if col is None:
                return self._json(500, {'error': err})
            id_dash = q.get('id', [''])[0]
            if not id_dash:
                return self._json(400, {'error': 'Falta el parámetro id.'})
            try:
                doc = col.find_one({'_id': id_dash})
            except Exception as e:
                return self._json(500, {'error': f'Error consultando MongoDB: {e}'})
            if not doc:
                return self._json(404, {'error': 'Dashboard no encontrado. El enlace puede ser incorrecto.'})
            return self._json(200, {'titulo': doc.get('titulo',''),
                                    'tipo': doc.get('tipo', 'dashboard'),
                                    'columnas': doc.get('columnas', []),
                                    'datos': doc.get('datos', []),
                                    'informe': doc.get('informe')})

        return self._json(404, {'error': 'Ruta no encontrada'})

    def do_POST(self):
        ruta = urlparse(self.path).path

        if ruta == '/dashboard':
            col, err = obtener_coleccion()
            if col is None:
                return self._json(500, {'error': err})
            tam = int(self.headers.get('Content-Length', '0') or 0)
            if tam <= 0:
                return self._json(400, {'error': 'No llegó ningún contenido.'})
            if tam > MAX_JSON_MB * 1024 * 1024:
                return self._json(413, {'error': f'El dashboard supera el límite de {MAX_JSON_MB} MB. Reduce las filas o columnas.'})
            try:
                cuerpo = json.loads(self.rfile.read(tam).decode('utf-8'))
            except Exception:
                return self._json(400, {'error': 'El contenido no es JSON válido.'})
            datos    = cuerpo.get('datos')
            columnas = cuerpo.get('columnas')
            informe  = cuerpo.get('informe')
            es_informe = isinstance(informe, dict) and isinstance(informe.get('filas'), list) and informe.get('filas')
            if es_informe:
                if len(informe['filas']) > MAX_FILAS_COMPARTIR:
                    informe['filas'] = informe['filas'][:MAX_FILAS_COMPARTIR]
            else:
                if not isinstance(datos, list) or not datos:
                    return self._json(400, {'error': 'Faltan las filas de datos.'})
                if not isinstance(columnas, list) or not columnas:
                    return self._json(400, {'error': 'Falta la configuración de columnas.'})
                if len(datos) > MAX_FILAS_COMPARTIR:
                    datos = datos[:MAX_FILAS_COMPARTIR]
            huella = str(cuerpo.get('huella', ''))[:120]
            campos = {'titulo': str(cuerpo.get('titulo', ''))[:120],
                      'actualizado_en': time.time()}
            total_filas = len(informe['filas']) if es_informe else len(datos)
            if es_informe:
                campos['tipo'] = 'informe'
                campos['informe'] = informe
                campos['columnas'] = []
                campos['datos'] = []
            else:
                campos['tipo'] = 'dashboard'
                campos['columnas'] = columnas
                campos['datos'] = datos

            # Dashboards únicos: si el archivo (huella) ya tiene dashboard,
            # se actualiza ese mismo registro y el enlace no cambia.
            if huella:
                existente = col.find_one({'huella': huella})
                if existente:
                    try:
                        col.update_one({'_id': existente['_id']}, {'$set': campos})
                    except Exception as e:
                        return self._json(500, {'error': f'No se pudo actualizar en MongoDB: {e}'})
                    return self._json(200, {'id': existente['_id'], 'filas': total_filas, 'actualizado': True})

            id_dash = uuid.uuid4().hex[:10]
            doc = dict(campos, _id=id_dash, huella=huella, creado=time.time())
            try:
                col.insert_one(doc)
            except Exception as e:
                return self._json(500, {'error': f'No se pudo guardar en MongoDB: {e}'})
            return self._json(200, {'id': id_dash, 'filas': total_filas})

        if ruta != '/subir':
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
            tablas = [str(t) for t in modelo.tables
                      if not str(t).startswith(('LocalDateTable_', 'DateTableTemplate_'))]
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

            errores = []
            # Relaciones del modelo (para reconstruir el informe con cruces)
            try:
                rel = modelo.relationships
                lista = []
                for _, f in rel.iterrows():
                    d = {str(k).lower(): str(v) for k, v in f.items()}
                    def busca(*claves):
                        for k in d:
                            for c in claves:
                                if c in k:
                                    return d[k]
                        return ''
                    r = {'deTabla': busca('fromtable'), 'deCol': busca('fromcolumn'),
                         'aTabla': busca('totable'),   'aCol': busca('tocolumn')}
                    if r['deTabla'] and r['aTabla']:
                        lista.append(r)
                respuesta['relaciones'] = lista
            except Exception as e:
                errores.append(f'relaciones: {e}')
            # Medidas DAX (nombre, tabla y expresión) para resolverlas en la web
            try:
                md = modelo.dax_measures
                lista = []
                for _, f in md.iterrows():
                    nombre = tabla = expr = ''
                    for k, v in f.items():
                        kl = str(k).lower()
                        if 'expression' in kl: expr = str(v)
                        elif 'table' in kl:    tabla = str(v)
                        elif 'name' in kl:     nombre = str(v)
                    if nombre:
                        lista.append({'tabla': tabla, 'nombre': nombre, 'dax': expr})
                respuesta['medidas_detalle'] = lista
            except Exception as e:
                errores.append(f'medidas: {e}')
            if errores:
                respuesta['errores'] = errores

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
    if not os.environ.get('MONGO_URI', '').strip():
        print('  ⚠ Sin MONGO_URI: los enlaces compartidos estarán desactivados.')
    else:
        print(f"  MongoDB: base '{os.environ.get('MONGO_DB','ryukpowerbi')}' · colección '{os.environ.get('MONGO_COLECCION','dashboard')}'")
    print(f'  Escuchando en http://{HOST}:{PUERTO}')
    print('  Deja esta ventana abierta y sube tu .pbix en la página.')
    print('  (Ctrl+C para detener)')
    try:
        ThreadingHTTPServer((HOST, PUERTO), Manejador).serve_forever()
    except KeyboardInterrupt:
        print('\n  Servidor detenido.')
