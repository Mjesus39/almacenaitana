from flask import Flask, jsonify, render_template, request
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime
import os
import json
import re

# ================== CONFIG ==================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1jFPOu6RGoEyTeFyS79crPx7JxlMl5AeEslCf9_aQ6iI"  # Tu Google Sheet

# ================== CREDENCIALES ==================
def cargar_credenciales():
    google_creds_env = os.getenv("GOOGLE_CREDENTIALS")
    if google_creds_env:
        try:
            creds_dict = json.loads(google_creds_env)
            return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        except json.JSONDecodeError:
            raise Exception("❌ GOOGLE_CREDENTIALS no contiene un JSON válido")
    raise Exception("❌ No se encontró la variable GOOGLE_CREDENTIALS en Render")

creds = cargar_credenciales()
service = build("sheets", "v4", credentials=creds)

# ================== FLASK APP ==================
app = Flask(__name__, template_folder="templates")

# ================== HELPERS ==================
def obtener_ultima_hoja():
    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    sheets = spreadsheet.get("sheets", [])
    fechas = []
    for s in sheets:
        title = s["properties"]["title"]
        if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", title):
            fechas.append(title)
    if not fechas:
        return None
    fechas.sort(reverse=True)
    return fechas[0]

def hoja_existe(nombre_hoja):
    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    sheets = [s["properties"]["title"] for s in spreadsheet.get("sheets", [])]
    return nombre_hoja in sheets

def obtener_locale_y_tokens():
    """
    Detecta el locale del Spreadsheet y devuelve:
    - IF/AND/SUM o SI/Y/SUMA
    - Separador de argumentos: ',' (EN) o ';' (ES)
    """
    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    locale = (spreadsheet.get("properties", {}) or {}).get("locale", "en_US").lower()

    es = locale.startswith("es")
    IF_FN   = "SI"   if es else "IF"
    AND_FN  = "Y"    if es else "AND"
    SUM_FN  = "SUMA" if es else "SUM"
    SEP     = ";"    if es else ","
    return IF_FN, AND_FN, SUM_FN, SEP, locale

# ================== ROUTES ==================
@app.route("/")
def index():
    today = datetime.today().strftime("%Y-%m-%d")
    return render_template("index.html", today=today)

@app.route("/create_today", methods=["POST"])
def create_today():
    hoy = datetime.today().strftime("%Y-%m-%d")
    print("Fecha de hoy:", hoy)

    IF_FN, AND_FN, SUM_FN, SEP, locale = obtener_locale_y_tokens()
    print(f"Locale del Spreadsheet: {locale} -> usando {IF_FN}/{AND_FN} y separador '{SEP}'")

    # 🚀 1. Si ya existe la hoja -> eliminarla
    if hoja_existe(hoy):
        try:
            spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
            for s in spreadsheet["sheets"]:
                if s["properties"]["title"] == hoy:
                    sheet_id = s["properties"]["sheetId"]
                    service.spreadsheets().batchUpdate(
                        spreadsheetId=SPREADSHEET_ID,
                        body={"requests": [{"deleteSheet": {"sheetId": sheet_id}}]}
                    ).execute()
                    print(f"⚠️ Hoja '{hoy}' eliminada para recrear")
                    break
        except Exception as e:
            return jsonify({"error": f"No pude eliminar hoja existente: {str(e)}"}), 500

    # 🚀 2. Buscar última hoja previa
    ultima_hoja = obtener_ultima_hoja()
    if not ultima_hoja:
        return jsonify({"error": "No existe ninguna hoja anterior con datos."}), 400
    print("Última hoja detectada:", ultima_hoja)

    # 🚀 3. Crear nueva hoja
    try:
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": hoy}}}]}
        ).execute()
        print(f"✅ Hoja '{hoy}' creada correctamente")
    except Exception as e:
        return jsonify({"error": f"Error al crear hoja: {str(e)}"}), 500

    # 🚀 4. Copiar encabezados
    encabezados = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{ultima_hoja}!A1:J1"
    ).execute().get("values", [])
    if encabezados:
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{hoy}!A1",
            valueInputOption="USER_ENTERED",
            body={"values": encabezados}
        ).execute()

    # 🚀 5. Copiar filas base
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{ultima_hoja}!A2:J"
    ).execute()
    valores = result.get("values", [])

    nueva_data = []
    for fila in valores:
        producto            = fila[1] if len(fila) > 1 else ""   # B
        valor_unit          = fila[2] if len(fila) > 2 else ""   # C
        utilidad            = fila[3] if len(fila) > 3 else ""   # D
        unidades_restantes  = fila[9] if len(fila) > 9 else 0    # J (ayer) -> E

        nueva_data.append([
            hoy,                    # A
            producto,               # B
            valor_unit,             # C
            utilidad,               # D
            unidades_restantes,     # E
            0,                      # F (unidades vendidas inicia en 0)
            "", "", "", ""          # G,H,I,J
        ])

    if nueva_data:
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{hoy}!A2",
            valueInputOption="USER_ENTERED",
            body={"values": nueva_data}
        ).execute()

    # 🚀 6. Aplicar fórmulas (localizadas por idioma)
    fila_final = len(nueva_data) + 1
    EMPTY = '""'  # literal cadena vacía para la fórmula

    def f_G(idx):
        # G = precio con utilidad => C * (1 + D/100) si C y D no están vacíos
        return f"={IF_FN}({AND_FN}(C{idx}<>\"\"{SEP} D{idx}<>\"\"){SEP} C{idx}*(1+D{idx}/100){SEP} {EMPTY})"

    def f_H(idx):
        # ✅ H = total vendido => F * G si F no está vacío
        return f"={IF_FN}(F{idx}<>\"\"{SEP} F{idx}*G{idx}{SEP} {EMPTY})"

    def f_I(idx):
        # I = ganancia => H - (C*F) si G y F no están vacíos
        return f"={IF_FN}({AND_FN}(G{idx}<>\"\"{SEP} F{idx}<>\"\"){SEP} H{idx}-(C{idx}*F{idx}){SEP} {EMPTY})"

    def f_J(idx):
        # J = inventario restante => E - F si E y F no están vacíos
        return f"={IF_FN}({AND_FN}(E{idx}<>\"\"{SEP} F{idx}<>\"\"){SEP} E{idx}-F{idx}{SEP} {EMPTY})"

    if nueva_data:
        formulas_G = [[f_G(idx)] for idx in range(2, fila_final + 1)]
        formulas_H = [[f_H(idx)] for idx in range(2, fila_final + 1)]
        formulas_I = [[f_I(idx)] for idx in range(2, fila_final + 1)]
        formulas_J = [[f_J(idx)] for idx in range(2, fila_final + 1)]

        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{hoy}!G2:G{fila_final}",
            valueInputOption="USER_ENTERED",
            body={"values": formulas_G}
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{hoy}!H2:H{fila_final}",
            valueInputOption="USER_ENTERED",
            body={"values": formulas_H}
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{hoy}!I2:I{fila_final}",
            valueInputOption="USER_ENTERED",
            body={"values": formulas_I}
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{hoy}!J2:J{fila_final}",
            valueInputOption="USER_ENTERED",
            body={"values": formulas_J}
        ).execute()

    print("Fórmulas aplicadas correctamente (con localización)")
    return jsonify({"message": f"Hoja '{hoy}' creada correctamente"}), 200

# ================== MAIN ==================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
