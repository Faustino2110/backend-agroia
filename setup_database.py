import sqlite3

print("Conectando a la base de datos...")
conn = sqlite3.connect('agroia.db')

print("Ejecutando schema.sql...")
with open('schema.sql', 'r') as f:
    conn.executescript(f.read())

conn.commit()
conn.close()
print("¡Base de datos creada exitosamente!")

listo ya tengo todo, solo que tengo una observacion, necesito una parte para poder agregar cultivos ya que por si necesito agregar o eliminar un cultivo, solo es eso puedes continuar