# aifa_search_debugger.py
#
# Script di troubleshooting focalizzato sulla ricerca per nome commerciale
# per capire perché "Tachipirina" non viene trovata direttamente.

import os
import sys
import duckdb
import pandas as pd

# --- CONFIGURAZIONE ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR) 
AIFA_DB_PATH = os.path.join(PROJECT_ROOT, '1_aifa', 'aifa.db')

# Imposta pandas per mostrare più testo nelle colonne
pd.set_option('display.max_colwidth', 100)

def print_header(title):
    """Funzione helper per stampare titoli chiari."""
    print("\n" + "="*70)
    print(f"--- {title.upper()} ---")
    print("="*70)

def run_debug_searches():
    """Esegue una serie di query di debug sulla vista farmaci_completi."""
    
    print_header("Fase 1: Connessione e verifica della vista")
    
    if not os.path.exists(AIFA_DB_PATH):
        print(f"ERRORE: Database non trovato in {AIFA_DB_PATH}")
        return
        
    try:
        con = duckdb.connect(database=AIFA_DB_PATH, read_only=True)
        print("Connessione al DB... OK ✓")
        
        tables = con.execute("SHOW TABLES").fetchdf()['name'].tolist()
        if 'farmaci_completi' not in tables:
            print("ERRORE: La vista 'farmaci_completi' non esiste. Riesegui la pipeline.")
            return
        print("Vista 'farmaci_completi' trovata... OK ✓")
    except Exception as e:
        print(f"ERRORE durante la connessione al DB: {e}")
        return

    # --- INIZIO DEBUG SULLA RICERCA ---

    print_header("Fase 2: Ricerca con la stessa logica del server")
    
    search_term = "Tachipirina"
    query1 = "SELECT denominazione, codice_aic FROM farmaci_completi WHERE lower(denominazione) LIKE ? LIMIT 5;"
    params1 = [f"%{search_term.lower()}%"]
    
    print(f"Eseguo query: {query1}")
    print(f"Con parametro: {params1}")
    
    results1 = con.execute(query1, params1).fetchdf()
    
    if results1.empty:
        print("\nRISULTATO: FALLITO ❌\nLa query LIKE '%tachipirina%' non ha restituito risultati. Questo conferma il problema.")
    else:
        print("\nRISULTATO: SUCCESSO (Inaspettato) ✓\nLa query ha funzionato. Mostro i risultati:")
        print(results1)

    print_header("Fase 3: Ricerca senza il 'lower()'")
    
    query2 = "SELECT denominazione, codice_aic FROM farmaci_completi WHERE denominazione LIKE ? LIMIT 5;"
    params2 = [f"%{search_term}%"]
    
    print(f"Eseguo query: {query2}")
    print(f"Con parametro: {params2}")
    
    results2 = con.execute(query2, params2).fetchdf()
    
    if results2.empty:
        print("\nRISULTATO: NESSUN RISULTATO.\nLa ricerca case-sensitive non funziona (questo è normale se il DB ha 'TACHIPIRINA').")
    else:
        print("\nRISULTATO: TROVATI RISULTATI.\nInteressante, la ricerca case-sensitive funziona. Mostro i risultati:")
        print(results2)

    print_header("Fase 4: Ricerca di campioni che contengono 'TACHI' per ispezione manuale")

    query3 = "SELECT denominazione, codice_aic FROM farmaci_completi WHERE lower(denominazione) LIKE '%tachi%' LIMIT 10;"
    print(f"Eseguo query: {query3}")
    
    results3 = con.execute(query3).fetchdf()
    
    if results3.empty:
        print("\nRISULTATO: FALLITO ❌\nIncredibilmente, non c'è NESSUN farmaco che contenga 'tachi'. Questo indicherebbe un problema molto serio nei dati di origine (file confezioni.csv).")
    else:
        print("\nRISULTATO: SUCCESSO ✓\nTrovati farmaci contenenti 'tachi'. Ispezioniamo i nomi:")
        print(results3)
        print("\nDIAGNOSI PROBABILE: I nomi nel database potrebbero avere spazi extra, caratteri non visibili o una formattazione diversa da 'Tachipirina'. Confronta i risultati qui sopra con la stringa di ricerca.")

    print_header("Fase 5: Ricerca esatta (case-insensitive) per verifica finale")
    
    query4 = "SELECT denominazione, codice_aic FROM farmaci_completi WHERE lower(denominazione) = 'tachipirina' LIMIT 5;"
    print(f"Eseguo query: {query4}")

    results4 = con.execute(query4).fetchdf()

    if results4.empty:
        print("\nRISULTATO: NESSUN RISULTATO.\nCome previsto, la ricerca esatta non funziona perché i nomi contengono anche la descrizione della confezione.")
    else:
        print("\nRISULTATO: TROVATI RISULTATI (Molto strano).\nLa ricerca esatta funziona, il che contraddice il fallimento della ricerca LIKE.")
        print(results4)

    con.close()
    print("\n\n--- DEBUG COMPLETATO ---")


if __name__ == "__main__":
    run_debug_searches()