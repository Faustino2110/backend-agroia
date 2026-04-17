# app.py - Backend Flask para AgroIA
from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# Configuración de la base de datos
DATABASE = os.path.join(app.root_path, 'agroia.db')
ALERTA_COOLDOWN_MINUTES = max(1, int(os.getenv('ALERTA_COOLDOWN_MINUTES', '2')))
REPORT_RECENT_READINGS_LIMIT = max(1, int(os.getenv('REPORT_RECENT_READINGS_LIMIT', '5')))
REPORT_RECENT_ALERTS_LIMIT = max(1, int(os.getenv('REPORT_RECENT_ALERTS_LIMIT', '3')))

@app.route('/', methods=['GET'])
def home():
    """Ruta raiz para verificar que el backend esta activo."""
    return "Servidor funcionando"

def get_db():
    """Conexión a la base de datos"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Inicializar base de datos"""
    with app.app_context():
        db = get_db()
        try:
            with app.open_resource('schema.sql', mode='r') as f:
                db.cursor().executescript(f.read())
            db.commit()
        finally:
            db.close()

def ensure_indexes():
    """Crear indices seguros para acelerar consultas frecuentes."""
    db = get_db()
    try:
        db.executescript("""
            CREATE INDEX IF NOT EXISTS idx_cultivos_sensor_activo
            ON cultivos(sensor_id, activo);

            CREATE INDEX IF NOT EXISTS idx_cultivos_usuario_activo
            ON cultivos(usuario_id, activo);

            CREATE INDEX IF NOT EXISTS idx_lecturas_cultivo_fecha
            ON lecturas(cultivo_id, fecha DESC);

            CREATE INDEX IF NOT EXISTS idx_alertas_cultivo_resuelta_fecha
            ON alertas(cultivo_id, resuelta, fecha DESC);

            CREATE INDEX IF NOT EXISTS idx_alertas_fecha
            ON alertas(fecha DESC);
        """)
        db.commit()
    except sqlite3.Error as e:
        print(f"No se pudieron crear indices SQLite: {e}")
    finally:
        db.close()

def ensure_db_ready():
    """Crear la base de datos si aun no tiene el esquema principal."""
    db = get_db()
    try:
        tablas = db.execute("""
            SELECT COUNT(*) as total
            FROM sqlite_master
            WHERE type = 'table' AND name IN ('usuarios', 'cultivos', 'alertas', 'lecturas')
        """).fetchone()
    finally:
        db.close()

    if int(tablas['total'] or 0) < 4:
        init_db()

# Decorador para verificar autenticación (simplificado)
def requiere_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # En producción usar JWT o sesiones reales
        usuario_id = request.headers.get('X-Usuario-ID')
        if not usuario_id:
            return jsonify({'error': 'No autorizado'}), 401
        return f(*args, **kwargs)
    return decorated_function

# Decorador para verificar rol admin
def requiere_admin(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        usuario_id = request.headers.get('X-Usuario-ID')
        if not usuario_id:
            return jsonify({'error': 'No autorizado'}), 401
        
        db = get_db()
        usuario = db.execute('SELECT rol FROM usuarios WHERE id = ?', (usuario_id,)).fetchone()
        
        if not usuario or usuario['rol'] != 'admin':
            return jsonify({'error': 'Acceso denegado. Se requieren permisos de administrador'}), 403
        
        return f(*args, **kwargs)
    return decorated_function

# ========================================
# RUTAS DE AUTENTICACIÓN
# ========================================

@app.route('/api/login', methods=['POST'])
def login():
    """Login de usuario"""
    data = request.json
    correo = data.get('correo')
    contrasena = data.get('contrasena')
    
    if not correo or not contrasena:
        return jsonify({'error': 'Correo y contraseña requeridos'}), 400
    
    db = get_db()
    usuario = db.execute(
        'SELECT id, nombre, correo, rol FROM usuarios WHERE correo = ? AND contrasena = ? AND activo = 1',
        (correo, contrasena)
    ).fetchone()
    
    if usuario:
        return jsonify({
            'success': True,
            'usuario': {
                'id': usuario['id'],
                'nombre': usuario['nombre'],
                'correo': usuario['correo'],
                'rol': usuario['rol']
            }
        })
    else:
        return jsonify({'error': 'Credenciales inválidas'}), 401

@app.route('/api/register', methods=['POST'])
def register():
    """Registro de nuevo usuario (siempre como cliente)"""
    data = request.json
    nombre = data.get('nombre')
    correo = data.get('correo')
    contrasena = data.get('contrasena')
    
    if not nombre or not correo or not contrasena:
        return jsonify({'error': 'Todos los campos son requeridos'}), 400
    
    db = get_db()
    
    # Verificar si el correo ya existe
    existe = db.execute('SELECT id FROM usuarios WHERE correo = ?', (correo,)).fetchone()
    if existe:
        return jsonify({'error': 'El correo ya está registrado'}), 400
    
    try:
        db.execute(
            'INSERT INTO usuarios (nombre, correo, contrasena, rol) VALUES (?, ?, ?, ?)',
            (nombre, correo, contrasena, 'cliente')
        )
        db.commit()
        return jsonify({'success': True, 'mensaje': 'Usuario registrado exitosamente'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========================================
# RUTAS DE USUARIOS (ADMIN)
# ========================================

@app.route('/api/usuarios', methods=['GET'])
@requiere_admin
def get_usuarios():
    """Obtener todos los usuarios (solo admin)"""
    db = get_db()
    usuarios = db.execute(
        'SELECT id, nombre, correo, rol, fecha_registro, activo FROM usuarios ORDER BY fecha_registro DESC'
    ).fetchall()
    
    return jsonify([dict(u) for u in usuarios])

@app.route('/api/usuarios/<int:usuario_id>', methods=['PUT'])
@requiere_admin
def actualizar_usuario(usuario_id):
    """Actualizar usuario (solo admin)"""
    data = request.json
    db = get_db()
    
    try:
        db.execute(
            'UPDATE usuarios SET nombre = ?, correo = ?, rol = ? WHERE id = ?',
            (data.get('nombre'), data.get('correo'), data.get('rol'), usuario_id)
        )
        db.commit()
        return jsonify({'success': True, 'mensaje': 'Usuario actualizado'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/usuarios/<int:usuario_id>', methods=['DELETE'])
@requiere_admin
def eliminar_usuario(usuario_id):
    """Eliminar usuario (solo admin)"""
    db = get_db()
    
    try:
        db.execute('DELETE FROM usuarios WHERE id = ?', (usuario_id,))
        db.commit()
        return jsonify({'success': True, 'mensaje': 'Usuario eliminado'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========================================
# RUTAS DE CULTIVOS
# ========================================

@app.route('/api/cultivos', methods=['GET'])
@requiere_auth
def get_cultivos():
    """Obtener cultivos (admin ve todos, cliente solo los suyos)"""
    usuario_id = request.headers.get('X-Usuario-ID')
    db = get_db()
    
    # Verificar rol del usuario
    usuario = db.execute('SELECT rol FROM usuarios WHERE id = ?', (usuario_id,)).fetchone()
    
    if usuario['rol'] == 'admin':
        # Admin ve todos los cultivos
        cultivos = db.execute('''
            SELECT c.*, u.nombre as nombre_usuario 
            FROM cultivos c
            LEFT JOIN usuarios u ON c.usuario_id = u.id
            WHERE c.activo = 1
            ORDER BY c.fecha_creacion DESC
        ''').fetchall()
    else:
        # Cliente solo ve sus cultivos
        cultivos = db.execute(
            'SELECT * FROM cultivos WHERE usuario_id = ? AND activo = 1 ORDER BY fecha_creacion DESC',
            (usuario_id,)
        ).fetchall()
    
    return jsonify([dict(c) for c in cultivos])

@app.route('/api/cultivos', methods=['POST'])
@requiere_auth
def crear_cultivo():
    """Crear nuevo cultivo"""
    data = request.json
    usuario_id = request.headers.get('X-Usuario-ID')
    
    db = get_db()
    
    try:
        cursor = db.execute('''
            INSERT INTO cultivos (usuario_id, nombre, tipo_cultivo, etapa, sensor_id, umbral_min, umbral_max, fecha_siembra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            usuario_id,
            data.get('nombre'),
            data.get('tipo_cultivo'),
            data.get('etapa', 'vegetativa'),
            data.get('sensor_id'),
            data.get('umbral_min', 30),
            data.get('umbral_max', 70),
            data.get('fecha_siembra', datetime.now().strftime('%Y-%m-%d'))
        ))
        db.commit()
        
        return jsonify({
            'success': True, 
            'mensaje': 'Cultivo creado exitosamente',
            'cultivo_id': cursor.lastrowid
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cultivos/<int:cultivo_id>', methods=['PUT'])
@requiere_auth
def actualizar_cultivo(cultivo_id):
    """Actualizar cultivo"""
    data = request.json
    usuario_id = request.headers.get('X-Usuario-ID')
    db = get_db()
    
    # Verificar que el cultivo pertenece al usuario (o que sea admin)
    usuario = db.execute('SELECT rol FROM usuarios WHERE id = ?', (usuario_id,)).fetchone()
    
    if usuario['rol'] != 'admin':
        cultivo = db.execute('SELECT usuario_id FROM cultivos WHERE id = ?', (cultivo_id,)).fetchone()
        if not cultivo or cultivo['usuario_id'] != int(usuario_id):
            return jsonify({'error': 'No autorizado'}), 403
    
    try:
        db.execute('''
            UPDATE cultivos 
            SET nombre = ?, tipo_cultivo = ?, etapa = ?, umbral_min = ?, umbral_max = ?
            WHERE id = ?
        ''', (
            data.get('nombre'),
            data.get('tipo_cultivo'),
            data.get('etapa'),
            data.get('umbral_min'),
            data.get('umbral_max'),
            cultivo_id
        ))
        db.commit()
        return jsonify({'success': True, 'mensaje': 'Cultivo actualizado'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cultivos/<int:cultivo_id>', methods=['DELETE'])
@requiere_auth
def eliminar_cultivo(cultivo_id):
    """Eliminar cultivo (soft delete)"""
    usuario_id = request.headers.get('X-Usuario-ID')
    db = get_db()
    
    # Verificar permisos
    usuario = db.execute('SELECT rol FROM usuarios WHERE id = ?', (usuario_id,)).fetchone()
    
    if usuario['rol'] != 'admin':
        cultivo = db.execute('SELECT usuario_id FROM cultivos WHERE id = ?', (cultivo_id,)).fetchone()
        if not cultivo or cultivo['usuario_id'] != int(usuario_id):
            return jsonify({'error': 'No autorizado'}), 403
    
    try:
        db.execute('UPDATE cultivos SET activo = 0 WHERE id = ?', (cultivo_id,))
        db.commit()
        return jsonify({'success': True, 'mensaje': 'Cultivo eliminado'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========================================
# RUTAS DE ALERTAS
# ========================================

@app.route('/api/alertas', methods=['GET'])
@requiere_auth
def get_alertas():
    """Obtener alertas (admin ve todas, cliente solo las suyas)"""
    usuario_id = request.headers.get('X-Usuario-ID')
    db = get_db()
    
    usuario = db.execute('SELECT rol FROM usuarios WHERE id = ?', (usuario_id,)).fetchone()
    
    if usuario['rol'] == 'admin':
        alertas = db.execute('''
            SELECT a.*, c.nombre as nombre_cultivo, u.nombre as nombre_usuario
            FROM alertas a
            LEFT JOIN cultivos c ON a.cultivo_id = c.id
            LEFT JOIN usuarios u ON c.usuario_id = u.id
            ORDER BY a.fecha DESC
            LIMIT 100
        ''').fetchall()
    else:
        alertas = db.execute('''
            SELECT a.*, c.nombre as nombre_cultivo
            FROM alertas a
            LEFT JOIN cultivos c ON a.cultivo_id = c.id
            WHERE c.usuario_id = ?
            ORDER BY a.fecha DESC
            LIMIT 50
        ''', (usuario_id,)).fetchall()
    
    return jsonify([dict(a) for a in alertas])

@app.route('/api/alertas/<int:alerta_id>/marcar-leida', methods=['PUT'])
@requiere_auth
def marcar_alerta_leida(alerta_id):
    """Marcar alerta como leída"""
    db = get_db()
    
    try:
        db.execute('UPDATE alertas SET leida = 1 WHERE id = ?', (alerta_id,))
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========================================
# RUTAS DEL SENSOR (Arduino)
# ========================================

@app.route('/api/sensor/humedad', methods=['POST'])
def recibir_humedad():
    """Recibir datos del sensor Arduino"""
    data = request.json
    humedad = data.get('humedad')
    sensor_id = data.get('sensor_id', 1)
    temperatura = data.get('temperatura', 0)
    
    if humedad is None:
        return jsonify({'error': 'Humedad requerida'}), 400
    
    db = get_db()
    
    # Buscar cultivo asociado al sensor
    cultivo = db.execute(
        'SELECT * FROM cultivos WHERE sensor_id = ? AND activo = 1',
        (sensor_id,)
    ).fetchone()
    
    if not cultivo:
        return jsonify({'error': f'No se encontró cultivo para sensor {sensor_id}'}), 404
    
    try:
        # Actualizar humedad del cultivo
        db.execute(
            'UPDATE cultivos SET humedad = ?, temperatura = ? WHERE id = ?',
            (humedad, temperatura, cultivo['id'])
        )
        
        # Guardar lectura en historial
        db.execute(
            'INSERT INTO lecturas (cultivo_id, humedad, temperatura) VALUES (?, ?, ?)',
            (cultivo['id'], humedad, temperatura)
        )
        
        # Evaluar y crear alertas
        crear_alerta_si_necesario(db, cultivo['id'], humedad, cultivo['umbral_min'], cultivo['umbral_max'])
        
        db.commit()
        
        return jsonify({
            'success': True,
            'mensaje': 'Datos recibidos correctamente',
            'cultivo': cultivo['nombre'],
            'humedad': humedad
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def crear_alerta_si_necesario(db, cultivo_id, humedad, umbral_min, umbral_max):
    """Crear alerta automática según umbrales"""
    
    # Verificar si ya existe una alerta reciente no resuelta
    alerta_reciente = db.execute('''
        SELECT id FROM alertas 
        WHERE cultivo_id = ? AND resuelta = 0 
        AND fecha > datetime('now', ?)
        LIMIT 1
    ''', (cultivo_id, f'-{ALERTA_COOLDOWN_MINUTES} minutes')).fetchone()
    
    if alerta_reciente:
        return  # Ya hay una alerta activa
    
    tipo_alerta = None
    nivel = 'baja'
    mensaje = ''
    
    if humedad < umbral_min:
        diferencia = umbral_min - humedad
        if diferencia > 20:
            tipo_alerta = 'Sequía Crítica'
            nivel = 'critica'
            mensaje = f'Humedad muy baja ({humedad}%). Requiere riego urgente.'
        elif diferencia > 10:
            tipo_alerta = 'Sequía'
            nivel = 'alta'
            mensaje = f'Humedad baja ({humedad}%). Se recomienda riego.'
        else:
            tipo_alerta = 'Humedad Baja'
            nivel = 'media'
            mensaje = f'Humedad bajo el umbral ({humedad}%).'
    
    elif humedad > umbral_max:
        diferencia = humedad - umbral_max
        if diferencia > 20:
            tipo_alerta = 'Riesgo de Hongo Crítico'
            nivel = 'critica'
            mensaje = f'Humedad excesiva ({humedad}%). Alto riesgo de hongos.'
        elif diferencia > 10:
            tipo_alerta = 'Riesgo de Hongo'
            nivel = 'alta'
            mensaje = f'Humedad alta ({humedad}%). Riesgo de hongos.'
        else:
            tipo_alerta = 'Humedad Alta'
            nivel = 'media'
            mensaje = f'Humedad sobre el umbral ({humedad}%).'
    
    if tipo_alerta:
        db.execute('''
            INSERT INTO alertas (cultivo_id, tipo_alerta, nivel, mensaje)
            VALUES (?, ?, ?, ?)
        ''', (cultivo_id, tipo_alerta, nivel, mensaje))

# ========================================
# RUTAS DE ESTADÍSTICAS (Dashboard)
# ========================================

@app.route('/api/estadisticas', methods=['GET'])
@requiere_auth
def get_estadisticas():
    """Obtener estadísticas para el dashboard"""
    usuario_id = request.headers.get('X-Usuario-ID')
    db = get_db()
    
    usuario = db.execute('SELECT rol FROM usuarios WHERE id = ?', (usuario_id,)).fetchone()
    
    if usuario['rol'] == 'admin':
        # Estadísticas globales para admin
        total_usuarios = db.execute('SELECT COUNT(*) as total FROM usuarios WHERE activo = 1').fetchone()['total']
        total_cultivos = db.execute('SELECT COUNT(*) as total FROM cultivos WHERE activo = 1').fetchone()['total']
        alertas_activas = db.execute('SELECT COUNT(*) as total FROM alertas WHERE resuelta = 0').fetchone()['total']
        
        # Alertas por tipo
        alertas_por_tipo = db.execute('''
            SELECT tipo_alerta, COUNT(*) as cantidad
            FROM alertas
            WHERE fecha > datetime('now', '-7 days')
            GROUP BY tipo_alerta
        ''').fetchall()
        
        return jsonify({
            'total_usuarios': total_usuarios,
            'total_cultivos': total_cultivos,
            'alertas_activas': alertas_activas,
            'alertas_por_tipo': [dict(a) for a in alertas_por_tipo]
        })
    else:
        # Estadísticas personales para cliente
        total_cultivos = db.execute(
            'SELECT COUNT(*) as total FROM cultivos WHERE usuario_id = ? AND activo = 1',
            (usuario_id,)
        ).fetchone()['total']
        
        alertas_activas = db.execute('''
            SELECT COUNT(*) as total FROM alertas a
            LEFT JOIN cultivos c ON a.cultivo_id = c.id
            WHERE c.usuario_id = ? AND a.resuelta = 0
        ''', (usuario_id,)).fetchone()['total']
        
        humedad_promedio = db.execute('''
            SELECT AVG(humedad) as promedio FROM cultivos
            WHERE usuario_id = ? AND activo = 1
        ''', (usuario_id,)).fetchone()['promedio'] or 0
        
        return jsonify({
            'total_cultivos': total_cultivos,
            'alertas_activas': alertas_activas,
            'humedad_promedio': round(humedad_promedio, 1)
        })

# ========================================
# RUTAS DE REPORTES
# ========================================

def verificar_acceso_cultivo(db, usuario_id, cultivo_id):
    """Validar acceso al cultivo para admin o propietario."""
    usuario = db.execute('SELECT rol FROM usuarios WHERE id = ?', (usuario_id,)).fetchone()
    if not usuario:
        return None, ('No autorizado', 401)

    cultivo = db.execute('''
        SELECT c.*, u.nombre as nombre_usuario
        FROM cultivos c
        LEFT JOIN usuarios u ON c.usuario_id = u.id
        WHERE c.id = ? AND c.activo = 1
    ''', (cultivo_id,)).fetchone()

    if not cultivo:
        return None, ('Cultivo no encontrado', 404)

    if usuario['rol'] != 'admin' and cultivo['usuario_id'] != int(usuario_id):
        return None, ('No autorizado', 403)

    return cultivo, None

def obtener_estado_humedad(humedad, umbral_min, umbral_max):
    """ClasificaciÃ³n simple del estado de humedad."""
    if humedad < umbral_min:
        return 'baja'
    if humedad > umbral_max:
        return 'alta'
    return 'estable'

def generar_observaciones_reporte(cultivo, promedio_humedad, total_alertas):
    """Crear observaciones cortas para el reporte."""
    humedad_actual = float(cultivo['humedad'] or 0)
    umbral_min = float(cultivo['umbral_min'] or 0)
    umbral_max = float(cultivo['umbral_max'] or 0)
    estado = obtener_estado_humedad(humedad_actual, umbral_min, umbral_max)

    observaciones = []

    if estado == 'baja':
        observaciones.append('La humedad actual estÃ¡ por debajo del rango recomendado. Conviene revisar el riego.')
    elif estado == 'alta':
        observaciones.append('La humedad actual estÃ¡ por encima del rango recomendado. Conviene reducir exceso de agua.')
    else:
        observaciones.append('La humedad actual se mantiene dentro del rango esperado para el cultivo.')

    if promedio_humedad is not None:
        if promedio_humedad < umbral_min:
            observaciones.append('El promedio reciente tambiÃ©n se mantiene bajo, lo que sugiere ajustar la frecuencia de riego.')
        elif promedio_humedad > umbral_max:
            observaciones.append('El promedio reciente es alto, por lo que vale la pena vigilar drenaje y ventilaciÃ³n.')

    if total_alertas > 0:
        observaciones.append(f'Se registraron {total_alertas} alertas recientes. Es recomendable revisar su causa principal.')
    else:
        observaciones.append('No hay alertas recientes registradas para este cultivo.')

    return observaciones[:3]

def generar_recomendaciones_locales_reporte(cultivo, promedio_humedad, total_alertas):
    """Generar recomendaciones de respaldo cuando la IA no este disponible."""
    humedad_actual = float(cultivo['humedad'] or 0)
    umbral_min = float(cultivo['umbral_min'] or 0)
    umbral_max = float(cultivo['umbral_max'] or 0)
    recomendaciones = []

    if humedad_actual < umbral_min:
        recomendaciones.append({
            'titulo': 'Ajustar riego',
            'descripcion': 'La humedad actual esta por debajo del umbral. Conviene aumentar la frecuencia de riego y revisar el caudal.',
            'prioridad': 'alta',
            'categoria': 'riego'
        })
    elif humedad_actual > umbral_max:
        recomendaciones.append({
            'titulo': 'Reducir exceso de humedad',
            'descripcion': 'La humedad supera el rango recomendado. Revisa drenaje, ventilacion y volumen de riego aplicado.',
            'prioridad': 'alta',
            'categoria': 'sanidad'
        })
    else:
        recomendaciones.append({
            'titulo': 'Mantener manejo actual',
            'descripcion': 'La humedad se mantiene estable. Continua con el manejo actual y monitorea cambios bruscos.',
            'prioridad': 'media',
            'categoria': 'monitoreo'
        })

    if promedio_humedad is not None and promedio_humedad < umbral_min:
        recomendaciones.append({
            'titulo': 'Revisar frecuencia de riego',
            'descripcion': 'El promedio reciente de humedad tambien se mantiene bajo, lo que sugiere ajustar tiempos o frecuencia de riego.',
            'prioridad': 'media',
            'categoria': 'riego'
        })
    elif promedio_humedad is not None and promedio_humedad > umbral_max:
        recomendaciones.append({
            'titulo': 'Evaluar drenaje del suelo',
            'descripcion': 'El promedio reciente es alto. Conviene revisar drenaje, compactacion y ventilacion para evitar enfermedades.',
            'prioridad': 'media',
            'categoria': 'suelo'
        })

    if total_alertas > 0:
        recomendaciones.append({
            'titulo': 'Atender alertas recurrentes',
            'descripcion': 'Se han registrado alertas en este cultivo. Identifica si provienen de riego irregular, drenaje o condiciones ambientales.',
            'prioridad': 'alta' if total_alertas >= 3 else 'media',
            'categoria': 'alertas'
        })

    return recomendaciones[:4]

def construir_analisis_local_reporte(cultivo, metricas, alertas_recientes):
    """Analisis local para que el reporte no dependa totalmente de OpenAI."""
    humedad_actual = float(cultivo['humedad'] or 0)
    temperatura_actual = float(cultivo['temperatura'] or 0)
    promedio_humedad = metricas.get('humedad_promedio')
    estado_humedad = obtener_estado_humedad(
        humedad_actual,
        float(cultivo['umbral_min'] or 0),
        float(cultivo['umbral_max'] or 0)
    )

    if estado_humedad == 'baja':
        resumen = 'El cultivo presenta un nivel de humedad por debajo del rango esperado y requiere seguimiento cercano.'
    elif estado_humedad == 'alta':
        resumen = 'El cultivo presenta exceso de humedad y existe riesgo de problemas sanitarios si la condicion persiste.'
    else:
        resumen = 'El cultivo mantiene un comportamiento estable de humedad dentro del rango esperado.'

    hallazgos = [
        f"Humedad actual: {humedad_actual}%",
        f"Temperatura actual: {temperatura_actual} C",
        f"Total de lecturas registradas: {int(metricas.get('total_lecturas') or 0)}"
    ]

    if promedio_humedad is not None:
        hallazgos.append(f"Humedad promedio historica: {promedio_humedad}%")

    riesgos = [a['mensaje'] for a in alertas_recientes[:3]] if alertas_recientes else ['Sin alertas recientes registradas.']

    return {
        'resumen_ejecutivo': resumen,
        'hallazgos_clave': hallazgos[:4],
        'riesgos_principales': riesgos[:3]
    }

def limpiar_json_respuesta(texto_respuesta):
    """Intentar convertir respuestas de IA a JSON util."""
    if not texto_respuesta:
        raise ValueError('Respuesta vacia de IA')

    texto_limpio = texto_respuesta.strip()
    texto_limpio = texto_limpio.replace('```json', '').replace('```', '').strip()
    return json.loads(texto_limpio)

def generar_analisis_ia_reporte(reporte):
    """Complementar el reporte con analisis y recomendaciones generadas por IA."""
    cultivo = reporte['cultivo']
    resumen = reporte['resumen']
    metricas = reporte['metricas']
    lecturas = reporte['lecturas_recientes']
    alertas = reporte['alertas_recientes']

    analisis_local = construir_analisis_local_reporte(cultivo, metricas, alertas)
    recomendaciones_locales = generar_recomendaciones_locales_reporte(
        {
            'humedad': resumen['humedad_actual'],
            'temperatura': resumen['temperatura_actual'],
            'umbral_min': cultivo.get('umbral_min', 0),
            'umbral_max': cultivo.get('umbral_max', 0)
        },
        metricas.get('humedad_promedio'),
        metricas.get('total_alertas', 0)
    )

    if not openai_client:
        return {
            'fuente': 'local',
            'analisis': analisis_local,
            'recomendaciones': recomendaciones_locales
        }

    lecturas_texto = "\n".join(
        [f"- {l['fecha']}: humedad {l['humedad']}%, temperatura {l['temperatura']} C" for l in lecturas]
    ) or "- Sin lecturas recientes"
    alertas_texto = "\n".join(
        [f"- {a['fecha']}: {a['tipo_alerta']} ({a['nivel']}) - {a['mensaje']}" for a in alertas]
    ) or "- Sin alertas recientes"

    prompt = f"""Eres un agronomo experto y analista tecnico.

Genera un complemento para un reporte agricola en formato JSON valido.

DATOS DEL CULTIVO:
- Nombre: {cultivo['nombre']}
- Tipo: {cultivo['tipo_cultivo']}
- Etapa: {cultivo['etapa']}
- Fecha de siembra: {cultivo['fecha_siembra']}
- Humedad actual: {resumen['humedad_actual']}%
- Temperatura actual: {resumen['temperatura_actual']} C
- Rango recomendado de humedad: {resumen['rango_humedad_recomendado']}
- Estado de humedad: {resumen['estado_humedad']}
- Total de lecturas: {metricas['total_lecturas']}
- Humedad promedio: {metricas['humedad_promedio']}
- Humedad minima: {metricas['humedad_minima']}
- Humedad maxima: {metricas['humedad_maxima']}
- Temperatura promedio: {metricas['temperatura_promedio']}
- Total de alertas: {metricas['total_alertas']}

LECTURAS RECIENTES:
{lecturas_texto}

ALERTAS RECIENTES:
{alertas_texto}

Devuelve SOLO un JSON con esta estructura exacta:
{{
  "analisis": {{
    "resumen_ejecutivo": "texto breve",
    "hallazgos_clave": ["hallazgo 1", "hallazgo 2", "hallazgo 3"],
    "riesgos_principales": ["riesgo 1", "riesgo 2"]
  }},
  "recomendaciones": [
    {{
      "titulo": "titulo corto",
      "descripcion": "accion concreta y util",
      "prioridad": "alta",
      "categoria": "riego"
    }}
  ]
}}

Reglas:
- Responde en espanol.
- Maximo 3 hallazgos clave.
- Maximo 4 recomendaciones.
- Las recomendaciones deben ser concretas, accionables y coherentes con los datos.
"""

    try:
        texto_respuesta = generar_respuesta_openai(modelo=OPENAI_TEXT_MODEL, prompt=prompt)
        resultado = limpiar_json_respuesta(texto_respuesta)
        analisis = resultado.get('analisis') or analisis_local
        recomendaciones = resultado.get('recomendaciones') or recomendaciones_locales

        return {
            'fuente': 'openai',
            'analisis': analisis,
            'recomendaciones': recomendaciones[:4]
        }
    except Exception as e:
        print(f"Error al enriquecer reporte con IA: {e}")
        return {
            'fuente': 'local',
            'analisis': analisis_local,
            'recomendaciones': recomendaciones_locales
        }

def construir_reporte_cultivo(db, cultivo):
    """Construir un reporte breve y legible para el frontend."""
    cultivo_id = cultivo['id']

    lecturas = db.execute('''
        SELECT humedad, temperatura, fecha
        FROM lecturas
        WHERE cultivo_id = ?
        ORDER BY fecha DESC
        LIMIT ?
    ''', (cultivo_id, REPORT_RECENT_READINGS_LIMIT)).fetchall()

    metricas = db.execute('''
        SELECT
            AVG(humedad) as promedio_humedad,
            MIN(humedad) as minima_humedad,
            MAX(humedad) as maxima_humedad,
            AVG(temperatura) as promedio_temperatura,
            COUNT(*) as total_lecturas
        FROM lecturas
        WHERE cultivo_id = ?
    ''', (cultivo_id,)).fetchone()

    alertas = db.execute('''
        SELECT tipo_alerta, nivel, mensaje, fecha
        FROM alertas
        WHERE cultivo_id = ?
        ORDER BY fecha DESC
        LIMIT ?
    ''', (cultivo_id, REPORT_RECENT_ALERTS_LIMIT)).fetchall()

    total_alertas = db.execute(
        'SELECT COUNT(*) as total FROM alertas WHERE cultivo_id = ?',
        (cultivo_id,)
    ).fetchone()['total']

    promedio_humedad = metricas['promedio_humedad']
    promedio_temperatura = metricas['promedio_temperatura']

    reporte = {
        'cultivo': {
            'id': cultivo['id'],
            'nombre': cultivo['nombre'],
            'tipo_cultivo': cultivo['tipo_cultivo'],
            'etapa': cultivo['etapa'],
            'propietario': cultivo['nombre_usuario'],
            'fecha_siembra': cultivo['fecha_siembra'],
            'umbral_min': float(cultivo['umbral_min'] or 0),
            'umbral_max': float(cultivo['umbral_max'] or 0)
        },
        'resumen': {
            'fecha_generacion': datetime.now().isoformat(),
            'humedad_actual': float(cultivo['humedad'] or 0),
            'temperatura_actual': float(cultivo['temperatura'] or 0),
            'rango_humedad_recomendado': f"{float(cultivo['umbral_min'] or 0)}% - {float(cultivo['umbral_max'] or 0)}%",
            'estado_humedad': obtener_estado_humedad(
                float(cultivo['humedad'] or 0),
                float(cultivo['umbral_min'] or 0),
                float(cultivo['umbral_max'] or 0)
            )
        },
        'metricas': {
            'total_lecturas': int(metricas['total_lecturas'] or 0),
            'humedad_promedio': round(promedio_humedad, 1) if promedio_humedad is not None else None,
            'humedad_minima': round(metricas['minima_humedad'], 1) if metricas['minima_humedad'] is not None else None,
            'humedad_maxima': round(metricas['maxima_humedad'], 1) if metricas['maxima_humedad'] is not None else None,
            'temperatura_promedio': round(promedio_temperatura, 1) if promedio_temperatura is not None else None,
            'total_alertas': int(total_alertas or 0)
        },
        'lecturas_recientes': [dict(l) for l in lecturas],
        'alertas_recientes': [dict(a) for a in alertas],
        'observaciones': generar_observaciones_reporte(
            cultivo,
            promedio_humedad,
            total_alertas
        )
    }

    complemento_ia = generar_analisis_ia_reporte(reporte)
    reporte['analisis_complementario'] = complemento_ia['analisis']
    reporte['recomendaciones'] = complemento_ia['recomendaciones']
    reporte['fuente_analisis'] = complemento_ia['fuente']

    return reporte

@app.route('/api/reportes/<int:cultivo_id>', methods=['GET'])
@app.route('/api/cultivos/<int:cultivo_id>/reporte', methods=['GET'])
@requiere_auth
def generar_reporte_cultivo(cultivo_id):
    """Generar reporte simple de un cultivo."""
    usuario_id = request.headers.get('X-Usuario-ID')
    db = get_db()
    try:
        cultivo, error = verificar_acceso_cultivo(db, usuario_id, cultivo_id)
        if error:
            mensaje, codigo = error
            return jsonify({'error': mensaje}), codigo

        reporte = construir_reporte_cultivo(db, cultivo)
        return jsonify({
            'success': True,
            'reporte': reporte
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

# ========================================
# RUTA DE SALUD DEL SERVIDOR
# ========================================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Verificar estado del servidor"""
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat()})

@app.route('/api/ia/status', methods=['GET'])
def ia_status():
    """Estado basico de la configuracion IA sin exponer secretos."""
    api_key_present = bool(OPENAI_API_KEY)
    api_key_preview = None

    if api_key_present:
        api_key_preview = f"{OPENAI_API_KEY[:7]}...{OPENAI_API_KEY[-4:]}"

    return jsonify({
        'success': True,
        'openai_configurada': api_key_present,
        'openai_sdk_instalado': bool(OpenAI),
        'openai_modelo_texto': OPENAI_TEXT_MODEL,
        'openai_modelo_vision': OPENAI_VISION_MODEL,
        'openai_api_key_preview': api_key_preview
    })

    
import base64
import json
import re
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip() or None
OPENAI_TEXT_MODEL = os.getenv("OPENAI_TEXT_MODEL", "gpt-4.1-mini")
OPENAI_VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini")

openai_client = OpenAI(api_key=OPENAI_API_KEY) if OpenAI and OPENAI_API_KEY else None

def generar_respuesta_openai(modelo, prompt):
    """Genera texto con OpenAI usando la Responses API."""
    if not OpenAI:
        raise RuntimeError(
            "No está instalado el SDK 'openai'. Instálalo con: pip install openai"
        )

    if not OPENAI_API_KEY:
        raise RuntimeError(
            "Falta la API key de OpenAI. Configura la variable de entorno OPENAI_API_KEY."
        )

    if not openai_client:
        raise RuntimeError("No se pudo inicializar el cliente de OpenAI.")

    response = openai_client.responses.create(
        model=modelo,
        input=prompt
    )

    texto = getattr(response, 'output_text', None)
    if texto:
        return texto.strip()

    raise ValueError("OpenAI no devolvió texto en la respuesta")

def generar_respuesta_openai_imagen(modelo, prompt, imagen_bytes, mime_type):
    """Analiza una imagen con OpenAI usando texto e imagen en la misma solicitud."""
    if not OpenAI:
        raise RuntimeError(
            "No está instalado el SDK 'openai'. Instálalo con: pip install openai"
        )

    if not OPENAI_API_KEY:
        raise RuntimeError(
            "Falta la API key de OpenAI. Configura la variable de entorno OPENAI_API_KEY."
        )

    if not openai_client:
        raise RuntimeError("No se pudo inicializar el cliente de OpenAI.")

    imagen_base64 = base64.b64encode(imagen_bytes).decode('utf-8')
    image_url = f"data:{mime_type};base64,{imagen_base64}"

    response = openai_client.responses.create(
        model=modelo,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": image_url},
                ],
            }
        ],
    )

    texto = getattr(response, 'output_text', None)
    if texto:
        return texto.strip()

    raise ValueError("OpenAI no devolvió texto en la respuesta")

def construir_error_openai(error, operacion):
    """Convierte errores de OpenAI en respuestas HTTP útiles para el frontend."""
    mensaje = str(error)
    retry_match = re.search(r"(?:Please retry in|Try again in) ([\d.]+)s", mensaje)
    retry_after = int(float(retry_match.group(1))) + 1 if retry_match else None

    if "429" in mensaje or "rate limit" in mensaje.lower() or "quota" in mensaje.lower():
        payload = {
            'error': f'OpenAI sin cuota disponible para {operacion}',
            'detalle': 'Se excedió la cuota o el límite de peticiones de la API.',
            'tipo': 'quota_exceeded'
        }
        if retry_after is not None:
            payload['retry_after'] = retry_after
        return jsonify(payload), 429

    if "401" in mensaje or "403" in mensaje:
        return jsonify({
            'error': f'No se pudo autenticar OpenAI para {operacion}',
            'detalle': 'Revisa la API key y los permisos de tu cuenta.',
            'tipo': 'auth_error'
        }), 502

    return jsonify({
        'error': f'Error al usar OpenAI para {operacion}',
        'detalle': mensaje,
        'tipo': 'openai_error'
    }), 500

def generar_respuesta_gemini(modelo, contenido):
    """Genera contenido con Gemini usando el SDK actual."""
    if not genai:
        raise RuntimeError(
            "No está instalado el SDK 'google-genai'. Instálalo con: pip install google-genai"
        )

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "Falta la API key de Gemini. Configura la variable de entorno GEMINI_API_KEY o GOOGLE_API_KEY."
        )

    if not gemini_client:
        raise RuntimeError("No se pudo inicializar el cliente de Gemini.")

    response = gemini_client.models.generate_content(
        model=modelo,
        contents=contenido
    )

    texto = getattr(response, 'text', None)
    if texto:
        return texto.strip()

    raise ValueError("Gemini no devolvió texto en la respuesta")

def construir_error_gemini(error, operacion):
    """Convierte errores de Gemini en respuestas HTTP útiles para el frontend."""
    mensaje = str(error)
    retry_match = re.search(r"Please retry in ([\d.]+)s", mensaje)
    retry_after = int(float(retry_match.group(1))) + 1 if retry_match else None

    if "429" in mensaje or "RESOURCE_EXHAUSTED" in mensaje or "quota" in mensaje.lower():
        payload = {
            'error': f'Gemini sin cuota disponible para {operacion}',
            'detalle': 'Se excedió la cuota o el límite de peticiones de la API.',
            'tipo': 'quota_exceeded'
        }
        if retry_after is not None:
            payload['retry_after'] = retry_after
        return jsonify(payload), 429

    if "401" in mensaje or "403" in mensaje:
        return jsonify({
            'error': f'No se pudo autenticar Gemini para {operacion}',
            'detalle': 'Revisa la API key y los permisos del proyecto.',
            'tipo': 'auth_error'
        }), 502

    return jsonify({
        'error': f'Error al usar Gemini para {operacion}',
        'detalle': mensaje,
        'tipo': 'gemini_error'
    }), 500

@app.route('/api/ia/analizar-imagen', methods=['POST'])
def analizar_imagen_ia():
    try:
        if 'imagen' not in request.files:
            return jsonify({'error': 'No se envió ninguna imagen'}), 400
        
        imagen_file = request.files['imagen']
        cultivo_nombre = request.form.get('cultivo_nombre', 'Cultivo')
        
        imagen_bytes = imagen_file.read()
        mime_type = imagen_file.mimetype or 'image/jpeg'
        
        prompt = f"""Eres un agrónomo experto analizando una imagen de un cultivo ({cultivo_nombre}).

Analiza la imagen y proporciona:

1. Estado General: Describe el estado visual de la planta
2. Plagas Detectadas: Identifica si hay signos de plagas
3. Enfermedades: Detecta enfermedades fúngicas, bacterianas o virales
4. Deficiencias Nutricionales: Identifica deficiencias de nutrientes
5. Recomendaciones: Da 3-5 acciones concretas

Responde SOLO con este JSON exacto:
{{
    "estado_general": "descripción del estado",
    "salud_score": 85,
    "plagas": ["lista de plagas o Ninguna"],
    "enfermedades": ["lista de enfermedades o Ninguna"],
    "deficiencias": ["deficiencias nutricionales o Ninguna"],
    "recomendaciones": [
        "Recomendación 1",
        "Recomendación 2",
        "Recomendación 3"
    ],
    "urgencia": "baja"
}}"""
        
        texto_respuesta = generar_respuesta_openai_imagen(
            modelo=OPENAI_VISION_MODEL,
            prompt=prompt,
            imagen_bytes=imagen_bytes,
            mime_type=mime_type
        )

        try:
            texto_limpio = texto_respuesta.replace('```json', '').replace('```', '').strip()
            resultado = json.loads(texto_limpio)
        except:
            resultado = {
                'estado_general': 'Análisis completado',
                'salud_score': 70,
                'plagas': ['No se pudo determinar'],
                'enfermedades': ['No se pudo determinar'],
                'deficiencias': ['No se pudo determinar'],
                'recomendaciones': [texto_respuesta],
                'urgencia': 'media'
            }
        
        return jsonify({
            'success': True,
            'analisis': resultado,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        print(f"Error en análisis IA: {e}")
        return construir_error_openai(e, 'analizar imagen')


@app.route('/api/ia/chat', methods=['POST'])
def chat_ia():
    try:
        data = request.json
        pregunta = data.get('pregunta')
        cultivo_id = data.get('cultivo_id')
        
        if not pregunta:
            return jsonify({'error': 'No se envió ninguna pregunta'}), 400
        
        contexto = ""
        if cultivo_id:
            db = get_db()
            cultivo = db.execute(
                'SELECT * FROM cultivos WHERE id = ?', 
                (cultivo_id,)
            ).fetchone()
            
            if cultivo:
                contexto = f"""
                CONTEXTO DEL CULTIVO:
                - Nombre: {cultivo['nombre']}
                - Tipo: {cultivo['tipo_cultivo']}
                - Etapa: {cultivo['etapa']}
                - Humedad actual: {cultivo['humedad']}%
                - Umbral mínimo: {cultivo['umbral_min']}%
                - Umbral máximo: {cultivo['umbral_max']}%
                """
        
        prompt = f"""Eres un agrónomo experto especializado en cultivos. 
        
{contexto}

PREGUNTA DEL USUARIO: {pregunta}

INSTRUCCIONES:
- Responde de manera clara y práctica
- Basate en el contexto del cultivo si está disponible
- Da consejos específicos y aplicables
- Máximo 200 palabras
- Responde en español"""
        
        respuesta_ia = generar_respuesta_openai(modelo=OPENAI_TEXT_MODEL, prompt=prompt)
        
        return jsonify({
            'success': True,
            'respuesta': respuesta_ia,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        print(f"Error en chat IA: {e}")
        return construir_error_openai(e, 'chat')


@app.route('/api/ia/recomendaciones/<int:cultivo_id>', methods=['GET'])
def recomendaciones_ia(cultivo_id):
    try:
        db = get_db()
        
        cultivo = db.execute(
            'SELECT * FROM cultivos WHERE id = ?', 
            (cultivo_id,)
        ).fetchone()
        
        if not cultivo:
            return jsonify({'error': 'Cultivo no encontrado'}), 404
        
        alertas = db.execute(
            'SELECT * FROM alertas WHERE cultivo_id = ? ORDER BY fecha DESC LIMIT 5',
            (cultivo_id,)
        ).fetchall()
        
        alertas_texto = "\n".join([f"- {a['tipo_alerta']} ({a['nivel']})" for a in alertas])
        
        prompt = f"""Analiza este cultivo y genera recomendaciones personalizadas:

DATOS DEL CULTIVO:
- Nombre: {cultivo['nombre']}
- Tipo: {cultivo['tipo_cultivo']}
- Etapa: {cultivo['etapa']}
- Humedad actual: {cultivo['humedad']}%
- Rango óptimo: {cultivo['umbral_min']}% - {cultivo['umbral_max']}%

ALERTAS RECIENTES:
{alertas_texto if alertas_texto else "Sin alertas"}

Genera 3-5 recomendaciones específicas en formato JSON:
{{
    "recomendaciones": [
        {{
            "titulo": "Título corto",
            "descripcion": "Descripción detallada",
            "prioridad": "alta",
            "categoria": "riego"
        }}
    ]
}}"""
        
        texto_respuesta = generar_respuesta_openai(modelo=OPENAI_TEXT_MODEL, prompt=prompt)

        try:
            texto_limpio = texto_respuesta.replace('```json', '').replace('```', '').strip()
            resultado = json.loads(texto_limpio)
        except:
            resultado = {
                'recomendaciones': [
                    {
                        'titulo': 'Recomendación generada',
                        'descripcion': texto_respuesta,
                        'prioridad': 'media',
                        'categoria': 'general'
                    }
                ]
            }
        
        return jsonify({
            'success': True,
            'recomendaciones': resultado['recomendaciones'],
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        print(f"Error en recomendaciones IA: {e}")
        return construir_error_openai(e, 'generar recomendaciones')

ensure_db_ready()
ensure_indexes()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
