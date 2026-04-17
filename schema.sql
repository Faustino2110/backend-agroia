-- Base de datos AgroIA
-- SQLite Schema

-- Tabla de usuarios con roles
CREATE TABLE usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre VARCHAR(100) NOT NULL,
    correo VARCHAR(100) UNIQUE NOT NULL,
    contrasena VARCHAR(255) NOT NULL,
    rol VARCHAR(20) NOT NULL DEFAULT 'cliente', -- 'admin' o 'cliente'
    fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
    activo BOOLEAN DEFAULT 1
);

-- Tabla de cultivos
CREATE TABLE cultivos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL,
    nombre VARCHAR(100) NOT NULL,
    tipo_cultivo VARCHAR(50) NOT NULL, -- tomate, lechuga, etc
    etapa VARCHAR(50) DEFAULT 'vegetativa', -- germinación, vegetativa, floración, cosecha
    humedad DECIMAL(5,2) DEFAULT 0,
    temperatura DECIMAL(5,2) DEFAULT 0,
    sensor_id INTEGER, -- ID del sensor Arduino (1, 2, etc)
    umbral_min DECIMAL(5,2) DEFAULT 30, -- Humedad mínima
    umbral_max DECIMAL(5,2) DEFAULT 70, -- Humedad máxima
    fecha_siembra DATE,
    fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
    activo BOOLEAN DEFAULT 1,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
);

-- Tabla de alertas
CREATE TABLE alertas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cultivo_id INTEGER NOT NULL,
    tipo_alerta VARCHAR(50) NOT NULL, -- 'Sequía', 'Riesgo de hongo', 'Normal', 'Crítico'
    nivel VARCHAR(20) NOT NULL, -- 'baja', 'media', 'alta', 'critica'
    mensaje TEXT,
    fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
    leida BOOLEAN DEFAULT 0,
    resuelta BOOLEAN DEFAULT 0,
    FOREIGN KEY (cultivo_id) REFERENCES cultivos(id) ON DELETE CASCADE
);

-- Tabla de lecturas del sensor (historial)
CREATE TABLE lecturas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cultivo_id INTEGER NOT NULL,
    humedad DECIMAL(5,2) NOT NULL,
    temperatura DECIMAL(5,2),
    fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cultivo_id) REFERENCES cultivos(id) ON DELETE CASCADE
);

-- Tabla de configuración del sistema
CREATE TABLE configuracion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clave VARCHAR(50) UNIQUE NOT NULL,
    valor TEXT,
    descripcion TEXT
);

-- Insertar usuario administrador por defecto
INSERT INTO usuarios (nombre, correo, contrasena, rol) 
VALUES ('Administrador', 'admin@agroia.com', 'admin123', 'admin');

-- Insertar usuario cliente de prueba
INSERT INTO usuarios (nombre, correo, contrasena, rol) 
VALUES ('Usuario Demo', 'usuario@agroia.com', 'usuario123', 'cliente');

-- Insertar configuración por defecto
INSERT INTO configuracion (clave, valor, descripcion)
VALUES 
('alertas_email', '1', 'Enviar alertas por email'),
('lecturas_intervalo', '5', 'Intervalo de lecturas en minutos'),
('modo_demo', '1', 'Modo demostración activo');