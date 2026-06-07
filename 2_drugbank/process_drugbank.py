import os
import time
from typing import Optional
from lxml import etree as ET
import polars as pl
from tqdm import tqdm

# --- CONFIGURAZIONE PERCORSI ---
XML_FILE_PATH = os.path.join("0_raw_files", "full database.xml")
OUTPUT_DIR = os.path.join("2_drugbank", "parquet_files")

# File di output
DRUGS_FILE = os.path.join(OUTPUT_DIR, "drugs.parquet")
INTERACTIONS_FILE = os.path.join(OUTPUT_DIR, "drug_interactions.parquet")
SYNONYMS_FILE = os.path.join(OUTPUT_DIR, "drug_synonyms.parquet")
ATC_CODES_FILE = os.path.join(OUTPUT_DIR, "drug_atc_codes.parquet")

# Questo dizionario mappa il prefisso 'db' al namespace XML 'http://www.drugbank.ca'
NS: dict[str, str] = {'db': 'http://www.drugbank.ca'}

def process_drugbank_xml(filepath: str) -> None:
    """
    Parsing ottimizzato di DrugBank XML usando lxml + tuple + Polars.
    Strategia: 'Tuple-based ingestion' per massima velocità e minima RAM.
    """
    start_time = time.time()
    print(f"--- Inizio Pipeline ETL: DrugBank XML -> Parquet ---")
    print(f"    File input: {filepath}")

    if not os.path.exists(filepath):
        raise FileNotFoundError(f"ERRORE: File XML non trovato in: '{filepath}'")

    os.makedirs(OUTPUT_DIR, exist_ok=True) # exist_ok=True evita errori se la cartella esiste già

    # Accumulatori dati (Liste di Tuple)
    drugs_data: list[tuple[str, str]] = []         # (id, name)
    interactions_data: list[tuple[str, Optional[str], Optional[str]]] = []  # (source_id, target_id, description)
    synonyms_data: list[tuple[str, str]] = []      # (id, synonym)
    atc_codes_data: list[tuple[str, str]] = []     # (id, atc_code)
    
    print("Inizio parsing streaming (lxml)...")
    
    # iterparse permette di scorrere l'XML senza caricarlo tutto in RAM;
    # crea un iteratore che si ferma quando raggiunge la fine di un tag 'drug'
    context = ET.iterparse(filepath, events=('end',), tag="{http://www.drugbank.ca}drug")

    # Contatore per fini di logging
    processed_count = 0

    with tqdm(desc="Processing Drugs", unit=" records") as pbar:
        for event, elem in context: # event = 'end', elem = <drug>
            
            # Estrazione dati primari
            drugbank_id = elem.findtext('db:drugbank-id[@primary="true"]', namespaces=NS)
            name = elem.findtext('db:name', namespaces=NS)
            
            # Processiamo solo se i dati essenziali sono presenti
            if drugbank_id and name:
                # 1. Farmaci
                drugs_data.append((drugbank_id, name))
                
                # 2. Interazioni (Sezione critica per performance)
                # Usiamo findall + list comprehension per velocità massima
                interactions = elem.findall('db:drug-interactions/db:drug-interaction', namespaces=NS)
                if interactions:
                    interactions_data.extend([
                        (drugbank_id, 
                         inter.findtext('db:drugbank-id', namespaces=NS), 
                         inter.findtext('db:description', namespaces=NS))
                        for inter in interactions
                    ])

                # 3. Sinonimi
                synonyms = elem.findall('db:synonyms/db:synonym', namespaces=NS)
                if synonyms:
                    synonyms_data.extend([
                        (drugbank_id, syn.text) 
                        for syn in synonyms if syn.text
                    ])

                # 4. Codici ATC
                atc_codes = elem.findall('db:atc-codes/db:atc-code', namespaces=NS)
                if atc_codes:
                    atc_codes_data.extend([
                        (drugbank_id, atc.get('code'))
                        for atc in atc_codes if atc.get('code')
                    ])
                
                processed_count += 1
                pbar.update(1)
            
            # Pulizia memoria XML (Cruciale)
            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]

    del context # Libera il parser XML
    print(f"\nParsing completato. {processed_count} farmaci processati.")
    print("Conversione in Polars DataFrame e salvataggio su disco...")

    # Salvataggio DRUGS
    print(f" -> Salvataggio {DRUGS_FILE}...")
    pl.DataFrame(drugs_data, schema=["drugbank_id", "name"], orient="row") \
      .write_parquet(DRUGS_FILE)

    # Salvataggio INTERACTIONS
    print(f" -> Salvataggio {INTERACTIONS_FILE} ({len(interactions_data)} righe)...")
    pl.DataFrame(interactions_data, schema=["source_drug_id", "target_drug_id", "description"], orient="row") \
      .write_parquet(INTERACTIONS_FILE)

    # Salvataggio SYNONYMS
    print(f" -> Salvataggio {SYNONYMS_FILE}...")
    pl.DataFrame(synonyms_data, schema=["drugbank_id", "synonym"], orient="row") \
      .write_parquet(SYNONYMS_FILE)

    # Salvataggio ATC
    print(f" -> Salvataggio {ATC_CODES_FILE}...")
    pl.DataFrame(atc_codes_data, schema=["drugbank_id", "atc_code"], orient="row") \
      .write_parquet(ATC_CODES_FILE)
    
    end_time = time.time()
    elapsed = end_time - start_time
    print(f"\n--- Pipeline ETL completata con successo in {elapsed:.2f} secondi. ---")

if __name__ == "__main__":
    process_drugbank_xml(XML_FILE_PATH)