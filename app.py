import streamlit as st

st.set_page_config(page_title="Monitoraggio Bovini", layout="wide")
st.title("🚜 Sistema Monitoraggio Bovini 2026")
st.write("Configurazione infrastruttura completata con successo!")

st.sidebar.header("Menu")
st.sidebar.button("Cerca Bovini")

st.info("In attesa di collegamento con il gateway Dragino...")
