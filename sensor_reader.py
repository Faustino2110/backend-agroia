# sensor_reader.py - Lector de datos del Arduino
import serial
import requests
import time
import json

# Configuración
PUERTO_SERIAL = 'COM13'  # Cambiar según tu puerto (COM3, COM4, /dev/ttyUSB0 en Linux)
BAUD_RATE = 9600
BACKEND_URL = 'http://localhost:5000/api/sensor/humedad'

# Tiempo entre lecturas (segundos)
INTERVALO_LECTURA = 5

def conectar_arduino():
    """Conectar con Arduino"""
    try:
        ser = serial.Serial(PUERTO_SERIAL, BAUD_RATE, timeout=1)
        time.sleep(2)  # Esperar a que Arduino se inicialice
        print(f"✓ Conectado a Arduino en {PUERTO_SERIAL}")
        return ser
    except Exception as e:
        print(f"✗ Error al conectar con Arduino: {e}")
        return None

def leer_datos(ser):
    """Leer datos del puerto serial"""
    try:
        if ser.in_waiting > 0:
            linea = ser.readline().decode('utf-8').strip()
            return linea
        return None
    except Exception as e:
        print(f"✗ Error al leer datos: {e}")
        return None

def parsear_datos(linea):
    """
    Parsear datos del Arduino
    Formato esperado: "S1:45,S2:62" o "HUM:45"
    """
    sensores = []
    
    try:
        # Formato con múltiples sensores: S1:45,S2:62
        if ',' in linea:
            partes = linea.split(',')
            for parte in partes:
                if ':' in parte:
                    sensor_id, valor = parte.split(':')
                    sensor_num = int(sensor_id.replace('S', ''))
                    humedad = int(valor)
                    sensores.append({'sensor_id': sensor_num, 'humedad': humedad})
        
        # Formato simple: HUM:45 (sensor 1 por defecto)
        elif ':' in linea:
            _, valor = linea.split(':')
            humedad = int(valor)
            sensores.append({'sensor_id': 1, 'humedad': humedad})
        
        # Formato directo: 45
        else:
            humedad = int(linea)
            sensores.append({'sensor_id': 1, 'humedad': humedad})
            
    except Exception as e:
        print(f"✗ Error al parsear datos '{linea}': {e}")
        return []
    
    return sensores

def enviar_al_backend(datos_sensor):
    """Enviar datos al backend Flask"""
    try:
        response = requests.post(BACKEND_URL, json=datos_sensor, timeout=5)
        
        if response.status_code == 200:
            resultado = response.json()
            print(f"✓ Datos enviados - Sensor {datos_sensor['sensor_id']}: {datos_sensor['humedad']}% - {resultado.get('cultivo', 'N/A')}")
            return True
        else:
            print(f"✗ Error del servidor: {response.status_code} - {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("✗ No se pudo conectar con el backend. ¿Está corriendo Flask?")
        return False
    except Exception as e:
        print(f"✗ Error al enviar datos: {e}")
        return False

def main():
    """Función principal"""
    print("=" * 60)
    print("AgroIA - Lector de Sensores Arduino")
    print("=" * 60)
    print(f"Puerto: {PUERTO_SERIAL}")
    print(f"Backend: {BACKEND_URL}")
    print(f"Intervalo: {INTERVALO_LECTURA}s")
    print("=" * 60)
    print("\nPresiona Ctrl+C para detener\n")
    
    # Conectar con Arduino
    arduino = conectar_arduino()
    if not arduino:
        print("\n✗ No se pudo establecer conexión. Verifica:")
        print("  1. Arduino está conectado")
        print("  2. El puerto COM es correcto")
        print("  3. No hay otro programa usando el puerto")
        return
    
    try:
        while True:
            # Leer datos del Arduino
            linea = leer_datos(arduino)
            
            if linea:
                # Parsear datos
                sensores = parsear_datos(linea)
                
                # Enviar cada sensor al backend
                for sensor in sensores:
                    enviar_al_backend(sensor)
                
            # Esperar antes de la siguiente lectura
            time.sleep(INTERVALO_LECTURA)
            
    except KeyboardInterrupt:
        print("\n\n✓ Detenido por el usuario")
    except Exception as e:
        print(f"\n✗ Error inesperado: {e}")
    finally:
        if arduino:
            arduino.close()
            print("✓ Conexión cerrada")

if __name__ == '__main__':
    main()