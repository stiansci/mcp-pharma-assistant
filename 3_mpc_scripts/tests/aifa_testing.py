# aifa_troubleshooting.py (v2 - con debug approfondito)

import os
import sys
import duckdb
import pandas as pd

# --- CONFIGURAZIONE ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR) 
AIFA_DB_PATH = os.path.join(PROJECT_ROOT, '1_aifa', 'aifa.db')

try:
    from italian_pharma_server import (
        _get_drug_info_by_name,
        _find_drugs_by_ingredient,
        _find_generics,
        _get_active_ingredients_by_aic,
        con
    )
except ImportError as e:
    print(f"ERRORE: Impossibile importare dal file del server...\nDettagli: {e}")
    sys.exit(1)

def print_header(title):
    print("\n" + "="*70)
    print(f"--- {title.upper()} ---")
    print("="*70)

def run_tests():
    print_header("Test 1: Verifica Connessione e File Database")
    # ... (Test 1 invariato) ...
    if not os.path.exists(AIFA_DB_PATH):
        print(f"RISULTATO: FALLITO ❌\nIl file del database non è stato trovato al percorso: {AIFA_DB_PATH}")
        return
    print(f"Percorso database: {AIFA_DB_PATH} ... OK ✓")

    if con is None:
        print("RISULTATO: FALLITO ❌\nLa connessione al database (variabile 'con') non è stata stabilita.")
        return
    print("Connessione al database stabilita ... OK ✓")
    
    # --- NUOVO TEST DI ISPEZIONE ---
    print_header("Test 1.5: Ispezione della Vista 'farmaci_completi'")
    try:
        view_info = con.execute("DESCRIBE farmaci_completi;").fetchdf()
        print("Schema della vista 'farmaci_completi':")
        print(view_info)
        
        view_sample = con.execute("SELECT * FROM farmaci_completi LIMIT 3;").fetchdf()
        print("\nDati di esempio dalla vista 'farmaci_completi':")
        print(view_sample)
        
        if 'azienda' not in view_info['column_name'].tolist():
             print("\nDIAGNOSI: La colonna 'azienda' NON è presente nella vista!")
        else:
             print("\nDIAGNOSI: La colonna 'azienda' È presente nella vista.")

    except Exception as e:
        print(f"RISULTATO: FALLITO ❌\nImpossibile ispezionare la vista 'farmaci_completi': {e}")
        return
    
    print_header("Test 2: Ricerca per Nome Commerciale ('Tachipirina') con DEBUG")
    
    try:
        search_term = "Tachipirina"
        print(f"Eseguo la query per '{search_term}'...")
        # Re-implementiamo la logica qui per il debug
        query = "SELECT * FROM farmaci_completi WHERE lower(denominazione) LIKE ? LIMIT 5;"
        results_df = con.execute(query, [f"%{search_term.lower()}%"]).fetchdf()
        
        if results_df.empty:
            print("RISULTATO: FALLITO ❌\nLa query non ha prodotto risultati.")
        else:
            print("\n--- INIZIO DEBUG DATAFRAME ---")
            print("DataFrame 'results_df' prima della validazione Pydantic:")
            print("Prime 5 righe:")
            print(results_df.head())
            print("\nNomi delle colonne nel DataFrame:")
            print(results_df.columns.tolist())
            print("--- FINE DEBUG DATAFRAME ---\n")
            
            if 'azienda' not in results_df.columns:
                print("DIAGNOSI FINALE: La colonna 'azienda' MANCA nel DataFrame restituito da DuckDB!")
            else:
                print("DIAGNOSI FINALE: La colonna 'azienda' È PRESENTE. Il problema è altrove.")

            # Ora proviamo a chiamare la funzione originale per replicare l'errore
            print("\nChiamo la funzione originale _get_drug_info_by_name per confermare l'errore...")
            _get_drug_info_by_name(search_term)
            print("RISULTATO: SUCCESSO ✓ (Inaspettato, l'errore non si è replicato)")


    except Exception as e:
        print(f"RISULTATO: FALLITO ❌\nLa funzione ha generato un'eccezione (previsto): {e}")

    # ... gli altri test possono essere commentati per ora per focalizzarsi sul problema principale ...
    # print_header("Test 3: ...")
    # print_header("Test 4: ...")
    # print_header("Test 5: ...")


if __name__ == "__main__":
    run_tests()