import uuid
import re
import requests
import streamlit as st
import pandas as pd
import datetime as dt
from zoneinfo import ZoneInfo
import gspread
from google.oauth2.service_account import Credentials

# =========================================================
# CONFIG
# =========================================================
STGO = ZoneInfo("America/Santiago")

SPREADSHEET_KEY = "1-McBRqr5mdiw3Wd0Cw9lOebvp1C7AOj1JmTz4wpyPoA"
HOJA = "finanzas"

USER_A = "🐳Javiera"
USER_B = "🪈Francis"
USUARIOS = [USER_A, USER_B]

MEDIOS = ["Efectivo", "Tarjeta de crédito", "Débito", "Transferencia", "Cuenta de ahorro", "Otro"]

EXPECTED_HEADERS = [
    "ID","Tipo","Detalle","Categoría","Fecha","Persona",
    "Persona_Origen","Persona_Destino","Monto",
    "Monto_original","Moneda",
    "Medio","Compartido","Proporcion_Javiera","Proporcion_Francis",
    "Created_At","Created_By","Last_Modified_At","Last_Modified_By","Anulado"
]

FLASH_KEY = "flash_notice"

# =========================================================
# UI CONFIG
# =========================================================
st.set_page_config(page_title="Finanzas APP", page_icon="💰", layout="wide")
st.title("💰 Finanzas Javiera & Francis")

def _show_flash():
    if FLASH_KEY in st.session_state:
        f = st.session_state[FLASH_KEY]
        st.success(f["msg"])
        if f.get("record"):
            st.json(f["record"])
        del st.session_state[FLASH_KEY]
        st.session_state["just_saved"] = False

# =========================================================
# GOOGLE SHEETS
# =========================================================
def _a1_range_row(row: int, ncols: int) -> str:
    last_cell = gspread.utils.rowcol_to_a1(row, ncols)
    last_col = re.sub(r"\d+", "", last_cell)
    return f"A{row}:{last_col}{row}"

def _open_ws(sheet_name=HOJA):
    creds = Credentials.from_service_account_info(
        st.secrets["gspread"],
        scopes=[
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ],
    )
    client = gspread.authorize(creds)
    sh = client.open_by_key(SPREADSHEET_KEY)
    return sh.worksheet(sheet_name)

def _ensure_headers(ws):
    headers_raw = ws.row_values(1)
    headers = [h.strip() for h in headers_raw]
    missing = [h for h in EXPECTED_HEADERS if h not in headers]
    if missing:
        new_headers = headers + missing
        ws.update(_a1_range_row(1, len(new_headers)), [new_headers])
        return new_headers
    return headers

@st.cache_data(ttl=120)
def _load_df() -> pd.DataFrame:
    ws = _open_ws(HOJA)
    headers = _ensure_headers(ws)
    values = ws.get_all_values()
    if not values:
        return pd.DataFrame(columns=EXPECTED_HEADERS + ["_row"])
    rows = values[1:]
    norm_rows = [r[:len(headers)] + [""] * max(0, len(headers)-len(r)) for r in rows]
    df = pd.DataFrame(norm_rows, columns=headers)
    df["_row"] = range(2, 2+len(df))
    return df

def _normalize_df(df_raw: pd.DataFrame) -> pd.DataFrame:
    if df_raw.empty:
        return pd.DataFrame(columns=EXPECTED_HEADERS + ["_row"])
    df = df_raw.copy()
    df["Fecha_dt"] = pd.to_datetime(df["Fecha"], errors="coerce")
    df["Monto_int"] = pd.to_numeric(df["Monto"], errors="coerce").fillna(0).astype(int)
    df["Monto_original"] = pd.to_numeric(df["Monto_original"], errors="coerce").fillna(0)
    df["Anulado_bool"] = df["Anulado"].str.lower().isin(["true","1","si","sí","yes","y"])
    df["Compartido_bool"] = df["Compartido"].str.lower().isin(["true","1","si","sí","yes","y"])
    return df

def _append_record(record: dict):
    ws = _open_ws(HOJA)
    headers = _ensure_headers(ws)
    row_out = [record.get(h,"") for h in headers]
    ws.append_row(row_out, value_input_option="USER_ENTERED")

def _update_row(row: int, record: dict):
    ws = _open_ws(HOJA)
    headers = _ensure_headers(ws)
    vals = [record.get(h,"") for h in headers]
    ws.update(_a1_range_row(row, len(headers)), [vals])

# =========================================================
# MONEDA
# =========================================================
def _get_usd_value(date: dt.date) -> float:
    try:
        resp = requests.get("https://mindicador.cl/api/dolar")
        data = resp.json()
        for d in data["serie"]:
            if d["fecha"].startswith(date.strftime("%Y-%m-%d")):
                return d["valor"]
        return data["serie"][0]["valor"]  # último valor
    except:
        return 900  # fallback

def _procesar_monto(monto: float, moneda: str, fecha: dt.date):
    if moneda == "USD":
        valor = _get_usd_value(fecha)
        return monto * valor, monto
    return monto, monto

def formatear_monto(valor, moneda="CLP"):
    try:
        valor = float(valor)
    except:
        return valor
    if moneda == "CLP":
        return f"${valor:,.0f}"       # CLP sin decimales
    elif moneda == "USD":
        return f"US${valor:,.2f}"     # USD con 2 decimales
    return str(valor)



# =========================================================
# UI EXTRA
# =========================================================
def _tipo_registro_ui():
    st.subheader("1️⃣ Tipo de registro")
    opciones = ["--- Selecciona ---", "Ingreso", "Gasto individual", "Gasto compartido"]
    if "tipo_registro" not in st.session_state:
        st.session_state["tipo_registro"] = "--- Selecciona ---"
    st.radio("Selecciona el tipo:", opciones, key="tipo_registro")

    if st.session_state["tipo_registro"] == "Gasto compartido":
        if "prop_j" not in st.session_state:
            st.session_state["prop_j"] = 50
        st.slider("Proporción Javiera", 0, 100,
                  st.session_state["prop_j"], step=5, key="prop_j")
        st.caption(f"Francis: {100 - st.session_state['prop_j']}%")

def _categoria_ui(cats_existentes: list[str]):
    st.subheader("2️⃣ Categoría")
    if "use_new_cat" not in st.session_state:
        st.session_state["use_new_cat"] = False

    col1, col2 = st.columns([2,1])
    with col1:
        st.selectbox(
            "Categoría existente",
            [""]+cats_existentes,
            key="cat_exist",
            disabled=st.session_state["use_new_cat"]
        )
    with col2:
        st.checkbox("➕ Nueva categoría", key="use_new_cat")

    if st.session_state["use_new_cat"]:
        st.text_input("Nombre nueva categoría", key="cat_new")

# =========================================================
# FORMULARIOS
# =========================================================
def _form_ingreso_gasto(cats_existentes: list[str]):
   
    _tipo_registro_ui()
    if st.session_state["tipo_registro"] == "--- Selecciona ---":
        st.info("👉 Selecciona primero el tipo de registro para continuar.")
        return

    _categoria_ui(cats_existentes)

    with st.form("form_mov", clear_on_submit=True):
        fecha = st.date_input("Fecha", value=dt.date.today())
        persona = st.selectbox("Persona", USUARIOS)
        medio = st.selectbox("Medio de pago", [""]+MEDIOS)
        monto_in = st.number_input("Monto", min_value=0, step=100)
        moneda = st.selectbox("Moneda", ["CLP","USD"])
        detalle = st.text_input("Detalle")

        if st.form_submit_button("💾 Registrar"):
            tipo_sel = "Ingreso" if st.session_state["tipo_registro"] == "Ingreso" else "Gasto"
            compartido = (st.session_state["tipo_registro"] == "Gasto compartido")
            pj = st.session_state.get("prop_j", 50) if compartido else ""
            pf = (100 - pj) if compartido else ""

            monto_clp, monto_original = _procesar_monto(monto_in, moneda, fecha)

            categoria = (st.session_state["cat_new"].strip()
                         if st.session_state.get("use_new_cat") and st.session_state.get("cat_new")
                         else st.session_state.get("cat_exist",""))

            now = pd.Timestamp.now(tz=STGO)
            record = {
                "ID": str(uuid.uuid4()),
                "Tipo": tipo_sel,
                "Detalle": detalle,
                "Categoría": categoria,
                "Fecha": fecha.strftime("%Y-%m-%d"),
                "Persona": persona,
                "Persona_Origen": "",
                "Persona_Destino": "",
                "Monto": int(monto_clp),
                "Monto_original": monto_original,
                "Moneda": moneda,
                "Medio": medio,
                "Compartido": "TRUE" if compartido else "",
                "Proporcion_Javiera": pj if compartido else "",
                "Proporcion_Francis": pf if compartido else "",
                "Created_At": now.strftime("%Y-%m-%d %H:%M:%S"),
                "Created_By": persona,
                "Last_Modified_At": "",
                "Last_Modified_By": "",
                "Anulado": ""
            }
            _append_record(record)
            st.session_state[FLASH_KEY] = {"msg":f"{tipo_sel} registrado ✅","record":record}
            st.session_state["just_saved"] = True

def _form_traspaso():
    st.subheader("➕ Registrar Traspaso")
    with st.form("form_traspaso", clear_on_submit=True):
        fecha = st.date_input("Fecha", value=dt.date.today())
        col1,col2 = st.columns(2)
        with col1:
            origen = st.selectbox("Origen", USUARIOS)
        with col2:
            destino = st.selectbox("Destino", USUARIOS)
        monto_in = st.number_input("Monto", min_value=0, step=100)
        moneda = st.selectbox("Moneda", ["CLP","USD"])
        detalle = st.text_input("Detalle")

        if st.form_submit_button("💾 Registrar traspaso"):
            monto_clp, monto_original = _procesar_monto(monto_in, moneda, fecha)
            now = pd.Timestamp.now(tz=STGO)
            record = {
                "ID": str(uuid.uuid4()),
                "Tipo": "Traspaso",
                "Detalle": detalle,
                "Categoría": "",
                "Fecha": fecha.strftime("%Y-%m-%d"),
                "Persona": "",
                "Persona_Origen": origen,
                "Persona_Destino": destino,
                "Monto": int(monto_clp),
                "Monto_original": monto_original,
                "Moneda": moneda,
                "Medio": "",
                "Compartido": "",
                "Proporcion_Javiera": "",
                "Proporcion_Francis": "",
                "Created_At": now.strftime("%Y-%m-%d %H:%M:%S"),
                "Created_By": origen,
                "Last_Modified_At": "",
                "Last_Modified_By": "",
                "Anulado": ""
            }
            _append_record(record)
            st.session_state[FLASH_KEY] = {"msg":"Traspaso registrado ✅","record":record}
            st.session_state["just_saved"] = True

# =========================================================
# HISTORIAL
# =========================================================
def _historial(df: pd.DataFrame):
    st.subheader("📜 Historial de registros")
    show_anulados = st.checkbox("Mostrar registros anulados", value=False)

    df_show = df.copy()
    if not show_anulados:
        df_show = df_show[~df_show["Anulado_bool"]]

    st.dataframe(df_show.sort_values("Fecha_dt", ascending=False).head(50))

    edit_id = st.text_input("ID a editar/anular")
    accion = st.radio("Acción", ["","Editar","Anular"])

    if accion=="Anular" and edit_id:
        row = df[df["ID"]==edit_id]
        if not row.empty:
            rec = row.iloc[0].to_dict()
            rec["Anulado"] = "TRUE"
            _update_row(int(row["_row"].values[0]), rec)
            st.success("Registro anulado")
            st.cache_data.clear()
            

    if accion=="Editar" and edit_id:
        row = df[df["ID"]==edit_id]
        if not row.empty:
            rec = row.iloc[0].to_dict()
            st.subheader(f"✏️ Editando registro {edit_id}")
            with st.form("edit_form"):
                detalle = st.text_input("Detalle", rec["Detalle"])
                monto_in = st.number_input("Monto", value=float(rec["Monto_original"]))
                moneda = st.selectbox("Moneda", ["CLP","USD"], index=0 if rec["Moneda"]=="CLP" else 1)
                if st.form_submit_button("Guardar cambios"):
                    monto_clp, monto_original = _procesar_monto(monto_in, moneda, pd.to_datetime(rec["Fecha"]))
                    rec["Detalle"] = detalle
                    rec["Monto_original"] = monto_original
                    rec["Moneda"] = moneda
                    rec["Monto"] = int(monto_clp)
                    rec["Last_Modified_At"] = pd.Timestamp.now(tz=STGO).strftime("%Y-%m-%d %H:%M:%S")
                    rec["Last_Modified_By"] = "Edición manual"
                    _update_row(int(row["_row"].values[0]), rec)
                    st.session_state[FLASH_KEY] = {"msg":"Registro actualizado ✅","record":rec}
                    st.session_state["just_saved"] = True
                    # Resetear triggers
                    st.session_state["accion"] = ""
                    st.session_state["edit_id"] = ""
                    st.cache_data.clear()
                    st.rerun()


# =========================================================
# CÁLCULOS DE GASTOS
# =========================================================

def calcular_gastos_personales(df: pd.DataFrame, persona: str) -> dict:
    df_activos = df[~df["Anulado_bool"]]

    # Gastos individuales
    indiv = df_activos[
        (df_activos["Tipo"]=="Gasto") &
        (~df_activos["Compartido_bool"]) &
        (df_activos["Persona"]==persona)
    ]["Monto_int"].sum()

    # Gastos compartidos pagados por esta persona
    df_comp_pagos = df_activos[
        (df_activos["Tipo"]=="Gasto") &
        (df_activos["Compartido_bool"]) &
        (df_activos["Persona"]==persona)
    ]
    if persona == USER_A:
        comp_pagados = (df_comp_pagos["Monto_int"] * df_comp_pagos["Proporcion_Javiera"].astype(float)/100).sum()
    else:
        comp_pagados = (df_comp_pagos["Monto_int"] * df_comp_pagos["Proporcion_Francis"].astype(float)/100).sum()

    # Gastos compartidos pagados por la otra persona
    df_comp_otro = df_activos[
        (df_activos["Tipo"]=="Gasto") &
        (df_activos["Compartido_bool"]) &
        (df_activos["Persona"]!=persona)
    ]
    if persona == USER_A:
        comp_recibidos = (df_comp_otro["Monto_int"] * df_comp_otro["Proporcion_Javiera"].astype(float)/100).sum()
    else:
        comp_recibidos = (df_comp_otro["Monto_int"] * df_comp_otro["Proporcion_Francis"].astype(float)/100).sum()

    total = indiv + comp_pagados + comp_recibidos

    return {
        "Persona": persona,
        "Gastos_individuales": indiv,
        "Aporte_compartidos_pagados": comp_pagados,
        "Beneficio_compartidos_recibidos": comp_recibidos,
        "Total_considerado": total
    }


def calcular_saldos(df: pd.DataFrame) -> dict:
    df_activos = df[~df["Anulado_bool"] & df["Compartido_bool"]]

    # Lo que Javiera pagó por Francis
    pagado_por_j = (df_activos[df_activos["Persona"]==USER_A]["Monto_int"] *
                    df_activos[df_activos["Persona"]==USER_A]["Proporcion_Francis"].astype(float)/100).sum()
    # Lo que Francis pagó por Javiera
    pagado_por_f = (df_activos[df_activos["Persona"]==USER_B]["Monto_int"] *
                    df_activos[df_activos["Persona"]==USER_B]["Proporcion_Javiera"].astype(float)/100).sum()

    saldo_j = pagado_por_f - pagado_por_j
    saldo_f = pagado_por_j - pagado_por_f

    return {
        USER_A: saldo_j,
        USER_B: saldo_f
    }

# =========================================================
# RESUMEN
# =========================================================
def _resumen(df: pd.DataFrame):
    st.subheader("📊 Resumen general")

   
    # -----------------------
    # Selector de período
    # -----------------------
    meses = sorted(df["Fecha_dt"].dt.to_period("M").dropna().unique())
    opciones_meses = [str(m) for m in meses]

    mes_sel = None
    if opciones_meses:
        mes_sel = st.selectbox(
            "Selecciona un mes",
            opciones_meses,
            index=len(opciones_meses)-1  # por defecto el último (mes más reciente)
        )

    rango_fechas = st.date_input("O selecciona un rango de fechas", [])

    if mes_sel:
        periodo = pd.Period(mes_sel)
        df_periodo = df[df["Fecha_dt"].dt.to_period("M") == periodo]
    elif rango_fechas and len(rango_fechas) == 2:
        df_periodo = df[
            (df["Fecha_dt"] >= pd.to_datetime(rango_fechas[0])) &
            (df["Fecha_dt"] <= pd.to_datetime(rango_fechas[1]))
        ]
    else:
        df_periodo = df
        
    df_activos = df_periodo[~df_periodo["Anulado_bool"]]

    # -----------------------
    # Sub-tabs
    # -----------------------
    subtab = st.radio("Secciones del resumen",
                      ["🌍 Totales globales","👤 Totales por persona","🤝 Gastos compartidos","🔁 Traspasos","📋 Todos los registros"],
                      horizontal=True)

    # 🌍 Totales globales
    if subtab=="🌍 Totales globales":
        total_clp = df_activos[df_activos["Moneda"]=="CLP"]["Monto_int"].sum()
        total_usd = df_activos[df_activos["Moneda"]=="USD"]["Monto_original"].sum()

        st.write("**Totales**")
        st.dataframe(pd.DataFrame({
            "Total CLP":[formatear_monto(total_clp,"CLP")],
            "Total USD originales":[formatear_monto(total_usd,"USD")]
        }))

        totales_tipo = df_activos.groupby("Tipo")["Monto_int"].sum().reset_index()
        totales_tipo["Monto_fmt"] = totales_tipo.apply(lambda r: formatear_monto(r["Monto_int"],"CLP"), axis=1)
        st.write("**Totales por tipo de movimiento (CLP)**")
        st.dataframe(totales_tipo[["Tipo","Monto_fmt"]])

    # 👤 Totales por persona
    elif subtab=="👤 Totales por persona":
        res_j = calcular_gastos_personales(df_periodo, USER_A)
        res_f = calcular_gastos_personales(df_periodo, USER_B)

        st.write("**Totales personales (CLP)**")
        st.dataframe(pd.DataFrame([res_j,res_f]))

        st.write("**Gastos por categoría (CLP)**")
        cat_persona = df_activos[df_activos["Tipo"]=="Gasto"].groupby(["Persona","Categoría"])["Monto_int"].sum().reset_index()
        cat_persona = cat_persona.sort_values(["Persona","Monto_int"], ascending=[True,False])
        cat_persona["Monto_fmt"] = cat_persona.apply(lambda r: formatear_monto(r["Monto_int"],"CLP"), axis=1)
        st.dataframe(cat_persona[["Persona","Categoría","Monto_fmt"]])

    # 🤝 Gastos compartidos
    elif subtab=="🤝 Gastos compartidos":
        gastos_compartidos = df_activos[df_activos["Compartido_bool"]].copy()
        if gastos_compartidos.empty:
            st.info("No hay gastos compartidos en este período.")
        else:
            gastos_compartidos["Monto_fmt"] = gastos_compartidos.apply(
                lambda r: formatear_monto(r["Monto_int"], "CLP"), axis=1
            )
            st.write("**Detalle de gastos compartidos**")
            st.dataframe(gastos_compartidos[[
                "Fecha","Detalle","Categoría","Persona","Monto_fmt","Proporcion_Javiera","Proporcion_Francis"
            ]])

            saldos = calcular_saldos(df_periodo)
            st.write("**Totales de gastos compartidos**")
            st.dataframe(pd.DataFrame([
                {"Persona":USER_A, "Saldo pendiente": formatear_monto(saldos[USER_A],"CLP")},
                {"Persona":USER_B, "Saldo pendiente": formatear_monto(saldos[USER_B],"CLP")}
            ]))

    # 🔁 Traspasos
    elif subtab=="🔁 Traspasos":
        trasp = df_activos[df_activos["Tipo"]=="Traspaso"].copy()
        if trasp.empty:
            st.info("No hay traspasos en este período.")
        else:
            trasp["Monto_fmt"] = trasp.apply(lambda r: formatear_monto(r["Monto_original"], r["Moneda"]), axis=1)
            st.write("**Detalle de traspasos**")
            st.dataframe(trasp[["Fecha","Persona_Origen","Persona_Destino","Monto_fmt","Moneda"]])

            resumen_trasp = trasp.groupby("Persona_Origen")["Monto_int"].sum().reset_index()
            resumen_trasp["Monto_fmt"] = resumen_trasp.apply(lambda r: formatear_monto(r["Monto_int"],"CLP"), axis=1)
            st.write("**Resumen neto de traspasos (CLP)**")
            st.dataframe(resumen_trasp[["Persona_Origen","Monto_fmt"]])

    # 📋 Todos los registros
    elif subtab=="📋 Todos los registros":
        with st.expander("Ver registros completos del período"):
            df_periodo["Monto_fmt"] = df_periodo.apply(
                lambda r: formatear_monto(r["Monto_original"], r["Moneda"]), axis=1
            )
            st.dataframe(df_periodo)


# =========================================================
# MAIN
# =========================================================
def render():
    df_raw = _load_df()
    df = _normalize_df(df_raw)
    cats = sorted(df["Categoría"].dropna().unique().tolist())

    tab = st.radio(
        "Navegación",
        ["📊 Resumen","➕ Ingreso/Gasto","🔁 Traspaso","📜 Historial"],
        horizontal=True,
        key="active_tab"
    )

    if st.session_state.get("just_saved", False):
        _show_flash()

    if tab == "📊 Resumen":
        _resumen(df)
    elif tab == "➕ Ingreso/Gasto":
        _form_ingreso_gasto(cats)
    elif tab == "🔁 Traspaso":
        _form_traspaso()
    elif tab == "📜 Historial":
        _historial(df)

render()
