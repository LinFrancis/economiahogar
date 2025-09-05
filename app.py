import uuid
import re
import streamlit as st
import pandas as pd
import datetime as dt
from zoneinfo import ZoneInfo
import gspread
from google.oauth2.service_account import Credentials

# =========================================================
# CONFIG BÁSICA
# =========================================================

STGO = ZoneInfo("America/Santiago")

# 👉 NUEVA PLANILLA (la que enviaste):
SPREADSHEET_KEY = "1-McBRqr5mdiw3Wd0Cw9lOebvp1C7AOj1JmTz4wpyPoA"
HOJA = "finanzas"  # cámbialo si tu pestaña tiene otro nombre

# Usuarios (con emojis) y nombres "limpios" para proporciones
USER_A = "🐳Javiera"
USER_B = "🪈Francis"
NAME_A = "Javiera"
NAME_B = "Francis"
USUARIOS = [USER_A, USER_B]

# Medios de pago
MEDIOS = ["Efectivo", "Tarjeta de crédito", "Débito", "Transferencia", "Cuenta de ahorro", "Otro"]

# Encabezados esperados (se agregan si faltan)
EXPECTED_HEADERS = [
    "ID","Tipo","Detalle","Categoría","Fecha","Persona",
    "Persona_Origen","Persona_Destino","Monto",
    "Medio","Compartido","Proporcion_Javiera","Proporcion_Francis",
    "Created_At","Created_By","Last_Modified_At","Last_Modified_By","Anulado"
]

FLASH_KEY = "flash_notice"

# =========================================================
# UI SETUP
# =========================================================
def setup_app():
    st.set_page_config(
        page_title="Finanzas APP - Javiera y Francis",
        page_icon="💰",
        layout="wide",
        initial_sidebar_state="collapsed"
    )
    col1, col2 = st.columns([1, 4])
    with col1:
        try:
            st.image("images/logoapp.png")
        except:
            st.write("💰")
    with col2:
        st.title("Finanzas APP - Javiera y Francis")

    # Selector de usuario "básico" (no auth formal, pero práctico)
    st.sidebar.markdown("### 👤 Usuario actual")
    default_idx = 1 if USER_B in USUARIOS else 0
    st.selectbox("¿Quién usa la app?", USUARIOS, index=default_idx, key="current_user")
    # Filtros globales
    st.sidebar.markdown("### 🔎 Filtros rápidos")
    st.selectbox("Ver movimientos de", ["Todos"] + USUARIOS, index=0, key="vista_persona")
    st.selectbox("Filtrar por medio", ["Todos"] + MEDIOS, index=0, key="vista_medio")
    st.sidebar.divider()

def _show_flash():
    """Muestra mensaje resumen después de crear/editar/anular y lo limpia."""
    if FLASH_KEY in st.session_state:
        f = st.session_state[FLASH_KEY]
        tipo = f.get("kind", "ok")
        msg = f.get("msg", "")
        rec = f.get("record")
        if tipo == "ok":
            st.success(msg)
        elif tipo == "warn":
            st.warning(msg)
        else:
            st.info(msg)
        if rec:
            with st.expander("Ver resumen del registro", expanded=True):
                st.json(rec, expanded=False)
        del st.session_state[FLASH_KEY]

setup_app()

# =========================================================
# HELPERS CONEXIÓN
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

def _ensure_sheet_headers(ws):
    headers_raw = ws.row_values(1)
    headers = [h.strip() for h in headers_raw]
    missing = [h for h in EXPECTED_HEADERS if h not in headers]
    if missing:
        new_headers = headers + missing
        ws.update(_a1_range_row(1, len(new_headers)), [new_headers])
        return new_headers
    return headers

# =========================================================
# NORMALIZACIÓN
# =========================================================
def _parse_monto_raw(x) -> int:
    if pd.isna(x): return 0
    s = str(x).replace("$", "").replace(".", "").replace(",", "").strip()
    if s == "": return 0
    try:
        return abs(int(float(s)))
    except:
        return 0

def _parse_fecha_any(s) -> pd.Timestamp:
    return pd.to_datetime(s, dayfirst=True, errors="coerce")

@st.cache_data(ttl=120)
def _load_finanzas_df() -> pd.DataFrame:
    try:
        ws = _open_ws(HOJA)
        headers = _ensure_sheet_headers(ws)
        values = ws.get_all_values()
    except Exception as e:
        st.error(f"No se pudo leer la hoja '{HOJA}': {e}")
        return pd.DataFrame(columns=EXPECTED_HEADERS)

    if not values:
        return pd.DataFrame(columns=EXPECTED_HEADERS)
    rows = values[1:]
    norm_rows = [r[:len(headers)] + [""] * max(0, len(headers)-len(r)) for r in rows]
    df = pd.DataFrame(norm_rows, columns=headers)
    return df

def _normalize_finanzas(df_raw: pd.DataFrame) -> pd.DataFrame:
    if df_raw is None or df_raw.empty:
        return pd.DataFrame(columns=EXPECTED_HEADERS)

    df = df_raw.copy()
    for c in ["Tipo","Detalle","Categoría","Persona","Persona_Origen","Persona_Destino","Medio","Compartido"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()
        else:
            df[c] = ""

    # Proporciones
    for c in ["Proporcion_Javiera","Proporcion_Francis"]:
        if c not in df.columns:
            df[c] = ""
        df[c] = pd.to_numeric(df[c].replace("", pd.NA), errors="coerce").fillna(0).astype(int)

    # Flags y derivados
    df["Fecha_dt"] = df["Fecha"].apply(_parse_fecha_any)
    df["Monto_int"] = df["Monto"].apply(_parse_monto_raw)
    df["Anulado_bool"] = df["Anulado"].astype(str).str.lower().isin(["true","1","sí","si","yes","y"])
    df["Compartido_bool"] = df["Compartido"].astype(str).str.lower().isin(["true","1","sí","si","yes","y"])
    if "_row" not in df.columns:
        df["_row"] = range(2, 2+len(df))

    # Período YYYY-MM
    df["Periodo"] = df["Fecha_dt"].dt.strftime("%Y-%m")

    return df

# =========================================================
# CÁLCULOS
# =========================================================
def _calc_saldos_por_persona(df: pd.DataFrame) -> pd.DataFrame:
    df_ok = df[~df["Anulado_bool"]].copy()
    saldos = []
    for persona in USUARIOS:
        ingresos = df_ok[(df_ok["Tipo"]=="Ingreso") & (df_ok["Persona"]==persona)]["Monto_int"].sum()
        gastos = df_ok[(df_ok["Tipo"]=="Gasto") & (df_ok["Persona"]==persona)]["Monto_int"].sum()
        t_recib = df_ok[(df_ok["Tipo"]=="Traspaso") & (df_ok["Persona_Destino"]==persona)]["Monto_int"].sum()
        t_entreg = df_ok[(df_ok["Tipo"]=="Traspaso") & (df_ok["Persona_Origen"]==persona)]["Monto_int"].sum()
        saldo = ingresos + t_recib - gastos - t_entreg
        saldos.append({
            "Persona": persona,
            "Saldo": int(saldo),
            "Ingresos": int(ingresos),
            "Gastos": int(gastos),
            "Traspasos_Recibidos": int(t_recib),
            "Traspasos_Entregados": int(t_entreg),
        })
    return pd.DataFrame(saldos)

def _get_shares(row) -> tuple[int,int]:
    """Devuelve (share_Javiera, share_Francis) forzando [0..100] y suma 100."""
    sj = int(row.get("Proporcion_Javiera", 0)) if pd.notna(row.get("Proporcion_Javiera", 0)) else 0
    sf = int(row.get("Proporcion_Francis", 0)) if pd.notna(row.get("Proporcion_Francis", 0)) else 0
    if sj < 0: sj = 0
    if sf < 0: sf = 0
    if sj == 0 and sf == 0:
        sj = 50; sf = 50
    total = sj + sf
    if total != 100 and total > 0:
        # Normaliza para sumar 100
        sj = round(sj * 100 / total)
        sf = 100 - sj
    return sj, sf

def _calc_ajustes_compartidos(df: pd.DataFrame) -> dict:
    """
    Ajustes SOLO sobre gastos compartidos.
    Para cada gasto compartido:
      - quien paga = 'Persona'
      - 'Debe' de cada uno = Monto * su proporción
      - 'Pago' de cada uno = suma de los montos que efectivamente pagó (como 'Persona')
    Resultado: proponer transferencias para saldar diferencias (Pago - Debe).
    """
    df_ok = df[(~df["Anulado_bool"]) & (df["Tipo"]=="Gasto") & (df["Compartido_bool"])].copy()
    if df_ok.empty:
        return {
            "total_compartido": 0,
            "debe": {USER_A: 0, USER_B: 0},
            "pago": {USER_A: 0, USER_B: 0},
            "balances": {USER_A: 0, USER_B: 0},
            "ajustes": [],
        }

    # Sumas "Debe"
    debe = {USER_A: 0, USER_B: 0}
    pago = {USER_A: 0, USER_B: 0}
    total = 0

    for _, r in df_ok.iterrows():
        monto = int(r["Monto_int"])
        total += monto
        sj, sf = _get_shares(r)
        debe[USER_A] += round(monto * sj / 100)
        debe[USER_B] += round(monto * sf / 100)
        # Pagos efectivos (quien aparece como Persona)
        if r["Persona"] == USER_A:
            pago[USER_A] += monto
        elif r["Persona"] == USER_B:
            pago[USER_B] += monto

    # Balance: positivo = pagó de más vs lo que debía; negativo = pagó de menos
    balances = {
        USER_A: int(pago[USER_A] - debe[USER_A]),
        USER_B: int(pago[USER_B] - debe[USER_B]),
    }

    # Proponer transferencias
    deudores = [(p, -bal) for p, bal in balances.items() if bal < 0]
    acreedores = [(p, bal) for p, bal in balances.items() if bal > 0]
    deudores.sort(key=lambda x: x[1], reverse=True)
    acreedores.sort(key=lambda x: x[1], reverse=True)

    ajustes = []
    i, j = 0, 0
    while i < len(deudores) and j < len(acreedores):
        deudor, debe_monto = deudores[i]
        acreedor, recibe_monto = acreedores[j]
        monto = min(debe_monto, recibe_monto)
        ajustes.append({"Deudor": deudor, "Acreedor": acreedor, "Monto": int(monto)})
        deudores[i] = (deudor, debe_monto - monto)
        acreedores[j] = (acreedor, recibe_monto - monto)
        if deudores[i][1] == 0: i += 1
        if acreedores[j][1] == 0: j += 1

    return {
        "total_compartido": int(total),
        "debe": {k:int(v) for k,v in debe.items()},
        "pago": {k:int(v) for k,v in pago.items()},
        "balances": balances,
        "ajustes": ajustes,
    }

# =========================================================
# FORMULARIOS
# =========================================================
def _append_record(record: dict):
    ws = _open_ws(HOJA)
    headers = _ensure_sheet_headers(ws)
    row_out = [record.get(h,"") for h in headers]
    ws.append_row(row_out, value_input_option="USER_ENTERED")

def _update_row(rownum: int, valores: dict):
    ws = _open_ws(HOJA)
    headers = _ensure_sheet_headers(ws)
    row_out = [valores.get(h,"") for h in headers]
    ws.update(_a1_range_row(rownum, len(headers)), [row_out], value_input_option="USER_ENTERED")

# ---------- Traspaso (independiente) ----------
def _form_traspaso():
    with st.form("form_traspaso", clear_on_submit=True):
        fecha = st.date_input("Fecha", value=dt.date.today(), max_value=dt.date.today(), key="t_fecha")
        col1,col2,col3 = st.columns(3)
        with col1: origen = st.selectbox("Persona que entrega", [""]+USUARIOS, index=USUARIOS.index(st.session_state["current_user"])+1, key="t_origen")
        with col2: destino = st.selectbox("Persona que recibe", [""]+USUARIOS, key="t_destino")
        with col3: monto = st.number_input("Monto (CLP)", min_value=0, step=100, key="t_monto")
        detalle = st.text_input("Detalle (obligatorio)", "", key="t_detalle")

        submit = st.form_submit_button("Registrar traspaso")
        if submit:
            if not (origen and destino and monto>0 and len(detalle.strip())>=5 and origen!=destino):
                st.error("⚠️ Completa todos los campos y revisa que origen ≠ destino.")
            else:
                now = pd.Timestamp.now(tz=STGO)
                record = {
                    "ID": str(uuid.uuid4()),
                    "Tipo": "Traspaso",
                    "Detalle": detalle.strip(),
                    "Categoría": "",
                    "Fecha": fecha.strftime("%Y-%m-%d"),
                    "Persona": "",
                    "Persona_Origen": origen,
                    "Persona_Destino": destino,
                    "Monto": str(int(monto)),
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
                st.session_state[FLASH_KEY] = {"kind":"ok","msg":f"🔄 Traspaso {origen} → {destino} registrado.","record":record}
                st.cache_data.clear()
                st.rerun()

# ---------- Ingreso/Gasto unificado ----------
def _ensure_reg_defaults():
    ss = st.session_state
    ss.setdefault("mov_tipo", "Gasto")
    ss.setdefault("mov_fecha", dt.date.today())
    ss.setdefault("mov_persona", ss.get("current_user", USER_B))
    ss.setdefault("mov_medio", "")
    ss.setdefault("mov_monto", 0)
    ss.setdefault("mov_detalle", "")
    ss.setdefault("mov_usar_nueva_cat", False)
    ss.setdefault("mov_cat_exist", "")
    ss.setdefault("mov_nueva_cat", "")
    ss.setdefault("mov_compartido", True)  # por defecto compartido visible = 50/50
    ss.setdefault("mov_prop_j", 50)        # 50% Javiera

def _reset_reg_defaults():
    ss = st.session_state
    ss["mov_tipo"] = "Gasto"
    ss["mov_fecha"] = dt.date.today()
    ss["mov_persona"] = ss.get("current_user", USER_B)
    ss["mov_medio"] = ""
    ss["mov_monto"] = 0
    ss["mov_detalle"] = ""
    ss["mov_usar_nueva_cat"] = False
    ss["mov_cat_exist"] = ""
    ss["mov_nueva_cat"] = ""
    ss["mov_compartido"] = True
    ss["mov_prop_j"] = 50

def _form_ingreso_gasto_unificado(cats_existentes: list[str]):
    _ensure_reg_defaults()

    with st.form("form_mov_unificado", clear_on_submit=False):
        # 1) Tipo dentro del formulario (no borra el resto)
        st.selectbox("Tipo de movimiento", ["Ingreso","Gasto"], key="mov_tipo")

        # 2) Fecha / Persona / Medio / Monto
        c1, c2, c3 = st.columns(3)
        with c1:
            st.date_input("Fecha", value=st.session_state["mov_fecha"], max_value=dt.date.today(), key="mov_fecha")
        with c2:
            st.selectbox("Persona", USUARIOS, index=USUARIOS.index(st.session_state["mov_persona"]) if st.session_state.get("mov_persona") in USUARIOS else 0, key="mov_persona")
        with c3:
            st.selectbox("Medio de pago", [""]+MEDIOS, key="mov_medio")

        st.number_input("Monto (CLP)", min_value=0, step=100, key="mov_monto")
        st.text_input("Detalle", key="mov_detalle")

        # 3) Categoría con opción de nueva (persistente)
        st.markdown("#### Categoría")
        col1, col2 = st.columns([2,1])
        with col1:
            opciones = [""] + sorted({c for c in cats_existentes if c})
            st.selectbox("Categoría existente", opciones, key="mov_cat_exist")
        with col2:
            st.checkbox("➕ Crear nueva", key="mov_usar_nueva_cat")

        if st.session_state["mov_usar_nueva_cat"]:
            st.text_input("Nombre nueva categoría", key="mov_nueva_cat")

        # 4) Gasto compartido (solo si es Gasto). Defaults 50/50, persistentes
        if st.session_state["mov_tipo"] == "Gasto":
            st.checkbox("Es un gasto compartido", key="mov_compartido", help="Si está activado, reparte el monto según proporciones.")
            if st.session_state["mov_compartido"]:
                st.caption("Ajusta las proporciones (la suma debe ser 100%).")
                st.slider(f"Proporción para {NAME_A}", 0, 100, st.session_state["mov_prop_j"], step=5, key="mov_prop_j")
                st.write(f"Proporción para {NAME_B}: **{100 - st.session_state['mov_prop_j']}%**")

        # 5) Botones
        colA, colB = st.columns([1,1])
        with colA:
            submit = st.form_submit_button("💾 Registrar movimiento")
        with colB:
            limpiar = st.form_submit_button("🧹 Limpiar formulario")

        # 6) Acciones
        if limpiar:
            _reset_reg_defaults()
            st.info("Formulario limpiado.")
        if submit:
            categoria_final = (st.session_state["mov_nueva_cat"] if st.session_state["mov_usar_nueva_cat"] else st.session_state["mov_cat_exist"]).strip()
            if not (st.session_state["mov_persona"] and categoria_final and st.session_state["mov_medio"] and st.session_state["mov_monto"] > 0 and len(st.session_state["mov_detalle"].strip()) >= 3):
                st.error("⚠️ Debes completar Persona, Categoría, Medio, Monto (>0) y Detalle (≥3).")
            else:
                now = pd.Timestamp.now(tz=STGO)
                compartido_flag = (st.session_state["mov_tipo"]=="Gasto" and st.session_state.get("mov_compartido", False))
                pj = int(st.session_state.get("mov_prop_j", 50)) if compartido_flag else ""
                pf = (100 - int(pj)) if compartido_flag else ""

                record = {
                    "ID": str(uuid.uuid4()),
                    "Tipo": st.session_state["mov_tipo"],
                    "Detalle": st.session_state["mov_detalle"].strip(),
                    "Categoría": categoria_final,
                    "Fecha": st.session_state["mov_fecha"].strftime("%Y-%m-%d"),
                    "Persona": st.session_state["mov_persona"],
                    "Persona_Origen": "",
                    "Persona_Destino": "",
                    "Monto": str(int(st.session_state["mov_monto"])),
                    "Medio": st.session_state["mov_medio"],
                    "Compartido": "TRUE" if compartido_flag else "",
                    "Proporcion_Javiera": pj,
                    "Proporcion_Francis": pf,
                    "Created_At": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "Created_By": st.session_state["mov_persona"],
                    "Last_Modified_At": "",
                    "Last_Modified_By": "",
                    "Anulado": ""
                }
                _append_record(record)
                st.session_state[FLASH_KEY] = {"kind":"ok","msg":f"✅ {st.session_state['mov_tipo']} registrado correctamente.","record":record}
                _reset_reg_defaults()
                st.cache_data.clear()
                st.rerun()

def _form_registro(cats_existentes: list[str]):
    st.markdown("### ➕ Registrar movimiento")
    _show_flash()
    with st.expander("🧾 Ingreso o Gasto", expanded=True):
        _form_ingreso_gasto_unificado(cats_existentes)
    with st.expander("🔁 Traspaso entre cuentas/personas", expanded=False):
        _form_traspaso()

# ---------- Edición/Anulación ----------
def _form_editar_anular(df: pd.DataFrame):
    st.markdown("### ✏️ Editar / Anular movimiento")
    _show_flash()
    if df.empty:
        st.caption("No hay movimientos para editar o anular.")
        return

    incluir_anulados = st.checkbox("🔍 Mostrar también movimientos anulados", value=False)
    df_view = df if incluir_anulados else df[~df["Anulado_bool"]]
    df_view = df_view.sort_values("Fecha_dt", ascending=False).copy()

    if df_view.empty:
        st.caption("No hay movimientos con el filtro actual.")
        return

    df_view["Opción"] = df_view.apply(
        lambda r: f"{r['Fecha']} | {r['Tipo']} | "
                  f"{r['Persona'] or (r['Persona_Origen']+'→'+r['Persona_Destino'])} | "
                  f"{r['Monto_int']} | {r['Detalle'][:30]}"
                  + (" (ANULADO)" if r["Anulado_bool"] else ""),
        axis=1
    )

    opcion = st.selectbox("Selecciona un movimiento", [""] + df_view["Opción"].tolist())
    if not opcion:
        return

    row = df_view[df_view["Opción"] == opcion].iloc[0]
    tipo = row["Tipo"]
    rid = row.get("ID", f"row{int(row.get('_row',0))}")

    # categoría activa para edición
    if "categoria_activa_edit" not in st.session_state:
        st.session_state["categoria_activa_edit"] = row["Categoría"]

    # selector de categoría (solo Ingreso/Gasto)
    if tipo in ["Ingreso","Gasto"]:
        st.markdown("#### Categoría")
        col1, col2 = st.columns([2,1])
        with col1:
            cats_existentes = sorted({c for c in df["Categoría"].unique() if str(c).strip()})
            cat_sel = st.selectbox(
                "Categoría existente",
                [""] + cats_existentes,
                index=cats_existentes.index(row["Categoría"]) if row["Categoría"] in cats_existentes else 0,
                key="edit_cat_exist"
            )
            if cat_sel:
                st.session_state["categoria_activa_edit"] = cat_sel
        with col2:
            nueva_cat_btn = st.checkbox("➕ Nueva categoría", key="edit_btn_new_cat")

        if nueva_cat_btn:
            nueva = st.text_input(
                "Nombre nueva categoría",
                value=st.session_state.get("categoria_activa_edit", ""),
                key="edit_txt_new_cat"
            )
            if nueva:
                st.session_state["categoria_activa_edit"] = nueva
        st.info(f"📌 Categoría activa: **{st.session_state['categoria_activa_edit']}**")

    with st.form("form_editar"):
        fecha = st.date_input("Fecha", value=row["Fecha_dt"].date() if pd.notna(row["Fecha_dt"]) else dt.date.today(), max_value=dt.date.today())

        if tipo in ["Ingreso","Gasto"]:
            tipo_editado = st.selectbox("Tipo de movimiento", ["Ingreso","Gasto"], index=0 if tipo=="Ingreso" else 1, key="edit_tipo")
            persona = st.selectbox("Persona", USUARIOS,
                                   index=USUARIOS.index(row["Persona"]) if row["Persona"] in USUARIOS else 0,
                                   key="edit_persona")
            medio = st.selectbox("Medio de pago", MEDIOS, index=MEDIOS.index(row["Medio"]) if row["Medio"] in MEDIOS else 0, key="edit_medio")
            monto = st.number_input("Monto (CLP)", min_value=0, step=100, value=int(row["Monto_int"]), key="edit_monto")
            detalle = st.text_input("Detalle", row["Detalle"], key="edit_detalle")

            # Claves estables por registro para preservar al alternar "compartido"
            ckey = f"edit_shared_{rid}"
            pkey = f"edit_prop_j_{rid}"
            compartido_default = bool(row["Compartido_bool"])
            propj_default = int(row.get("Proporcion_Javiera", 50))
            st.checkbox("Es un gasto compartido", key=ckey, value=st.session_state.get(ckey, compartido_default))
            if st.session_state.get(ckey, compartido_default) and tipo_editado=="Gasto":
                st.caption("Ajusta las proporciones (la suma debe ser 100%).")
                st.slider(f"Proporción para {NAME_A}", 0, 100, st.session_state.get(pkey, propj_default), step=5, key=pkey)
                st.write(f"Proporción para {NAME_B}: **{100 - st.session_state[pkey]}%**")
            else:
                st.session_state.setdefault(pkey, propj_default)

        elif tipo == "Traspaso":
            st.caption("Tipo: Traspaso (no editable)")
            tipo_editado = "Traspaso"
            col1, col2, col3 = st.columns(3)
            with col1:
                origen = st.selectbox("Persona que entrega", USUARIOS,
                                      index=USUARIOS.index(row["Persona_Origen"]) if row["Persona_Origen"] in USUARIOS else 0,
                                      key="edit_origen")
            with col2:
                destino = st.selectbox("Persona que recibe", USUARIOS,
                                       index=USUARIOS.index(row["Persona_Destino"]) if row["Persona_Destino"] in USUARIOS else 0,
                                       key="edit_destino")
            with col3:
                monto = st.number_input("Monto (CLP)", min_value=0, step=100, value=int(row["Monto_int"]), key="edit_monto_t")
            medio = ""
            detalle = st.text_input("Detalle", row["Detalle"], key="edit_detalle_t")

        editor = st.selectbox("¿Quién edita/anula?", [""] + USUARIOS, key="edit_editor")
        colA, colB = st.columns(2)
        with colA:
            guardar = st.form_submit_button("💾 Guardar cambios")
        with colB:
            anular = st.form_submit_button("🗑️ Anular movimiento")

    if (guardar or anular) and not editor:
        st.error("Debes indicar quién realiza la edición/anulación.")
        return

    if guardar or anular:
        valores = row.to_dict()
        if anular:
            valores["Anulado"] = "TRUE"
            msg = "🗑️ Movimiento anulado."
        else:
            valores["Fecha"] = fecha.strftime("%Y-%m-%d")
            valores["Detalle"] = detalle.strip()
            valores["Monto"] = str(int(monto))
            valores["Medio"] = medio
            msg = "✅ Cambios guardados."

            if tipo_editado in ["Ingreso","Gasto"]:
                valores["Tipo"] = tipo_editado
                valores["Persona"] = persona
                valores["Categoría"] = st.session_state["categoria_activa_edit"].strip()
                ckey = f"edit_shared_{rid}"
                pkey = f"edit_prop_j_{rid}"
                if tipo_editado == "Gasto" and st.session_state.get(ckey, False):
                    valores["Compartido"] = "TRUE"
                    valores["Proporcion_Javiera"] = int(st.session_state.get(pkey, 50))
                    valores["Proporcion_Francis"] = 100 - int(valores["Proporcion_Javiera"])
                else:
                    valores["Compartido"] = ""
                    valores["Proporcion_Javiera"] = ""
                    valores["Proporcion_Francis"] = ""
            elif tipo_editado == "Traspaso":
                valores["Persona_Origen"] = origen
                valores["Persona_Destino"] = destino

            now = pd.Timestamp.now(tz=STGO)
            valores["Last_Modified_At"] = now.strftime("%Y-%m-%d %H:%M:%S")
            valores["Last_Modified_By"] = editor

        _update_row(int(row["_row"]), valores)
        st.session_state[FLASH_KEY] = {"kind":"ok","msg":msg,"record":valores}
        st.cache_data.clear()
        st.rerun()

# =========================================================
# RENDER PRINCIPAL
# =========================================================
def render_dashboard(df: pd.DataFrame):
    col1, col2, col3, col4 = st.columns(4)
    total = int(_calc_saldos_por_persona(df)["Saldo"].sum())
    ingresos = int(df[(df["Tipo"]=="Ingreso") & (~df["Anulado_bool"])]["Monto_int"].sum())
    gastos = int(df[(df["Tipo"]=="Gasto") & (~df["Anulado_bool"])]["Monto_int"].sum())
    n_traspasos = int(len(df[(df["Tipo"]=="Traspaso") & (~df["Anulado_bool"])]))
    with col1: st.metric("Saldo Total", f"$ {total:,}".replace(",",".")) 
    with col2: st.metric("Ingresos", f"$ {ingresos:,}".replace(",",".")) 
    with col3: st.metric("Gastos", f"$ {gastos:,}".replace(",",".")) 
    with col4: st.metric("Traspasos", f"{n_traspasos}")

    saldos = _calc_saldos_por_persona(df)
    st.markdown("#### Saldos actuales")
    st.dataframe(saldos.set_index("Persona"), use_container_width=True)

    st.markdown("#### Detalle Registros")
    # Filtros de tabla
    col1, col2, col3 = st.columns(3)
    with col1:
        persona_filtro = st.selectbox("Filtrar por persona", ["Todos"] + USUARIOS, key="filtro_persona")
    with col2:
        tipo_filtro = st.selectbox("Filtrar por tipo", ["Todos", "Ingreso", "Gasto", "Traspaso"], key="filtro_tipo")
    with col3:
        incluir_anulados = st.checkbox("Mostrar anulados", value=False, key="filtro_anulados")

    df_view = df.copy().sort_values(by="Fecha_dt", ascending=False)
    if persona_filtro != "Todos":
        df_view = df_view[
            (df_view["Persona"] == persona_filtro) |
            (df_view["Persona_Origen"] == persona_filtro) |
            (df_view["Persona_Destino"] == persona_filtro)
        ]
    if tipo_filtro != "Todos":
        df_view = df_view[df_view["Tipo"] == tipo_filtro]
    if not incluir_anulados:
        df_view = df_view[~df_view["Anulado_bool"]]

    # Aplicar filtros globales sidebar
    if st.session_state["vista_persona"] != "Todos":
        p = st.session_state["vista_persona"]
        df_view = df_view[
            (df_view["Persona"] == p) |
            (df_view["Persona_Origen"] == p) |
            (df_view["Persona_Destino"] == p)
        ]
    if st.session_state["vista_medio"] != "Todos":
        df_view = df_view[df_view["Medio"] == st.session_state["vista_medio"]]

    # Vista humanizada
    def mostrar_quien(row):
        if row["Tipo"] == "Traspaso":
            return f"{row['Persona_Origen']} → {row['Persona_Destino']}"
        return row["Persona"]

    view = df_view[[
        "Fecha","Tipo","Persona","Persona_Origen","Persona_Destino",
        "Categoría","Monto_int","Medio","Compartido","Proporcion_Javiera","Proporcion_Francis",
        "Detalle","Anulado"
    ]].copy()
    view["Quién"] = view.apply(mostrar_quien, axis=1)
    view = view[["Fecha","Tipo","Quién","Categoría","Monto_int","Medio","Compartido","Proporcion_Javiera","Proporcion_Francis","Detalle","Anulado"]]
    st.dataframe(view, use_container_width=True)

    # Exportar
    csv = view.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Exportar CSV (filtros aplicados)", csv, "finanzas_export.csv", "text/csv")

def render_estadisticas(df: pd.DataFrame):
    st.markdown("### 📈 Estadísticas")
    df_ok = df[(~df["Anulado_bool"])].copy()

    # Top categorías por persona
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Top categorías – Gastos (Todos)**")
        topcat = (df_ok[df_ok["Tipo"]=="Gasto"]
                  .groupby("Categoría")["Monto_int"].sum().sort_values(ascending=False).head(10))
        st.bar_chart(topcat)

    with col2:
        st.markdown(f"**Gastos por medio**")
        by_medio = (df_ok[df_ok["Tipo"]=="Gasto"]
                    .groupby("Medio")["Monto_int"].sum().sort_values(ascending=False))
        st.bar_chart(by_medio)

    # Evolución mensual de gastos e ingresos
    evo = (df_ok.groupby(["Periodo","Tipo"])["Monto_int"].sum().reset_index())
    pivot = evo.pivot(index="Periodo", columns="Tipo", values="Monto_int").fillna(0)
    st.markdown("**Evolución mensual (Ingreso vs Gasto)**")
    st.line_chart(pivot)

    # Gastos compartidos vs personales
    g_df = df_ok[df_ok["Tipo"]=="Gasto"].copy()
    g_df["TipoGasto"] = g_df["Compartido_bool"].map({True:"Compartido", False:"Personal"})
    por_tipo = g_df.groupby("TipoGasto")["Monto_int"].sum()
    st.markdown("**Gasto compartido vs personal**")
    st.bar_chart(por_tipo)

def render_ajustes(df: pd.DataFrame):
    st.markdown("### ⚖️ Ajustes de gastos compartidos (con proporciones)")
    data = _calc_ajustes_compartidos(df)
    if data["total_compartido"] == 0:
        st.info("No hay gastos compartidos registrados aún.")
        return

    c1, c2, c3 = st.columns(3)
    with c1: st.metric("Total compartido", f"$ {data['total_compartido']:,}".replace(",",".")) 
    with c2: st.metric(f"Debe {USER_A}", f"$ {data['debe'][USER_A]:,}".replace(",",".")) 
    with c3: st.metric(f"Debe {USER_B}", f"$ {data['debe'][USER_B]:,}".replace(",",".")) 

    resumen = pd.DataFrame([
        {"Persona": USER_A, "Pagó": data["pago"][USER_A], "Debía": data["debe"][USER_A], "Balance": data["balances"][USER_A]},
        {"Persona": USER_B, "Pagó": data["pago"][USER_B], "Debía": data["debe"][USER_B], "Balance": data["balances"][USER_B]},
    ])
    st.markdown("**Resumen** (Balance positivo = pagó de más)")
    st.table(resumen.style.format({"Pagó":"$ {:,}".format,"Debía":"$ {:,}".format,"Balance":"$ {:,}".format}))

    st.markdown("**Ajustes propuestos**")
    if data["ajustes"]:
        st.table(pd.DataFrame([{
            "Deudor": a["Deudor"],
            "Acreedor": a["Acreedor"],
            "Monto": f"$ {a['Monto']:,}".replace(",",".")
        } for a in data["ajustes"]]))
    else:
        st.success("🎉 No se requieren ajustes.")

def render_historial(df: pd.DataFrame):
    st.markdown("### 🕓 Historial de edición/anulación")
    hist = df.copy()
    hist = hist[[
        "Fecha","Tipo","Persona","Categoria","Monto_int","Medio","Compartido",
        "Created_At","Created_By","Last_Modified_At","Last_Modified_By","Anulado"
    ] if "Categoria" in hist.columns else [
        "Fecha","Tipo","Persona","Categoría","Monto_int","Medio","Compartido",
        "Created_At","Created_By","Last_Modified_At","Last_Modified_By","Anulado"
    ]]
    hist = hist.sort_values(by=["Last_Modified_At","Created_At"], ascending=False)
    st.dataframe(hist, use_container_width=True)

def render():
    # Botón de actualizar
    col1, col2 = st.columns([3,1])
    with col1:
        st.markdown("### Panel de Control")
    with col2:
        if st.button("🔄 Actualizar"):
            st.cache_data.clear()
            st.success("BD actualizada ✅")
            st.rerun()

    df_raw = _load_finanzas_df()
    df = _normalize_finanzas(df_raw)
    cats_existentes = sorted(df["Categoría"].dropna().unique().tolist())

    tab1, tab2, tab3, tab4 = st.tabs(["📊 Resumen","➕ Registrar / Editar","📈 Estadísticas","⚖️ Ajustes"])

    with tab1:
        _show_flash()
        render_dashboard(df)

    with tab2:
        modo = st.radio("Selecciona modo", ["Registrar","Editar / Anular"], horizontal=True, key="modo_reg")
        if modo=="Registrar":
            _form_registro(cats_existentes)
        else:
            _form_editar_anular(df)

    with tab3:
        render_estadisticas(df)

    with tab4:
        render_ajustes(df)

    # Footer
    st.markdown(
        """
        <hr style="margin-top: 40px; margin-bottom: 10px;">
        <div style="text-align: center; font-size: 13px; color: #666;">
            Desarrollado por <b>Francis</b> –
            <a href="https://www.LivLin.cl" target="_blank">www.LivLin.cl</a><br><br>
            ¿Quieres una aplicación personalizada para tu proyecto u organización?<br>
            <a href="mailto:francis.mason@gmail.com?subject=Desarrollo%20de%20aplicación%20personalizada"
               style="color:#333; text-decoration:none;">✉️ Contáctame</a>
        </div>
        """,
        unsafe_allow_html=True
    )

render()
