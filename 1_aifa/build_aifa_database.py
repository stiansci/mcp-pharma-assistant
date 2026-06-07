import pandas as pd
import os
import re
import duckdb
import chardet
from typing import Any

# --- CONFIGURAZIONE ---
DATABASE_NAME = "aifa.db"

# Utilizziamo __file__ per ottenere il la cartella del file
base_dir = os.path.dirname(__file__)
DATA_DIR = os.path.join(base_dir, "../0_raw_files")

FILE_PATHS: dict[str, str] = {
    'farmaci_anagrafica': f"{DATA_DIR}/confezioni.csv",
    'principi_attivi': f"{DATA_DIR}/PA_confezioni.csv",
    'atc': f"{DATA_DIR}/atc.csv",
    'farmaci_carenti': f"{DATA_DIR}/elenco_medicinali_carenti.csv",
    'farmaci_equivalenti': f"{DATA_DIR}/Lista_farmaci_equivalenti.csv",
    'classe_a': f"{DATA_DIR}/Classe_A_per_nome_commerciale_31-05-2025.csv",
    'classe_h': f"{DATA_DIR}/Classe_H_per_nome_commerciale_31-05-2025.csv",
}

def detect_encoding(filepath: str, sample_size: int = 102400) -> str:
    """
    Rileva la codifica di un file leggendo un campione di byte.
        filepath (str): Percorso del file.
        sample_size (int): Numero di byte da leggere per il campionamento.
        
    Returns:
        str: La codifica rilevata (es. 'utf-8', 'latin-1').
    """
    with open(filepath, 'rb') as f:
        raw_data = f.read(sample_size)
        result = chardet.detect(raw_data)
        encoding = result['encoding'] if result['confidence'] > 0.7 else 'latin-1'
        print(f" -> Codifica per '{os.path.basename(filepath)}': {encoding} (confidenza: {result['confidence']:.2f})")
        return encoding

def optimized_read_csv(filepath: str, **kwargs: Any) -> pd.DataFrame:
    """
    Legge un file CSV con rilevamento automatico della codifica e gestione errori.
    
    Args:
        filepath (str): Percorso del file CSV.
        **kwargs: Argomenti aggiuntivi per pd.read_csv.
        
    Returns:
        pd.DataFrame: Il DataFrame caricato.
    """
    encoding = detect_encoding(filepath)
    try:
        return pd.read_csv(filepath, encoding=encoding, sep=';', engine='python', on_bad_lines='warn', **kwargs)
    except Exception as e:
        print(f"Errore irreversibile durante la lettura di '{filepath}': {e}")
        raise

def read_aifa_list_csv(filepath: str, **kwargs: Any) -> pd.DataFrame:
    """
    Legge i file CSV specifici delle liste AIFA (Classe A/H) gestendo intestazioni problematiche.
    
    Args:
        filepath (str): Percorso del file CSV.
        **kwargs: Argomenti aggiuntivi per pd.read_csv.
        
    Returns:
        pd.DataFrame: Il DataFrame pulito.
    """
    encoding = detect_encoding(filepath)
    try:
        with open(filepath, 'r', encoding=encoding) as f:
            header_line = f.readline().strip()
        
        columns = [col.replace('\n', ' ').replace('"', '').strip() for col in header_line.split(';')]
        
        # Lettura del file ignorando l'intestazione problematica
        df = pd.read_csv(filepath, encoding=encoding, sep=';', engine='python',
                         skiprows=1, header=None, on_bad_lines='warn', **kwargs)
        
        # Selezione delle sole colonne attese
        num_expected_columns = len(columns)
        df = df.iloc[:, :num_expected_columns]
        df.columns = columns
        
        print(f" -> Letto '{os.path.basename(filepath)}' con gestione intestazione personalizzata.")
        return df
    except Exception as e:
        print(f"Errore irreversibile in read_aifa_list_csv per '{filepath}': {e}")
        raise

def clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    Pulisce i nomi delle colonne, preservando le lettere accentate italiane e normalizzando i nomi.
    
    Args:
        df (pd.DataFrame): Il DataFrame da pulire.
        
    Returns:
        pd.DataFrame: Il DataFrame con nomi colonne puliti.
    """
    new_columns = {}
    for col in df.columns:
        new_col = str(col).strip().lower()
        # Aggiunta dei caratteri accentati italiani ai caratteri permessi
        new_col = re.sub(r'[^a-z0-9_àèéìòù]+', '_', new_col)
        new_col = new_col.strip('_')
        
        if 'unnamed' in new_col:
            continue
        new_columns[col] = new_col
    df.rename(columns=new_columns, inplace=True)

    rename_map = {'aic': 'codice_aic', 'codice_aic_': 'codice_aic', 'codice': 'codice_aic'}
    for old_name, new_name in rename_map.items():
        if old_name in df.columns:
            df.rename(columns={old_name: new_name}, inplace=True)
            
    return df
    
def clean_price_columns(series: pd.Series) -> pd.Series:
    """
    Pulisce una colonna di prezzi rimuovendo simboli di valuta e convertendo in numerico.
    
    Args:
        series (pd.Series): La colonna da pulire.
        
    Returns:
        pd.Series: La colonna convertita in numerico.
    """
    if series.dtype == 'object':
        series = series.str.replace('€', '', regex=False).str.strip()
        series = series.str.replace(',', '.', regex=False)
        return pd.to_numeric(series, errors='coerce')
    return series

# --- FUNZIONI DI CARICAMENTO E PROCESSING ---

def load_data_to_table(con: duckdb.DuckDBPyConnection, table_name: str, filepath: str, transformations: dict[str, Any]) -> None:
    """
    Carica i dati da un file CSV in una tabella DuckDB applicando trasformazioni.
    
    Args:
        con (duckdb.DuckDBPyConnection): Connessione al database DuckDB.
        table_name (str): Nome della tabella di destinazione.
        filepath (str): Percorso del file CSV.
        transformations (dict[str, Any]): Dizionario con funzioni di lettura e processamento.
    """
    print(f"Inizio il caricamento del file '{filepath}'...")
    reader_func = transformations['reader'] # Funzione di lettura del file
    read_kwargs = transformations.get('read_kwargs', {}) # Parametri aggiuntivi per la lettura del file come skiprows
    
    df = reader_func(filepath, **read_kwargs)
    df = clean_column_names(df)
    
    if 'processing_func' in transformations: # Controlla è previsto un processamento specifico
        df = transformations['processing_func'](df)
        
    con.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM df")
    print(f" -> Tabella '{table_name}' creata/aggiornata con {len(df)} righe.")

def process_farmaci_equivalenti(df: pd.DataFrame) -> pd.DataFrame:
    """
    Processa specificamente il DataFrame dei farmaci equivalenti pulendo le colonne dei prezzi.
    
    Args:
        df (pd.DataFrame): DataFrame dei farmaci equivalenti.
        
    Returns:
        pd.DataFrame: DataFrame processato.
    """
    price_cols = [col for col in df.columns if 'prezzo' in col or 'differenza' in col]
    for col in price_cols:
        df[col] = clean_price_columns(df[col])
    return df

# --- FUNZIONE PRINCIPALE ---

def main() -> None:
    """
    Funzione principale che orchestra la creazione del database AIFA.
    """
    print("--- Inizio Pipeline: Creazione Database AIFA Unificato ---")
    
    if os.path.exists(DATABASE_NAME):
        os.remove(DATABASE_NAME)
        print(f"Database '{DATABASE_NAME}' preesistente rimosso.")

    con = duckdb.connect(DATABASE_NAME)
    
    transform_map = {
        'farmaci_anagrafica': {'reader': optimized_read_csv},
        'principi_attivi': {'reader': optimized_read_csv},
        'atc': {'reader': optimized_read_csv},
        'farmaci_carenti': {'reader': optimized_read_csv, 'read_kwargs': {'skiprows': 2}},
        'farmaci_equivalenti': {'reader': optimized_read_csv, 'processing_func': process_farmaci_equivalenti},
        'classe_a': {'reader': read_aifa_list_csv},
        'classe_h': {'reader': read_aifa_list_csv},
    }

    try:
        for name, transformations in transform_map.items():
            filepath = FILE_PATHS.get(name) # None implicito se non esiste
            if not filepath or not os.path.exists(filepath):
                print(f"ATTENZIONE: File per la tabella '{name}' non trovato. Saltata.")
                continue
            load_data_to_table(con, name, filepath, transformations)

        print("\n--- Creazione Vista Unificata dei Farmaci ---")

        # Recupero le tabelle esistenti in una lista

        existing_tables: list[str] = con.execute("SHOW TABLES").fetchdf()['name'].tolist()
        
        select_clause = "SELECT anag.*,"
        from_clause = " FROM farmaci_anagrafica AS anag"
        joins_clause = ""
        
        # Cerchiamo la classe del farmaco, presumendo la classe C in caso di assenza di una classe valida
        # Usiamo il left join affinché non vengano persi i farmaci di classe C

        case_classe = "CASE "
        if 'classe_a' in existing_tables:
            case_classe += "WHEN a.codice_aic IS NOT NULL THEN 'A' "
            joins_clause += " LEFT JOIN classe_a AS a ON anag.codice_aic = a.codice_aic"
        if 'classe_h' in existing_tables:
            case_classe += "WHEN h.codice_aic IS NOT NULL THEN 'H' "
            joins_clause += " LEFT JOIN classe_h AS h ON anag.codice_aic = h.codice_aic"
        case_classe += """
            WHEN carenti.classe_di_rimborsabilità IS NOT NULL THEN carenti.classe_di_rimborsabilità
            ELSE 'C' 
        END AS classe_rimborsabilita,
        """
        
        case_carenza = """
            CASE
            WHEN carenti.codice_aic IS NOT NULL THEN TRUE
            ELSE FALSE
            END AS is_carente,
            carenti.data_inizio AS data_inizio_carenza,
            carenti.motivazioni AS motivazioni_carenza
        """
        joins_clause += " LEFT JOIN farmaci_carenti AS carenti ON anag.codice_aic = carenti.codice_aic"
        
        final_query = f"CREATE OR REPLACE VIEW farmaci_completi AS {select_clause} {case_classe} {case_carenza} {from_clause} {joins_clause};"
        
        print("Query SQL generata dinamicamente:\n", final_query)
        con.execute(final_query)
        print(" -> Vista 'farmaci_completi' creata con successo.")
        
        print("\nVerifica tabelle e viste create nel database:")
        print(con.execute("SHOW ALL TABLES").fetchdf())
        
        print("\nEsempio di dati dalla vista arricchita:")
        print(con.execute("SELECT * FROM farmaci_completi LIMIT 10;").fetchdf())

    finally:
        con.close()
        print(f"\n--- Pipeline completata. Database '{DATABASE_NAME}' creato e arricchito con successo. ---")

if __name__ == "__main__":
    main()