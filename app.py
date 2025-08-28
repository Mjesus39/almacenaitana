from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime
import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

app = Flask(__name__)

# ========= CONFIGURACIÓN GOOGLE SHEETS =========
SPREADSHEET_ID = "1jFPOu6RGoEyTeFyS79crPx7JxlMl5AeEslCf9_aQ6iI"  # ✅ Tu ID real

# Cargar credenciales desde variable de entorno GOOGLE_CREDENTIALS
creds_json = os.environ.get("GOOGLE_CREDENTIALS")
if not creds_json:
    raise Exception("❌ No se encontró la variable de entorno GOOGLE_CREDENTIALS")

creds_dict = json.loads(creds_json)
creds = service_account.Credentials.from_service_account_info(
    creds_dict,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)

service = build("sheets", "v4", credentials=creds)

# ========= FUNCIÓN PARA CREAR HOJA NUEVA =========
def crear_hoja_nueva():
    try:
        # Nombre de la hoja de hoy (YYYY-MM-DD)
        hoy = datetime.today().strftime("%Y-%m-%d")
        
        # 1. Obtener la última hoja (ayer)
        sheet_metadata = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        hojas = sheet_metadata.get("sheets", [])
        ultima_hoja = hojas[-1]["properties"]["title"]  # última hoja
        print(f"Última hoja encontrada: {ultima_hoja}")

        # 2. Leer datos de la última hoja
        rango = f"{ultima_hoja}!A:J"
        resultado = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=rango
        ).execute()
        valores = resultado.get("values", [])

        if not valores:
            print("La hoja anterior está vacía.")
            return "La hoja anterior está vacía."

        # 3. Crear la nueva hoja
        requests = [
            {
                "addSheet": {
                    "properties": {
                        "title": hoy
                    }
                }
            }
        ]
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": requests}
        ).execute()

        # 4. Construir datos para la nueva hoja
        nuevas_filas = []
        for i, fila in enumerate(valores):
            if i == 0:
                # Encabezados
                nuevas_filas.append(fila)
            else:
                fecha = hoy
                producto = fila[1] if len(fila) > 1 else ""
                interno = fila[2] if len(fila) > 2 else ""
                utilidad = fila[3] if len(fila) > 3 else ""
                iniciales = fila[9] if len(fila) > 9 else "0"
                vendidas = "0"
                nuevas_filas.append([
                    fecha, 
                    producto, 
                    interno, 
                    utilidad, 
                    iniciales, 
                    vendidas,
                    f"=C{i+1}*(1+D{i+1}/100)",   # G (precio con utilidad)
                    f"=F{i+1}*G{i+1}",           # H (total vendido)
                    f"=(E{i+1}-F{i+1})*G{i+1}",  # I (valor inventario)
                    f"=E{i+1}-F{i+1}"            # J (stock final)
                ])

        # 5. Escribir en la hoja nueva
        rango_nueva = f"{hoy}!A1"
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=rango_nueva,
            valueInputOption="USER_ENTERED",
            body={"values": nuevas_filas}
        ).execute()

        return f"✅ Hoja {hoy} creada con éxito."

    except HttpError as err:
        return f"❌ Error de Google Sheets: {err}"
    except Exception as e:
        return f"❌ Error inesperado: {e}"

# ========= RUTAS DE FLASK =========
@app.route("/")
def index():
    mensaje = request.args.get("mensaje", "")
    return render_template("index.html", mensaje=mensaje)

@app.route("/crear-hoja", methods=["POST"])
def crear_hoja():
    mensaje = crear_hoja_nueva()
    return redirect(url_for("index", mensaje=mensaje))

# ========= MAIN =========
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
