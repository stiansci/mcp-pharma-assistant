# validate_aifa_pipeline.py (v2 - con campionamento di 2 righe)

import pandas as pd
import duckdb
import os
import re
import chardet

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_NAME = os.path.join(BASE_DIR, '..', 'aifa.db')
FILES_DIR = os.path.join(BASE_DIR, '..', '..', 'files')
TABLE_NAMES = [
    'farmaci_anagrafica', 'principi_attivi', 'atc', 
    'farmaci_carenti', 'farmaci_equivalenti', 'classe_a', 'classe_h'
]

FILE_PATHS = {
    'farmaci_anagrafica': os.path.join(FILES_DIR, 'confezioni.csv'),
    'principi_attivi': os.path.join(FILES_DIR, 'PA_confezioni.csv'),
    'atc': os.path.join(FILES_DIR, 'atc.csv'),
    'farmaci_carenti': os.path.join(FILES_DIR, 'elenco_medicinali_carenti.csv'),
    'farmaci_equivalenti': os.path.join(FILES_DIR, 'Lista_farmaci_equivalenti.csv'),
    'classe_a': os.path.join(FILES_DIR, 'Classe_A_per_nome_commerciale_31-05-2025.csv'),
    'classe_h': os.path.join(FILES_DIR, 'Classe_H_per_nome_commerciale_31-05-2025.csv'),
}

def detect_encoding(filepath, sample_size=102400):
    with open(filepath, 'rb') as f:
        raw_data = f.read(sample_size)
        result = chardet.detect(raw_data)
        return result['encoding']

def robust_read_csv(filepath, **kwargs):
    encoding = detect_encoding(filepath)
    separators_to_try = [',', ';']
    for sep in separators_to_try:
        try:
            return pd.read_csv(filepath, encoding=encoding, sep=sep, **kwargs)
        except (pd.errors.ParserError, UnicodeDecodeError):
            continue
    raise IOError(f"Impossibile leggere il file '{filepath}'.")

def clean_column_names(df):
    new_columns = {}
    for col in df.columns:
        original_col = col
        new_col = col.strip().lower()
        new_col = re.sub(r'[\s\.]+', '_', new_col)
        if 'medicinali carenti' in new_col:
            new_col = 'nome_medicinale'
        if 'unnamed:' in new_col:
            continue
        new_columns[original_col] = new_col
    df.rename(columns=new_columns, inplace=True)
    return df

# --- FUNZIONE DI VALIDAZIONE (AGGIORNATA) ---

def validate_data(con, num_samples=2): # <-- Aggiunto parametro per il numero di campioni
    """
    Esegue una validazione a campione confrontando N righe casuali dal file CSV
    originale con le righe corrispondenti nel database DuckDB.
    """
    print("\n" + "="*80)
    print(f"INIZIO VALIDAZIONE A CAMPIONE (campionando {num_samples} righe per tabella)")
    print("="*80)

    id_columns = {
        'farmaci_anagrafica': 'codice_aic',
        'principi_attivi': 'codice_aic',
        'atc': 'codice_atc',
        'farmaci_carenti': 'codice_aic',
        'farmaci_equivalenti': 'aic'
    }

    for table_name in TABLE_NAMES:
        if table_name not in id_columns:
            continue

        print(f"\n{'='*25} Validazione per la tabella: '{table_name}' {'='*25}")
        
        filepath = FILE_PATHS[table_name]
        id_col_cleaned = id_columns[table_name]
        
        # Carica il CSV originale
        kwargs = {'skiprows': 2} if table_name == 'farmaci_carenti' else {}
        original_df = robust_read_csv(filepath, **kwargs)
        
        # Trova il nome originale della colonna ID prima della pulizia
        temp_df_cleaned = original_df.copy()
        clean_column_names(temp_df_cleaned)
        original_id_col = next((orig for orig, clean in zip(original_df.columns, temp_df_cleaned.columns) if clean == id_col_cleaned), None)
        
        if not original_id_col:
            print(f"ERRORE: Impossibile trovare la colonna ID originale per '{id_col_cleaned}'")
            continue
        
        # Seleziona N righe casuali
        # Assicurati di avere abbastanza righe uniche da cui campionare
        sample_size = min(num_samples, len(original_df.dropna(subset=[original_id_col])))
        random_samples_original = original_df.dropna(subset=[original_id_col]).sample(sample_size)

        for i, (_, random_row_original) in enumerate(random_samples_original.iterrows()):
            print(f"\n--- Campione #{i+1} ---")
            id_value = random_row_original[original_id_col]

            print(f"Riga casuale selezionata dal CSV '{os.path.basename(filepath)}' (ID: {id_value}):")
            print(pd.DataFrame([random_row_original]).to_string())
            
            print(f"\nRiga corrispondente letta dal database DuckDB (tabella: '{table_name}'):")
            try:
                query_id = f"'{id_value}'" if isinstance(id_value, str) else id_value
                query = f"SELECT * FROM {table_name} WHERE {id_col_cleaned} = {query_id}"
                
                db_row = con.execute(query).fetchdf()
                
                if db_row.empty:
                    print("Riga non trovata nel database.")
                else:
                    print(db_row.to_string())
            except duckdb.Error as e:
                print(f"Errore durante la query al database: {e}")

# --- FUNZIONE PRINCIPALE ---

def main():
    if not os.path.exists(DATABASE_NAME):
        print(f"Database '{DATABASE_NAME}' non trovato. Esegui prima 'build_aifa_database.py'.")
        return
        
    con = duckdb.connect(DATABASE_NAME, read_only=True)
    try:
        validate_data(con, num_samples=2) # <-- Specifichiamo 2 campioni
    finally:
        con.close()
        print("\n" + "="*80)
        print("VALIDAZIONE COMPLETATA")
        print("="*80)

if __name__ == "__main__":
    main()