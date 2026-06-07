# drugbank_search_debugger.py (v2 - Corretto errore di battitura)

import os
import sys
import polars as pl

# --- CONFIGURAZIONE ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR) 
PROCESSED_DATA_DIR = os.path.join(PROJECT_ROOT, 'processed_data')

def print_header(title):
    """Funzione helper per stampare titoli chiari."""
    print("\n" + "="*70)
    print(f"--- {title.upper()} ---") # <-- CORRETTO
    print("="*70)

def run_drugbank_debug():
    print_header("Fase 1: Caricamento Dati DrugBank")
    try:
        df_drugs = pl.read_parquet(os.path.join(PROCESSED_DATA_DIR, 'drugs.parquet'))
        df_synonyms = pl.read_parquet(os.path.join(PROCESSED_DATA_DIR, 'drug_synonyms.parquet'))
        print(f"Dati caricati: {len(df_drugs)} farmaci, {len(df_synonyms)} sinonimi. OK ✓")
    except Exception as e:
        print(f"ERRORE: Impossibile caricare i file Parquet: {e}")
        sys.exit(1)

    # --- INIZIO DEBUG ---

    print_header("Fase 2: Ricerca per nome principale 'Nirmatrelvir'")
    search_term = "nirmatrelvir"
    print(f"Cerco '{search_term}' nella colonna 'name' del DataFrame principale...")
    
    results1 = df_drugs.filter(pl.col('name').str.to_lowercase() == search_term)
    
    if results1.is_empty():
        print("RISULTATO: Nessuna corrispondenza esatta nel nome principale. ❌")
    else:
        print("RISULTATO: TROVATO! ✓ Il farmaco è presente nel DB principale:")
        print(results1)

    print_header("Fase 3: Ricerca per sinonimo 'Nirmatrelvir'")
    print(f"Cerco '{search_term}' nella colonna 'synonym'...")

    results2 = df_synonyms.filter(pl.col('synonym').str.to_lowercase() == search_term)

    if results2.is_empty():
        print("RISULTATO: Nessuna corrispondenza esatta tra i sinonimi. ❌")
    else:
        print("RISULTATO: TROVATO! ✓ Il nome è presente come sinonimo:")
        print(results2)

    print_header("Fase 4: Ricerca per nome in codice 'PF-07321332'")
    search_code = "pf-07321332"
    print(f"Cerco '{search_code}' tra i sinonimi...")
    
    results3 = df_synonyms.filter(pl.col('synonym').str.to_lowercase() == search_code)

    if results3.is_empty():
        print(f"RISULTATO: Nessuna corrispondenza per il codice '{search_code}'. ❌")
    else:
        print(f"RISULTATO: TROVATO! ✓ Il codice è presente come sinonimo:")
        print(results3)
        # Se lo troviamo, cerchiamo il record principale associato
        drug_id = results3['drugbank_id'][0]
        main_record = df_drugs.filter(pl.col('drugbank_id') == drug_id)
        print("\nRecord principale associato a questo sinonimo:")
        print(main_record)

    print_header("Fase 5: Ricerca parziale con 'contains'")
    partial_term = "nirmatrelvir"
    print(f"Cerco qualsiasi sinonimo che CONTIENE '{partial_term}'...")

    results4 = df_synonyms.filter(pl.col('synonym').str.to_lowercase().str.contains(partial_term))

    if results4.is_empty():
        print("RISULTATO: Fallita anche la ricerca parziale. ❌\nDIAGNOSI: È molto probabile che 'Nirmatrelvir' non sia presente in nessuna forma nel nostro file XML di DrugBank.")
    else:
        print("RISULTATO: TROVATO! ✓ La ricerca parziale ha dato risultati:")
        print(results4)
        print("\nDIAGNOSI: Il farmaco esiste, ma con un nome leggermente diverso (es. con sali, esteri, etc.). La nostra ricerca esatta è troppo restrittiva.")

if __name__ == "__main__":
    run_drugbank_debug()